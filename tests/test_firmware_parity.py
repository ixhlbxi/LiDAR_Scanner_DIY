"""[lora] radio parameters are documentation: they must equal the firmware build flags (T1-041)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _build_flags() -> dict[str, str]:
    """Parse platformio.ini and extract -D flags."""
    ini = (REPO / "firmware/esp32-rover/platformio.ini").read_text(encoding="utf-8")
    return dict(re.findall(r"-D\s*([A-Z_]+)=([^\s\\]+)", ini))


def test_lora_params_match_firmware_build_flags():
    """Verify [lora] TOML params match firmware build flags."""
    toml = tomllib.loads((REPO / "config/default.toml").read_text(encoding="utf-8"))["lora"]
    flags = _build_flags()

    # spreading_factor: SF7 in firmware, 7 in TOML
    assert int(flags["LORA_SF"]) == toml["spreading_factor"]

    # bandwidth_khz: 125.0 in firmware, 125 in TOML
    assert int(float(flags["LORA_BW_KHZ"])) == toml["bandwidth_khz"]

    # coding_rate: "4/5" in both TOML and firmware (CR_DENOM=5 => 4/5)
    assert f"4/{flags['LORA_CR_DENOM']}" == toml["coding_rate"]

    # sync_word: 0x12 in both
    assert int(flags["LORA_SYNC_PRIVATE"], 0) == toml["sync_word"]
