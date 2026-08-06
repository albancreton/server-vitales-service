from __future__ import annotations

from helpers import write

from vitalsd.collectors.hwmon import HwmonCollector


def test_probe_none_when_no_chips(tmp_path):
    assert HwmonCollector.probe(str(tmp_path)) is None


def test_fans_and_rails_excluding_gpu_chips(tmp_path):
    root = str(tmp_path)
    write(root, "sys/class/hwmon/hwmon0/name", "nct6798")
    write(root, "sys/class/hwmon/hwmon0/fan1_input", "900")
    write(root, "sys/class/hwmon/hwmon0/fan2_input", "1250")
    write(root, "sys/class/hwmon/hwmon0/fan2_label", "cpu_fan")
    write(root, "sys/class/hwmon/hwmon1/name", "amdgpu")        # GPU-owned: skip
    write(root, "sys/class/hwmon/hwmon1/device/vendor", "0x1002")
    write(root, "sys/class/hwmon/hwmon1/fan1_input", "3000")
    write(root, "sys/class/hwmon/hwmon2/name", "ina3221")
    write(root, "sys/class/hwmon/hwmon2/power1_input", "25000000")
    write(root, "sys/class/hwmon/hwmon2/power1_label", "VDD_CPU")

    out = HwmonCollector.probe(root).sample()
    assert out["fans"] == [
        {"label": "nct6798_fan1", "rpm": 900},
        {"label": "cpu_fan", "rpm": 1250},
    ]
    assert out["power"]["sources"] == {"VDD_CPU": 25.0}


def test_prefers_power_average_over_input(tmp_path):
    root = str(tmp_path)
    write(root, "sys/class/hwmon/hwmon0/name", "chip")
    write(root, "sys/class/hwmon/hwmon0/power1_average", "10000000")
    write(root, "sys/class/hwmon/hwmon0/power1_input", "99000000")
    out = HwmonCollector.probe(root).sample()
    assert out["power"]["sources"] == {"chip_power1": 10.0}


def test_fans_only_chip_has_no_power_key(tmp_path):
    root = str(tmp_path)
    write(root, "sys/class/hwmon/hwmon0/name", "fanchip")
    write(root, "sys/class/hwmon/hwmon0/fan1_input", "500")
    out = HwmonCollector.probe(root).sample()
    assert out == {"fans": [{"label": "fanchip_fan1", "rpm": 500}]}
