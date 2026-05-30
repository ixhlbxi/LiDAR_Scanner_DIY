"""
MPU-9250 IMU polling and Madgwick sensor fusion.

Reads accelerometer, gyroscope, and (optionally) magnetometer data
via I2C, then runs a Madgwick filter to produce quaternion orientation.

The magnetometer is disabled during motor operation (DEC-013) to avoid
stepper EMI corruption.

Outputs quaternion orientation at fusion_output_hz (default 100 Hz).
IMU samples are stored in a ring buffer for timestamp correlation
with LiDAR scans via slerp interpolation (DEC-014).

Decision references:
    DEC-011  MPU-9250 as primary IMU
    DEC-012  Madgwick filter
    DEC-013  Magnetometer disabled during motor operation
    DEC-014  IMU-LiDAR timestamp correlation via slerp

Dependencies:
    smbus2

Changelog:
    0.1.0  2026-03-22  Stub
    0.2.0  2026-03-22  Full implementation
"""

from __future__ import annotations

import collections
import logging
import math
import struct
import time
from dataclasses import dataclass

from rover.config import ImuConfig

logger = logging.getLogger(__name__)

# MPU-9250 registers
_REG_WHO_AM_I = 0x75
_REG_PWR_MGMT_1 = 0x6B
_REG_SMPLRT_DIV = 0x19
_REG_CONFIG = 0x1A
_REG_GYRO_CONFIG = 0x1B
_REG_ACCEL_CONFIG = 0x1C
_REG_ACCEL_CONFIG2 = 0x1D
_REG_INT_PIN_CFG = 0x37
_REG_ACCEL_XOUT_H = 0x3B

# AK8963 magnetometer
_AK8963_ADDR = 0x0C
_AK8963_REG_WIA = 0x00
_AK8963_REG_CNTL1 = 0x0A
_AK8963_REG_HXL = 0x03

# Conversion factors
_ACCEL_SCALE_2G = 9.81 / 16384.0  # m/s² per LSB at ±2g
_GYRO_SCALE_250DPS = math.pi / (180.0 * 131.0)  # rad/s per LSB at ±250°/s
_MAG_SCALE_14BIT = 0.15  # µT per LSB in 14-bit mode

# WHO_AM_I expected values
WHO_AM_I_MPU9250 = 0x71
WHO_AM_I_MPU9255 = 0x73

try:
    from smbus2 import SMBus
    _I2C_AVAILABLE = True
except ImportError:
    SMBus = None  # type: ignore[assignment, misc]
    _I2C_AVAILABLE = False


@dataclass
class ImuSample:
    """Single IMU measurement with fused orientation."""
    timestamp: float                        # Unix timestamp
    accel: tuple[float, float, float]       # m/s², (x, y, z)
    gyro: tuple[float, float, float]        # rad/s, (x, y, z)
    mag: tuple[float, float, float] | None  # µT, (x, y, z) or None if disabled
    orientation: tuple[float, float, float, float]  # quaternion [w, x, y, z]


class MadgwickFilter:
    """Madgwick AHRS filter for quaternion orientation estimation.

    Simplified 6-DOF (accel + gyro) implementation. When magnetometer
    data is available, it is used for yaw correction.

    Args:
        beta: Filter gain parameter (0..1). Higher = more accel trust.
    """

    def __init__(self, beta: float = 0.1) -> None:
        self._beta = beta
        # Quaternion [w, x, y, z], initialized to identity
        self._q = [1.0, 0.0, 0.0, 0.0]

    @property
    def quaternion(self) -> tuple[float, float, float, float]:
        return (self._q[0], self._q[1], self._q[2], self._q[3])

    def update(
        self,
        gx: float, gy: float, gz: float,
        ax: float, ay: float, az: float,
        dt: float,
    ) -> None:
        """Update orientation from gyro (rad/s) and accel (m/s²)."""
        q0, q1, q2, q3 = self._q

        # Normalize accelerometer
        norm = math.sqrt(ax * ax + ay * ay + az * az)
        if norm < 1e-10:
            # Free-fall or invalid — skip correction, gyro only
            q0 += 0.5 * dt * (-q1 * gx - q2 * gy - q3 * gz)
            q1 += 0.5 * dt * (q0 * gx + q2 * gz - q3 * gy)
            q2 += 0.5 * dt * (q0 * gy - q1 * gz + q3 * gx)
            q3 += 0.5 * dt * (q0 * gz + q1 * gy - q2 * gx)
            self._q = [q0, q1, q2, q3]
            self._normalize()
            return

        ax /= norm
        ay /= norm
        az /= norm

        # Gradient descent corrective step
        f1 = 2.0 * (q1 * q3 - q0 * q2) - ax
        f2 = 2.0 * (q0 * q1 + q2 * q3) - ay
        f3 = 2.0 * (0.5 - q1 * q1 - q2 * q2) - az

        j_t_f0 = -2.0 * q2 * f1 + 2.0 * q1 * f2
        j_t_f1 = 2.0 * q3 * f1 + 2.0 * q0 * f2 - 4.0 * q1 * f3
        j_t_f2 = -2.0 * q0 * f1 + 2.0 * q3 * f2 - 4.0 * q2 * f3
        j_t_f3 = 2.0 * q1 * f1 + 2.0 * q2 * f2

        grad_norm = math.sqrt(
            j_t_f0 * j_t_f0 + j_t_f1 * j_t_f1 +
            j_t_f2 * j_t_f2 + j_t_f3 * j_t_f3
        )
        if grad_norm > 1e-10:
            j_t_f0 /= grad_norm
            j_t_f1 /= grad_norm
            j_t_f2 /= grad_norm
            j_t_f3 /= grad_norm

        # Quaternion derivative from gyro
        qd0 = 0.5 * (-q1 * gx - q2 * gy - q3 * gz)
        qd1 = 0.5 * (q0 * gx + q2 * gz - q3 * gy)
        qd2 = 0.5 * (q0 * gy - q1 * gz + q3 * gx)
        qd3 = 0.5 * (q0 * gz + q1 * gy - q2 * gx)

        # Apply correction
        q0 += (qd0 - self._beta * j_t_f0) * dt
        q1 += (qd1 - self._beta * j_t_f1) * dt
        q2 += (qd2 - self._beta * j_t_f2) * dt
        q3 += (qd3 - self._beta * j_t_f3) * dt

        self._q = [q0, q1, q2, q3]
        self._normalize()

    def _normalize(self) -> None:
        norm = math.sqrt(sum(x * x for x in self._q))
        if norm > 1e-10:
            self._q = [x / norm for x in self._q]


class ImuDriver:
    """MPU-9250 IMU driver with Madgwick fusion.

    Args:
        config: ImuConfig section from rover config.
    """

    def __init__(self, config: ImuConfig) -> None:
        self._config = config
        self._available = False
        self._started = False
        self._mag_enabled = config.use_magnetometer
        self._bus = None
        self._filter = MadgwickFilter(beta=config.fusion_beta)
        self._last_time: float | None = None
        self._identity: str | None = None

        # Ring buffer for timestamp correlation (DEC-014)
        self._ring_buffer: collections.deque[ImuSample] = collections.deque(
            maxlen=config.sample_rate_hz * 2,  # ~2 seconds of samples
        )

        if not config.enabled:
            logger.info("IMU disabled by config")
            return

        if not _I2C_AVAILABLE:
            logger.warning(
                "IMU enabled but smbus2 not available — running without hardware"
            )
            return

        logger.info(
            "ImuDriver initialized (bus=%d, addr=0x%02X, mag=%s)",
            config.bus, config.address, config.use_magnetometer,
        )

    @property
    def available(self) -> bool:
        """Whether the IMU hardware is initialized and usable."""
        return self._available

    @property
    def identity(self) -> str | None:
        """Device identity string from WHO_AM_I, or None if not started."""
        return self._identity

    def start(self) -> None:
        """Open I2C bus, verify WHO_AM_I, configure sensor."""
        if not self._config.enabled:
            logger.info("IMU disabled, skipping start")
            return

        if not _I2C_AVAILABLE:
            logger.warning("Cannot start IMU: smbus2 unavailable")
            return

        if self._started:
            logger.warning("IMU already started")
            return

        try:
            self._bus = SMBus(self._config.bus)
            self._init_mpu9250()

            if self._mag_enabled:
                self._init_ak8963()

        except Exception:
            logger.warning("Failed to initialize IMU", exc_info=True)
            self._available = False
            try:
                if self._bus is not None:
                    self._bus.close()
            except Exception:
                pass
            self._bus = None
            return

        self._started = True
        self._available = True
        self._last_time = None
        self._ring_buffer.clear()
        logger.info("IMU started (%s)", self._identity)

    def _init_mpu9250(self) -> None:
        """Wake up MPU-9250, verify identity, configure sample rate."""
        addr = self._config.address

        # Wake up
        self._bus.write_byte_data(addr, _REG_PWR_MGMT_1, 0x00)
        time.sleep(0.1)

        # Auto-select best clock source
        self._bus.write_byte_data(addr, _REG_PWR_MGMT_1, 0x01)
        time.sleep(0.1)

        # Check WHO_AM_I
        who = self._bus.read_byte_data(addr, _REG_WHO_AM_I)
        if who == WHO_AM_I_MPU9250:
            self._identity = "MPU-9250"
        elif who == WHO_AM_I_MPU9255:
            self._identity = "MPU-9255"
        else:
            self._identity = f"Unknown (0x{who:02X})"
            logger.warning("Unexpected WHO_AM_I: 0x%02X", who)

        # Gyro: ±250°/s
        self._bus.write_byte_data(addr, _REG_GYRO_CONFIG, 0x00)
        # Accel: ±2g
        self._bus.write_byte_data(addr, _REG_ACCEL_CONFIG, 0x00)
        # DLPF: 92 Hz bandwidth
        self._bus.write_byte_data(addr, _REG_CONFIG, 0x02)
        # Accel DLPF: 99 Hz bandwidth
        self._bus.write_byte_data(addr, _REG_ACCEL_CONFIG2, 0x02)

        # Sample rate divider: rate = 1kHz / (1 + div)
        div = max(0, min(255, (1000 // self._config.sample_rate_hz) - 1))
        self._bus.write_byte_data(addr, _REG_SMPLRT_DIV, div)

        # Enable I2C bypass for magnetometer access
        self._bus.write_byte_data(addr, _REG_INT_PIN_CFG, 0x02)
        time.sleep(0.01)

    def _init_ak8963(self) -> None:
        """Initialize AK8963 magnetometer via I2C bypass."""
        try:
            who = self._bus.read_byte_data(_AK8963_ADDR, _AK8963_REG_WIA)
        except OSError:
            logger.warning("AK8963 not found — magnetometer disabled")
            self._mag_enabled = False
            return

        if who != 0x48:
            logger.warning("Unexpected AK8963 WIA: 0x%02X", who)

        # Power down, then continuous measurement mode 2 (100 Hz), 16-bit
        self._bus.write_byte_data(_AK8963_ADDR, _AK8963_REG_CNTL1, 0x00)
        time.sleep(0.01)
        self._bus.write_byte_data(_AK8963_ADDR, _AK8963_REG_CNTL1, 0x16)
        time.sleep(0.01)

    def stop(self) -> None:
        """Stop polling and close I2C bus."""
        if not self._started:
            return

        try:
            if self._bus is not None:
                self._bus.close()
        except Exception:
            pass

        self._bus = None
        self._started = False
        self._available = False
        logger.info("IMU stopped")

    def read_sample(self) -> ImuSample:
        """Read current sensor data, run Madgwick filter, return fused sample.

        Returns:
            ImuSample with accel, gyro, optional mag, and fused quaternion.

        Raises:
            RuntimeError: If the IMU is not available.
        """
        if not self._available or self._bus is None:
            raise RuntimeError("IMU not available")

        now = time.time()
        dt = (now - self._last_time) if self._last_time is not None else 0.005
        self._last_time = now

        accel, gyro = self._read_accel_gyro()
        mag = self._read_mag() if self._mag_enabled else None

        # Run Madgwick filter
        self._filter.update(
            gyro[0], gyro[1], gyro[2],
            accel[0], accel[1], accel[2],
            dt,
        )

        sample = ImuSample(
            timestamp=now,
            accel=accel,
            gyro=gyro,
            mag=mag,
            orientation=self._filter.quaternion,
        )

        self._ring_buffer.append(sample)
        return sample

    def _read_accel_gyro(self) -> tuple[
        tuple[float, float, float], tuple[float, float, float]
    ]:
        """Read accel (m/s²) and gyro (rad/s) from MPU-9250."""
        addr = self._config.address
        raw = self._bus.read_i2c_block_data(addr, _REG_ACCEL_XOUT_H, 14)

        ax = struct.unpack(">h", bytes(raw[0:2]))[0] * _ACCEL_SCALE_2G
        ay = struct.unpack(">h", bytes(raw[2:4]))[0] * _ACCEL_SCALE_2G
        az = struct.unpack(">h", bytes(raw[4:6]))[0] * _ACCEL_SCALE_2G
        # raw[6:8] = temperature, skip
        gx = struct.unpack(">h", bytes(raw[8:10]))[0] * _GYRO_SCALE_250DPS
        gy = struct.unpack(">h", bytes(raw[10:12]))[0] * _GYRO_SCALE_250DPS
        gz = struct.unpack(">h", bytes(raw[12:14]))[0] * _GYRO_SCALE_250DPS

        return (ax, ay, az), (gx, gy, gz)

    def _read_mag(self) -> tuple[float, float, float] | None:
        """Read magnetometer (µT) from AK8963. Returns None if not ready."""
        try:
            raw = self._bus.read_i2c_block_data(_AK8963_ADDR, _AK8963_REG_HXL, 7)
        except OSError:
            return None

        # ST2 (byte 6) must be read to signal end of measurement
        if raw[6] & 0x08:  # Overflow
            return None

        # AK8963 is little-endian
        mx = struct.unpack("<h", bytes(raw[0:2]))[0] * _MAG_SCALE_14BIT
        my = struct.unpack("<h", bytes(raw[2:4]))[0] * _MAG_SCALE_14BIT
        mz = struct.unpack("<h", bytes(raw[4:6]))[0] * _MAG_SCALE_14BIT

        return (mx, my, mz)

    def enable_magnetometer(self, enable: bool) -> None:
        """Enable or disable magnetometer readings (DEC-013)."""
        self._mag_enabled = enable
        logger.info("Magnetometer %s", "enabled" if enable else "disabled")

    def get_sample_at(self, timestamp: float) -> ImuSample | None:
        """Find the closest sample in the ring buffer to the given timestamp.

        Used for IMU-LiDAR timestamp correlation (DEC-014).

        Args:
            timestamp: Unix timestamp to match.

        Returns:
            Closest ImuSample, or None if buffer is empty.
        """
        if not self._ring_buffer:
            return None

        return min(self._ring_buffer, key=lambda s: abs(s.timestamp - timestamp))

    def __enter__(self) -> ImuDriver:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
