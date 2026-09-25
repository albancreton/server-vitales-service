"""Loaded-model inventory and unload across model-serving services.

Opt-in per host via a TOML config (default /etc/vitalsd/models.toml; absent
means the feature is off). Each [[service]] names an adapter kind that knows
how to list what that service holds resident and how to unload it:

    token = "..."            # optional: POST /models/unload then requires
                             # "Authorization: Bearer <token>"

    [[service]]
    id = "llama-swap"
    kind = "llamaswap"
    url = "http://127.0.0.1:11343"
    container = "llama-swap" # optional: attributes GPU processes to it

GPU processes (NVML) are attributed to services through their container;
anything unclaimed is reported under "other" so nothing holding VRAM hides.
"""
from __future__ import annotations

import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import docker

DEFAULT_CONFIG = "/etc/vitalsd/models.toml"
HTTP_TIMEOUT = 3.0


class Busy(Exception):
    """The service is doing work an unload would destroy (HTTP 409)."""


class BadRequest(Exception):
    """The unload request doesn't fit the service (HTTP 400)."""


def http_json(method: str, url: str, timeout: float = HTTP_TIMEOUT):
    req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url}: HTTP {e.code}") from None
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return raw.decode("utf-8", "replace")


class Adapter:
    kind = ""
    # "model": unload() accepts a model id; "service": all-or-nothing.
    granularity = "model"

    def __init__(self, cfg: dict):
        self.id = cfg["id"]
        self.url = cfg["url"].rstrip("/")
        self.container = cfg.get("container")

    def list(self) -> list[dict]:
        raise NotImplementedError

    def unload(self, model: str | None, force: bool) -> str:
        """Unload one model (or everything when None); returns the action taken."""
        raise NotImplementedError


class LlamaSwap(Adapter):
    kind = "llamaswap"

    def list(self):
        body = http_json("GET", f"{self.url}/running")
        return [{"id": r["model"], "name": r.get("name") or r["model"],
                 "state": r.get("state", "ready"), "vram_bytes": None}
                for r in (body or {}).get("running", [])]

    def unload(self, model, force):
        if model is None:
            http_json("POST", f"{self.url}/api/models/unload")
            return "unloaded all"
        http_json("POST", f"{self.url}/api/models/unload/{urllib.parse.quote(model, safe='')}")
        return f"unloaded {model}"


class ComfyUI(Adapter):
    """Listing needs the comfy-vitals custom node (GET /vitals/models).

    Unloading restarts the container: Comfy keeps its CUDA context and
    allocator cache after /free, a restart returns every byte. Refused while
    a prompt is running or queued unless forced.
    """
    kind = "comfyui"
    granularity = "service"

    def __init__(self, cfg):
        super().__init__(cfg)
        if not self.container:
            raise ValueError(f"service {self.id}: comfyui needs 'container' (unload restarts it)")

    def list(self):
        try:
            body = http_json("GET", f"{self.url}/vitals/models")
        except RuntimeError as e:
            if "HTTP 404" in str(e):
                return []  # plugin not installed: VRAM still shows via processes
            raise
        # state: "ready", or "loading" while the running prompt brings it in.
        return [{"id": m["name"], "name": m["name"], "state": m.get("state", "ready"),
                 "vram_bytes": m.get("loaded_bytes"), "size_bytes": m.get("size_bytes"),
                 "type": m.get("type")}
                for m in (body or {}).get("models", [])]

    def unload(self, model, force):
        if model is not None:
            raise BadRequest(f"{self.id} unloads all-or-nothing; omit 'model'")
        if not force:
            q = http_json("GET", f"{self.url}/queue") or {}
            n = len(q.get("queue_running", [])) + len(q.get("queue_pending", []))
            if n:
                raise Busy(f"{self.id} has {n} prompt(s) running or queued; pass force to restart anyway")
        docker.restart(self.container)
        return f"restarted {self.container}"


class Fourfold(Adapter):
    kind = "fourfold"
    granularity = "service"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.model = cfg.get("model", "RealESRGAN_x4plus")

    def list(self):
        body = http_json("GET", f"{self.url}/api/health") or {}
        if not body.get("loaded"):
            return []
        return [{"id": self.model, "name": self.model, "state": "ready", "vram_bytes": None}]

    def unload(self, model, force):
        if model is not None and model != self.model:
            raise BadRequest(f"{self.id} only holds {self.model}")
        http_json("POST", f"{self.url}/api/unload")
        return f"unloaded {self.model}"


KINDS = {cls.kind: cls for cls in (LlamaSwap, ComfyUI, Fourfold)}


class Models:
    def __init__(self, services: list[Adapter], token: str | None = None,
                 root: str = "/", names: docker.Names | None = None):
        self.services = services
        self.token = token or None
        self.root = root
        self.names = names or docker.Names()

    def authorized(self, header: str | None) -> bool:
        if self.token is None:
            return True
        expected = f"Bearer {self.token}"
        return header is not None and hmac.compare_digest(header.encode(), expected.encode())

    def snapshot(self, gpu_procs: list[dict]) -> dict:
        with ThreadPoolExecutor(max_workers=max(1, len(self.services))) as ex:
            futures = [ex.submit(s.list) for s in self.services]
        services = []
        by_container = {}
        for svc, fut in zip(self.services, futures):
            entry = {"id": svc.id, "kind": svc.kind, "container": svc.container,
                     "granularity": svc.granularity, "ok": True, "error": None,
                     "vram_bytes": None, "models": []}
            try:
                entry["models"] = fut.result()
            except Exception as e:  # one dead service must not hide the others
                entry["ok"], entry["error"] = False, str(e)
            services.append(entry)
            if svc.container:
                by_container[svc.container] = entry

        other = []
        for p in gpu_procs:
            cid = docker.container_id_of(p["pid"], self.root)
            cname = self.names.get(cid) if cid else None
            owner = by_container.get(cname) if cname else None
            if owner is not None:
                if isinstance(p.get("mem_bytes"), int):
                    owner["vram_bytes"] = (owner["vram_bytes"] or 0) + p["mem_bytes"]
            else:
                other.append({"pid": p["pid"], "name": p.get("name"),
                              "container": cname, "mem_bytes": p.get("mem_bytes")})
        return {"ts": time.time(), "services": services, "other": other}

    def unload(self, service: str, model: str | None = None, force: bool = False):
        """Returns (http_status, results). service "*" unloads every service."""
        targets = self.services if service == "*" else [s for s in self.services if s.id == service]
        if not targets:
            return 404, [{"service": service, "ok": False, "error": "unknown service"}]
        if service == "*" and model is not None:
            return 400, [{"service": service, "ok": False, "error": "'model' needs a single service"}]
        results, status = [], 200
        for svc in targets:
            try:
                results.append({"service": svc.id, "ok": True, "action": svc.unload(model, force)})
                continue
            except Busy as e:
                code, err = 409, str(e)
            except BadRequest as e:
                code, err = 400, str(e)
            except Exception as e:
                code, err = 502, str(e)
            results.append({"service": svc.id, "ok": False, "error": err})
            status = status if status != 200 else code
        return status, results


def load(path: str = DEFAULT_CONFIG) -> tuple[Models | None, str | None]:
    """(models, error). A missing file means the feature is off, not an error."""
    try:
        import tomllib
    except ImportError:
        return None, "models config needs Python 3.11+ (tomllib)"
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except FileNotFoundError:
        return None, None
    except (OSError, tomllib.TOMLDecodeError) as e:
        return None, f"{path}: {e}"
    try:
        services = []
        for s in cfg.get("service", []):
            cls = KINDS.get(s.get("kind"))
            if cls is None:
                raise ValueError(f"service {s.get('id')!r}: unknown kind {s.get('kind')!r} "
                                 f"(known: {', '.join(KINDS)})")
            services.append(cls(s))
        ids = [s.id for s in services]
        if len(set(ids)) != len(ids) or "*" in ids:
            raise ValueError("service ids must be unique and not '*'")
    except KeyError as e:
        return None, f"{path}: a [[service]] is missing {e}"
    except ValueError as e:
        return None, f"{path}: {e}"
    return Models(services, token=cfg.get("token")), None
