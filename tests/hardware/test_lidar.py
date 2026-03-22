#!/usr/bin/env python3
"""LD19 LiDAR diagnostic script.

Purpose:
    Validate LD19 LiDAR communication by parsing the raw packet stream and
    reporting scan statistics. Run on the Raspberry Pi with the LD19 connected.

Context:
    PiLiDAR-RTK Rover — Phase 3, Task 4 (sensor test scripts).
    This is a field diagnostic tool, NOT a pytest test.

Dependencies:
    - pyserial (pip install pyserial)

Usage:
    python tests/hardware/test_lidar.py [--port PORT] [--duration SECONDS]

    --port PORT         Serial port (default: /dev/ttyUSB0)
    --duration SECONDS  Run duration in seconds (default: 10)

I/O:
    Input:  LD19 serial stream at 230400 baud
    Output: Console summary (scan rate, point count, distance range, CRC errors)

LD19 Packet Format (47 bytes):
    [0x54][ver_len:1][speed:2LE][start_angle:2LE]
    [12 × (distance:2LE + intensity:1)]
    [end_angle:2LE][timestamp:2LE][CRC8:1]

Limitations:
    - Requires LD19 connected via USB-serial adapter
    - CRC8 lookup table derived from community documentation
    - Does not perform Madgwick fusion or IMU correlation

Changelog:
    0.1.0  2026-03-22  Initial implementation
"""

from __future__ import annotations

import argparse
import signal
import struct
import sys
import time

# LD19 constants
PACKET_HEADER = 0x54
PACKET_LENGTH = 47
POINTS_PER_PACKET = 12
BAUD_RATE = 230400

# CRC8 lookup table for LD19 (polynomial 0x4D, used by LDRobot sensors)
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


def crc8(data: bytes) -> int:
    """Compute CRC8 over data using the LD19 lookup table."""
    crc = 0
    for b in data:
        crc = _CRC_TABLE[(crc ^ b) & 0xFF]
    return crc


def parse_packet(packet: bytes) -> dict | None:
    """Parse a 47-byte LD19 packet. Returns dict or None on CRC failure."""
    if len(packet) != PACKET_LENGTH:
        return None
    if packet[0] != PACKET_HEADER:
        return None

    # CRC check: CRC8 over bytes 0..45, compare to byte 46
    expected_crc = packet[46]
    computed_crc = crc8(packet[:46])
    if computed_crc != expected_crc:
        return None

    ver_len = packet[1]
    speed = struct.unpack_from("<H", packet, 2)[0]  # degrees/sec * 100
    start_angle = struct.unpack_from("<H", packet, 4)[0]  # degrees * 100

    points = []
    for i in range(POINTS_PER_PACKET):
        offset = 6 + i * 3
        dist = struct.unpack_from("<H", packet, offset)[0]  # mm
        intensity = packet[offset + 2]
        points.append({"distance_mm": dist, "intensity": intensity})

    end_angle = struct.unpack_from("<H", packet, 42)[0]  # degrees * 100
    timestamp = struct.unpack_from("<H", packet, 44)[0]  # ms, wraps at 30000

    return {
        "ver_len": ver_len,
        "speed_dps": speed / 100.0,
        "start_angle_deg": start_angle / 100.0,
        "end_angle_deg": end_angle / 100.0,
        "timestamp_ms": timestamp,
        "points": points,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LD19 LiDAR diagnostic — parse packets and report statistics"
    )
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Serial port")
    parser.add_argument(
        "--duration", type=int, default=10, help="Run duration in seconds"
    )
    args = parser.parse_args()

    try:
        import serial
    except ImportError:
        print("ERROR: pyserial not installed. Run: pip install pyserial")
        sys.exit(1)

    # Graceful shutdown on Ctrl-C
    stop_event = False

    def handle_signal(signum, frame):
        nonlocal stop_event
        stop_event = True
        print("\nInterrupted — finishing...")

    signal.signal(signal.SIGINT, handle_signal)

    print(f"Opening {args.port} at {BAUD_RATE} baud...")
    try:
        ser = serial.Serial(args.port, BAUD_RATE, timeout=1)
    except serial.SerialException as e:
        print(f"ERROR: Cannot open {args.port}: {e}")
        sys.exit(1)

    print(f"Reading for {args.duration} seconds...\n")

    total_packets = 0
    crc_errors = 0
    total_points = 0
    min_distance_mm = float("inf")
    max_distance_mm = 0
    speeds: list[float] = []
    start_time = time.monotonic()
    buf = bytearray()

    try:
        while not stop_event:
            elapsed = time.monotonic() - start_time
            if elapsed >= args.duration:
                break

            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue
            buf.extend(data)

            # Scan buffer for packets
            while len(buf) >= PACKET_LENGTH:
                # Find header byte
                idx = buf.find(PACKET_HEADER)
                if idx < 0:
                    buf.clear()
                    break
                if idx > 0:
                    buf = buf[idx:]
                if len(buf) < PACKET_LENGTH:
                    break

                raw = bytes(buf[:PACKET_LENGTH])
                buf = buf[PACKET_LENGTH:]

                result = parse_packet(raw)
                if result is None:
                    crc_errors += 1
                    total_packets += 1
                    continue

                total_packets += 1
                speeds.append(result["speed_dps"])

                for pt in result["points"]:
                    d = pt["distance_mm"]
                    if d > 0:  # 0 = invalid/no return
                        total_points += 1
                        min_distance_mm = min(min_distance_mm, d)
                        max_distance_mm = max(max_distance_mm, d)

    finally:
        ser.close()

    # Summary
    elapsed = time.monotonic() - start_time
    print("=" * 50)
    print("LD19 LiDAR Diagnostic Summary")
    print("=" * 50)
    print(f"  Duration:          {elapsed:.1f} s")
    print(f"  Total packets:     {total_packets}")
    print(f"  CRC errors:        {crc_errors}", end="")
    if total_packets > 0:
        rate = crc_errors / total_packets * 100
        print(f" ({rate:.2f}%)")
    else:
        print()
    print(f"  Valid points:      {total_points}")
    if total_packets > crc_errors and elapsed > 0:
        pps = (total_packets - crc_errors) / elapsed
        # Each packet has 12 points; ~40-50 packets per full 360° scan
        # Scan rate ≈ packets_per_sec / packets_per_revolution
        print(f"  Packet rate:       {pps:.1f} packets/s")
    if speeds:
        avg_speed = sum(speeds) / len(speeds)
        scan_rate = avg_speed / 360.0
        print(f"  Avg motor speed:   {avg_speed:.1f} °/s")
        print(f"  Scan rate:         {scan_rate:.1f} Hz")
    if min_distance_mm < float("inf"):
        print(f"  Min distance:      {min_distance_mm} mm ({min_distance_mm/1000:.3f} m)")
        print(f"  Max distance:      {max_distance_mm} mm ({max_distance_mm/1000:.3f} m)")
    else:
        print("  No valid distance readings")
    print("=" * 50)


if __name__ == "__main__":
    main()
