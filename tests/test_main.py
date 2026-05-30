"""Smoke tests for the rover orchestrator.

These run off-Pi with all hardware-dependent sensors disabled — the goal is
to confirm that init/teardown wiring is correct and that the loop survives
sensor init failures.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from rover import main as main_mod


def _write_all_disabled_config(tmp_path: Path) -> Path:
    """Write a TOML that disables every sensor and every telemetry channel.

    This is the minimal valid config for an off-Pi bench run.
    """
    cfg = tmp_path / "rover_all_disabled.toml"
    cfg.write_text(
        f"""
[general]
device_name = "test-rover"
log_level = "WARNING"

[lidar]
enabled = false
port = "/dev/null"
baud = 230400
scan_rate_hz = 10

[stepper]
enabled = false
steps_per_rev = 3200
rpm = 1.0
step_interval_deg = 1.5
direction_pin = 17
step_pin = 27
enable_pin = 22

[imu]
enabled = false
bus = 1
address = 0x68
sample_rate_hz = 200
fusion_output_hz = 100
use_magnetometer = false
fusion_beta = 0.1

[gnss]
enabled = false
port = "/dev/null"
baud = 115200
rtcm_profile = "robust"
survey_in_duration_sec = 300
survey_in_accuracy_m = 0.02

[ntrip]
enabled = false
client_location = "pi"

[lora]
enabled = false
port = "/dev/null"
role = "disabled"

[base_station_integration]
enabled = false

[telemetry]
http_enabled = false

[camera]
enabled = false
resolution = [640, 480]
capture_cadence = 1
jpeg_quality = 85
output_folder = "images"

[logging]
output_dir = "{(tmp_path / 'data').as_posix()}"
session_prefix = "test"
format = "jsonl"
flush_interval_sec = 1.0
rotate_size_mb = 0
save_images = false

[watchdog]
enabled = false
timeout_sec = 30
heartbeat_interval_sec = 5

[power]
monitor_battery = false
battery_adc_channel = 0
low_battery_mv = 10500
critical_battery_mv = 10000
"""
    )
    return cfg


def test_run_all_disabled_clean_exit(tmp_path: Path) -> None:
    """All sensors disabled, all telemetry channels disabled — run should boot,
    idle, and shut down cleanly within the duration."""
    config_path = _write_all_disabled_config(tmp_path)
    exit_code = main_mod.run(config_path=config_path, duration_sec=1.5)
    assert exit_code == 0

    # Session directory should exist with scan.jsonl + metadata.json + a config copy
    data_dir = tmp_path / "data"
    sessions = sorted(data_dir.glob("test_*"))
    assert len(sessions) == 1, f"expected exactly one session dir, found {sessions}"
    session = sessions[0]
    assert (session / "scan.jsonl").exists()
    assert (session / "metadata.json").exists()
    assert (session / "config.toml").exists()


def test_external_stop_event_aborts_promptly(tmp_path: Path) -> None:
    """A stop event set from another thread should end the run quickly."""
    config_path = _write_all_disabled_config(tmp_path)
    stop = threading.Event()

    def _trip() -> None:
        time.sleep(0.5)
        stop.set()

    t = threading.Thread(target=_trip, daemon=True)
    t.start()

    start = time.monotonic()
    # Pass a generous duration; the external stop should win.
    exit_code = main_mod.run(
        config_path=config_path, duration_sec=10.0, stop_event=stop
    )
    elapsed = time.monotonic() - start

    assert exit_code == 0
    assert elapsed < 5.0, f"stop event took {elapsed:.1f}s — should be ~0.5s"


def test_sensor_init_failure_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    """If a sensor's constructor raises, the run should warn and continue."""
    from rover import main as main_to_patch

    class _Boom:
        def __init__(self, *_a, **_kw) -> None:
            raise RuntimeError("simulated sensor failure")

    # Patch in a sensor that explodes on construction; main should log + continue.
    monkeypatch.setattr(main_to_patch, "StepperMotor", _Boom)
    monkeypatch.setattr(main_to_patch, "LidarScanner", _Boom)
    monkeypatch.setattr(main_to_patch, "ImuDriver", _Boom)
    monkeypatch.setattr(main_to_patch, "GnssReceiver", _Boom)

    # Use a config that wants those sensors enabled — but log to a tmp dir.
    cfg = tmp_path / "enabled.toml"
    cfg.write_text(
        f"""
[lidar]
enabled = true

[stepper]
enabled = true

[imu]
enabled = true

[gnss]
enabled = true

[camera]
enabled = false

[ntrip]
enabled = false

[lora]
enabled = false
role = "disabled"

[base_station_integration]
enabled = false

[telemetry]
http_enabled = false

[watchdog]
enabled = false

[logging]
output_dir = "{(tmp_path / 'data').as_posix()}"
session_prefix = "boomtest"

[power]
monitor_battery = false
"""
    )

    exit_code = main_to_patch.run(config_path=cfg, duration_sec=1.0)
    assert exit_code == 0
