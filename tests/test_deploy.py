"""Static checks that the deploy kit and shipped configs agree (T2-001..T2-003)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
UNITS = [REPO / "deploy/systemd/rover.service", REPO / "deploy/systemd/rover-telemetry.service"]
# Bench sessions (telemetry-only) stay out of the scan-session folder.
EXPECTED_OUTPUT_DIRS = [
    (REPO / "config/default.toml", "/var/lib/rover/data"),
    (REPO / "config/telemetry-only.toml", "/var/lib/rover/bench"),
]


@pytest.mark.parametrize("unit", UNITS, ids=lambda p: p.name)
def test_unit_grants_state_and_runtime_dirs(unit: Path) -> None:
    text = unit.read_text(encoding="utf-8")
    assert re.search(r"^StateDirectory=rover$", text, re.M), unit.name
    assert re.search(r"^RuntimeDirectory=rover$", text, re.M), unit.name
    assert re.search(r"^PrivateTmp=true$", text, re.M), unit.name
    assert "DEC-013 of arm-drone-lidar-workflow" not in text


@pytest.mark.parametrize(
    "toml_path, expected",
    EXPECTED_OUTPUT_DIRS,
    ids=[p.name for p, _ in EXPECTED_OUTPUT_DIRS],
)
def test_shipped_output_dir_is_writable_under_hardening(toml_path: Path, expected: str) -> None:
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    out = data["logging"]["output_dir"]
    assert out.startswith("/var/lib/rover/"), out
    assert not out.startswith("/home/"), "ProtectHome=true hides /home"
    assert out == expected, out


def test_install_sh_installs_configs_without_overwriting() -> None:
    sh = (REPO / "deploy/install.sh").read_text(encoding="utf-8")
    assert 'if [[ ! -f "$ETC_DIR/config.toml" ]]' in sh
    assert 'if [[ ! -f "$ETC_DIR/telemetry-only.toml" ]]' in sh
    assert "rsync" in sh and "/opt/rover" in sh
    assert 'install -d -m 0755 "$RUN_DIR"' not in sh, "/run is tmpfs; RuntimeDirectory= owns it"
    assert "rover-telemetry.service" in sh.split("=== Reload ===")[1], "both units restarted"
