"""
MPU-9250 IMU polling and Madgwick sensor fusion.

Reads accelerometer, gyroscope, and (optionally) magnetometer data
via I2C, then runs a Madgwick filter to produce quaternion orientation.

The magnetometer is disabled during motor operation (D-013) to avoid
stepper EMI corruption.

Outputs quaternion orientation at fusion_output_hz (default 100 Hz).
IMU samples are stored in a ring buffer for timestamp correlation
with LiDAR scans via slerp interpolation (D-014).

Decision references:
    D-011  MPU-9250 as primary IMU
    D-012  Madgwick filter
    D-013  Magnetometer disabled during motor operation
    D-014  IMU-LiDAR timestamp correlation via slerp

Dependencies:
    smbus2
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rover.config import ImuConfig

logger = logging.getLogger(__name__)


@dataclass
class ImuSample:
    """Single IMU measurement with fused orientation."""
    timestamp: float                        # Unix timestamp
    accel: tuple[float, float, float]       # m/s², (x, y, z)
    gyro: tuple[float, float, float]        # rad/s, (x, y, z)
    mag: tuple[float, float, float] | None  # µT, (x, y, z) or None if disabled
    orientation: tuple[float, float, float, float]  # quaternion [w, x, y, z]


class ImuDriver:
    """MPU-9250 IMU driver with Madgwick fusion.

    Args:
        config: ImuConfig section from rover config.
    """

    # MPU-9250 WHO_AM_I register values
    WHO_AM_I_MPU9250 = 0x71
    WHO_AM_I_MPU9255 = 0x73

    def __init__(self, config: ImuConfig) -> None:
        self._config = config
        self._running = False
        self._mag_enabled = config.use_magnetometer
        logger.info(
            "ImuDriver initialized (bus=%d, addr=%s, mag=%s)",
            config.bus, hex(config.address), config.use_magnetometer,
        )

    def start(self) -> None:
        """Open I2C bus, verify WHO_AM_I, configure sensor, begin polling."""
        raise NotImplementedError("ImuDriver.start() not yet implemented")

    def stop(self) -> None:
        """Stop polling and close I2C bus."""
        raise NotImplementedError("ImuDriver.stop() not yet implemented")

    def read_sample(self) -> ImuSample:
        """Read latest fused IMU sample."""
        raise NotImplementedError("ImuDriver.read_sample() not yet implemented")

    def enable_magnetometer(self, enable: bool) -> None:
        """Enable or disable magnetometer readings (D-013)."""
        self._mag_enabled = enable
        logger.info("Magnetometer %s", "enabled" if enable else "disabled")
