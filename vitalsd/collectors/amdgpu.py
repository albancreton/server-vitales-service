"""AMD GPU collector via the amdgpu sysfs interface (/sys/class/drm)."""
from __future__ import annotations

import glob
import os
import re
import subprocess

from . import read_int, read_str

AMD_VENDOR = "0x1002"


class _Gpu:
    __slots__ = ("index", "card", "dev", "hwmon", "name", "device_id",
                 "unique_id", "vbios", "vram_total", "power_cap_w", "_temp_labels")

    def __init__(self, index: int, card: str, dev: str, name: str):
        self.index = index
        self.card = card            # e.g. "card1"
        self.dev = dev              # .../card1/device
        self.name = name
        hwmons = sorted(glob.glob(os.path.join(dev, "hwmon", "hwmon*")))
        self.hwmon = hwmons[0] if hwmons else None

        self.device_id = read_str(os.path.join(dev, "device"))
        self.unique_id = read_str(os.path.join(dev, "unique_id"))
        self.vbios = read_str(os.path.join(dev, "vbios_version"))
        self.vram_total = read_int(os.path.join(dev, "mem_info_vram_total"))
        cap = self._hw_int("power1_cap")            # microwatts
        self.power_cap_w = round(cap / 1e6, 1) if cap is not None else None

        # Map temp<N>_input -> label once (edge / junction / mem).
        self._temp_labels: dict[str, str] = {}
        if self.hwmon:
            for lp in sorted(glob.glob(os.path.join(self.hwmon, "temp*_label"))):
                label = read_str(lp)
                if label:
                    self._temp_labels[lp[: -len("_label")] + "_input"] = label

    def _hw_int(self, name: str) -> int | None:
        return read_int(os.path.join(self.hwmon, name)) if self.hwmon else None

    def static_info(self) -> dict:
        return {
            "index": self.index,
            "vendor": "amd",
            "name": self.name,
            "uuid": self.unique_id,
            "memory_kind": "dedicated",
            "vram_total": self.vram_total,
            "power_limit_w": self.power_cap_w,
            "max_clocks_mhz": {"graphics": None, "memory": None},
            "temp_slowdown_c": None,
            "vbios": self.vbios,
        }

    def sample(self) -> dict:
        total = read_int(os.path.join(self.dev, "mem_info_vram_total"))
        used = read_int(os.path.join(self.dev, "mem_info_vram_used"))
        memory = None
        if total is not None and used is not None:
            memory = {
                "total": total,
                "used": used,
                "free": total - used,
                "used_pct": round(used / total * 100, 1) if total else None,
            }

        temps: dict[str, float] = {}
        for input_path, label in self._temp_labels.items():
            mc = read_int(input_path)               # millidegrees C
            if mc is not None:
                temps[label] = round(mc / 1000.0, 1)

        pw = self._hw_int("power1_average")
        if pw is None:
            pw = self._hw_int("power1_input")
        fan_rpm = self._hw_int("fan1_input")
        sclk = self._hw_int("freq1_input")          # Hz
        mclk = self._hw_int("freq2_input")

        return {
            "index": self.index,
            "vendor": "amd",
            "util_gpu_pct": read_int(os.path.join(self.dev, "gpu_busy_percent")),
            "util_memory_pct": read_int(os.path.join(self.dev, "mem_busy_percent")),
            "memory": memory,
            "temperature_c": temps["edge"] if "edge" in temps else next(iter(temps.values()), None),
            "temperatures_c": temps,
            "power_w": round(pw / 1e6, 1) if pw is not None else None,
            "fans": [{"rpm": fan_rpm, "pct": None}] if fan_rpm is not None else [],
            "clocks_mhz": {
                "graphics": sclk // 1_000_000 if sclk is not None else None,
                "memory": mclk // 1_000_000 if mclk is not None else None,
            },
            "perf_state": None,
            "throttle_reasons": [],
            "processes": [],
        }


def _pci_names(root: str) -> dict[str, str]:
    """{realpath(device dir) -> marketing name} via lspci; real hosts only."""
    if root != "/":
        return {}
    names: dict[str, str] = {}
    try:
        out = subprocess.run(
            ["lspci", "-D", "-mm", "-d", "1002::0300"],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return names
    for line in out.splitlines():
        m = re.match(r'^(\S+)\s+"[^"]*"\s+"[^"]*"\s+"([^"]*)"', line)
        if not m:
            continue
        slot, name = m.group(1), m.group(2)
        m2 = re.search(r"\[([^\]]+)\]", name)   # prefer the bracketed board name
        names[os.path.realpath(f"/sys/bus/pci/devices/{slot}")] = (
            m2.group(1) if m2 else name)
    return names


class AmdGpuCollector:
    name = "gpu.amdgpu"

    def __init__(self, gpus: list[_Gpu], root: str = "/"):
        self.gpus = gpus
        self._root = root
        self._cards = frozenset(g.card for g in gpus)

    @staticmethod
    def _ready_cards(root: str) -> list[tuple[str, str]]:
        """[(cardN, .../cardN/device)] for AMD cards whose amdgpu init is done.

        amdgpu brings cards up asynchronously after modprobe; a card whose
        sysfs dir exists but has no gpu_busy_percent yet is still initializing.
        """
        cards: list[tuple[str, str]] = []
        pattern = os.path.join(root, "sys/class/drm/card[0-9]*")
        for card_path in sorted(glob.glob(pattern)):
            base = os.path.basename(card_path)
            if not base[4:].isdigit():
                continue                # skip card1-DP-1 style connector dirs
            dev = os.path.join(card_path, "device")
            if read_str(os.path.join(dev, "vendor")) != AMD_VENDOR:
                continue
            if not os.path.exists(os.path.join(dev, "gpu_busy_percent")):
                continue                # display-only adapter, or not ready yet
            cards.append((base, dev))
        return cards

    @classmethod
    def _discover(cls, root: str) -> list[_Gpu]:
        pci_names = _pci_names(root)
        gpus: list[_Gpu] = []
        for idx, (base, dev) in enumerate(cls._ready_cards(root)):
            device_id = read_str(os.path.join(dev, "device"))
            name = pci_names.get(os.path.realpath(dev)) or f"AMD GPU {device_id or idx}"
            gpus.append(_Gpu(idx, base, dev, name))
        return gpus

    @classmethod
    def probe(cls, root: str = "/"):
        gpus = cls._discover(root)
        return cls(gpus, root) if gpus else None

    def _rescan(self) -> None:
        """Pick up cards that finished initializing (or were hot-plugged)
        after probe(). Cheap: one directory glob + a few stats per call."""
        cards = frozenset(c for c, _ in self._ready_cards(self._root))
        if cards != self._cards:
            self.gpus = self._discover(self._root)
            self._cards = frozenset(g.card for g in self.gpus)

    def static_info(self) -> dict:
        self._rescan()
        return {"gpus": [g.static_info() for g in self.gpus]}

    def sample(self) -> dict:
        self._rescan()
        return {"gpus": [g.sample() for g in self.gpus]}
