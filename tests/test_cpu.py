from __future__ import annotations

from helpers import StubPsutil, write

from vitalsd.collectors.cpu import CpuCollector


def test_cpu_probe_and_sample_shape():
    col = CpuCollector.probe()
    assert col is not None
    out = col.sample()["cpu"]
    assert isinstance(out["usage_pct"], (int, float))
    assert isinstance(out["per_core_pct"], list)
    assert out["count"] >= 1
    assert len(out["load_avg"]) == 3
    assert "temperature_c" in out
    assert isinstance(out["temperatures_c"], dict)
    assert "freq_mhz" in out
    static = col.static_info()["cpu"]
    assert static["count"] >= 1
    assert "count_physical" in static and "model" in static


def test_cpu_thermal_zone_fallback(tmp_path):
    root = str(tmp_path)
    write(root, "sys/class/thermal/thermal_zone0/type", "cpu-thermal")
    write(root, "sys/class/thermal/thermal_zone0/temp", "45500")
    write(root, "sys/class/thermal/thermal_zone1/type", "wifi")
    write(root, "sys/class/thermal/thermal_zone1/temp", "60000")
    col = CpuCollector(StubPsutil(), root=root)
    out = col.sample()["cpu"]
    assert out["temperatures_c"] == {"cpu-thermal": 45.5}
    assert out["temperature_c"] == 45.5


def test_cpu_model_from_cpuinfo(tmp_path):
    root = str(tmp_path)
    write(root, "proc/cpuinfo", "processor\t: 0\nmodel name\t: Fake CPU 9000")
    col = CpuCollector(StubPsutil(), root=root)
    assert col.static_info()["cpu"]["model"] == "Fake CPU 9000"
