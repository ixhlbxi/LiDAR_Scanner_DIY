"""Version coherence — one literal, three consumers (T1-036)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import rover
from rover import ntrip

REPO = Path(__file__).resolve().parents[1]


def test_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", rover.__version__), rover.__version__


def test_pyproject_version_is_dynamic() -> None:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in data["project"], "pyproject must not carry a literal version"
    assert "version" in data["project"].get("dynamic", [])
    assert data["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "rover.__version__"}


def test_ntrip_user_agent_carries_package_version() -> None:
    assert rover.__version__ in ntrip.USER_AGENT


def test_logger_has_no_hardcoded_version_literal() -> None:
    src = (REPO / "src" / "rover" / "logger.py").read_text(encoding="utf-8")
    assert '"firmware_version": "' not in src, "logger.py must import __version__"
