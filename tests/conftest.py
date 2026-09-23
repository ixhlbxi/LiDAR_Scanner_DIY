"""Shared pytest fixtures for rover tests."""

import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def tmp_toml(tmp_path: Path):
    """Helper: write TOML content to a temp file and return its path."""

    def _write(content: str) -> Path:
        p = tmp_path / "test_config.toml"
        p.write_text(textwrap.dedent(content))
        return p

    return _write
