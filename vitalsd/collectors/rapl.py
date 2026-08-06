"""CPU package power via the Linux powercap (intel-rapl) interface.

energy_uj is a monotonically increasing counter, root-readable only on modern
kernels (which is why vitalsd runs as a root systemd service). Watts are the
counter delta between ticks. Only package-* domains are summed: psys would
double-count the packages, and core/uncore/dram subdomains are inside them.
"""
from __future__ import annotations

import glob
import os
import time

from . import read_int, read_str


class RaplCollector:
    name = "power.rapl"

    def __init__(self, domains: list[dict], clock=time.monotonic):
        self.domains = domains  # [{"energy": path, "max": int | None}]
        self._clock = clock
        self._last: tuple[float, list[int]] | None = None

    @classmethod
    def probe(cls, root: str = "/"):
        domains: list[dict] = []
        pattern = os.path.join(root, "sys/class/powercap/intel-rapl:[0-9]*")
        for d in sorted(glob.glob(pattern)):
            name = read_str(os.path.join(d, "name")) or ""
            if not name.startswith("package"):
                continue
            energy = os.path.join(d, "energy_uj")
            if read_int(energy) is None:
                continue  # unreadable (permissions) -> unsupported
            domains.append({"energy": energy,
                            "max": read_int(os.path.join(d, "max_energy_range_uj"))})
        return cls(domains) if domains else None

    def static_info(self) -> dict:
        return {}

    def sample(self) -> dict:
        now = self._clock()
        readings = [read_int(d["energy"]) for d in self.domains]
        if any(r is None for r in readings):
            return {}
        last, self._last = self._last, (now, readings)
        if last is None:
            return {}
        t0, prev = last
        dt = now - t0
        if dt <= 0:
            return {}
        total_uj = 0
        for dom, a, b in zip(self.domains, prev, readings):
            d_uj = b - a
            if d_uj < 0 and dom["max"]:
                d_uj += dom["max"]      # counter wrapped
            if d_uj < 0:
                return {}               # still negative: counter reset, skip tick
            total_uj += d_uj
        return {"power": {"sources": {"cpu_package": round(total_uj / dt / 1e6, 1)}}}
