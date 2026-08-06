from __future__ import annotations

from helpers import write

from vitalsd.collectors.rapl import RaplCollector

D = "sys/class/powercap/intel-rapl:0"


def _rapl_tree(root, energy="1000000"):
    write(root, f"{D}/name", "package-0")
    write(root, f"{D}/energy_uj", energy)
    write(root, f"{D}/max_energy_range_uj", "262143328850")


def test_probe_none_without_rapl(tmp_path):
    assert RaplCollector.probe(str(tmp_path)) is None


def test_probe_skips_subdomains_and_psys(tmp_path):
    root = str(tmp_path)
    _rapl_tree(root)
    write(root, "sys/class/powercap/intel-rapl:0:0/name", "core")
    write(root, "sys/class/powercap/intel-rapl:0:0/energy_uj", "500")
    write(root, "sys/class/powercap/intel-rapl:1/name", "psys")
    write(root, "sys/class/powercap/intel-rapl:1/energy_uj", "900")
    col = RaplCollector.probe(root)
    assert len(col.domains) == 1


def test_watts_from_energy_delta(tmp_path):
    root = str(tmp_path)
    _rapl_tree(root, "1000000")
    col = RaplCollector.probe(root)
    t = {"now": 100.0}
    col._clock = lambda: t["now"]
    assert col.sample() == {}                      # first tick just primes
    write(root, f"{D}/energy_uj", "31000000")      # +30 J
    t["now"] = 102.0                               # over 2 s -> 15 W
    out = col.sample()
    assert out["power"]["sources"]["cpu_package"] == 15.0


def test_counter_wraparound(tmp_path):
    root = str(tmp_path)
    _rapl_tree(root, "262143328000")
    col = RaplCollector.probe(root)
    t = {"now": 100.0}
    col._clock = lambda: t["now"]
    col.sample()
    write(root, f"{D}/energy_uj", "999150")        # wrapped past max
    t["now"] = 101.0                               # +1 J over 1 s -> 1 W
    out = col.sample()
    assert out["power"]["sources"]["cpu_package"] == 1.0
