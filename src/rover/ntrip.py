"""Pi-side NTRIP client (D-031, D-032).

Connects to an NTRIP caster (default: the arm-drone-lidar-workflow Base-Station's
ARM_BASE mountpoint on rtk-base.local:2101), reads RTCM3 from the response stream,
and writes those bytes to the F9P over its USB serial interface so the receiver
can reach RTK FIX.

The module is active only when:
    config.ntrip.enabled = true
AND config.ntrip.client_location = "pi"

If client_location = "esp32" the rover's ESP32 firmware does this job over WiFi
(see firmware/esp32-rover/) and this module stays idle.

The NTRIP request shape is the small subset of RFC 2616 needed to negotiate a
mountpoint: an HTTP/1.1-style GET line, a User-Agent identifying us as an NTRIP
client, an Ntrip-Version header, and Basic Auth from the env-var-supplied
password. RTCM bytes arrive as the response body — no chunked encoding, no
content-length — we read until the socket dies, then reconnect.

Public API:
    NtripClient(config, rtcm_sink, status_sink=None)
        rtcm_sink:  callable(bytes) -> None  — typically gnss.write_rtcm
        status_sink: optional callable(dict) -> None — receives connection stats
    .start() / .stop()
    .build_request(host, mountpoint, username, password, user_agent="...")
        — exposed for unit testing without a real caster

The actual TCP I/O lives in a background thread (see NtripClient._run_loop) so the
main acquisition loop doesn't block on caster reconnect.

Dependencies: stdlib (socket, base64, threading, time, os). pyserial is NOT used
here — the caller supplies the sink. Tests exercise the request-building helpers
without any network or hardware.

Changelog:
    0.10.0  2026-05-23  Initial implementation (Phase C of overhaul).
"""

from __future__ import annotations

import base64
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from rover.config import RoverConfig

logger = logging.getLogger(__name__)


USER_AGENT = "PiLiDAR-RTK-Rover/0.10 (NTRIP)"
NTRIP_VERSION = "Ntrip/2.0"

# Tunables — not exposed via config until field experience says they should be.
_CONNECT_TIMEOUT_SEC = 5.0
_READ_TIMEOUT_SEC = 30.0
_BACKOFF_INITIAL_SEC = 1.0
_BACKOFF_MAX_SEC = 30.0
_READ_CHUNK_SIZE = 1024


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NtripStats:
    """Connection statistics — pushed to the optional status_sink and surfaced on
    the rover's telemetry channels."""

    connected: bool = False
    bytes_received_total: int = 0
    bytes_received_this_sec: int = 0
    last_connect_attempt_epoch: float = 0.0
    last_byte_epoch: float = 0.0
    connect_count: int = 0
    error_count: int = 0
    last_error: str = ""


# ---------------------------------------------------------------------------
# Request / response helpers (stateless, easy to unit-test)
# ---------------------------------------------------------------------------


class NtripError(RuntimeError):
    """Raised by the request-building / response-parsing helpers on a fatal error
    (rejected mountpoint, auth failure). Reconnectable errors (TCP reset,
    timeout) are not exposed via this exception type — those just trip the
    backoff loop."""


def build_request(
    host: str,
    mountpoint: str,
    username: str,
    password: str,
    user_agent: str = USER_AGENT,
) -> bytes:
    """Build an NTRIP v2 GET request.

    Mountpoint name is sent verbatim (no URL encoding); casters use names like
    `ARM_BASE` which are URL-safe by convention. Basic Auth header is
    `Basic base64(user:pass)`.

    Args:
        host: Used in the Host: header (caster hostname).
        mountpoint: Caster mountpoint name (e.g. "ARM_BASE").
        username: NTRIP client username.
        password: NTRIP client password (read from env var by the caller; never
                  passed via config).
        user_agent: User-Agent string. Defaults to USER_AGENT.

    Returns:
        Bytes ready to send on the socket.
    """
    if not mountpoint:
        raise NtripError("mountpoint is required")
    creds = f"{username}:{password}".encode("utf-8")
    auth = base64.b64encode(creds).decode("ascii")

    lines = [
        f"GET /{mountpoint} HTTP/1.1",
        f"Host: {host}",
        f"User-Agent: {user_agent}",
        f"Ntrip-Version: {NTRIP_VERSION}",
        f"Authorization: Basic {auth}",
        "Connection: close",
        "",  # terminating empty line
        "",
    ]
    return "\r\n".join(lines).encode("ascii")


def parse_response_status(header_bytes: bytes) -> tuple[int, str]:
    """Parse the HTTP status line out of the response header buffer.

    Returns (status_code, reason). Raises NtripError on a malformed status line.
    Some casters reply with `ICY 200 OK` (legacy NTRIP v1 style) — that's
    accepted and mapped to status code 200.
    """
    first_line_end = header_bytes.find(b"\r\n")
    if first_line_end < 0:
        first_line_end = len(header_bytes)
    first_line = header_bytes[:first_line_end].decode("ascii", errors="replace")

    parts = first_line.split(None, 2)
    if len(parts) < 2:
        raise NtripError(f"malformed status line: {first_line!r}")

    proto, code_str = parts[0], parts[1]
    reason = parts[2] if len(parts) >= 3 else ""

    if proto == "ICY":
        # Legacy NTRIPv1: "ICY 200 OK"
        if code_str == "200":
            return 200, reason or "OK"
        raise NtripError(f"caster rejected: {first_line!r}")

    if not proto.startswith("HTTP/"):
        raise NtripError(f"unknown protocol in status line: {first_line!r}")

    try:
        code = int(code_str)
    except ValueError:
        raise NtripError(f"non-numeric status code: {code_str!r}")

    return code, reason


# ---------------------------------------------------------------------------
# NtripClient — background-thread NTRIP consumer
# ---------------------------------------------------------------------------


class NtripClient:
    """NTRIP-over-IP client that pushes RTCM3 bytes into the supplied sink.

    Args:
        config: RoverConfig (we read .ntrip and .general).
        rtcm_sink: Callable invoked with raw RTCM bytes whenever the caster
            sends some. Typically wired to GnssReceiver.write_rtcm so the bytes
            land on the F9P's USB serial port.
        status_sink: Optional callable receiving an NtripStats snapshot on
            connect / disconnect / per-second bytes. Used to feed
            TelemetryRouter.publish().
    """

    def __init__(
        self,
        config: RoverConfig,
        rtcm_sink: Callable[[bytes], None],
        status_sink: Optional[Callable[[NtripStats], None]] = None,
    ) -> None:
        self._cfg = config.ntrip
        self._device_name = config.general.device_name
        self._rtcm_sink = rtcm_sink
        self._status_sink = status_sink
        self._stats = NtripStats()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._password = self._resolve_password()

    @property
    def stats(self) -> NtripStats:
        return self._stats

    def _resolve_password(self) -> str:
        """Read password from environment per `[ntrip].password_env`.

        Empty string is a valid configured state (some casters allow blank
        passwords); a missing env var is treated the same as an explicit blank
        and logged at info level. The caster will reject if it doesn't like it.
        """
        env_name = self._cfg.password_env
        if not env_name:
            return ""
        return os.environ.get(env_name, "")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background NTRIP loop. Idempotent."""
        if not self._cfg.enabled:
            logger.info("NTRIP disabled in config; client not starting")
            return
        if self._cfg.client_location != "pi":
            logger.info(
                "NTRIP client_location=%r; Pi-side client not starting "
                "(ESP32 firmware handles NTRIP in that mode)",
                self._cfg.client_location,
            )
            return
        if self._thread is not None and self._thread.is_alive():
            logger.warning("NtripClient.start() called twice — ignoring")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="rover-ntrip-client",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "NtripClient started: %s:%d/%s as user=%r",
            self._cfg.caster_host, self._cfg.caster_port, self._cfg.mountpoint,
            self._cfg.username,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    # ------------------------------------------------------------------
    # Internal — run loop with exponential backoff
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        backoff = _BACKOFF_INITIAL_SEC
        while not self._stop_event.is_set():
            try:
                self._one_connection()
                # Successful connection — reset backoff
                backoff = _BACKOFF_INITIAL_SEC
            except NtripError as e:
                # Fatal-per-attempt (auth, bad mountpoint) — log loudly
                self._stats.error_count += 1
                self._stats.last_error = str(e)
                logger.error("NTRIP fatal error: %s", e)
                self._publish_stats()
            except (OSError, socket.timeout) as e:
                self._stats.error_count += 1
                self._stats.last_error = str(e)
                logger.info("NTRIP transient error: %s", e)
                self._publish_stats()
            except Exception as e:  # pragma: no cover — defensive
                self._stats.error_count += 1
                self._stats.last_error = f"unexpected: {e!r}"
                logger.exception("NTRIP unexpected error")
                self._publish_stats()

            if self._stop_event.is_set():
                break

            # Backoff before reconnect attempt
            self._stop_event.wait(backoff)
            backoff = min(backoff * 2.0, _BACKOFF_MAX_SEC)

    def _one_connection(self) -> None:
        """Single connect-and-stream cycle. Returns when the stream ends or is closed."""
        self._stats.last_connect_attempt_epoch = time.time()
        self._publish_stats()

        sock = socket.create_connection(
            (self._cfg.caster_host, self._cfg.caster_port),
            timeout=_CONNECT_TIMEOUT_SEC,
        )
        sock.settimeout(_READ_TIMEOUT_SEC)

        try:
            request = build_request(
                host=self._cfg.caster_host,
                mountpoint=self._cfg.mountpoint,
                username=self._cfg.username,
                password=self._password,
            )
            sock.sendall(request)

            # Read response headers (small; terminated by \r\n\r\n)
            header_buf = self._read_until(sock, b"\r\n\r\n", limit=4096)
            code, reason = parse_response_status(header_buf)
            if code == 401:
                raise NtripError(
                    f"caster rejected credentials (401) for mountpoint "
                    f"{self._cfg.mountpoint!r}; check ${self._cfg.password_env}"
                )
            if code == 404:
                raise NtripError(
                    f"caster does not serve mountpoint {self._cfg.mountpoint!r} (404)"
                )
            if code != 200:
                raise NtripError(f"caster returned HTTP {code} {reason!r}")

            self._stats.connected = True
            self._stats.connect_count += 1
            self._stats.last_error = ""
            self._publish_stats()
            logger.info(
                "NTRIP connected to %s:%d/%s",
                self._cfg.caster_host, self._cfg.caster_port, self._cfg.mountpoint,
            )

            # Stream RTCM until close
            self._stream_body(sock)
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._stats.connected = False
            self._publish_stats()

    def _read_until(self, sock: socket.socket, marker: bytes, limit: int) -> bytes:
        """Read from socket until *marker* appears (returned as part of the buffer)
        or *limit* bytes have been read. Used only for HTTP headers."""
        buf = b""
        while marker not in buf:
            if len(buf) >= limit:
                raise NtripError(f"response headers exceed {limit} bytes")
            chunk = sock.recv(min(_READ_CHUNK_SIZE, limit - len(buf)))
            if not chunk:
                raise NtripError("caster closed connection during handshake")
            buf += chunk
        return buf

    def _stream_body(self, sock: socket.socket) -> None:
        """Read RTCM bytes from socket and dispatch them to the sink.

        The caster simply streams bytes — there's no chunked encoding, no
        framing. Whatever arrives is RTCM3 raw bytes that the F9P knows how to
        parse on its own.
        """
        sec_marker = int(time.time())
        sec_bytes = 0
        while not self._stop_event.is_set():
            try:
                chunk = sock.recv(_READ_CHUNK_SIZE)
            except socket.timeout:
                logger.info("NTRIP read timeout; will reconnect")
                return
            if not chunk:
                logger.info("NTRIP caster closed connection; will reconnect")
                return

            self._stats.bytes_received_total += len(chunk)
            self._stats.last_byte_epoch = time.time()

            try:
                self._rtcm_sink(chunk)
            except Exception as e:
                # Sink errors should not kill the NTRIP loop — log and keep going
                logger.warning("RTCM sink raised: %s", e)

            now_sec = int(time.time())
            if now_sec != sec_marker:
                self._stats.bytes_received_this_sec = sec_bytes
                self._publish_stats()
                sec_marker = now_sec
                sec_bytes = 0
            sec_bytes += len(chunk)

    def _publish_stats(self) -> None:
        if self._status_sink is None:
            return
        try:
            self._status_sink(self._stats)
        except Exception as e:  # pragma: no cover — defensive
            logger.warning("ntrip status_sink raised: %s", e)


__all__ = [
    "NtripClient",
    "NtripStats",
    "NtripError",
    "build_request",
    "parse_response_status",
    "USER_AGENT",
    "NTRIP_VERSION",
]
