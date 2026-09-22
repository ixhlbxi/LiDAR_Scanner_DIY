"""Unit tests for the heartbeat watchdog."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from rover import watchdog as wd_mod
from rover.config import WatchdogConfig
from rover.watchdog import Watchdog


@pytest.fixture
def fast_config() -> WatchdogConfig:
    """A watchdog that checks every poll and times out fast — for unit tests."""
    # heartbeat_interval_sec and timeout_sec are ints in the dataclass; we use
    # the smallest legal values (1) and verify behavior with sub-second sleeps.
    return WatchdogConfig(enabled=True, timeout_sec=1, heartbeat_interval_sec=1)


def test_disabled_watchdog_never_starts_thread() -> None:
    cfg = WatchdogConfig(enabled=False, timeout_sec=1, heartbeat_interval_sec=1)
    wd = Watchdog(cfg)
    wd.start()
    # No thread because disabled
    assert wd._thread is None  # type: ignore[attr-defined]
    wd.stop()  # still safe to call


def test_heartbeat_keeps_watchdog_alive(fast_config: WatchdogConfig) -> None:
    fired = threading.Event()
    wd = Watchdog(fast_config, on_timeout=fired.set)
    wd.start()
    try:
        # Send heartbeats inside the timeout window for ~2.5s; should never fire
        end = time.monotonic() + 2.5
        while time.monotonic() < end:
            wd.heartbeat()
            time.sleep(0.2)
        assert not fired.is_set(), "watchdog fired even though heartbeats arrived"
    finally:
        wd.stop()


def test_missed_heartbeat_fires_callback(fast_config: WatchdogConfig) -> None:
    fired = threading.Event()
    wd = Watchdog(fast_config, on_timeout=fired.set)
    wd.start()
    try:
        # Don't send any heartbeats — should fire within ~2 polls of the 1s
        # interval plus 1s timeout = ~3s worst case
        assert fired.wait(timeout=4.0), "watchdog did not fire on missing heartbeat"
    finally:
        wd.stop()


def test_callback_fires_only_once(fast_config: WatchdogConfig) -> None:
    count = {"n": 0}

    def increment() -> None:
        count["n"] += 1

    wd = Watchdog(fast_config, on_timeout=increment)
    wd.start()
    try:
        # Wait long enough for multiple poll cycles after the first fire
        time.sleep(4.0)
        assert count["n"] == 1, f"callback fired {count['n']} times, expected 1"
    finally:
        wd.stop()


def test_stop_is_idempotent(fast_config: WatchdogConfig) -> None:
    wd = Watchdog(fast_config)
    wd.start()
    wd.stop()
    wd.stop()  # should not raise


def test_default_timeout_exits_process_with_code_2() -> None:
    """The default callback must end the PROCESS, not just the monitor thread (T1-001)."""
    script = (
        "import time\n"
        "from rover.config import WatchdogConfig\n"
        "from rover.watchdog import Watchdog\n"
        "wd = Watchdog(WatchdogConfig(enabled=True, timeout_sec=1, heartbeat_interval_sec=1))\n"
        "wd.start()\n"
        "time.sleep(10)\n"  # never heartbeats; must be killed long before this
        "print('STILL ALIVE')\n"
    )
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=8,
        env={**os.environ, "PYTHONPATH": src_dir},
    )
    assert proc.returncode == 2, proc.stderr
    assert "STILL ALIVE" not in proc.stdout


@pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason=(
        "AF_UNIX not exposed by this Python/OS build (observed on the official "
        "python.org Windows 3.13/3.14 builds on this machine, which are compiled "
        "without AF_UNIX support even though Windows itself supports it since "
        "10 build 17063). Production runs on Raspberry Pi OS (Linux), where "
        "AF_UNIX is always available."
    ),
)
def test_sd_notify_reuses_one_socket(monkeypatch, tmp_path) -> None:
    """One connected datagram socket per process, not one per heartbeat."""
    monkeypatch.setenv("NOTIFY_SOCKET", "@rover-test-notify")
    wd_mod._reset_notify_socket_for_tests()
    fake = mock.MagicMock()
    with mock.patch("rover.watchdog.socket.socket", return_value=fake) as ctor:
        wd_mod._sd_notify("READY=1\n")
        wd_mod._sd_notify("WATCHDOG=1\n")
        wd_mod._sd_notify("WATCHDOG=1\n")
    assert ctor.call_count == 1
    assert fake.sendall.call_count == 3
    wd_mod._reset_notify_socket_for_tests()
