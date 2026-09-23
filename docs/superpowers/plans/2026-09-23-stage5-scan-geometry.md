# Stage 5 — Scan Geometry and Field Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The mast sweeps 360° and rewinds instead of winding its cables forever, LoRa carries status only, and georef produces a cloud whose azimuth is true north (when a magnetometer heading exists), whose LiDAR origin is corrected for the antenna lever arm, and whose heights are exported twice — ellipsoidal and NAVD88 (GEOID18) — without ever labelling ellipsoidal heights as NAVD88.

**Architecture:** Seven tasks on branch `fix/stage5-scan-geometry`, then merge. Rover side: `[lora]` becomes status-only at 10 s; new `[stepper]`/`[imu]`/`[calibration]` keys; `StepperMotor` exposes `current_step` and takes a per-call rpm; a pure `SweepPlanner` (new `src/rover/sweep.py`) decides rest → scan steps → rewind chunks from the stepper's actual position; `main._scan_loop` executes those actions, tags lidar records with a sweep index, logs `sweep_start` events and a `geometry` metadata block. Post-processing side (`scripts/georef.py`): a WMM declination helper, a heading model (Madgwick NWU → ENU, per-sweep rest heading, per-scan tilt, `base`/`platform` IMU mount, rotating antenna lever arm), and a dual ellipsoidal/NAVD88 export with an `export.json` manifest and a hard guard against PROJ's silent ballpark vertical transform.

**Tech Stack:** Python 3.11 stdlib, pytest, numpy, pyproj 3.7 (PROJ network grid fetch), laspy, pygeomag 1.1 (WMM 2025, pure Python; post-processing only).

**Spec:** `docs/superpowers/specs/2026-09-22-audit-remediation-design.md` §6a (amendment 2026-09-23), plus `docs/CROSS_REPO_BACKLOG.md` rows S3-R1, S3-R3, CR-002 and the sibling cross-check recorded there.

## Global Constraints

- **DEC-015 (amended by §6a):** no slip ring. The mast never travels more than `sweep_deg` (≤ 360) from its home position, and returns home by rewinding. The one-direction-forever loop is the defect this stage fixes.
- **Rewind is not scan data:** no lidar, camera or IMU records are logged while rewinding; `scan_state` publishes `SCAN_REWINDING` (new value 4). Status schema stays v2 (a new enum value is not a new field).
- **Stop latency:** a rewind moves in chunks of at most 45°, so a SIGTERM mid-rewind is honoured within one chunk.
- **Sensors never crash the system** (CLAUDE.md §5); a stepper failure during rewind goes through the same `_SensorGate("stepper")` as a scan step.
- **Heading frames:** Madgwick's world frame is North-West-Up with x = magnetic north (S3-R1). Conversion to ENU is `R_enu = Rz(-D) · Rz(+90°) · R_nwu`, with D = magnetic declination, east-positive, in degrees. Grid convergence is handled by pyproj when ENU points are projected; do not add it by hand.
- **Heading reference labels:** `"true"` (magnetometer rest heading + WMM declination), `"magnetic"` (rest heading, no declination available), `"relative"` (no magnetometer samples at rest; mast-0 forward = +X). The label is written to `export.json` and logged; it is never inferred silently.
- **Heights:** raw JSONL stays ellipsoidal metres. NAVD88 output only through the GEOID18 grid (`us_noaa_g2018u0.tif`), source CRS NAD83(2011) geographic 3D **EPSG:6319**, target compound `EPSG:<H>+6360` (ftUS) or `+5703` (m). A transform whose undulation is under 1 m anywhere is a ballpark fallback and must raise, never be written.
- **ARM EPSG codes** (sibling `decision-log.md:47`): PA North 6563, PA South 6565, ftUS = 0.3048006096012192 m. Vertical 6360 = NAVD88 height (ftUS).
- **RTK frame assumption:** rover lat/lon inherit the Base-Station's declared frame, which ARM declares in NAD83(2011) (sibling DEC-001). Horizontal projection keeps its existing `EPSG:4326` source; it was measured identical to `EPSG:6318` at State College to the last printed digit (2026-09-23), so only the vertical path uses 6319.
- **pygeomag is post-processing only:** declared in the `post` and `dev` extras, imported lazily in `scripts/georef.py`, never imported by `src/rover/`.
- **Old sessions still load:** lidar records without `sweep` are sweep 0; sessions without `sweep_start` events use the first lidar timestamp of each sweep as the rest-window end; metadata without `geometry` means mount `base`, no lever arm.
- **LoRa (DEC-031 amended):** status-only. `[lora].role` ∈ {`"status_tx_only"`, `"disabled"`}, default `"status_tx_only"`; `telemetry_interval_sec` default 10.0. `TYPE_RTCM_CHUNK` leaves the Python protocol; 0x10 is documented as reserved. The ESP32 NTRIP client mode (DEC-032) stays. Firmware is **not** edited this stage (no PlatformIO build available).
- Style `X | None`; `python -m ruff format src scripts tests` then `python -m ruff check src scripts tests` clean; `config/` and `deploy/` files stay LF (probe below); commit trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; do not push.
- File-content hazard (machine CLAUDE.md): write file content with the Edit/Write tools, never through a shell string; never `sed -i`. After editing any file under `config/` or `deploy/` run
  `python -c "import sys;d=open(sys.argv[1],'rb').read();c=d.count(b'\r\n');print('crlf',c,'lone-lf',d.count(b'\n')-c)" <file>` and confirm `crlf 0`.
- Suite baseline at the stage 4 merge (`167f4a2`): **422 passed**. It must not go down. Tests that need pygeomag or the GEOID18 grid are the only ones allowed to skip, and each skip must name its reason.
- Closes: S3-R1, S3-R3 (mount made configurable; physical choice stays a bench item), CR-002 (not needed), the one-direction sweep defect (found 2026-09-23). Stays open: S3-R2 (LD19 angle direction), S4-R1 (stage 6 docs).

## Review Focus

1. **The GEOID18 grid is missing on the processing PC** (and PROJ network is off or fails): PROJ silently returns ellipsoidal heights through a "ballpark" transform — measured 2026-09-23, even with `only_best=True`. The expected behaviour is an ERROR, exit code 3, the ellipsoidal files written, and **no** `_navd88` file. Pinned by Task 7 (`test_ballpark_transform_is_refused`, `test_missing_grid_writes_ellipsoidal_only_and_exits_3`).
2. **SIGTERM while the mast is rewinding** must end the run within one chunk, not after a full 360° rewind. Pinned by Task 4 (`test_stop_during_rewind_is_prompt`).
3. **A stepper that fails mid-sweep and then recovers** must not push the planner past `sweep_deg`; the planner reads the stepper's real position every iteration. Pinned by Task 3 (`test_planner_is_position_based`).
4. **Magnetometer on, but no GNSS fix** (indoor, or antenna not yet bought): georef must label the heading `"magnetic"` and export, not crash and not claim `"true"`. Pinned by Task 6 (`test_magnetic_label_without_gnss`).
5. **A session dated after the WMM 2025 model's life span (2030)**: pygeomag raises `ValueError`; georef must fall back to `"magnetic"` with a warning naming the date. Pinned by Task 5 (`test_outside_lifespan_returns_none`).

---

### Task 1: LoRa status-only at 10 s

**Files:**
- Modify: `src/rover/config.py` (`LoraConfig.role` default; `_DEFAULTS["lora"]` role and `telemetry_interval_sec`; the `_require_in` set for `role`)
- Modify: `config/default.toml` (`[lora]` block: `telemetry_interval_sec`, `role`, the section comment)
- Modify: `src/rover/lora_protocol.py` (remove `TYPE_RTCM_CHUNK`; module docstring; changelog)
- Modify: `src/rover/main.py` (drop `metadata["lora_rtcm_used"]`)
- Test: `tests/test_config_session.py`, `tests/test_lora_protocol.py`, `tests/test_main.py`, `tests/test_telemetry.py` (comment at the default-config test only)

**Interfaces:**
- Produces: `config.lora.role in {"status_tx_only", "disabled"}`, default `"status_tx_only"`; `config.lora.telemetry_interval_sec == 10.0` by default; `rover.lora_protocol` no longer exports `TYPE_RTCM_CHUNK`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_config_session.py`, class `TestLoraV2Fields`, replace `test_lora_default_role` and add two tests:

```python
    def test_lora_default_role(self):
        """DEC-031 amended 2026-09-23: LoRa is status-only; NTRIP is the only RTK path."""
        cfg = load_config()
        assert cfg.lora.role == "status_tx_only"

    def test_retired_rtcm_role_rejected(self, tmp_toml):
        p = tmp_toml(
            """
            [lora]
            role = "rtcm_rx+status_tx"
            """
        )
        with pytest.raises(ValueError, match=r"\[lora\] role"):
            load_config(p)

    def test_lora_default_interval_is_10s(self):
        """Matches the Base-Station Heltec beacon on the shared 915 MHz / SF7 / 0x12 channel."""
        assert load_config().lora.telemetry_interval_sec == 10.0
```

Also change the assertion at the other default-role check in the same file (`assert cfg.lora.role == "rtcm_rx+status_tx"`, near line 385) to `"status_tx_only"`.

In `tests/test_lora_protocol.py`, replace `test_empty_payload_roundtrip` and drop `TYPE_RTCM_CHUNK` from the import list:

```python
    def test_empty_payload_roundtrip(self):
        frame = encode_frame(TYPE_LINK, 0, b"")
        ptype, seq, decoded = decode_frame(frame)
        assert ptype == TYPE_LINK
        assert seq == 0
        assert decoded == b""

    def test_rtcm_chunk_type_is_retired(self):
        """DEC-031 amended 2026-09-23: no RTCM over LoRa; 0x10 stays reserved, unexported."""
        from rover import lora_protocol

        assert not hasattr(lora_protocol, "TYPE_RTCM_CHUNK")
```

(`TYPE_LINK` must be in that file's import list; add it if missing.)

In `tests/test_main.py`, extend `test_run_all_disabled_clean_exit` after the existing asserts:

```python
    import json

    meta = json.loads((session / "metadata.json").read_text())
    assert "lora_rtcm_used" not in meta
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q tests/test_config_session.py tests/test_lora_protocol.py tests/test_main.py::test_run_all_disabled_clean_exit`
Expected: FAIL — default role is `rtcm_rx+status_tx`, interval 1.0, the retired role is accepted, `TYPE_RTCM_CHUNK` exists, `lora_rtcm_used` is in metadata.

- [ ] **Step 3: Implement**

`src/rover/config.py`:

```python
    role: str = "status_tx_only"
```

in `LoraConfig`; in `_DEFAULTS["lora"]` set `"telemetry_interval_sec": 10.0,` and `"role": "status_tx_only",`; change the validation line to

```python
    _require_in("lora", "role", lo["role"], {"status_tx_only", "disabled"})
```

`config/default.toml`, `[lora]` block:

```toml
[lora]                            # DEC-031 (amended 2026-09-23) — STATUS/LINK telemetry only; no RTCM over LoRa
...
telemetry_interval_sec = 10.0     # STATUS/LINK Tx cadence; matches the Base-Station beacon on the shared channel
role = "status_tx_only"           # "status_tx_only" | "disabled"
```

(Keep every other line of the block unchanged; edit with the Edit tool, then run the LF probe.)

`src/rover/lora_protocol.py`: delete the `TYPE_RTCM_CHUNK` line and put in its place

```python
# 0x10 was RTCM_CHUNK (base → rover). Retired 2026-09-23 with DEC-031's
# amendment; the value stays reserved so no future type reuses it.
```

In the module docstring, change the Heltec/ESP32 sentence to name STATUS + LINK only, drop `TYPE_RTCM_CHUNK` from Public API, and add a changelog line:

```
    0.11.0  2026-09-23  TYPE_RTCM_CHUNK removed (DEC-031 amended: LoRa is
                        status-only); 0x10 reserved.
```

`src/rover/main.py`: delete the `metadata["lora_rtcm_used"] = ...` line in `run()`.

In `tests/test_telemetry.py`, update the docstring that says `role=rtcm_rx+status_tx` (the default-config test near line 318) to `role=status_tx_only`.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass (422 + 3 new = 425 or more). `test_firmware_parity` still passes (radio params unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/rover/config.py config/default.toml src/rover/lora_protocol.py src/rover/main.py tests/test_config_session.py tests/test_lora_protocol.py tests/test_main.py tests/test_telemetry.py
git commit -m "feat(lora): status-only at 10 s; retire RTCM_CHUNK (DEC-031 amended)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Sweep, mount and lever-arm config keys; stepper position and rewind speed

**Files:**
- Modify: `src/rover/config.py` (`StepperConfig`, `ImuConfig`, `CalibrationConfig`, `_DEFAULTS`, `_validate`, `load_config` construction of `CalibrationConfig`)
- Modify: `config/default.toml` (`[stepper]`, `[imu]`, `[calibration]`)
- Modify: `src/rover/stepper.py` (`current_step` property; `step(steps, rpm=None)`; changelog)
- Test: `tests/test_config.py`, `tests/test_stepper.py`

**Interfaces:**
- Produces:
  - `StepperConfig.sweep_deg: float = 360.0` (0 < x ≤ 360, and ≥ `step_interval_deg`); `StepperConfig.rewind_rpm: float = 10.0` (> 0); `StepperConfig.rest_before_sweep_sec: float = 2.0` (≥ 0).
  - `ImuConfig.mount: str = "base"` (∈ {`"base"`, `"platform"`}).
  - `CalibrationConfig.antenna_offset_m: list[float] | None = None` — vector from the LiDAR optical centre to the antenna phase centre, metres, platform frame at mast 0 (x forward, y left, z up).
  - `StepperMotor.current_step -> int`; `StepperMotor.step(steps: int, rpm: float | None = None) -> None` — `rpm=None` keeps the configured scan rate.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
class TestStage5GeometryKeys:
    def test_defaults(self):
        cfg = load_config()
        assert cfg.stepper.sweep_deg == 360.0
        assert cfg.stepper.rewind_rpm == 10.0
        assert cfg.stepper.rest_before_sweep_sec == 2.0
        assert cfg.imu.mount == "base"
        assert cfg.calibration.antenna_offset_m is None

    def test_default_toml_matches_defaults(self):
        cfg = load_config(Path("config/default.toml"))
        assert cfg.stepper.sweep_deg == 360.0
        assert cfg.stepper.rewind_rpm == 10.0
        assert cfg.imu.mount == "base"

    @pytest.mark.parametrize("value", [0, -10.0, 360.5, 720])
    def test_sweep_deg_range(self, tmp_toml, value):
        p = tmp_toml(f"[stepper]\nsweep_deg = {value}\n")
        with pytest.raises(ValueError, match=r"\[stepper\] sweep_deg"):
            load_config(p)

    def test_sweep_smaller_than_one_increment_rejected(self, tmp_toml):
        p = tmp_toml("[stepper]\nsweep_deg = 1.0\n")  # default increment is 1.575°
        with pytest.raises(ValueError, match=r"\[stepper\] sweep_deg"):
            load_config(p)

    def test_rewind_rpm_positive(self, tmp_toml):
        p = tmp_toml("[stepper]\nrewind_rpm = 0\n")
        with pytest.raises(ValueError, match=r"\[stepper\] rewind_rpm"):
            load_config(p)

    def test_rest_before_sweep_non_negative(self, tmp_toml):
        p = tmp_toml("[stepper]\nrest_before_sweep_sec = -1\n")
        with pytest.raises(ValueError, match=r"\[stepper\] rest_before_sweep_sec"):
            load_config(p)

    def test_mount_values(self, tmp_toml):
        assert load_config(tmp_toml('[imu]\nmount = "platform"\n')).imu.mount == "platform"
        with pytest.raises(ValueError, match=r"\[imu\] mount"):
            load_config(tmp_toml('[imu]\nmount = "mast"\n'))

    def test_antenna_offset(self, tmp_toml):
        cfg = load_config(tmp_toml("[calibration]\nantenna_offset_m = [0.0, 0.0, 0.35]\n"))
        assert cfg.calibration.antenna_offset_m == [0.0, 0.0, 0.35]
        with pytest.raises(ValueError, match=r"\[calibration\] antenna_offset_m"):
            load_config(tmp_toml("[calibration]\nantenna_offset_m = [0.0, 0.35]\n"))
```

(`Path`, `pytest` and `load_config` are already imported at the top of `tests/test_config.py`; add any that are not.)

Append to `tests/test_stepper.py`:

```python
class TestStage5StepperApi:
    @patch("rover.stepper.time")
    def test_current_step_tracks_moves(self, mock_time, stepper_config, mock_gpio):
        mock_time.monotonic.return_value = 0.0
        from rover.stepper import StepperMotor

        m = StepperMotor(stepper_config)
        m.start()
        m.step(14)
        m.step(-4)
        assert m.current_step == 10

    @patch("rover.stepper.time")
    def test_rpm_override_changes_pacing(self, mock_time, stepper_config, mock_gpio):
        """rpm=None paces at the configured scan rate; rpm=60 paces 60x faster.
        The pacing sleep is the LAST sleep of a one-step move (the 1 ms
        direction-setup sleep and the 2 µs pulse sleep come before it)."""
        mock_time.monotonic.return_value = 0.0
        from rover.stepper import StepperMotor

        m = StepperMotor(stepper_config)  # rpm = 1.0, 3200 steps/rev
        m.start()
        m.step(1)
        slow = mock_time.sleep.call_args_list[-1].args[0]
        m.step(1, rpm=60.0)
        fast = mock_time.sleep.call_args_list[-1].args[0]
        assert slow == pytest.approx(60.0 / 3200, rel=1e-6)  # 1 rpm → 18.75 ms/step
        assert fast == pytest.approx(1.0 / 3200, rel=1e-6)  # 60 rpm → 0.3125 ms/step
```

(`patch` is already imported at the top of `tests/test_stepper.py`; the decorator form matches the existing `test_step_positive`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q tests/test_config.py::TestStage5GeometryKeys tests/test_stepper.py::TestStage5StepperApi`
Expected: FAIL — unknown attributes / unknown config keys.

- [ ] **Step 3: Implement**

`src/rover/config.py` — dataclasses (new fields go last, with defaults, so existing positional constructions in tests keep working):

```python
@dataclass(frozen=True)
class StepperConfig:
    enabled: bool
    steps_per_rev: int
    rpm: float
    step_interval_deg: float
    direction_pin: int
    step_pin: int
    enable_pin: int
    sweep_deg: float = 360.0  # DEC-015 (amended): 360° forward, then rewind; never more
    rewind_rpm: float = 10.0
    rest_before_sweep_sec: float = 2.0  # IMU settles with the magnetometer on before each sweep
```

```python
@dataclass(frozen=True)
class ImuConfig:
    enabled: bool
    bus: int
    address: int
    sample_rate_hz: int
    use_magnetometer: bool
    fusion_beta: float
    mount: str = "base"  # "base" (fixed body) | "platform" (turns with the mast) — S3-R3
```

In `CalibrationConfig` add `antenna_offset_m: list[float] | None = None` after `mag_offset`. In `_DEFAULTS["stepper"]` add `"sweep_deg": 360.0, "rewind_rpm": 10.0, "rest_before_sweep_sec": 2.0`; in `_DEFAULTS["imu"]` add `"mount": "base"`.

Validation, in the `# -- stepper` block after the pin loop:

```python
    _require_type("stepper", "sweep_deg", st["sweep_deg"], (int, float))
    st["sweep_deg"] = float(st["sweep_deg"])
    if not (st["step_interval_deg"] <= st["sweep_deg"] <= 360.0):
        raise ValueError(
            f"[stepper] sweep_deg ({st['sweep_deg']}) must be between step_interval_deg "
            f"({st['step_interval_deg']}) and 360 (DEC-015: no slip ring)"
        )
    _require_type("stepper", "rewind_rpm", st["rewind_rpm"], (int, float))
    _require_positive("stepper", "rewind_rpm", st["rewind_rpm"])
    st["rewind_rpm"] = float(st["rewind_rpm"])
    _require_type("stepper", "rest_before_sweep_sec", st["rest_before_sweep_sec"], (int, float))
    if st["rest_before_sweep_sec"] < 0:
        raise ValueError("[stepper] rest_before_sweep_sec must be >= 0")
    st["rest_before_sweep_sec"] = float(st["rest_before_sweep_sec"])
```

(`sweep_deg = 0` and negatives fail the lower bound because `step_interval_deg` is already validated positive; the message names `[stepper] sweep_deg`.)

In the `# -- imu` block:

```python
    _require_type("imu", "mount", im["mount"], str)
    _require_in("imu", "mount", im["mount"], {"base", "platform"})
```

In the `# -- calibration` block, add `"antenna_offset_m"` to the tuple the 3-float loop iterates, and pass `antenna_offset_m=cal_raw.get("antenna_offset_m")` in the `CalibrationConfig(...)` construction in `load_config`.

`config/default.toml` — `[stepper]` gains

```toml
sweep_deg = 360.0                 # DEC-015 (amended 2026-09-23): 360° forward, then rewind; never more (no slip ring)
rewind_rpm = 10.0                 # rewind speed; no data is logged while rewinding
rest_before_sweep_sec = 2.0       # hold still before each sweep so the rest heading can be read
```

`[imu]` gains

```toml
mount = "base"                    # "base" (fixed body) | "platform" (turns with the mast); decided at the bench (S3-R3)
```

`[calibration]` gains the commented example

```toml
# antenna_offset_m = [0.0, 0.0, 0.35]           # LiDAR centre → antenna phase centre, metres, platform frame at mast 0
```

Run the LF probe on `config/default.toml`.

`src/rover/stepper.py`:

```python
    @property
    def current_step(self) -> int:
        """Signed microstep count from home (the position at start())."""
        return self._current_step

    def step(self, steps: int, rpm: float | None = None) -> None:
        """Move the motor by the given number of steps (negative = reverse).

        Args:
            steps: Number of steps to move. Positive = forward, negative = reverse.
            rpm: Pace for this move only; None uses the configured scan rpm.
                 The sweep rewind passes [stepper].rewind_rpm here.

        Raises:
            RuntimeError: If the stepper is not available.
        """
        if not self._available:
            raise RuntimeError("Stepper not available")

        if steps == 0:
            return

        step_interval = (
            self._step_interval if rpm is None else 60.0 / (rpm * self._config.steps_per_rev)
        )
```

…and use the local `step_interval` in place of `self._step_interval` inside the pacing loop. Add a changelog line to the module docstring (`current_step`; per-call rpm for the sweep rewind).

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/rover/config.py config/default.toml src/rover/stepper.py tests/test_config.py tests/test_stepper.py
git commit -m "feat(config,stepper): sweep_deg/rewind_rpm/rest, imu.mount, antenna_offset_m; current_step and per-call rpm" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: SweepPlanner and the rewinding scan state

**Files:**
- Create: `src/rover/sweep.py`
- Modify: `src/rover/lora_protocol.py` (`SCAN_REWINDING = 4`; `encode_status_payload` docstring says 0..4)
- Test: `tests/test_sweep.py` (new), `tests/test_lora_protocol.py`

**Interfaces:**
- Consumes: `StepperConfig` fields from Task 2.
- Produces:

```python
@dataclass(frozen=True)
class SweepAction:
    kind: str            # "rest" | "scan_step" | "rewind"
    steps: int = 0       # signed microsteps for scan_step (> 0) and rewind (< 0)
    seconds: float = 0.0 # for rest

class SweepPlanner:
    REWIND_CHUNK_DEG: float = 45.0
    def __init__(self, config: StepperConfig) -> None: ...
    sweep_index: int                      # 0-based; increments when a rewind reaches home
    sweep_steps: int                      # round(sweep_deg / 360 * steps_per_rev)
    def next_action(self, current_step: int) -> SweepAction: ...
```

`lora_protocol.SCAN_REWINDING == 4`.

- [ ] **Step 1: Write the failing tests** — `tests/test_sweep.py`

```python
"""SweepPlanner — pure decision logic for the 360-then-rewind sweep (DEC-015 amended)."""

from __future__ import annotations

from rover.config import StepperConfig
from rover.sweep import SweepAction, SweepPlanner


def _cfg(sweep_deg=9.0, step_interval_deg=1.125, rest=0.5) -> StepperConfig:
    return StepperConfig(
        enabled=True,
        steps_per_rev=3200,
        rpm=1.0,
        step_interval_deg=step_interval_deg,
        direction_pin=17,
        step_pin=27,
        enable_pin=22,
        sweep_deg=sweep_deg,
        rewind_rpm=10.0,
        rest_before_sweep_sec=rest,
    )


def _run(planner: SweepPlanner, n: int) -> list[SweepAction]:
    """Simulate a perfect stepper for n actions."""
    pos = 0
    out = []
    for _ in range(n):
        a = planner.next_action(pos)
        out.append(a)
        pos += a.steps
    return out


def test_rest_then_scan_then_rewind_then_rest():
    p = SweepPlanner(_cfg())  # 9° sweep = 80 steps, 10-step increments
    acts = _run(p, 12)
    assert acts[0] == SweepAction("rest", seconds=0.5)
    assert [a.kind for a in acts[1:9]] == ["scan_step"] * 8
    assert all(a.steps == 10 for a in acts[1:9])
    assert acts[9] == SweepAction("rewind", steps=-80)  # 80 steps < one 45° chunk (400)
    assert acts[10] == SweepAction("rest", seconds=0.5)
    assert acts[11].kind == "scan_step"
    assert p.sweep_index == 1


def test_last_increment_is_clamped_to_sweep_end():
    p = SweepPlanner(_cfg(sweep_deg=10.0))  # 10° = 88.9 → 89 steps
    acts = _run(p, 11)
    scan = [a.steps for a in acts if a.kind == "scan_step"]
    assert sum(scan) == 89
    assert scan[-1] == 9


def test_full_360_never_exceeds_one_turn_and_rewinds_in_45deg_chunks():
    p = SweepPlanner(_cfg(sweep_deg=360.0, step_interval_deg=1.575))  # 3200 steps, 14/step
    pos = 0
    peak = 0
    rewinds = []
    for _ in range(400):
        a = p.next_action(pos)
        pos += a.steps
        peak = max(peak, pos)
        if a.kind == "rewind":
            rewinds.append(a.steps)
        if p.sweep_index == 1:
            break
    assert peak == 3200
    assert pos == 0
    assert all(-400 <= s < 0 for s in rewinds)  # 45° = 400 steps
    assert sum(rewinds) == -3200


def test_planner_is_position_based():
    """A step that fails leaves the position unchanged; the planner must ask
    for the same increment again, never assume the move happened (Review Focus 3)."""
    p = SweepPlanner(_cfg())
    assert p.next_action(0).kind == "rest"
    first = p.next_action(0)
    again = p.next_action(0)  # the move above failed: still at 0
    assert first == again == SweepAction("scan_step", steps=10)
    # A position past the end (should never happen, but must not scan further)
    assert p.next_action(95).kind == "rewind"


def test_zero_rest_still_emits_rest_action():
    """rest_before_sweep_sec = 0 still yields a rest action (the loop logs sweep_start there)."""
    p = SweepPlanner(_cfg(rest=0.0))
    assert p.next_action(0) == SweepAction("rest", seconds=0.0)
```

Append to `tests/test_lora_protocol.py`:

```python
def test_scan_rewinding_state_encodes():
    from rover.lora_protocol import SCAN_REWINDING, decode_status_payload, encode_status_payload

    assert SCAN_REWINDING == 4
    payload = encode_status_payload(
        fix_type=5, sat_count=18, hdop=0.85, battery_mv=11800, scan_state=SCAN_REWINDING
    )
    assert decode_status_payload(payload)["scan_state"] == 4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q tests/test_sweep.py tests/test_lora_protocol.py::test_scan_rewinding_state_encodes`
Expected: FAIL — `ModuleNotFoundError: rover.sweep`; `SCAN_REWINDING` missing.

- [ ] **Step 3: Implement** — `src/rover/sweep.py`

```python
"""Sweep planner — 360-then-rewind mast motion (DEC-015, amended 2026-09-23).

Pure decision logic, no I/O: given the stepper's actual position it returns the
next action for the acquisition loop. Position-based on purpose — a failed
step leaves the position unchanged, and the planner simply asks for the same
move again instead of drifting past the sweep end.

Cycle: rest (magnetometer on, platform still) → scan steps up to sweep_deg →
rewind to home in chunks of at most REWIND_CHUNK_DEG → rest → ...

Changelog:
    0.1.0  2026-09-23  Initial (stage 5).
"""

from __future__ import annotations

from dataclasses import dataclass

from rover.config import StepperConfig


@dataclass(frozen=True)
class SweepAction:
    kind: str  # "rest" | "scan_step" | "rewind"
    steps: int = 0
    seconds: float = 0.0


class SweepPlanner:
    """Decides rest → scan_step* → rewind* → rest from the stepper's real position."""

    REWIND_CHUNK_DEG: float = 45.0  # bounds stop latency during a rewind

    def __init__(self, config: StepperConfig) -> None:
        per_rev = config.steps_per_rev
        self._increment = max(1, round(config.step_interval_deg / (360.0 / per_rev)))
        self.sweep_steps = round(config.sweep_deg / 360.0 * per_rev)
        self._rewind_chunk = max(1, round(self.REWIND_CHUNK_DEG / 360.0 * per_rev))
        self._rest_sec = config.rest_before_sweep_sec
        self._phase = "rest"
        self.sweep_index = 0

    def next_action(self, current_step: int) -> SweepAction:
        if self._phase == "rest":
            self._phase = "scan"
            return SweepAction("rest", seconds=self._rest_sec)
        if self._phase == "scan":
            remaining = self.sweep_steps - current_step
            if remaining > 0:
                return SweepAction("scan_step", steps=min(self._increment, remaining))
            self._phase = "rewind"
        # rewind
        if current_step > 0:
            return SweepAction("rewind", steps=-min(self._rewind_chunk, current_step))
        self._phase = "scan"
        self.sweep_index += 1
        return SweepAction("rest", seconds=self._rest_sec)
```

`src/rover/lora_protocol.py`, after `SCAN_ERROR = 3`:

```python
SCAN_REWINDING = 4  # mast returning home after a sweep; no data logged (DEC-015 amended)
```

and change the `encode_status_payload` docstring line to `scan_state: 0..4 (see SCAN_* constants).`

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q tests/test_sweep.py tests/test_lora_protocol.py` then `python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rover/sweep.py src/rover/lora_protocol.py tests/test_sweep.py tests/test_lora_protocol.py
git commit -m "feat(sweep): position-based 360-then-rewind planner; SCAN_REWINDING" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Acquisition loop executes the sweep

**Files:**
- Modify: `src/rover/main.py` (`_scan_loop` step block; lidar record `sweep` field; `sweep_start` event; `run()` metadata `geometry` block; changelog 0.12.0)
- Test: `tests/test_main.py` (`_FakeStepper`, `_BrokenStepper`, `_stage3_config`, `test_records_are_columnar_with_mast_angle_and_imu_batches`, new tests)

**Interfaces:**
- Consumes: `SweepPlanner`, `SweepAction` (Task 3); `StepperMotor.current_step`, `step(steps, rpm=None)`, `StepperConfig.rewind_rpm` (Task 2); `SCAN_REWINDING` (Task 3).
- Produces (record format, read by Task 6):
  - lidar records gain `"sweep": int`.
  - event `{"type": "event", "timestamp": t, "event": "sweep_start", "details": {"sweep": k, "rest_sec": s}}`, written at the end of each rest, before the sweep's first step.
  - `metadata.json` gains `"geometry": {"imu_mount": str, "antenna_offset_m": list | None, "sweep_deg": float, "rewind_rpm": float, "rest_before_sweep_sec": float}`.

Loop behaviour per action (stepper present and not tripped):

| action | stepper | magnetometer | IMU drain | lidar / camera | scan_state |
|---|---|---|---|---|---|
| `rest` | none | `use_magnetometer` | drain **and log** (rest samples carry the heading) | skipped | SCANNING |
| `scan_step` | `step(n)` | off during step, back on after settle (DEC-013, unchanged) | drain and log | read and log, `sweep` tagged | SCANNING |
| `rewind` | `step(-n, rpm=rewind_rpm)` | off | drain and **discard** | skipped | REWINDING |

The ERROR override at the end of the iteration (tripped stepper gate or NTRIP fatal) stays last. `step_index` increments only on `scan_step` iterations (camera cadence and record numbering count scans, not rests or rewinds). With no stepper, or a tripped stepper gate, the loop behaves exactly as today (continuous mode).

- [ ] **Step 1: Write the failing tests**

In `tests/test_main.py`, replace `_FakeStepper` and `_BrokenStepper`:

```python
class _FakeStepper:
    moves: list[tuple[int, float | None]] = []

    def __init__(self, *_a, **_kw) -> None:
        self._step = 0

    @property
    def available(self) -> bool:
        return True

    @property
    def current_step(self) -> int:
        return self._step

    @property
    def current_angle(self) -> float:
        return self._step * (360.0 / 3200)

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def step(self, steps: int, rpm: float | None = None) -> None:
        type(self).moves.append((steps, rpm))
        self._step += steps
```

```python
class _BrokenStepper(_FakeStepper):
    fails = 0

    def step(self, steps: int, rpm: float | None = None) -> None:
        type(self).fails += 1
        raise RuntimeError("stall")
```

In `_stage3_config`, add under `[stepper]`:

```toml
rest_before_sweep_sec = 0.0
```

In `test_records_are_columnar_with_mast_angle_and_imu_batches`, replace the DEC-013 assertion with

```python
    # The first iteration is the rest (magnetometer on); DEC-013 gating then
    # disables it before each step and re-enables it after settle.
    assert _FakeImu.mag_calls[0] is True
    assert _FakeImu.mag_calls[1:3] == [False, True]
```

and add `assert r["sweep"] == 0`.

Add a sweep config helper and tests:

```python
def _sweep_config(tmp_path: Path, sweep_deg: float = 9.0, rest: float = 0.05) -> Path:
    cfg = tmp_path / "sweep.toml"
    cfg.write_text(
        f"""
[lidar]
enabled = true
scan_rate_hz = 20                 # config allows 1..20; 50 ms settle keeps these tests short

[stepper]
enabled = true
steps_per_rev = 3200
step_interval_deg = 1.125
sweep_deg = {sweep_deg}
rewind_rpm = 30.0
rest_before_sweep_sec = {rest}

[imu]
enabled = true
use_magnetometer = true
mount = "platform"

[calibration]
antenna_offset_m = [0.0, 0.0, 0.35]

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
session_prefix = "sw"
"""
    )
    return cfg


def _records(tmp_path: Path, prefix: str) -> tuple[list[dict], dict]:
    import json

    session = next((tmp_path / "data").glob(f"{prefix}_*"))
    recs = [json.loads(x) for x in (session / "scan.jsonl").read_text().splitlines() if x]
    meta = json.loads((session / "metadata.json").read_text())
    return recs, meta


def test_sweep_rewinds_and_never_exceeds_sweep_deg(tmp_path: Path, monkeypatch) -> None:
    """DEC-015 (amended): 9° forward, rewind, repeat — the mast never passes 9°."""
    _FakeStepper.moves = []
    published: list[int] = []
    monkeypatch.setattr(main_mod, "StepperMotor", _FakeStepper)
    monkeypatch.setattr(main_mod, "LidarScanner", _StaticLidar)
    monkeypatch.setattr(main_mod, "ImuDriver", _FakeImu)

    class _SpyRouter(main_mod.TelemetryRouter):
        def publish(self, status):
            published.append(status.scan_state)
            return super().publish(status)

    monkeypatch.setattr(main_mod, "TelemetryRouter", _SpyRouter)
    assert main_mod.run(config_path=_sweep_config(tmp_path), duration_sec=2.5) == 0

    pos = peak = 0
    for steps, _rpm in _FakeStepper.moves:
        pos += steps
        peak = max(peak, pos)
    assert peak == 80  # 9° at 3200 steps/rev
    rewinds = [(s, rpm) for s, rpm in _FakeStepper.moves if s < 0]
    assert rewinds, "never rewound"
    assert all(rpm == 30.0 for _s, rpm in rewinds)
    assert all(rpm is None for s, rpm in _FakeStepper.moves if s > 0)
    assert main_mod.SCAN_REWINDING in published

    recs, meta = _records(tmp_path, "sw")
    lidar = [r for r in recs if r["type"] == "lidar"]
    assert {r["sweep"] for r in lidar} >= {0, 1}
    assert all(0.0 < r["mast_angle_deg"] <= 9.0 for r in lidar)  # nothing logged at home / mid-rewind
    starts = [r for r in recs if r.get("event") == "sweep_start"]
    assert [e["details"]["sweep"] for e in starts][:2] == [0, 1]
    assert meta["geometry"] == {
        "imu_mount": "platform",
        "antenna_offset_m": [0.0, 0.0, 0.35],
        "sweep_deg": 9.0,
        "rewind_rpm": 30.0,
        "rest_before_sweep_sec": 0.05,
    }


class _MarkingImu(_FakeImu):
    """Marks every sample drained while the magnetometer is off. Only the
    rewind drains with it off: a scan step re-enables it after settle (before
    the drain), and a rest enables it before draining."""

    marked = 0

    def drain(self):
        from rover.imu import ImuSample

        rewinding = bool(type(self).mag_calls) and type(self).mag_calls[-1] is False
        if rewinding:
            type(self).marked += 1
        q = (0.0, 1.0, 0.0, 0.0) if rewinding else (1.0, 0.0, 0.0, 0.0)
        return [
            ImuSample(timestamp=time.time(), accel=(0, 0, 9.81), gyro=(0, 0, 0), mag=None, orientation=q)
        ]


def test_no_records_logged_during_rewind(tmp_path: Path, monkeypatch) -> None:
    """Rewind drains the IMU and discards it; no marked sample reaches scan.jsonl,
    and no lidar record is written between a sweep's end and the next sweep_start."""
    _FakeStepper.moves = []
    _FakeImu.mag_calls = []
    _MarkingImu.marked = 0
    monkeypatch.setattr(main_mod, "StepperMotor", _FakeStepper)
    monkeypatch.setattr(main_mod, "LidarScanner", _StaticLidar)
    monkeypatch.setattr(main_mod, "ImuDriver", _MarkingImu)
    assert main_mod.run(config_path=_sweep_config(tmp_path), duration_sec=2.5) == 0
    recs, _meta = _records(tmp_path, "sw")
    assert _MarkingImu.marked >= 1, "no rewind drain happened — the test proves nothing"
    logged_orientations = [o for r in recs if r["type"] == "imu" for o in r["orientation"]]
    assert [0.0, 1.0, 0.0, 0.0] not in logged_orientations
    last0 = max(r["timestamp"] for r in recs if r["type"] == "lidar" and r["sweep"] == 0)
    start1 = next(
        r["timestamp"] for r in recs if r.get("event") == "sweep_start" and r["details"]["sweep"] == 1
    )
    assert not [r for r in recs if r["type"] == "lidar" and last0 < r["timestamp"] < start1]


def test_stop_during_rewind_is_prompt(tmp_path: Path, monkeypatch) -> None:
    """Review Focus 2: a stop during a 360° rewind lands within one 45° chunk."""
    moves: list[int] = []
    stop = threading.Event()

    class _SlowRewindStepper(_FakeStepper):
        def step(self, steps: int, rpm: float | None = None) -> None:
            moves.append(steps)
            if steps < 0:
                time.sleep(0.2)  # a chunk takes time on real hardware
                stop.set()  # SIGTERM arrives mid-rewind
            self._step += steps

    monkeypatch.setattr(main_mod, "StepperMotor", _SlowRewindStepper)
    monkeypatch.setattr(main_mod, "LidarScanner", _StaticLidar)
    monkeypatch.setattr(main_mod, "ImuDriver", _FakeImu)
    t0 = time.monotonic()
    assert main_mod.run(config_path=_sweep_config(tmp_path, sweep_deg=90.0, rest=0.0),
                        duration_sec=30.0, stop_event=stop) == 0
    assert time.monotonic() - t0 < 25.0
    assert sum(1 for s in moves if s < 0) == 1, "loop kept rewinding after stop"
```

(Keep `test_stepper_failures_are_gated_and_still_publish` as is; with `rest_before_sweep_sec = 0.0` in `_stage3_config` its `fails == 5` expectation is unchanged.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q tests/test_main.py`
Expected: FAIL — no `sweep` field, no rewind moves, no `geometry` in metadata; the columnar test fails on `mag_calls[0]`.

- [ ] **Step 3: Implement** — `src/rover/main.py`

Imports: add `from rover.sweep import SweepPlanner` and extend the `lora_protocol` import to `SCAN_ERROR, SCAN_REWINDING, SCAN_SCANNING`.

Before the loop (next to the gates):

```python
    planner: SweepPlanner | None = None
    if sensors.stepper is not None and sensors.stepper.available and steps_per_increment > 0:
        planner = SweepPlanner(config.stepper)
```

Replace the `# --- Step + settle ---` block down to (and including) the `mast_angle_deg = ...` assignment with:

```python
        # --- Sweep action (DEC-015 amended: rest → scan steps → rewind) ---
        stepped = False
        step_ok = True
        action = None
        if planner is not None and not stepper_gate.tripped:
            action = planner.next_action(sensors.stepper.current_step)

        if action is not None and action.kind == "rest":
            if sensors.imu is not None and sensors.imu.available:
                sensors.imu.enable_magnetometer(config.imu.use_magnetometer)
            stop_event.wait(action.seconds)
            rest_batch: list = []
            if sensors.imu is not None and sensors.imu.available and not imu_gate.tripped:
                try:
                    rest_batch = sensors.imu.drain()
                    imu_gate.record_success()
                except _SENSOR_ERRORS as e:
                    if imu_gate.record_failure(e):
                        _note_gate_trip(session_logger, imu_gate, e)
            if rest_batch:
                session_logger.write(_imu_record(rest_batch))
            session_logger.write(
                {
                    "type": "event",
                    "timestamp": time.time(),
                    "event": "sweep_start",
                    "details": {"sweep": planner.sweep_index, "rest_sec": action.seconds},
                }
            )
            status.scan_state = SCAN_SCANNING
            _publish(status)
            continue

        if action is not None and action.kind == "rewind":
            if sensors.imu is not None and sensors.imu.available:
                sensors.imu.enable_magnetometer(False)  # DEC-013: stepper EMI
            try:
                sensors.stepper.step(action.steps, rpm=config.stepper.rewind_rpm)
                stepper_gate.record_success()
            except Exception as e:
                if stepper_gate.record_failure(e):
                    _note_gate_trip(session_logger, stepper_gate, e)
                stop_event.wait(0.5)
            if sensors.imu is not None and sensors.imu.available:
                try:
                    sensors.imu.drain()  # rewind samples are not scan data
                except _SENSOR_ERRORS:
                    pass
            status.scan_state = SCAN_REWINDING
            _publish(status)
            continue

        if action is not None:  # scan_step
            if sensors.imu is not None and sensors.imu.available:
                sensors.imu.enable_magnetometer(False)  # DEC-013: stepper EMI
            try:
                sensors.stepper.step(action.steps)
                stepped = True
                stepper_gate.record_success()
                status.scan_state = SCAN_SCANNING
            except Exception as e:
                step_ok = False
                if stepper_gate.record_failure(e):
                    _note_gate_trip(session_logger, stepper_gate, e)
                status.scan_state = SCAN_ERROR
        if step_ok:
            stop_event.wait(settle_sec)
        else:
            stop_event.wait(0.5)
        if sensors.imu is not None and sensors.imu.available:
            sensors.imu.enable_magnetometer(config.imu.use_magnetometer)
        mast_angle_deg = (
            sensors.stepper.current_angle
            if sensors.stepper is not None and sensors.stepper.available
            else 0.0
        )
        sweep_index = planner.sweep_index if planner is not None else 0
```

Factor the existing telemetry tail into a local closure so rest/rewind iterations publish through the same path. Define it once, before the `while` loop:

```python
    def _publish(st) -> None:
        st.timestamp_epoch = time.time()
        st.sensors_disabled = [g.name for g in gates if g.tripped]
        st.logger_degraded = session_logger.degraded
        nonlocal ntrip_fatal_noted
        if ntrip_client is not None:
            ntrip_stats = ntrip_client.stats
            st.ntrip_connected = ntrip_stats.connected
            st.ntrip_bytes_per_sec = ntrip_stats.bytes_received_this_sec
            if ntrip_client.fatal_error is not None and not ntrip_fatal_noted:
                ntrip_fatal_noted = True
                logger.error(
                    "NTRIP fatal mid-session (continuing scan without RTK corrections): %s",
                    ntrip_client.fatal_error,
                )
        if stepper_gate.tripped or (
            ntrip_client is not None and ntrip_client.fatal_error is not None
        ):
            st.scan_state = SCAN_ERROR
        telemetry.publish(st)
```

(Carry the two existing explanatory comments — the mid-session-fatal comment and the "scan_state is derived from persistent conditions" comment — into this closure verbatim. `_scan_loop` is a function, so `nonlocal` works on its local `ntrip_fatal_noted`.) Replace the old inline telemetry block at the end of the iteration with `_publish(status)`; keep the `status.timestamp_epoch = now` semantics by leaving the closure's `time.time()` (the difference is sub-millisecond).

Factor the IMU record dict into a module-level helper used by both the rest path and the existing IMU logging:

```python
def _imu_record(batch: list) -> dict:
    return {
        "type": "imu",
        "timestamp": batch[-1].timestamp,
        "t": [s.timestamp for s in batch],
        "accel": [list(s.accel) for s in batch],
        "gyro": [list(s.gyro) for s in batch],
        "mag": [list(s.mag) if s.mag is not None else None for s in batch],
        "orientation": [list(s.orientation) for s in batch],
    }
```

Add `"sweep": sweep_index,` to the lidar record dict (after `"step_index"`). Change the final `step_index += 1` so it runs only when this iteration was a scan (`action is None or action.kind == "scan_step"`) — the rest and rewind branches `continue` before reaching it, so no condition is needed if it stays at the end of the loop body.

Remove the old `steps_per_increment`-driven `sensors.stepper.step(steps_per_increment)` call (the planner owns increments now); keep `steps_per_increment` only for the planner guard and `settle_sec`.

In `run()`, next to the `ntrip_stats` metadata:

```python
        metadata["geometry"] = {
            "imu_mount": config.imu.mount,
            "antenna_offset_m": config.calibration.antenna_offset_m,
            "sweep_deg": config.stepper.sweep_deg,
            "rewind_rpm": config.stepper.rewind_rpm,
            "rest_before_sweep_sec": config.stepper.rest_before_sweep_sec,
        }
```

Module docstring changelog:

```
    0.12.0  2026-09-23  Sweep executed by rover.sweep.SweepPlanner (DEC-015
                         amended): rest with the magnetometer on and IMU logged,
                         scan steps to sweep_deg, rewind in <=45° chunks at
                         rewind_rpm with nothing logged and SCAN_REWINDING
                         published. Fixes the loop that stepped one direction
                         forever and would wind every cable around the rod.
                         Lidar records carry "sweep"; a sweep_start event ends
                         each rest; metadata.json carries a "geometry" block.
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q tests/test_main.py` then `python -m pytest -q`
Expected: PASS. `test_round_trip_produces_points` must still pass (georef ignores the new field until Task 6).

- [ ] **Step 5: Commit**

```bash
git add src/rover/main.py tests/test_main.py
git commit -m "fix(main): sweep 360 then rewind instead of stepping one direction forever (DEC-015 amended)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Magnetic declination helper (WMM 2025)

**Files:**
- Modify: `pyproject.toml` (`pygeomag>=1.1,<2` in `post` and `dev`)
- Modify: `scripts/georef.py` (new `magnetic_declination_deg`)
- Test: `tests/test_georef.py`

**Interfaces:**
- Produces: `georef.magnetic_declination_deg(lat: float, lon: float, when_epoch: float) -> float | None` — east-positive degrees from WMM 2025 at the ellipsoid surface; `None` (with a WARNING) when pygeomag is missing or the date is outside the model's life span.

Known answers (pygeomag 1.1.0, `wmm/WMM_2025.COF`, altitude 0, measured 2026-09-23): State College PA (40.79, −77.86) on 2026-09-23 → **−10.5348°**; Scranton (41.40, −75.66) on 2026-09-23 → about −11.8°. Both agree with the sibling repo's "about −11° in PA".

- [ ] **Step 1: Install the dependency**

Run: `python -m pip install "pygeomag>=1.1,<2"`
Expected: `pygeomag 1.1.x` installed. (Without it the tests below skip, and a skipped known-answer test proves nothing — install it.)

- [ ] **Step 2: Write the failing tests** (append to `tests/test_georef.py`)

```python
class TestDeclination:
    _WHEN = 1790121600.0  # 2026-09-23T00:00:00Z

    def test_state_college_known_answer(self):
        pytest.importorskip("pygeomag", reason="pygeomag not installed (post/dev extra)")
        d = georef.magnetic_declination_deg(40.79, -77.86, self._WHEN)
        assert d == pytest.approx(-10.5348, abs=0.01)

    def test_east_pa_is_more_westerly_than_central(self):
        pytest.importorskip("pygeomag", reason="pygeomag not installed (post/dev extra)")
        central = georef.magnetic_declination_deg(40.79, -77.86, self._WHEN)
        east = georef.magnetic_declination_deg(41.40, -75.66, self._WHEN)
        assert east < central < -9.0

    def test_outside_lifespan_returns_none(self, caplog):
        """Review Focus 5: WMM 2025 ends in 2030; a later session falls back."""
        pytest.importorskip("pygeomag", reason="pygeomag not installed (post/dev extra)")
        when_2031 = 1940000000.0  # 2031-06-23
        with caplog.at_level("WARNING", logger="georef"):
            assert georef.magnetic_declination_deg(40.79, -77.86, when_2031) is None
        assert any("life span" in r.message or "lifespan" in r.message for r in caplog.records)

    def test_missing_library_returns_none(self, monkeypatch, caplog):
        monkeypatch.setattr(georef, "_optional_import", lambda name: None)
        with caplog.at_level("WARNING", logger="georef"):
            assert georef.magnetic_declination_deg(40.79, -77.86, self._WHEN) is None
        assert any("pygeomag" in r.message for r in caplog.records)
```

Before relying on `_WHEN`, verify it: `python -c "import datetime;print(datetime.datetime.fromtimestamp(1790121600, datetime.UTC))"` must print `2026-09-23 00:00:00+00:00`; if not, use the printed value's correct epoch and fix the constant.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest -q tests/test_georef.py::TestDeclination`
Expected: FAIL — `AttributeError: magnetic_declination_deg`.

- [ ] **Step 4: Implement** — `scripts/georef.py`, in a new `# Heading reference` section after the geometry helpers

```python
def magnetic_declination_deg(lat: float, lon: float, when_epoch: float) -> float | None:
    """WMM 2025 declination (degrees, east-positive) at the ellipsoid surface.

    Returns None — and says why — when pygeomag is not installed or the date
    is outside the model's five-year life span; the caller then labels the
    heading "magnetic" instead of "true".
    """
    pygeomag = _optional_import("pygeomag")
    if pygeomag is None:
        logger.warning(
            'pygeomag not installed — heading stays magnetic; install via `pip install -e ".[post]"`'
        )
        return None
    from datetime import UTC, datetime

    day = datetime.fromtimestamp(when_epoch, UTC).date()
    year = pygeomag.decimal_year_from_date(day)
    try:
        result = pygeomag.GeoMag(coefficients_file="wmm/WMM_2025.COF").calculate(
            glat=lat, glon=lon, alt=0.0, time=year
        )
    except ValueError as e:
        logger.warning("WMM 2025 cannot give a declination for %s (%s) — heading stays magnetic", day, e)
        return None
    return float(result.d)
```

(pygeomag's own message is "Time extends beyond model 5-year life span"; the WARNING includes it, which the lifespan test matches.)

`pyproject.toml`: add `"pygeomag>=1.1,<2",` to both `post` and `dev`.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest -q tests/test_georef.py::TestDeclination` then `python -m pytest -q`
Expected: PASS, 0 skips in `TestDeclination`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml scripts/georef.py tests/test_georef.py
git commit -m "feat(georef): WMM 2025 magnetic declination helper (S3-R1)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Heading model — NWU→ENU, per-sweep rest heading, tilt per scan, mount, lever arm

**Files:**
- Modify: `scripts/georef.py` (`SessionData.sweep_starts`; `load_session`; new helpers; `session_to_pointcloud`; docstring coordinate flow + changelog 0.14.0)
- Test: `tests/test_georef.py` (update `TestYawStripWithoutMag.test_yaw_kept_with_mag`; new `TestHeadingModel`)

**Interfaces:**
- Consumes: `magnetic_declination_deg` (Task 5); lidar `sweep`, `sweep_start` events and `metadata["geometry"]` (Task 4).
- Produces:
  - `SessionData.sweep_starts: dict[int, float]` (sweep index → `sweep_start` timestamp; empty for old sessions). Give it a default (`field(default_factory=dict)`) so existing constructions still work.
  - `session_to_pointcloud(session, info: dict | None = None)` — unchanged 3-tuple return; when `info` is given it is filled with `{"heading_reference": "true" | "magnetic" | "relative", "declination_deg": float | None, "imu_mount": str, "antenna_offset_m": list | None}`. Task 7 writes this into `export.json`.

The model (all rotations are 3×3, applied to column vectors; `C = _rot_z(90.0)` maps NWU to ENU):

1. **Mount.** `m_imu(rec) = rec["mast_angle_deg"]` when `geometry.imu_mount == "platform"`, else `0.0`.
2. **Tilt per scan.** `T = strip_yaw(R(q_t) · Rz(-m_imu))`, with `q_t = orientation_at(t_scan)`. For a base mount this is the base tilt; for a platform mount the mast rotation is removed first, leaving the same base tilt.
3. **Rest heading per sweep.** Rest samples for sweep k are IMU samples that carry `mag` and whose timestamp is in `(end of sweep k-1, rest_end_k]`. `rest_end_k` is `sweep_starts[k]`, or, for old sessions, the first lidar timestamp of sweep k. "End of sweep k-1" is its last lidar timestamp, or −∞ for k = 0. At rest the mast is home, so no mount correction applies. `yaw_ref_k` is the circular mean over those samples of `yaw(Rz(-D) · C · R(q))`, where `yaw(r) = atan2(r[1,0], r[0,0])` in degrees, and `D` is the declination, or 0 when unknown.
4. **Missing rest samples.** A sweep with none reuses the nearest earlier sweep's `yaw_ref`, else the nearest later one, with one WARNING. If no sweep has any, the heading is `"relative"`: `yaw_ref = 0`, which puts mast-0 forward on +X. The INFO line must contain the words `no magnetometer data`, because an existing test matches them.
5. **Label.** `"true"` when rest samples exist and `D` is not None. `"magnetic"` when rest samples exist and `D` is None, which covers no GNSS origin and no WMM. Otherwise `"relative"`. `D` is computed once, from the GNSS origin and the first lidar timestamp, and only when rest samples and a GNSS origin both exist.
6. **World orientation per scan.** `q_world = quat(Rz(yaw_ref_k) · T)`, then `lidar_points_to_local(rec, q_world)`. That function is unchanged: mount, then `Rz(mast)`, then `q_world`.
7. **Lever arm.** When an origin exists and `antenna_offset_m` is set: `arm = R(q_world) · Rz(mast) · a`, and `pts = pts - arm + [dE, dN, dU]`. The GNSS fix is the antenna, so the LiDAR sits at antenna minus arm.

Replace the old `strip_yaw` flag logic in `session_to_pointcloud` with this model.

- [ ] **Step 1: Write the failing tests**

Update `TestYawStripWithoutMag.test_yaw_kept_with_mag` — the IMU's 90° yaw is in NWU, so it now lands differently:

```python
    def test_yaw_kept_with_mag(self, tmp_path):
        """With mag at rest the heading is kept and converted from Madgwick's
        NWU frame to ENU (S3-R1). A 90° yaw in NWU turns body forward from
        magnetic north (NWU +x) to west (NWU +y), which is ENU -x. No GNSS, so
        no declination: the label is "magnetic"."""
        sess = self._session(tmp_path, mag=[1.0, 2.0, 3.0])
        data = georef.load_session(sess)
        xyz, _intensity, _origin = georef.session_to_pointcloud(data)
        np.testing.assert_allclose(xyz[0], [-1.0, 0.0, 0.0], atol=1e-9)
```

Add:

```python
def _heading_session(
    tmp_path: Path,
    *,
    name: str = "hd",
    rest_q=(1.0, 0.0, 0.0, 0.0),
    scan_q=None,
    mag=(20.0, 0.0, -40.0),
    with_gnss: bool = True,
    mast_angles=(0.0,),
    mount: str = "base",
    antenna_offset=None,
    when: float = 1790121600.0,
    platform_q_follows_mast: bool = False,
) -> Path:
    """Rest IMU sample (with mag) at `when`, sweep_start at when+0.1, one lidar
    point 1 m straight ahead per mast angle, GNSS fix at State College."""
    import math

    sess = tmp_path / name
    sess.mkdir()
    meta = {
        "session": {"profile": "personal", "target_crs_epsg": 0, "units": "m"},
        "geometry": {"imu_mount": mount, "antenna_offset_m": antenna_offset},
    }
    (sess / "metadata.json").write_text(json.dumps(meta))
    lines = [json.dumps(_imu_batch([when], orientation=rest_q, mag=list(mag) if mag else None))]
    lines.append(json.dumps({"type": "event", "timestamp": when + 0.1, "event": "sweep_start", "details": {"sweep": 0, "rest_sec": 0.1}}))
    if with_gnss:
        lines.append(json.dumps({"type": "gnss", "timestamp": when + 0.2, "fix_type": 5, "lat": 40.79, "lon": -77.86, "alt": 300.0, "hdop": 0.8, "vdop": 1.0, "sat_count": 18, "rtk_age": 1.0}))
    for i, m in enumerate(mast_angles):
        t = when + 1.0 + i
        q = scan_q if scan_q is not None else rest_q
        if platform_q_follows_mast:
            # IMU on the platform: R_platform = R_base · Rz(mast)
            q = tuple(
                float(v)
                for v in georef._rotmat_to_quat(georef._quat_to_rotmat(q) @ georef._rot_z(m))
            )
        lines.append(json.dumps(_imu_batch([t - 0.01, t + 0.01], orientation=q, mag=None)))
        rec = _lidar_record(t, i, float(m), [0.0], [1.0], [1])
        rec["sweep"] = 0
        lines.append(json.dumps(rec))
    (sess / "scan.jsonl").write_text("\n".join(lines) + "\n")
    return sess


class TestHeadingModel:
    D_STATE_COLLEGE = -10.5348  # Task 5 known answer, 2026-09-23

    def test_true_north_known_answer(self, tmp_path):
        """Body forward = magnetic north at rest (identity NWU quaternion). With
        D = -10.53°, a point 1 m ahead lies at true azimuth 349.47°:
        ENU (-sin 10.53°, cos 10.53°, 0)."""
        pytest.importorskip("pygeomag", reason="pygeomag not installed (post/dev extra)")
        import math

        data = georef.load_session(_heading_session(tmp_path))
        info: dict = {}
        xyz, _i, _o = georef.session_to_pointcloud(data, info=info)
        d = math.radians(-self.D_STATE_COLLEGE)
        np.testing.assert_allclose(xyz[0], [-math.sin(d), math.cos(d), 0.0], atol=1e-3)
        assert info["heading_reference"] == "true"
        assert info["declination_deg"] == pytest.approx(self.D_STATE_COLLEGE, abs=0.01)

    def test_magnetic_label_without_gnss(self, tmp_path):
        """Review Focus 4: mag at rest, no GNSS → 'magnetic', no declination,
        forward = magnetic north = ENU +y."""
        data = georef.load_session(_heading_session(tmp_path, with_gnss=False))
        info: dict = {}
        xyz, _i, _o = georef.session_to_pointcloud(data, info=info)
        np.testing.assert_allclose(xyz[0], [0.0, 1.0, 0.0], atol=1e-9)
        assert info["heading_reference"] == "magnetic"
        assert info["declination_deg"] is None

    def test_relative_label_without_mag(self, tmp_path):
        data = georef.load_session(_heading_session(tmp_path, mag=None, with_gnss=False))
        info: dict = {}
        xyz, _i, _o = georef.session_to_pointcloud(data, info=info)
        np.testing.assert_allclose(xyz[0], [1.0, 0.0, 0.0], atol=1e-9)
        assert info["heading_reference"] == "relative"

    def test_gyro_yaw_drift_during_sweep_is_ignored(self, tmp_path):
        """The scan-time quaternion carries 30° of gyro yaw drift (mag off while
        stepping, DEC-013). Yaw comes from the rest heading, so the point stays put."""
        import math

        h = math.radians(30.0) / 2
        drifted = (math.cos(h), 0.0, 0.0, math.sin(h))
        data = georef.load_session(_heading_session(tmp_path, scan_q=drifted, with_gnss=False))
        xyz, _i, _o = georef.session_to_pointcloud(data)
        np.testing.assert_allclose(xyz[0], [0.0, 1.0, 0.0], atol=1e-9)

    def test_tilt_applied_per_scan(self, tmp_path):
        """Base tilted 10° about body X, relative heading: at mast 90° the
        forward point goes left, then the tilt lifts it: (0, cos10°, sin10°)."""
        import math

        h = math.radians(10.0) / 2
        tilted = (math.cos(h), math.sin(h), 0.0, 0.0)
        data = georef.load_session(
            _heading_session(tmp_path, rest_q=tilted, mag=None, with_gnss=False, mast_angles=(90.0,))
        )
        xyz, _i, _o = georef.session_to_pointcloud(data)
        t = math.radians(10.0)
        np.testing.assert_allclose(xyz[0], [0.0, math.cos(t), math.sin(t)], atol=1e-9)

    def test_platform_mount_matches_base_mount(self, tmp_path):
        """An IMU riding the mast reports R_base · Rz(mast). With mount =
        'platform' the mast rotation is removed before the tilt is taken, so
        the cloud equals the base-mount cloud of the same scene.

        The base is TILTED 10° about X on purpose: with a level base, strip_yaw
        would discard a pure mast yaw anyway, and the test would pass even if
        the mount were ignored. With a tilt, ignoring the mount makes the tilt
        axis turn with the mast (strip_yaw(Rx·Rz(m)) != Rx), so the clouds differ."""
        import math

        h = math.radians(10.0) / 2
        tilted = (math.cos(h), math.sin(h), 0.0, 0.0)
        masts = (0.0, 45.0, 90.0, 135.0)
        base = georef.session_to_pointcloud(
            georef.load_session(
                _heading_session(tmp_path, name="b", rest_q=tilted, mast_angles=masts, with_gnss=False)
            )
        )[0]
        plat = georef.session_to_pointcloud(
            georef.load_session(
                _heading_session(tmp_path, name="p", rest_q=tilted, mast_angles=masts,
                                 with_gnss=False, mount="platform", platform_q_follows_mast=True)
            )
        )[0]
        np.testing.assert_allclose(plat, base, atol=1e-9)
        # Same scene with the mount wrongly declared "base" must NOT match.
        wrong = georef.session_to_pointcloud(
            georef.load_session(
                _heading_session(tmp_path, name="w", rest_q=tilted, mast_angles=masts,
                                 with_gnss=False, mount="base", platform_q_follows_mast=True)
            )
        )[0]
        assert not np.allclose(wrong, base, atol=1e-6)

    def test_lever_arm_on_axis(self, tmp_path):
        """Antenna 0.5 m above the LiDAR: every point drops 0.5 m (relative heading)."""
        data = georef.load_session(
            _heading_session(tmp_path, mag=None, antenna_offset=[0.0, 0.0, 0.5])
        )
        xyz, _i, _o = georef.session_to_pointcloud(data)
        np.testing.assert_allclose(xyz[0], [1.0, 0.0, -0.5], atol=1e-6)

    def test_lever_arm_rotates_with_mast(self, tmp_path):
        """Antenna 0.2 m ahead and 0.5 m up at mast 0; at mast 90° the arm
        points left: forward point (0, 1, 0) minus arm (0, 0.2, 0.5)."""
        data = georef.load_session(
            _heading_session(tmp_path, mag=None, antenna_offset=[0.2, 0.0, 0.5], mast_angles=(90.0,))
        )
        xyz, _i, _o = georef.session_to_pointcloud(data)
        np.testing.assert_allclose(xyz[0], [0.0, 0.8, -0.5], atol=1e-6)

    def test_old_session_without_geometry_or_events_loads(self, tmp_path):
        """Pre-stage-5 sessions: no geometry, no sweep field, no sweep_start."""
        sess = _make_session(tmp_path)
        data = georef.load_session(sess)
        assert data.sweep_starts == {}
        xyz, _i, _o = georef.session_to_pointcloud(data)
        assert len(xyz) == 4
```

`test_platform_mount_matches_base_mount` carries its own negative control: the "wrong" session must differ from the base cloud. If that assertion fails, the tilt is not large enough to expose a missing mount correction. Fix the test before touching the implementation.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q tests/test_georef.py::TestHeadingModel tests/test_georef.py::TestYawStripWithoutMag`
Expected: FAIL. At least `test_true_north_known_answer`, `test_magnetic_label_without_gnss`, `test_gyro_yaw_drift_during_sweep_is_ignored`, `test_platform_mount_matches_base_mount`, both lever-arm tests and `test_yaw_kept_with_mag` fail. Note which pass on old code, if any. A test that passes on old code must be justified in the task report or strengthened.

- [ ] **Step 3: Implement** — `scripts/georef.py`

`SessionData` gains `sweep_starts: dict[int, float] = field(default_factory=dict)` (import `field` from `dataclasses`). In `load_session`'s scan loop, collect events:

```python
        elif t == "event" and rec.get("event") == "sweep_start":
            k = int((rec.get("details") or {}).get("sweep", 0))
            sweep_starts.setdefault(k, float(rec["timestamp"]))
```

and pass `sweep_starts=sweep_starts` to `SessionData(...)`.

New helpers (in the `# Heading reference` section):

```python
def _yaw_deg(r) -> float:
    return math.degrees(math.atan2(float(r[1, 0]), float(r[0, 0])))


def _nwu_to_enu(declination_deg: float | None):
    """Madgwick world (North-West-Up, x = magnetic north) → ENU, true north when
    the declination is known: Rz(-D) · Rz(+90°)."""
    return _rot_z(-(declination_deg or 0.0)) @ _rot_z(90.0)


def _circular_mean_deg(angles: list[float]) -> float:
    s = sum(math.sin(math.radians(a)) for a in angles)
    c = sum(math.cos(math.radians(a)) for a in angles)
    return math.degrees(math.atan2(s, c))


def _rest_samples_by_sweep(session: SessionData, imu_sorted: list[dict]) -> dict[int, list[dict]]:
    """Mag-bearing IMU samples in (end of previous sweep, rest end of this sweep]."""
    by_sweep: dict[int, list[dict]] = {}
    for rec in session.lidar_records:
        by_sweep.setdefault(int(rec.get("sweep", 0)), []).append(rec)
    out: dict[int, list[dict]] = {}
    prev_end = float("-inf")
    for k in sorted(by_sweep):
        recs = by_sweep[k]
        first = min(r["timestamp"] for r in recs)
        rest_end = session.sweep_starts.get(k, first)
        out[k] = [
            s for s in imu_sorted
            if s.get("mag") is not None and prev_end < s["timestamp"] <= rest_end
        ]
        prev_end = max(r["timestamp"] for r in recs)
    return out
```

In `session_to_pointcloud(session, info=None)`, after the origin block, replace the `strip_yaw` block and the per-record loop with:

```python
    geometry = session.metadata.get("geometry") or {}
    mount = geometry.get("imu_mount", "base")
    antenna = geometry.get("antenna_offset_m")
    arm_platform = np.asarray(antenna, dtype=float) if antenna else None

    rest = _rest_samples_by_sweep(session, imu_sorted)
    have_rest = any(rest.values())
    declination = None
    if have_rest and origin_lat is not None and session.lidar_records:
        t_first = min(r["timestamp"] for r in session.lidar_records)
        declination = magnetic_declination_deg(origin_lat, origin_lon, t_first)
    enu = _nwu_to_enu(declination)
    yaw_ref: dict[int, float] = {}
    for k, samples in rest.items():
        if samples:
            yaw_ref[k] = _circular_mean_deg(
                [_yaw_deg(enu @ _quat_to_rotmat(s["orientation"])) for s in samples]
            )
    if not have_rest:
        label = "relative"
        logger.info(
            "no magnetometer data at rest: heading is relative (mast-0 forward = +X); "
            "tilt from the IMU, yaw from the commanded mast angle"
        )
    else:
        label = "true" if declination is not None else "magnetic"
        missing = sorted(k for k in rest if k not in yaw_ref)
        if missing:
            logger.warning("sweeps %s have no rest heading; reusing the nearest sweep's", missing)
        for k in missing:
            earlier = [j for j in yaw_ref if j < k]
            yaw_ref[k] = yaw_ref[max(earlier)] if earlier else yaw_ref[min(yaw_ref)]
    logger.info("heading reference: %s (declination %s)", label, declination)
    if info is not None:
        info.update(
            heading_reference=label,
            declination_deg=declination,
            imu_mount=mount,
            antenna_offset_m=antenna,
        )

    chunks_xyz = []
    chunks_int = []
    for rec in session.lidar_records:
        mast = float(rec.get("mast_angle_deg", 0.0))
        q_t = orientation_at(rec["timestamp"], imu_sorted)
        m_imu = mast if mount == "platform" else 0.0
        tilt = _strip_yaw(_rotmat_to_quat(_quat_to_rotmat(q_t) @ _rot_z(-m_imu)))
        r_world = _rot_z(yaw_ref.get(int(rec.get("sweep", 0)), 0.0)) @ _quat_to_rotmat(tilt)
        q_world = _rotmat_to_quat(r_world)
        pts_local, intens = lidar_points_to_local(rec, q_world)
        if pts_local.size == 0:
            continue
        if origin_lat is not None:
            scan_fix = _nearest_gnss(rec["timestamp"], gnss_sorted)
            if scan_fix is not None:
                dE, dN, dU = enu_offset_m(
                    scan_fix["lat"], scan_fix["lon"], scan_fix.get("alt", 0.0),
                    origin_lat, origin_lon, origin_alt,
                )
                pts_local = pts_local + np.array([dE, dN, dU])
            if arm_platform is not None:
                pts_local = pts_local - r_world @ (_rot_z(mast) @ arm_platform)
        chunks_xyz.append(pts_local)
        chunks_int.append(intens)
```

Keep the existing `mast angle never changed` warning, the no-GNSS warning, the origin logging and the return statement exactly as they are.

Update the module docstring's coordinate-flow block to show NWU → ENU (declination) and the lever arm, and add:

```
    0.14.0  2026-09-23  Heading model (S3-R1, S3-R3): Madgwick NWU converted
                        to ENU with WMM declination; yaw from a per-sweep rest
                        heading, never from gyro yaw during the sweep; tilt per
                        scan; imu_mount "base" | "platform"; rotating antenna
                        lever arm; heading labelled true/magnetic/relative.
```

(Task 5 added nothing to the changelog; if it did, keep its line.)

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q tests/test_georef.py` then `python -m pytest -q`
Expected: PASS, including `test_round_trip_produces_points` in `tests/test_main.py`.

- [ ] **Step 5: Commit**

```bash
git add scripts/georef.py tests/test_georef.py
git commit -m "feat(georef): true-north heading from rest samples, per-scan tilt, IMU mount, antenna lever arm (S3-R1, S3-R3)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Dual ellipsoidal / NAVD88 export with a ballpark guard and `export.json`

**Files:**
- Modify: `scripts/georef.py` (`GeoidUnavailable`; `_geoid_transformer`; `navd88_from_enu`; `export_ply(..., comments=())`; `export_las(..., crs: int | str)`; `main()` output naming, exit code 3, manifest; docstring + changelog 0.15.0)
- Test: `tests/test_georef.py` (update `TestPipelinePly.test_arm_group_with_crs_override`; new `TestNavd88Export`)

**Interfaces:**
- Consumes: `session_to_pointcloud(session, info=...)` (Task 6).
- Produces:
  - `class GeoidUnavailable(RuntimeError)`.
  - `_geoid_transformer(target_epsg: int) -> tuple[transformer, str, float]` returns `(pyproj Transformer, compound CRS string, metres per CRS unit)`. It raises `GeoidUnavailable` when the GEOID18 grid cannot be had locally or over the PROJ network. It is module-level so tests can monkeypatch it.
  - `navd88_from_enu(xyz, origin, target_epsg: int) -> tuple[ndarray, str]` returns `(N×3 in the CRS unit, compound CRS string)`. It raises `GeoidUnavailable` for a ballpark result.
  - Output files for a projected export (`epsg_to_embed != 0`): `<prefix>_ellipsoidal.{ply,las}` and `<prefix>_navd88.{ply,las}`. Unprojected exports (local ENU, or a units mismatch) keep `<prefix>.{ply,las}`.
  - `export/export.json`: `{"files": [{"path", "horizontal", "vertical"}], "heading_reference", "declination_deg", "imu_mount", "antenna_offset_m", "navd88_error": str | null}`.
  - `main()` returns **3** when a NAVD88 export was due and failed; the ellipsoidal files are still written.

Known answers (pyproj 3.7.2 + `us_noaa_g2018u0.tif`, measured 2026-09-23): NAD83(2011) h = 300.000 m at (40.79, −77.86) → EPSG:6563+6360 z = **1093.5003 ftUS** (geoid height N = −33.30 m); h = 100.000 m at (40.0, −76.3) → EPSG:6565+6360 z = **439.5313 ftUS** (N = −33.97 m). Horizontal x, y are identical to the ellipsoidal path's.

- [ ] **Step 1: Write the failing tests**

Update `TestPipelinePly.test_arm_group_with_crs_override`. In the pyproj branch it must not touch the network, so stub the geoid:

```python
        else:
            monkeypatch.setattr(georef, "_geoid_transformer", _fake_geoid(-33.3))
            rc = georef.main([str(sess), "--crs", "6563", "--no-las"])
            assert rc == 0
            out = sess / "export"
            assert (out / f"{sess.name}_ellipsoidal.ply").exists()
            assert (out / f"{sess.name}_navd88.ply").exists()
```

(add `monkeypatch` to that test's parameters.)

Add at module level:

```python
def _fake_geoid(undulation_m: float, unit_m: float = 0.3048006096012192):
    """Stand-in for _geoid_transformer: real pyproj horizontal, fixed geoid undulation."""

    def _factory(target_epsg: int):
        import pyproj

        horiz = pyproj.Transformer.from_crs("EPSG:6319", f"EPSG:{target_epsg}", always_xy=True)

        class _T:
            def transform(self, lons, lats, alts):
                xs, ys = horiz.transform(lons, lats)
                return xs, ys, (np.asarray(alts) - undulation_m) / unit_m

        return _T(), f"EPSG:{target_epsg}+6360", unit_m

    return _factory


def _grid_available() -> bool:
    pyproj = pytest.importorskip("pyproj")
    import warnings

    from pyproj.transformer import TransformerGroup

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return TransformerGroup("EPSG:6319", "EPSG:6563+6360", always_xy=True).best_available


class TestNavd88Export:
    def _arm_session(self, tmp_path):
        return _make_session(tmp_path, profile="arm_group", target_crs=6563)

    def test_ballpark_transform_is_refused(self, monkeypatch):
        """Review Focus 1: PROJ's ballpark vertical returns ellipsoidal heights
        unchanged (measured 2026-09-23, even with only_best=True). Undulation 0
        must raise, never be labelled NAVD88."""
        pytest.importorskip("pyproj")
        monkeypatch.setattr(georef, "_geoid_transformer", _fake_geoid(0.0))
        xyz = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
        with pytest.raises(georef.GeoidUnavailable, match="ballpark"):
            georef.navd88_from_enu(xyz, (40.79, -77.86, 300.0), 6563)

    def test_missing_grid_writes_ellipsoidal_only_and_exits_3(self, tmp_path, monkeypatch, caplog):
        pytest.importorskip("pyproj")

        def _no_grid(_epsg):
            raise georef.GeoidUnavailable("GEOID18 grid us_noaa_g2018u0.tif unavailable")

        monkeypatch.setattr(georef, "_geoid_transformer", _no_grid)
        sess = self._arm_session(tmp_path)
        with caplog.at_level("ERROR", logger="georef"):
            rc = georef.main([str(sess), "--no-las"])
        assert rc == 3
        out = sess / "export"
        assert (out / f"{sess.name}_ellipsoidal.ply").exists()
        assert not (out / f"{sess.name}_navd88.ply").exists()
        manifest = json.loads((out / "export.json").read_text())
        assert "us_noaa_g2018u0" in manifest["navd88_error"]
        assert [f["vertical"] for f in manifest["files"]] == ["ellipsoidal NAD83(2011)"]
        assert any("NAVD88" in r.message for r in caplog.records)

    def test_manifest_and_ply_headers_name_their_datum(self, tmp_path, monkeypatch):
        pytest.importorskip("pyproj")
        monkeypatch.setattr(georef, "_geoid_transformer", _fake_geoid(-33.3))
        sess = self._arm_session(tmp_path)
        assert georef.main([str(sess), "--no-las"]) == 0
        out = sess / "export"
        manifest = json.loads((out / "export.json").read_text())
        verticals = {f["path"]: f["vertical"] for f in manifest["files"]}
        assert verticals[f"{sess.name}_ellipsoidal.ply"] == "ellipsoidal NAD83(2011)"
        assert verticals[f"{sess.name}_navd88.ply"] == "NAVD88 (GEOID18) EPSG:6360"
        assert manifest["navd88_error"] is None
        assert manifest["heading_reference"] == "relative"
        head = (out / f"{sess.name}_navd88.ply").read_bytes().split(b"end_header")[0]
        assert b"comment vertical NAVD88 (GEOID18) EPSG:6360" in head

    def test_navd88_z_is_ellipsoidal_minus_undulation(self, tmp_path, monkeypatch):
        pytest.importorskip("pyproj")
        monkeypatch.setattr(georef, "_geoid_transformer", _fake_geoid(-33.3))
        xyz = np.array([[0.0, 0.0, 0.0]])
        out, compound = georef.navd88_from_enu(xyz, (40.79, -77.86, 300.0), 6563)
        assert compound == "EPSG:6563+6360"
        assert out[0, 2] == pytest.approx((300.0 + 33.3) / 0.3048006096012192, abs=1e-6)

    def test_real_geoid18_known_answer(self):
        """pyproj + the real GEOID18 grid. Skips (with the reason) only when the
        grid is not on this machine — install it with
        `projsync --file us_noaa_g2018u0.tif` to run it."""
        if not _grid_available():
            pytest.skip("GEOID18 grid us_noaa_g2018u0.tif not installed locally")
        transformer, compound, unit_m = georef._geoid_transformer(6563)
        x, y, z = transformer.transform(-77.86, 40.79, 300.0)
        assert compound == "EPSG:6563+6360"
        assert z == pytest.approx(1093.5003, abs=0.001)
        transformer5, _c, _u = georef._geoid_transformer(6565)
        assert transformer5.transform(-76.3, 40.0, 100.0)[2] == pytest.approx(439.5313, abs=0.001)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest -q tests/test_georef.py::TestNavd88Export tests/test_georef.py::TestPipelinePly`
Expected: FAIL — `GeoidUnavailable`, `_geoid_transformer`, `navd88_from_enu` missing; single-output naming.

- [ ] **Step 3: Implement** — `scripts/georef.py`

```python
class GeoidUnavailable(RuntimeError):
    """NAVD88 heights cannot be produced honestly (grid missing, or PROJ fell
    back to a ballpark vertical transform)."""


_GEOID_GRID = "us_noaa_g2018u0.tif"
_NAVD88_VERTICAL = {True: 6360, False: 5703}  # ftUS CRS → 6360, metric → 5703


def _geoid_transformer(target_epsg: int):
    """GEOID18 transformer NAD83(2011) 3D (EPSG:6319) → EPSG:<H>+<NAVD88>.

    PROJ does not raise when the geoid grid is missing: it silently returns a
    'ballpark' transform that leaves ellipsoidal heights unchanged (measured
    2026-09-23, pyproj 3.7.2, even with only_best=True). So availability is
    checked explicitly, and the PROJ network (cdn.proj.org) is tried once.
    """
    import warnings

    pyproj = _optional_import("pyproj")
    if pyproj is None:
        raise GeoidUnavailable('pyproj not installed — install via `pip install -e ".[post]"`')
    from pyproj.transformer import TransformerGroup

    crs = pyproj.CRS.from_epsg(target_epsg)
    unit_m = float(crs.axis_info[0].unit_conversion_factor)
    is_ft = abs(unit_m - US_SURVEY_FOOT_M) < 1e-9 or abs(unit_m - 0.3048) < 1e-9
    compound = f"EPSG:{target_epsg}+{_NAVD88_VERTICAL[is_ft]}"

    def _group():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return TransformerGroup("EPSG:6319", compound, always_xy=True)

    group = _group()
    if not group.best_available and not pyproj.network.is_network_enabled():
        logger.info("GEOID18 grid not found locally; fetching %s from cdn.proj.org", _GEOID_GRID)
        pyproj.network.set_network_enabled(True)
        group = _group()
    if not group.best_available or not group.transformers:
        raise GeoidUnavailable(
            f"GEOID18 grid {_GEOID_GRID} unavailable — run `projsync --file {_GEOID_GRID}` "
            "or allow network access, then re-export"
        )
    return group.transformers[0], compound, unit_m


def navd88_from_enu(xyz, origin_lat_lon_alt, target_epsg: int):
    """Local ENU metres → (x, y, NAVD88 height) in target_epsg's unit, via GEOID18."""
    np = _require_numpy()
    transformer, compound, unit_m = _geoid_transformer(target_epsg)
    lat0, lon0, alt0 = origin_lat_lon_alt
    lats, lons, alts = geodetic_from_enu(xyz[:, 0], xyz[:, 1], xyz[:, 2], lat0, lon0, alt0)
    xs, ys, zs = transformer.transform(lons, lats, alts)
    zs = np.asarray(zs, dtype=float)
    undulation = np.asarray(alts, dtype=float) - zs * unit_m
    # CONUS geoid heights run about -8 m to -53 m; |N| < 1 m everywhere means
    # PROJ handed back ellipsoidal heights through a ballpark transform.
    if not np.all(np.isfinite(zs)) or float(np.max(np.abs(undulation))) < 1.0:
        raise GeoidUnavailable(
            "transform returned ellipsoidal heights (ballpark) — refusing to label them NAVD88"
        )
    return np.column_stack([np.asarray(xs), np.asarray(ys), zs]), compound
```

`export_ply(out_path, xyz, intensity, comments: tuple[str, ...] | list[str] = ())` — insert `f"comment {c}\n"` lines right after the `format` line.

`export_las(out_path, xyz, intensity, target_epsg: int | str)` — for an `int > 0` keep `add_crs(f"EPSG:{target_epsg}")`; for a `str` (a compound like `"EPSG:6563+6360"`) call `header.add_crs(pyproj.CRS(target_epsg))`, inside the same broad `try`/warning. Also log the CRS as given, not with `%d`.

`main()` — after `session_to_pointcloud(session, info=info)` and `project_to_crs`:

```python
    prefix = args.out_prefix or session_dir.name
    out_dir = session_dir / "export"
    files: list[dict] = []
    navd88_error: str | None = None
    exit_code = 0
    if epsg_to_embed != 0:
        name = f"{prefix}_ellipsoidal"
        vertical = "ellipsoidal NAD83(2011)"
        export_ply(out_dir / f"{name}.ply", xyz, intensity, comments=(f"vertical {vertical}", f"horizontal EPSG:{epsg_to_embed}"))
        if not args.no_las:
            export_las(out_dir / f"{name}.las", xyz, intensity, epsg_to_embed)
        files.append({"path": f"{name}.ply", "horizontal": f"EPSG:{epsg_to_embed}", "vertical": vertical})
        try:
            xyz_n, compound = navd88_from_enu(xyz_enu, origin, epsg_to_embed)
        except GeoidUnavailable as e:
            navd88_error = str(e)
            logger.error("NAVD88 export skipped: %s", e)
            exit_code = 3
        else:
            name = f"{prefix}_navd88"
            vertical = f"NAVD88 (GEOID18) EPSG:{compound.split('+')[1]}"
            export_ply(out_dir / f"{name}.ply", xyz_n, intensity, comments=(f"vertical {vertical}", f"horizontal EPSG:{epsg_to_embed}"))
            if not args.no_las:
                export_las(out_dir / f"{name}.las", xyz_n, intensity, compound)
            files.append({"path": f"{name}.ply", "horizontal": f"EPSG:{epsg_to_embed}", "vertical": vertical})
    else:
        vertical = "local ENU (ellipsoidal offsets)" if origin[0] is not None else "LiDAR-relative"
        export_ply(out_dir / f"{prefix}.ply", xyz, intensity, comments=(f"vertical {vertical}",))
        if not args.no_las:
            export_las(out_dir / f"{prefix}.las", xyz, intensity, 0)
        files.append({"path": f"{prefix}.ply", "horizontal": "none", "vertical": vertical})
    atomic_manifest = {
        "files": files,
        "navd88_error": navd88_error,
        **info,
    }
    (out_dir / "export.json").write_text(json.dumps(atomic_manifest, indent=2))
    logger.info("Export complete: %s", out_dir)
    return exit_code
```

`xyz_enu` is the local-ENU cloud returned by `session_to_pointcloud`. Keep a reference to it before `project_to_crs` reassigns `xyz`: rename the returned value `xyz_enu`, then call `xyz, epsg_to_embed = project_to_crs(xyz_enu, ...)`. Keep the `if target_epsg != 0 or units == "ft"` guard and fall through with `xyz = xyz_enu` otherwise. Write `export.json` after `out_dir.mkdir(parents=True, exist_ok=True)`, since `export_ply` already creates it. The manifest is only listed for `.ply` paths; LAS files sit beside them with the same stem.

Docstring: replace "Heights are ellipsoidal (WGS84) throughout; no geoid model is applied." with the dual-output description, the ballpark guard, exit code 3, and the `projsync` hint. Add to Failure modes: "GEOID18 grid unavailable → ellipsoidal files written, NAVD88 skipped, exit 3". Changelog:

```
    0.15.0  2026-09-23  Dual export for projected CRSs: <prefix>_ellipsoidal
                        and <prefix>_navd88 (GEOID18, EPSG:<H>+6360/5703, source
                        NAD83(2011) 3D EPSG:6319); refuses PROJ's silent ballpark
                        vertical (|N| < 1 m) and exits 3 with the ellipsoidal
                        files written; export.json manifest names every file's
                        horizontal and vertical datum and the heading reference.
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q tests/test_georef.py` then `python -m pytest -q`
Expected: PASS. `test_real_geoid18_known_answer` runs where the grid is cached; on 2026-09-23 it was fetched to this PC's PROJ user directory. If it skips, the report must say so.

- [ ] **Step 5: Lint, format, LF probe**

Run: `python -m ruff format src scripts tests` then `python -m ruff check src scripts tests`, then the LF probe on `config/default.toml`.
Expected: clean; `crlf 0`.

- [ ] **Step 6: Commit**

```bash
git add scripts/georef.py tests/test_georef.py
git commit -m "feat(georef): ellipsoidal + NAVD88 (GEOID18) export with a ballpark guard and export.json" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Merge gate and bookkeeping (controller, after the whole-branch review)

1. Gate on the branch tip: `python -m pytest -q` (record the count; must be ≥ 422 + this stage's additions, with no unexplained skips), `ruff check` and `ruff format --check` clean, `bash -n deploy/install.sh`, LF probe on every touched `config/`/`deploy/` file.
2. `git merge --no-ff fix/stage5-scan-geometry` into local `main` with a message listing the seven tasks, the closed items and the measured suite count. Do not push.
3. `docs/CROSS_REPO_BACKLOG.md`:
   - Close **S3-R1** (heading model) and **S3-R3** (mount configurable; physical choice remains a bench item — say so in the close note) with the merge SHA.
   - Mark **CR-002** `❌ Not needed — DEC-031 amended 2026-09-23, LoRa is status-only`.
   - Update **CR-001/CR-003** text: LoRa carries STATUS/LINK only.
   - File a firmware row in "Rover-side deferred": *`firmware/esp32-rover`: retire the `lora_rtcm_relay` env and the RTCM_CHUNK receive handler; make `ntrip_client` the only RTCM mode — needs a PlatformIO build + flash.*
4. Stage 6 (docs) plan inherits: DEC-015 and DEC-031 amendments written into `docs/DECISIONS.md`; HARDWARE.md mounting table (IMU mount is a config choice; antenna = SparkFun GPS-RTK-SMA + ANN-MB-00, placement TBD); SPECIFICATIONS.md record format (`sweep`, `sweep_start`, `geometry`, `export.json`); the S4-R1 upgrade note; the EPSG 6346 doc fixes carried from stage 3.
