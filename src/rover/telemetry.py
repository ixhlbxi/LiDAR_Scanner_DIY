"""Triple-channel telemetry router (D-033).

Routes rover status to three independent, individually enable-able publishers:

    Channel A — StatusJsonPublisher
        Atomic write to a configurable path (default /run/rover/status.json), shaped
        to be readable by anything that consumes arm-drone-lidar-workflow's
        /run/rtk-base/status.json. The atomic-write pattern mirrors
        base-station/rtk_io.py:atomic_write_json byte-for-byte.

    Channel B — LocalHttpPublisher
        Stdlib http.server on loopback (default :8090) exposing
        GET /status (current snapshot) and GET /health (liveness).

    Channel C — LoRaPublisher
        Encodes STATUS (0x01) and LINK (0x02) frames per the shared LoRa frame v2
        envelope (see rover.lora_protocol) and writes them to the rover ESP32
        over USB serial. The ESP32 then broadcasts over LoRa.

Each publisher's lifecycle (start/stop) is independent; one publisher failing or
being disabled never takes down the others.

Public API:
    RoverStatus       — dataclass; current rover snapshot for routing
    TelemetryRouter   — composes the configured channels and fans out publish()
    StatusJsonPublisher / LocalHttpPublisher / LoRaPublisher — individual channels
    atomic_write_json — mirror of the Base-Station's helper (so external code can
                        reuse it for tests / sidecar consumers)

Decision references: D-033 (this whole module exists for D-033).

Dependencies: stdlib only (pyserial is imported lazily inside LoRaPublisher.start()
so off-Pi tests don't require it).

Changelog:
    0.10.0  2026-05-23  Initial multi-publisher router (Phase B of overhaul).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from rover.config import RoverConfig
from rover.lora_protocol import (
    TYPE_LINK,
    TYPE_STATUS,
    encode_frame,
    encode_link_payload,
    encode_status_payload,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RoverStatus — the canonical in-memory snapshot
# ---------------------------------------------------------------------------


@dataclass
class RoverStatus:
    """Current rover state — input to every telemetry channel.

    Field shape is the union of what any publisher needs. Publishers that don't
    care about a given field simply skip it.

    The status.json on-wire shape is derived from this in
    StatusJsonPublisher.build_payload(); the LoRa STATUS/LINK encodings live in
    lora_protocol.py.
    """

    timestamp_epoch: float = field(default_factory=time.time)
    # Session context (from RoverConfig.session)
    device: str = ""
    profile: str = ""
    mission: str = ""
    project_code: str = ""
    # GNSS
    fix_type: int = 0
    sat_count: int = 0
    hdop: float = 99.9
    lat: float = 0.0
    lon: float = 0.0
    alt_m: float = 0.0
    rtk_age_s: float = -1.0
    # Power
    battery_mv: int = 0
    # Scan state (see lora_protocol.SCAN_* constants)
    scan_state: int = 0
    # LoRa link metrics
    lora_link_rssi: int = -128
    lora_link_snr: int = -128
    # NTRIP client status
    ntrip_connected: bool = False
    ntrip_bytes_per_sec: int = 0


# ---------------------------------------------------------------------------
# atomic_write_json — port of arm-drone-lidar-workflow/base-station/rtk_io.py
# ---------------------------------------------------------------------------


def atomic_write_json(path: Path, data: dict) -> None:
    """Write *data* as JSON to *path* via mkstemp + os.rename.

    Mirrors `base-station/rtk_io.py:atomic_write_json`. Any process that already
    knows how to read /run/rtk-base/status.json can read this rover's status.json
    using the same expectations (atomicity, 0644 perms, trailing newline).

    Creates parent directory if absent. Raises on failure — callers log at
    whatever severity suits their context.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.write("\n")
        # Windows: chmod is mostly a no-op for 0o644 but harmless.
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        os.replace(tmp, str(path))  # os.replace is atomic on Windows too
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Publisher base + concrete channels
# ---------------------------------------------------------------------------


class _Publisher:
    """Common contract — start, publish(status), stop. Failures isolated."""

    name: str = "publisher"

    def start(self) -> None:
        pass

    def publish(self, status: RoverStatus) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        pass


class StatusJsonPublisher(_Publisher):
    """Channel A — Base-Station-compatible atomic status.json (D-033)."""

    name = "status_json"

    def __init__(self, config: RoverConfig) -> None:
        self._bsi = config.base_station_integration
        self._device = config.general.device_name
        self._schema_version = self._bsi.status_schema_version

    def publish(self, status: RoverStatus) -> None:
        payload = self.build_payload(status)
        try:
            atomic_write_json(Path(self._bsi.status_json_path), payload)
        except OSError as e:
            # Log-once-per-minute would be nicer; for v0.10 we log every failure.
            # status.json is non-critical — never raise out of publish().
            logger.warning("status.json write failed: %s", e)

    def build_payload(self, status: RoverStatus) -> dict:
        """Construct the on-disk JSON shape. Kept separate for tests."""
        return {
            "schema_version": self._schema_version,
            "timestamp_epoch": status.timestamp_epoch,
            "device": self._device or status.device,
            "profile": status.profile,
            "mission": status.mission,
            "project_code": status.project_code,
            "scan_state": status.scan_state,
            "fix_type": status.fix_type,
            "sat_count": status.sat_count,
            "hdop": status.hdop,
            "lat": status.lat,
            "lon": status.lon,
            "alt_m": status.alt_m,
            "rtk_age_s": status.rtk_age_s,
            "battery_mv": status.battery_mv,
            "lora_link_rssi": status.lora_link_rssi,
            "lora_link_snr": status.lora_link_snr,
            "ntrip_connected": status.ntrip_connected,
            "ntrip_bytes_per_sec": status.ntrip_bytes_per_sec,
        }


class LocalHttpPublisher(_Publisher):
    """Channel B — stdlib http.server on loopback (D-033).

    GET /status — latest RoverStatus snapshot, same shape as StatusJsonPublisher.
    GET /health — `{"ok": true, "uptime_s": N}`.

    Modeled on arm-drone-lidar-workflow/base-station/rtk_base_api.py — read-only,
    minimal, ThreadingHTTPServer so a slow client doesn't wedge the publisher.
    """

    name = "local_http"

    def __init__(self, config: RoverConfig) -> None:
        self._tm = config.telemetry
        self._bsi = config.base_station_integration
        self._device = config.general.device_name
        self._lock = threading.Lock()
        self._latest_payload: dict = {}
        self._started_monotonic = time.monotonic()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        # The same payload-shaping logic StatusJsonPublisher uses, so both channels
        # return identical JSON on the wire.
        self._json_builder = StatusJsonPublisher(config)

    def start(self) -> None:
        handler_class = _make_http_handler(self)
        self._server = ThreadingHTTPServer(
            (self._tm.http_bind, self._tm.http_port), handler_class
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rover-http-telemetry",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "LocalHttpPublisher listening on http://%s:%d",
            self._tm.http_bind, self._tm.http_port,
        )

    def publish(self, status: RoverStatus) -> None:
        with self._lock:
            self._latest_payload = self._json_builder.build_payload(status)

    def get_latest(self) -> dict:
        with self._lock:
            return dict(self._latest_payload)

    def uptime_s(self) -> float:
        return time.monotonic() - self._started_monotonic

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


def _make_http_handler(owner: LocalHttpPublisher) -> type:
    """Build a request handler bound to *owner*'s state."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            # Quiet — route through our logger at debug level rather than spamming stderr.
            logger.debug("http %s - %s", self.address_string(), format % args)

        def _write_json(self, status_code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler convention)
            if self.path == "/status":
                self._write_json(200, owner.get_latest())
            elif self.path == "/health":
                self._write_json(200, {"ok": True, "uptime_s": owner.uptime_s()})
            else:
                self._write_json(404, {"error": "not found", "path": self.path})

    return _Handler


class LoRaPublisher(_Publisher):
    """Channel C — LoRa STATUS + LINK frames to rover ESP32 via USB serial (D-033)."""

    name = "lora"

    def __init__(self, config: RoverConfig) -> None:
        self._lora = config.lora
        self._sequence_status = 0
        self._sequence_link = 0
        self._serial = None  # opened lazily in start() so off-Pi tests don't import pyserial

    def start(self) -> None:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "LoRaPublisher: pyserial not available; channel C disabled this run"
            )
            self._serial = None
            return

        try:
            self._serial = serial.Serial(
                self._lora.port, self._lora.baud, timeout=0.5
            )
            logger.info("LoRaPublisher serial open: %s @ %d",
                        self._lora.port, self._lora.baud)
        except OSError as e:
            logger.warning(
                "LoRaPublisher: cannot open %s: %s — channel C disabled this run",
                self._lora.port, e,
            )
            self._serial = None

    def publish(self, status: RoverStatus) -> None:
        if self._serial is None:
            return
        if self._lora.role == "disabled":
            return

        # STATUS frame (0x01)
        try:
            payload = encode_status_payload(
                fix_type=status.fix_type,
                sat_count=status.sat_count,
                hdop=status.hdop,
                battery_mv=status.battery_mv,
                scan_state=status.scan_state,
            )
            frame = encode_frame(TYPE_STATUS, self._sequence_status, payload)
            self._serial.write(frame)
            self._sequence_status = (self._sequence_status + 1) & 0xFFFF
        except (ValueError, OSError) as e:
            logger.warning("LoRaPublisher: STATUS send failed: %s", e)

    def publish_link(
        self,
        rssi_dbm: int,
        snr_db: int,
        rx_count: int,
        tx_count: int,
        err_count: int,
    ) -> None:
        """Emit a LINK frame. Separate method because LINK metrics come from the
        ESP32 itself in steady state — this is called by whoever is reading ESP32
        feedback, not by the main acquisition loop."""
        if self._serial is None:
            return
        if self._lora.role == "disabled":
            return
        try:
            payload = encode_link_payload(rssi_dbm, snr_db, rx_count, tx_count, err_count)
            frame = encode_frame(TYPE_LINK, self._sequence_link, payload)
            self._serial.write(frame)
            self._sequence_link = (self._sequence_link + 1) & 0xFFFF
        except (ValueError, OSError) as e:
            logger.warning("LoRaPublisher: LINK send failed: %s", e)

    def stop(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except OSError:
                pass
            self._serial = None


# ---------------------------------------------------------------------------
# TelemetryRouter — compose enabled channels
# ---------------------------------------------------------------------------


class TelemetryRouter:
    """Fans out RoverStatus to all enabled publishers.

    Construction reads the config once; publishers don't get reconfigured at
    runtime. A failure inside one publisher's publish() never raises out — they
    are intentionally isolated.
    """

    def __init__(self, config: RoverConfig) -> None:
        self._config = config
        self._publishers: list[_Publisher] = []

        if config.base_station_integration.enabled:
            self._publishers.append(StatusJsonPublisher(config))
        if config.telemetry.http_enabled:
            self._publishers.append(LocalHttpPublisher(config))
        if config.lora.enabled and config.lora.role != "disabled":
            self._publishers.append(LoRaPublisher(config))

        names = [p.name for p in self._publishers] or ["<none>"]
        logger.info("TelemetryRouter publishers: %s", ", ".join(names))

    @property
    def publishers(self) -> list[_Publisher]:
        return list(self._publishers)

    def start(self) -> None:
        for pub in self._publishers:
            try:
                pub.start()
            except Exception as e:
                logger.warning("publisher %r start failed: %s", pub.name, e)

    def publish(self, status: RoverStatus) -> None:
        for pub in self._publishers:
            try:
                pub.publish(status)
            except Exception as e:
                logger.warning("publisher %r publish failed: %s", pub.name, e)

    def stop(self) -> None:
        for pub in self._publishers:
            try:
                pub.stop()
            except Exception as e:
                logger.warning("publisher %r stop failed: %s", pub.name, e)


# ---------------------------------------------------------------------------
# Convenience: build a RoverStatus pre-seeded from RoverConfig.session
# ---------------------------------------------------------------------------


def status_from_config(config: RoverConfig) -> RoverStatus:
    """Construct a baseline RoverStatus with session context pre-filled."""
    return RoverStatus(
        device=config.general.device_name,
        profile=config.session.profile,
        mission=config.session.mission_tag,
        project_code=config.session.project_code,
    )


__all__ = [
    "RoverStatus",
    "TelemetryRouter",
    "StatusJsonPublisher",
    "LocalHttpPublisher",
    "LoRaPublisher",
    "atomic_write_json",
    "status_from_config",
]


# Cleanup: asdict is imported above for parity with config.py patterns even
# though this module doesn't use it directly. Keep import minimal.
_ = asdict
