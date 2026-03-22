"""Shared pytest fixtures for rover tests."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test output."""
    return tmp_path


@pytest.fixture
def sample_toml(tmp_path: Path) -> Path:
    """Write a minimal valid TOML config and return its path."""
    config_path = tmp_path / "test_config.toml"
    config_path.write_text(
        '[general]\n'
        'device_name = "test-rover"\n'
        'log_level = "DEBUG"\n'
    )
    return config_path


@pytest.fixture
def default_toml_path() -> Path:
    """Return path to the project's default.toml."""
    return Path(__file__).resolve().parent.parent / "config" / "default.toml"
