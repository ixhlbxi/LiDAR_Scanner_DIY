"""Unit tests for rover.imu — runs anywhere, no hardware required."""

import math
from unittest.mock import MagicMock, patch, call

import pytest

from rover.config import ImuConfig
from rover.imu import ImuDriver, ImuSample, MadgwickFilter


@pytest.fixture
def imu_config():
    return ImuConfig(
        enabled=True,
        bus=1,
        address=0x68,
        sample_rate_hz=200,
        fusion_output_hz=100,
        use_magnetometer=True,
        fusion_beta=0.1,
    )


@pytest.fixture
def disabled_config():
    return ImuConfig(
        enabled=False,
        bus=1,
        address=0x68,
        sample_rate_hz=200,
        fusion_output_hz=100,
        use_magnetometer=True,
        fusion_beta=0.1,
    )


@pytest.fixture
def mock_smbus():
    """Patch smbus2 and availability flag for off-Pi testing."""
    mock_bus = MagicMock()
    # WHO_AM_I returns MPU-9250
    mock_bus.read_byte_data.return_value = 0x71
    # Accel/gyro: 14 bytes of zeros (at rest, ~1g on Z after scaling)
    mock_bus.read_i2c_block_data.return_value = [0] * 14

    mock_smbus_class = MagicMock(return_value=mock_bus)
    with (
        patch("rover.imu._I2C_AVAILABLE", True),
        patch("rover.imu.SMBus", mock_smbus_class),
        patch("rover.imu.time"),
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
        assert driver.available
        assert driver.identity == "MPU-9250"

    def test_start_mpu9255(self, imu_config, mock_smbus):
        mock_smbus.read_byte_data.return_value = 0x73
        driver = ImuDriver(imu_config)
        driver.start()
        assert driver.identity == "MPU-9255"

    def test_start_unknown_who_am_i(self, imu_config, mock_smbus):
        mock_smbus.read_byte_data.return_value = 0x00
        driver = ImuDriver(imu_config)
        driver.start()
        assert driver.available  # Still usable
        assert "Unknown" in driver.identity

    def test_double_start_ignored(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        driver.start()  # Should not raise
        assert driver.available

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
        sample = driver.read_sample()
        assert isinstance(sample, ImuSample)
        assert len(sample.accel) == 3
        assert len(sample.gyro) == 3
        assert len(sample.orientation) == 4

    def test_read_sample_with_mag_disabled(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        driver.enable_magnetometer(False)
        sample = driver.read_sample()
        assert sample.mag is None

    def test_enable_magnetometer_toggle(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        driver.enable_magnetometer(False)
        assert not driver._mag_enabled
        driver.enable_magnetometer(True)
        assert driver._mag_enabled

    def test_ring_buffer_stores_samples(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        for _ in range(5):
            driver.read_sample()
        assert len(driver._ring_buffer) == 5

    def test_get_sample_at_empty(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()
        assert driver.get_sample_at(0.0) is None

    def test_get_sample_at_finds_closest(self, imu_config, mock_smbus):
        driver = ImuDriver(imu_config)
        driver.start()

        # Manually add samples with known timestamps
        for t in [1.0, 2.0, 3.0, 4.0, 5.0]:
            driver._ring_buffer.append(ImuSample(
                timestamp=t,
                accel=(0, 0, 9.81),
                gyro=(0, 0, 0),
                mag=None,
                orientation=(1, 0, 0, 0),
            ))

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
        assert driver.available
        assert not driver._mag_enabled
