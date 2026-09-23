"""Smoke tests for the rover orchestrator.

These run off-Pi with all hardware-dependent sensors disabled — the goal is
to confirm that init/teardown wiring is correct and that the loop survives
sensor init failures.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

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
output_dir = "{(tmp_path / "data").as_posix()}"
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
    exit_code = main_mod.run(config_path=config_path, duration_sec=10.0, stop_event=stop)
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
output_dir = "{(tmp_path / "data").as_posix()}"
session_prefix = "boomtest"

[power]
monitor_battery = false
"""
    )

    exit_code = main_to_patch.run(config_path=cfg, duration_sec=1.0)
    assert exit_code == 0


def test_ready_notified_even_when_watchdog_disabled(tmp_path: Path, monkeypatch) -> None:
    """Type=notify units need READY=1 regardless of [watchdog].enabled (T1-002)."""
    from rover import watchdog as wd_mod

    sent: list[str] = []
    monkeypatch.setattr(wd_mod, "_sd_notify", sent.append)
    config_path = _write_all_disabled_config(tmp_path)  # has [watchdog] enabled = false
    assert main_mod.run(config_path=config_path, duration_sec=0.5) == 0
    assert "READY=1\n" in sent
    assert any(m == "WATCHDOG=1\n" for m in sent), "heartbeats must flow when disabled too"


def _enabled_lidar_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "lidar_on.toml"
    cfg.write_text(
        f"""
[lidar]
enabled = true

[stepper]
enabled = false

[imu]
enabled = false

[gnss]
enabled = false

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
output_dir = "{(tmp_path / "data").as_posix()}"
session_prefix = "gate"
"""
    )
    return cfg


class _FlakyLidar:
    """Stands in for LidarScanner: available, but every read raises OSError."""

    calls = 0

    def __init__(self, *_a, **_kw) -> None:
        pass

    @property
    def available(self) -> bool:
        return True

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def read_scan(self):
        type(self).calls += 1
        raise OSError(5, "simulated serial unplug")


def test_scan_loop_disables_sensor_after_repeated_oserror(tmp_path: Path, monkeypatch) -> None:
    """OSError from a read must not abort the run, and after 5 failures the
    sensor is skipped rather than re-read every iteration (T1-003)."""
    _FlakyLidar.calls = 0
    monkeypatch.setattr(main_mod, "LidarScanner", _FlakyLidar)
    # No stepper in this config, so the loop paces itself on the idle settle;
    # shrink it so 1.5 s yields well over five iterations.
    monkeypatch.setattr(main_mod, "_IDLE_SETTLE_SEC", 0.05)
    exit_code = main_mod.run(config_path=_enabled_lidar_config(tmp_path), duration_sec=1.5)
    assert exit_code == 0
    assert _FlakyLidar.calls == 5, (
        f"expected exactly 5 attempts before the gate trips, got {_FlakyLidar.calls}"
    )


def test_sensor_gate_trips_once_and_resets_on_success() -> None:
    gate = main_mod._SensorGate("lidar", limit=3)
    assert gate.record_failure(OSError("x")) is False
    assert gate.record_failure(OSError("x")) is False
    assert gate.record_failure(OSError("x")) is True  # trips on the 3rd
    assert gate.tripped
    assert gate.record_failure(OSError("x")) is False  # already tripped: no re-warn
    gate.record_success()
    assert not gate.tripped


def test_settle_uses_stop_event(tmp_path: Path, monkeypatch) -> None:
    """The settle pause must be interruptible: run() with a 1.0 s idle settle
    should return well under 1 s after stop is set (T1-038 hygiene, in scope here)."""
    config_path = _write_all_disabled_config(tmp_path)
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    start = time.monotonic()
    assert main_mod.run(config_path=config_path, duration_sec=10.0, stop_event=stop) == 0
    assert time.monotonic() - start < 1.5


def test_telemetry_constructor_failure_still_tears_down(tmp_path: Path, monkeypatch) -> None:
    """A failure after sensors + logger are up must still write scan_abort and
    close the session (T1-029)."""
    import json

    class _BoomRouter:
        def __init__(self, *_a, **_kw) -> None:
            raise RuntimeError("simulated telemetry failure")

    monkeypatch.setattr(main_mod, "TelemetryRouter", _BoomRouter)
    config_path = _write_all_disabled_config(tmp_path)
    exit_code = main_mod.run(config_path=config_path, duration_sec=0.5)
    assert exit_code == 1

    session = next((tmp_path / "data").glob("test_*"))
    events = [
        json.loads(line)["event"]
        for line in (session / "scan.jsonl").read_text().splitlines()
        if '"event"' in line
    ]
    assert events[-1] == "scan_abort", events
    assert (session / "metadata.json").exists(), "logger.stop() must still run"


class _CountingCamera:
    captures = 0

    def __init__(self, *_a, **_kw) -> None:
        pass

    @property
    def available(self) -> bool:
        return True

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def should_capture(self, step_index: int) -> bool:
        return True

    def capture(self, output_dir, step_index) -> str:
        type(self).captures += 1
        return f"images/img_{step_index:06d}.jpg"


def test_save_images_false_prevents_capture(tmp_path: Path, monkeypatch) -> None:
    """[logging].save_images = false must stop captures, not just skip a mkdir (T1-033)."""
    _CountingCamera.captures = 0
    monkeypatch.setattr(main_mod, "Camera", _CountingCamera)
    monkeypatch.setattr(main_mod, "_CAMERA_IMPORT_OK", True)
    monkeypatch.setattr(main_mod, "_IDLE_SETTLE_SEC", 0.05)  # many iterations in 1 s
    cfg = tmp_path / "cam.toml"
    cfg.write_text(
        f"""
[camera]
enabled = true

[lidar]
enabled = false
[stepper]
enabled = false
[imu]
enabled = false
[gnss]
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
output_dir = "{(tmp_path / "data").as_posix()}"
session_prefix = "noimg"
save_images = false
"""
    )
    assert main_mod.run(config_path=cfg, duration_sec=1.0) == 0
    assert _CountingCamera.captures == 0
