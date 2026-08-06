"""Shared test helpers: fake sysfs trees and schema-shape assertions."""
from __future__ import annotations

import os

GPU_SAMPLE_KEYS = {
    "index", "vendor", "util_gpu_pct", "util_memory_pct", "memory",
    "temperature_c", "temperatures_c", "power_w", "fans",
    "clocks_mhz", "perf_state", "throttle_reasons", "processes",
}


def write(root, rel, content):
    """Create root/rel with content, making parent dirs."""
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"{content}\n")
    return path


def assert_gpu_sample_shape(g):
    missing = GPU_SAMPLE_KEYS - set(g)
    assert not missing, f"gpu sample missing keys: {missing}"
    assert g["vendor"] in ("nvidia", "amd")
    assert isinstance(g["fans"], list)
    for fan in g["fans"]:
        assert {"rpm", "pct"} <= set(fan)
    assert isinstance(g["temperatures_c"], dict)
    assert isinstance(g["throttle_reasons"], list)
    assert isinstance(g["processes"], list)
    assert set(g["clocks_mhz"]) == {"graphics", "memory"}


class StubPsutil:
    """Minimal psutil stand-in for exercising sysfs fallback paths."""

    def cpu_percent(self, interval=None, percpu=False):
        return [1.0, 2.0] if percpu else 1.5

    def cpu_count(self, logical=True):
        return 2 if logical else 1

    def cpu_freq(self):
        return None


import types


class NVMLError(Exception):
    pass


def _unsupported(*a, **k):
    raise NVMLError("unsupported")


def make_fake_nvml(*, unified=False, has_power=True):
    """A pynvml stand-in with one GPU; flags mimic a unified-memory SoC's quirks."""
    util = types.SimpleNamespace(gpu=87, memory=41)
    mem = types.SimpleNamespace(total=8 * 1024**3, used=2 * 1024**3, free=6 * 1024**3)
    proc = types.SimpleNamespace(pid=4242, usedGpuMemory=123456)
    return types.SimpleNamespace(
        NVMLError=NVMLError,
        NVML_CLOCK_GRAPHICS=0,
        NVML_CLOCK_MEM=2,
        NVML_TEMPERATURE_GPU=0,
        NVML_TEMPERATURE_THRESHOLD_SLOWDOWN=1,
        nvmlInit=lambda: None,
        nvmlShutdown=lambda: None,
        nvmlDeviceGetCount=lambda: 1,
        nvmlSystemGetDriverVersion=lambda: b"580.65.06",
        nvmlDeviceGetHandleByIndex=lambda i: "handle",
        nvmlDeviceGetName=lambda h: b"Fake RTX",
        nvmlDeviceGetUUID=lambda h: b"GPU-fake",
        nvmlDeviceGetMemoryInfo=_unsupported if unified else (lambda h: mem),
        nvmlDeviceGetEnforcedPowerLimit=(lambda h: 320000) if has_power else _unsupported,
        nvmlDeviceGetNumFans=lambda h: 1,
        nvmlDeviceGetMaxClockInfo=lambda h, c: 2500,
        nvmlDeviceGetTemperatureThreshold=lambda h, t: 90,
        nvmlDeviceGetUtilizationRates=lambda h: util,
        nvmlDeviceGetTemperature=lambda h, s: 66,
        nvmlDeviceGetPowerUsage=(lambda h: 123450) if has_power else _unsupported,
        nvmlDeviceGetFanSpeed_v2=lambda h, i: 34,
        nvmlDeviceGetFanSpeed=lambda h: 34,
        nvmlDeviceGetPerformanceState=lambda h: 0,
        nvmlDeviceGetCurrentClocksThrottleReasons=lambda h: 0x0004,
        nvmlDeviceGetClockInfo=lambda h, c: 1800,
        nvmlDeviceGetComputeRunningProcesses=lambda h: [proc],
        nvmlDeviceGetGraphicsRunningProcesses=lambda h: [],
    )
