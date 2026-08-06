"""RAM + swap collector via psutil."""
from __future__ import annotations


class MemoryCollector:
    name = "memory"

    def __init__(self, psutil_mod):
        self.psutil = psutil_mod

    @classmethod
    def probe(cls, root: str = "/"):
        try:
            import psutil
        except ImportError:
            return None
        return cls(psutil)

    def static_info(self) -> dict:
        return {"memory_total": self.psutil.virtual_memory().total}

    def sample(self) -> dict:
        vm = self.psutil.virtual_memory()
        sm = self.psutil.swap_memory()
        return {
            "memory": {"total": vm.total, "used": vm.used,
                       "available": vm.available, "used_pct": vm.percent},
            "swap": {"total": sm.total, "used": sm.used, "used_pct": sm.percent},
        }
