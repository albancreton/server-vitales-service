from __future__ import annotations

import http.client
import json
import threading
import urllib.request

import pytest

from vitalsd.server import VitalsServer
from vitalsd.state import State


class FakeCollector:
    name = "fake"

    def static_info(self):
        return {"gpus": [{"index": 0, "vendor": "fake"}]}

    def sample(self):
        return {"gpus": [{"index": 0, "util_gpu_pct": 5}]}


@pytest.fixture()
def server():
    srv = VitalsServer(("127.0.0.1", 0), State([FakeCollector()], host="testhost"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _get(srv, path):
    port = srv.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
        return r.status, json.loads(r.read())


def test_health(server):
    status, body = _get(server, "/health")
    assert status == 200
    assert body["ok"] is True
    assert body["uptime_s"] >= 0


def test_info(server):
    _, body = _get(server, "/info")
    assert body["schema"] == 1
    assert body["host"] == "testhost"
    assert body["capabilities"] == ["fake"]


def test_metrics(server):
    _, body = _get(server, "/metrics")
    assert body["gpus"][0]["util_gpu_pct"] == 5


def test_404(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(server, "/nope")
    assert e.value.code == 404


def test_stream_sends_info_then_ticks(server):
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/stream?hz=10")
    resp = conn.getresponse()
    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/event-stream"
    buf = b""
    while buf.count(b"\n\n") < 2:
        chunk = resp.read1(4096)
        if not chunk:
            break
        buf += chunk
    conn.close()
    events = buf.split(b"\n\n")
    assert events[0].startswith(b"event: info\ndata: ")
    assert events[1].startswith(b"event: tick\ndata: ")
    tick = json.loads(events[1].split(b"\ndata: ", 1)[1])
    assert tick["gpus"][0]["util_gpu_pct"] == 5
