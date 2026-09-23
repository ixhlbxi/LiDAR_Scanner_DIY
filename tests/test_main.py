"""Smoke tests for the rover orchestrator.

These run off-Pi with all hardware-dependent sensors disabled — the goal is
to confirm that init/teardown wiring is correct and that the loop survives
sensor init failures.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from rover import main as main_mod

# Make scripts/ importable as `scripts.georef` for the round-trip test below
# (mirrors tests/test_georef.py's own sys.path setup). Importing georef.py
# itself never requires numpy — only the functions the round-trip test calls
# do, which is why that test guards with pytest.importorskip("numpy").
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts import georef  # noqa: E402


def _write_all_disabled_config(tmp_path: Path) -> Path:
    """Write a TOML that disables every sensor and every telemetry channel.

    Keeps only keys that differ from defaults.
    """
    cfg = tmp_path / "rover_all_disabled.toml"
    cfg.write_text(
        f"""
[general]
device_name = "test-rover"
log_level = "WARNING"

[lidar]
enabled = false

[stepper]
enabled = false

[imu]
enabled = false

[gnss]
enabled = false

[camera]
enabled = false

[lora]
enabled = false

[watchdog]
enabled = false

[logging]
output_dir = "{(tmp_path / "data").as_posix()}"
session_prefix = "test"
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

    def read_scan(self, discard_stale: bool = True):
        type(self).calls += 1
        raise OSError(5, "simulated serial unplug")


def test_scan_loop_disables_sensor_after_repeated_oserror(tmp_path: Path, monkeypatch) -> None:
    """OSError from a read must not abort the run, and after 5 failures the
    sensor is skipped rather than re-read every iteration (T1-003). The trip
    itself must also be visible in scan.jsonl, not just the journal (Important 4)."""
    import json

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

    session = next((tmp_path / "data").glob("gate_*"))
    records = [
        json.loads(line) for line in (session / "scan.jsonl").read_text().splitlines() if line
    ]
    disabled_events = [r for r in records if r.get("event") == "sensor_disabled"]
    assert len(disabled_events) == 1, disabled_events
    assert disabled_events[0]["details"]["sensor"] == "lidar"


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
    """The settle pause must be interruptible (T1-003): with the idle settle
    forced to 5 s and stop set 0.2 s in, only a `stop_event.wait`-style
    interruptible wait can return in under 2 s — a plain `time.sleep(5)`
    settle would not."""
    monkeypatch.setattr(main_mod, "_IDLE_SETTLE_SEC", 5.0)
    config_path = _write_all_disabled_config(tmp_path)
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    start = time.monotonic()
    assert main_mod.run(config_path=config_path, duration_sec=10.0, stop_event=stop) == 0
    assert time.monotonic() - start < 2.0


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
    """[logging].save_images = false must stop captures, not just skip a mkdir (T1-031)."""
    _CountingCamera.captures = 0
    monkeypatch.setattr(main_mod, "Camera", _CountingCamera)
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


def test_save_images_true_captures_and_logs(tmp_path: Path, monkeypatch) -> None:
    """The enabled-camera success path — capture, gate reset, and the
    scan.jsonl camera record — must actually run (Finding 3 follow-up to T1-031)."""
    import json

    _CountingCamera.captures = 0
    monkeypatch.setattr(main_mod, "Camera", _CountingCamera)
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
session_prefix = "withimg"
save_images = true
"""
    )
    assert main_mod.run(config_path=cfg, duration_sec=1.0) == 0
    assert _CountingCamera.captures > 0

    session = next((tmp_path / "data").glob("withimg_*"))
    lines = (session / "scan.jsonl").read_text().splitlines()
    camera_records = [json.loads(line) for line in lines if '"type":"camera"' in line]
    assert camera_records, "expected at least one camera record in scan.jsonl"
    assert any(r["filename"].startswith("images/") for r in camera_records)


class _FakeScan:
    def __init__(self, n: int = 3) -> None:
        from rover.lidar import LidarPoint, LidarScan

        self.scan = LidarScan(
            points=[
                LidarPoint(angle=10.0 * i, distance=1.0 + i, intensity=100 + i) for i in range(n)
            ],
            lidar_ms_start=1000,
            lidar_ms_end=1090,
        )


class _StaticLidar:
    calls: list[bool] = []

    def __init__(self, *_a, **_kw) -> None:
        pass

    @property
    def available(self) -> bool:
        return True

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def read_scan(self, discard_stale: bool = True):
        type(self).calls.append(discard_stale)
        return _FakeScan().scan


class _FakeStepper:
    def __init__(self, *_a, **_kw) -> None:
        self._angle = 0.0

    @property
    def available(self) -> bool:
        return True

    @property
    def current_angle(self) -> float:
        return self._angle

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def step(self, steps: int) -> None:
        self._angle += steps * (360.0 / 3200)


class _FakeImu:
    mag_calls: list[bool] = []

    def __init__(self, *_a, **_kw) -> None:
        pass

    @property
    def available(self) -> bool:
        return True

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def enable_magnetometer(self, enable: bool) -> None:
        type(self).mag_calls.append(enable)

    def drain(self):
        from rover.imu import ImuSample

        return [
            ImuSample(
                timestamp=1.0,
                accel=(0, 0, 9.81),
                gyro=(0, 0, 0),
                mag=None,
                orientation=(1, 0, 0, 0),
            ),
            ImuSample(
                timestamp=1.005,
                accel=(0, 0, 9.81),
                gyro=(0, 0, 0),
                mag=(1, 2, 3),
                orientation=(1, 0, 0, 0),
            ),
        ]


def _stage3_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "s3.toml"
    cfg.write_text(
        f"""
[lidar]
enabled = true
scan_rate_hz = 10

[stepper]
enabled = true
steps_per_rev = 3200
step_interval_deg = 1.125

[imu]
enabled = true
use_magnetometer = true

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
session_prefix = "s3"
"""
    )
    return cfg


def test_records_are_columnar_with_mast_angle_and_imu_batches(tmp_path: Path, monkeypatch) -> None:
    import json

    _StaticLidar.calls = []
    _FakeImu.mag_calls = []
    monkeypatch.setattr(main_mod, "LidarScanner", _StaticLidar)
    monkeypatch.setattr(main_mod, "StepperMotor", _FakeStepper)
    monkeypatch.setattr(main_mod, "ImuDriver", _FakeImu)
    assert main_mod.run(config_path=_stage3_config(tmp_path), duration_sec=1.5) == 0

    session = next((tmp_path / "data").glob("s3_*"))
    recs = [json.loads(line) for line in (session / "scan.jsonl").read_text().splitlines() if line]
    lidar = [r for r in recs if r["type"] == "lidar"]
    imu = [r for r in recs if r["type"] == "imu"]
    assert lidar, "no lidar records"
    r = lidar[0]
    assert r["angle"] == [0.0, 10.0, 20.0] and r["distance"] == [1.0, 2.0, 3.0]
    assert r["intensity"] == [100, 101, 102]
    assert r["lidar_ms_start"] == 1000 and r["lidar_ms_end"] == 1090
    assert r["mast_angle_deg"] == pytest.approx(1.125)  # after the first 10-microstep move
    assert "points" not in r
    assert len(lidar) >= 2 and lidar[1]["mast_angle_deg"] == pytest.approx(2.25)
    # IMU batches
    assert imu, "no imu records"
    b = imu[0]
    assert b["t"] == [1.0, 1.005] and b["mag"] == [None, [1, 2, 3]]
    assert b["orientation"][0] == [1, 0, 0, 0]
    # DEC-013: mag disabled before each step, re-enabled after settle
    assert _FakeImu.mag_calls[:2] == [False, True]
    # stale discard after a step
    assert _StaticLidar.calls and all(_StaticLidar.calls)


def test_round_trip_produces_points(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: run() writes a real session with the stage 3 fakes, then
    scripts/georef.py must load it and assemble a nonzero point cloud whose
    lidar record count matches what was actually captured during the run."""
    pytest.importorskip("numpy")

    _StaticLidar.calls = []
    _FakeImu.mag_calls = []
    monkeypatch.setattr(main_mod, "LidarScanner", _StaticLidar)
    monkeypatch.setattr(main_mod, "StepperMotor", _FakeStepper)
    monkeypatch.setattr(main_mod, "ImuDriver", _FakeImu)
    assert main_mod.run(config_path=_stage3_config(tmp_path), duration_sec=1.0) == 0

    session = next((tmp_path / "data").glob("s3_*"))
    session_data = georef.load_session(session)
    xyz, intensity, _origin = georef.session_to_pointcloud(session_data)

    assert len(xyz) > 0
    assert len(intensity) == len(xyz)
    assert len(session_data.lidar_records) == len(_StaticLidar.calls)


def test_run_aborts_on_401_in_arm_group(tmp_path: Path, monkeypatch) -> None:
    """BASE_STATION_INTEGRATION §7: refuse to start in arm_group on a 401 (T1-004)."""
    import socket
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _serve():
        conn, _ = srv.accept()
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
        conn.close()
        srv.close()

    threading.Thread(target=_serve, daemon=True).start()

    class _FakeGnss:
        def __init__(self, *_a, **_kw): ...
        @property
        def available(self):
            return True

        def start(self): ...
        def stop(self): ...
        def latest_fix(self):
            return None

        def write_rtcm(self, b): ...

    monkeypatch.setattr(main_mod, "GnssReceiver", _FakeGnss)
    cfg = tmp_path / "ag.toml"
    cfg.write_text(
        f"""
[session]
profile = "arm_group"
project_code = "TEST"
target_crs_epsg = 6346
[base_station_integration]
enabled = true
status_json_path = "{(tmp_path / "status.json").as_posix()}"
[gnss]
enabled = true
[ntrip]
enabled = true
client_location = "pi"
caster_host = "127.0.0.1"
caster_port = {port}
mountpoint = "ARM_BASE"
[lidar]
enabled = false
[stepper]
enabled = false
[imu]
enabled = false
[camera]
enabled = false
[lora]
enabled = false
role = "disabled"
[telemetry]
http_enabled = false
[watchdog]
enabled = false
[logging]
output_dir = "{(tmp_path / "data").as_posix()}"
session_prefix = "ag"
"""
    )
    assert main_mod.run(config_path=cfg, duration_sec=5.0) == 4


class _BrokenStepper(_FakeStepper):
    fails = 0

    def step(self, steps: int) -> None:
        type(self).fails += 1
        raise RuntimeError("stall")


def test_stepper_failures_are_gated_and_still_publish(tmp_path: Path, monkeypatch) -> None:
    """A failing stepper must not spam warnings forever nor skip telemetry (S2-R3)."""
    import json

    _BrokenStepper.fails = 0
    published: list = []
    monkeypatch.setattr(main_mod, "StepperMotor", _BrokenStepper)
    monkeypatch.setattr(main_mod, "LidarScanner", _StaticLidar)
    monkeypatch.setattr(main_mod, "ImuDriver", _FakeImu)

    real_router = main_mod.TelemetryRouter

    class _SpyRouter(real_router):
        def publish(self, status):
            published.append(status.scan_state)
            return super().publish(status)

    monkeypatch.setattr(main_mod, "TelemetryRouter", _SpyRouter)
    assert main_mod.run(config_path=_stage3_config(tmp_path), duration_sec=4.0) == 0
    assert _BrokenStepper.fails == 5, "gate must stop retrying after 5 failures"
    assert any(s == main_mod.SCAN_ERROR for s in published), "SCAN_ERROR must be published"
    session = next((tmp_path / "data").glob("s3_*"))
    events = [
        json.loads(line)["event"]
        for line in (session / "scan.jsonl").read_text().splitlines()
        if '"event"' in line
    ]
    assert "sensor_disabled" in events


def test_scan_constants_come_from_lora_protocol():
    from rover import lora_protocol

    assert main_mod.SCAN_ERROR is lora_protocol.SCAN_ERROR


# ---------------------------------------------------------------------------
# Final review I4 — scan_state must persist through a mid-session NTRIP fatal
# ---------------------------------------------------------------------------


class _LateFatalNtrip:
    """Fakes NtripClient: healthy through the startup grace check, then
    fatal_error flips non-None partway through the scan loop — a caster
    rejection discovered mid-session, not at connect time."""

    def __init__(self, config, rtcm_sink=None, gga_source=None) -> None:
        from rover.ntrip import NtripStats

        self.stats = NtripStats(connected=True)
        self._go_fatal_at: float | None = None

    def start(self) -> None:
        self._go_fatal_at = time.monotonic() + 0.35

    def stop(self) -> None:
        pass

    @property
    def fatal_error(self):
        if self._go_fatal_at is not None and time.monotonic() >= self._go_fatal_at:
            return "401 Unauthorized (simulated mid-session)"
        return None


class _FakeGnssMinimal:
    def __init__(self, *_a, **_kw) -> None: ...

    @property
    def available(self) -> bool:
        return True

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def latest_fix(self):
        return None

    def write_rtcm(self, b) -> None: ...


def test_scan_state_persists_through_mid_session_ntrip_fatal(tmp_path: Path, monkeypatch) -> None:
    """scan_state must be derived each iteration from persistent conditions
    (tripped stepper gate OR an NTRIP fatal error), not left as whatever the
    per-step logic set: previously, once the stepper resumed succeeding, the
    next healthy step reset scan_state to SCAN_SCANNING and silently cleared
    an unresolved NTRIP fatal that had only been logged once (final review
    I4)."""
    monkeypatch.setattr(main_mod, "StepperMotor", _FakeStepper)
    monkeypatch.setattr(main_mod, "GnssReceiver", _FakeGnssMinimal)
    monkeypatch.setattr(main_mod, "NtripClient", _LateFatalNtrip)
    monkeypatch.setattr(main_mod, "_NTRIP_FATAL_GRACE_SEC", 0.02)

    published: list = []
    real_router = main_mod.TelemetryRouter

    class _SpyRouter(real_router):
        def publish(self, status):
            published.append(status.scan_state)
            return super().publish(status)

    monkeypatch.setattr(main_mod, "TelemetryRouter", _SpyRouter)

    cfg = tmp_path / "i4.toml"
    cfg.write_text(
        f"""
[stepper]
enabled = true
steps_per_rev = 3200
step_interval_deg = 1.125

[lidar]
enabled = false
[imu]
enabled = false
[camera]
enabled = false

[gnss]
enabled = true

[ntrip]
enabled = true
client_location = "pi"
caster_host = "127.0.0.1"
caster_port = 1
mountpoint = "ARM_BASE"

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
session_prefix = "i4"
"""
    )

    exit_code = main_mod.run(config_path=cfg, duration_sec=1.3)
    assert exit_code == 0  # a mid-session fatal does not abort the run

    assert main_mod.SCAN_ERROR in published, f"SCAN_ERROR must be published: {published}"
    first_error_idx = published.index(main_mod.SCAN_ERROR)
    tail = published[first_error_idx:]
    assert len(tail) >= 3, f"expected SCAN_ERROR to persist across several iterations: {published}"
    assert all(s == main_mod.SCAN_ERROR for s in tail), (
        f"a healthy step must not clear an unresolved NTRIP fatal: {published}"
    )
