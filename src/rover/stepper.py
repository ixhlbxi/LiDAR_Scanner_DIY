"""
NEMA17 stepper motor control via A4988 driver.

Controls the rotation platform for 3D scan acquisition.
Uses rpi-lgpio for GPIO (D-029) — NOT RPi.GPIO (broken on Bookworm).

BCM GPIO assignments (from config):
  - direction_pin (17): rotation direction
  - step_pin (27): step pulse
  - enable_pin (22): active-low motor enable

Step-and-scan approach: step to angle, settle, acquire, repeat.
Includes configurable settling delay after each step to let
vibrations dissipate before LiDAR acquisition.

Decision references:
    D-015  Direct drive, no slip ring
    D-016  Open-loop step indexing
    D-017  1/16 microstepping (3200 steps/rev)
    D-029  rpi-lgpio over RPi.GPIO

Dependencies:
    rpi-lgpio (on Pi) or gpiozero
"""

from __future__ import annotations

import logging

from rover.config import StepperConfig

logger = logging.getLogger(__name__)


class StepperMotor:
    """A4988-driven NEMA17 stepper motor controller.

    Args:
        config: StepperConfig section from rover config.
    """

    def __init__(self, config: StepperConfig) -> None:
        self._config = config
        self._current_step: int = 0
        self._enabled = False
        logger.info(
            "StepperMotor initialized (steps/rev=%d, rpm=%.1f, pins DIR=%d STEP=%d EN=%d)",
            config.steps_per_rev, config.rpm,
            config.direction_pin, config.step_pin, config.enable_pin,
        )

    def start(self) -> None:
        """Configure GPIO pins and enable motor (set ENABLE low)."""
        raise NotImplementedError("StepperMotor.start() not yet implemented")

    def stop(self) -> None:
        """Disable motor (set ENABLE high) and clean up GPIO."""
        raise NotImplementedError("StepperMotor.stop() not yet implemented")

    def step(self, steps: int) -> None:
        """Move the motor by the given number of steps (negative = reverse)."""
        raise NotImplementedError("StepperMotor.step() not yet implemented")

    def move_to_angle(self, degrees: float) -> None:
        """Move to an absolute angle position."""
        raise NotImplementedError("StepperMotor.move_to_angle() not yet implemented")

    @property
    def current_angle(self) -> float:
        """Current angle in degrees."""
        return (self._current_step / self._config.steps_per_rev) * 360.0
