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
import sys
import time

from rover.lidar import PACKET_HEADER, PACKET_LENGTH, parse_packet

BAUD_RATE = 230400


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LD19 LiDAR diagnostic — parse packets and report statistics"
    )
    parser.add_argument("--port", default="/dev/rover-lidar", help="Serial port")
    parser.add_argument("--duration", type=int, default=10, help="Run duration in seconds")
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
        print(f"  Min distance:      {min_distance_mm} mm ({min_distance_mm / 1000:.3f} m)")
        print(f"  Max distance:      {max_distance_mm} mm ({max_distance_mm / 1000:.3f} m)")
    else:
        print("  No valid distance readings")
    print("=" * 50)


if __name__ == "__main__":
    main()
