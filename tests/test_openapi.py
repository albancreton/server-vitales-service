from __future__ import annotations

import json
import threading
import urllib.request

import pytest

import vitalsd
from helpers import GPU_SAMPLE_KEYS

from vitalsd.collectors import probe_all
from vitalsd.openapi import DOCUMENT
from vitalsd.server import VitalsServer
from vitalsd.state import State


@pytest.fixture()
def server():
    srv = VitalsServer(("127.0.0.1", 0), State([], host="testhost"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_openapi_endpoint(server):
    port = server.server_address[1]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/openapi.json") as r:
        assert r.status == 200
        assert r.headers["Content-Type"] == "application/json"
        assert r.headers["Access-Control-Allow-Origin"] == "*"
        assert r.headers["Cache-Control"] == "no-store"
        doc = json.loads(r.read())
    assert doc == DOCUMENT


def test_document_shape():
    assert DOCUMENT["openapi"].startswith("3.1")
    assert DOCUMENT["info"]["version"] == vitalsd.__version__
    assert set(DOCUMENT["paths"]) == {
        "/health", "/info", "/metrics", "/stream", "/openapi.json",
        "/models", "/models/unload"}


def test_tick_schema_covers_real_payload():
    tick = State(probe_all()).tick()
    declared = set(DOCUMENT["components"]["schemas"]["TickPayload"]["properties"])
    assert set(tick) <= declared, f"undeclared keys: {set(tick) - declared}"
    gpu_declared = set(DOCUMENT["components"]["schemas"]["GpuSample"]["properties"])
    assert GPU_SAMPLE_KEYS <= gpu_declared, f"missing: {GPU_SAMPLE_KEYS - gpu_declared}"


def test_info_schema_covers_real_payload():
    info = State(probe_all()).info_payload()
    declared = set(DOCUMENT["components"]["schemas"]["InfoPayload"]["properties"])
    assert set(info) <= declared, f"undeclared keys: {set(info) - declared}"


def test_models_schema_covers_real_payload():
    from vitalsd.models import Models
    payload = State([], models=Models([])).models_payload()
    schemas = DOCUMENT["components"]["schemas"]
    assert set(payload) == set(schemas["ModelsPayload"]["properties"])
