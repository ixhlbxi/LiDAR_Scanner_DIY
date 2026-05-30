"""Health monitoring and heartbeat watchdog (Stage A of v0.10 alignment).

The main acquisition loop calls ``Watchdog.heartbeat()`` once per iteration.
A background daemon thread wakes every ``heartbeat_interval_sec`` and checks
how long it has been since the last heartbeat. If the gap exceeds
``timeout_sec``, it fires the configured ``on_timeout`` callback (default:
``sys.exit(2)``, which lets systemd restart us).

The thread is a daemon so it never holds the process up; ``stop()`` is the
clean shutdown path and joins.

Stage C will add sd_notify integration so this same heartbeat drives systemd's
``WatchdogSec=`` machinery. For now this module is stdlib-only.

Decision references:
    Architecture §9 — Failure modes and recovery

Changelog:
    0.10.1  2026-05-30  Real heartbeat thread (Stage A of deep-alignment overhaul).
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Callable, Optional

from rover.config import WatchdogConfig

logger = logging.getLogger(__name__)


# Default callback: process exit with a distinguishable code. Systemd's
# Restart=on-failure brings us back; standalone runs surface the failure
# to whoever launched us.
def _default_on_timeout() -> None:  # pragma: no cover — process-killing
    logger.error("Watchdog timeout — exiting with code 2")
    sys.exit(2)


class Watchdog:
    """Heartbeat-based health monitor.

    Args:
        config: WatchdogConfig — provides timeout_sec and heartbeat_interval_sec.
        on_timeout: Optional callback fired when timeout is exceeded. Defaults
            to a process-exit so systemd can restart us.
    """

    def __init__(
        self,
        config: WatchdogConfig,
        on_timeout: Optional[Callable[[], None]] = None,
    ) -> None:
        self._config = config
        self._on_timeout = on_timeout or _default_on_timeout
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_beat_monotonic: float = 0.0
        self._lock = threading.Lock()
        self._fired = False  # one-shot — don't re-fire on subsequent checks
        logger.info(
            "Watchdog initialized (timeout=%ds, heartbeat=%ds)",
            config.timeout_sec, config.heartbeat_interval_sec,
        )

    def start(self) -> None:
        """Start the watchdog monitor thread. Idempotent."""
        if not self._config.enabled:
            logger.info("Watchdog disabled by config; not starting monitor thread")
            return
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Watchdog.start() called twice — ignoring")
            return

        self._stop_event.clear()
        self._fired = False
        self._last_beat_monotonic = time.monotonic()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="rover-watchdog",
            daemon=True,
        )
        self._thread.start()
        logger.info("Watchdog started")

    def stop(self) -> None:
        """Stop the watchdog monitor. Safe to call multiple times."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Watchdog stopped")

    def heartbeat(self) -> None:
        """Signal that the main loop is alive. Call periodically (thread-safe)."""
        with self._lock:
            self._last_beat_monotonic = time.monotonic()

    def _last_beat_age(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_beat_monotonic

    def _run_loop(self) -> None:
        """Background thread: poll the heartbeat age and fire on timeout."""
        interval = float(self._config.heartbeat_interval_sec)
        timeout = float(self._config.timeout_sec)
        while not self._stop_event.wait(interval):
            age = self._last_beat_age()
            if age > timeout and not self._fired:
                self._fired = True
                logger.error(
                    "Watchdog timeout: last heartbeat %.1fs ago (limit %.1fs)",
                    age, timeout,
                )
                try:
                    self._on_timeout()
                except SystemExit:
                    raise
                except Exception as e:  # pragma: no cover — defensive
                    logger.exception("Watchdog on_timeout callback raised: %s", e)


__all__ = ["Watchdog"]
