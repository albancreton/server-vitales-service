"""NVIDIA GPU collector via NVML (nvidia-ml-py, imports as `pynvml`).

Handles unified-memory SoC quirks (e.g. NVIDIA GB10): NVML refuses
GetMemoryInfo, so RAM figures come from /proc/meminfo, and power readings
may be unavailable.
"""
from __future__ import annotations

import os
import threading
import time

THROTTLE_BITS = [
    (0x0001, "gpu_idle"),
    (0x0002, "app_clocks_setting"),
    (0x0004, "sw_power_cap"),
    (0x0008, "hw_slowdown"),
    (0x0010, "sync_boost"),
    (0x0020, "sw_thermal_slowdown"),
    (0x0040, "hw_thermal_slowdown"),
    (0x0080, "hw_power_brake"),
    (0x0100, "display_clock_setting"),
]


def decode_throttle(bits: int) -> list[str]:
    if not bits:
        return []
    return [name for mask, name in THROTTLE_BITS if bits & mask]


def read_meminfo(root: str) -> dict[str, int]:
    out: dict[str, int] = {}
    with open(os.path.join(root, "proc/meminfo"), "rb") as f:
        for line in f:
            k, _, v = line.partition(b":")
            parts = v.strip().split()
            if parts:
                try:
                    out[k.decode()] = int(parts[0]) * 1024  # kB -> bytes
                except ValueError:
                    pass
    return out


class _ProcNames:
    TTL = 30.0

    def __init__(self, root: str):
        self.root = root
        self._cache: dict[int, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, pid: int) -> str | None:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(pid)
            if hit and now - hit[1] < self.TTL:
                return hit[0]
        try:
            with open(os.path.join(self.root, f"proc/{pid}/comm"), "rb") as f:
                name = f.read().decode("utf-8", "replace").strip()
        except OSError:
            name = None
        with self._lock:
            if name is not None:
                self._cache[pid] = (name, now)
            else:
                self._cache.pop(pid, None)
        return name


class _Device:
    def __init__(self, nv, index: int, root: str, driver: str | None):
        self.nv = nv
        self.index = index
        self.root = root
        self.driver = driver
        self.handle = nv.nvmlDeviceGetHandleByIndex(index)
        self.procs = _ProcNames(root)

        self.name = self._safe(nv.nvmlDeviceGetName, self.handle) or f"GPU{index}"
        self.uuid = self._safe(nv.nvmlDeviceGetUUID, self.handle)

        # Probe memory once. If NVML refuses, this box has unified memory.
        try:
            m = nv.nvmlDeviceGetMemoryInfo(self.handle)
            self.memory_via_nvml = True
            self.vram_total = m.total
        except nv.NVMLError:
            self.memory_via_nvml = False
            self.vram_total = None

        plimit = self._safe(nv.nvmlDeviceGetEnforcedPowerLimit, self.handle)
        self.power_limit_w = round(plimit / 1000.0, 2) if plimit is not None else None
        self.fan_count = self._safe(nv.nvmlDeviceGetNumFans, self.handle) or 0
        self.max_graphics_mhz = self._safe(
            nv.nvmlDeviceGetMaxClockInfo, self.handle, nv.NVML_CLOCK_GRAPHICS)
        self.max_mem_mhz = self._safe(
            nv.nvmlDeviceGetMaxClockInfo, self.handle, nv.NVML_CLOCK_MEM)
        self.temp_slowdown_c = self._safe(
            nv.nvmlDeviceGetTemperatureThreshold, self.handle,
            nv.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN)

    def _safe(self, fn, *a):
        try:
            v = fn(*a)
            return v.decode() if isinstance(v, bytes) else v
        except self.nv.NVMLError:
            return None

    def static_info(self) -> dict:
        return {
            "index": self.index,
            "vendor": "nvidia",
            "name": self.name,
            "uuid": self.uuid,
            "memory_kind": "dedicated" if self.memory_via_nvml else "unified",
            "vram_total": self.vram_total,
            "power_limit_w": self.power_limit_w,
            "max_clocks_mhz": {"graphics": self.max_graphics_mhz,
                               "memory": self.max_mem_mhz},
            "temp_slowdown_c": self.temp_slowdown_c,
            "driver_version": self.driver,
        }

    def sample(self) -> dict:
        nv = self.nv
        h = self.handle

        try:
            u = nv.nvmlDeviceGetUtilizationRates(h)
            util_gpu, util_mem = u.gpu, u.memory
        except nv.NVMLError:
            util_gpu = util_mem = None

        memory = None
        if self.memory_via_nvml:
            try:
                m = nv.nvmlDeviceGetMemoryInfo(h)
                memory = {"total": m.total, "used": m.used, "free": m.free,
                          "used_pct": round(m.used / m.total * 100, 1) if m.total else None}
            except nv.NVMLError:
                pass
        else:
            try:
                mi = read_meminfo(self.root)
                total = mi.get("MemTotal", 0)
                avail = mi.get("MemAvailable", mi.get("MemFree", 0))
                memory = {"total": total, "used": total - avail, "free": avail,
                          "used_pct": round((total - avail) / total * 100, 1) if total else None}
            except OSError:
                pass

        temp = self._safe(nv.nvmlDeviceGetTemperature, h, nv.NVML_TEMPERATURE_GPU)
        pw = self._safe(nv.nvmlDeviceGetPowerUsage, h)  # milliwatts

        fans = []
        for i in range(self.fan_count):
            try:
                pct = nv.nvmlDeviceGetFanSpeed_v2(h, i)
            except (nv.NVMLError, AttributeError):
                pct = self._safe(nv.nvmlDeviceGetFanSpeed, h)
            if pct is not None:
                fans.append({"pct": pct, "rpm": None})

        perf = self._safe(nv.nvmlDeviceGetPerformanceState, h)
        try:
            throttle = decode_throttle(nv.nvmlDeviceGetCurrentClocksThrottleReasons(h))
        except nv.NVMLError:
            throttle = []

        procs = []
        for fn, kind in ((nv.nvmlDeviceGetComputeRunningProcesses, "compute"),
                         (nv.nvmlDeviceGetGraphicsRunningProcesses, "graphics")):
            try:
                for p in fn(h):
                    mem_b = getattr(p, "usedGpuMemory", None)
                    procs.append({"pid": p.pid, "kind": kind,
                                  "mem_bytes": mem_b if isinstance(mem_b, int) else None,
                                  "name": self.procs.get(p.pid)})
            except nv.NVMLError:
                pass

        return {
            "index": self.index,
            "vendor": "nvidia",
            "util_gpu_pct": util_gpu,
            "util_memory_pct": util_mem,
            "memory": memory,
            "temperature_c": temp,
            "temperatures_c": {"gpu": temp} if temp is not None else {},
            "power_w": round(pw / 1000.0, 2) if pw is not None else None,
            "fans": fans,
            "clocks_mhz": {
                "graphics": self._safe(nv.nvmlDeviceGetClockInfo, h, nv.NVML_CLOCK_GRAPHICS),
                "memory": self._safe(nv.nvmlDeviceGetClockInfo, h, nv.NVML_CLOCK_MEM),
            },
            "perf_state": f"P{perf}" if perf is not None else None,
            "throttle_reasons": throttle,
            "processes": procs,
        }


class NvmlCollector:
    name = "gpu.nvml"

    def __init__(self, nv, devices: list[_Device]):
        self.nv = nv
        self.devices = devices

    @classmethod
    def probe(cls, root: str = "/"):
        try:
            import pynvml as nv
        except ImportError:
            return None
        try:
            nv.nvmlInit()
        except Exception:
            return None
        try:
            count = nv.nvmlDeviceGetCount()
        except nv.NVMLError:
            count = 0
        if not count:
            try:
                nv.nvmlShutdown()
            except nv.NVMLError:
                pass
            return None
        driver = None
        try:
            v = nv.nvmlSystemGetDriverVersion()
            driver = v.decode() if isinstance(v, bytes) else v
        except nv.NVMLError:
            pass
        return cls(nv, [_Device(nv, i, root, driver) for i in range(count)])

    def static_info(self) -> dict:
        return {"gpus": [d.static_info() for d in self.devices]}

    def sample(self) -> dict:
        return {"gpus": [d.sample() for d in self.devices]}
