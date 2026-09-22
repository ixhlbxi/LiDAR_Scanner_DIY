"""Licence coherence after the relicense (D-008)."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_license_file_is_cc_by_nc_sa_legal_code() -> None:
    text = (REPO / "LICENSE").read_text(encoding="utf-8")
    first = text.lstrip().splitlines()[0]
    assert "Attribution-NonCommercial-ShareAlike 4.0 International" in first, first
    assert "Section 8 -- Interpretation." in text


def test_pyproject_declares_license() -> None:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["license"] == "CC-BY-NC-SA-4.0"


def test_readme_acknowledges_upstream() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "## Acknowledgements" in readme
    assert "PiLiDAR" in readme and "CC BY-NC-SA 4.0" in readme
    assert "## Licence" in readme
