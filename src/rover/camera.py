"""
Raspberry Pi HQ Camera capture via picamera2.

Captures JPEG images at each rotation step for visual context.
Images are associated with scan data via step_index and timestamp.

The camera provides reference imagery, not photogrammetry input (D-026).
Capture cadence is configurable (every N steps).

Decision references:
    D-026  Camera as visual reference
    D-027  Triggered capture per rotation step

Dependencies:
    picamera2
"""

from __future__ import annotations

import logging
from pathlib import Path

from rover.config import CameraConfig

logger = logging.getLogger(__name__)


class Camera:
    """Pi HQ Camera driver for context imagery capture.

    Args:
        config: CameraConfig section from rover config.
    """

    def __init__(self, config: CameraConfig) -> None:
        self._config = config
        self._capture_count = 0
        logger.info(
            "Camera initialized (resolution=%s, quality=%d, cadence=%d)",
            config.resolution, config.jpeg_quality, config.capture_cadence,
        )

    def start(self) -> None:
        """Initialize picamera2 and configure capture settings."""
        raise NotImplementedError("Camera.start() not yet implemented")

    def stop(self) -> None:
        """Stop camera and release resources."""
        raise NotImplementedError("Camera.stop() not yet implemented")

    def capture(self, output_dir: Path, step_index: int) -> str:
        """Capture a JPEG image and return the relative filename.

        Args:
            output_dir: Session directory containing the images/ folder.
            step_index: Current rotation step index.

        Returns:
            Relative path to saved image (e.g. "images/img_000047.jpg").
        """
        raise NotImplementedError("Camera.capture() not yet implemented")
