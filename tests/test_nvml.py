from __future__ import annotations

import sys

from helpers import assert_gpu_sample_shape, make_fake_nvml, write

from vitalsd.collectors.nvml import NvmlCollector


def test_probe_none_without_pynvml(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)  # forces ImportError
    assert NvmlCollector.probe() is None


def test_dedicated_gpu(monkeypatch, tmp_path):
    root = str(tmp_path)
    write(root, "proc/4242/comm", "llama-server")
    monkeypatch.setitem(sys.modules, "pynvml", make_fake_nvml())
    col = NvmlCollector.probe(root)

    static = col.static_info()["gpus"][0]
    assert static["vendor"] == "nvidia"
    assert static["name"] == "Fake RTX"
    assert static["memory_kind"] == "dedicated"
    assert static["vram_total"] == 8 * 1024**3
    assert static["power_limit_w"] == 320.0
    assert static["max_clocks_mhz"] == {"graphics": 2500, "memory": 2500}
    assert static["temp_slowdown_c"] == 90
    assert static["driver_version"] == "580.65.06"

    g = col.sample()["gpus"][0]
    assert_gpu_sample_shape(g)
    assert g["util_gpu_pct"] == 87
    assert g["util_memory_pct"] == 41
    assert g["memory"]["used_pct"] == 25.0
    assert g["temperature_c"] == 66
    assert g["power_w"] == 123.45
    assert g["fans"] == [{"pct": 34, "rpm": None}]
    assert g["clocks_mhz"] == {"graphics": 1800, "memory": 1800}
    assert g["perf_state"] == "P0"
    assert g["throttle_reasons"] == ["sw_power_cap"]
    assert g["processes"] == [{"pid": 4242, "kind": "compute",
                               "mem_bytes": 123456, "name": "llama-server"}]


def test_unified_memory_fallback(monkeypatch, tmp_path):
    root = str(tmp_path)
    write(root, "proc/meminfo",
          "MemTotal:       131072000 kB\nMemAvailable:    65536000 kB")
    monkeypatch.setitem(sys.modules, "pynvml",
                        make_fake_nvml(unified=True, has_power=False))
    col = NvmlCollector.probe(root)

    static = col.static_info()["gpus"][0]
    assert static["memory_kind"] == "unified"
    assert static["vram_total"] is None
    assert static["power_limit_w"] is None

    g = col.sample()["gpus"][0]
    total = 131072000 * 1024
    assert g["memory"] == {"total": total, "used": total - 65536000 * 1024,
                           "free": 65536000 * 1024, "used_pct": 50.0}
    assert g["power_w"] is None
