"""Shared HTTP + SSE layer (same contract as the legacy daemons)."""
from __future__ import annotations

import json
import socketserver
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from . import openapi


class Handler(BaseHTTPRequestHandler):
    server_version = "vitalsd/1.0"
    # Socket timeout: unstick SSE writes to silently-dead clients.
    timeout = 30

    @property
    def state(self):
        return self.server.state

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{time.strftime('%H:%M:%S')} {fmt % args}\n")

    def _send_json(self, payload: dict, status: int = 200, cors: bool = True):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/health":
            self._send_json({"ok": True, "uptime_s": time.time() - self.state.started_at})
        elif url.path == "/info":
            self._send_json(self.state.info_payload())
        elif url.path == "/metrics":
            self._send_json(self.state.tick())
        elif url.path == "/stream":
            self._stream(url)
        elif url.path == "/openapi.json":
            self._send_json(openapi.DOCUMENT)
        elif url.path == "/models":
            if self.state.models is None:
                self._send_json({"error": "models not configured on this host"}, 404)
            else:
                self._send_json(self.state.models_payload())
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        # The only mutating route. No CORS header, and a JSON content type is
        # required: a cross-origin page can't send that without a preflight,
        # which fails here — so browsers can't fire unloads even without a token.
        url = urlparse(self.path)
        models = self.state.models
        if url.path != "/models/unload" or models is None:
            self._send_json({"error": "not found"}, 404, cors=False)
            return
        if not models.authorized(self.headers.get("Authorization")):
            self._send_json({"error": "unauthorized"}, 401, cors=False)
            return
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype != "application/json":
            self._send_json({"error": "Content-Type must be application/json"}, 415, cors=False)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
            service = req["service"]
            model = req.get("model")
            force = bool(req.get("force", False))
            if not isinstance(service, str) or not isinstance(model, (str, type(None))):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            self._send_json({"error": 'body must be {"service": str, "model"?: str, "force"?: bool}'},
                            400, cors=False)
            return
        status, results = models.unload(service, model, force)
        self._send_json({"results": results}, status, cors=False)

    def _stream(self, url):
        try:
            hz = float(parse_qs(url.query).get("hz", ["1"])[0])
        except ValueError:
            hz = 1.0
        hz = max(0.1, min(hz, 10.0))
        interval = 1.0 / hz
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self._sse("info", self.state.info_payload())
            next_t = time.monotonic()
            while True:
                self._sse("tick", self.state.tick())
                next_t += interval
                sleep = next_t - time.monotonic()
                if sleep > 0:
                    time.sleep(sleep)
                else:
                    next_t = time.monotonic()  # fell behind, resync
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def _sse(self, event: str, data: dict):
        msg = f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
        self.wfile.write(msg.encode())
        self.wfile.flush()


class VitalsServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, state):
        self.state = state
        super().__init__(addr, Handler)
