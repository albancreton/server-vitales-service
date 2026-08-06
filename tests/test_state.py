from __future__ import annotations

import vitalsd
from vitalsd.state import State, merge


class GpuA:
    name = "gpu.a"

    def static_info(self):
        return {"gpus": [{"index": 0, "vendor": "a"}]}

    def sample(self):
        return {"gpus": [{"index": 0, "power_w": 10.0}]}


class GpuB:
    name = "gpu.b"

    def static_info(self):
        return {"gpus": [{"index": 0, "vendor": "b"}]}

    def sample(self):
        return {"gpus": [{"index": 0, "power_w": 5.5}]}


class Rapl:
    name = "power.rapl"

    def static_info(self):
        return {}

    def sample(self):
        return {"power": {"sources": {"cpu_package": 20.0}}}


class Broken:
    name = "broken"

    def static_info(self):
        raise RuntimeError("boom-static")

    def sample(self):
        raise RuntimeError("boom-sample")


def test_merge_concatenates_lists_and_merges_dicts():
    dst = {"gpus": [1], "power": {"sources": {"a": 1}}}
    merge(dst, {"gpus": [2], "power": {"sources": {"b": 2}}, "x": 3})
    assert dst == {"gpus": [1, 2], "power": {"sources": {"a": 1, "b": 2}}, "x": 3}


def test_info_payload():
    s = State([GpuA(), GpuB()], host="h")
    info = s.info_payload()
    assert info["schema"] == 1
    assert info["host"] == "h"
    assert info["version"] == vitalsd.__version__
    assert info["capabilities"] == ["gpu.a", "gpu.b"]
    assert [g["vendor"] for g in info["gpus"]] == ["a", "b"]
    assert "machine" in info["platform"]


def test_tick_sums_power_sources():
    s = State([GpuA(), GpuB(), Rapl()], host="h")
    t = s.tick()
    assert [g["power_w"] for g in t["gpus"]] == [10.0, 5.5]
    assert t["power"]["sources"] == {"gpu": 15.5, "cpu_package": 20.0}
    assert t["power"]["measured_w"] == 35.5
    assert isinstance(t["tick_us"], int)
    assert t["schema"] == 1 and t["host"] == "h" and "ts" in t


def test_tick_power_null_when_no_sources():
    t = State([], host="h").tick()
    assert t["power"] == {"sources": {}, "measured_w": None}


def test_collector_errors_are_isolated():
    s = State([Broken(), GpuA()], host="h")
    assert s.info_payload()["errors"] == {"broken": "boom-static"}
    t = s.tick()
    assert t["errors"] == {"broken": "boom-sample"}
    assert t["gpus"][0]["power_w"] == 10.0
