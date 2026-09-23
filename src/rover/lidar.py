"""
LD19 LiDAR acquisition and packet parsing.

Handles the LD19 binary serial protocol:
  - Packet header: 0x54
  - 12 measurement points per packet, 47 bytes total
  - CRC8 verification (polynomial 0x4D)
  - Angle interpolation between start and end angles
  - Continuous packet stream → assembled 360° scans

Serial interface: /dev/ttyUSB0 at 230400 baud (configurable).

Decision references:
    DEC-014  Timestamp sync via ring buffer + slerp

Dependencies:
    pyserial

Changelog:
    0.1.0  2026-03-22  Stub
    0.2.0  2026-03-22  Full implementation
    0.11.0  2026-09  Seam carry-over, stale discard, LidarScan with LD19 timestamps, one-byte resync
    0.11.1  2026-09-23  Shared _is_wrap() helper between the discard-skip and
                        assembly loops; read_scan() docstring notes the
                        shared timeout budget
"""

from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass

from rover.config import LidarConfig

logger = logging.getLogger(__name__)

# LD19 protocol constants
PACKET_HEADER = 0x54
PACKET_LENGTH = 47
POINTS_PER_PACKET = 12

# CRC8 lookup table for LD19 (polynomial 0x4D, LDRobot standard)
# fmt: off
_CRC_TABLE = [
    0x00, 0x4D, 0x9A, 0xD7, 0x79, 0x34, 0xE3, 0xAE,
    0xF2, 0xBF, 0x68, 0x25, 0x8B, 0xC6, 0x11, 0x5C,
    0xA9, 0xE4, 0x33, 0x7E, 0xD0, 0x9D, 0x4A, 0x07,
    0x5B, 0x16, 0xC1, 0x8C, 0x22, 0x6F, 0xB8, 0xF5,
    0x1F, 0x52, 0x85, 0xC8, 0x66, 0x2B, 0xFC, 0xB1,
    0xED, 0xA0, 0x77, 0x3A, 0x94, 0xD9, 0x0E, 0x43,
    0xB6, 0xFB, 0x2C, 0x61, 0xCF, 0x82, 0x55, 0x18,
    0x44, 0x09, 0xDE, 0x93, 0x3D, 0x70, 0xA7, 0xEA,
    0x3E, 0x73, 0xA4, 0xE9, 0x47, 0x0A, 0xDD, 0x90,
    0xCC, 0x81, 0x56, 0x1B, 0xB5, 0xF8, 0x2F, 0x62,
    0x97, 0xDA, 0x0D, 0x40, 0xEE, 0xA3, 0x74, 0x39,
    0x65, 0x28, 0xFF, 0xB2, 0x1C, 0x51, 0x86, 0xCB,
    0x21, 0x6C, 0xBB, 0xF6, 0x58, 0x15, 0xC2, 0x8F,
    0xD3, 0x9E, 0x49, 0x04, 0xAA, 0xE7, 0x30, 0x7D,
    0x88, 0xC5, 0x12, 0x5F, 0xF1, 0xBC, 0x6B, 0x26,
    0x7A, 0x37, 0xE0, 0xAD, 0x03, 0x4E, 0x99, 0xD4,
    0x7C, 0x31, 0xE6, 0xAB, 0x05, 0x48, 0x9F, 0xD2,
    0x8E, 0xC3, 0x14, 0x59, 0xF7, 0xBA, 0x6D, 0x20,
    0xD5, 0x98, 0x4F, 0x02, 0xAC, 0xE1, 0x36, 0x7B,
    0x27, 0x6A, 0xBD, 0xF0, 0x5E, 0x13, 0xC4, 0x89,
    0x63, 0x2E, 0xF9, 0xB4, 0x1A, 0x57, 0x80, 0xCD,
    0x91, 0xDC, 0x0B, 0x46, 0xE8, 0xA5, 0x72, 0x3F,
    0xCA, 0x87, 0x50, 0x1D, 0xB3, 0xFE, 0x29, 0x64,
    0x38, 0x75, 0xA2, 0xEF, 0x41, 0x0C, 0xDB, 0x96,
    0x42, 0x0F, 0xD8, 0x95, 0x3B, 0x76, 0xA1, 0xEC,
    0xB0, 0xFD, 0x2A, 0x67, 0xC9, 0x84, 0x53, 0x1E,
    0xEB, 0xA6, 0x71, 0x3C, 0x92, 0xDF, 0x08, 0x45,
    0x19, 0x54, 0x83, 0xCE, 0x60, 0x2D, 0xFA, 0xB7,
    0x5D, 0x10, 0xC7, 0x8A, 0x24, 0x69, 0xBE, 0xF3,
    0xAF, 0xE2, 0x35, 0x78, 0xD6, 0x9B, 0x4C, 0x01,
    0xF4, 0xB9, 0x6E, 0x23, 0x8D, 0xC0, 0x17, 0x5A,
    0x06, 0x4B, 0x9C, 0xD1, 0x7F, 0x32, 0xE5, 0xA8,
]
# fmt: on

try:
    import serial

    _SERIAL_AVAILABLE = True
except ImportError:
    serial = None  # type: ignore[assignment]
    _SERIAL_AVAILABLE = False

PACKET_VERLEN = 0x2C  # byte 1: (packet type 2 << 5) | 12 points
# Header(1) VerLen(1) speed(H) start(H) 12x(dist H, intensity B) end(H) timestamp(H) — 46 bytes, CRC is byte 46
_PACKET_STRUCT = struct.Struct("<xxHH" + "HB" * POINTS_PER_PACKET + "HH")
assert _PACKET_STRUCT.size == PACKET_LENGTH - 1


def crc8(data: bytes) -> int:
    """Compute CRC8 over data using the LD19 lookup table."""
    crc = 0
    for b in data:
        crc = _CRC_TABLE[(crc ^ b) & 0xFF]
    return crc


def parse_packet(packet: bytes) -> dict | None:
    """Parse a 47-byte LD19 packet.

    Returns:
        Dict with speed, angles, timestamp, and 12 raw points, or None
        if the packet is malformed or fails CRC.
    """
    if len(packet) != PACKET_LENGTH or packet[0] != PACKET_HEADER:
        return None
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


def interpolate_angles(start: float, end: float, count: int) -> list[float]:
    """Linearly interpolate angles for each point in a packet.

    Handles the 360→0 wraparound case.
    """
    span = end - start
    if span < 0:
        span += 360.0
    step = span / max(count - 1, 1)
    return [(start + i * step) % 360.0 for i in range(count)]


@dataclass
class LidarPoint:
    """Single LiDAR measurement point."""

    angle: float  # degrees, 0-360
    distance: float  # meters
    intensity: int  # 0-255


@dataclass
class LidarScan:
    """One full LD19 revolution."""

    points: list[LidarPoint]
    lidar_ms_start: int  # LD19 timestamp of the first packet (ms, wraps at 30000)
    lidar_ms_end: int  # LD19 timestamp of the last packet


_SCAN_TIMEOUT_SEC = 5.0
_WRAP_THRESHOLD_DEG = 10.0


def _is_wrap(start: float, prev: float | None) -> bool:
    """True when `start` reveals a 360deg->0deg wrap relative to `prev` (the
    previous packet's start_angle). `prev is None` means there is no
    previous packet yet, so no wrap is possible. Shared by both the
    discard_stale skip-to-wrap loop and the revolution-assembly loop in
    read_scan() so the two can't drift onto different wrap definitions."""
    return prev is not None and start < prev - _WRAP_THRESHOLD_DEG


class LidarScanner:
    """LD19 LiDAR scanner driver.

    Acquires 2D scan data from the LD19 via serial. The LD19 continuously
    streams packets; this class parses them and assembles complete 360° scans.

    Args:
        config: LidarConfig section from rover config.
    """

    def __init__(self, config: LidarConfig) -> None:
        self._config = config
        self._available = False
        self._started = False
        self._serial = None
        self._buf = bytearray()
        self._carry: dict | None = None

        if not config.enabled:
            logger.info("LiDAR disabled by config")
            return

        if not _SERIAL_AVAILABLE:
            logger.warning("LiDAR enabled but pyserial not available — running without hardware")
            return

        logger.info(
            "LidarScanner initialized (port=%s, baud=%d)",
            config.port,
            config.baud,
        )

    @property
    def available(self) -> bool:
        """Whether the LiDAR hardware is initialized and usable."""
        return self._available

    def start(self) -> None:
        """Open serial port and begin acquisition."""
        if not self._config.enabled:
            logger.info("LiDAR disabled, skipping start")
            return

        if not _SERIAL_AVAILABLE:
            logger.warning("Cannot start LiDAR: pyserial unavailable")
            return

        if self._started:
            logger.warning("LiDAR already started")
            return

        try:
            self._serial = serial.Serial(
                self._config.port,
                self._config.baud,
                timeout=1,
            )
        except Exception:
            logger.warning("Failed to open LiDAR serial port", exc_info=True)
            self._available = False
            return

        self._buf.clear()
        self._carry = None
        self._started = True
        self._available = True
        logger.info("LiDAR started on %s", self._config.port)

    def stop(self) -> None:
        """Stop acquisition and close serial port."""
        if not self._started:
            return

        try:
            if self._serial is not None:
                self._serial.close()
        except Exception:
            pass

        self._serial = None
        self._buf.clear()
        self._carry = None
        self._started = False
        self._available = False
        logger.info("LiDAR stopped")

    def read_packet(self) -> dict | None:
        """Read and parse the next valid LD19 packet from the serial stream.

        Returns:
            Parsed packet dict, or None if no complete packet is available.
        """
        if not self._available or self._serial is None:
            return None

        # Read available bytes
        waiting = self._serial.in_waiting or 1
        data = self._serial.read(waiting)
        if data:
            self._buf.extend(data)

        # Try to extract a packet
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

        A single `_SCAN_TIMEOUT_SEC` deadline, set once at the top of this call,
        covers BOTH phases when discard_stale is true — the skip-to-wrap discard
        loop and the revolution-assembly loop share it rather than each getting
        their own budget. A slow or stalled stream can spend the whole deadline
        discarding and leave nothing for the actual scan; that surfaces as the
        same TimeoutError either way, not a distinguishable failure mode.

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
                if _is_wrap(pkt["start_angle"], prev):
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
            if _is_wrap(pkt["start_angle"], prev):
                self._carry = pkt  # opens the next revolution
                return LidarScan(points=points, lidar_ms_start=ms_start, lidar_ms_end=ms_end)
            prev = pkt["start_angle"]
            points.extend(self._packet_points(pkt))
            ms_end = pkt["timestamp_ms"]

    def __enter__(self) -> LidarScanner:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
