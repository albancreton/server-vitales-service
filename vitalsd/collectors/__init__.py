"""Collector registry and shared sysfs helpers.

Every collector class provides:
  name: str                            capability id, e.g. "gpu.nvml"
  probe(root="/") -> Collector | None  None means unsupported on this host
  static_info() -> dict                partial /info payload (deep-merged)
  sample() -> dict                     partial tick payload (deep-merged)
"""
from __future__ import annotations

import importlib


def read_str(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace").strip()
    except OSError:
        return None


def read_int(path: str) -> int | None:
    v = read_str(path)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None


_REGISTRY = [
    ("nvml", "NvmlCollector"),
    ("amdgpu", "AmdGpuCollector"),
    ("cpu", "CpuCollector"),
    ("memory", "MemoryCollector"),
    ("hwmon", "HwmonCollector"),
    ("rapl", "RaplCollector"),
]


def probe_all(root: str = "/") -> list:
    found = []
    for mod_name, cls_name in _REGISTRY:
        mod = importlib.import_module(f".{mod_name}", __package__)
        cls = getattr(mod, cls_name)
        try:
            collector = cls.probe(root)
        except Exception:
            collector = None
        if collector is not None:
            found.append(collector)
    return found
