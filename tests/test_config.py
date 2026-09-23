"""Unit tests for rover.config — runs anywhere, no hardware required."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from rover.config import (
    RoverConfig,
    load_config,
)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_load_defaults_no_file(self):
        cfg = load_config()
        assert isinstance(cfg, RoverConfig)

    def test_default_values(self):
        cfg = load_config()
        assert cfg.general.device_name == "rover-01"
        assert cfg.general.log_level == "INFO"
        assert cfg.lidar.baud == 230400
        assert cfg.stepper.steps_per_rev == 3200
        assert cfg.imu.address == 0x68
        assert cfg.camera.resolution == (1920, 1080)

    def test_calibration_defaults_are_none(self):
        cfg = load_config()
        assert cfg.calibration.lidar_to_imu_translation is None
        assert cfg.calibration.lidar_to_imu_rotation is None
        assert cfg.calibration.imu_to_gnss_translation is None


# ---------------------------------------------------------------------------
# File loading and merge
# ---------------------------------------------------------------------------


class TestFileLoading:
    def test_load_from_default_toml(self):
        cfg = load_config(Path("config/default.toml"))
        assert cfg.general.device_name == "rover-01"

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config(Path("/nonexistent/config.toml"))

    def test_override_merges_over_defaults(self, tmp_toml):
        p = tmp_toml("""
            [general]
            device_name = "my-rover"
        """)
        cfg = load_config(p)
        assert cfg.general.device_name == "my-rover"
        # Other defaults preserved
        assert cfg.general.log_level == "INFO"
        assert cfg.lidar.baud == 230400

    def test_partial_section_override(self, tmp_toml):
        p = tmp_toml("""
            [lidar]
            scan_rate_hz = 5
        """)
        cfg = load_config(p)
        assert cfg.lidar.scan_rate_hz == 5
        assert cfg.lidar.baud == 230400  # default preserved

    def test_missing_section_uses_defaults(self, tmp_toml):
        p = tmp_toml("""
            [general]
            device_name = "test"
        """)
        cfg = load_config(p)
        assert cfg.watchdog.enabled is True


# ---------------------------------------------------------------------------
# Unknown keys (strict mode)
# ---------------------------------------------------------------------------


class TestUnknownKeys:
    def test_unknown_section_raises(self, tmp_toml):
        p = tmp_toml("""
            [liidar]
            enabled = true
        """)
        with pytest.raises(ValueError, match="Unknown config section.*liidar"):
            load_config(p)

    def test_unknown_section_suggests(self, tmp_toml):
        p = tmp_toml("""
            [liidar]
            enabled = true
        """)
        with pytest.raises(ValueError, match="Did you mean 'lidar'"):
            load_config(p)

    def test_unknown_key_in_section_raises(self, tmp_toml):
        p = tmp_toml("""
            [stepper]
            enabel_pin = 22
        """)
        with pytest.raises(ValueError, match="Unknown key 'enabel_pin' in \\[stepper\\]"):
            load_config(p)

    def test_unknown_key_suggests(self, tmp_toml):
        p = tmp_toml("""
            [stepper]
            enabel_pin = 22
        """)
        with pytest.raises(ValueError, match="Did you mean 'enable_pin'"):
            load_config(p)


# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------


class TestTypeValidation:
    def test_wrong_type_string_for_int(self, tmp_toml):
        p = tmp_toml("""
            [lidar]
            baud = "fast"
        """)
        with pytest.raises(ValueError, match="\\[lidar\\] baud"):
            load_config(p)

    def test_wrong_type_bool_for_string(self, tmp_toml):
        p = tmp_toml("""
            [general]
            device_name = 42
        """)
        with pytest.raises(ValueError, match="\\[general\\] device_name"):
            load_config(p)


# ---------------------------------------------------------------------------
# Range validation
# ---------------------------------------------------------------------------


class TestRangeValidation:
    def test_scan_rate_too_high(self, tmp_toml):
        p = tmp_toml("""
            [lidar]
            scan_rate_hz = 50
        """)
        with pytest.raises(ValueError, match="scan_rate_hz"):
            load_config(p)

    def test_scan_rate_too_low(self, tmp_toml):
        p = tmp_toml("""
            [lidar]
            scan_rate_hz = 0
        """)
        with pytest.raises(ValueError, match="scan_rate_hz"):
            load_config(p)

    def test_jpeg_quality_out_of_range(self, tmp_toml):
        p = tmp_toml("""
            [camera]
            jpeg_quality = 101
        """)
        with pytest.raises(ValueError, match="jpeg_quality"):
            load_config(p)

    def test_spreading_factor_out_of_range(self, tmp_toml):
        p = tmp_toml("""
            [lora]
            spreading_factor = 13
        """)
        with pytest.raises(ValueError, match="spreading_factor"):
            load_config(p)

    def test_fusion_beta_out_of_range(self, tmp_toml):
        p = tmp_toml("""
            [imu]
            fusion_beta = 1.5
        """)
        with pytest.raises(ValueError, match="fusion_beta"):
            load_config(p)

    def test_gpio_pin_out_of_range(self, tmp_toml):
        p = tmp_toml("""
            [stepper]
            step_pin = 40
        """)
        with pytest.raises(ValueError, match="step_pin"):
            load_config(p)

    def test_negative_baud(self, tmp_toml):
        p = tmp_toml("""
            [lidar]
            baud = -1
        """)
        with pytest.raises(ValueError, match="baud"):
            load_config(p)


# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------


class TestEnumValidation:
    def test_invalid_log_level(self, tmp_toml):
        p = tmp_toml("""
            [general]
            log_level = "VERBOSE"
        """)
        with pytest.raises(ValueError, match="log_level"):
            load_config(p)

    def test_invalid_coding_rate(self, tmp_toml):
        p = tmp_toml("""
            [lora]
            coding_rate = "4/9"
        """)
        with pytest.raises(ValueError, match="coding_rate"):
            load_config(p)

    def test_invalid_bandwidth(self, tmp_toml):
        p = tmp_toml("""
            [lora]
            bandwidth_khz = 200
        """)
        with pytest.raises(ValueError, match="bandwidth_khz"):
            load_config(p)


# ---------------------------------------------------------------------------
# Special field handling
# ---------------------------------------------------------------------------


class TestSpecialFields:
    def test_imu_address_hex_string(self, tmp_toml):
        p = tmp_toml("""
            [imu]
            address = "0x69"
        """)
        cfg = load_config(p)
        assert cfg.imu.address == 0x69

    def test_imu_address_int(self, tmp_toml):
        p = tmp_toml("""
            [imu]
            address = 0x69
        """)
        cfg = load_config(p)
        assert cfg.imu.address == 0x69

    def test_resolution_must_be_pair(self, tmp_toml):
        p = tmp_toml("""
            [camera]
            resolution = [1920]
        """)
        with pytest.raises(ValueError, match="resolution"):
            load_config(p)

    def test_resolution_must_be_positive(self, tmp_toml):
        p = tmp_toml("""
            [camera]
            resolution = [0, 1080]
        """)
        with pytest.raises(ValueError, match="resolution"):
            load_config(p)

    def test_resolution_stored_as_tuple(self):
        cfg = load_config()
        assert isinstance(cfg.camera.resolution, tuple)

    def test_log_level_normalized_to_upper(self, tmp_toml):
        p = tmp_toml("""
            [general]
            log_level = "debug"
        """)
        cfg = load_config(p)
        assert cfg.general.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


class TestCalibration:
    def test_calibration_with_values(self, tmp_toml):
        p = tmp_toml("""
            [calibration]
            lidar_to_imu_translation = [0.0, 0.0, 0.05]
            lidar_to_imu_rotation = [1.0, 0.0, 0.0, 0.0]
            imu_to_gnss_translation = [0.0, 0.0, 0.30]
        """)
        cfg = load_config(p)
        assert cfg.calibration.lidar_to_imu_translation == [0.0, 0.0, 0.05]
        assert cfg.calibration.lidar_to_imu_rotation == [1.0, 0.0, 0.0, 0.0]

    def test_calibration_wrong_length(self, tmp_toml):
        p = tmp_toml("""
            [calibration]
            lidar_to_imu_translation = [0.0, 0.0]
        """)
        with pytest.raises(ValueError, match="lidar_to_imu_translation"):
            load_config(p)

    def test_calibration_rotation_wrong_length(self, tmp_toml):
        p = tmp_toml("""
            [calibration]
            lidar_to_imu_rotation = [1.0, 0.0, 0.0]
        """)
        with pytest.raises(ValueError, match="lidar_to_imu_rotation"):
            load_config(p)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_frozen_top_level(self):
        cfg = load_config()
        with pytest.raises(FrozenInstanceError):
            cfg.general = None  # type: ignore[misc]

    def test_frozen_section(self):
        cfg = load_config()
        with pytest.raises(FrozenInstanceError):
            cfg.lidar.baud = 9600  # type: ignore[misc]


# ---------------------------------------------------------------------------
# to_dict()
# ---------------------------------------------------------------------------


class TestToDict:
    def test_roundtrip_structure(self):
        cfg = load_config()
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert "general" in d
        assert "lidar" in d
        assert d["general"]["device_name"] == "rover-01"

    def test_resolution_is_list(self):
        cfg = load_config()
        d = cfg.to_dict()
        assert isinstance(d["camera"]["resolution"], list)
        assert d["camera"]["resolution"] == [1920, 1080]


# ---------------------------------------------------------------------------
# Stage 3 Config (T1-041, T1-007)
# ---------------------------------------------------------------------------


class TestStage3Config:
    def test_mag_offset_parsed(self, tmp_toml):
        p = tmp_toml("""
            [calibration]
            mag_offset = [12.5, -3.0, 40.0]
        """)
        cfg = load_config(p)
        assert cfg.calibration.mag_offset == [12.5, -3.0, 40.0]

    def test_mag_offset_rejects_wrong_length(self, tmp_toml):
        p = tmp_toml("""
            [calibration]
            mag_offset = [1.0, 2.0]
        """)
        with pytest.raises(ValueError, match=r"\[calibration\] mag_offset"):
            load_config(p)

    def test_default_magnetometer_off_until_calibrated(self):
        cfg = load_config()
        assert cfg.imu.use_magnetometer is False
        assert cfg.calibration.mag_offset is None

    def test_step_interval_must_be_multiple_of_microstep(self, tmp_toml):
        p = tmp_toml("""
            [stepper]
            steps_per_rev = 3200
            step_interval_deg = 1.5
        """)
        with pytest.raises(ValueError, match=r"step_interval_deg.*multiple of 0\.1125"):
            load_config(p)

    def test_default_step_interval_is_exact(self):
        cfg = load_config()
        per_step = 360.0 / cfg.stepper.steps_per_rev
        assert cfg.stepper.step_interval_deg / per_step == pytest.approx(
            round(cfg.stepper.step_interval_deg / per_step)
        )

    def test_step_interval_error_names_both_neighbors(self, tmp_toml):
        """step_interval_deg error message should name both integer-multiple neighbours."""
        p = tmp_toml("""
            [stepper]
            steps_per_rev = 3200
            step_interval_deg = 1.5
        """)
        with pytest.raises(ValueError) as exc_info:
            load_config(p)
        error_msg = str(exc_info.value)
        # The per-step is 360/3200 = 0.1125
        # 1.5 / 0.1125 = 13.333...
        # floor_n = 13, ceil_n = 14
        # Valid values: 13 * 0.1125 = 1.4625, 14 * 0.1125 = 1.575
        assert "1.4625" in error_msg
        assert "1.575" in error_msg

    def test_mag_offset_rejects_bool_value(self, tmp_toml):
        """mag_offset must not accept bool values (even though isinstance(True, int) is True)."""
        p = tmp_toml("""
            [calibration]
            mag_offset = [1.0, true, 2.0]
        """)
        with pytest.raises(ValueError, match=r"\[calibration\] mag_offset.*bool"):
            load_config(p)

    def test_mag_offset_rejects_infinite_value(self, tmp_toml):
        """mag_offset must not accept inf or nan."""
        p = tmp_toml("""
            [calibration]
            mag_offset = [0.0, 0.0, inf]
        """)
        with pytest.raises(ValueError, match=r"\[calibration\] mag_offset.*finite"):
            load_config(p)


# ---------------------------------------------------------------------------
# Dead Config Removal (T1-041)
# ---------------------------------------------------------------------------


class TestDeadConfigRemoved:
    def test_power_section_is_unknown(self, tmp_toml):
        """[power] section should be rejected as unknown."""
        p = tmp_toml("""
            [power]
            monitor_battery = true
        """)
        with pytest.raises(ValueError, match="power"):
            load_config(p)

    def test_gnss_survey_in_duration_is_unknown(self, tmp_toml):
        """[gnss] survey_in_duration_sec should be rejected as unknown."""
        p = tmp_toml("""
            [gnss]
            survey_in_duration_sec = 300
        """)
        with pytest.raises(ValueError, match="survey_in_duration_sec"):
            load_config(p)

    def test_gnss_survey_in_accuracy_is_unknown(self, tmp_toml):
        """[gnss] survey_in_accuracy_m should be rejected as unknown."""
        p = tmp_toml("""
            [gnss]
            survey_in_accuracy_m = 0.02
        """)
        with pytest.raises(ValueError, match="survey_in_accuracy_m"):
            load_config(p)

    def test_gnss_rtcm_profile_is_unknown(self, tmp_toml):
        """[gnss] rtcm_profile should be rejected as unknown."""
        p = tmp_toml("""
            [gnss]
            rtcm_profile = "robust"
        """)
        with pytest.raises(ValueError, match="rtcm_profile"):
            load_config(p)

    def test_imu_fusion_output_hz_is_unknown(self, tmp_toml):
        """[imu] fusion_output_hz should be rejected as unknown."""
        p = tmp_toml("""
            [imu]
            fusion_output_hz = 100
        """)
        with pytest.raises(ValueError, match="fusion_output_hz"):
            load_config(p)

    def test_logging_format_is_unknown(self, tmp_toml):
        """[logging] format should be rejected as unknown."""
        p = tmp_toml("""
            [logging]
            format = "jsonl"
        """)
        with pytest.raises(ValueError, match="format"):
            load_config(p)

    def test_no_power_attribute(self):
        """RoverConfig should not have a .power attribute."""
        cfg = load_config()
        assert not hasattr(cfg, "power")
