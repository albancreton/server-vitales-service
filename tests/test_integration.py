"""End-to-end: real probe on the dev machine (cpu+memory at minimum)."""
from __future__ import annotations

from vitalsd.collectors import probe_all
from vitalsd.state import State


def test_probe_and_tick_end_to_end():
    state = State(probe_all())
    caps = [c.name for c in state.collectors]
    assert "cpu" in caps and "memory" in caps   # psutil probes everywhere

    info = state.info_payload()
    assert info["schema"] == 1
    assert info["capabilities"] == caps
    assert info["memory_total"] > 0

    tick = state.tick()
    assert tick["schema"] == 1
    assert tick["cpu"]["count"] >= 1
    assert tick["memory"]["total"] > 0
    assert "measured_w" in tick["power"]
    assert "errors" not in tick, f"collector errors: {tick.get('errors')}"
