from __future__ import annotations

from vitalsd.collectors.memory import MemoryCollector


def test_memory_probe_and_sample_shape():
    col = MemoryCollector.probe()
    assert col is not None
    out = col.sample()
    assert out["memory"]["total"] > 0
    assert 0 <= out["memory"]["used_pct"] <= 100
    assert set(out["memory"]) == {"total", "used", "available", "used_pct"}
    assert set(out["swap"]) == {"total", "used", "used_pct"}
    assert col.static_info()["memory_total"] == out["memory"]["total"]
