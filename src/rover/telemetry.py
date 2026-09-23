"""Triple-channel telemetry router (DEC-033).

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
        Encodes a STATUS (0x01) frame per the shared LoRa frame v2 envelope
        (see rover.lora_protocol) and writes it to the rover ESP32 over USB
        serial. The ESP32 then broadcasts over LoRa. LINK (0x02) frames are
        not emitted from here — see the class docstring.

Each publisher's lifecycle (start/stop) is independent; one publisher failing or
being disabled never takes down the others.

Public API:
    STATUS_SCHEMA_VERSION — module-level constant; rover-side schema version
    RoverStatus       — dataclass; current rover snapshot for routing
    TelemetryRouter   — composes the configured channels and fans out publish()
    StatusJsonPublisher / LocalHttpPublisher / LoRaPublisher — individual channels
    atomic_write_json — re-exported from rover._io (mirror of base-station helper)

Decision references: DEC-033 (this whole module exists for DEC-033).

Dependencies: stdlib only (pyserial is imported lazily inside LoRaPublisher.start()
so off-Pi tests don't require it).

Schema version history (rover side; versioned independently from base):
    v1 (2026-05-23): initial set per BASE_STATION_INTEGRATION.md §3.1. Fields:
                     schema_version, timestamp_epoch, device, profile, mission,
                     project_code, scan_state, fix_type, sat_count, hdop, lat,
                     lon, alt_m, rtk_age_s, battery_mv, lora_link_rssi,
                     lora_link_snr, ntrip_connected, ntrip_bytes_per_sec.
    v2 (2026-09-23): added sensors_disabled (list[str]), logger_degraded
                     (bool), pdop (float). battery_mv, lora_link_rssi and
                     lora_link_snr become optional (int | None) and are
                     OMITTED from the payload entirely when unmeasured
                     (None) instead of carrying a −128/0 placeholder that
                     read as indistinguishable from a real reading
                     (S2-R2). LoRaPublisher.publish_link() removed — no
                     wire encoding lost a field, since LINK metrics were
                     never sourced from RoverStatus.

Adding a field is a minor bump (consumers ignore unknown keys); removing or
renaming is a major bump. Cross-ref: arm-drone-lidar-workflow/base-station/
rtk_io.py:STATUS_SCHEMA_VERSION (currently 9 — versioned independently).

Changelog:
    0.10.0  2026-05-23  Initial multi-publisher router (Phase B of overhaul).
    0.10.2  2026-05-30  STATUS_SCHEMA_VERSION constant; atomic_write_json moved
                        to rover._io (Stage B of deep-alignment overhaul).
    0.11.0  2026-09-23  Schema v2 (sensors_disabled/logger_degraded/pdop;
                        unmeasured fields omitted); build_payload() is now a
                        module function shared by all three publishers;
                        TelemetryRouter.publish() applies an independent
                        cadence per channel (status_json/http use
                        publish_interval_sec, lora uses
                        lora.telemetry_interval_sec — previously unread);
                        LoRaPublisher.publish_link() and the dead
                        role == "disabled" re-checks removed (T1-025,
                        T1-026, T1-030, T1-047, S2-R2).
    0.11.1  2026-09-23  TelemetryRouter.publish()'s catch-up-after-a-stall is
                        now bounded to one extra fire per channel instead of
                        unbounded (a caller wedged for 30s on a 1s-interval
                        LoRa channel used to burst ~30 back-to-back fires on
                        an airtime-limited link) — fix round 1 on Task 4.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rover._io import atomic_write_json
from rover.config import RoverConfig
from rover.lora_protocol import (
    TYPE_STATUS,
    encode_frame,
    encode_status_payload,
)

logger = logging.getLogger(__name__)


# Rover-side status.json schema version. Bumped on field add/remove; consumers
# (Base-Station sidecars, dashboards) read this to decide whether they
# understand the payload. See module docstring for the full version history.
STATUS_SCHEMA_VERSION = 2


# ---------------------------------------------------------------------------
# RoverStatus — the canonical in-memory snapshot
# ---------------------------------------------------------------------------


@dataclass
class RoverStatus:
    """Current rover state — input to every telemetry channel.

    Field shape is the union of what any publisher needs. Publishers that don't
    care about a given field simply skip it.

    The status.json on-wire shape is derived from this via the module-level
    build_payload(); the LoRa STATUS frame encoding lives in lora_protocol.py.
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
    pdop: float = 99.9  # NAV-PVT position DOP; 99.9 when the source is GGA (see GnssFix.pdop)
    lat: float = 0.0
    lon: float = 0.0
    alt_m: float = 0.0
    rtk_age_s: float = -1.0
    # Power. None = unmeasured — omitted from the wire payload rather than
    # sent as a 0 placeholder indistinguishable from a real reading (S2-R2).
    battery_mv: int | None = None
    # Scan state (see lora_protocol.SCAN_* constants)
    scan_state: int = 0
    # LoRa link metrics. None = unmeasured — same omit-don't-fake-it rule as
    # battery_mv; a −128 placeholder used to be indistinguishable from a real
    # reading (S2-R2).
    lora_link_rssi: int | None = None
    lora_link_snr: int | None = None
    # NTRIP client status
    ntrip_connected: bool = False
    ntrip_bytes_per_sec: int = 0
    # Sensor-gate / logger health (S2-R2) — always present, never omitted.
    sensors_disabled: list[str] = field(default_factory=list)
    logger_degraded: bool = False


def build_payload(status: RoverStatus, schema_version: int, device: str) -> dict:
    """On-wire status.json shape: every RoverStatus field, minus unmeasured (None) ones.

    Shared by all three publishers (status_json, local_http, lora's own
    payload is built separately since it's a binary frame, not JSON) so the
    shaping logic — and the v2 omit-when-None rule — lives in exactly one
    place.
    """
    payload = {k: v for k, v in dataclasses.asdict(status).items() if v is not None}
    payload["schema_version"] = schema_version
    payload["device"] = device or status.device
    return payload


# ---------------------------------------------------------------------------
# Publisher base + concrete channels
# (atomic_write_json lives in rover._io and is re-exported above.)
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
    """Channel A — Base-Station-compatible atomic status.json (DEC-033)."""

    name = "status_json"

    def __init__(self, config: RoverConfig) -> None:
        self._bsi = config.base_station_integration
        self._device = config.general.device_name
        # STATUS_SCHEMA_VERSION is the code-level source of truth (mirrors
        # base-station/rtk_io.py:STATUS_SCHEMA_VERSION). The config field
        # is retained as a per-session override hatch — e.g. for testing a
        # newer schema against an older consumer. Normal runs use the
        # constant by leaving the config at its default.
        self._schema_version = self._bsi.status_schema_version or STATUS_SCHEMA_VERSION

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
        return build_payload(status, self._schema_version, self._device)


class LocalHttpPublisher(_Publisher):
    """Channel B — stdlib http.server on loopback (DEC-033).

    GET /status — latest RoverStatus snapshot, same shape as StatusJsonPublisher.
    GET /health — `{"ok": true, "uptime_s": N}`.

    Modeled on arm-drone-lidar-workflow/base-station/rtk_base_api.py — read-only,
    minimal, ThreadingHTTPServer so a slow client doesn't wedge the publisher.
    """

    name = "local_http"

    def __init__(self, config: RoverConfig) -> None:
        self._tm = config.telemetry
        self._device = config.general.device_name
        # Same schema-version resolution rule as StatusJsonPublisher: 0 in
        # config means "use the code constant."
        self._schema_version = (
            config.base_station_integration.status_schema_version or STATUS_SCHEMA_VERSION
        )
        self._lock = threading.Lock()
        self._latest_payload: dict = {}
        self._started_monotonic = time.monotonic()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handler_class = _make_http_handler(self)
        self._server = ThreadingHTTPServer((self._tm.http_bind, self._tm.http_port), handler_class)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rover-http-telemetry",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "LocalHttpPublisher listening on http://%s:%d",
            self._tm.http_bind,
            self._tm.http_port,
        )

    def publish(self, status: RoverStatus) -> None:
        with self._lock:
            self._latest_payload = build_payload(status, self._schema_version, self._device)

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
    """Channel C — LoRa STATUS frame to rover ESP32 via USB serial (DEC-033).

    LINK frames (radio-health metrics) are not emitted here — they were never
    sourced from RoverStatus (the ESP32 reports its own link health), so
    publish_link() was dead code from this router's perspective and was
    removed in schema v2 (S2-R2).
    """

    name = "lora"

    def __init__(self, config: RoverConfig) -> None:
        self._lora = config.lora
        self._sequence_status = 0
        self._serial = None  # opened lazily in start() so off-Pi tests don't import pyserial

    def start(self) -> None:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("LoRaPublisher: pyserial not available; channel C disabled this run")
            self._serial = None
            return

        try:
            self._serial = serial.Serial(self._lora.port, self._lora.baud, timeout=0.5)
            logger.info("LoRaPublisher serial open: %s @ %d", self._lora.port, self._lora.baud)
        except OSError as e:
            logger.warning(
                "LoRaPublisher: cannot open %s: %s — channel C disabled this run",
                self._lora.port,
                e,
            )
            self._serial = None

    def publish(self, status: RoverStatus) -> None:
        if self._serial is None:
            return

        # STATUS frame (0x01). battery_mv is sent as 0 when unmeasured (None)
        # — the wire format has no null representation, so this is the one
        # place a placeholder is still unavoidable; the JSON channels omit
        # the field entirely instead (see build_payload()).
        try:
            payload = encode_status_payload(
                fix_type=status.fix_type,
                sat_count=status.sat_count,
                hdop=status.hdop,
                battery_mv=status.battery_mv or 0,
                scan_state=status.scan_state,
            )
            frame = encode_frame(TYPE_STATUS, self._sequence_status, payload)
            self._serial.write(frame)
            self._sequence_status = (self._sequence_status + 1) & 0xFFFF
        except (ValueError, OSError) as e:
            logger.warning("LoRaPublisher: STATUS send failed: %s", e)

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
    """Fans out RoverStatus to all enabled publishers, each on its own cadence.

    Construction reads the config once; publishers don't get reconfigured at
    runtime. A failure inside one publisher's publish() never raises out — they
    are intentionally isolated.

    Per-channel cadence (schema v2): status_json and local_http both publish on
    base_station_integration.publish_interval_sec; lora publishes on
    lora.telemetry_interval_sec (previously configured but never read — the
    router used to publish every channel on every call()). publish() is now
    meant to be called every acquisition-loop iteration; each channel decides
    for itself whether enough time has passed.
    """

    def __init__(self, config: RoverConfig) -> None:
        self._publishers: list[_Publisher] = []
        self._intervals: dict[str, float] = {}

        if config.base_station_integration.enabled:
            pub: _Publisher = StatusJsonPublisher(config)
            self._publishers.append(pub)
            self._intervals[pub.name] = config.base_station_integration.publish_interval_sec
        if config.telemetry.http_enabled:
            pub = LocalHttpPublisher(config)
            self._publishers.append(pub)
            self._intervals[pub.name] = config.base_station_integration.publish_interval_sec
        if config.lora.enabled and config.lora.role != "disabled":
            pub = LoRaPublisher(config)
            self._publishers.append(pub)
            self._intervals[pub.name] = config.lora.telemetry_interval_sec

        # -inf so the first publish() call always fires every channel,
        # regardless of its configured interval.
        self._last: dict[str, float] = dict.fromkeys(
            (p.name for p in self._publishers), float("-inf")
        )

        names = [p.name for p in self._publishers] or ["<none>"]
        logger.info("TelemetryRouter publishers: %s", ", ".join(names))

    @property
    def publishers(self) -> list[_Publisher]:
        return list(self._publishers)

    def interval_for(self, name: str) -> float:
        """Configured publish interval (seconds) for a channel, by publisher name."""
        return self._intervals.get(name, 0.0)

    def start(self) -> None:
        for pub in self._publishers:
            try:
                pub.start()
            except Exception as e:
                logger.warning("publisher %r start failed: %s", pub.name, e)

    def publish(self, status: RoverStatus) -> None:
        now = time.monotonic()
        for pub in self._publishers:
            last = self._last.get(pub.name, float("-inf"))
            interval = self._intervals.get(pub.name, 0.0)
            if now - last < interval:
                continue
            # Advance the schedule by a fixed `interval` rather than snapping
            # to the actual `now` of this call. Snapping accumulates the
            # caller's per-iteration jitter into the due-check itself, which
            # measurably undercounts publishes over many iterations (a
            # channel due every 0.2s over a 0.1s-jittery loop fired 9 times
            # in 2s instead of the intended 11). Advancing by a fixed step
            # keeps the schedule on-grid.
            #
            # The `max(..., now - interval)` clamp bounds catch-up after a
            # stall: without it, a long gap (e.g. the caller wedges for 30s
            # on a 1s-interval LoRa channel) leaves `last` far behind `now`,
            # and every subsequent call stays "overdue" until `last`
            # increments its way back up to `now` — a burst of ~30 back-to-
            # back fires on an airtime-limited radio link. Clamping `last` to
            # no earlier than `now - interval` means at most one extra catch-
            # up fire happens after any gap, however long.
            self._last[pub.name] = (
                now if last == float("-inf") else max(last + interval, now - interval)
            )
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
    "STATUS_SCHEMA_VERSION",
    "RoverStatus",
    "build_payload",
    "TelemetryRouter",
    "StatusJsonPublisher",
    "LocalHttpPublisher",
    "LoRaPublisher",
    "atomic_write_json",
    "status_from_config",
]
