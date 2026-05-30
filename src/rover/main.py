"""Rover orchestration and state machine (Stage A of v0.10 alignment).

Top-level entry point. Manages the scan lifecycle:

  1. Parse CLI args (optional config path, optional run duration)
  2. Load config; configure logging
  3. Initialize sensors under try/except (warn + continue on failure)
  4. Start session logger, telemetry router, NTRIP client, watchdog
  5. Run the acquisition loop: step → settle → lidar + imu + camera → log
  6. Publish RoverStatus on the configured interval
  7. Graceful shutdown on SIGINT/SIGTERM, on duration timeout, or on
     unrecoverable error.

Sensors that fail to initialize log a warning and are marked unavailable
rather than crashing the system (per the project's "don't crash" rule).

Usage:
    rover                                   # via pyproject.toml entry point
    python -m rover.main --config path.toml
    python -m rover.main --duration-sec 30  # bench timer

Decision references:
    D-020  Python on Pi OS Lite
    D-021  JSONL logging
    D-031  NTRIP-primary RTK (NtripClient wired here when client_location=pi)
    D-033  Triple-channel telemetry (TelemetryRouter wired here)

Changelog:
    0.10.1  2026-05-30  Real orchestrator (Stage A of deep-alignment overhaul).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from rover.config import RoverConfig, load_config
from rover.gnss import GnssFix, GnssReceiver
from rover.imu import ImuDriver
from rover.lidar import LidarScanner
from rover.logger import SessionLogger
from rover.ntrip import NtripClient, NtripStats
from rover.stepper import StepperMotor
from rover.telemetry import RoverStatus, TelemetryRouter, status_from_config
from rover.watchdog import Watchdog

# Optional import — Camera depends on picamera2 which may not be importable off-Pi.
# Failure to import is treated the same as the device being absent: the camera
# subsystem is unavailable, but the rest of the system runs.
try:
    from rover.camera import Camera
    _CAMERA_IMPORT_OK = True
except Exception as _e:  # pragma: no cover — import-time only
    Camera = None  # type: ignore[assignment]
    _CAMERA_IMPORT_OK = False
    _CAMERA_IMPORT_ERROR = _e

logger = logging.getLogger(__name__)


# Scan state constants — kept in sync with lora_protocol.SCAN_* values so the
# numeric we put in RoverStatus.scan_state lines up with the wire encoding.
SCAN_IDLE = 0
SCAN_SCANNING = 1
SCAN_PAUSED = 2
SCAN_ERROR = 3


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rover",
        description="PiLiDAR-RTK Rover — acquisition orchestrator",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to TOML config (defaults to built-in defaults if omitted).",
    )
    p.add_argument(
        "--duration-sec",
        type=float,
        default=None,
        help="If set, stop cleanly after N seconds. For bench tests / smoke runs.",
    )
    return p


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


def _bootstrap_logging() -> None:
    """Pre-load_config logging — INFO so the load_config banner is visible."""
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def _apply_config_log_level(config: RoverConfig) -> None:
    """Switch root logger to the level the user asked for in config."""
    level = getattr(logging, config.general.log_level, logging.INFO)
    logging.getLogger().setLevel(level)


# ---------------------------------------------------------------------------
# Sensor init — each sensor's failure is isolated
# ---------------------------------------------------------------------------


class _Sensors:
    """Container for initialized sensor instances. Holds None when init failed."""

    def __init__(self) -> None:
        self.stepper: Optional[StepperMotor] = None
        self.lidar: Optional[LidarScanner] = None
        self.imu: Optional[ImuDriver] = None
        self.camera: Optional["Camera"] = None
        self.gnss: Optional[GnssReceiver] = None


def _init_sensors(config: RoverConfig) -> _Sensors:
    """Construct sensor instances; survive any individual failure."""
    sensors = _Sensors()

    if config.stepper.enabled:
        try:
            sensors.stepper = StepperMotor(config.stepper)
        except Exception as e:
            logger.warning("Stepper init failed: %s — subsystem disabled", e)

    if config.lidar.enabled:
        try:
            sensors.lidar = LidarScanner(config.lidar)
        except Exception as e:
            logger.warning("LiDAR init failed: %s — subsystem disabled", e)

    if config.imu.enabled:
        try:
            sensors.imu = ImuDriver(config.imu)
        except Exception as e:
            logger.warning("IMU init failed: %s — subsystem disabled", e)

    if config.camera.enabled and _CAMERA_IMPORT_OK:
        try:
            sensors.camera = Camera(config.camera)
        except Exception as e:
            logger.warning("Camera init failed: %s — subsystem disabled", e)
    elif config.camera.enabled and not _CAMERA_IMPORT_OK:
        logger.warning(
            "Camera enabled but picamera2 import failed (%s) — subsystem disabled",
            _CAMERA_IMPORT_ERROR,
        )

    if config.gnss.enabled:
        try:
            sensors.gnss = GnssReceiver(config)
        except Exception as e:
            logger.warning("GNSS init failed: %s — subsystem disabled", e)

    return sensors


def _start_sensors(sensors: _Sensors) -> None:
    """Call start() on each constructed sensor. Each failure isolated."""
    for name, obj in (
        ("stepper", sensors.stepper),
        ("lidar", sensors.lidar),
        ("imu", sensors.imu),
        ("camera", sensors.camera),
        ("gnss", sensors.gnss),
    ):
        if obj is None:
            continue
        try:
            obj.start()
        except Exception as e:
            logger.warning("%s start failed: %s — subsystem disabled", name, e)


def _stop_sensors(sensors: _Sensors) -> None:
    """Stop sensors in reverse-of-start order. Each failure isolated."""
    for name, obj in (
        ("camera", sensors.camera),
        ("lidar", sensors.lidar),
        ("imu", sensors.imu),
        ("stepper", sensors.stepper),
        ("gnss", sensors.gnss),
    ):
        if obj is None:
            continue
        try:
            obj.stop()
        except Exception as e:
            logger.warning("%s stop failed: %s", name, e)


# ---------------------------------------------------------------------------
# Acquisition loop
# ---------------------------------------------------------------------------


def _scan_loop(
    config: RoverConfig,
    sensors: _Sensors,
    session_logger: SessionLogger,
    telemetry: TelemetryRouter,
    watchdog: Optional[Watchdog],
    ntrip_stats_holder: dict,
    stop_event: threading.Event,
    duration_sec: Optional[float],
) -> None:
    """Run the acquisition loop until stop_event is set or duration elapses.

    The loop is robust to all-sensors-disabled — in that case it idles on a
    1Hz heartbeat + telemetry publish. That's the bench/test mode.
    """
    status = status_from_config(config)
    status.scan_state = SCAN_SCANNING

    # Cadence bookkeeping
    publish_interval = config.base_station_integration.publish_interval_sec or 1.0
    last_publish = 0.0
    last_logged_fix_ts: float = -1.0

    # Steps-per-increment derived from stepper geometry
    if sensors.stepper is not None and sensors.stepper.available:
        steps_per_increment = max(
            1,
            int(round(config.stepper.step_interval_deg
                      / (360.0 / config.stepper.steps_per_rev))),
        )
        settle_sec = 1.0 / max(1, config.lidar.scan_rate_hz)
    else:
        steps_per_increment = 0
        settle_sec = 1.0  # idle pace when nothing to step

    step_index = 0
    started_monotonic = time.monotonic()

    while not stop_event.is_set():
        # Honor duration timeout for bench runs
        if duration_sec is not None and (time.monotonic() - started_monotonic) >= duration_sec:
            logger.info("Duration timeout (%.1fs) reached — stopping", duration_sec)
            break

        if watchdog is not None:
            try:
                watchdog.heartbeat()
            except Exception:
                pass

        # --- Step + settle ---
        if sensors.stepper is not None and sensors.stepper.available and steps_per_increment > 0:
            try:
                sensors.stepper.step(steps_per_increment)
            except Exception as e:
                logger.warning("Stepper step failed: %s — pausing scan", e)
                status.scan_state = SCAN_ERROR
                stop_event.wait(0.5)
                continue
        time.sleep(settle_sec)

        # --- LiDAR ---
        lidar_points: list = []
        if sensors.lidar is not None and sensors.lidar.available:
            try:
                lidar_points = sensors.lidar.read_scan()
            except (RuntimeError, TimeoutError) as e:
                logger.debug("LiDAR read skipped: %s", e)

        # --- IMU ---
        imu_sample = None
        if sensors.imu is not None and sensors.imu.available:
            try:
                imu_sample = sensors.imu.read_sample()
            except RuntimeError as e:
                logger.debug("IMU read skipped: %s", e)

        # --- Camera (cadence-gated) ---
        image_relpath: Optional[str] = None
        if (
            sensors.camera is not None
            and sensors.camera.available
            and sensors.camera.should_capture(step_index)
            and session_logger.session_dir is not None
        ):
            try:
                image_relpath = sensors.camera.capture(
                    session_logger.session_dir, step_index
                )
            except RuntimeError as e:
                logger.debug("Camera capture skipped: %s", e)

        # --- Log records ---
        now = time.time()
        if lidar_points:
            session_logger.write({
                "type": "lidar",
                "timestamp": now,
                "step_index": step_index,
                "points": [
                    {"angle": p.angle, "distance": p.distance, "intensity": p.intensity}
                    for p in lidar_points
                ],
            })
        if imu_sample is not None:
            session_logger.write({
                "type": "imu",
                "timestamp": imu_sample.timestamp,
                "accel": list(imu_sample.accel),
                "gyro": list(imu_sample.gyro),
                "mag": list(imu_sample.mag) if imu_sample.mag is not None else None,
                "orientation": list(imu_sample.orientation),
            })
        if image_relpath is not None:
            session_logger.write({
                "type": "camera",
                "timestamp": now,
                "step_index": step_index,
                "filename": image_relpath,
            })

        # --- GNSS fix (log + status update; only on new fix) ---
        gnss_fix: Optional[GnssFix] = None
        if sensors.gnss is not None:
            try:
                gnss_fix = sensors.gnss.latest_fix()
            except Exception:
                gnss_fix = None
        if gnss_fix is not None and gnss_fix.timestamp > last_logged_fix_ts:
            session_logger.write({
                "type": "gnss",
                "timestamp": gnss_fix.timestamp,
                "fix_type": gnss_fix.fix_type,
                "lat": gnss_fix.lat,
                "lon": gnss_fix.lon,
                "alt": gnss_fix.alt,
                "hdop": gnss_fix.hdop,
                "vdop": gnss_fix.vdop,
                "sat_count": gnss_fix.sat_count,
                "rtk_age": gnss_fix.rtk_age,
            })
            last_logged_fix_ts = gnss_fix.timestamp
            status.fix_type = gnss_fix.fix_type
            status.sat_count = gnss_fix.sat_count
            status.hdop = gnss_fix.hdop
            status.lat = gnss_fix.lat
            status.lon = gnss_fix.lon
            status.alt_m = gnss_fix.alt
            status.rtk_age_s = gnss_fix.rtk_age

        # --- Telemetry publish (cadenced) ---
        now_monotonic = time.monotonic()
        if now_monotonic - last_publish >= publish_interval:
            status.timestamp_epoch = now
            ntrip_stats = ntrip_stats_holder.get("stats")
            if isinstance(ntrip_stats, NtripStats):
                status.ntrip_connected = ntrip_stats.connected
                status.ntrip_bytes_per_sec = ntrip_stats.bytes_received_this_sec
            telemetry.publish(status)
            last_publish = now_monotonic

        step_index += 1


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    config_path: Optional[Path] = None,
    duration_sec: Optional[float] = None,
    stop_event: Optional[threading.Event] = None,
) -> int:
    """Programmatic entry — same flow as main(), but with no CLI parsing.

    Args:
        config_path: TOML path or None for defaults.
        duration_sec: If set, exit cleanly after this many seconds.
        stop_event: Externally-controlled stop signal. If None, one is created
            here and wired to SIGINT/SIGTERM.

    Returns:
        Process exit code (0 on clean exit).
    """
    _bootstrap_logging()
    try:
        config = load_config(config_path)
    except Exception as e:
        logger.error("Failed to load config: %s", e)
        return 2
    _apply_config_log_level(config)

    # --- Signal handling (only if caller didn't supply a stop_event) ---
    owns_signals = stop_event is None
    if stop_event is None:
        stop_event = threading.Event()

    def _handle_signal(signum: int, _frame) -> None:
        logger.info("Received signal %d — shutting down", signum)
        stop_event.set()  # noqa: F821 — captured

    if owns_signals:
        # Only the main thread can install signal handlers.
        try:
            signal.signal(signal.SIGINT, _handle_signal)
            try:
                signal.signal(signal.SIGTERM, _handle_signal)
            except (AttributeError, ValueError):
                # SIGTERM absent on some platforms; that's fine
                pass
        except ValueError:
            # Not in main thread (e.g. test runner) — caller must drive stop_event
            logger.debug("Signal handlers not installed (not main thread)")

    # --- Sensors ---
    sensors = _init_sensors(config)
    _start_sensors(sensors)

    # --- Session logger ---
    session_logger = SessionLogger(config, config_path=config_path)
    try:
        session_logger.start()
    except Exception as e:
        logger.error("SessionLogger.start() failed: %s — aborting", e)
        _stop_sensors(sensors)
        return 3
    session_logger.write({
        "type": "event",
        "timestamp": time.time(),
        "event": "scan_start",
        "details": {"profile": config.session.profile},
    })

    # --- Telemetry ---
    telemetry = TelemetryRouter(config)
    telemetry.start()

    # --- NTRIP (Pi-mode only — ESP32 mode owns the path itself) ---
    ntrip_client: Optional[NtripClient] = None
    ntrip_stats_holder: dict = {"stats": None}

    def _ntrip_stats_sink(stats: NtripStats) -> None:
        ntrip_stats_holder["stats"] = stats

    if (
        config.ntrip.enabled
        and config.ntrip.client_location == "pi"
        and sensors.gnss is not None
    ):
        try:
            ntrip_client = NtripClient(
                config,
                rtcm_sink=sensors.gnss.write_rtcm,
                status_sink=_ntrip_stats_sink,
            )
            ntrip_client.start()
        except Exception as e:
            logger.warning("NtripClient start failed: %s — RTK degraded", e)
            ntrip_client = None

    # --- Watchdog ---
    watchdog: Optional[Watchdog] = None
    if config.watchdog.enabled:
        try:
            watchdog = Watchdog(config.watchdog)
            watchdog.start()
        except Exception as e:
            logger.warning("Watchdog start failed: %s — running without health monitor", e)
            watchdog = None

    # --- Acquisition loop ---
    exit_code = 0
    try:
        _scan_loop(
            config=config,
            sensors=sensors,
            session_logger=session_logger,
            telemetry=telemetry,
            watchdog=watchdog,
            ntrip_stats_holder=ntrip_stats_holder,
            stop_event=stop_event,
            duration_sec=duration_sec,
        )
    except Exception as e:
        logger.exception("Acquisition loop crashed: %s", e)
        exit_code = 1
    finally:
        session_logger.write({
            "type": "event",
            "timestamp": time.time(),
            "event": "scan_complete" if exit_code == 0 else "scan_abort",
        })

        # --- Reverse-order teardown ---
        if watchdog is not None:
            try:
                watchdog.stop()
            except Exception as e:
                logger.warning("Watchdog stop failed: %s", e)

        if ntrip_client is not None:
            try:
                ntrip_client.stop()
            except Exception as e:
                logger.warning("NtripClient stop failed: %s", e)

        try:
            telemetry.stop()
        except Exception as e:
            logger.warning("TelemetryRouter stop failed: %s", e)

        _stop_sensors(sensors)

        # Metadata fields populated from runtime
        metadata: dict = {}
        ntrip_stats = ntrip_stats_holder.get("stats")
        if isinstance(ntrip_stats, NtripStats):
            metadata["ntrip_stats"] = asdict(ntrip_stats)
        metadata["lora_rtcm_used"] = (
            config.lora.enabled and config.lora.role == "rtcm_rx+status_tx"
        )

        try:
            session_logger.stop(metadata=metadata)
        except Exception as e:
            logger.warning("SessionLogger stop failed: %s", e)

    return exit_code


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point — used by `rover` console script and `python -m rover.main`."""
    args = _build_argparser().parse_args(argv)
    return run(config_path=args.config, duration_sec=args.duration_sec)


if __name__ == "__main__":
    sys.exit(main())
