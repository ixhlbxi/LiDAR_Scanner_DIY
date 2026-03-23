"""
NEMA17 stepper motor control via A4988 driver.

Controls the rotation platform for 3D scan acquisition.
Uses rpi-lgpio for GPIO (D-029) — NOT RPi.GPIO (broken on Bookworm).

BCM GPIO assignments (from config):
  - direction_pin (17): rotation direction
  - step_pin (27): step pulse
  - enable_pin (22): active-low motor enable

Step-and-scan approach: step to angle, settle, acquire, repeat.

Decision references:
    D-015  Direct drive, no slip ring
    D-016  Open-loop step indexing
    D-017  1/16 microstepping (3200 steps/rev)
    D-029  rpi-lgpio over RPi.GPIO

Dependencies:
    rpi-lgpio (on Pi) or gpiozero

Changelog:
    0.1.0  2026-03-22  Stub
    0.2.0  2026-03-22  Full implementation
"""

from __future__ import annotations

import logging
import os
import time

from rover.config import StepperConfig

logger = logging.getLogger(__name__)

# Suppress lgpio temp file clutter (D-029) — must be set before import
os.environ.setdefault("LG_WD", "/tmp")

try:
    import RPi.GPIO as GPIO  # rpi-lgpio is a drop-in replacement
    _GPIO_AVAILABLE = True
except ImportError:
    GPIO = None  # type: ignore[assignment]
    _GPIO_AVAILABLE = False


class StepperMotor:
    """A4988-driven NEMA17 stepper motor controller.

    Args:
        config: StepperConfig section from rover config.
    """

    def __init__(self, config: StepperConfig) -> None:
        self._config = config
        self._current_step: int = 0
        self._available = False
        self._started = False

        # Precompute timing
        self._steps_per_sec = config.rpm / 60.0 * config.steps_per_rev
        self._step_interval = 1.0 / self._steps_per_sec
        self._degrees_per_step = 360.0 / config.steps_per_rev

        if not config.enabled:
            logger.info("Stepper disabled by config")
            return

        if not _GPIO_AVAILABLE:
            logger.warning(
                "Stepper enabled but GPIO not available — running without hardware"
            )
            return

        logger.info(
            "StepperMotor initialized (steps/rev=%d, rpm=%.1f, pins DIR=%d STEP=%d EN=%d)",
            config.steps_per_rev, config.rpm,
            config.direction_pin, config.step_pin, config.enable_pin,
        )

    @property
    def available(self) -> bool:
        """Whether the stepper hardware is initialized and usable."""
        return self._available

    @property
    def current_angle(self) -> float:
        """Current angle in degrees."""
        return self._current_step * self._degrees_per_step

    def start(self) -> None:
        """Configure GPIO pins and enable motor (set ENABLE low)."""
        if not self._config.enabled:
            logger.info("Stepper disabled, skipping start")
            return

        if not _GPIO_AVAILABLE:
            logger.warning("Cannot start stepper: GPIO unavailable")
            return

        if self._started:
            logger.warning("Stepper already started")
            return

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self._config.direction_pin, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(self._config.step_pin, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(self._config.enable_pin, GPIO.OUT, initial=GPIO.HIGH)

            # Enable motor (active low)
            GPIO.output(self._config.enable_pin, GPIO.LOW)
            time.sleep(0.01)  # Let A4988 driver stabilize
        except Exception:
            logger.warning("Failed to initialize stepper GPIO", exc_info=True)
            self._available = False
            try:
                GPIO.cleanup()
            except Exception:
                pass
            return

        self._started = True
        self._available = True
        self._current_step = 0
        logger.info("Stepper started")

    def stop(self) -> None:
        """Disable motor (set ENABLE high) and clean up GPIO."""
        if not self._started:
            return

        try:
            GPIO.output(self._config.enable_pin, GPIO.HIGH)
        except Exception:
            pass

        try:
            GPIO.cleanup()
        except Exception:
            pass

        self._started = False
        self._available = False
        logger.info("Stepper stopped, motor disabled")

    def step(self, steps: int) -> None:
        """Move the motor by the given number of steps (negative = reverse).

        Args:
            steps: Number of steps to move. Positive = forward, negative = reverse.

        Raises:
            RuntimeError: If the stepper is not available.
        """
        if not self._available:
            raise RuntimeError("Stepper not available")

        if steps == 0:
            return

        # Set direction
        direction = GPIO.HIGH if steps > 0 else GPIO.LOW
        GPIO.output(self._config.direction_pin, direction)
        time.sleep(0.001)  # Direction setup time

        increment = 1 if steps > 0 else -1

        for _ in range(abs(steps)):
            t_before = time.monotonic()

            # Step pulse (A4988 requires ≥1µs HIGH)
            GPIO.output(self._config.step_pin, GPIO.HIGH)
            time.sleep(0.000002)  # 2µs minimum pulse width
            GPIO.output(self._config.step_pin, GPIO.LOW)

            # Pace to target interval
            pulse_time = time.monotonic() - t_before
            sleep_time = self._step_interval - pulse_time
            if sleep_time > 0:
                time.sleep(sleep_time)

            self._current_step += increment

    def move_to_angle(self, degrees: float) -> None:
        """Move to an absolute angle position.

        Args:
            degrees: Target angle in degrees.
        """
        target_step = round(degrees / self._degrees_per_step)
        delta = target_step - self._current_step
        if delta != 0:
            self.step(delta)

    def reset_position(self) -> None:
        """Reset the internal step counter to zero (current position becomes 0°)."""
        self._current_step = 0

    def __enter__(self) -> StepperMotor:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
