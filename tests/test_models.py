from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from helpers import write

from vitalsd import docker, models
from vitalsd.server import VitalsServer
from vitalsd.state import State

CID = "a" * 64


class FakeHTTP:
    """Stands in for models.http_json: routes (method, url) to canned bodies."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, timeout=None):
        self.calls.append((method, url))
        body = self.routes.get((method, url))
        if isinstance(body, Exception):
            raise body
        if body is None:
            raise RuntimeError(f"{method} {url}: HTTP 404")
        return body


class FakeNames:
    def __init__(self, names):
        self.names = names

    def get(self, cid):
        return self.names.get(cid)


@pytest.fixture()
def fake_http(monkeypatch):
    def install(routes):
        fake = FakeHTTP(routes)
        monkeypatch.setattr(models, "http_json", fake)
        return fake
    return install


@pytest.fixture()
def restarts(monkeypatch):
    calls = []
    monkeypatch.setattr(docker, "restart", lambda c, **k: calls.append(c))
    return calls


def swap():
    return models.LlamaSwap({"id": "llama-swap", "url": "http://swap/", "container": "llama-swap"})


def comfy():
    return models.ComfyUI({"id": "comfyui", "url": "http://comfy", "container": "comfyui"})


def fourfold():
    return models.Fourfold({"id": "fourfold", "url": "http://ff"})


# ---------- adapters ----------

def test_llamaswap_list_and_unload(fake_http):
    http = fake_http({
        ("GET", "http://swap/running"): {"running": [{"model": "qwen", "name": "Qwen 3", "state": "ready"}]},
        ("POST", "http://swap/api/models/unload/qwen%2Fa"): "OK",
        ("POST", "http://swap/api/models/unload"): "OK",
    })
    assert swap().list() == [{"id": "qwen", "name": "Qwen 3", "state": "ready", "vram_bytes": None}]
    assert swap().unload("qwen/a", False) == "unloaded qwen/a"
    assert swap().unload(None, False) == "unloaded all"
    assert ("POST", "http://swap/api/models/unload") in http.calls


def test_comfy_lists_plugin_models(fake_http):
    fake_http({("GET", "http://comfy/vitals/models"): {"models": [
        {"name": "flux1-dev.safetensors", "type": "Flux", "loaded_bytes": 10, "size_bytes": 20}]}})
    assert comfy().list() == [{"id": "flux1-dev.safetensors", "name": "flux1-dev.safetensors",
                               "state": "ready", "vram_bytes": 10, "size_bytes": 20, "type": "Flux"}]


def test_comfy_without_plugin_lists_nothing(fake_http):
    fake_http({})
    assert comfy().list() == []


def test_comfy_unload_restarts_when_idle(fake_http, restarts):
    fake_http({("GET", "http://comfy/queue"): {"queue_running": [], "queue_pending": []}})
    assert comfy().unload(None, False) == "restarted comfyui"
    assert restarts == ["comfyui"]


def test_comfy_unload_refuses_when_busy_unless_forced(fake_http, restarts):
    http = fake_http({("GET", "http://comfy/queue"): {"queue_running": [["x"]], "queue_pending": []}})
    with pytest.raises(models.Busy):
        comfy().unload(None, False)
    assert restarts == []
    comfy().unload(None, True)
    assert restarts == ["comfyui"]
    assert http.calls.count(("GET", "http://comfy/queue")) == 1  # force skips the check


def test_comfy_rejects_single_model_unload(fake_http, restarts):
    with pytest.raises(models.BadRequest):
        comfy().unload("flux", False)


def test_comfy_requires_container():
    with pytest.raises(ValueError):
        models.ComfyUI({"id": "c", "url": "http://c"})


def test_fourfold(fake_http):
    fake_http({("GET", "http://ff/api/health"): {"ok": True, "loaded": True},
               ("POST", "http://ff/api/unload"): {"ok": True}})
    assert [m["id"] for m in fourfold().list()] == ["RealESRGAN_x4plus"]
    assert fourfold().unload(None, False) == "unloaded RealESRGAN_x4plus"


# ---------- registry ----------

def test_snapshot_attributes_processes_and_isolates_failures(fake_http, tmp_path):
    write(tmp_path, "proc/100/cgroup", f"0::/system.slice/docker-{CID}.scope")
    write(tmp_path, "proc/200/cgroup", "0::/user.slice/user-1000.slice")
    fake_http({("GET", "http://swap/running"): RuntimeError("connection refused")})
    reg = models.Models([swap(), comfy()], root=str(tmp_path),
                        names=FakeNames({CID: "comfyui"}))
    reg.services[1].list = lambda: []
    snap = reg.snapshot([{"pid": 100, "mem_bytes": 1000, "name": "python"},
                         {"pid": 200, "mem_bytes": 50, "name": "Xorg"}])
    swap_e, comfy_e = snap["services"]
    assert swap_e["ok"] is False and "refused" in swap_e["error"]
    assert comfy_e["ok"] is True and comfy_e["vram_bytes"] == 1000
    assert snap["other"] == [{"pid": 200, "name": "Xorg", "container": None, "mem_bytes": 50}]


def test_unload_statuses(fake_http, restarts):
    fake_http({("POST", "http://swap/api/models/unload"): "OK",
               ("GET", "http://comfy/queue"): {"queue_running": [], "queue_pending": [["p"]]}})
    reg = models.Models([swap(), comfy()])
    assert reg.unload("nope")[0] == 404
    assert reg.unload("*", model="x")[0] == 400
    status, results = reg.unload("*")
    assert status == 409
    assert [r["ok"] for r in results] == [True, False]  # swap still unloaded


def test_token():
    assert models.Models([]).authorized(None)
    reg = models.Models([], token="s3cret")
    assert reg.authorized("Bearer s3cret")
    assert not reg.authorized("Bearer nope")
    assert not reg.authorized(None)


# ---------- config ----------

def test_load_missing_file_is_off(tmp_path):
    assert models.load(str(tmp_path / "none.toml")) == (None, None)


def test_load_config(tmp_path):
    p = write(tmp_path, "m.toml", '''
token = "t"
[[service]]
id = "llama-swap"
kind = "llamaswap"
url = "http://127.0.0.1:11343"
[[service]]
id = "comfyui"
kind = "comfyui"
url = "http://127.0.0.1:8188"
container = "comfyui"
''')
    reg, err = models.load(p)
    assert err is None
    assert [s.kind for s in reg.services] == ["llamaswap", "comfyui"]
    assert reg.token == "t"


@pytest.mark.parametrize("body, needle", [
    ('[[service]]\nid="x"\nkind="ollama"\nurl="u"', "unknown kind"),
    ('[[service]]\nid="x"\nkind="llamaswap"', "missing 'url'"),
    ('[[service]]\nid="x"\nkind="llamaswap"\nurl="u"\n[[service]]\nid="x"\nkind="fourfold"\nurl="u"', "unique"),
    ("not toml [", "m.toml"),
])
def test_load_config_errors(tmp_path, body, needle):
    reg, err = models.load(write(tmp_path, "m.toml", body))
    assert reg is None and needle in err


# ---------- HTTP ----------

@pytest.fixture()
def server(fake_http):
    fake_http({("GET", "http://swap/running"): {"running": []},
               ("POST", "http://swap/api/models/unload/qwen"): "OK"})
    reg = models.Models([swap()], token="tok", names=FakeNames({}))
    srv = VitalsServer(("127.0.0.1", 0), State([], host="testhost", models=reg))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _req(srv, method, path, body=None, headers=None):
    port = srv.server_address[1]
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), e.headers


JSON_AUTH = {"Content-Type": "application/json", "Authorization": "Bearer tok"}


def test_get_models(server):
    status, body, _ = _req(server, "GET", "/models")
    assert status == 200
    assert body["host"] == "testhost"
    assert body["services"][0]["id"] == "llama-swap"


def test_info_advertises_models(server):
    _, body, _ = _req(server, "GET", "/info")
    assert "models" in body["capabilities"]


def test_post_unload(server):
    status, body, headers = _req(server, "POST", "/models/unload",
                                 {"service": "llama-swap", "model": "qwen"}, JSON_AUTH)
    assert status == 200
    assert body["results"] == [{"service": "llama-swap", "ok": True, "action": "unloaded qwen"}]
    assert headers["Access-Control-Allow-Origin"] is None


def test_post_unload_guards(server):
    body = {"service": "llama-swap"}
    assert _req(server, "POST", "/models/unload", body,
                {"Content-Type": "application/json"})[0] == 401
    assert _req(server, "POST", "/models/unload", body,
                {"Authorization": "Bearer tok", "Content-Type": "text/plain"})[0] == 415
    assert _req(server, "POST", "/models/unload", {"model": "x"}, JSON_AUTH)[0] == 400
    assert _req(server, "POST", "/nope", body, JSON_AUTH)[0] == 404


def test_models_404_when_not_configured():
    srv = VitalsServer(("127.0.0.1", 0), State([], host="h"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert _req(srv, "GET", "/models")[0] == 404
        assert _req(srv, "POST", "/models/unload", {"service": "x"},
                    {"Content-Type": "application/json"})[0] == 404
    finally:
        srv.shutdown()
        srv.server_close()
