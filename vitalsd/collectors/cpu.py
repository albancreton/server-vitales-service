"""CPU collector: usage, load, frequency, temperature (psutil + sysfs).

A 1 Hz background thread owns psutil.cpu_percent() — its readings are deltas
since the previous call, so they must come from a single caller no matter how
many stream clients poll.
"""
from __future__ import annotations

import glob
import os
import platform
import threading

from . import read_int, read_str

_PRIMARY_LABELS = ("Tctl", "Package id 0", "Tdie")
_TZ_KEYWORDS = ("cpu", "soc", "pkg")


class CpuCollector:
    name = "cpu"

    def __init__(self, psutil_mod, root: str = "/"):
        self.psutil = psutil_mod
        self.root = root
        self._lock = threading.Lock()
        self._pct = 0.0
        self._per_core: list = [0.0] * (psutil_mod.cpu_count(logical=True) or 0)
        psutil_mod.cpu_percent(interval=None)               # prime
        psutil_mod.cpu_percent(interval=None, percpu=True)  # prime per-core
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    @classmethod
    def probe(cls, root: str = "/"):
        try:
            import psutil
        except ImportError:
            return None
        return cls(psutil, root)

    def _run(self):
        while not self._stop.wait(1.0):
            try:
                pct = self.psutil.cpu_percent(interval=None)
                per_core = self.psutil.cpu_percent(interval=None, percpu=True)
            except Exception:
                continue  # transient psutil hiccup: keep the sampler alive
            with self._lock:
                self._pct = pct
                self._per_core = per_core

    def _model(self) -> str | None:
        info = read_str(os.path.join(self.root, "proc/cpuinfo")) or ""
        for line in info.splitlines():
            if line.lower().startswith(("model name", "hardware")):
                return line.split(":", 1)[1].strip()
        return platform.processor() or None

    def _temps(self) -> tuple[float | None, dict]:
        temps: dict[str, float] = {}
        try:
            sensors = self.psutil.sensors_temperatures()
        except (AttributeError, OSError):
            sensors = {}
        chip = sensors.get("k10temp") or sensors.get("coretemp")
        if chip:
            for s in chip:
                temps[s.label or "temp"] = round(s.current, 1)
        if not temps:
            # some aarch64 SoCs expose CPU temps as thermal zones instead
            pattern = os.path.join(self.root, "sys/class/thermal/thermal_zone[0-9]*")
            for tz in sorted(glob.glob(pattern)):
                ttype = read_str(os.path.join(tz, "type")) or ""
                if not any(k in ttype.lower() for k in _TZ_KEYWORDS):
                    continue
                mc = read_int(os.path.join(tz, "temp"))
                if mc is not None:
                    temps[ttype] = round(mc / 1000.0, 1)
        primary = next((temps[k] for k in _PRIMARY_LABELS if k in temps), None)
        if primary is None and temps:
            primary = next(iter(temps.values()))
        return primary, temps

    def static_info(self) -> dict:
        return {"cpu": {
            "count": self.psutil.cpu_count(logical=True),
            "count_physical": self.psutil.cpu_count(logical=False),
            "model": self._model(),
        }}

    def sample(self) -> dict:
        with self._lock:
            pct = self._pct
            per_core = list(self._per_core)
        try:
            f = self.psutil.cpu_freq()
            freq = round(f.current) if f else None
        except (AttributeError, OSError, NotImplementedError):
            freq = None
        primary, temps = self._temps()
        return {"cpu": {
            "usage_pct": pct,
            "per_core_pct": per_core,
            "count": self.psutil.cpu_count(logical=True),
            "load_avg": [round(x, 2) for x in os.getloadavg()],
            "freq_mhz": freq,
            "temperature_c": primary,
            "temperatures_c": temps,
        }}
