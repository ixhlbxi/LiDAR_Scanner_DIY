#!/usr/bin/env python3
"""MPU-9250 IMU diagnostic script.

Purpose:
    Validate MPU-9250 I2C communication by reading identification registers,
    streaming accel/gyro/mag data, and reporting achieved sample rate.
    Run on the Raspberry Pi with the MPU-9250 connected via I2C.

Context:
    PiLiDAR-RTK Rover — Phase 3, Task 4 (sensor test scripts).
    This is a field diagnostic tool, NOT a pytest test.

Dependencies:
    - smbus2 (pip install smbus2)

Usage:
    python tests/hardware/test_imu.py [OPTIONS]

    --bus BUS           I2C bus number (default: 1)
    --address ADDR      MPU-9250 I2C address in hex (default: 0x68)
    --duration SECONDS  Run duration in seconds (default: 10)
    --rate HZ           Target sample rate in Hz (default: 200)
    --no-mag            Disable magnetometer reading

I/O:
    Input:  MPU-9250 via I2C bus
    Output: Console — identification, live samples, summary

MPU-9250 Register Map (key registers):
    0x75  WHO_AM_I      — 0x71 (MPU-9250) or 0x73 (MPU-9255)
    0x6B  PWR_MGMT_1    — Power management
    0x1B  GYRO_CONFIG   — Gyro full-scale range
    0x1C  ACCEL_CONFIG  — Accel full-scale range
    0x19  SMPLRT_DIV    — Sample rate divider
    0x37  INT_PIN_CFG   — I2C bypass enable (bit 1)
    0x3B  ACCEL_XOUT_H  — Start of 14-byte sensor data block

AK8963 (magnetometer at 0x0C via bypass):
    0x00  WIA           — Device ID (expect 0x48)
    0x0A  CNTL1         — Mode control
    0x03  HXL           — Start of 6-byte mag data + ST2

Limitations:
    - Requires MPU-9250 wired to I2C bus with 4.7k pull-ups on SDA/SCL
    - Magnetometer readings may be corrupted near stepper motor (DEC-013)
    - Does not perform Madgwick fusion — raw sensor values only

Changelog:
    0.1.0  2026-03-22  Initial implementation
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from rover.config import load_config
from rover.imu import ImuDriver


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MPU-9250 IMU diagnostic — read sensor data and report statistics"
    )
    parser.add_argument("--config", help="Config file (optional; use defaults if not provided)")
    parser.add_argument("--duration", type=int, default=10, help="Run duration in seconds")
    parser.add_argument("--no-mag", action="store_true", help="Disable magnetometer reading")
    args = parser.parse_args()

    stop_event = False

    def handle_signal(signum, frame):
        nonlocal stop_event
        stop_event = True
        print("\nInterrupted — finishing...")

    signal.signal(signal.SIGINT, handle_signal)

    cfg = load_config(args.config)
    print("Initializing MPU-9250 via ImuDriver...")
    imu = ImuDriver(cfg.imu)
    if not imu.available:
        print("ERROR: IMU initialization failed")
        sys.exit(1)

    imu.start()
    try:
        print(f"\nStreaming for {args.duration} seconds...\n")

        sample_count = 0
        start_time = time.monotonic()
        last_print = start_time

        while not stop_event:
            now = time.monotonic()
            elapsed = now - start_time
            if elapsed >= args.duration:
                break

            sample = imu.read_sample()
            if sample is None:
                time.sleep(0.001)
                continue

            sample_count += 1

            # Print every ~1 second
            if now - last_print >= 1.0:
                last_print = now
                a_str = (
                    f"[{sample.accel[0]:+7.3f}, {sample.accel[1]:+7.3f}, {sample.accel[2]:+7.3f}]"
                )
                g_str = f"[{sample.gyro[0]:+7.4f}, {sample.gyro[1]:+7.4f}, {sample.gyro[2]:+7.4f}]"
                line = f"  Accel (m/s2): {a_str}  Gyro (rad/s): {g_str}"
                if sample.mag is not None:
                    m_str = f"[{sample.mag[0]:+7.1f}, {sample.mag[1]:+7.1f}, {sample.mag[2]:+7.1f}]"
                    line += f"  Mag (uT): {m_str}"
                print(line)

    finally:
        imu.stop()

    # Summary
    elapsed = time.monotonic() - start_time
    achieved_rate = sample_count / elapsed if elapsed > 0 else 0

    print()
    print("=" * 55)
    print("MPU-9250 IMU Diagnostic Summary")
    print("=" * 55)
    print(f"  Duration:          {elapsed:.1f} s")
    print(f"  Accel/Gyro samples:{sample_count}")
    print(f"  Target rate:       {cfg.imu.sample_rate_hz} Hz")
    print(f"  Achieved rate:     {achieved_rate:.1f} Hz")
    print(f"  Rate accuracy:     {achieved_rate / cfg.imu.sample_rate_hz * 100:.1f}%")
    print("=" * 55)


if __name__ == "__main__":
    main()
