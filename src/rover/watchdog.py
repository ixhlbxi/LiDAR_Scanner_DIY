"""
Health monitoring and heartbeat watchdog.

Monitors the main acquisition loop for hangs or crashes.
If no heartbeat is received within timeout_sec, triggers recovery
(log error, attempt restart, or safe shutdown).

Decision references:
    Architecture §9.1 — Failure modes and recovery

Dependencies:
    stdlib only (threading, time)
"""

from __future__ import annotations

import logging

from rover.config import WatchdogConfig

logger = logging.getLogger(__name__)


class Watchdog:
    """Heartbeat-based health monitor.

    Args:
        config: WatchdogConfig section from rover config.
    """

    def __init__(self, config: WatchdogConfig) -> None:
        self._config = config
        self._running = False
        logger.info("Watchdog initialized (timeout=%ds, heartbeat=%ds)",
                     config.timeout_sec, config.heartbeat_interval_sec)

    def start(self) -> None:
        """Start the watchdog monitor thread."""
        raise NotImplementedError("Watchdog.start() not yet implemented")

    def stop(self) -> None:
        """Stop the watchdog monitor."""
        raise NotImplementedError("Watchdog.stop() not yet implemented")

    def heartbeat(self) -> None:
        """Signal that the main loop is alive. Call periodically."""
        raise NotImplementedError("Watchdog.heartbeat() not yet implemented")
