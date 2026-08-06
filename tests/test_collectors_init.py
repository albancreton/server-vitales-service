from __future__ import annotations

from vitalsd.collectors import probe_all, read_int, read_str


def test_read_helpers(tmp_path):
    p = tmp_path / "v"
    p.write_text(" 42\n")
    assert read_str(str(p)) == "42"
    assert read_int(str(p)) == 42
    (tmp_path / "junk").write_text("abc\n")
    assert read_int(str(tmp_path / "junk")) is None
    assert read_str(str(tmp_path / "missing")) is None
    assert read_int(str(tmp_path / "missing")) is None


def test_probe_all_returns_list():
    assert isinstance(probe_all(root="/nonexistent"), list)
