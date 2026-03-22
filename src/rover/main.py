"""
Rover orchestration and state machine.

Top-level entry point for the PiLiDAR-RTK rover. Manages the scan
lifecycle:
  1. Load config
  2. Initialize sensors (skip disabled ones)
  3. Start session logging
  4. Run scan loop: step → settle → acquire LiDAR + IMU + camera → log
  5. Generate telemetry
  6. Handle graceful shutdown

Sensors that fail to initialize log a warning and are marked unavailable
rather than crashing the system.

Usage:
    rover              # via pyproject.toml entry point
    python -m rover.main

Decision references:
    D-020  Python on Pi OS Lite
    All sensor decisions (D-005 through D-029)
"""

from __future__ import annotations

import logging
import sys

from rover.config import load_config

logger = logging.getLogger(__name__)


def main() -> int:
    """Rover main entry point."""
    # TODO: Implement full state machine
    #
    # Planned flow:
    #   1. Parse CLI args (optional config path)
    #   2. load_config() with user overrides
    #   3. Configure logging from config.general.log_level
    #   4. Log effective config at INFO level
    #   5. Initialize sensors (each guarded by try/except + enabled flag)
    #   6. Start session logger
    #   7. Run scan acquisition loop
    #   8. Graceful shutdown on SIGINT/SIGTERM
    #
    raise NotImplementedError("Rover main loop not yet implemented")


if __name__ == "__main__":
    sys.exit(main())
