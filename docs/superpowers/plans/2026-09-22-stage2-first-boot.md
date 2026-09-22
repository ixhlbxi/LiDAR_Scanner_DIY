# Stage 2 — First-Boot Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After `sudo deploy/install.sh` on a fresh Raspberry Pi OS Bookworm, `rover.service` reaches READY under systemd, survives a sensor unplug, and stops cleanly; the logger never silently stops writing.

**Architecture:** Eleven tasks on branch `fix/stage2-first-boot`, each a TDD cycle. The watchdog becomes unconditional and process-killing; the acquisition loop gains a per-sensor failure gate; telemetry/NTRIP/watchdog setup moves inside the teardown guard; logger flush becomes fault-tolerant with a bounded queue and fsync; deploy files agree with the config on where sessions are written.

**Tech Stack:** Python 3.11 stdlib (`threading`, `queue`, `os`, `socket`, `subprocess`), pytest, pyubx2 (dev only), systemd unit directives.

**Spec:** `docs/superpowers/specs/2026-09-22-audit-remediation-design.md` §4

## Global Constraints

- Python 3.11+, stdlib preferred; `pyubx2` is added to the `dev` extra only (it is already in `pi`).
- Sensors that fail must log a warning and mark themselves unavailable; the system never crashes on a sensor fault (CLAUDE.md §5).
- Repo path contains spaces and a comma: always quote it.
- Use the Write tool for any file content containing backslashes or backticks.
- After stage 1, run `python -m ruff format` and `python -m ruff check` on touched files before each commit; both must be clean.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Test count after stage 1 is measured at its merge (plan expects 279); it must not go down.
- Finding IDs closed: T1-001, T1-002, T1-003, T1-005, T1-006, T1-011, T1-027, T1-029, T1-032, T1-033, T2-001, T2-002, T2-003, T2-004, part of T2-005, D-016.

## Review Focus

1. **A sensor that fails on every read** (LiDAR cable pulled mid-session) must degrade the session, not spin the loop at full speed logging one DEBUG line per iteration forever. Pinned by Task 3 step 1 (`test_scan_loop_disables_sensor_after_repeated_oserror`).
2. **Disk full mid-session** must leave the flush timer alive and the process running so telemetry keeps publishing. Pinned by Task 7 step 1 (`test_flush_failure_keeps_timer_alive`).
3. **`[watchdog] enabled = false` under systemd** must still send READY and WATCHDOG pings. Pinned by Task 2 step 1.
4. **`systemctl stop` while `read_scan()` is blocking** should not take longer than one LiDAR timeout (5 s) plus settle. Pinned by Task 3 step 1 (`test_settle_uses_stop_event`).
5. **`install.sh` run twice** must not overwrite an operator-edited `/etc/rover/config.toml`. Pinned by Task 10 step 1 (static test asserts the `if [[ ! -f` guard) and the checklist in Task 11.

---

### Task 1: Watchdog kills the process and reuses its notify socket

**Files:**
- Modify: `src/rover/watchdog.py:47-76`
- Test: `tests/test_watchdog.py`

**Interfaces:**
- Produces: `_default_on_timeout()` calls `os._exit(2)` after `logging.shutdown()`. `_sd_notify(message: str) -> None` keeps one module-level connected socket. Unchanged public API: `Watchdog(config, on_timeout=None)`, `.start()`, `.stop()`, `.heartbeat()`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_watchdog.py`)

```python
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from rover import watchdog as wd_mod


def test_default_timeout_exits_process_with_code_2() -> None:
    """The default callback must end the PROCESS, not just the monitor thread (T1-001)."""
    script = (
        "import time\n"
        "from rover.config import WatchdogConfig\n"
        "from rover.watchdog import Watchdog\n"
        "wd = Watchdog(WatchdogConfig(enabled=True, timeout_sec=1, heartbeat_interval_sec=1))\n"
        "wd.start()\n"
        "time.sleep(10)\n"  # never heartbeats; must be killed long before this
        "print('STILL ALIVE')\n"
    )
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=8,
        env={**os.environ, "PYTHONPATH": src_dir},
    )
    assert proc.returncode == 2, proc.stderr
    assert "STILL ALIVE" not in proc.stdout


def test_sd_notify_reuses_one_socket(monkeypatch, tmp_path) -> None:
    """One connected datagram socket per process, not one per heartbeat."""
    monkeypatch.setenv("NOTIFY_SOCKET", "@rover-test-notify")
    wd_mod._reset_notify_socket_for_tests()
    fake = mock.MagicMock()
    with mock.patch("rover.watchdog.socket.socket", return_value=fake) as ctor:
        wd_mod._sd_notify("READY=1\n")
        wd_mod._sd_notify("WATCHDOG=1\n")
        wd_mod._sd_notify("WATCHDOG=1\n")
    assert ctor.call_count == 1
    assert fake.sendall.call_count == 3
    wd_mod._reset_notify_socket_for_tests()
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_watchdog.py -q -k "default_timeout or reuses_one_socket"
```

Expected: `test_default_timeout_exits_process_with_code_2` FAIL (returncode 0, "STILL ALIVE" printed); `test_sd_notify_reuses_one_socket` FAIL with `AttributeError: _reset_notify_socket_for_tests`.

- [ ] **Step 3: Implement**

Replace the `_sd_notify` function and `_default_on_timeout` in `src/rover/watchdog.py` with:

```python
_notify_sock: socket.socket | None = None
_notify_lock = threading.Lock()


def _reset_notify_socket_for_tests() -> None:
    """Close and forget the cached notify socket (tests only)."""
    global _notify_sock
    with _notify_lock:
        if _notify_sock is not None:
            try:
                _notify_sock.close()
            except OSError:
                pass
        _notify_sock = None


def _sd_notify(message: str) -> None:
    """Send a notification message to systemd via $NOTIFY_SOCKET.

    Silent no-op if NOTIFY_SOCKET is unset (dev shell instead of systemd).
    One datagram socket is connected on first use and reused for the life of
    the process; a send failure drops it so the next call reconnects.
    Mirrors the helper in arm-drone-lidar-workflow/base-station/rtk_base_manager.py.
    """
    global _notify_sock
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    with _notify_lock:
        try:
            if _notify_sock is None:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                sock.connect(addr)
                _notify_sock = sock
            _notify_sock.sendall(message.encode("utf-8"))
        except OSError as e:
            logger.debug("sd_notify(%r) failed: %s", message, e)
            if _notify_sock is not None:
                try:
                    _notify_sock.close()
                except OSError:
                    pass
            _notify_sock = None


def _default_on_timeout() -> None:
    """Default timeout action: end the whole process so systemd restarts it.

    ``sys.exit`` would only end the monitor thread (SystemExit is swallowed by
    threading); ``os._exit`` bypasses the hung main thread. Logging handlers are
    flushed first so the ERROR line above reaches the journal.
    """
    logger.error("Watchdog timeout — exiting with code 2")
    logging.shutdown()
    os._exit(2)
```

Also fix the module docstring line 7 to say `os._exit(2)` instead of `sys.exit(2)`, and remove the now-unused `import sys` if ruff reports it.

- [ ] **Step 4: Run the whole watchdog test file**

```bash
python -m pytest tests/test_watchdog.py -q
```

Expected: all pass (existing 5 plus 2 new).

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/watchdog.py tests/test_watchdog.py && python -m ruff check src/rover/watchdog.py tests/test_watchdog.py
git add src/rover/watchdog.py tests/test_watchdog.py
git commit -m "fix(watchdog): default timeout uses os._exit so systemd can restart; reuse notify socket (T1-001)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Watchdog always constructed

**Files:**
- Modify: `src/rover/main.py:481-489`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `run()` always builds `Watchdog(config.watchdog)` and calls `start()`; `_scan_loop` receives a non-None `watchdog`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_main.py`)

```python
def test_ready_notified_even_when_watchdog_disabled(tmp_path: Path, monkeypatch) -> None:
    """Type=notify units need READY=1 regardless of [watchdog].enabled (T1-002)."""
    from rover import watchdog as wd_mod

    sent: list[str] = []
    monkeypatch.setattr(wd_mod, "_sd_notify", sent.append)
    config_path = _write_all_disabled_config(tmp_path)  # has [watchdog] enabled = false
    assert main_mod.run(config_path=config_path, duration_sec=0.5) == 0
    assert "READY=1\n" in sent
    assert any(m == "WATCHDOG=1\n" for m in sent), "heartbeats must flow when disabled too"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_main.py -q -k ready_notified
```

Expected: FAIL, `"READY=1\n" in sent` is False.

- [ ] **Step 3: Implement**

In `src/rover/main.py`, replace

```python
    watchdog: Optional[Watchdog] = None
    if config.watchdog.enabled:
        try:
            watchdog = Watchdog(config.watchdog)
            watchdog.start()
        except Exception as e:
            logger.warning("Watchdog start failed: %s — running without health monitor", e)
            watchdog = None
```

with

```python
    # Always constructed: start() sends READY=1 and, when enabled, runs the
    # monitor thread; heartbeat() always pings systemd's WatchdogSec.
    watchdog: Optional[Watchdog] = None
    try:
        watchdog = Watchdog(config.watchdog)
        watchdog.start()
    except Exception as e:
        logger.warning("Watchdog start failed: %s — running without health monitor", e)
        watchdog = None
```

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_main.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/main.py tests/test_main.py && python -m ruff check src/rover/main.py tests/test_main.py
git add src/rover/main.py tests/test_main.py
git commit -m "fix(main): always start the watchdog so READY=1/WATCHDOG=1 reach systemd (T1-002)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Fail-soft sensor reads with a failure gate

**Files:**
- Modify: `src/rover/main.py` (new `_SensorGate` class before `_scan_loop`; read sites inside `_scan_loop`; settle sleep)
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `_SensorGate(name: str, limit: int = 5)` with `.record_failure(exc) -> bool` (returns True when the gate has just tripped), `.record_success()`, `.tripped: bool`. `_scan_loop` skips a sensor whose gate is tripped.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_main.py`)

```python
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
output_dir = "{(tmp_path / 'data').as_posix()}"
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
    assert _FlakyLidar.calls == 5, f"expected exactly 5 attempts before the gate trips, got {_FlakyLidar.calls}"


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
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_main.py -q -k "gate or settle"
```

Expected: `disables_sensor` FAIL (exit code 1: the OSError escapes); `_SensorGate` FAIL with AttributeError; `settle` may already pass (that is fine, keep it).

- [ ] **Step 3: Implement the gate** (insert in `src/rover/main.py` immediately before `def _scan_loop`)

```python
class _SensorGate:
    """Counts consecutive read failures for one sensor and trips after *limit*.

    A tripped gate makes the loop skip that sensor instead of re-raising or
    re-logging every iteration (CLAUDE.md §5: degrade, never crash).
    """

    def __init__(self, name: str, limit: int = 5) -> None:
        self.name = name
        self.limit = limit
        self.failures = 0
        self.tripped = False

    def record_failure(self, exc: BaseException) -> bool:
        """Return True exactly once, on the failure that trips the gate."""
        if self.tripped:
            return False
        self.failures += 1
        logger.debug("%s read failed (%d/%d): %s", self.name, self.failures, self.limit, exc)
        if self.failures >= self.limit:
            self.tripped = True
            logger.warning(
                "%s: %d consecutive read failures — subsystem disabled for this session (last: %s)",
                self.name, self.failures, exc,
            )
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0
        self.tripped = False
```

- [ ] **Step 4: Use the gate at each read site**

Add a module-level constant next to the `SCAN_*` constants near the top of `main.py`:

```python
# Loop pace when there is no stepper to settle behind (bench / telemetry-only).
# Module-level so tests can shrink it.
_IDLE_SETTLE_SEC = 1.0
```

and in `_scan_loop` change `settle_sec = 1.0  # idle pace when nothing to step` to `settle_sec = _IDLE_SETTLE_SEC`.

In `_scan_loop`, after `step_index = 0` add:

```python
    lidar_gate = _SensorGate("lidar")
    imu_gate = _SensorGate("imu")
    camera_gate = _SensorGate("camera")
    _SENSOR_ERRORS = (RuntimeError, TimeoutError, OSError)
```

Replace `time.sleep(settle_sec)` with `stop_event.wait(settle_sec)`.

Replace the LiDAR block with:

```python
        lidar_points: list = []
        if sensors.lidar is not None and sensors.lidar.available and not lidar_gate.tripped:
            try:
                lidar_points = sensors.lidar.read_scan()
                lidar_gate.record_success()
            except _SENSOR_ERRORS as e:
                lidar_gate.record_failure(e)
```

Replace the IMU block with:

```python
        imu_sample = None
        if sensors.imu is not None and sensors.imu.available and not imu_gate.tripped:
            try:
                imu_sample = sensors.imu.read_sample()
                imu_gate.record_success()
            except _SENSOR_ERRORS as e:
                imu_gate.record_failure(e)
```

In the camera block, add `and not camera_gate.tripped` to the `if`, and change `except RuntimeError as e: logger.debug(...)` to:

```python
            except _SENSOR_ERRORS as e:
                camera_gate.record_failure(e)
            else:
                camera_gate.record_success()
```

(Put the `else:` on the `try`, after the `except`.)

- [ ] **Step 5: Run**

```bash
python -m pytest tests/test_main.py -q
```

Expected: all pass, including exactly 5 LiDAR attempts.

- [ ] **Step 6: Commit**

```bash
python -m ruff format src/rover/main.py tests/test_main.py && python -m ruff check src/rover/main.py tests/test_main.py
git add src/rover/main.py tests/test_main.py
git commit -m "fix(main): fail-soft sensor reads with a 5-strike gate; interruptible settle (T1-003)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Teardown covers telemetry, NTRIP and watchdog setup

**Files:**
- Modify: `src/rover/main.py` (`_scan_loop` signature; `run()` from `# --- Telemetry ---` to the end)
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `_scan_loop(..., ntrip_client: Optional[NtripClient], ...)` replaces the `ntrip_stats_holder: dict` parameter; the loop reads `ntrip_client.stats`. `run()` wraps telemetry/NTRIP/watchdog construction in the same try/finally as the loop.

- [ ] **Step 1: Write the failing test** (append to `tests/test_main.py`)

```python
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_main.py -q -k constructor_failure
```

Expected: FAIL with the RuntimeError propagating out of `run()`.

- [ ] **Step 3: Restructure `run()`**

Replace everything in `run()` from the line `# --- Telemetry ---` through `return exit_code` with:

```python
    telemetry: Optional[TelemetryRouter] = None
    ntrip_client: Optional[NtripClient] = None
    watchdog: Optional[Watchdog] = None
    exit_code = 0
    try:
        # --- Telemetry ---
        telemetry = TelemetryRouter(config)
        telemetry.start()

        # --- NTRIP (Pi-mode only — ESP32 mode owns the path itself) ---
        if (
            config.ntrip.enabled
            and config.ntrip.client_location == "pi"
            and sensors.gnss is not None
        ):
            try:
                ntrip_client = NtripClient(config, rtcm_sink=sensors.gnss.write_rtcm)
                ntrip_client.start()
            except Exception as e:
                logger.warning("NtripClient start failed: %s — RTK degraded", e)
                ntrip_client = None

        # --- Watchdog (always constructed: start() sends READY=1; the monitor
        # thread only runs when enabled; heartbeat() always pings systemd) ---
        try:
            watchdog = Watchdog(config.watchdog)
            watchdog.start()
        except Exception as e:
            logger.warning("Watchdog start failed: %s — running without health monitor", e)
            watchdog = None

        # --- Acquisition loop ---
        _scan_loop(
            config=config,
            sensors=sensors,
            session_logger=session_logger,
            telemetry=telemetry,
            watchdog=watchdog,
            ntrip_client=ntrip_client,
            stop_event=stop_event,
            duration_sec=duration_sec,
        )
    except Exception as e:
        logger.exception("Acquisition setup or loop crashed: %s", e)
        exit_code = 1
    finally:
        session_logger.write({
            "type": "event",
            "timestamp": time.time(),
            "event": "scan_complete" if exit_code == 0 else "scan_abort",
        })

        # --- Reverse-order teardown ---
        if watchdog is not None:
            try:
                watchdog.stop()
            except Exception as e:
                logger.warning("Watchdog stop failed: %s", e)

        if ntrip_client is not None:
            try:
                ntrip_client.stop()
            except Exception as e:
                logger.warning("NtripClient stop failed: %s", e)

        if telemetry is not None:
            try:
                telemetry.stop()
            except Exception as e:
                logger.warning("TelemetryRouter stop failed: %s", e)

        _stop_sensors(sensors)

        metadata: dict = {}
        if ntrip_client is not None:
            metadata["ntrip_stats"] = asdict(ntrip_client.stats)
        metadata["lora_rtcm_used"] = (
            config.lora.enabled and config.lora.role == "rtcm_rx+status_tx"
        )

        try:
            session_logger.stop(metadata=metadata)
        except Exception as e:
            logger.warning("SessionLogger stop failed: %s", e)

    return exit_code
```

- [ ] **Step 4: Update `_scan_loop`**

Change the parameter `ntrip_stats_holder: dict,` to `ntrip_client: Optional[NtripClient],` and replace the telemetry-publish block's stats lookup:

```python
            if ntrip_client is not None:
                ntrip_stats = ntrip_client.stats
                status.ntrip_connected = ntrip_stats.connected
                status.ntrip_bytes_per_sec = ntrip_stats.bytes_received_this_sec
```

Delete the now-unused `_ntrip_stats_sink` closure and `ntrip_stats_holder` dict. Delete `NtripStats` from the imports if ruff reports it unused (keep `asdict`).

- [ ] **Step 5: Run**

```bash
python -m pytest tests/test_main.py tests/test_telemetry.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
python -m ruff format src/rover/main.py tests/test_main.py && python -m ruff check src/rover/main.py tests/test_main.py
git add src/rover/main.py tests/test_main.py
git commit -m "fix(main): telemetry/NTRIP/watchdog setup inside the teardown guard; drop stats holder (T1-029, T1-046)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Camera JPEG quality via `options`

**Files:**
- Modify: `src/rover/camera.py:78-107` (`start`), `:164-167` (`capture`)
- Test: `tests/test_camera.py`

**Interfaces:**
- Produces: `Camera.start()` sets `self._cam.options["quality"] = jpeg_quality`; `capture()` calls `capture_file(path, format="jpeg")` with no `quality` kwarg.

- [ ] **Step 1: Replace the loose mock with an autospec'd stub** (edit `tests/test_camera.py`)

Replace the `mock_picamera2` fixture with:

```python
class _Picamera2Stub:
    """Mirrors the picamera2 0.3.x surface this driver touches. Autospec'd so a
    kwarg picamera2 does not accept (e.g. quality=) fails the test (T1-005)."""

    def __init__(self) -> None:
        self.options: dict = {}

    def create_still_configuration(self, main=None, lores=None, raw=None, **kw):
        return {"main": main}

    def configure(self, config) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...

    def capture_file(self, file_output, name="main", format=None, wait=None, signal_function=None):
        return {}


@pytest.fixture
def mock_picamera2():
    """Patch picamera2 with an autospec'd stub for off-Pi testing."""
    from unittest.mock import create_autospec

    mock_cam = create_autospec(_Picamera2Stub, instance=True)
    mock_cam.options = {}
    mock_cam_class = MagicMock(return_value=mock_cam)
    with (
        patch("rover.camera._CAMERA_AVAILABLE", True),
        patch("rover.camera.Picamera2", mock_cam_class),
        patch("rover.camera.time"),
    ):
        yield mock_cam
```

Then add to the hardware-mocked test class (find the class that uses `mock_picamera2`; add these methods):

```python
    def test_start_sets_jpeg_quality_option(self, camera_config, mock_picamera2):
        cam = Camera(camera_config)
        cam.start()
        assert mock_picamera2.options["quality"] == 85

    def test_capture_does_not_pass_quality_kwarg(self, camera_config, mock_picamera2, tmp_path):
        cam = Camera(camera_config)
        cam.start()
        cam.capture(tmp_path, 3)
        _args, kwargs = mock_picamera2.capture_file.call_args
        assert "quality" not in kwargs
        assert kwargs.get("format") == "jpeg"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_camera.py -q
```

Expected: the existing capture test and the two new ones FAIL with `TypeError: got an unexpected keyword argument 'quality'` or the option assertion.

- [ ] **Step 3: Implement**

In `start()`, after `self._cam.configure(still_config)` add:

```python
            # JPEG quality is a Picamera2 option, not a capture_file kwarg.
            self._cam.options["quality"] = self._config.jpeg_quality
```

In `capture()`, change the call to:

```python
        self._cam.capture_file(str(full_path), format="jpeg")
```

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_camera.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/camera.py tests/test_camera.py && python -m ruff check src/rover/camera.py tests/test_camera.py
git add src/rover/camera.py tests/test_camera.py
git commit -m "fix(camera): set JPEG quality via Picamera2.options, not capture_file kwarg (T1-005)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: NAV-PVT uses pyubx2's scaled attributes

**Files:**
- Modify: `pyproject.toml` (`dev` extra gains `pyubx2`)
- Modify: `src/rover/gnss.py:403-435` (`_fix_from_nav_pvt`)
- Test: `tests/test_gnss.py`

**Interfaces:**
- Produces: `_fix_from_nav_pvt(msg) -> GnssFix` reading `msg.lat`, `msg.lon` (degrees), `msg.hMSL` (mm), `msg.pDOP` (already scaled), `msg.carrSoln`, `msg.fixType`, `msg.numSV`.

- [ ] **Step 1: Add the dev dependency and install it**

In `pyproject.toml` `[project.optional-dependencies]`, change `dev = ["pytest", "ruff"]` to `dev = ["pytest", "ruff", "pyubx2"]`, then:

```bash
pip install -q pyubx2 && python -c "import pyubx2; print(pyubx2.__version__)"
```

- [ ] **Step 2: Write the failing test** (append to `tests/test_gnss.py`)

```python
def test_fix_from_nav_pvt_uses_pyubx2_scaled_attributes() -> None:
    """pyubx2 already scales lat/lon to degrees and pDOP to 0.01 units and
    expands the flags byte into carrSoln; dividing again zeroes the fix (T1-006)."""
    pyubx2 = pytest.importorskip("pyubx2")
    from rover.gnss import _fix_from_nav_pvt

    msg = pyubx2.UBXMessage(
        "NAV", "NAV-PVT", pyubx2.GET,
        fixType=3, carrSoln=2, numSV=18,
        lat=40.712800, lon=-74.006000, hMSL=10500, pDOP=1.2,
    )
    # Sanity: the library really does expose scaled values. If this constructor
    # rejects `carrSoln=` as a kwarg on the installed pyubx2, build the same
    # message with `flags=0b10000000` instead (carrSoln lives in bits 6-7 of
    # flags) and keep the assertions below unchanged.
    assert abs(msg.lat - 40.7128) < 1e-6
    assert msg.carrSoln == 2

    fix = _fix_from_nav_pvt(msg)
    assert abs(fix.lat - 40.7128) < 1e-6
    assert abs(fix.lon - (-74.006)) < 1e-6
    assert abs(fix.alt - 10.5) < 1e-6
    assert fix.fix_type == 5  # RTK FIX
    assert abs(fix.hdop - 1.2) < 1e-6
    assert fix.sat_count == 18
```

- [ ] **Step 3: Run to confirm failure**

```bash
python -m pytest tests/test_gnss.py -q -k nav_pvt
```

Expected: FAIL (lat ≈ 0.0000041, fix_type 2).

- [ ] **Step 4: Implement**

Replace the body of `_fix_from_nav_pvt` after the docstring with:

```python
    fix_type_raw = getattr(msg, "fixType", 0)
    carr_soln = getattr(msg, "carrSoln", 0)

    fix_type = 0
    if fix_type_raw == 2:
        fix_type = 1  # 2D
    elif fix_type_raw in (3, 4):
        fix_type = 2  # 3D (4 = GNSS + dead reckoning)
    if carr_soln == 1:
        fix_type = 4  # FLOAT
    elif carr_soln == 2:
        fix_type = 5  # FIX

    return GnssFix(
        timestamp=time.time(),
        fix_type=fix_type,
        lat=float(getattr(msg, "lat", 0.0)),
        lon=float(getattr(msg, "lon", 0.0)),
        alt=float(getattr(msg, "hMSL", 0)) / 1000.0,
        hdop=float(getattr(msg, "pDOP", 99.9)),  # pDOP, labelled properly in stage 4
        vdop=99.9,
        sat_count=int(getattr(msg, "numSV", 0)),
        rtk_age=-1.0,
    )
```

Update the docstring: pyubx2 (default `scaling=True`) delivers `lat`/`lon` in degrees, `hMSL` in mm, `pDOP` scaled, and `carrSoln` as its own attribute.

- [ ] **Step 5: Run**

```bash
python -m pytest tests/test_gnss.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
python -m ruff format src/rover/gnss.py tests/test_gnss.py && python -m ruff check src/rover/gnss.py tests/test_gnss.py
git add pyproject.toml src/rover/gnss.py tests/test_gnss.py
git commit -m "fix(gnss): read NAV-PVT via pyubx2 scaled attributes; add pyubx2 to dev extra (T1-006)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Logger flush is fault-tolerant, bounded and fsync'd

**Files:**
- Modify: `src/rover/logger.py` (`__init__` queue, `write`, `_periodic_flush`, `_flush`, `stop`, `_write_metadata`)
- Test: `tests/test_logger.py`

**Interfaces:**
- Produces: `SessionLogger.degraded: bool` property; `SessionLogger.dropped_records: int` property; queue bounded at `_QUEUE_MAX = 10_000`; `os.fsync` on `stop()` and every `_FSYNC_EVERY = 10` periodic flushes; `metadata.json` written via `rover._io.atomic_write_json`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_logger.py`)

```python
def test_flush_failure_keeps_timer_alive(fast_flush_cfg, monkeypatch):
    """A write error inside the timer thread must not stop future flushes (T1-011)."""
    config, path = fast_flush_cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    try:
        calls = {"n": 0}
        real = lg._write_record

        def _boom(record):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError(28, "No space left on device")
            real(record)

        monkeypatch.setattr(lg, "_write_record", _boom)
        lg.write({"type": "event", "event": "first"})
        time.sleep(0.3)  # first flush raises
        assert lg.degraded is True
        assert lg._flush_timer is not None and lg._flush_timer.is_alive()
        lg.write({"type": "event", "event": "second"})
        time.sleep(0.3)  # second flush succeeds
    finally:
        lg.stop()
    text = (lg.session_dir / "scan.jsonl").read_text()
    assert '"second"' in text


def test_queue_is_bounded_and_drops_oldest(cfg):
    config, path = cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    try:
        from rover import logger as logger_mod

        for i in range(logger_mod._QUEUE_MAX + 5):
            lg.write({"type": "event", "i": i})
        assert lg.dropped_records == 5
    finally:
        lg.stop()
    lines = (lg.session_dir / "scan.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    assert first["i"] == 5, "oldest five must have been dropped"


def test_stop_fsyncs_files(cfg, monkeypatch):
    import os as os_mod

    synced: list[int] = []
    monkeypatch.setattr(os_mod, "fsync", lambda fd: synced.append(fd))
    config, path = cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    lg.write({"type": "event", "event": "x"})
    lg.stop()
    assert len(synced) >= 2, "scan and gnss files must be fsync'd at stop"


def test_metadata_written_atomically(cfg, monkeypatch):
    from rover import logger as logger_mod

    called: list[str] = []

    def _fake_atomic(path, data):
        called.append(str(path))
        Path(path).write_text(json.dumps(data))

    monkeypatch.setattr(logger_mod, "atomic_write_json", _fake_atomic)
    config, path = cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    lg.stop()
    assert called and called[0].endswith("metadata.json")
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_logger.py -q -k "flush_failure or bounded or fsync or atomically"
```

Expected: all four FAIL.

- [ ] **Step 3: Implement**

At module level in `src/rover/logger.py` add after the imports:

```python
import os

from rover._io import atomic_write_json

_QUEUE_MAX = 10_000     # records buffered between flushes before dropping oldest
_FSYNC_EVERY = 10       # periodic flushes between fsync calls
```

In `__init__`, change `self._queue: queue.Queue[dict] = queue.Queue()` to `queue.Queue(maxsize=_QUEUE_MAX)` and add:

```python
        self._degraded = False
        self._dropped = 0
        self._flush_count = 0
```

Add properties after `images_dir`:

```python
    @property
    def degraded(self) -> bool:
        """True once any flush has failed; the logger keeps running regardless."""
        return self._degraded

    @property
    def dropped_records(self) -> int:
        """Records discarded because the queue was full."""
        return self._dropped
```

Replace `write()`'s body after the running check with:

```python
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            # Drop the oldest so a stalled disk cannot eat all memory.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._dropped += 1
            if self._dropped in (1, 100, 1000) or self._dropped % 10_000 == 0:
                logger.warning("SessionLogger queue full — dropped %d records so far", self._dropped)
            self._queue.put_nowait(record)
```

Replace `_periodic_flush` with:

```python
    def _periodic_flush(self) -> None:
        """Called by timer: flush, then ALWAYS reschedule (T1-011)."""
        try:
            self._flush()
            self._flush_count += 1
            if self._flush_count % _FSYNC_EVERY == 0:
                self._fsync_files()
        except Exception as e:
            if not self._degraded:
                logger.error("SessionLogger flush failed — continuing degraded: %s", e)
            self._degraded = True
        finally:
            self._schedule_flush()
```

Add a helper next to `_close_files`:

```python
    def _fsync_files(self) -> None:
        for f in (self._scan_file, self._gnss_file):
            if f is not None and not f.closed:
                f.flush()
                os.fsync(f.fileno())
```

In `stop()`, change the final-drain section to:

```python
        try:
            self._flush()
            self._fsync_files()
        except Exception as e:
            logger.error("SessionLogger final flush failed: %s", e)
            self._degraded = True
```

In `_write_metadata`, replace the two-line `meta_path.write_text(...)` with `atomic_write_json(meta_path, meta)`, and add `"logger_degraded": self._degraded, "dropped_records": self._dropped,` to the `meta` dict after `"config_hash"`.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_logger.py -q
```

Expected: all pass. If an existing test asserted `metadata.json` is indented JSON, relax it to `json.loads` (atomic_write_json writes compact JSON plus a trailing newline).

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/logger.py tests/test_logger.py && python -m ruff check src/rover/logger.py tests/test_logger.py
git add src/rover/logger.py tests/test_logger.py
git commit -m "fix(logger): flush survives write errors, bounded queue, fsync, atomic metadata (T1-011, T1-032)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: `save_images` gates capture

**Files:**
- Modify: `src/rover/main.py` (camera block condition)
- Modify: `src/rover/logger.py` (remove `_images_dir`, `images_dir`, and the pre-creation in `start()`)
- Test: `tests/test_main.py`, `tests/test_logger.py`

**Interfaces:**
- Produces: `SessionLogger.images_dir` removed; capture happens only when `config.logging.save_images` is true.

- [ ] **Step 1: Write the failing test** (append to `tests/test_main.py`)

```python
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
output_dir = "{(tmp_path / 'data').as_posix()}"
session_prefix = "noimg"
save_images = false
"""
    )
    assert main_mod.run(config_path=cfg, duration_sec=1.0) == 0
    assert _CountingCamera.captures == 0
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_main.py -q -k save_images
```

Expected: FAIL, captures > 0.

- [ ] **Step 3: Implement**

In `_scan_loop`'s camera `if`, add `and config.logging.save_images` as the first condition after `sensors.camera is not None`.

In `src/rover/logger.py`: delete `self._images_dir` from `__init__`, delete the `images_dir` property, and delete the "Images directory" block in `start()` (the three lines under `# Images directory`). Search tests for `images_dir`:

```bash
grep -n "images_dir" tests/*.py src/rover/*.py
```

Any test asserting the pre-created directory is rewritten to assert the directory does NOT exist after `start()` (the camera creates it on first capture).

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_main.py tests/test_logger.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/main.py src/rover/logger.py tests && python -m ruff check src/rover/main.py src/rover/logger.py tests
git add src/rover/main.py src/rover/logger.py tests/test_main.py tests/test_logger.py
git commit -m "fix: save_images=false gates camera capture; drop unused images_dir (T1-033)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Config cross-check NTRIP-on-Pi requires GNSS

**Files:**
- Modify: `src/rover/config.py` (inside `_validate`, after the `# -- ntrip` block)
- Test: `tests/test_config_session.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_config_session.py`)

```python
def test_ntrip_on_pi_requires_gnss_enabled(tmp_toml):
    """NTRIP on the Pi has nowhere to write RTCM if the F9P is disabled (T1-027)."""
    path = tmp_toml(
        """
        [gnss]
        enabled = false

        [ntrip]
        enabled = true
        client_location = "pi"
        """
    )
    with pytest.raises(ValueError, match=r"\[ntrip\].*requires \[gnss\]\.enabled"):
        load_config(path)


def test_ntrip_on_esp32_does_not_require_gnss(tmp_toml):
    path = tmp_toml(
        """
        [gnss]
        enabled = false

        [ntrip]
        enabled = true
        client_location = "esp32"
        """
    )
    cfg = load_config(path)
    assert cfg.ntrip.client_location == "esp32"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_config_session.py -q -k requires_gnss
```

Expected: first FAIL (no error raised), second passes.

- [ ] **Step 3: Implement**

In `_validate`, at the end of the `# -- ntrip` block (before `# -- lora --`), add:

```python
    if nt["enabled"] and nt["client_location"] == "pi" and not gn["enabled"]:
        raise ValueError(
            "[ntrip] enabled with client_location = 'pi' requires [gnss].enabled = true "
            "(the Pi-side client writes RTCM to the F9P serial port)"
        )
```

- [ ] **Step 4: Run the whole suite** (other fixtures may enable NTRIP without GNSS)

```bash
python -m pytest -q 2>&1 | tail -3
```

Expected: green. If a test config trips the new rule, that config was silently running without RTK; add `[gnss] enabled = true` or set `[ntrip] enabled = false` in it, whichever the test's intent needs.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/config.py tests/test_config_session.py && python -m ruff check src/rover/config.py tests/test_config_session.py
git add src/rover/config.py tests/test_config_session.py tests
git commit -m "fix(config): NTRIP on Pi requires GNSS enabled (T1-027)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Deploy files agree with the config

**Files:**
- Modify: `deploy/systemd/rover.service`, `deploy/systemd/rover-telemetry.service`
- Modify: `config/default.toml:97`, `config/telemetry-only.toml` (`output_dir`)
- Modify: `deploy/install.sh`
- Create: `tests/test_deploy.py`

**Interfaces:**
- Produces: both units carry `StateDirectory=rover`, `RuntimeDirectory=rover`, `PrivateTmp=true`; both TOMLs default `output_dir = "/var/lib/rover/data"`; `install.sh` installs configs (no overwrite) and code, restarts both units, prints the drop-in recipe.

- [ ] **Step 1: Write the failing static tests** (`tests/test_deploy.py`)

```python
"""Static checks that the deploy kit and shipped configs agree (T2-001..T2-003)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
UNITS = [REPO / "deploy/systemd/rover.service", REPO / "deploy/systemd/rover-telemetry.service"]
TOMLS = [REPO / "config/default.toml", REPO / "config/telemetry-only.toml"]


@pytest.mark.parametrize("unit", UNITS, ids=lambda p: p.name)
def test_unit_grants_state_and_runtime_dirs(unit: Path) -> None:
    text = unit.read_text(encoding="utf-8")
    assert re.search(r"^StateDirectory=rover$", text, re.M), unit.name
    assert re.search(r"^RuntimeDirectory=rover$", text, re.M), unit.name
    assert re.search(r"^PrivateTmp=true$", text, re.M), unit.name
    assert "DEC-013 of arm-drone-lidar-workflow" not in text


@pytest.mark.parametrize("toml_path", TOMLS, ids=lambda p: p.name)
def test_shipped_output_dir_is_writable_under_hardening(toml_path: Path) -> None:
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    out = data["logging"]["output_dir"]
    assert out.startswith("/var/lib/rover/"), out
    assert not out.startswith("/home/"), "ProtectHome=true hides /home"


def test_install_sh_installs_configs_without_overwriting() -> None:
    sh = (REPO / "deploy/install.sh").read_text(encoding="utf-8")
    assert 'if [[ ! -f "$ETC_DIR/config.toml" ]]' in sh
    assert 'if [[ ! -f "$ETC_DIR/telemetry-only.toml" ]]' in sh
    assert "rsync" in sh and "/opt/rover" in sh
    assert 'install -d -m 0755 "$RUN_DIR"' not in sh, "/run is tmpfs; RuntimeDirectory= owns it"
    assert "rover-telemetry.service" in sh.split("=== Reload ===")[1], "both units restarted"
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_deploy.py -q
```

Expected: 5 of 5 FAIL.

- [ ] **Step 3: Edit both unit files**

In `deploy/systemd/rover.service`: delete the two comment lines mentioning `DEC-013 of arm-drone-lidar-workflow` (keep the ordering-cycle explanation, drop the attribution). After `ReadWritePaths=/run/rover /var/log/rover /etc/rover` add:

```ini
# systemd creates and owns these; StateDirectory is where sessions land by
# default (config/default.toml output_dir). To write somewhere else, add a
# drop-in: `systemctl edit rover` → [Service] ReadWritePaths=/path/to/projects
StateDirectory=rover
RuntimeDirectory=rover
# rpi-lgpio writes its working files to $LG_WD; ProtectSystem=strict makes the
# real /tmp read-only, so give the service a private one.
PrivateTmp=true
```

Apply the same three directives (and the comment) to `deploy/systemd/rover-telemetry.service` after its `ReadWritePaths=` line.

- [ ] **Step 4: Edit both TOMLs**

`config/default.toml` line 97: `output_dir = "/var/lib/rover/data"` with the comment `# systemd StateDirectory (see deploy/systemd/rover.service); override per project`. Same key in `config/telemetry-only.toml`.

- [ ] **Step 5: Edit `install.sh`**

In the header "What it does" list, replace items 4 and 7 with:

```
#   4. Creates /var/log/rover and /etc/rover (systemd owns /run/rover and
#      /var/lib/rover via RuntimeDirectory= / StateDirectory=).
#   5. Installs config/default.toml → /etc/rover/config.toml and
#      config/telemetry-only.toml → /etc/rover/telemetry-only.toml, never
#      overwriting an existing file.
#   6. Syncs src/rover → /opt/rover/src/rover (the units' PYTHONPATH).
#   7. Ensures /etc/rover/secret exists with mode 0600.
#   8. systemctl daemon-reload + udev reload + trigger.
#   9. Restarts rover.service and rover-telemetry.service if running.
```

Add after `LOG_DIR="/var/log/rover"`:

```bash
OPT_DIR="/opt/rover"
CONFIG_DIR="$SCRIPT_DIR/../config"
SRC_DIR="$SCRIPT_DIR/../src"
```

In the Install section, delete `install -d -m 0755 "$RUN_DIR"` (and the now-unused `RUN_DIR=` assignment) and add after the udev copy loop. Two explicit guards, not a loop, so the static test's literal strings match:

```bash
echo "  installing configs (existing files kept)..."
if [[ ! -f "$ETC_DIR/config.toml" ]]; then
    install -m 0644 "$CONFIG_DIR/default.toml" "$ETC_DIR/config.toml"
    echo "    created $ETC_DIR/config.toml"
else
    echo "    kept $ETC_DIR/config.toml"
fi
if [[ ! -f "$ETC_DIR/telemetry-only.toml" ]]; then
    install -m 0644 "$CONFIG_DIR/telemetry-only.toml" "$ETC_DIR/telemetry-only.toml"
    echo "    created $ETC_DIR/telemetry-only.toml"
else
    echo "    kept $ETC_DIR/telemetry-only.toml"
fi

echo "  syncing rover package to $OPT_DIR/src/rover ..."
install -d -m 0755 "$OPT_DIR/src"
rsync -a --delete --exclude '__pycache__' "$SRC_DIR/rover/" "$OPT_DIR/src/rover/"
```

`rsync` ships with Raspberry Pi OS Lite; if `command -v rsync` fails on the target, the checklist in Task 11 says to `apt install rsync` before re-running.

Replace the restart block with:

```bash
for unit in rover.service rover-telemetry.service; do
    if [[ "$RESTART" == true ]] && systemctl is-active --quiet "$unit"; then
        echo "  restarting $unit..."
        systemctl restart "$unit"
    fi
done

echo
echo "Done. Inspect with:"
echo "  systemctl status rover"
echo "  ls -la /dev/rover-*"
echo "  cat /run/rover/status.json   # once rover has published"
echo
echo "Sessions are written to /var/lib/rover/data. To log elsewhere (e.g. a"
echo "project folder), set [logging].output_dir in /etc/rover/config.toml AND"
echo "grant the path: systemctl edit rover  →  [Service]"
echo "                                          ReadWritePaths=/your/path"
```

Also add the `--dry-run` DIFFERS check for the two config files and the `rsync --dry-run` summary in the dry-run section, mirroring the existing unit/udev diff loop.

- [ ] **Step 6: Run**

```bash
python -m pytest tests/test_deploy.py -q
bash -n deploy/install.sh
```

Expected: 5 passed; `bash -n` silent.

- [ ] **Step 7: Commit**

```bash
git add deploy config tests/test_deploy.py
git commit -m "fix(deploy): StateDirectory/RuntimeDirectory/PrivateTmp; default output under /var/lib/rover; install configs+code (T2-001, T2-002, T2-003, D-016)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: On-Pi smoke checklist

**Files:**
- Create: `deploy/SMOKE_CHECKLIST.md`

**Interfaces:**
- Produces: the procedure that turns the four `probable` hardware findings (T1-005, T1-006, T1-033, T2-002) into observed results.

- [ ] **Step 1: Write the checklist** (Write tool)

```markdown
# First-boot smoke checklist (run on the Pi after `sudo deploy/install.sh`)

Each line is pass/fail. Record the outcome and date in the audit report row named.

1. `git -C /opt/rover status` is not needed: the units import from `/opt/rover/src`.
   `python3 -c "import sys; sys.path.insert(0,'/opt/rover/src'); import rover; print(rover.__version__)"`
   → prints the version. (sanity)
2. `sudo systemctl start rover-telemetry && sleep 5 && systemctl is-active rover-telemetry`
   → `active`. Then `journalctl -u rover-telemetry -n 20` shows `Watchdog started` or
   `Watchdog disabled by config` and NO `start operation timed out`. (T1-002)
3. `cat /run/rover/status.json` → JSON with `schema_version`. (RuntimeDirectory, T2-003)
4. `ls /var/lib/rover/data/` → one session directory. (StateDirectory, T2-001)
5. `sudo systemctl stop rover-telemetry` returns within 10 s and the session has
   `metadata.json`. (T1-029)
6. `sudo systemctl start rover` with the stepper connected → journal shows no
   `lgpio` / `LG_WD` error and the motor steps. (PrivateTmp, T2-002)
7. With the camera enabled: journal shows `Captured images/img_000000.jpg`, no
   `TypeError`. (T1-005)
8. With the F9P connected and pyubx2 installed: `status.json` shows a plausible
   `lat`/`lon` (not 0.0) within 60 s of a sky view. (T1-006)
9. Pull the LD19 USB cable mid-session → journal shows one WARNING
   `lidar: 5 consecutive read failures — subsystem disabled`, the service stays
   `active`, telemetry keeps publishing. (T1-003)
10. `python3 -c "import RPi.GPIO as g; print(g.__file__)"` → path contains
    `rpi_lgpio` or `lgpio`, not `RPi/GPIO`. If it does not, `sudo apt remove
    python3-rpi.gpio && pip install rpi-lgpio`. (T1-033; stage 4 adds a code guard)
11. `sudo deploy/install.sh` a second time → prints `kept /etc/rover/config.toml`.
```

- [ ] **Step 2: Link it**

In `deploy/install.sh` final echo block add `echo "  see deploy/SMOKE_CHECKLIST.md for the first-boot checks"`.

- [ ] **Step 3: Commit**

```bash
git add deploy/SMOKE_CHECKLIST.md deploy/install.sh
git commit -m "docs(deploy): first-boot smoke checklist for the hardware-only findings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Merge stage 2

- [ ] **Step 1: Full verification**

```bash
python -m pytest -q 2>&1 | tail -1
python -m ruff check src scripts tests
python -m ruff format --check src scripts tests | tail -1
bash -n deploy/install.sh
```

Expected: green (279 + about 17 new tests; report the measured number), ruff clean, format clean.

- [ ] **Step 2: Merge**

```bash
git checkout main
git merge --no-ff fix/stage2-first-boot -m "Merge stage 2: first-boot blockers (T1-001..003, T1-005, T1-006, T1-011, T1-027, T1-029, T1-032, T1-033, T2-001..004)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git branch -d fix/stage2-first-boot
```

- [ ] **Step 3: Mark the rows in the audit report**

Set `triage` to `done (<merge sha>)` for T1-001, T1-002, T1-003, T1-011, T1-027, T1-029, T1-032, T1-033, T2-001, T2-003, T2-004, D-016. Set T1-005, T1-006, T2-002 to `done-unverified (<sha>; see deploy/SMOKE_CHECKLIST.md)`. Commit on `main`:

```bash
git add docs/AUDIT_super_20260922_1810.md
git commit -m "audit: mark stage 2 findings done

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
