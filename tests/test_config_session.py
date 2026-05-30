"""Unit tests for the v0.10 config sections — session, ntrip, lora v2, base-station
integration, telemetry HTTP. No hardware required.

See DEC-030 through DEC-034 in docs/DECISIONS.md.
"""

import textwrap
from pathlib import Path

import pytest

from rover.config import (
    BaseStationIntegrationConfig,
    NtripConfig,
    RoverConfig,
    SessionConfig,
    TelemetryConfig,
    load_config,
)


@pytest.fixture
def tmp_toml(tmp_path):
    def _write(content: str) -> Path:
        p = tmp_path / "test_config.toml"
        p.write_text(textwrap.dedent(content))
        return p

    return _write


# ---------------------------------------------------------------------------
# Session (DEC-030)
# ---------------------------------------------------------------------------


class TestSessionDefaults:
    def test_session_default_profile_is_personal(self):
        cfg = load_config()
        assert isinstance(cfg.session, SessionConfig)
        assert cfg.session.profile == "personal"

    def test_session_default_crs_zero(self):
        cfg = load_config()
        assert cfg.session.target_crs_epsg == 0
        assert cfg.session.units == "m"

    def test_session_block_present_in_dict(self):
        cfg = load_config()
        d = cfg.to_dict()
        assert "session" in d
        assert d["session"]["profile"] == "personal"


class TestSessionValidation:
    def test_invalid_profile(self, tmp_toml):
        p = tmp_toml(
            """
            [session]
            profile = "professional"
            """
        )
        with pytest.raises(ValueError, match=r"\[session\] profile"):
            load_config(p)

    def test_invalid_units(self, tmp_toml):
        p = tmp_toml(
            """
            [session]
            units = "yards"
            """
        )
        with pytest.raises(ValueError, match=r"\[session\] units"):
            load_config(p)

    def test_negative_crs_epsg(self, tmp_toml):
        p = tmp_toml(
            """
            [session]
            target_crs_epsg = -1
            """
        )
        with pytest.raises(ValueError, match="target_crs_epsg"):
            load_config(p)

    def test_mission_tag_normalized_uppercase(self, tmp_toml):
        p = tmp_toml(
            """
            [session]
            mission_tag = "wentz"
            """
        )
        cfg = load_config(p)
        assert cfg.session.mission_tag == "WENTZ"


class TestArmGroupCrossValidation:
    """arm_group profile requires several other sections to be configured."""

    def test_arm_group_requires_project_code(self, tmp_toml):
        p = tmp_toml(
            """
            [session]
            profile = "arm_group"
            project_code = ""
            target_crs_epsg = 6346

            [base_station_integration]
            enabled = true

            [ntrip]
            enabled = true
            """
        )
        with pytest.raises(ValueError, match="project_code"):
            load_config(p)

    def test_arm_group_requires_crs(self, tmp_toml):
        p = tmp_toml(
            """
            [session]
            profile = "arm_group"
            project_code = "2026-WENTZ-LIDR"
            target_crs_epsg = 0

            [base_station_integration]
            enabled = true

            [ntrip]
            enabled = true
            """
        )
        with pytest.raises(ValueError, match="target_crs_epsg"):
            load_config(p)

    def test_arm_group_requires_base_station_integration(self, tmp_toml):
        p = tmp_toml(
            """
            [session]
            profile = "arm_group"
            project_code = "2026-WENTZ-LIDR"
            target_crs_epsg = 6346

            [base_station_integration]
            enabled = false

            [ntrip]
            enabled = true
            """
        )
        with pytest.raises(ValueError, match="base_station_integration"):
            load_config(p)

    def test_arm_group_requires_ntrip(self, tmp_toml):
        p = tmp_toml(
            """
            [session]
            profile = "arm_group"
            project_code = "2026-WENTZ-LIDR"
            target_crs_epsg = 6346

            [base_station_integration]
            enabled = true

            [ntrip]
            enabled = false
            """
        )
        with pytest.raises(ValueError, match=r"\[ntrip\]"):
            load_config(p)

    def test_arm_group_valid_config(self, tmp_toml):
        p = tmp_toml(
            """
            [session]
            profile = "arm_group"
            project_code = "2026-WENTZ-LIDR"
            mission_tag = "wentz"
            target_crs_epsg = 6346
            units = "ft"

            [base_station_integration]
            enabled = true

            [ntrip]
            enabled = true
            """
        )
        cfg = load_config(p)
        assert cfg.session.profile == "arm_group"
        assert cfg.session.project_code == "2026-WENTZ-LIDR"
        assert cfg.session.mission_tag == "WENTZ"  # normalized
        assert cfg.session.target_crs_epsg == 6346
        assert cfg.base_station_integration.enabled is True
        assert cfg.ntrip.enabled is True


# ---------------------------------------------------------------------------
# NTRIP (DEC-031, DEC-032)
# ---------------------------------------------------------------------------


class TestNtripConfig:
    def test_ntrip_defaults(self):
        cfg = load_config()
        assert isinstance(cfg.ntrip, NtripConfig)
        assert cfg.ntrip.enabled is False
        assert cfg.ntrip.client_location == "pi"
        assert cfg.ntrip.caster_host == "rtk-base.local"
        assert cfg.ntrip.caster_port == 2101
        assert cfg.ntrip.mountpoint == "ARM_BASE"
        assert cfg.ntrip.password_env == "ROVER_NTRIP_PASSWORD"

    def test_invalid_client_location(self, tmp_toml):
        p = tmp_toml(
            """
            [ntrip]
            client_location = "raspberry"
            """
        )
        with pytest.raises(ValueError, match="client_location"):
            load_config(p)

    def test_invalid_port_too_high(self, tmp_toml):
        p = tmp_toml(
            """
            [ntrip]
            caster_port = 99999
            """
        )
        with pytest.raises(ValueError, match="caster_port"):
            load_config(p)

    def test_invalid_port_zero(self, tmp_toml):
        p = tmp_toml(
            """
            [ntrip]
            caster_port = 0
            """
        )
        with pytest.raises(ValueError, match="caster_port"):
            load_config(p)

    def test_negative_gga_interval(self, tmp_toml):
        p = tmp_toml(
            """
            [ntrip]
            gga_send_interval_sec = -5
            """
        )
        with pytest.raises(ValueError, match="gga_send_interval_sec"):
            load_config(p)


# ---------------------------------------------------------------------------
# LoRa (DEC-031 — frame v2 fields)
# ---------------------------------------------------------------------------


class TestLoraV2Fields:
    def test_lora_default_sync_word(self):
        cfg = load_config()
        assert cfg.lora.sync_word == 0x12

    def test_lora_default_role(self):
        cfg = load_config()
        assert cfg.lora.role == "rtcm_rx+status_tx"

    def test_lora_default_spreading_factor_is_7(self):
        """SF7 is the new default (matches Base-Station Heltec/T-Deck firmware)."""
        cfg = load_config()
        assert cfg.lora.spreading_factor == 7

    def test_invalid_role(self, tmp_toml):
        p = tmp_toml(
            """
            [lora]
            role = "transmit_only"
            """
        )
        with pytest.raises(ValueError, match=r"\[lora\] role"):
            load_config(p)

    def test_sync_word_out_of_range(self, tmp_toml):
        p = tmp_toml(
            """
            [lora]
            sync_word = 300
            """
        )
        with pytest.raises(ValueError, match="sync_word"):
            load_config(p)

    def test_role_disabled_accepted(self, tmp_toml):
        p = tmp_toml(
            """
            [lora]
            role = "disabled"
            """
        )
        cfg = load_config(p)
        assert cfg.lora.role == "disabled"


# ---------------------------------------------------------------------------
# Base-station integration (DEC-033 channel A)
# ---------------------------------------------------------------------------


class TestBaseStationIntegration:
    def test_defaults(self):
        cfg = load_config()
        assert isinstance(cfg.base_station_integration, BaseStationIntegrationConfig)
        assert cfg.base_station_integration.enabled is False
        assert cfg.base_station_integration.status_schema_version == 1
        assert cfg.base_station_integration.publish_interval_sec == 1.0

    def test_negative_schema_version(self, tmp_toml):
        p = tmp_toml(
            """
            [base_station_integration]
            status_schema_version = 0
            """
        )
        with pytest.raises(ValueError, match="status_schema_version"):
            load_config(p)


# ---------------------------------------------------------------------------
# Telemetry HTTP (DEC-033 channel B)
# ---------------------------------------------------------------------------


class TestTelemetryHttp:
    def test_defaults(self):
        cfg = load_config()
        assert isinstance(cfg.telemetry, TelemetryConfig)
        assert cfg.telemetry.http_enabled is False
        assert cfg.telemetry.http_bind == "127.0.0.1"
        assert cfg.telemetry.http_port == 8090

    def test_invalid_http_port(self, tmp_toml):
        p = tmp_toml(
            """
            [telemetry]
            http_port = 65536
            """
        )
        with pytest.raises(ValueError, match="http_port"):
            load_config(p)


# ---------------------------------------------------------------------------
# RoverConfig wiring
# ---------------------------------------------------------------------------


class TestRoverConfigComposition:
    def test_all_sections_present(self):
        cfg = load_config()
        assert isinstance(cfg, RoverConfig)
        for name in (
            "general", "session", "lidar", "stepper", "imu", "gnss",
            "ntrip", "lora", "base_station_integration", "telemetry",
            "camera", "logging", "watchdog", "power", "calibration",
        ):
            assert hasattr(cfg, name), f"missing section {name}"

    def test_default_toml_loads_clean(self):
        """The shipped config/default.toml must round-trip without errors."""
        cfg = load_config(Path("config/default.toml"))
        assert cfg.session.profile == "personal"
        assert cfg.ntrip.enabled is False
        assert cfg.lora.role == "rtcm_rx+status_tx"
