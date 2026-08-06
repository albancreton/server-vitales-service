"""Generic hwmon collector: chassis/CPU fans and power rails.

GPU-owned hwmon devices are excluded — the GPU collectors own those readings,
and skipping them here keeps power sources free of double counting.
"""
from __future__ import annotations

import glob
import os

from . import read_int, read_str

GPU_VENDORS = {"0x1002", "0x10de"}


def _is_gpu_owned(hdir: str) -> bool:
    return read_str(os.path.join(hdir, "device", "vendor")) in GPU_VENDORS


def _label(stem: str, chip_name: str) -> str:
    return read_str(stem + "_label") or f"{chip_name}_{os.path.basename(stem)}"


class HwmonCollector:
    name = "hwmon"

    def __init__(self, chips: list[dict]):
        self.chips = chips  # [{"name": str, "fans": [paths], "powers": [paths]}]

    @classmethod
    def probe(cls, root: str = "/"):
        chips: list[dict] = []
        pattern = os.path.join(root, "sys/class/hwmon/hwmon[0-9]*")
        for hdir in sorted(glob.glob(pattern)):
            if _is_gpu_owned(hdir):
                continue
            chip_name = read_str(os.path.join(hdir, "name")) or os.path.basename(hdir)
            fans = sorted(glob.glob(os.path.join(hdir, "fan[0-9]*_input")))
            powers = sorted(glob.glob(os.path.join(hdir, "power[0-9]*_average")))
            have = {os.path.basename(p)[: -len("_average")] for p in powers}
            for inp in sorted(glob.glob(os.path.join(hdir, "power[0-9]*_input"))):
                if os.path.basename(inp)[: -len("_input")] not in have:
                    powers.append(inp)
            if fans or powers:
                chips.append({"name": chip_name, "fans": fans, "powers": powers})
        return cls(chips) if chips else None

    def static_info(self) -> dict:
        return {}

    def sample(self) -> dict:
        fans: list[dict] = []
        sources: dict[str, float] = {}
        for chip in self.chips:
            for fp in chip["fans"]:
                rpm = read_int(fp)
                if rpm is None:
                    continue
                stem = fp.rsplit("_", 1)[0]
                fans.append({"label": _label(stem, chip["name"]), "rpm": rpm})
            for pp in chip["powers"]:
                uw = read_int(pp)  # microwatts
                if uw is None:
                    continue
                stem = pp.rsplit("_", 1)[0]
                sources[_label(stem, chip["name"])] = round(uw / 1e6, 1)
        out: dict = {"fans": fans}
        if sources:
            out["power"] = {"sources": sources}
        return out
