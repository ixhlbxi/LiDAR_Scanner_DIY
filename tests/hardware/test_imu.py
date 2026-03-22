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
    - Magnetometer readings may be corrupted near stepper motor (D-013)
    - Does not perform Madgwick fusion — raw sensor values only

Changelog:
    0.1.0  2026-03-22  Initial implementation
"""

from __future__ import annotations

import argparse
import math
import signal
import struct
import sys
import time

# MPU-9250 registers
REG_WHO_AM_I = 0x75
REG_PWR_MGMT_1 = 0x6B
REG_PWR_MGMT_2 = 0x6C
REG_SMPLRT_DIV = 0x19
REG_CONFIG = 0x1A
REG_GYRO_CONFIG = 0x1B
REG_ACCEL_CONFIG = 0x1C
REG_ACCEL_CONFIG2 = 0x1D
REG_INT_PIN_CFG = 0x37
REG_ACCEL_XOUT_H = 0x3B

# AK8963 magnetometer registers
AK8963_ADDR = 0x0C
AK8963_REG_WIA = 0x00
AK8963_REG_CNTL1 = 0x0A
AK8963_REG_HXL = 0x03
AK8963_REG_ST2 = 0x09

# Conversion factors
ACCEL_SCALE_2G = 9.81 / 16384.0  # m/s² per LSB at ±2g
GYRO_SCALE_250DPS = math.pi / (180.0 * 131.0)  # rad/s per LSB at ±250°/s
MAG_SCALE_14BIT = 0.15  # µT per LSB in 14-bit mode


def read_word_signed(bus, addr: int, reg: int) -> int:
    """Read a signed 16-bit big-endian value from two consecutive registers."""
    high = bus.read_byte_data(addr, reg)
    low = bus.read_byte_data(addr, reg + 1)
    val = (high << 8) | low
    if val >= 0x8000:
        val -= 0x10000
    return val


def init_mpu9250(bus, addr: int, rate_hz: int) -> str:
    """Initialize MPU-9250. Returns device identification string."""
    # Wake up (clear sleep bit)
    bus.write_byte_data(addr, REG_PWR_MGMT_1, 0x00)
    time.sleep(0.1)

    # Auto-select best clock source
    bus.write_byte_data(addr, REG_PWR_MGMT_1, 0x01)
    time.sleep(0.1)

    # Check WHO_AM_I
    who = bus.read_byte_data(addr, REG_WHO_AM_I)
    if who == 0x71:
        identity = "MPU-9250"
    elif who == 0x73:
        identity = "MPU-9255"
    else:
        identity = f"Unknown (WHO_AM_I=0x{who:02X})"

    # Configure gyro: ±250°/s (0x00)
    bus.write_byte_data(addr, REG_GYRO_CONFIG, 0x00)

    # Configure accel: ±2g (0x00)
    bus.write_byte_data(addr, REG_ACCEL_CONFIG, 0x00)

    # DLPF config: bandwidth 92 Hz (CONFIG = 0x02)
    bus.write_byte_data(addr, REG_CONFIG, 0x02)

    # Accel DLPF: bandwidth 99 Hz
    bus.write_byte_data(addr, REG_ACCEL_CONFIG2, 0x02)

    # Sample rate divider: rate = 1kHz / (1 + div)
    div = max(0, min(255, (1000 // rate_hz) - 1))
    bus.write_byte_data(addr, REG_SMPLRT_DIV, div)
    actual_rate = 1000 / (1 + div)
    print(f"  Sample rate divider: {div} (actual rate: {actual_rate:.0f} Hz)")

    return identity


def init_ak8963(bus) -> str | None:
    """Initialize AK8963 magnetometer via I2C bypass. Returns ID or None."""
    try:
        who = bus.read_byte_data(AK8963_ADDR, AK8963_REG_WIA)
    except OSError:
        return None

    if who != 0x48:
        return f"Unknown (WIA=0x{who:02X})"

    # Power down first
    bus.write_byte_data(AK8963_ADDR, AK8963_REG_CNTL1, 0x00)
    time.sleep(0.01)

    # Continuous measurement mode 2 (100 Hz), 16-bit output
    bus.write_byte_data(AK8963_ADDR, AK8963_REG_CNTL1, 0x16)
    time.sleep(0.01)

    return "AK8963"


def read_accel_gyro(bus, addr: int) -> tuple[list[float], list[float]]:
    """Read accel (m/s²) and gyro (rad/s) from MPU-9250."""
    # Read 14 bytes starting at ACCEL_XOUT_H: accel(6) + temp(2) + gyro(6)
    raw = bus.read_i2c_block_data(addr, REG_ACCEL_XOUT_H, 14)

    ax = struct.unpack(">h", bytes(raw[0:2]))[0] * ACCEL_SCALE_2G
    ay = struct.unpack(">h", bytes(raw[2:4]))[0] * ACCEL_SCALE_2G
    az = struct.unpack(">h", bytes(raw[4:6]))[0] * ACCEL_SCALE_2G

    gx = struct.unpack(">h", bytes(raw[8:10]))[0] * GYRO_SCALE_250DPS
    gy = struct.unpack(">h", bytes(raw[10:12]))[0] * GYRO_SCALE_250DPS
    gz = struct.unpack(">h", bytes(raw[12:14]))[0] * GYRO_SCALE_250DPS

    return [ax, ay, az], [gx, gy, gz]


def read_mag(bus) -> list[float] | None:
    """Read magnetometer (µT) from AK8963. Returns None if not ready."""
    try:
        # Read 7 bytes: HXL, HXH, HYL, HYH, HZL, HZH, ST2
        raw = bus.read_i2c_block_data(AK8963_ADDR, AK8963_REG_HXL, 7)
    except OSError:
        return None

    # ST2 must be read to signal end of measurement
    st2 = raw[6]
    if st2 & 0x08:  # Overflow
        return None

    # AK8963 is little-endian
    mx = struct.unpack("<h", bytes(raw[0:2]))[0] * MAG_SCALE_14BIT
    my = struct.unpack("<h", bytes(raw[2:4]))[0] * MAG_SCALE_14BIT
    mz = struct.unpack("<h", bytes(raw[4:6]))[0] * MAG_SCALE_14BIT

    return [mx, my, mz]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MPU-9250 IMU diagnostic — read sensor data and report statistics"
    )
    parser.add_argument("--bus", type=int, default=1, help="I2C bus number")
    parser.add_argument(
        "--address", type=lambda x: int(x, 0), default=0x68,
        help="MPU-9250 I2C address (hex, default: 0x68)"
    )
    parser.add_argument(
        "--duration", type=int, default=10, help="Run duration in seconds"
    )
    parser.add_argument(
        "--rate", type=int, default=200, help="Target sample rate in Hz"
    )
    parser.add_argument(
        "--no-mag", action="store_true", help="Disable magnetometer reading"
    )
    args = parser.parse_args()

    try:
        from smbus2 import SMBus
    except ImportError:
        print("ERROR: smbus2 not installed. Run: pip install smbus2")
        sys.exit(1)

    stop_event = False

    def handle_signal(signum, frame):
        nonlocal stop_event
        stop_event = True
        print("\nInterrupted — finishing...")

    signal.signal(signal.SIGINT, handle_signal)

    print(f"Opening I2C bus {args.bus}, address 0x{args.address:02X}...")
    try:
        bus = SMBus(args.bus)
    except OSError as e:
        print(f"ERROR: Cannot open I2C bus {args.bus}: {e}")
        sys.exit(1)

    try:
        # Initialize MPU-9250
        print("Initializing MPU-9250...")
        identity = init_mpu9250(bus, args.address, args.rate)
        print(f"  Device: {identity}")

        # Enable I2C bypass for magnetometer access
        bus.write_byte_data(args.address, REG_INT_PIN_CFG, 0x02)
        time.sleep(0.01)

        # Initialize magnetometer
        mag_identity = None
        use_mag = not args.no_mag
        if use_mag:
            print("Initializing AK8963 magnetometer...")
            mag_identity = init_ak8963(bus)
            if mag_identity is None:
                print("  WARNING: AK8963 not found — magnetometer disabled")
                use_mag = False
            else:
                print(f"  Device: {mag_identity}")

        print(f"\nStreaming for {args.duration} seconds...\n")

        sample_count = 0
        mag_count = 0
        interval = 1.0 / args.rate
        start_time = time.monotonic()
        last_print = start_time

        while not stop_event:
            now = time.monotonic()
            elapsed = now - start_time
            if elapsed >= args.duration:
                break

            accel, gyro = read_accel_gyro(bus, args.address)
            sample_count += 1

            mag = None
            if use_mag:
                mag = read_mag(bus)
                if mag is not None:
                    mag_count += 1

            # Print every ~1 second
            if now - last_print >= 1.0:
                last_print = now
                a_str = f"[{accel[0]:+7.3f}, {accel[1]:+7.3f}, {accel[2]:+7.3f}]"
                g_str = f"[{gyro[0]:+7.4f}, {gyro[1]:+7.4f}, {gyro[2]:+7.4f}]"
                line = f"  Accel (m/s2): {a_str}  Gyro (rad/s): {g_str}"
                if mag is not None:
                    m_str = f"[{mag[0]:+7.1f}, {mag[1]:+7.1f}, {mag[2]:+7.1f}]"
                    line += f"  Mag (uT): {m_str}"
                print(line)

            # Pace to target rate
            target_time = start_time + sample_count * interval
            sleep_time = target_time - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)

    finally:
        bus.close()

    # Summary
    elapsed = time.monotonic() - start_time
    achieved_rate = sample_count / elapsed if elapsed > 0 else 0

    print()
    print("=" * 55)
    print("MPU-9250 IMU Diagnostic Summary")
    print("=" * 55)
    print(f"  Device:            {identity}")
    print(f"  Duration:          {elapsed:.1f} s")
    print(f"  Accel/Gyro samples:{sample_count}")
    print(f"  Target rate:       {args.rate} Hz")
    print(f"  Achieved rate:     {achieved_rate:.1f} Hz")
    print(f"  Rate accuracy:     {achieved_rate / args.rate * 100:.1f}%")
    if use_mag:
        print(f"  Mag readings:      {mag_count}")
        if mag_identity:
            print(f"  Magnetometer:      {mag_identity}")
    else:
        print("  Magnetometer:      Disabled")
    print("=" * 55)


if __name__ == "__main__":
    main()
