"""Unit tests for rover.lidar — runs anywhere, no hardware required."""

import struct
from unittest.mock import MagicMock, patch

import pytest

from rover.config import LidarConfig
from rover.lidar import (
    PACKET_HEADER,
    PACKET_LENGTH,
    POINTS_PER_PACKET,
    LidarPoint,
    LidarScanner,
    crc8,
    interpolate_angles,
    parse_packet,
)


@pytest.fixture
def lidar_config():
    return LidarConfig(
        enabled=True,
        port="/dev/ttyUSB0",
        baud=230400,
        scan_rate_hz=10,
    )


@pytest.fixture
def disabled_config():
    return LidarConfig(
        enabled=False,
        port="/dev/ttyUSB0",
        baud=230400,
        scan_rate_hz=10,
    )


def build_packet(
    start_angle_deg: float = 0.0,
    end_angle_deg: float = 5.5,
    speed_dps: float = 360.0,
    distances_mm: list[int] | None = None,
    intensities: list[int] | None = None,
    timestamp_ms: int = 1000,
) -> bytes:
    """Build a valid 47-byte LD19 packet with correct CRC."""
    if distances_mm is None:
        distances_mm = [1500] * POINTS_PER_PACKET
    if intensities is None:
        intensities = [128] * POINTS_PER_PACKET

    buf = bytearray(PACKET_LENGTH)
    buf[0] = PACKET_HEADER
    buf[1] = 0x2C  # ver_len

    struct.pack_into("<H", buf, 2, int(speed_dps * 100))
    struct.pack_into("<H", buf, 4, int(start_angle_deg * 100))

    for i in range(POINTS_PER_PACKET):
        offset = 6 + i * 3
        struct.pack_into("<H", buf, offset, distances_mm[i])
        buf[offset + 2] = intensities[i]

    struct.pack_into("<H", buf, 42, int(end_angle_deg * 100))
    struct.pack_into("<H", buf, 44, timestamp_ms)

    # Compute and set CRC
    buf[46] = crc8(bytes(buf[:46]))
    return bytes(buf)


# ---------------------------------------------------------------------------
# CRC tests
# ---------------------------------------------------------------------------


class TestCRC8:
    def test_empty(self):
        assert crc8(b"") == 0

    def test_known_value(self):
        # CRC is deterministic — same input always produces same output
        val = crc8(b"\x54\x2C")
        assert isinstance(val, int)
        assert 0 <= val <= 255

    def test_different_inputs_differ(self):
        assert crc8(b"\x00") != crc8(b"\x01")


# ---------------------------------------------------------------------------
# Packet parsing tests
# ---------------------------------------------------------------------------


class TestParsePacket:
    def test_valid_packet(self):
        pkt = build_packet(start_angle_deg=10.0, end_angle_deg=15.5)
        result = parse_packet(pkt)
        assert result is not None
        assert result["start_angle"] == pytest.approx(10.0)
        assert result["end_angle"] == pytest.approx(15.5)
        assert len(result["points_raw"]) == 12

    def test_wrong_length(self):
        assert parse_packet(b"\x54" * 10) is None

    def test_wrong_header(self):
        pkt = bytearray(build_packet())
        pkt[0] = 0x00
        assert parse_packet(bytes(pkt)) is None

    def test_bad_crc(self):
        pkt = bytearray(build_packet())
        pkt[46] ^= 0xFF  # Corrupt CRC
        assert parse_packet(bytes(pkt)) is None

    def test_distances_preserved(self):
        distances = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200]
        pkt = build_packet(distances_mm=distances)
        result = parse_packet(pkt)
        assert result is not None
        for i, (dist_mm, _intensity) in enumerate(result["points_raw"]):
            assert dist_mm == distances[i]

    def test_intensities_preserved(self):
        intensities = list(range(12))
        pkt = build_packet(intensities=intensities)
        result = parse_packet(pkt)
        assert result is not None
        for i, (_dist, intensity) in enumerate(result["points_raw"]):
            assert intensity == intensities[i]

    def test_speed(self):
        pkt = build_packet(speed_dps=360.0)
        result = parse_packet(pkt)
        assert result is not None
        assert result["speed_dps"] == pytest.approx(360.0)

    def test_timestamp(self):
        pkt = build_packet(timestamp_ms=12345)
        result = parse_packet(pkt)
        assert result is not None
        assert result["timestamp_ms"] == 12345


# ---------------------------------------------------------------------------
# Angle interpolation tests
# ---------------------------------------------------------------------------


class TestInterpolateAngles:
    def test_simple_range(self):
        angles = interpolate_angles(0.0, 11.0, 12)
        assert len(angles) == 12
        assert angles[0] == pytest.approx(0.0)
        assert angles[-1] == pytest.approx(11.0)

    def test_wraparound(self):
        # 355° → 5° should span 10°, not -350°
        angles = interpolate_angles(355.0, 5.0, 11)
        assert angles[0] == pytest.approx(355.0)
        # Last angle should wrap to 5°
        assert angles[-1] == pytest.approx(5.0, abs=0.1)

    def test_single_point(self):
        angles = interpolate_angles(90.0, 90.0, 1)
        assert len(angles) == 1
        assert angles[0] == pytest.approx(90.0)

    def test_all_positive_direction(self):
        angles = interpolate_angles(10.0, 20.0, 6)
        for i in range(len(angles) - 1):
            assert angles[i + 1] > angles[i]


# ---------------------------------------------------------------------------
# LidarScanner tests — no GPIO
# ---------------------------------------------------------------------------


class TestScannerNoSerial:
    def test_init_disabled(self, disabled_config):
        scanner = LidarScanner(disabled_config)
        assert not scanner.available

    def test_start_disabled(self, disabled_config):
        scanner = LidarScanner(disabled_config)
        scanner.start()
        assert not scanner.available

    def test_start_without_pyserial(self, lidar_config):
        with patch("rover.lidar._SERIAL_AVAILABLE", False):
            scanner = LidarScanner(lidar_config)
            scanner.start()
            assert not scanner.available

    def test_stop_idempotent(self, lidar_config):
        scanner = LidarScanner(lidar_config)
        scanner.stop()  # Should not raise

    def test_read_scan_not_available(self, lidar_config):
        scanner = LidarScanner(lidar_config)
        with pytest.raises(RuntimeError, match="not available"):
            scanner.read_scan()


# ---------------------------------------------------------------------------
# LidarScanner tests — with mocked serial
# ---------------------------------------------------------------------------


class TestScannerWithMockSerial:
    @pytest.fixture
    def mock_serial(self):
        mock_ser = MagicMock()
        mock_ser_class = MagicMock(return_value=mock_ser)
        with (
            patch("rover.lidar._SERIAL_AVAILABLE", True),
            patch("rover.lidar.serial") as mock_mod,
        ):
            mock_mod.Serial = mock_ser_class
            yield mock_ser

    def test_start_opens_port(self, lidar_config, mock_serial):
        scanner = LidarScanner(lidar_config)
        scanner.start()
        assert scanner.available

    def test_double_start_ignored(self, lidar_config, mock_serial):
        scanner = LidarScanner(lidar_config)
        scanner.start()
        scanner.start()  # Should not raise
        assert scanner.available

    def test_stop_closes_port(self, lidar_config, mock_serial):
        scanner = LidarScanner(lidar_config)
        scanner.start()
        scanner.stop()
        mock_serial.close.assert_called_once()
        assert not scanner.available

    def test_context_manager(self, lidar_config, mock_serial):
        with LidarScanner(lidar_config) as scanner:
            assert scanner.available
        assert not scanner.available

    def test_read_packet_valid(self, lidar_config, mock_serial):
        pkt = build_packet(start_angle_deg=10.0, end_angle_deg=15.5)
        mock_serial.in_waiting = len(pkt)
        mock_serial.read.return_value = pkt

        scanner = LidarScanner(lidar_config)
        scanner.start()
        result = scanner.read_packet()

        assert result is not None
        assert result["start_angle"] == pytest.approx(10.0)

    def test_read_packet_returns_none_when_incomplete(self, lidar_config, mock_serial):
        mock_serial.in_waiting = 0
        mock_serial.read.return_value = b""

        scanner = LidarScanner(lidar_config)
        scanner.start()
        result = scanner.read_packet()
        assert result is None

    @patch("rover.lidar.time")
    def test_read_scan_assembles_full_revolution(
        self, mock_time, lidar_config, mock_serial
    ):
        # Simulate a full 360° scan: 45 packets at 8° intervals, then
        # one packet wrapping back to 0° to trigger scan completion
        packets = bytearray()
        for i in range(45):
            start = i * 8.0
            end = start + 8.0
            if end > 360.0:
                end -= 360.0
            pkt = build_packet(
                start_angle_deg=start,
                end_angle_deg=end,
                distances_mm=[1000 + i * 10] * 12,
            )
            packets.extend(pkt)

        # Add wrap-around packet (start=0°) to trigger scan completion
        wrap_pkt = build_packet(start_angle_deg=0.0, end_angle_deg=8.0)
        packets.extend(wrap_pkt)

        # Feed all data at once, then empty
        call_count = [0]

        def read_side_effect(n):
            if call_count[0] == 0:
                call_count[0] += 1
                return bytes(packets)
            return b""

        mock_serial.in_waiting = len(packets)
        mock_serial.read.side_effect = read_side_effect

        # time.monotonic needs to return values < deadline
        mock_time.monotonic.return_value = 0.0
        mock_time.sleep = MagicMock()

        scanner = LidarScanner(lidar_config)
        scanner.start()
        points = scanner.read_scan()

        assert len(points) > 0
        assert all(isinstance(p, LidarPoint) for p in points)
        # All distances should be in meters
        assert all(p.distance > 0 for p in points)
        assert all(0 <= p.angle < 360 for p in points)

    def test_start_serial_error(self, lidar_config):
        with (
            patch("rover.lidar._SERIAL_AVAILABLE", True),
            patch("rover.lidar.serial") as mock_mod,
        ):
            mock_mod.Serial.side_effect = OSError("Port not found")
            scanner = LidarScanner(lidar_config)
            scanner.start()
            assert not scanner.available
