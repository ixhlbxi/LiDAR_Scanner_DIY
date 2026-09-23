"""Unit tests for rover.imu — runs anywhere, no hardware required."""

import math
import struct
import time as _time
from unittest.mock import MagicMock, patch

import pytest

from rover.config import ImuConfig
from rover.imu import _MAG_SCALE_16BIT, ImuDriver, ImuSample, MadgwickFilter


def _poll_drain(drv, deadline_sec: float = 2.0):
    """Poll drv.drain() until it returns a non-empty batch or the deadline passes."""
    deadline = _time.monotonic() + deadline_sec
    batch: list = []
    while _time.monotonic() < deadline:
        batch = drv.drain()
        if batch:
            return batch
        _time.sleep(0.01)
    return batch


@pytest.fixture
def imu_config():
    return ImuConfig(
        enabled=True,
        bus=1,
        address=0x68,
        sample_rate_hz=200,
        use_magnetometer=False,
        fusion_beta=0.1,
    )


@pytest.fixture
def disabled_config():
    return ImuConfig(
        enabled=False,
        bus=1,
        address=0x68,
        sample_rate_hz=200,
        use_magnetometer=False,
        fusion_beta=0.1,
    )


@pytest.fixture
def mock_smbus():
    """Patch smbus2 and availability flag for off-Pi testing.

    Patches only `time.sleep` (a no-op), not the whole `time` module: `start()`
    now also launches the sampling thread, and `rover.imu.time` IS the real
    `time` module (same `sys.modules` singleton the thread's `time.monotonic()`/
    `time.time()` calls resolve through). A whole-module `patch("rover.imu.time")`
    used to be fine here because nothing but `read_sample()` ever touched it;
    with a live thread also calling in, its pacing math (`delay = next_t -
    time.monotonic(); if delay > 0`) hit a direct comparison against a
    MagicMock and crashed the thread. Leaving `monotonic`/`time` real fixes
    that; no-op'ing only `sleep` keeps `_init_mpu9250`/`_init_ak8963`'s ~0.22 s
    of real init delay out of every test using this fixture.
    """
    mock_bus = MagicMock()
    # WHO_AM_I returns MPU-9250
    mock_bus.read_byte_data.return_value = 0x71
    # Accel/gyro: 14 bytes of zeros (at rest, ~1g on Z after scaling)
    mock_bus.read_i2c_block_data.return_value = [0] * 14

    mock_smbus_class = MagicMock(return_value=mock_bus)
    with (
        patch("rover.imu._I2C_AVAILABLE", True),
        patch("rover.imu.SMBus", mock_smbus_class),
        patch("time.sleep", lambda *_a, **_k: None),
    ):
        yield mock_bus


# ---------------------------------------------------------------------------
# Madgwick filter tests
# ---------------------------------------------------------------------------


class TestMadgwickFilter:
    def test_initial_quaternion(self):
        f = MadgwickFilter(beta=0.1)
        assert f.quaternion == (1.0, 0.0, 0.0, 0.0)

    def test_update_with_gravity(self):
        f = MadgwickFilter(beta=0.1)
        # Stationary with gravity along Z
        for _ in range(100):
            f.update(0, 0, 0, 0, 0, 9.81, 0.01)
        q = f.quaternion
        # Should remain close to identity
        assert q[0] == pytest.approx(1.0, abs=0.05)

    def test_update_with_rotation(self):
        f = MadgwickFilter(beta=0.1)
        # Apply gyro rotation around Z
        for _ in range(50):
            f.update(0, 0, 1.0, 0, 0, 9.81, 0.01)
        q = f.quaternion
        # Quaternion should have changed from identity
        assert q != (1.0, 0.0, 0.0, 0.0)
        # Should still be unit quaternion
        norm = math.sqrt(sum(x * x for x in q))
        assert norm == pytest.approx(1.0, abs=1e-6)

    def test_quaternion_normalized(self):
        f = MadgwickFilter(beta=0.5)
        f.update(0.5, -0.3, 0.1, 2.0, -1.0, 9.0, 0.02)
        norm = math.sqrt(sum(x * x for x in f.quaternion))
        assert norm == pytest.approx(1.0, abs=1e-6)

    def test_zero_accel_gyro_only(self):
        """With zero accel (free-fall), should still produce valid quaternion."""
        f = MadgwickFilter(beta=0.1)
        f.update(0.1, 0, 0, 0, 0, 0, 0.01)
        norm = math.sqrt(sum(x * x for x in f.quaternion))
        assert norm == pytest.approx(1.0, abs=1e-6)


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
        yaw must settle near 0; with the field measured along body +Y it must
        settle near -90 deg.

        Body forward = +X, left = +Y (repo convention). North measured along
        the body's +Y (left) axis means north is 90 deg to the body's left, so
        the body's forward axis has been yawed -90 deg from north.
        """
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
        assert abs(yaw_deg(g.quaternion) - (-90.0)) < 3.0

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


# ---------------------------------------------------------------------------
# ImuDriver tests — no I2C
# ---------------------------------------------------------------------------


class TestImuNoI2C:
    def test_init_disabled(self, disabled_config):
        driver = ImuDriver(disabled_config)
        assert not driver.available

    def test_start_disabled(self, disabled_config):
        driver = ImuDriver(disabled_config)
        driver.start()
        assert not driver.available

    def test_start_without_smbus(self, imu_config):
        with patch("rover.imu._I2C_AVAILABLE", False):
            driver = ImuDriver(imu_config)
            driver.start()
            assert not driver.available

    def test_stop_idempotent(self, imu_config):
        driver = ImuDriver(imu_config)
        driver.stop()  # Should not raise

    def test_read_sample_not_available(self, imu_config):
        driver = ImuDriver(imu_config)
        with pytest.raises(RuntimeError, match="not available"):
            driver.read_sample()


# ---------------------------------------------------------------------------
# ImuDriver tests — with mocked I2C
# ---------------------------------------------------------------------------


class TestImuWithMockI2C:
    def test_start_opens_bus(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        try:
            assert driver.available
            assert driver.identity == "MPU-9250"
        finally:
            driver.stop()

    def test_start_mpu9255(self, imu_config, mock_smbus):
        mock_smbus.read_byte_data.return_value = 0x73
        driver = ImuDriver(imu_config)
        driver.start()
        try:
            assert driver.identity == "MPU-9255"
        finally:
            driver.stop()

    def test_start_unknown_who_am_i(self, imu_config, mock_smbus):
        mock_smbus.read_byte_data.return_value = 0x00
        driver = ImuDriver(imu_config)
        driver.start()
        try:
            assert driver.available  # Still usable
            assert "Unknown" in driver.identity
        finally:
            driver.stop()

    def test_double_start_ignored(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        try:
            driver.start()  # Should not raise
            assert driver.available
        finally:
            driver.stop()

    def test_stop_closes_bus(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        driver.stop()
        mock_smbus.close.assert_called_once()
        assert not driver.available

    def test_context_manager(self, imu_config, mock_smbus):
        with ImuDriver(imu_config) as driver:
            assert driver.available
        assert not driver.available

    def test_read_sample_returns_imu_sample(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        try:
            sample = driver.read_sample()
            assert isinstance(sample, ImuSample)
            assert len(sample.accel) == 3
            assert len(sample.gyro) == 3
            assert len(sample.orientation) == 4
        finally:
            driver.stop()

    def test_read_sample_with_mag_disabled(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        try:
            driver.enable_magnetometer(False)
            sample = driver.read_sample()
            assert sample.mag is None
        finally:
            driver.stop()

    def test_enable_magnetometer_toggle(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        try:
            # imu_config has use_magnetometer=False, so _init_ak8963() never ran
            # during start() and _mag_present is still False; simulate a chip
            # that was successfully initialised so enable_magnetometer(True)
            # below isn't declined.
            driver._mag_present = True
            driver.enable_magnetometer(False)
            assert not driver._mag_enabled
            driver.enable_magnetometer(True)
            assert driver._mag_enabled
        finally:
            driver.stop()

    def test_ring_buffer_stores_samples(self, imu_config, mock_smbus):
        # Deliberately not started (no thread spawned): wire up availability
        # by hand so read_sample() has exclusive ownership of the ring buffer
        # and the count is exact, not "at least".
        driver = ImuDriver(imu_config)
        driver._available = True
        driver._bus = mock_smbus
        for _ in range(5):
            driver.read_sample()
        assert len(driver._ring_buffer) == 5

    def test_get_sample_at_empty(self, imu_config, mock_smbus):
        # Deliberately not started: get_sample_at only needs the ring buffer,
        # which is empty until something (a manual read or the sampling
        # thread) populates it — starting the thread here would race it.
        driver = ImuDriver(imu_config)
        assert driver.get_sample_at(0.0) is None

    def test_get_sample_at_finds_closest(self, imu_config, mock_smbus):
        # Deliberately not started (see test_get_sample_at_empty): this test
        # seeds the ring buffer directly and must own it exclusively.
        driver = ImuDriver(imu_config)

        # Manually add samples with known timestamps
        for t in [1.0, 2.0, 3.0, 4.0, 5.0]:
            driver._ring_buffer.append(
                ImuSample(
                    timestamp=t,
                    accel=(0, 0, 9.81),
                    gyro=(0, 0, 0),
                    mag=None,
                    orientation=(1, 0, 0, 0),
                )
            )

        closest = driver.get_sample_at(3.2)
        assert closest is not None
        assert closest.timestamp == 3.0

    def test_start_i2c_error_marks_unavailable(self, imu_config):
        mock_bus = MagicMock()
        mock_bus.write_byte_data.side_effect = OSError("I2C error")
        with (
            patch("rover.imu._I2C_AVAILABLE", True),
            patch("rover.imu.SMBus", return_value=mock_bus),
            patch("rover.imu.time"),
        ):
            driver = ImuDriver(imu_config)
            driver.start()
            assert not driver.available

    def test_ak8963_not_found_disables_mag(self, imu_config, mock_smbus):
        # First calls are for MPU init (WHO_AM_I etc.), last one for AK8963
        call_count = [0]

        def read_byte_side_effect(addr, reg):
            call_count[0] += 1
            if addr == 0x0C:
                raise OSError("AK8963 not found")
            return 0x71  # MPU-9250 WHO_AM_I

        mock_smbus.read_byte_data.side_effect = read_byte_side_effect

        driver = ImuDriver(imu_config)
        driver.start()
        try:
            assert driver.available
            assert not driver._mag_enabled
        finally:
            driver.stop()


class TestReadMag:
    def test_read_mag_short_read_returns_none(self, imu_config):
        driver = ImuDriver(imu_config)
        driver._bus = MagicMock()
        driver._bus.read_i2c_block_data.return_value = [0] * 6  # too short (need 7)
        assert driver._read_mag() is None

    def test_read_mag_maps_axes_to_body_frame(self, imu_config):
        """Chip frame (mx, my, mz) must come back as body frame
        (my, mx, -mz) per the MPU-9250 datasheet's magnetometer orientation
        figure."""
        driver = ImuDriver(imu_config)
        driver._bus = MagicMock()
        raw = list(struct.pack("<3h", 100, 200, 300)) + [0]  # ST2 byte, no overflow
        driver._bus.read_i2c_block_data.return_value = raw
        result = driver._read_mag()
        s = _MAG_SCALE_16BIT
        assert result == pytest.approx((200 * s, 100 * s, -300 * s))


# ---------------------------------------------------------------------------
# ImuDriver sampling thread tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_smbus_realtime():
    """Like mock_smbus but leaves rover.imu.time entirely REAL, so the sampling
    thread can pace itself with monotonic() and the test's own real-time waits
    (`_time.sleep`) actually elapse.

    Deliberately does NOT patch `rover.imu.time.sleep`: `rover.imu.time` is the
    same singleton module object as this test file's own `time` (imported here
    as `_time`) — `import time` always returns the one cached `sys.modules`
    entry. Patching `.sleep` on it (as an early draft of this fixture did) does
    not scope to `rover.imu`; it silently neuters every `_time.sleep(...)` call
    in the tests below too, so `test_thread_samples_at_configured_rate`'s
    "sleep 0.5s then drain" collapsed to "drain almost immediately," capturing
    ~1 sample instead of ~100 — measured, not assumed. Leaving `time` real costs
    the ~0.22 s of real `_init_mpu9250`/`_init_ak8963` sleeps per `start()`,
    which is cheap next to the real waits these tests need anyway.
    """
    mock_bus = MagicMock()
    mock_bus.read_byte_data.return_value = 0x71
    mock_bus.read_i2c_block_data.return_value = [0] * 14
    with (
        patch("rover.imu._I2C_AVAILABLE", True),
        patch("rover.imu.SMBus", MagicMock(return_value=mock_bus)),
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
        # 200 Hz × 0.5 s = 100 nominal; accept a loaded CI box (a Windows host's
        # ~15.6 ms time.monotonic() resolution on Python <=3.12 can push the
        # floor much lower than a Linux CI box would).
        assert 10 <= len(batch) <= 130, len(batch)
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
        assert seen and max(seen) < 0.1, (
            "dt must come from monotonic(), not a frozen/jumping wall clock"
        )

    def test_read_one_dt_bookkeeping_is_atomic(self, imu_config, mock_smbus_realtime, monkeypatch):
        """Finding 1: `read_sample()` from the test thread racing the sampling
        thread must never observe a stale `_last_mono` (negative/duplicated
        dt) or a filter update corrupted by interleaving — both are only
        prevented by `_bus_lock` covering the dt bookkeeping and the
        `MadgwickFilter.update()` call, not just the raw bus read."""
        drv = ImuDriver(imu_config)
        seen: list[float] = []
        real_update = drv._filter.update

        def spy(gx, gy, gz, ax, ay, az, dt, *mag):
            seen.append(dt)
            return real_update(gx, gy, gz, ax, ay, az, dt, *mag)

        monkeypatch.setattr(drv._filter, "update", spy)
        drv.start()
        start_mono = _time.monotonic()
        try:
            for _ in range(50):
                drv.read_sample()
        finally:
            drv.stop()
        elapsed_monotonic = _time.monotonic() - start_mono
        assert seen
        # >= 0, not > 0: on Python <=3.12 Windows, time.monotonic()'s ~15.6 ms
        # resolution can return the SAME value on two back-to-back calls, so a
        # strict > 0 is not guaranteed even though the bookkeeping is correct.
        assert all(dt >= 0 for dt in seen), seen
        # The sum of every reported dt cannot exceed the real wall-clock time
        # the loop actually took (plus a small margin) — that would mean dt
        # bookkeeping double-counted an interval.
        assert sum(seen) <= elapsed_monotonic + 0.05

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

    def test_sample_thread_stops_on_struct_error(self, imu_config, mock_smbus_realtime):
        """Finding 2: a short/malformed I2C read raises struct.error, not
        OSError — the thread must survive it the same way (count, shut down
        after the threshold, never crash silently while `available` stays
        True)."""
        drv = ImuDriver(imu_config)
        drv.start()
        mock_smbus_realtime.read_i2c_block_data.return_value = [0] * 3  # too short
        deadline = _time.monotonic() + 3.0
        while drv.available and _time.monotonic() < deadline:
            _time.sleep(0.01)
        try:
            assert drv.available is False
            assert drv._thread is None or not drv._thread.is_alive()
        finally:
            drv.stop()

    def test_sample_thread_marks_unavailable_on_unexpected_exception(
        self, imu_config, mock_smbus_realtime
    ):
        """An exception type neither the OSError/struct.error branch nor the
        error-threshold logic anticipates must still leave `available` False —
        the try/finally guard around _sample_loop's body is the only thing
        that can catch a case like this."""
        drv = ImuDriver(imu_config)
        drv.start()
        mock_smbus_realtime.read_i2c_block_data.side_effect = RuntimeError("unexpected failure")
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
        # imu_config has use_magnetometer=False, so _init_ak8963() never ran;
        # simulate a successfully-initialised chip so enable_magnetometer(True)
        # below is honoured instead of quietly declined.
        drv._mag_present = True
        try:
            drv.enable_magnetometer(False)
            drv.drain()
            batch = _poll_drain(drv)
            assert batch and all(s.mag is None for s in batch)
            drv.enable_magnetometer(True)
            drv.drain()
            batch = _poll_drain(drv)
            assert batch and any(s.mag is not None for s in batch)
        finally:
            drv.stop()

    def test_stop_joins_thread(self, imu_config, mock_smbus_realtime):
        drv = ImuDriver(imu_config)
        drv.start()
        t = drv._thread
        drv.stop()
        assert t is not None and not t.is_alive()
