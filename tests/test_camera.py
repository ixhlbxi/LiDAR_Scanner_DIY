"""Unit tests for rover.camera — runs anywhere, no hardware required."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rover.config import CameraConfig
from rover.camera import Camera


@pytest.fixture
def camera_config():
    return CameraConfig(
        enabled=True,
        resolution=(1920, 1080),
        capture_cadence=1,
        jpeg_quality=85,
        output_folder="images",
    )


@pytest.fixture
def disabled_config():
    return CameraConfig(
        enabled=False,
        resolution=(1920, 1080),
        capture_cadence=1,
        jpeg_quality=85,
        output_folder="images",
    )


@pytest.fixture
def mock_picamera2():
    """Patch picamera2 and availability flag for off-Pi testing."""
    mock_cam = MagicMock()
    mock_cam_class = MagicMock(return_value=mock_cam)
    with (
        patch("rover.camera._CAMERA_AVAILABLE", True),
        patch("rover.camera.Picamera2", mock_cam_class),
        patch("rover.camera.time"),
    ):
        yield mock_cam


# ---------------------------------------------------------------------------
# Tests without picamera2
# ---------------------------------------------------------------------------


class TestCameraNoHardware:
    def test_init_disabled(self, disabled_config):
        cam = Camera(disabled_config)
        assert not cam.available

    def test_start_disabled(self, disabled_config):
        cam = Camera(disabled_config)
        cam.start()
        assert not cam.available

    def test_start_without_picamera2(self, camera_config):
        with patch("rover.camera._CAMERA_AVAILABLE", False):
            cam = Camera(camera_config)
            cam.start()
            assert not cam.available

    def test_stop_idempotent(self, camera_config):
        cam = Camera(camera_config)
        cam.stop()  # Should not raise

    def test_capture_not_available(self, camera_config, tmp_path):
        cam = Camera(camera_config)
        with pytest.raises(RuntimeError, match="not available"):
            cam.capture(tmp_path, 0)


# ---------------------------------------------------------------------------
# Tests with mocked picamera2
# ---------------------------------------------------------------------------


class TestCameraWithMock:
    def test_start_initializes(self, camera_config, mock_picamera2):
        cam = Camera(camera_config)
        cam.start()
        assert cam.available
        mock_picamera2.create_still_configuration.assert_called_once()
        mock_picamera2.configure.assert_called_once()
        mock_picamera2.start.assert_called_once()

    def test_double_start_ignored(self, camera_config, mock_picamera2):
        cam = Camera(camera_config)
        cam.start()
        cam.start()  # Should not raise
        assert cam.available

    def test_stop_closes_camera(self, camera_config, mock_picamera2):
        cam = Camera(camera_config)
        cam.start()
        cam.stop()
        mock_picamera2.stop.assert_called_once()
        mock_picamera2.close.assert_called_once()
        assert not cam.available

    def test_context_manager(self, camera_config, mock_picamera2):
        with Camera(camera_config) as cam:
            assert cam.available
        assert not cam.available

    def test_capture_creates_file(self, camera_config, mock_picamera2, tmp_path):
        cam = Camera(camera_config)
        cam.start()
        result = cam.capture(tmp_path, 47)

        assert result == "images/img_000047.jpg"
        mock_picamera2.capture_file.assert_called_once()
        # Verify the images directory was created
        assert (tmp_path / "images").exists()

    def test_capture_increments_count(self, camera_config, mock_picamera2, tmp_path):
        cam = Camera(camera_config)
        cam.start()
        assert cam.capture_count == 0
        cam.capture(tmp_path, 0)
        assert cam.capture_count == 1
        cam.capture(tmp_path, 1)
        assert cam.capture_count == 2

    def test_capture_filename_format(self, camera_config, mock_picamera2, tmp_path):
        cam = Camera(camera_config)
        cam.start()
        result = cam.capture(tmp_path, 123)
        assert result == "images/img_000123.jpg"

    def test_should_capture_cadence_1(self, camera_config):
        cam = Camera(camera_config)
        assert cam.should_capture(0)
        assert cam.should_capture(1)
        assert cam.should_capture(99)

    def test_should_capture_cadence_3(self):
        config = CameraConfig(
            enabled=True,
            resolution=(1920, 1080),
            capture_cadence=3,
            jpeg_quality=85,
            output_folder="images",
        )
        cam = Camera(config)
        assert cam.should_capture(0)
        assert not cam.should_capture(1)
        assert not cam.should_capture(2)
        assert cam.should_capture(3)
        assert not cam.should_capture(4)

    def test_start_picamera2_error(self, camera_config):
        mock_cam = MagicMock()
        mock_cam.start.side_effect = RuntimeError("Camera not found")
        with (
            patch("rover.camera._CAMERA_AVAILABLE", True),
            patch("rover.camera.Picamera2", return_value=mock_cam),
            patch("rover.camera.time"),
        ):
            cam = Camera(camera_config)
            cam.start()
            assert not cam.available
