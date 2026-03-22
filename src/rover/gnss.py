"""
ZED-F9P GNSS receiver parsing (NMEA and UBX protocols).

Reads position, fix status, satellite info, and RTK correction age
from the ZED-F9P via USB-serial. RTCM corrections are NOT routed
through this module — they flow ESP32 → F9P UART2 directly (D-006).

This module only reads the F9P output for logging and telemetry.

Decision references:
    D-004  ZED-F9P selection
    D-006  RTCM routing bypasses Pi
    D-007  RTCM constellation profiles

Dependencies:
    pyserial, pyubx2, pynmeagps
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rover.config import GnssConfig

logger = logging.getLogger(__name__)


@dataclass
class GnssFix:
    """Single GNSS position fix."""
    timestamp: float    # Unix timestamp (GNSS time if available)
    fix_type: int       # 0=NONE, 1=2D, 2=3D, 3=DGPS, 4=FLOAT, 5=FIX
    lat: float          # Decimal degrees (WGS84)
    lon: float          # Decimal degrees (WGS84)
    alt: float          # Meters (ellipsoidal)
    hdop: float
    vdop: float
    sat_count: int
    rtk_age: float      # Age of RTK corrections in seconds


class GnssReceiver:
    """ZED-F9P GNSS receiver driver.

    Args:
        config: GnssConfig section from rover config.
    """

    def __init__(self, config: GnssConfig) -> None:
        self._config = config
        self._running = False
        logger.info("GnssReceiver initialized (port=%s, baud=%d)", config.port, config.baud)

    def start(self) -> None:
        """Open serial port, verify F9P identity (UBX-MON-VER), begin parsing."""
        raise NotImplementedError("GnssReceiver.start() not yet implemented")

    def stop(self) -> None:
        """Stop parsing and close serial port."""
        raise NotImplementedError("GnssReceiver.stop() not yet implemented")

    def read_fix(self) -> GnssFix:
        """Read latest GNSS fix. Blocks until fix is available."""
        raise NotImplementedError("GnssReceiver.read_fix() not yet implemented")
