"""Test hygiene — hardware scripts import real drivers; consolidated fixtures (T2-006, T2-007, T2-008)."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_hardware_scripts_import_drivers_not_copies():
    """Hardware test scripts import from rover.* instead of duplicating code."""
    src = (REPO / "tests/hardware/test_lidar.py").read_text(encoding="utf-8")
    assert "_CRC_TABLE" not in src and "from rover.lidar import" in src
    src = (REPO / "tests/hardware/test_imu.py").read_text(encoding="utf-8")
    assert "from rover.imu import ImuDriver" in src and "_REG_" not in src


def test_single_tmp_toml_fixture():
    """Only conftest.py defines tmp_toml; no duplicates in test files."""
    hits = [
        p
        for p in (REPO / "tests").glob("test_*.py")
        if re.search(r"^def tmp_toml", p.read_text(), re.M)
    ]
    assert hits == [], hits
