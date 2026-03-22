#!/usr/bin/env python3
"""Pi HQ Camera diagnostic script.

Purpose:
    Validate Pi HQ Camera operation by capturing single frames and optional
    burst sequences, reporting resolution, file size, and capture latency.
    Run on the Raspberry Pi with the HQ Camera connected via CSI ribbon.

Context:
    PiLiDAR-RTK Rover — Phase 3, Task 4 (sensor test scripts).
    This is a field diagnostic tool, NOT a pytest test.

Dependencies:
    - picamera2 (pre-installed on Pi OS, or: sudo apt install python3-picamera2)

Usage:
    python tests/hardware/test_camera.py [OPTIONS]

    --output PATH       Output path for single capture (default: /tmp/test_capture.jpg)
    --burst N           Burst mode: capture N frames (default: 1 = single shot)
    --resolution WxH    Capture resolution (default: 1920x1080)
    --quality Q         JPEG quality 1-100 (default: 85)

I/O:
    Input:  Pi HQ Camera via CSI
    Output: JPEG file(s) + console summary (resolution, file size, latency)

Limitations:
    - Requires Pi HQ Camera connected and enabled (raspi-config)
    - picamera2 must be installed with libcamera backend
    - First capture has higher latency due to sensor warm-up

Changelog:
    0.1.0  2026-03-22  Initial implementation
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pi HQ Camera diagnostic — capture frames and report latency"
    )
    parser.add_argument(
        "--output", default="/tmp/test_capture.jpg",
        help="Output path for single capture"
    )
    parser.add_argument(
        "--burst", type=int, default=1,
        help="Number of frames to capture (1 = single shot)"
    )
    parser.add_argument(
        "--resolution", default="1920x1080",
        help="Capture resolution as WxH (default: 1920x1080)"
    )
    parser.add_argument(
        "--quality", type=int, default=85,
        help="JPEG quality 1-100 (default: 85)"
    )
    args = parser.parse_args()

    try:
        from picamera2 import Picamera2
    except ImportError:
        print("ERROR: picamera2 not installed.")
        print("  On Pi OS: sudo apt install python3-picamera2")
        sys.exit(1)

    # Parse resolution
    try:
        w, h = args.resolution.split("x")
        width, height = int(w), int(h)
    except ValueError:
        print(f"ERROR: Invalid resolution format '{args.resolution}'. Use WxH (e.g., 1920x1080)")
        sys.exit(1)

    if args.quality < 1 or args.quality > 100:
        print(f"ERROR: Quality must be 1-100, got {args.quality}")
        sys.exit(1)

    stop_event = False

    def handle_signal(signum, frame):
        nonlocal stop_event
        stop_event = True
        print("\nInterrupted — stopping camera...")

    signal.signal(signal.SIGINT, handle_signal)

    print("Pi HQ Camera Diagnostic")
    print(f"  Resolution:  {width}x{height}")
    print(f"  JPEG quality: {args.quality}")
    print(f"  Frames:      {args.burst}")
    print()

    print("Initializing camera...")
    cam = Picamera2()

    try:
        still_config = cam.create_still_configuration(
            main={"size": (width, height), "format": "RGB888"}
        )
        cam.configure(still_config)
        cam.start()
        # Allow auto-exposure to settle
        time.sleep(1.0)

        latencies: list[float] = []
        file_sizes: list[int] = []

        for i in range(args.burst):
            if stop_event:
                break

            if args.burst == 1:
                output_path = args.output
            else:
                base, ext = os.path.splitext(args.output)
                output_path = f"{base}_{i + 1:04d}{ext}"

            t_start = time.monotonic()
            cam.capture_file(output_path, format="jpeg", quality=args.quality)
            t_end = time.monotonic()

            latency_ms = (t_end - t_start) * 1000
            latencies.append(latency_ms)

            fsize = os.path.getsize(output_path)
            file_sizes.append(fsize)

            if args.burst > 1:
                print(f"  Frame {i + 1}/{args.burst}: {latency_ms:.1f} ms, "
                      f"{fsize / 1024:.1f} KB — {output_path}")
            else:
                print(f"  Captured: {output_path}")

    finally:
        cam.stop()
        cam.close()

    # Summary
    print()
    print("=" * 50)
    print("Pi HQ Camera Diagnostic Summary")
    print("=" * 50)
    print(f"  Resolution:       {width}x{height}")
    print(f"  JPEG quality:     {args.quality}")
    print(f"  Frames captured:  {len(latencies)}")

    if latencies:
        print(f"  Capture latency:  {latencies[0]:.1f} ms (first frame)")
        if len(latencies) > 1:
            avg = sum(latencies[1:]) / len(latencies[1:])
            print(f"  Avg latency:      {avg:.1f} ms (excluding first)")
            print(f"  Min latency:      {min(latencies[1:]):.1f} ms")
            print(f"  Max latency:      {max(latencies[1:]):.1f} ms")

    if file_sizes:
        avg_kb = sum(file_sizes) / len(file_sizes) / 1024
        print(f"  Avg file size:    {avg_kb:.1f} KB")

    print("=" * 50)


if __name__ == "__main__":
    main()
