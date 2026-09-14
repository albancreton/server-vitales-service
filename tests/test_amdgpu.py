from __future__ import annotations

from helpers import assert_gpu_sample_shape, write

from vitalsd.collectors.amdgpu import AmdGpuCollector


def _amd_tree(root, card="card1"):
    dev = f"sys/class/drm/{card}/device"
    write(root, f"{dev}/vendor", "0x1002")
    write(root, f"{dev}/device", "0x7551")
    write(root, f"{dev}/gpu_busy_percent", "87")
    write(root, f"{dev}/mem_busy_percent", "40")
    write(root, f"{dev}/mem_info_vram_total", "34342961152")
    write(root, f"{dev}/mem_info_vram_used", "1000000000")
    write(root, f"{dev}/unique_id", "abc123")
    write(root, f"{dev}/vbios_version", "113-XYZ")
    hw = f"{dev}/hwmon/hwmon3"
    write(root, f"{hw}/temp1_label", "edge")
    write(root, f"{hw}/temp1_input", "64000")
    write(root, f"{hw}/temp2_label", "junction")
    write(root, f"{hw}/temp2_input", "72000")
    write(root, f"{hw}/power1_average", "123000000")
    write(root, f"{hw}/power1_cap", "300000000")
    write(root, f"{hw}/fan1_input", "1200")
    write(root, f"{hw}/freq1_input", "2100000000")
    write(root, f"{hw}/freq2_input", "1258000000")


def test_probe_none_without_amd_gpus(tmp_path):
    assert AmdGpuCollector.probe(str(tmp_path)) is None


def test_probe_skips_non_amd_and_non_render(tmp_path):
    root = str(tmp_path)
    _amd_tree(root, "card1")
    write(root, "sys/class/drm/card0/device/vendor", "0x10de")  # nvidia card
    write(root, "sys/class/drm/card2/device/vendor", "0x1002")  # no busy knob
    col = AmdGpuCollector.probe(root)
    assert len(col.gpus) == 1
    assert col.gpus[0].card == "card1"


def test_static_and_sample(tmp_path):
    root = str(tmp_path)
    _amd_tree(root)
    col = AmdGpuCollector.probe(root)

    static = col.static_info()["gpus"][0]
    assert static["vendor"] == "amd"
    assert static["name"] == "AMD GPU 0x7551"   # lspci naming is skipped off-host
    assert static["uuid"] == "abc123"
    assert static["memory_kind"] == "dedicated"
    assert static["vram_total"] == 34342961152
    assert static["power_limit_w"] == 300.0

    g = col.sample()["gpus"][0]
    assert_gpu_sample_shape(g)
    assert g["util_gpu_pct"] == 87
    assert g["util_memory_pct"] == 40
    assert g["memory"] == {"total": 34342961152, "used": 1000000000,
                           "free": 33342961152, "used_pct": 2.9}
    assert g["temperature_c"] == 64.0
    assert g["temperatures_c"] == {"edge": 64.0, "junction": 72.0}
    assert g["power_w"] == 123.0
    assert g["fans"] == [{"rpm": 1200, "pct": None}]
    assert g["clocks_mhz"] == {"graphics": 2100, "memory": 1258}


def test_zero_readings_are_not_null(tmp_path):
    root = str(tmp_path)
    _amd_tree(root)
    write(root, "sys/class/drm/card1/device/hwmon/hwmon3/freq1_input", "0")
    write(root, "sys/class/drm/card1/device/hwmon/hwmon3/temp1_input", "0")
    col = AmdGpuCollector.probe(root)
    g = col.sample()["gpus"][0]
    assert g["clocks_mhz"]["graphics"] == 0
    assert g["temperature_c"] == 0.0


def test_rescan_picks_up_late_initialized_card(tmp_path):
    root = str(tmp_path)
    _amd_tree(root, "card1")
    _amd_tree(root, "card2")
    # card3 exists but amdgpu hasn't finished bringing it up (no busy knob yet)
    write(root, "sys/class/drm/card3/device/vendor", "0x1002")
    col = AmdGpuCollector.probe(root)
    assert [g.card for g in col.gpus] == ["card1", "card2"]

    _amd_tree(root, "card3")                  # init completes after probe
    assert len(col.sample()["gpus"]) == 3
    assert [g["index"] for g in col.static_info()["gpus"]] == [0, 1, 2]
    assert [g.card for g in col.gpus] == ["card1", "card2", "card3"]


def test_rescan_drops_removed_card(tmp_path):
    import shutil
    root = str(tmp_path)
    _amd_tree(root, "card1")
    _amd_tree(root, "card2")
    col = AmdGpuCollector.probe(root)
    shutil.rmtree(f"{root}/sys/class/drm/card1")
    gpus = col.sample()["gpus"]
    assert len(gpus) == 1 and gpus[0]["index"] == 0
    assert col.gpus[0].card == "card2"
