"""State: owns the probed collectors and builds /info and tick payloads."""
from __future__ import annotations

import platform
import socket
import time

from . import __version__

SCHEMA = 1


def merge(dst: dict, src: dict) -> dict:
    """Deep-merge src into dst: dicts merge recursively, lists concatenate."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        elif isinstance(v, list) and isinstance(dst.get(k), list):
            dst[k].extend(v)
        else:
            dst[k] = v
    return dst


class State:
    def __init__(self, collectors: list, host: str | None = None,
                 models=None, models_error: str | None = None):
        self.collectors = collectors
        self.host = host or socket.gethostname()
        self.started_at = time.time()
        self.models = models  # vitalsd.models.Models, or None when not configured
        self.models_error = models_error

    def _collect(self, payload: dict, method: str) -> dict:
        for c in self.collectors:
            try:
                merge(payload, getattr(c, method)())
            except Exception as e:  # a collector must never kill the daemon
                merge(payload, {"errors": {c.name: str(e)}})
        return payload

    def info_payload(self) -> dict:
        payload = {
            "schema": SCHEMA,
            "host": self.host,
            "started_at": self.started_at,
            "version": __version__,
            "platform": {
                "machine": platform.machine(),
                "kernel": platform.release(),
                "os": platform.platform(),
            },
            "capabilities": [c.name for c in self.collectors]
                            + (["models"] if self.models else []),
        }
        if self.models_error:
            payload["errors"] = {"models": self.models_error}
        return self._collect(payload, "static_info")

    def gpu_processes(self) -> list[dict]:
        procs = []
        for c in self.collectors:
            if c.name.startswith("gpu."):
                try:
                    for g in c.sample().get("gpus", []):
                        procs.extend(g.get("processes", []))
                except Exception:
                    pass
        return procs

    def models_payload(self) -> dict:
        return {"schema": SCHEMA, "host": self.host,
                **self.models.snapshot(self.gpu_processes())}

    def tick(self) -> dict:
        t0 = time.perf_counter_ns()
        payload = {"schema": SCHEMA, "ts": time.time(), "host": self.host}
        self._collect(payload, "sample")

        gpu_w = [g.get("power_w") for g in payload.get("gpus", [])]
        gpu_w = [w for w in gpu_w if isinstance(w, (int, float))]
        if gpu_w:
            merge(payload, {"power": {"sources": {"gpu": round(sum(gpu_w), 1)}}})
        payload.setdefault("power", {"sources": {}})
        vals = [v for v in payload["power"]["sources"].values()
                if isinstance(v, (int, float))]
        payload["power"]["measured_w"] = round(sum(vals), 1) if vals else None

        payload["tick_us"] = (time.perf_counter_ns() - t0) // 1000
        return payload
