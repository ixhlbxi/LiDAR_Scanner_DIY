"""Health monitoring and heartbeat watchdog.

The main acquisition loop calls ``Watchdog.heartbeat()`` once per iteration.
A background daemon thread wakes every ``heartbeat_interval_sec`` and checks
how long it has been since the last heartbeat. If the gap exceeds
``timeout_sec``, it fires the configured ``on_timeout`` callback (default:
``sys.exit(2)``, which lets systemd restart us).

The thread is a daemon so it never holds the process up; ``stop()`` is the
clean shutdown path and joins.

systemd integration (Stage C): if the ``NOTIFY_SOCKET`` env var is set (which
systemd does for ``Type=notify`` units), each ``heartbeat()`` also sends
``WATCHDOG=1`` to that socket. Pairs with the ``WatchdogSec=`` directive in
``deploy/systemd/rover.service``. ``start()`` sends ``READY=1`` once. Both
are no-ops when ``NOTIFY_SOCKET`` is absent (dev runs, off-Pi tests).
Same minimal sd_notify reimplementation the sibling repo uses (no
``python-systemd`` dep — the protocol is one UDP datagram).

Decision references:
    Architecture §9 — Failure modes and recovery

Changelog:
    0.10.1  2026-05-30  Real heartbeat thread (Stage A of deep-alignment overhaul).
    0.10.3  2026-05-30  sd_notify READY=1 / WATCHDOG=1 (Stage C).
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
from typing import Callable, Optional

from rover.config import WatchdogConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# sd_notify — stdlib-only implementation of the protocol
# ---------------------------------------------------------------------------


def _sd_notify(message: str) -> None:
    """Send a notification message to systemd via $NOTIFY_SOCKET.

    Silent no-op if NOTIFY_SOCKET is unset (e.g. running under a dev shell
    instead of systemd). Mirrors the minimal helper in
    arm-drone-lidar-workflow/base-station/rtk_base_manager.py.
    """
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    # Linux abstract namespace: leading '@' is replaced with NUL byte.
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(message.encode("utf-8"))
    except OSError as e:
        # Don't let a notify failure kill the heartbeat path.
        logger.debug("sd_notify(%r) failed: %s", message, e)


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
        """Start the watchdog monitor thread. Idempotent.

        Also sends ``READY=1`` to systemd if running under a Type=notify unit.
        """
        if not self._config.enabled:
            logger.info("Watchdog disabled by config; not starting monitor thread")
            # Still notify systemd we're ready so the unit doesn't time out
            # waiting for READY=1 — the watchdog being disabled doesn't mean
            # the rover process is failing.
            _sd_notify("READY=1\n")
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
        _sd_notify("READY=1\n")
        logger.info("Watchdog started")

    def stop(self) -> None:
        """Stop the watchdog monitor. Safe to call multiple times."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("Watchdog stopped")

    def heartbeat(self) -> None:
        """Signal that the main loop is alive. Call periodically (thread-safe).

        Also pings systemd's watchdog if running under a Type=notify unit.
        """
        with self._lock:
            self._last_beat_monotonic = time.monotonic()
        _sd_notify("WATCHDOG=1\n")

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
