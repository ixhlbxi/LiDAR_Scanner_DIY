"""
LD19 LiDAR acquisition and packet parsing.

Handles the LD19 binary serial protocol:
  - Packet header: 0x54 0x2C
  - 12 measurement points per packet (distance + intensity)
  - CRC8 verification
  - Angle interpolation between FSA and LSA
  - Ring buffer for incoming bytes

Serial interface: /dev/ttyUSB0 at 230400 baud (configurable).

Decision references:
    D-005  LD19 LiDAR selection
    D-014  Timestamp sync via ring buffer + slerp

Dependencies:
    pyserial
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rover.config import LidarConfig

logger = logging.getLogger(__name__)


@dataclass
class LidarPoint:
    """Single LiDAR measurement point."""
    angle: float       # degrees, 0-360
    distance: float    # meters
    intensity: int     # 0-255


class LidarScanner:
    """LD19 LiDAR scanner driver.

    Acquires 2D scan data from the LD19 via serial.
    Each scan contains ~720 points (360° at ~0.5° resolution).

    Args:
        config: LidarConfig section from rover config.
    """

    def __init__(self, config: LidarConfig) -> None:
        self._config = config
        self._running = False
        logger.info("LidarScanner initialized (port=%s, baud=%d)", config.port, config.baud)

    def start(self) -> None:
        """Open serial port and begin acquisition."""
        raise NotImplementedError("LidarScanner.start() not yet implemented")

    def stop(self) -> None:
        """Stop acquisition and close serial port."""
        raise NotImplementedError("LidarScanner.stop() not yet implemented")

    def read_scan(self) -> list[LidarPoint]:
        """Read one complete 360° scan. Blocks until scan is ready."""
        raise NotImplementedError("LidarScanner.read_scan() not yet implemented")
