"""Unit tests for rover.stepper — runs anywhere, no hardware required."""

from unittest.mock import MagicMock, patch, call

import pytest

from rover.config import StepperConfig


@pytest.fixture
def stepper_config():
    return StepperConfig(
        enabled=True,
        steps_per_rev=3200,
        rpm=1.0,
        step_interval_deg=1.5,
        direction_pin=17,
        step_pin=27,
        enable_pin=22,
    )


@pytest.fixture
def disabled_config():
    return StepperConfig(
        enabled=False,
        steps_per_rev=3200,
        rpm=1.0,
        step_interval_deg=1.5,
        direction_pin=17,
        step_pin=27,
        enable_pin=22,
    )


@pytest.fixture
def mock_gpio():
    """Patch GPIO module and availability flag for off-Pi testing."""
    gpio = MagicMock()
    gpio.BCM = 11
    gpio.OUT = 0
    gpio.HIGH = 1
    gpio.LOW = 0
    with (
        patch("rover.stepper._GPIO_AVAILABLE", True),
        patch("rover.stepper.GPIO", gpio),
    ):
        yield gpio


# ---------------------------------------------------------------------------
# Tests without GPIO (off-Pi behavior)
# ---------------------------------------------------------------------------


class TestStepperNoGPIO:
    def test_init_when_disabled(self, disabled_config):
        from rover.stepper import StepperMotor

        motor = StepperMotor(disabled_config)
        assert not motor.available

    def test_start_when_disabled(self, disabled_config):
        from rover.stepper import StepperMotor

        motor = StepperMotor(disabled_config)
        motor.start()
        assert not motor.available

    def test_start_without_gpio(self, stepper_config):
        with patch("rover.stepper._GPIO_AVAILABLE", False):
            from rover.stepper import StepperMotor

            motor = StepperMotor(stepper_config)
            motor.start()
            assert not motor.available

    def test_stop_idempotent(self, stepper_config):
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.stop()  # Should not raise

    def test_current_angle_default(self, stepper_config):
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        assert motor.current_angle == 0.0


# ---------------------------------------------------------------------------
# Tests with mocked GPIO
# ---------------------------------------------------------------------------


class TestStepperWithMockGPIO:
    def test_start_configures_pins(self, stepper_config, mock_gpio):
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()

        mock_gpio.setmode.assert_called_once_with(mock_gpio.BCM)
        assert mock_gpio.setup.call_count == 3
        mock_gpio.setup.assert_any_call(17, mock_gpio.OUT, initial=mock_gpio.LOW)
        mock_gpio.setup.assert_any_call(27, mock_gpio.OUT, initial=mock_gpio.LOW)
        mock_gpio.setup.assert_any_call(22, mock_gpio.OUT, initial=mock_gpio.HIGH)

    def test_start_enables_motor(self, stepper_config, mock_gpio):
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()

        # Enable pin set LOW (active low = motor on)
        mock_gpio.output.assert_called_with(22, mock_gpio.LOW)

    def test_start_sets_available(self, stepper_config, mock_gpio):
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()
        assert motor.available

    def test_double_start_ignored(self, stepper_config, mock_gpio):
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()
        setup_count = mock_gpio.setup.call_count
        motor.start()  # Second call
        assert mock_gpio.setup.call_count == setup_count

    def test_stop_disables_motor(self, stepper_config, mock_gpio):
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()
        motor.stop()

        # Enable pin set HIGH (motor disabled)
        mock_gpio.output.assert_called_with(22, mock_gpio.HIGH)
        mock_gpio.cleanup.assert_called_once()

    def test_stop_clears_available(self, stepper_config, mock_gpio):
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()
        assert motor.available
        motor.stop()
        assert not motor.available

    @patch("rover.stepper.time")
    def test_step_positive(self, mock_time, stepper_config, mock_gpio):
        mock_time.monotonic.return_value = 0.0
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()
        mock_gpio.output.reset_mock()

        motor.step(10)

        # Direction set HIGH for positive steps
        assert mock_gpio.output.call_args_list[0] == call(17, mock_gpio.HIGH)
        # 10 step pulses = 10 × (HIGH + LOW) = 20 step pin calls
        step_calls = [c for c in mock_gpio.output.call_args_list if c[0][0] == 27]
        assert len(step_calls) == 20

    @patch("rover.stepper.time")
    def test_step_negative(self, mock_time, stepper_config, mock_gpio):
        mock_time.monotonic.return_value = 0.0
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()
        mock_gpio.output.reset_mock()

        motor.step(-5)

        # Direction set LOW for negative steps
        assert mock_gpio.output.call_args_list[0] == call(17, mock_gpio.LOW)
        step_calls = [c for c in mock_gpio.output.call_args_list if c[0][0] == 27]
        assert len(step_calls) == 10  # 5 × (HIGH + LOW)

    @patch("rover.stepper.time")
    def test_step_zero(self, mock_time, stepper_config, mock_gpio):
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()
        mock_gpio.output.reset_mock()

        motor.step(0)

        # Only the enable call from start, nothing more
        step_calls = [c for c in mock_gpio.output.call_args_list if c[0][0] == 27]
        assert len(step_calls) == 0

    @patch("rover.stepper.time")
    def test_step_updates_position(self, mock_time, stepper_config, mock_gpio):
        mock_time.monotonic.return_value = 0.0
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()

        motor.step(800)  # 800 / 3200 * 360 = 90°
        assert motor.current_angle == pytest.approx(90.0)

    @patch("rover.stepper.time")
    def test_step_negative_updates_position(self, mock_time, stepper_config, mock_gpio):
        mock_time.monotonic.return_value = 0.0
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()

        motor.step(800)
        motor.step(-400)  # Back to 45°
        assert motor.current_angle == pytest.approx(45.0)

    def test_step_not_available_raises(self, stepper_config):
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        with pytest.raises(RuntimeError, match="not available"):
            motor.step(10)

    @patch("rover.stepper.time")
    def test_move_to_angle(self, mock_time, stepper_config, mock_gpio):
        mock_time.monotonic.return_value = 0.0
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()

        motor.move_to_angle(90.0)
        assert motor.current_angle == pytest.approx(90.0)

    @patch("rover.stepper.time")
    def test_move_to_angle_reverse(self, mock_time, stepper_config, mock_gpio):
        mock_time.monotonic.return_value = 0.0
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()

        motor.move_to_angle(90.0)
        motor.move_to_angle(45.0)
        assert motor.current_angle == pytest.approx(45.0)

    @patch("rover.stepper.time")
    def test_move_to_angle_zero_delta(self, mock_time, stepper_config, mock_gpio):
        mock_time.monotonic.return_value = 0.0
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()
        mock_gpio.output.reset_mock()

        motor.move_to_angle(0.0)  # Already at 0
        step_calls = [c for c in mock_gpio.output.call_args_list if c[0][0] == 27]
        assert len(step_calls) == 0

    @patch("rover.stepper.time")
    def test_reset_position(self, mock_time, stepper_config, mock_gpio):
        mock_time.monotonic.return_value = 0.0
        from rover.stepper import StepperMotor

        motor = StepperMotor(stepper_config)
        motor.start()

        motor.step(800)
        assert motor.current_angle == pytest.approx(90.0)
        motor.reset_position()
        assert motor.current_angle == 0.0

    def test_context_manager(self, stepper_config, mock_gpio):
        from rover.stepper import StepperMotor

        with StepperMotor(stepper_config) as motor:
            assert motor.available
        assert not motor.available
        mock_gpio.cleanup.assert_called_once()

    def test_start_gpio_error_marks_unavailable(self, stepper_config, mock_gpio):
        from rover.stepper import StepperMotor

        mock_gpio.setup.side_effect = RuntimeError("GPIO permission denied")
        motor = StepperMotor(stepper_config)
        motor.start()
        assert not motor.available
