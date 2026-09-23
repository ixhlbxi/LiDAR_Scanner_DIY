# Stage 3 — Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A session's LiDAR slices, mast angles and IMU samples are captured completely and exported as a real 3D volume in the target CRS's units, at double precision.

**Architecture:** The LD19 driver returns whole, seam-complete revolutions with sensor timestamps. The IMU driver samples on its own thread at the configured rate with monotonic `dt`, optionally fusing the magnetometer (MARG) with a hard-iron offset, and hands the main loop batches. The main loop logs columnar records carrying the commanded mast angle. `scripts/georef.py` loads rotated files, applies mount rotation → mast rotation → IMU quaternion → GNSS offset → CRS, scales Z to the CRS unit, and writes double-precision PLY.

**Tech Stack:** Python 3.11 stdlib (`struct`, `threading`, `bisect`, `glob`), numpy, pyproj, laspy (post extras), pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-audit-remediation-design.md` §5

## Global Constraints

- Frames (CLAUDE.md §8): LiDAR/IMU/Body are Forward/Left/Up; quaternions scalar-first `[w, x, y, z]`, right-handed. Mount geometry per spec §5: the LD19 scan plane is the body X-Z plane (LiDAR x → body x, LiDAR y → body z); the stepper rotates that plane about body Z; the IMU is assumed rigid to the fixed body.
- Sensors never crash the system; a failing IMU thread marks the driver unavailable and stops, it does not raise into the main loop.
- Record format break is deliberate: no shim for the old per-point LiDAR dict format; fixtures are regenerated.
- `use_magnetometer` defaults to `false` in `config/default.toml` until a hard-iron calibration exists.
- Style `X | None`; ruff clean (`python -m ruff format` then `python -m ruff check` on touched files); commit trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; do not push.
- Suite baseline is measured at the stage 2 merge (307 expected); it must not go down.
- Findings closed: T1-007, T1-008, T1-009, T1-010, T1-012, T1-013, T1-014, T1-015, T1-016, T1-017, T1-039, T1-043, T1-044, T1-050, T1-052, and the `[calibration].mag_offset` half of T1-041.

## Review Focus

1. **A LiDAR scan straddling a mast step**: bytes buffered while the mast moved must never land in the next slice. Pinned by Task 2 (`test_read_scan_discards_buffered_packets_after_step`).
2. **An IMU I2C fault mid-session** must stop the sampling thread cleanly and mark the driver unavailable, not spin or raise. Pinned by Task 4 (`test_sample_thread_stops_on_repeated_bus_errors`).
3. **A session whose scan log rotated three times** must export every segment in order. Pinned by Task 7 (`test_load_session_reads_rotated_files_in_order`).
4. **An `arm_group` export to a ftUS CRS** must give X, Y and Z in the same unit. Pinned by Task 9 (`test_project_to_crs_scales_z_to_crs_unit`).
5. **`mag_offset` absent** (the default) must leave the MARG path identical to 6-DOF when `use_magnetometer` is false, and must not crash when true. Pinned by Task 3 (`test_update_without_mag_matches_6dof`) and Task 5.

---

### Task 1: LiDAR packet parsing — precompiled struct, one-byte resync, VerLen check

**Files:**
- Modify: `src/rover/lidar.py` (`parse_packet`, `read_packet`)
- Test: `tests/test_lidar.py`

**Interfaces:**
- Produces: `_PACKET_STRUCT = struct.Struct("<xxHH" + "HB" * 12 + "HH")` (46 bytes before the CRC); `parse_packet(packet: bytes) -> dict | None` unchanged signature, now also returns `None` when `packet[1] != 0x2C`; `read_packet()` advances one byte on a CRC failure.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_lidar.py`)

```python
class TestPacketResync:
    def test_parse_rejects_wrong_verlen(self):
        pkt = bytearray(build_packet())
        pkt[1] = 0x00
        pkt[46] = crc8(bytes(pkt[:46]))  # keep CRC valid so only VerLen fails
        assert parse_packet(bytes(pkt)) is None

    def test_false_header_byte_does_not_drop_next_packet(self, lidar_config, mock_serial):
        """A stray 0x54 data byte 1 byte before a real packet used to cost the
        whole real packet (47-byte skip). Resync must advance one byte (T1-014)."""
        real = build_packet(start_angle_deg=10.0, end_angle_deg=15.5)
        stream = b"\x54" + real  # false header immediately followed by a real packet
        mock_serial.in_waiting = len(stream)
        mock_serial.read.return_value = stream
        scanner = LidarScanner(lidar_config)
        scanner.start()
        result = scanner.read_packet()
        assert result is not None
        assert result["start_angle"] == pytest.approx(10.0)

    def test_parse_packet_values_via_struct(self):
        pkt = build_packet(
            start_angle_deg=1.0, end_angle_deg=2.0, speed_dps=359.9, timestamp_ms=4321,
            distances_mm=list(range(100, 100 + POINTS_PER_PACKET)),
            intensities=list(range(POINTS_PER_PACKET)),
        )
        r = parse_packet(pkt)
        assert r["speed_dps"] == pytest.approx(359.9)
        assert r["timestamp_ms"] == 4321
        assert r["points_raw"][5] == (105, 5)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_lidar.py -q -k "Resync"
```

Expected: `test_parse_rejects_wrong_verlen` FAIL (returns a dict), `test_false_header_byte_does_not_drop_next_packet` FAIL (returns None), the struct test passes already (fine).

- [ ] **Step 3: Implement**

At module level after the constants:

```python
PACKET_VERLEN = 0x2C  # byte 1: (packet type 2 << 5) | 12 points
# Header(1) VerLen(1) speed(H) start(H) 12×(dist H, intensity B) end(H) timestamp(H) — 46 bytes, CRC is byte 46
_PACKET_STRUCT = struct.Struct("<xxHH" + "HB" * POINTS_PER_PACKET + "HH")
assert _PACKET_STRUCT.size == PACKET_LENGTH - 1
```

Replace the body of `parse_packet` after the length/header check with:

```python
    if packet[1] != PACKET_VERLEN:
        return None
    if crc8(packet[:46]) != packet[46]:
        return None

    fields = _PACKET_STRUCT.unpack_from(packet, 0)
    speed_raw, start_raw = fields[0], fields[1]
    end_raw, timestamp_ms = fields[-2], fields[-1]
    body = fields[2:-2]
    points_raw = [(body[i], body[i + 1]) for i in range(0, len(body), 2)]

    return {
        "speed_dps": speed_raw / 100.0,
        "start_angle": start_raw / 100.0,
        "end_angle": end_raw / 100.0,
        "timestamp_ms": timestamp_ms,
        "points_raw": points_raw,
    }
```

Replace the extraction loop in `read_packet` with:

```python
        while len(self._buf) >= PACKET_LENGTH:
            idx = self._buf.find(PACKET_HEADER)
            if idx < 0:
                self._buf.clear()
                return None
            if idx > 0:
                del self._buf[:idx]
            if len(self._buf) < PACKET_LENGTH:
                return None

            raw = bytes(self._buf[:PACKET_LENGTH])
            result = parse_packet(raw)
            if result is not None:
                del self._buf[:PACKET_LENGTH]
                return result
            # Not a packet at this offset (VerLen or CRC): drop ONE byte and re-search,
            # so a 0x54 data byte cannot swallow the real packet behind it.
            del self._buf[:1]

        return None
```

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_lidar.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/lidar.py tests/test_lidar.py && python -m ruff check src/rover/lidar.py tests/test_lidar.py
git add src/rover/lidar.py tests/test_lidar.py
git commit -m "fix(lidar): one-byte CRC resync, VerLen check, precompiled struct, del-trimming (T1-014, T1-044)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: LiDAR `read_scan` — stale-discard, seam carry-over, sensor timestamps

**Files:**
- Modify: `src/rover/lidar.py` (`LidarPoint` unchanged; new `LidarScan` dataclass; `read_scan`)
- Test: `tests/test_lidar.py`

**Interfaces:**
- Produces: `@dataclass class LidarScan: points: list[LidarPoint]; lidar_ms_start: int; lidar_ms_end: int`. `LidarScanner.read_scan(discard_stale: bool = True) -> LidarScan`. When `discard_stale` is true the driver resets the serial input buffer, clears its parse buffer, drops packets until the first angle wrap, then collects one revolution. The packet that closes the revolution is kept as `self._carry` and seeds the next call when `discard_stale` is false. `len(scan.points)` replaces the old list length everywhere; Task 6 updates `main.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_lidar.py`)

```python
def _revolution_packets(rev_index: int = 0, start_ms: int = 1000) -> list[bytes]:
    """30 packets covering 0..360 in 12° packets; timestamps advance 3 ms each."""
    pkts = []
    for i in range(30):
        s = i * 12.0
        e = s + 11.0
        pkts.append(build_packet(start_angle_deg=s, end_angle_deg=e, timestamp_ms=start_ms + 3 * i))
    return pkts


class TestReadScanRevolutions:
    def _scanner(self, lidar_config, mock_serial, stream: bytes):
        mock_serial.in_waiting = len(stream)
        # first read returns everything, later reads return nothing
        mock_serial.read.side_effect = [stream] + [b""] * 10_000
        s = LidarScanner(lidar_config)
        s.start()
        return s

    def test_read_scan_returns_one_full_revolution_with_timestamps(self, lidar_config, mock_serial):
        stream = b"".join(_revolution_packets(0, 1000) + _revolution_packets(1, 2000) + _revolution_packets(2, 3000))
        s = self._scanner(lidar_config, mock_serial, stream)
        scan = s.read_scan(discard_stale=False)
        assert len(scan.points) == 30 * POINTS_PER_PACKET
        assert scan.lidar_ms_start == 1000
        assert scan.lidar_ms_end == 1000 + 3 * 29

    def test_seam_packet_is_carried_into_next_scan(self, lidar_config, mock_serial):
        """The packet that reveals the wrap (first packet of revolution 2) used to be
        thrown away; it must open the next scan instead (T1-013)."""
        stream = b"".join(_revolution_packets(0, 1000) + _revolution_packets(1, 2000) + _revolution_packets(2, 3000))
        s = self._scanner(lidar_config, mock_serial, stream)
        first = s.read_scan(discard_stale=False)
        second = s.read_scan(discard_stale=False)
        assert len(second.points) == 30 * POINTS_PER_PACKET
        assert second.lidar_ms_start == 2000  # revolution 2's very first packet, not its second
        assert first.lidar_ms_end < second.lidar_ms_start

    def test_read_scan_discards_buffered_packets_after_step(self, lidar_config, mock_serial):
        """With discard_stale=True the driver flushes the serial input and skips to the
        first wrap, so bytes buffered while the mast moved never land in the slice (T1-012)."""
        stale = _revolution_packets(0, 100)[10:25]  # a partial revolution from 120°..300°
        fresh = _revolution_packets(1, 5000) + _revolution_packets(2, 6000)
        stream = b"".join(stale + fresh)
        s = self._scanner(lidar_config, mock_serial, stream)
        scan = s.read_scan(discard_stale=True)
        mock_serial.reset_input_buffer.assert_called_once()
        assert scan.lidar_ms_start == 5000
        assert len(scan.points) == 30 * POINTS_PER_PACKET

    def test_read_scan_times_out_without_wrap(self, lidar_config, mock_serial, monkeypatch):
        stream = b"".join(_revolution_packets(0, 1000)[:5])
        s = self._scanner(lidar_config, mock_serial, stream)
        monkeypatch.setattr("rover.lidar._SCAN_TIMEOUT_SEC", 0.2)
        with pytest.raises(TimeoutError):
            s.read_scan(discard_stale=False)
```

Note for the implementer: the existing `mock_serial` fixture in this file patches `serial.Serial`; the tests above set `in_waiting` and `read.side_effect` on it. If the fixture's mock lacks `reset_input_buffer`, `MagicMock` provides it automatically.

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_lidar.py -q -k "ReadScanRevolutions"
```

Expected: all four FAIL (`read_scan()` takes no argument / returns a list).

- [ ] **Step 3: Implement**

Add after `LidarPoint`:

```python
@dataclass
class LidarScan:
    """One full LD19 revolution."""

    points: list[LidarPoint]
    lidar_ms_start: int  # LD19 timestamp of the first packet (ms, wraps at 30000)
    lidar_ms_end: int  # LD19 timestamp of the last packet


_SCAN_TIMEOUT_SEC = 5.0
_WRAP_THRESHOLD_DEG = 10.0
```

In `__init__` add `self._carry: dict | None = None`; in `start()` and `stop()` set `self._carry = None` next to `self._buf.clear()`.

Replace `read_scan` with:

```python
    def _packet_points(self, pkt: dict) -> list[LidarPoint]:
        angles = interpolate_angles(pkt["start_angle"], pkt["end_angle"], POINTS_PER_PACKET)
        return [
            LidarPoint(angle=a, distance=d_mm / 1000.0, intensity=inten)
            for a, (d_mm, inten) in zip(angles, pkt["points_raw"], strict=True)
            if d_mm > 0  # 0 = invalid / no return
        ]

    def _next_packet(self, deadline: float) -> dict:
        while time.monotonic() < deadline:
            pkt = self.read_packet()
            if pkt is not None:
                return pkt
            time.sleep(0.001)
        raise TimeoutError("No complete LiDAR scan received within timeout")

    def read_scan(self, discard_stale: bool = True) -> LidarScan:
        """Read one complete 360° revolution.

        Args:
            discard_stale: When true (the normal case after a mast step) flush the
                serial input and the parse buffer, then skip packets until the first
                angle wrap, so bytes buffered while the mast moved never enter the
                slice. When false, continue from the packet carried over from the
                previous call (the one that revealed its wrap).

        Raises:
            RuntimeError: If the scanner is not available.
            TimeoutError: If no full revolution arrives within the timeout.
        """
        if not self._available or self._serial is None:
            raise RuntimeError("LiDAR not available")

        deadline = time.monotonic() + _SCAN_TIMEOUT_SEC

        if discard_stale:
            try:
                self._serial.reset_input_buffer()
            except Exception as e:  # pragma: no cover — driver quirk, not fatal
                logger.debug("reset_input_buffer failed: %s", e)
            self._buf.clear()
            self._carry = None
            # Skip forward to the first wrap so we start at 0°.
            prev = None
            while True:
                pkt = self._next_packet(deadline)
                if prev is not None and pkt["start_angle"] < prev - _WRAP_THRESHOLD_DEG:
                    break
                prev = pkt["start_angle"]
            first = pkt
        elif self._carry is not None:
            first = self._carry
            self._carry = None
        else:
            first = self._next_packet(deadline)

        points = self._packet_points(first)
        ms_start = first["timestamp_ms"]
        ms_end = ms_start
        prev = first["start_angle"]

        while True:
            pkt = self._next_packet(deadline)
            if pkt["start_angle"] < prev - _WRAP_THRESHOLD_DEG:
                self._carry = pkt  # opens the next revolution
                return LidarScan(points=points, lidar_ms_start=ms_start, lidar_ms_end=ms_end)
            prev = pkt["start_angle"]
            points.extend(self._packet_points(pkt))
            ms_end = pkt["timestamp_ms"]
```

Update the module docstring changelog: `0.11.0  2026-09  Seam carry-over, stale discard, LidarScan with LD19 timestamps, one-byte resync`.

- [ ] **Step 4: Fix the pre-existing read_scan test(s)**

`tests/test_lidar.py` has an earlier test that builds a wrap packet and asserts a list is returned (around the `wrap_pkt = build_packet(start_angle_deg=0.0, ...)` line). Update it to call `read_scan(discard_stale=False)` and assert on `.points`. Then:

```bash
python -m pytest tests/test_lidar.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/lidar.py tests/test_lidar.py && python -m ruff check src/rover/lidar.py tests/test_lidar.py
git add src/rover/lidar.py tests/test_lidar.py
git commit -m "fix(lidar): read_scan discards stale input after a step, carries the seam packet, returns LidarScan with LD19 timestamps (T1-012, T1-013)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Note: `main.py` still calls `read_scan()` and treats the result as a list; `if lidar_points:` on a `LidarScan` dataclass is always true and `for p in lidar_points` fails. Task 6 fixes `main.py`; until then `tests/test_main.py`'s enabled-lidar test uses a stub `_FlakyLidar` that raises, so the suite stays green. Run the full suite anyway before committing and report the count.

---

### Task 3: Madgwick MARG update with hard-iron offset

**Files:**
- Modify: `src/rover/imu.py` (`MadgwickFilter`)
- Test: `tests/test_imu.py`

**Interfaces:**
- Produces: `MadgwickFilter(beta=0.1, mag_offset: tuple[float, float, float] | None = None)`; `update(gx, gy, gz, ax, ay, az, dt, mx=None, my=None, mz=None)`. With any of `mx/my/mz` None → 6-DOF (existing behaviour). With all three → Madgwick MARG (9-DOF) step after subtracting `mag_offset`. The duplicate derivative block is collapsed.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_imu.py` inside `TestMadgwickFilter` or a new class)

```python
class TestMadgwickMarg:
    def test_update_without_mag_matches_6dof(self):
        a = MadgwickFilter(beta=0.1)
        b = MadgwickFilter(beta=0.1)
        for _ in range(50):
            a.update(0.01, -0.02, 0.03, 0.1, 0.2, 9.7, 0.01)
            b.update(0.01, -0.02, 0.03, 0.1, 0.2, 9.7, 0.01, None, None, None)
        assert a.quaternion == pytest.approx(b.quaternion)

    def test_marg_converges_to_heading(self):
        """Level, with the magnetic field pointing +X (north = body forward) the
        yaw must settle near 0; with the field along +Y it must settle near +90°."""
        import math

        def yaw_deg(q):
            w, x, y, z = q
            return math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))

        f = MadgwickFilter(beta=0.3)
        for _ in range(2000):
            f.update(0, 0, 0, 0, 0, 9.81, 0.005, 30.0, 0.0, -40.0)
        assert abs(yaw_deg(f.quaternion)) < 3.0

        g = MadgwickFilter(beta=0.3)
        for _ in range(2000):
            g.update(0, 0, 0, 0, 0, 9.81, 0.005, 0.0, 30.0, -40.0)
        assert abs(yaw_deg(g.quaternion) - (-90.0)) < 3.0 or abs(yaw_deg(g.quaternion) - 90.0) < 3.0

    def test_mag_offset_is_subtracted(self):
        """A hard-iron offset equal to the field itself leaves no field: the MARG
        step must fall back to 6-DOF rather than divide by zero."""
        f = MadgwickFilter(beta=0.1, mag_offset=(30.0, 0.0, -40.0))
        for _ in range(100):
            f.update(0, 0, 0, 0, 0, 9.81, 0.01, 30.0, 0.0, -40.0)
        w, x, y, z = f.quaternion
        assert abs(w) > 0.99  # still ~identity: level and no yaw information

    def test_free_fall_branch_uses_consistent_derivative(self):
        """Gyro-only integration for one step must equal the closed-form small-angle
        rotation, which the old sequential in-place update did not (T1-018 hygiene)."""
        f = MadgwickFilter(beta=0.1)
        f.update(0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.1)  # 0.1 rad about Z, no accel
        w, x, y, z = f.quaternion
        assert w == pytest.approx(math.cos(0.05), abs=1e-3)
        assert z == pytest.approx(math.sin(0.05), abs=1e-3)
```

(`math` is already imported at the top of `tests/test_imu.py`.)

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_imu.py -q -k "Marg"
```

Expected: `test_update_without_mag_matches_6dof` and `test_marg_converges_to_heading` FAIL with `TypeError` (unexpected arguments); `test_mag_offset_is_subtracted` FAIL (`mag_offset` kwarg).

- [ ] **Step 3: Implement**

Replace the `MadgwickFilter` class with:

```python
class MadgwickFilter:
    """Madgwick AHRS filter for quaternion orientation estimation.

    6-DOF (accel + gyro) when no magnetometer sample is supplied; MARG (9-DOF)
    when ``mx, my, mz`` are all given. A hard-iron ``mag_offset`` (µT, body
    frame) is subtracted from every magnetometer sample before use; it comes
    from ``[calibration].mag_offset`` and defaults to none.

    Reference: S. Madgwick, "An efficient orientation filter for inertial and
    inertial/magnetic sensor arrays", 2010 — the standard MARG update, with the
    gyro-derivative term written once and shared by both branches.

    Args:
        beta: Filter gain (0..1). Higher = more accel/mag trust.
        mag_offset: Hard-iron offset (x, y, z) in µT, or None.
    """

    def __init__(
        self, beta: float = 0.1, mag_offset: tuple[float, float, float] | None = None
    ) -> None:
        self._beta = beta
        self._mag_offset = mag_offset
        self._q = [1.0, 0.0, 0.0, 0.0]  # [w, x, y, z]

    @property
    def quaternion(self) -> tuple[float, float, float, float]:
        return (self._q[0], self._q[1], self._q[2], self._q[3])

    def update(
        self,
        gx: float,
        gy: float,
        gz: float,
        ax: float,
        ay: float,
        az: float,
        dt: float,
        mx: float | None = None,
        my: float | None = None,
        mz: float | None = None,
    ) -> None:
        """Advance the orientation by one sample.

        gyro in rad/s, accel in m/s² (any scale; normalised), mag in µT (any
        scale; normalised). With any of mx/my/mz None the 6-DOF step runs.
        """
        q0, q1, q2, q3 = self._q

        # Rate of change of quaternion from gyroscope — shared by every branch.
        qd0 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz)
        qd1 = 0.5 * (q0 * gx + q2 * gz - q3 * gy)
        qd2 = 0.5 * (q0 * gy - q1 * gz + q3 * gx)
        qd3 = 0.5 * (q0 * gz + q1 * gy - q2 * gx)

        s0 = s1 = s2 = s3 = 0.0
        a_norm = math.sqrt(ax * ax + ay * ay + az * az)
        if a_norm > 1e-10:
            ax, ay, az = ax / a_norm, ay / a_norm, az / a_norm
            use_mag = mx is not None and my is not None and mz is not None
            if use_mag:
                if self._mag_offset is not None:
                    mx -= self._mag_offset[0]
                    my -= self._mag_offset[1]
                    mz -= self._mag_offset[2]
                m_norm = math.sqrt(mx * mx + my * my + mz * mz)
                use_mag = m_norm > 1e-10
            if use_mag:
                mx, my, mz = mx / m_norm, my / m_norm, mz / m_norm
                # Reference direction of Earth's magnetic field in the earth frame
                hx = mx * q0 * q0 - 2 * q0 * my * q3 + 2 * q0 * mz * q2 + mx * q1 * q1 + 2 * q1 * my * q2 + 2 * q1 * mz * q3 - mx * q2 * q2 - mx * q3 * q3
                hy = 2 * q0 * mx * q3 + my * q0 * q0 - 2 * q0 * mz * q1 + 2 * q1 * mx * q2 - my * q1 * q1 + my * q2 * q2 + 2 * q2 * mz * q3 - my * q3 * q3
                bx = math.sqrt(hx * hx + hy * hy)
                bz = -2 * q0 * mx * q2 + 2 * q0 * my * q1 + mz * q0 * q0 + 2 * q1 * mx * q3 - mz * q1 * q1 + 2 * q2 * my * q3 - mz * q2 * q2 + mz * q3 * q3
                # Gradient descent corrective step (MARG)
                f1 = 2 * (q1 * q3 - q0 * q2) - ax
                f2 = 2 * (q0 * q1 + q2 * q3) - ay
                f3 = 2 * (0.5 - q1 * q1 - q2 * q2) - az
                f4 = 2 * bx * (0.5 - q2 * q2 - q3 * q3) + 2 * bz * (q1 * q3 - q0 * q2) - mx
                f5 = 2 * bx * (q1 * q2 - q0 * q3) + 2 * bz * (q0 * q1 + q2 * q3) - my
                f6 = 2 * bx * (q0 * q2 + q1 * q3) + 2 * bz * (0.5 - q1 * q1 - q2 * q2) - mz
                s0 = (-2 * q2 * f1 + 2 * q1 * f2 - 2 * bz * q2 * f4
                      + (-2 * bx * q3 + 2 * bz * q1) * f5 + 2 * bx * q2 * f6)
                s1 = (2 * q3 * f1 + 2 * q0 * f2 - 4 * q1 * f3 + 2 * bz * q3 * f4
                      + (2 * bx * q2 + 2 * bz * q0) * f5 + (2 * bx * q3 - 4 * bz * q1) * f6)
                s2 = (-2 * q0 * f1 + 2 * q3 * f2 - 4 * q2 * f3 + (-4 * bx * q2 - 2 * bz * q0) * f4
                      + (2 * bx * q1 + 2 * bz * q3) * f5 + (2 * bx * q0 - 4 * bz * q2) * f6)
                s3 = (2 * q1 * f1 + 2 * q2 * f2 + (-4 * bx * q3 + 2 * bz * q1) * f4
                      + (-2 * bx * q0 + 2 * bz * q2) * f5 + 2 * bx * q1 * f6)
            else:
                # Gradient descent corrective step (accel only)
                f1 = 2 * (q1 * q3 - q0 * q2) - ax
                f2 = 2 * (q0 * q1 + q2 * q3) - ay
                f3 = 2 * (0.5 - q1 * q1 - q2 * q2) - az
                s0 = -2 * q2 * f1 + 2 * q1 * f2
                s1 = 2 * q3 * f1 + 2 * q0 * f2 - 4 * q1 * f3
                s2 = -2 * q0 * f1 + 2 * q3 * f2 - 4 * q2 * f3
                s3 = 2 * q1 * f1 + 2 * q2 * f2
            s_norm = math.sqrt(s0 * s0 + s1 * s1 + s2 * s2 + s3 * s3)
            if s_norm > 1e-10:
                s0, s1, s2, s3 = s0 / s_norm, s1 / s_norm, s2 / s_norm, s3 / s_norm
            else:
                s0 = s1 = s2 = s3 = 0.0
        # else: free-fall / invalid accel — gyro integration only (s = 0)

        q0 += (qd0 - self._beta * s0) * dt
        q1 += (qd1 - self._beta * s1) * dt
        q2 += (qd2 - self._beta * s2) * dt
        q3 += (qd3 - self._beta * s3) * dt
        self._q = [q0, q1, q2, q3]
        self._normalize()

    def _normalize(self) -> None:
        norm = math.sqrt(sum(x * x for x in self._q))
        if norm > 1e-10:
            self._q = [x / norm for x in self._q]
```

Ruff will wrap the long `hx`/`hy`/`bz` lines; let it. The `test_marg_converges_to_heading` sign for the +Y field depends on handedness conventions in the reference; the test accepts either ±90°, and the +X case must be near 0 — if it is not, the implementation is wrong, not the test.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_imu.py -q
```

Expected: all pass, including the pre-existing `TestMadgwickFilter` tests.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/imu.py tests/test_imu.py && python -m ruff check src/rover/imu.py tests/test_imu.py
git add src/rover/imu.py tests/test_imu.py
git commit -m "feat(imu): Madgwick MARG update with hard-iron offset; single gyro-derivative block (T1-016, T1-018)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: IMU sampling thread with monotonic dt and batch drain

**Files:**
- Modify: `src/rover/imu.py` (`ImuDriver`)
- Test: `tests/test_imu.py`

**Interfaces:**
- Produces: `ImuDriver.start()` launches a daemon thread sampling at `sample_rate_hz`; `ImuDriver.drain() -> list[ImuSample]` returns every sample since the last drain (thread-safe); `ImuDriver.latest() -> ImuSample | None`; `ImuDriver.read_sample()` remains for direct single reads (hardware diagnostics) and shares the bus lock; `enable_magnetometer(bool)` is read by the thread each sample; `get_sample_at()` and the 2 s ring buffer stay (DEC-014 source); `_MAG_SCALE_16BIT` replaces the misnamed constant; two `struct.unpack` calls per sample. After `_IMU_MAX_CONSECUTIVE_ERRORS = 50` bus errors the thread logs one WARNING, sets `available = False` and exits.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_imu.py`)

```python
import threading
import time as _time


@pytest.fixture
def mock_smbus_realtime():
    """Like mock_smbus but leaves rover.imu.time REAL except sleep, so the sampling
    thread can pace itself with monotonic()."""
    mock_bus = MagicMock()
    mock_bus.read_byte_data.return_value = 0x71
    mock_bus.read_i2c_block_data.return_value = [0] * 14
    with (
        patch("rover.imu._I2C_AVAILABLE", True),
        patch("rover.imu.SMBus", MagicMock(return_value=mock_bus)),
        patch("rover.imu.time.sleep", lambda *_a, **_k: None),
    ):
        yield mock_bus


class TestImuSamplingThread:
    def test_thread_samples_at_configured_rate(self, imu_config, mock_smbus_realtime):
        drv = ImuDriver(imu_config)  # sample_rate_hz = 200
        drv.start()
        try:
            _time.sleep(0.5)
            batch = drv.drain()
        finally:
            drv.stop()
        # 200 Hz × 0.5 s = 100 nominal; accept a loaded CI box
        assert 40 <= len(batch) <= 130, len(batch)
        assert drv.drain() == []  # drained
        assert drv.latest() is not None
        assert all(isinstance(s, ImuSample) for s in batch)

    def test_dt_uses_monotonic_clock(self, imu_config, mock_smbus_realtime, monkeypatch):
        """A wall-clock jump (NTP/GNSS correction) must not feed a huge dt to the filter."""
        drv = ImuDriver(imu_config)
        seen: list[float] = []
        real_update = drv._filter.update

        def spy(gx, gy, gz, ax, ay, az, dt, *mag):
            seen.append(dt)
            return real_update(gx, gy, gz, ax, ay, az, dt, *mag)

        monkeypatch.setattr(drv._filter, "update", spy)
        monkeypatch.setattr("rover.imu.time.time", lambda: 1e9)  # frozen wall clock
        drv.start()
        try:
            _time.sleep(0.2)
        finally:
            drv.stop()
        assert seen and max(seen) < 0.1, "dt must come from monotonic(), not a frozen/jumping wall clock"

    def test_sample_thread_stops_on_repeated_bus_errors(self, imu_config, mock_smbus_realtime):
        drv = ImuDriver(imu_config)
        drv.start()
        mock_smbus_realtime.read_i2c_block_data.side_effect = OSError(121, "Remote I/O error")
        deadline = _time.monotonic() + 3.0
        while drv.available and _time.monotonic() < deadline:
            _time.sleep(0.01)
        try:
            assert drv.available is False
            assert drv._thread is None or not drv._thread.is_alive()
        finally:
            drv.stop()

    def test_enable_magnetometer_is_honoured_by_thread(self, imu_config, mock_smbus_realtime):
        drv = ImuDriver(imu_config)
        drv.start()
        try:
            drv.enable_magnetometer(False)
            drv.drain()
            _time.sleep(0.1)
            batch = drv.drain()
            assert batch and all(s.mag is None for s in batch)
            drv.enable_magnetometer(True)
            drv.drain()
            _time.sleep(0.1)
            batch = drv.drain()
            assert batch and any(s.mag is not None for s in batch)
        finally:
            drv.stop()

    def test_stop_joins_thread(self, imu_config, mock_smbus_realtime):
        drv = ImuDriver(imu_config)
        drv.start()
        t = drv._thread
        drv.stop()
        assert t is not None and not t.is_alive()
```

Note: the existing `mock_smbus` fixture patches the whole `rover.imu.time` module; keep it for the existing tests (they call `read_sample()` directly and never start the thread long enough to matter). The realtime fixture is for the thread tests only. The AK8963 mock returns `[0]*14` for a 7-byte read too; `_read_mag` slices the first 7 and byte 6 is 0 (no overflow), so `mag` is `(0, 0, 0)` — that is fine for "not None".

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_imu.py -q -k "SamplingThread"
```

Expected: all FAIL (`drain`/`latest` missing; no thread).

- [ ] **Step 3: Implement**

Module level: rename `_MAG_SCALE_14BIT` → `_MAG_SCALE_16BIT` (value stays 0.15; comment `# µT per LSB in 16-bit mode (CNTL1 = 0x16)`), and add `_IMU_MAX_CONSECUTIVE_ERRORS = 50`. Add `import threading`.

In `ImuDriver.__init__` add:

```python
        self._filter = MadgwickFilter(beta=config.fusion_beta, mag_offset=mag_offset)
        self._bus_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: collections.deque[ImuSample] = collections.deque(maxlen=config.sample_rate_hz * 10)
        self._latest: ImuSample | None = None
        self._last_mono: float | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._consecutive_errors = 0
```

and change the signature to `def __init__(self, config: ImuConfig, mag_offset: tuple[float, float, float] | None = None) -> None:` (Task 5 wires it from `[calibration]`). Remove `self._last_time`.

In `start()`, after `self._ring_buffer.clear()`:

```python
        self._pending.clear()
        self._last_mono = None
        self._consecutive_errors = 0
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sample_loop, name="rover-imu", daemon=True)
        self._thread.start()
        logger.info("IMU started (%s), sampling at %d Hz", self._identity, self._config.sample_rate_hz)
```

(replace the old `logger.info("IMU started ...")`.)

In `stop()`, before closing the bus:

```python
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
```

Replace `read_sample` with a locked single read plus the loop, drain and latest:

```python
    def _read_one(self) -> ImuSample:
        """One locked bus read + filter step. Raises OSError on bus failure."""
        with self._bus_lock:
            accel, gyro = self._read_accel_gyro()
            mag = self._read_mag() if self._mag_enabled else None
        now_mono = time.monotonic()
        dt = (now_mono - self._last_mono) if self._last_mono is not None else 1.0 / self._config.sample_rate_hz
        self._last_mono = now_mono
        if mag is not None:
            self._filter.update(*gyro, *accel, dt, *mag)
        else:
            self._filter.update(*gyro, *accel, dt)
        return ImuSample(
            timestamp=time.time(), accel=accel, gyro=gyro, mag=mag, orientation=self._filter.quaternion
        )

    def read_sample(self) -> ImuSample:
        """Read one sample now (hardware diagnostics). Also recorded in the buffers."""
        if not self._available or self._bus is None:
            raise RuntimeError("IMU not available")
        sample = self._read_one()
        with self._state_lock:
            self._ring_buffer.append(sample)
            self._pending.append(sample)
            self._latest = sample
        return sample

    def _sample_loop(self) -> None:
        period = 1.0 / self._config.sample_rate_hz
        next_t = time.monotonic()
        while not self._stop_event.is_set():
            try:
                sample = self._read_one()
            except OSError as e:
                self._consecutive_errors += 1
                if self._consecutive_errors >= _IMU_MAX_CONSECUTIVE_ERRORS:
                    logger.warning(
                        "IMU: %d consecutive bus errors — sampling stopped, subsystem unavailable (last: %s)",
                        self._consecutive_errors, e,
                    )
                    self._available = False
                    return
                self._stop_event.wait(period)
                continue
            self._consecutive_errors = 0
            with self._state_lock:
                self._ring_buffer.append(sample)
                self._pending.append(sample)
                self._latest = sample
            next_t += period
            delay = next_t - time.monotonic()
            if delay > 0:
                self._stop_event.wait(delay)
            else:
                next_t = time.monotonic()  # fell behind; do not try to catch up

    def drain(self) -> list[ImuSample]:
        """Return and clear every sample recorded since the previous drain."""
        with self._state_lock:
            batch = list(self._pending)
            self._pending.clear()
        return batch

    def latest(self) -> ImuSample | None:
        with self._state_lock:
            return self._latest
```

`get_sample_at` reads `self._ring_buffer` under `self._state_lock` (wrap its body). `_read_accel_gyro` becomes:

```python
        raw = bytes(self._bus.read_i2c_block_data(addr, _REG_ACCEL_XOUT_H, 14))
        ax, ay, az, gx, gy, gz = struct.unpack(">3h2x3h", raw)
        return (
            (ax * _ACCEL_SCALE_2G, ay * _ACCEL_SCALE_2G, az * _ACCEL_SCALE_2G),
            (gx * _GYRO_SCALE_250DPS, gy * _GYRO_SCALE_250DPS, gz * _GYRO_SCALE_250DPS),
        )
```

and `_read_mag`'s three unpacks become `mx, my, mz = struct.unpack("<3h", bytes(raw[:6]))` scaled by `_MAG_SCALE_16BIT`. `enable_magnetometer` is unchanged (a bool assignment is atomic; the thread reads it per sample). Update the module docstring: the driver samples on its own thread; DEC-013 toggle is honoured per sample; changelog `0.11.0`.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_imu.py -q
```

Expected: all pass. The existing `test_ring_buffer_stores_samples`/`get_sample_at` tests call `read_sample()` directly; they still pass because `read_sample` appends to the ring buffer. If an existing test asserted `_MAG_SCALE_14BIT`, rename it.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/imu.py tests/test_imu.py && python -m ruff check src/rover/imu.py tests/test_imu.py
git add src/rover/imu.py tests/test_imu.py
git commit -m "feat(imu): sampling thread at sample_rate_hz with monotonic dt, drain()/latest(), bus-error shutdown; two-unpack reads (T1-017, T1-052)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Config — `mag_offset`, `use_magnetometer` default, step-interval validation

**Files:**
- Modify: `src/rover/config.py` (`CalibrationConfig`, `_validate` calibration + stepper blocks, `_build_config`)
- Modify: `config/default.toml` (`[imu].use_magnetometer`, `[stepper].step_interval_deg`, `[calibration]` comment)
- Modify: `src/rover/main.py` (`_init_sensors` passes `mag_offset`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `CalibrationConfig.mag_offset: list[float] | None`; `_validate` rejects a `step_interval_deg` that is not an integer multiple of `360 / steps_per_rev` (tolerance 1e-9); `default.toml` ships `step_interval_deg = 1.575` (14 microsteps at 3200/rev) and `use_magnetometer = false`; `ImuDriver(config.imu, mag_offset=tuple(config.calibration.mag_offset) if set else None)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_config.py`)

```python
class TestStage3Config:
    def test_mag_offset_parsed(self, tmp_path):
        p = tmp_path / "c.toml"
        p.write_text("[calibration]\nmag_offset = [12.5, -3.0, 40.0]\n")
        cfg = load_config(p)
        assert cfg.calibration.mag_offset == [12.5, -3.0, 40.0]

    def test_mag_offset_rejects_wrong_length(self, tmp_path):
        p = tmp_path / "c.toml"
        p.write_text("[calibration]\nmag_offset = [1.0, 2.0]\n")
        with pytest.raises(ValueError, match=r"\[calibration\] mag_offset"):
            load_config(p)

    def test_default_magnetometer_off_until_calibrated(self):
        cfg = load_config()
        assert cfg.imu.use_magnetometer is False
        assert cfg.calibration.mag_offset is None

    def test_step_interval_must_be_multiple_of_microstep(self, tmp_path):
        p = tmp_path / "c.toml"
        p.write_text("[stepper]\nsteps_per_rev = 3200\nstep_interval_deg = 1.5\n")
        with pytest.raises(ValueError, match=r"step_interval_deg.*multiple of 0\.1125"):
            load_config(p)

    def test_default_step_interval_is_exact(self):
        cfg = load_config()
        per_step = 360.0 / cfg.stepper.steps_per_rev
        assert cfg.stepper.step_interval_deg / per_step == pytest.approx(round(cfg.stepper.step_interval_deg / per_step))
```

(`load_config` and `pytest` are already imported in `tests/test_config.py`.)

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_config.py -q -k Stage3Config
```

Expected: all five FAIL.

- [ ] **Step 3: Implement**

`CalibrationConfig` gains `mag_offset: list[float] | None = None` with the comment `# hard-iron offset (x, y, z) in µT, body frame; None = uncalibrated`.

In `_validate`, in the calibration block, extend the 3-float loop to cover it: `for key in ("lidar_to_imu_translation", "imu_to_gnss_translation", "mag_offset"):`.

In the `# -- stepper --` block (after the existing type/range checks on `steps_per_rev` and `step_interval_deg`), add:

```python
    per_step = 360.0 / st["steps_per_rev"]
    ratio = st["step_interval_deg"] / per_step
    if abs(ratio - round(ratio)) > 1e-9:
        raise ValueError(
            f"[stepper] step_interval_deg ({st['step_interval_deg']}) must be an integer "
            f"multiple of {per_step:g}° (360 / steps_per_rev = {st['steps_per_rev']}); "
            f"e.g. {round(ratio) * per_step:g}"
        )
```

(where `st` is the stepper dict name used in that block — check the actual variable name.)

In `_build_config`, `CalibrationConfig(... mag_offset=cal_raw.get("mag_offset"))`.

`config/default.toml`: `use_magnetometer = false           # 9-DOF needs [calibration].mag_offset first (stage 3); DEC-013 gating applies when true`; `step_interval_deg = 1.575         # 14 microsteps at 3200/rev; MUST be a multiple of 0.1125°`; in `[calibration]` add a commented `# mag_offset = [0.0, 0.0, 0.0]                  # hard-iron offset, µT, body frame — measure before enabling use_magnetometer`.

`src/rover/main.py` `_init_sensors`: 

```python
    if config.imu.enabled:
        try:
            mag_offset = (
                tuple(config.calibration.mag_offset) if config.calibration.mag_offset else None
            )
            sensors.imu = ImuDriver(config.imu, mag_offset=mag_offset)
```

Also grep tests for `step_interval_deg = 1.5` and `step_interval_deg=1.5` and change those fixtures to `1.575` (or `1.125`) so the suite stays green; likewise any test asserting the default `use_magnetometer is True` (e.g. in `tests/test_config.py`'s defaults tests) flips to `False`. List every fixture you changed in the report.

- [ ] **Step 4: Run**

```bash
python -m pytest -q 2>&1 | tail -2
```

Expected: green; count reported.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/config.py src/rover/main.py tests && python -m ruff check src/rover/config.py src/rover/main.py tests
git add src/rover/config.py src/rover/main.py config/default.toml tests
git commit -m "feat(config): [calibration].mag_offset; magnetometer off by default; step_interval_deg must be a microstep multiple (T1-041, T1-007)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Main loop — columnar records, mast angle, IMU batches, DEC-013 gating

**Files:**
- Modify: `src/rover/main.py` (`_scan_loop`: step block, LiDAR block, IMU block, record block)
- Test: `tests/test_main.py`

**Interfaces:**
- Produces the stage 3 record formats:
  - lidar: `{"type": "lidar", "timestamp": float, "step_index": int, "mast_angle_deg": float, "lidar_ms_start": int, "lidar_ms_end": int, "angle": [float...], "distance": [float...], "intensity": [int...]}`
  - imu (batched, one per loop iteration when any samples were drained): `{"type": "imu", "timestamp": float (last sample), "t": [float...], "accel": [[x,y,z]...], "gyro": [[x,y,z]...], "mag": [[x,y,z] | null ...], "orientation": [[w,x,y,z]...]}`
- `mast_angle_deg` is `sensors.stepper.current_angle` when a stepper is available, else `0.0`.
- DEC-013: `sensors.imu.enable_magnetometer(False)` before `stepper.step(...)`, `enable_magnetometer(config.imu.use_magnetometer)` after the settle wait.
- LiDAR: `scan = sensors.lidar.read_scan(discard_stale=True)` after a step; `discard_stale=False` when no stepper is present (continuous mode).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_main.py`)

```python
class _FakeScan:
    def __init__(self, n: int = 3) -> None:
        from rover.lidar import LidarPoint, LidarScan

        self.scan = LidarScan(
            points=[LidarPoint(angle=10.0 * i, distance=1.0 + i, intensity=100 + i) for i in range(n)],
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
            ImuSample(timestamp=1.0, accel=(0, 0, 9.81), gyro=(0, 0, 0), mag=None, orientation=(1, 0, 0, 0)),
            ImuSample(timestamp=1.005, accel=(0, 0, 9.81), gyro=(0, 0, 0), mag=(1, 2, 3), orientation=(1, 0, 0, 0)),
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
output_dir = "{(tmp_path / 'data').as_posix()}"
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
    assert main_mod.run(config_path=_stage3_config(tmp_path), duration_sec=0.6) == 0

    session = next((tmp_path / "data").glob("s3_*"))
    recs = [json.loads(l) for l in (session / "scan.jsonl").read_text().splitlines() if l]
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
    b = imu[0]
    assert b["t"] == [1.0, 1.005] and b["mag"] == [None, [1, 2, 3]]
    assert b["orientation"][0] == [1, 0, 0, 0]
    # DEC-013: mag disabled before each step, re-enabled after settle
    assert _FakeImu.mag_calls[:2] == [False, True]
    # stale discard after a step
    assert _StaticLidar.calls and all(_StaticLidar.calls)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_main.py -q -k columnar
```

Expected: FAIL (`for p in lidar_points` on a `LidarScan`, or `"points"` present).

- [ ] **Step 3: Implement** in `_scan_loop`

Step block becomes:

```python
        stepped = False
        if sensors.stepper is not None and sensors.stepper.available and steps_per_increment > 0:
            if sensors.imu is not None and sensors.imu.available:
                sensors.imu.enable_magnetometer(False)  # DEC-013: stepper EMI
            try:
                sensors.stepper.step(steps_per_increment)
                stepped = True
            except Exception as e:
                logger.warning("Stepper step failed: %s — pausing scan", e)
                status.scan_state = SCAN_ERROR
                stop_event.wait(0.5)
                continue
        stop_event.wait(settle_sec)
        if stepped and sensors.imu is not None and sensors.imu.available:
            sensors.imu.enable_magnetometer(config.imu.use_magnetometer)
        mast_angle_deg = (
            sensors.stepper.current_angle
            if sensors.stepper is not None and sensors.stepper.available
            else 0.0
        )
```

LiDAR block: `lidar_scan: LidarScan | None = None` ... `lidar_scan = sensors.lidar.read_scan(discard_stale=stepped)` (import `LidarScan` from `rover.lidar`).

IMU block: replace `read_sample()` with:

```python
        imu_batch: list = []
        if sensors.imu is not None and sensors.imu.available and not imu_gate.tripped:
            try:
                imu_batch = sensors.imu.drain()
                imu_gate.record_success()
            except _SENSOR_ERRORS as e:
                imu_gate.record_failure(e)
```

Record block:

```python
        now = time.time()
        if lidar_scan is not None and lidar_scan.points:
            session_logger.write(
                {
                    "type": "lidar",
                    "timestamp": now,
                    "step_index": step_index,
                    "mast_angle_deg": mast_angle_deg,
                    "lidar_ms_start": lidar_scan.lidar_ms_start,
                    "lidar_ms_end": lidar_scan.lidar_ms_end,
                    "angle": [p.angle for p in lidar_scan.points],
                    "distance": [p.distance for p in lidar_scan.points],
                    "intensity": [p.intensity for p in lidar_scan.points],
                }
            )
        if imu_batch:
            session_logger.write(
                {
                    "type": "imu",
                    "timestamp": imu_batch[-1].timestamp,
                    "t": [s.timestamp for s in imu_batch],
                    "accel": [list(s.accel) for s in imu_batch],
                    "gyro": [list(s.gyro) for s in imu_batch],
                    "mag": [list(s.mag) if s.mag is not None else None for s in imu_batch],
                    "orientation": [list(s.orientation) for s in imu_batch],
                }
            )
```

The camera record is unchanged. Update `main.py`'s module docstring record description if it has one, and the changelog line.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_main.py tests/test_lidar.py tests/test_imu.py -q && python -m pytest -q 2>&1 | tail -1
```

Expected: green. `_FlakyLidar` from stage 2 still raises `OSError` from `read_scan(discard_stale=...)` — confirm its signature accepts the kwarg (`def read_scan(self, discard_stale=True)`), else update that stub.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/main.py tests/test_main.py && python -m ruff check src/rover/main.py tests/test_main.py
git add src/rover/main.py tests/test_main.py
git commit -m "feat(main): columnar lidar records with mast angle + LD19 timestamps; batched IMU records from drain(); DEC-013 mag gating around steps (T1-007, T1-015, T1-043)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Georef loader — rotated files, columnar lidar, flattened IMU batches

**Files:**
- Modify: `scripts/georef.py` (`load_session`; new `_iter_jsonl`, `_flatten_imu_batch`)
- Test: `tests/test_georef.py` (fixture regenerated)

**Interfaces:**
- Produces: `load_session(session_dir)` reads `scan.jsonl, scan_001.jsonl, scan_002.jsonl, …` and `gnss.jsonl, gnss_001.jsonl, …` in numeric order; `SessionData.imu_records` is a flat list of `{"timestamp", "accel", "gyro", "mag", "orientation"}` dicts (one per sample) expanded from batch records; lidar records are the columnar format from Task 6.

- [ ] **Step 1: Regenerate the fixture and write the failing tests**

In `tests/test_georef.py`, replace `_make_session` with:

```python
def _lidar_record(ts: float, step_index: int, mast_angle_deg: float, angles, distances, intensities) -> dict:
    return {
        "type": "lidar",
        "timestamp": ts,
        "step_index": step_index,
        "mast_angle_deg": mast_angle_deg,
        "lidar_ms_start": 1000,
        "lidar_ms_end": 1090,
        "angle": list(angles),
        "distance": list(distances),
        "intensity": list(intensities),
    }


def _imu_batch(ts: list[float], orientation=(1.0, 0.0, 0.0, 0.0)) -> dict:
    return {
        "type": "imu",
        "timestamp": ts[-1],
        "t": list(ts),
        "accel": [[0, 0, 9.81]] * len(ts),
        "gyro": [[0, 0, 0]] * len(ts),
        "mag": [None] * len(ts),
        "orientation": [list(orientation)] * len(ts),
    }


def _make_session(
    tmp_path: Path, with_gnss: bool = True, profile: str = "personal", target_crs: int = 0
) -> Path:
    """Create a minimal but valid session directory and return its path."""
    sess = tmp_path / "scan_20260523_120000"
    sess.mkdir()
    meta = {
        "session_id": sess.name,
        "device_name": "rover-01",
        "firmware_version": "0.10.0",
        "session": {
            "profile": profile,
            "project_code": "TEST" if profile == "arm_group" else "",
            "mission_tag": "BENCH",
            "target_crs_epsg": target_crs,
            "units": "m",
        },
    }
    (sess / "metadata.json").write_text(json.dumps(meta))
    lines = [json.dumps(_imu_batch([100.0, 100.1]))]
    if with_gnss:
        lines.append(
            json.dumps(
                {
                    "type": "gnss", "timestamp": 100.05, "fix_type": 5,
                    "lat": 40.7128, "lon": -74.0060, "alt": 10.0,
                    "hdop": 0.85, "vdop": 1.2, "sat_count": 18, "rtk_age": 1.2,
                }
            )
        )
    lines.append(
        json.dumps(
            _lidar_record(100.05, 0, 0.0, [0.0, 90.0, 180.0, 270.0], [1.0, 2.0, 1.5, 0.5], [128, 200, 50, 100])
        )
    )
    (sess / "scan.jsonl").write_text("\n".join(lines) + "\n")
    return sess
```

Update `TestLoadSession.test_load_returns_records` to expect `len(data.imu_records) == 2` (flattened from one batch) and add:

```python
    def test_load_flattens_imu_batches(self, tmp_path):
        sess = _make_session(tmp_path)
        data = georef.load_session(sess)
        assert [r["timestamp"] for r in data.imu_records] == [100.0, 100.1]
        assert data.imu_records[0]["orientation"] == [1.0, 0.0, 0.0, 0.0]

    def test_load_session_reads_rotated_files_in_order(self, tmp_path):
        sess = _make_session(tmp_path)
        # Two rotated segments after the base file, deliberately written out of
        # lexical order of creation to prove numeric ordering.
        (sess / "scan_002.jsonl").write_text(
            json.dumps(_lidar_record(300.0, 2, 3.0, [0.0], [1.0], [1])) + "\n"
        )
        (sess / "scan_001.jsonl").write_text(
            json.dumps(_lidar_record(200.0, 1, 1.5, [0.0], [1.0], [1])) + "\n"
        )
        (sess / "gnss.jsonl").write_text("")
        (sess / "gnss_001.jsonl").write_text(
            json.dumps({"type": "gnss", "timestamp": 250.0, "fix_type": 5, "lat": 40.7, "lon": -74.0, "alt": 9.0}) + "\n"
        )
        data = georef.load_session(sess)
        assert [r["step_index"] for r in data.lidar_records] == [0, 1, 2]
        assert [r["timestamp"] for r in data.gnss_records] == [100.05, 250.0]
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_georef.py -q -k "Load"
```

Expected: `test_load_flattens_imu_batches` FAIL (1 record, not 2), `rotated_files` FAIL (only step 0).

- [ ] **Step 3: Implement**

Replace `load_session` with:

```python
_SEGMENT_RE = re.compile(r"^(scan|gnss)(?:_(\d{3}))?\.jsonl$")


def _segment_files(session_dir: Path, stem: str) -> list[Path]:
    """`<stem>.jsonl, <stem>_001.jsonl, …` in numeric order (SessionLogger rotation)."""
    found: list[tuple[int, Path]] = []
    for p in session_dir.glob(f"{stem}*.jsonl"):
        m = _SEGMENT_RE.match(p.name)
        if m and m.group(1) == stem:
            found.append((int(m.group(2) or 0), p))
    return [p for _, p in sorted(found)]


def _iter_jsonl(paths: list[Path]):
    for p in paths:
        for line in p.read_text().splitlines():
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                logger.warning("skipping malformed line in %s", p.name)


def _flatten_imu_batch(rec: dict) -> list[dict]:
    """One batched IMU record → one dict per sample."""
    ts = rec["t"]
    return [
        {
            "timestamp": ts[i],
            "accel": rec["accel"][i],
            "gyro": rec["gyro"][i],
            "mag": rec["mag"][i],
            "orientation": rec["orientation"][i],
        }
        for i in range(len(ts))
    ]


def load_session(session_dir: Path) -> SessionData:
    """Load metadata.json + every scan*/gnss* segment (rotation-aware)."""
    metadata_path = session_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"No metadata.json in {session_dir}")
    metadata = json.loads(metadata_path.read_text())

    scan_files = _segment_files(session_dir, "scan")
    if not scan_files:
        raise FileNotFoundError(f"No scan.jsonl in {session_dir}")

    lidar: list[dict] = []
    imu: list[dict] = []
    gnss: list[dict] = []
    for rec in _iter_jsonl(scan_files):
        t = rec.get("type")
        if t == "lidar":
            lidar.append(rec)
        elif t == "imu":
            imu.extend(_flatten_imu_batch(rec))
        elif t == "gnss":
            gnss.append(rec)

    gnss_files = _segment_files(session_dir, "gnss")
    if gnss_files and not gnss:
        gnss = [r for r in _iter_jsonl(gnss_files) if r.get("type") == "gnss"]

    logger.info("Loaded session: %d lidar, %d imu, %d gnss records across %d scan segment(s)",
                len(lidar), len(imu), len(gnss), len(scan_files))
    return SessionData(metadata=metadata, lidar_records=lidar, imu_records=imu, gnss_records=gnss)
```

Add `import re` to the imports. Note: `gnss` records are still mirrored into `scan.jsonl` by the logger (stage 4 decides that duplication); the fallback logic is preserved.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_georef.py -q
```

Expected: the Load tests pass; the pipeline tests may now FAIL because `lidar_points_to_local` still reads `record["points"]` — that is Task 8. Commit only if the whole file is green; otherwise complete Task 8 first and commit both together with this task's message plus Task 8's (two commits are preferred; if the intermediate state is red, one combined commit is acceptable — say which).

- [ ] **Step 5: Commit**

```bash
python -m ruff format scripts/georef.py tests/test_georef.py && python -m ruff check scripts/georef.py tests/test_georef.py
git add scripts/georef.py tests/test_georef.py
git commit -m "fix(georef): load rotated scan/gnss segments in order; read columnar lidar and batched IMU records (T1-008)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Georef geometry — mount rotation, mast rotation, tuple contract, helpers

**Files:**
- Modify: `scripts/georef.py` (`lidar_points_to_local`, `session_to_pointcloud`, `_nearest_gnss`, `orientation_at`, module constants, `_require_numpy` usage)
- Test: `tests/test_georef.py`

**Interfaces:**
- Produces: module constants `R_EARTH_M = 6378137.0`, `US_SURVEY_FOOT_M = 0.3048006096012192`; `_np` resolved once via `np = _require_numpy()` at the top of `main()` and passed implicitly by module global `_NP` (set by `_require_numpy()` on first call); `_rot_z(theta_deg) -> 3x3`; `lidar_points_to_local(rec, quat) -> tuple[ndarray(N,3), ndarray(N,) uint8]` always a tuple; transform order: scan plane (x, y) → body `(x, 0, y)` → `R_z(mast_angle_deg)` → `R(quat)`; `enu_offset_m(lat, lon, alt, lat0, lon0, alt0)` and `geodetic_from_enu(e, n, u, lat0, lon0, alt0)` as the single pair of ENU helpers; `_nearest_gnss` and `orientation_at` use `bisect`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_georef.py`)

```python
class TestGeometry:
    def test_empty_record_returns_tuple(self):
        pts, inten = georef.lidar_points_to_local(
            {"angle": [], "distance": [], "intensity": [], "mast_angle_deg": 0.0},
            np.array([1.0, 0.0, 0.0, 0.0]),
        )
        assert pts.shape == (0, 3) and inten.shape == (0,)

    def test_scan_plane_is_body_xz_at_mast_zero(self):
        rec = {"angle": [0.0, 90.0], "distance": [2.0, 3.0], "intensity": [1, 2], "mast_angle_deg": 0.0}
        pts, _ = georef.lidar_points_to_local(rec, np.array([1.0, 0.0, 0.0, 0.0]))
        np.testing.assert_allclose(pts[0], [2.0, 0.0, 0.0], atol=1e-9)  # forward
        np.testing.assert_allclose(pts[1], [0.0, 0.0, 3.0], atol=1e-9)  # LiDAR +y → body up

    def test_mast_rotation_sweeps_forward_point_to_left(self):
        rec = {"angle": [0.0], "distance": [2.0], "intensity": [1], "mast_angle_deg": 90.0}
        pts, _ = georef.lidar_points_to_local(rec, np.array([1.0, 0.0, 0.0, 0.0]))
        np.testing.assert_allclose(pts[0], [0.0, 2.0, 0.0], atol=1e-9)  # +90° about Z: forward → left

    def test_imu_quaternion_applied_after_mast(self):
        # 90° about body Z from the IMU, mast at 0: forward → left
        q = np.array([np.cos(np.pi / 4), 0.0, 0.0, np.sin(np.pi / 4)])
        rec = {"angle": [0.0], "distance": [1.0], "intensity": [1], "mast_angle_deg": 0.0}
        pts, _ = georef.lidar_points_to_local(rec, q)
        np.testing.assert_allclose(pts[0], [0.0, 1.0, 0.0], atol=1e-9)

    def test_sweep_produces_a_volume(self, tmp_path):
        """A 2 m ring in the scan plane swept 0..180° about Z must fill a sphere:
        every axis spans about ±2 m and nothing is flat (T1-007)."""
        import json

        sess = tmp_path / "sweep"
        sess.mkdir()
        (sess / "metadata.json").write_text(json.dumps({"session": {"profile": "personal", "target_crs_epsg": 0, "units": "m"}}))
        angles = [float(a) for a in range(0, 360, 5)]
        lines = [json.dumps(_imu_batch([0.0, 1000.0]))]
        for i, mast in enumerate(range(0, 181, 5)):
            lines.append(json.dumps(_lidar_record(float(i), i, float(mast), angles, [2.0] * len(angles), [1] * len(angles))))
        (sess / "scan.jsonl").write_text("\n".join(lines) + "\n")
        data = georef.load_session(sess)
        xyz, inten, origin = georef.session_to_pointcloud(data)
        assert xyz.shape[0] == len(angles) * 37
        for axis in range(3):
            assert xyz[:, axis].min() == pytest.approx(-2.0, abs=0.05)
            assert xyz[:, axis].max() == pytest.approx(2.0, abs=0.05)
        assert xyz[:, 1].std() > 0.5

    def test_nearest_gnss_bisect_matches_linear(self):
        fixes = [{"timestamp": float(t), "lat": 0, "lon": 0} for t in (1, 4, 9, 16)]
        assert georef._nearest_gnss(5.0, fixes)["timestamp"] == 4.0
        assert georef._nearest_gnss(12.6, fixes)["timestamp"] == 16.0
        assert georef._nearest_gnss(0.0, fixes)["timestamp"] == 1.0
        assert georef._nearest_gnss(100.0, fixes)["timestamp"] == 16.0
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_georef.py -q -k "Geometry"
```

Expected: all FAIL (`KeyError: 'points'`, wrong axes, etc.).

- [ ] **Step 3: Implement**

Module constants after `logger`:

```python
R_EARTH_M = 6378137.0  # WGS84 semi-major axis
US_SURVEY_FOOT_M = 0.3048006096012192
```

Make `_require_numpy()` cache: 

```python
_NP = None


def _require_numpy():
    global _NP
    if _NP is None:
        try:
            import numpy as np
        except ImportError as e:
            raise SystemExit('numpy is required for scripts/georef.py — install via `pip install -e ".[post]"`') from e
        _NP = np
    return _NP
```

Add helpers:

```python
def _rot_z(theta_deg: float):
    np = _require_numpy()
    c, s = math.cos(math.radians(theta_deg)), math.sin(math.radians(theta_deg))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def enu_offset_m(lat, lon, alt, lat0, lon0, alt0) -> tuple[float, float, float]:
    """Small-baseline ENU offset (m) of (lat, lon, alt) from the origin. Equirectangular;
    adequate well under 1 km."""
    lat0_rad = math.radians(lat0)
    e = math.radians(lon - lon0) * R_EARTH_M * math.cos(lat0_rad)
    n = math.radians(lat - lat0) * R_EARTH_M
    return e, n, alt - alt0


def geodetic_from_enu(east, north, up, lat0: float, lon0: float, alt0: float):
    """Vectorised inverse of enu_offset_m (arrays in, arrays out)."""
    np = _require_numpy()
    lat0_rad = math.radians(lat0)
    lats = lat0 + np.degrees(north / R_EARTH_M)
    lons = lon0 + np.degrees(east / (R_EARTH_M * math.cos(lat0_rad)))
    return lats, lons, alt0 + up
```

Replace `lidar_points_to_local`:

```python
def lidar_points_to_local(lidar_record: dict, quat):
    """One columnar lidar record → (N×3 body-ENU-aligned points, N intensities).

    Chain (spec §5): scan plane (LiDAR x forward, y left) is mounted as the body
    X-Z plane → rotate about body Z by the commanded mast angle → rotate by the
    IMU quaternion. Always returns a tuple, even for an empty record.
    """
    np = _require_numpy()
    angles = np.asarray(lidar_record.get("angle", []), dtype=float)
    dists = np.asarray(lidar_record.get("distance", []), dtype=float)
    inten = np.asarray(lidar_record.get("intensity", []), dtype=np.uint8)
    if angles.size == 0:
        return np.zeros((0, 3)), np.zeros(0, dtype=np.uint8)
    a = np.deg2rad(angles)
    x_l = dists * np.cos(a)
    y_l = dists * np.sin(a)
    body = np.column_stack([x_l, np.zeros_like(x_l), y_l])  # mount: LiDAR y → body up
    body = body @ _rot_z(float(lidar_record.get("mast_angle_deg", 0.0))).T
    world = body @ _quat_to_rotmat(quat).T
    return world, inten
```

In `session_to_pointcloud`: replace `_gnss_offset_meters(...)` with `enu_offset_m(...)`, delete `_gnss_offset_meters`, delete `total_points` (use `len(xyz)` in the log line after `vstack`). Replace `_nearest_gnss` with a bisect version:

```python
def _nearest_gnss(t_scan: float, gnss_sorted: list[dict]) -> dict | None:
    if not gnss_sorted:
        return None
    i = bisect.bisect_left(gnss_sorted, t_scan, key=lambda r: r["timestamp"])
    if i == 0:
        return gnss_sorted[0]
    if i >= len(gnss_sorted):
        return gnss_sorted[-1]
    before, after = gnss_sorted[i - 1], gnss_sorted[i]
    return before if t_scan - before["timestamp"] <= after["timestamp"] - t_scan else after
```

and in `orientation_at` replace the hand-rolled binary search with `lo = bisect.bisect_left(imu_records, t_scan, key=lambda r: r["timestamp"])` (keeping the surrounding edge handling). Add `import bisect`. In `project_to_crs` (Task 9 rewrites it) leave as is for now except replacing its inline `R_EARTH`/back-projection with `geodetic_from_enu`.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_georef.py -q
```

Expected: all pass (the PLY pipeline test still asserts `element vertex 4`).

- [ ] **Step 5: Commit**

```bash
python -m ruff format scripts/georef.py tests/test_georef.py && python -m ruff check scripts/georef.py tests/test_georef.py
git add scripts/georef.py tests/test_georef.py
git commit -m "fix(georef): apply mount and mast rotation before the IMU quaternion; tuple contract; bisect lookups; shared ENU helpers (T1-007, T1-039, T1-050)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Georef export — Z in CRS units, units honoured, double PLY, CRS-embed warning

**Files:**
- Modify: `scripts/georef.py` (`project_to_crs`, `export_ply`, `export_las`, `_try_import_*`)
- Test: `tests/test_georef.py`

**Interfaces:**
- Produces: `project_to_crs(xyz, origin, target_epsg, units)` returns X, Y, Z all in the target CRS's horizontal unit when `target_epsg != 0` (Z = ellipsoidal height converted from metres), then, if `units` disagrees with the CRS unit, converts all three (ft-US ↔ m) and logs which; `export_ply` writes `property double x/y/z`; `export_las` logs a WARNING when the CRS cannot be embedded; one `_optional_import(name)` helper replaces the two try-import wrappers; the module docstring states heights are ellipsoidal.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_georef.py`)

```python
class TestExportUnits:
    def test_project_to_crs_scales_z_to_crs_unit(self, pyproj_mod):
        """EPSG:6346 is ftUS: a 1 m rise must come out as ~3.2808 ft, not 1 (T1-009)."""
        origin = (40.7128, -74.006, 10.0)
        out = georef.project_to_crs(np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]), origin, 6346, "ft")
        dz = out[1, 2] - out[0, 2]
        assert dz == pytest.approx(1.0 / georef.US_SURVEY_FOOT_M, rel=1e-6)
        # Absolute Z is the ellipsoidal height in feet
        assert out[0, 2] == pytest.approx(10.0 / georef.US_SURVEY_FOOT_M, rel=1e-6)

    def test_units_m_on_ftus_crs_converts_all_axes(self, pyproj_mod):
        origin = (40.7128, -74.006, 10.0)
        pts = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        ft = georef.project_to_crs(pts, origin, 6346, "ft")
        m = georef.project_to_crs(pts, origin, 6346, "m")
        np.testing.assert_allclose(m, ft * georef.US_SURVEY_FOOT_M, rtol=1e-9)

    def test_export_ply_is_double_precision(self, tmp_path):
        xyz = np.array([[1_234_567.123456, 2.0, 3.0]])
        inten = np.array([200], dtype=np.uint8)
        out = tmp_path / "p.ply"
        georef.export_ply(out, xyz, inten)
        raw = out.read_bytes()
        header, _, body = raw.partition(b"end_header\n")
        assert b"property double x" in header
        x = np.frombuffer(body[:8], dtype="<f8")[0]
        assert x == pytest.approx(1_234_567.123456, abs=1e-6)

    def test_export_las_warns_when_crs_cannot_be_embedded(self, tmp_path, monkeypatch, caplog):
        laspy = pytest.importorskip("laspy")

        class _NoCrsHeader(laspy.LasHeader):
            def add_crs(self, *_a, **_k):
                raise AttributeError("no add_crs")

        monkeypatch.setattr(laspy, "LasHeader", _NoCrsHeader)
        with caplog.at_level("WARNING", logger="georef"):
            ok = georef.export_las(tmp_path / "x.las", np.zeros((1, 3)), np.zeros(1, dtype=np.uint8), 6346)
        assert ok
        assert any("CRS" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_georef.py -q -k "ExportUnits"
```

Expected: Z test FAIL (dz == 1.0), units test FAIL, PLY test FAIL (`property float`), LAS warning test FAIL (no record). `pyproj` and `laspy` are installed on this machine (`[post]` extra); if either is missing the corresponding tests skip, which is NOT an acceptable GREEN — install them with `pip install -e ".[post]"` first.

- [ ] **Step 3: Implement**

Replace the two try-import wrappers with:

```python
def _optional_import(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None
```

(add `import importlib`; call sites become `_optional_import("laspy")` / `_optional_import("pyproj")`).

Replace `project_to_crs`:

```python
def project_to_crs(xyz, origin_lat_lon_alt, target_epsg: int, units: str):
    """Convert N×3 local-ENU metres to the target CRS.

    With ``target_epsg == 0`` the ENU frame is kept and only ``units`` applies.
    Otherwise X/Y are projected with pyproj and Z (ellipsoidal height, metres)
    is scaled to the CRS's horizontal unit so all three axes agree; if ``units``
    then disagrees with the CRS unit, all three axes are converted (ft-US ↔ m)
    and the choice is logged.
    """
    np = _require_numpy()
    if target_epsg == 0 or origin_lat_lon_alt[0] is None:
        return xyz / US_SURVEY_FOOT_M if units == "ft" else xyz

    pyproj = _optional_import("pyproj")
    if pyproj is None:
        raise SystemExit(
            'pyproj is required when target_crs_epsg != 0 — install via `pip install -e ".[post]"`'
        )
    lat0, lon0, alt0 = origin_lat_lon_alt
    lats, lons, alts = geodetic_from_enu(xyz[:, 0], xyz[:, 1], xyz[:, 2], lat0, lon0, alt0)
    crs = pyproj.CRS.from_epsg(target_epsg)
    transformer = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    xs, ys = transformer.transform(lons, lats)

    # Metres per horizontal CRS unit (1.0 for metric CRSs, 0.3048006… for ftUS).
    unit_m = float(crs.axis_info[0].unit_conversion_factor)
    zs = alts / unit_m  # ellipsoidal height, same unit as X/Y
    out = np.column_stack([xs, ys, zs])

    crs_is_ft = abs(unit_m - US_SURVEY_FOOT_M) < 1e-9 or abs(unit_m - 0.3048) < 1e-9
    if units == "m" and crs_is_ft:
        logger.info("Converting EPSG:%d output from feet to metres per --units m", target_epsg)
        out = out * unit_m
    elif units == "ft" and not crs_is_ft:
        logger.info("Converting EPSG:%d output from metres to US survey feet per --units ft", target_epsg)
        out = out / US_SURVEY_FOOT_M
    return out
```

`export_ply`: header lines `property double x/y/z`; dtype `[("xyz", "<f8", 3), ("rgb", "u1", 3)]`; `vtx["xyz"] = xyz.astype(np.float64)`; comment `# 3 float64 + 3 uint8 = 27 bytes per point`.

`export_las`: on `AttributeError` from `add_crs`, `logger.warning("laspy %s cannot embed CRS EPSG:%d — LAS written without CRS", getattr(laspy, "__version__", "?"), target_epsg)`.

Module docstring: add under "Coordinate flow": `Heights are ellipsoidal (WGS84) throughout; no geoid model is applied. Z is scaled to the target CRS's horizontal unit so LAS/PLY axes agree.` Changelog `0.11.0`.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_georef.py -q
```

Expected: all pass (the arm_group override test now writes a ftUS cloud with consistent Z).

- [ ] **Step 5: Commit**

```bash
python -m ruff format scripts/georef.py tests/test_georef.py && python -m ruff check scripts/georef.py tests/test_georef.py
git add scripts/georef.py tests/test_georef.py
git commit -m "fix(georef): Z in the CRS unit, --units honoured, double-precision PLY, CRS-embed warning, one optional-import helper (T1-009, T1-010, T1-050)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Merge stage 3

- [ ] **Step 1: Full verification**

```bash
python -m pytest -q 2>&1 | tail -1
python -m ruff check src scripts tests
python -m ruff format --check src scripts tests | tail -1
git ls-files -z 'deploy/*' 'config/*' | xargs -0 python -c "import sys; [print(p, open(p,'rb').read().count(b'\r\n')) for p in sys.argv[1:]]"
```

Expected: green (report the measured count), ruff clean, format clean, every deploy/config file 0 CRLF.

- [ ] **Step 2: Merge**

```bash
git checkout main
git merge --no-ff fix/stage3-pipeline -F <message file>
git branch -d fix/stage3-pipeline
```

Merge message: `Merge stage 3: data pipeline (T1-007..010, T1-012..017, T1-039, T1-043, T1-044, T1-050, T1-052)` + a body summarising the record-format change and the geometry chain + the trailer.

- [ ] **Step 3: Mark the rows done** in `docs/AUDIT_super_20260922_1810.md` (`done (<merge sha>)`) for the IDs above, and note in T1-041's row that `mag_offset` is now consumed. Commit on `main`.
