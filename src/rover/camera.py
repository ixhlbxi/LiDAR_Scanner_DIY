"""
Raspberry Pi HQ Camera capture via picamera2.

Captures JPEG images at each rotation step for visual context.
Images are associated with scan data via step_index and timestamp.

The camera provides reference imagery, not photogrammetry input (DEC-026).
Capture cadence is configurable (every N steps).

Decision references:
    DEC-026  Camera as visual reference
    DEC-027  Triggered capture per rotation step

Dependencies:
    picamera2

Changelog:
    0.1.0  2026-03-22  Stub
    0.2.0  2026-03-22  Full implementation
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from rover.config import CameraConfig

logger = logging.getLogger(__name__)

try:
    from picamera2 import Picamera2
    _CAMERA_AVAILABLE = True
except ImportError:
    Picamera2 = None  # type: ignore[assignment, misc]
    _CAMERA_AVAILABLE = False


class Camera:
    """Pi HQ Camera driver for context imagery capture.

    Args:
        config: CameraConfig section from rover config.
    """

    def __init__(self, config: CameraConfig) -> None:
        self._config = config
        self._available = False
        self._started = False
        self._cam = None
        self._capture_count = 0

        if not config.enabled:
            logger.info("Camera disabled by config")
            return

        if not _CAMERA_AVAILABLE:
            logger.warning(
                "Camera enabled but picamera2 not available — running without hardware"
            )
            return

        logger.info(
            "Camera initialized (resolution=%s, quality=%d, cadence=%d)",
            config.resolution, config.jpeg_quality, config.capture_cadence,
        )

    @property
    def available(self) -> bool:
        """Whether the camera hardware is initialized and usable."""
        return self._available

    def start(self) -> None:
        """Initialize picamera2 and configure capture settings."""
        if not self._config.enabled:
            logger.info("Camera disabled, skipping start")
            return

        if not _CAMERA_AVAILABLE:
            logger.warning("Cannot start camera: picamera2 unavailable")
            return

        if self._started:
            logger.warning("Camera already started")
            return

        try:
            self._cam = Picamera2()
            w, h = self._config.resolution
            still_config = self._cam.create_still_configuration(
                main={"size": (w, h), "format": "RGB888"}
            )
            self._cam.configure(still_config)
            self._cam.start()
            # Allow auto-exposure to settle
            time.sleep(1.0)
        except Exception:
            logger.warning("Failed to initialize camera", exc_info=True)
            self._available = False
            try:
                if self._cam is not None:
                    self._cam.close()
            except Exception:
                pass
            self._cam = None
            return

        self._started = True
        self._available = True
        self._capture_count = 0
        logger.info("Camera started (%dx%d)", w, h)

    def stop(self) -> None:
        """Stop camera and release resources."""
        if not self._started:
            return

        try:
            if self._cam is not None:
                self._cam.stop()
                self._cam.close()
        except Exception:
            pass

        self._cam = None
        self._started = False
        self._available = False
        logger.info("Camera stopped")

    def should_capture(self, step_index: int) -> bool:
        """Check whether this step should trigger a capture based on cadence.

        Args:
            step_index: Current rotation step index.

        Returns:
            True if a capture should be taken at this step.
        """
        return step_index % self._config.capture_cadence == 0

    def capture(self, output_dir: Path, step_index: int) -> str:
        """Capture a JPEG image and return the relative filename.

        Args:
            output_dir: Session directory (parent of images/ folder).
            step_index: Current rotation step index.

        Returns:
            Relative path to saved image (e.g. "images/img_000047.jpg").

        Raises:
            RuntimeError: If the camera is not available.
        """
        if not self._available or self._cam is None:
            raise RuntimeError("Camera not available")

        images_dir = Path(output_dir) / self._config.output_folder
        images_dir.mkdir(parents=True, exist_ok=True)

        filename = f"img_{step_index:06d}.jpg"
        relative_path = f"{self._config.output_folder}/{filename}"
        full_path = images_dir / filename

        self._cam.capture_file(
            str(full_path), format="jpeg", quality=self._config.jpeg_quality,
        )
        self._capture_count += 1

        logger.debug("Captured %s", relative_path)
        return relative_path

    @property
    def capture_count(self) -> int:
        """Total number of images captured this session."""
        return self._capture_count

    def __enter__(self) -> Camera:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
