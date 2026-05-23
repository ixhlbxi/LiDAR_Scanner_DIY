"""
Hardware diagnostic: end-to-end NTRIP + F9P RTK FIX verification.

Connects to the Base-Station's NTRIP caster (default `rtk-base.local:2101/ARM_BASE`),
streams RTCM into the ZED-F9P over USB, and watches the F9P's NMEA GGA output for
RTK FLOAT → RTK FIX promotion.

Run on the rover Pi with both:
    - the F9P connected (USB; default /dev/ttyACM0)
    - the Base-Station Pi reachable on the network (rtk-base.local)
    - the env var ROVER_NTRIP_PASSWORD set

Usage:
    export ROVER_NTRIP_PASSWORD='...'
    python -m tests.hardware.test_ntrip                # default: 60 s observation
    python -m tests.hardware.test_ntrip --duration 30
    python -m tests.hardware.test_ntrip --caster 192.168.1.50:2101 --mountpoint ARM_BASE

This is not a pytest unit test. It exits 0 on success (RTK FIX achieved), 1
otherwise. Designed for field commissioning + bench bring-up.

Decision references:
    D-031 NTRIP-primary RTK
    D-032 NTRIP client location (this script exercises the Pi-side path)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Make the project src importable when run directly.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from rover.config import load_config  # noqa: E402
from rover.gnss import GnssReceiver, GnssFix  # noqa: E402
from rover.ntrip import NtripClient  # noqa: E402

logger = logging.getLogger("rover-test-ntrip")


def _fix_type_name(fix_type: int) -> str:
    return {
        0: "NONE", 1: "2D", 2: "3D", 3: "DGPS", 4: "FLOAT", 5: "FIX",
    }.get(fix_type, f"?{fix_type}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=Path("config/default.toml"),
                        help="Rover TOML config (default: config/default.toml)")
    parser.add_argument("--caster", type=str, default=None,
                        help="Override caster as host:port")
    parser.add_argument("--mountpoint", type=str, default=None,
                        help="Override caster mountpoint")
    parser.add_argument("--duration", type=float, default=60.0,
                        help="Observation window in seconds (default: 60)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cfg = load_config(args.config)

    if not cfg.ntrip.enabled:
        logger.error(
            "[ntrip] enabled = false in %s — set it to true and re-run "
            "(or pass a config with NTRIP enabled).", args.config,
        )
        return 1

    if cfg.ntrip.client_location != "pi":
        logger.error(
            "[ntrip] client_location = %r — this script only tests the Pi-side "
            "path. For ESP32-hosted NTRIP, verify via the firmware monitor.",
            cfg.ntrip.client_location,
        )
        return 1

    if not os.environ.get(cfg.ntrip.password_env):
        logger.warning(
            "Env var %s is not set — caster will see a blank password and may reject.",
            cfg.ntrip.password_env,
        )

    # If --caster / --mountpoint were supplied, override (need to roll a new
    # config — but for diagnostic purposes a small mutation is fine).
    if args.caster or args.mountpoint:
        # Construct a fresh dict from the existing config and re-validate via load_config?
        # Simpler: poke the frozen dataclass via object.__setattr__ for this script only.
        if args.caster:
            host, _, port = args.caster.partition(":")
            object.__setattr__(cfg.ntrip, "caster_host", host)
            object.__setattr__(cfg.ntrip, "caster_port", int(port) if port else 2101)
        if args.mountpoint:
            object.__setattr__(cfg.ntrip, "mountpoint", args.mountpoint)

    logger.info(
        "Target: %s:%d/%s  (user=%s)",
        cfg.ntrip.caster_host, cfg.ntrip.caster_port,
        cfg.ntrip.mountpoint, cfg.ntrip.username,
    )

    # --- Bring up the F9P reader ---
    gnss = GnssReceiver(cfg)
    gnss.start()
    time.sleep(0.5)

    # --- Bring up the NTRIP client; pipe RTCM into the F9P ---
    ntrip = NtripClient(cfg, rtcm_sink=gnss.write_rtcm)
    ntrip.start()

    # --- Observe for the requested duration ---
    deadline = time.monotonic() + args.duration
    best_fix_type = 0
    last_log = 0.0
    fix_at: dict[int, float] = {}

    try:
        while time.monotonic() < deadline:
            fix: GnssFix | None = gnss.latest_fix()
            ntrip_stats = ntrip.stats
            now = time.monotonic()
            if fix is not None and fix.fix_type not in fix_at:
                fix_at[fix.fix_type] = now
                logger.info(
                    "Fix transition → %s (sats=%d hdop=%.2f rtk_age=%.1f)",
                    _fix_type_name(fix.fix_type), fix.sat_count, fix.hdop, fix.rtk_age,
                )
            if fix is not None:
                best_fix_type = max(best_fix_type, fix.fix_type)

            if now - last_log >= 5.0:
                last_log = now
                logger.info(
                    "[ntrip] connected=%s bytes_total=%d  [gnss] fix=%s sats=%d hdop=%.2f",
                    ntrip_stats.connected,
                    ntrip_stats.bytes_received_total,
                    _fix_type_name(fix.fix_type) if fix else "?",
                    fix.sat_count if fix else 0,
                    fix.hdop if fix else 99.9,
                )
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        ntrip.stop()
        gnss.stop()

    logger.info(
        "Best fix observed: %s. Total RTCM bytes received: %d. Errors: %d.",
        _fix_type_name(best_fix_type),
        ntrip.stats.bytes_received_total,
        ntrip.stats.error_count,
    )

    if best_fix_type >= 5:
        logger.info("RESULT: SUCCESS — RTK FIX achieved.")
        return 0
    if best_fix_type == 4:
        logger.warning("RESULT: PARTIAL — RTK FLOAT only. Check sky view / RTCM age.")
        return 1
    logger.error("RESULT: FAILURE — RTK never engaged. Check caster + credentials.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
