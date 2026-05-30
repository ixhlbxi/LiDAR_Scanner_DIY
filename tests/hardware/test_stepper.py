#!/usr/bin/env python3
"""A4988 stepper motor diagnostic script.

Purpose:
    Validate stepper motor control via A4988 driver by rotating a specified
    number of degrees, measuring step timing jitter, and optionally reversing.
    Run on the Raspberry Pi with the A4988 + NEMA 17 connected.

Context:
    PiLiDAR-RTK Rover — Phase 3, Task 4 (sensor test scripts).
    This is a field diagnostic tool, NOT a pytest test.
    Uses rpi-lgpio per DEC-029 (RPi.GPIO broken on Bookworm).

Dependencies:
    - rpi-lgpio (pip install rpi-lgpio)
      Set LG_WD=/tmp to suppress lgpio temp files.

Usage:
    python tests/hardware/test_stepper.py [OPTIONS]

    --degrees DEG    Rotation amount in degrees (default: 360)
    --rpm RPM        Rotation speed (default: 1.0)
    --reverse        Reverse direction after forward rotation
    --dir-pin PIN    BCM GPIO for direction (default: 17)
    --step-pin PIN   BCM GPIO for step pulse (default: 27)
    --enable-pin PIN BCM GPIO for enable, active low (default: 22)
    --steps-per-rev  Steps per full revolution (default: 3200, 1/16 microstep)

I/O:
    Input:  CLI arguments
    Output: Console — step count, timing stats, jitter analysis

Motor Control:
    - ENABLE pin is active low: LOW = motor energized, HIGH = motor disabled
    - STEP pulse: ≥1µs high, then low. Each rising edge = one step.
    - DIR pin: HIGH/LOW sets rotation direction
    - Motor is ALWAYS disabled on exit (including Ctrl-C)

Limitations:
    - Open-loop control — no encoder feedback (DEC-016)
    - Requires A4988 wired with 1/16 microstepping jumpers set (DEC-017)
    - 12V motor power must be supplied separately (DEC-018)

Changelog:
    0.1.0  2026-03-22  Initial implementation
"""

from __future__ import annotations

import argparse
import os
import signal
import statistics
import sys
import time

# Suppress lgpio temp file clutter (DEC-029)
os.environ.setdefault("LG_WD", "/tmp")

# Default GPIO pins (BCM)
DEFAULT_DIR_PIN = 17
DEFAULT_STEP_PIN = 27
DEFAULT_ENABLE_PIN = 22
DEFAULT_STEPS_PER_REV = 3200  # 200 steps × 16 microsteps


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A4988 stepper motor diagnostic — rotate and measure timing"
    )
    parser.add_argument(
        "--degrees", type=float, default=360.0, help="Degrees to rotate"
    )
    parser.add_argument(
        "--rpm", type=float, default=1.0, help="Rotation speed in RPM"
    )
    parser.add_argument(
        "--reverse", action="store_true", help="Reverse after forward rotation"
    )
    parser.add_argument(
        "--dir-pin", type=int, default=DEFAULT_DIR_PIN, help="BCM GPIO for DIR"
    )
    parser.add_argument(
        "--step-pin", type=int, default=DEFAULT_STEP_PIN, help="BCM GPIO for STEP"
    )
    parser.add_argument(
        "--enable-pin", type=int, default=DEFAULT_ENABLE_PIN,
        help="BCM GPIO for ENABLE (active low)"
    )
    parser.add_argument(
        "--steps-per-rev", type=int, default=DEFAULT_STEPS_PER_REV,
        help="Steps per full revolution"
    )
    args = parser.parse_args()

    try:
        import RPi.GPIO as GPIO  # rpi-lgpio is a drop-in replacement
    except ImportError:
        print("ERROR: rpi-lgpio not installed. Run: pip install rpi-lgpio")
        sys.exit(1)

    # Calculate step parameters
    steps_needed = int(args.degrees / 360.0 * args.steps_per_rev)
    steps_per_sec = args.rpm / 60.0 * args.steps_per_rev
    step_interval = 1.0 / steps_per_sec

    print(f"Stepper Motor Diagnostic")
    print(f"  Degrees:       {args.degrees}°")
    print(f"  RPM:           {args.rpm}")
    print(f"  Steps needed:  {steps_needed}")
    print(f"  Step interval: {step_interval * 1000:.3f} ms")
    print(f"  GPIO pins:     DIR={args.dir_pin} STEP={args.step_pin} EN={args.enable_pin}")
    print()

    stop_event = False

    def handle_signal(signum, frame):
        nonlocal stop_event
        stop_event = True
        print("\nInterrupted — disabling motor...")

    signal.signal(signal.SIGINT, handle_signal)

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(args.dir_pin, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(args.step_pin, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(args.enable_pin, GPIO.OUT, initial=GPIO.HIGH)  # Disabled

    try:
        # Enable motor
        GPIO.output(args.enable_pin, GPIO.LOW)
        time.sleep(0.01)  # Let driver stabilize

        for pass_num, direction in enumerate([GPIO.HIGH, GPIO.LOW]):
            if pass_num == 1 and not args.reverse:
                break
            if stop_event:
                break

            label = "FORWARD" if pass_num == 0 else "REVERSE"
            GPIO.output(args.dir_pin, direction)
            time.sleep(0.001)  # Direction setup time

            print(f"  {label}: stepping {steps_needed} steps...")

            jitter_us: list[float] = []
            start_time = time.monotonic()

            for step in range(steps_needed):
                if stop_event:
                    break

                t_before = time.monotonic()

                # Step pulse
                GPIO.output(args.step_pin, GPIO.HIGH)
                time.sleep(0.000002)  # 2µs minimum pulse width
                GPIO.output(args.step_pin, GPIO.LOW)

                # Pace to target interval
                t_after = time.monotonic()
                pulse_time = t_after - t_before
                sleep_time = step_interval - pulse_time
                if sleep_time > 0:
                    time.sleep(sleep_time)

                # Measure actual interval
                t_end = time.monotonic()
                actual_interval = t_end - t_before
                jitter_us.append((actual_interval - step_interval) * 1e6)

            actual_duration = time.monotonic() - start_time
            expected_duration = steps_needed * step_interval

            steps_done = min(step + 1, steps_needed) if not stop_event else step

            print(f"    Steps completed: {steps_done}")
            print(f"    Expected time:   {expected_duration:.3f} s")
            print(f"    Actual time:     {actual_duration:.3f} s")
            print(f"    Time error:      {(actual_duration - expected_duration) * 1000:.2f} ms")

            if jitter_us:
                print(f"    Jitter mean:     {statistics.mean(jitter_us):+.1f} µs")
                print(f"    Jitter stdev:    {statistics.stdev(jitter_us) if len(jitter_us) > 1 else 0:.1f} µs")
                print(f"    Jitter max:      {max(abs(j) for j in jitter_us):.1f} µs")
            print()

    finally:
        # ALWAYS disable motor and clean up GPIO
        GPIO.output(args.enable_pin, GPIO.HIGH)
        GPIO.cleanup()
        print("Motor disabled, GPIO cleaned up.")

    print("=" * 50)
    print("Stepper Diagnostic Complete")
    print("=" * 50)


if __name__ == "__main__":
    main()
