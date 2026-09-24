"""Minimal Docker Engine API client over the unix socket (stdlib only).

Used by the models layer to attribute GPU processes to containers and to
restart a container as a service's unload action.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import threading
import time

SOCKET = "/var/run/docker.sock"

# cgroup v2: ".../docker-<64 hex>.scope"; cgroup v1: ".../docker/<64 hex>".
_CID = re.compile(r"(?:docker-|docker/)([0-9a-f]{64})")


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def request(method: str, path: str, *, sock: str = SOCKET,
            timeout: float = 5.0) -> tuple[int, object]:
    conn = _UnixConnection(sock, timeout)
    try:
        conn.request(method, path, headers={"Host": "docker"})
        resp = conn.getresponse()
        raw = resp.read()
    finally:
        conn.close()
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = raw.decode("utf-8", "replace")
    return resp.status, body


def restart(container: str, *, sock: str = SOCKET, stop_timeout: int = 10) -> None:
    status, body = request("POST", f"/containers/{container}/restart?t={stop_timeout}",
                           sock=sock, timeout=stop_timeout + 30)
    if status != 204:
        msg = body.get("message") if isinstance(body, dict) else body
        raise RuntimeError(f"docker restart {container}: HTTP {status} {msg or ''}".strip())


def container_id_of(pid: int, root: str = "/") -> str | None:
    """Container id owning a host pid, from its cgroup path; None if not containerized."""
    try:
        with open(os.path.join(root, f"proc/{pid}/cgroup"), "rb") as f:
            m = _CID.search(f.read().decode("utf-8", "replace"))
    except OSError:
        return None
    return m.group(1) if m else None


class Names:
    """Container id -> name, cached (names only change on recreate)."""
    TTL = 60.0

    def __init__(self, sock: str = SOCKET):
        self.sock = sock
        self._cache: dict[str, tuple[str | None, float]] = {}
        self._lock = threading.Lock()

    def get(self, cid: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(cid)
            if hit and now - hit[1] < self.TTL:
                return hit[0]
        try:
            status, body = request("GET", f"/containers/{cid}/json", sock=self.sock, timeout=2.0)
            name = body["Name"].lstrip("/") if status == 200 and isinstance(body, dict) else None
        except (OSError, KeyError, http.client.HTTPException):
            name = None
        with self._lock:
            self._cache[cid] = (name, now)
        return name
