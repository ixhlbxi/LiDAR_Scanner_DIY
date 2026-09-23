"""Pi-side NTRIP client (DEC-031, DEC-032).

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
password. RTCM bytes arrive as the response body — no content-length, we read
until the socket dies, then reconnect. Chunked transfer encoding is refused
outright (NtripError) rather than mis-parsed as raw RTCM — casters serving
mountpoints are not expected to chunk, and silently forwarding chunk framing
bytes to the F9P as if they were RTCM would corrupt the correction stream.

Public API:
    NtripClient(config, rtcm_sink, status_sink=None, gga_source=None)
        rtcm_sink:  callable(bytes) -> None  — typically gnss.write_rtcm
        status_sink: optional callable(NtripStats) -> None — receives a
            connection-stats snapshot on connect/disconnect/per-second bytes
        gga_source: optional callable() -> GnssFix | None — the rover's own
            latest fix, sent upstream as `$GPGGA` for VRS casters
    .start() / .stop() — stop() shuts down the live socket so a thread
        blocked in recv() doesn't outlive the caller
    .fatal_error — str | None; set on NtripFatalError (401, 404, or chunked
        Transfer-Encoding) in the arm_group profile, after which the
        background loop has exited (BASE_STATION_INTEGRATION.md §7) — every
        other rejection (503, a handshake closed early, ...) just retries
    .stats — an NtripStats snapshot (dataclasses.replace); mutating the
        returned object never affects the client's own state
    .build_request(host, mountpoint, username, password, user_agent="...")
        — exposed for unit testing without a real caster
    build_gga(fix, when=None) -> bytes
        — module-level; builds the `$GPGGA` sentence NtripClient uploads

The actual TCP I/O lives in a background thread (see NtripClient._run_loop) so the
main acquisition loop doesn't block on caster reconnect.

Dependencies: stdlib (socket, base64, threading, time, os). pyserial is NOT used
here — the caller supplies the sink. Tests exercise the request-building helpers
without any network or hardware.

Changelog:
    0.10.0  2026-05-23  Initial implementation (Phase C of overhaul).
    0.11.0  2026-09-23  Profile-aware fatal errors (401/404 latch fatal_error
                         and stop the loop in arm_group; run() aborts with
                         exit 4 — BASE_STATION_INTEGRATION.md §7); stop()
                         shuts down the live socket instead of waiting out
                         the read timeout; .stats returns a snapshot; the
                         per-second byte rate is computed from a monotonic
                         window instead of wall-clock second boundaries;
                         unused _device_name dropped.
    0.11.1  2026-09-23  Periodic `$GPGGA` upload for VRS-style casters
                         (`[ntrip].gga_send_interval_sec`, already read from
                         config but never sent); body bytes bundled with the
                         response headers in the same recv() chunk are now
                         forwarded to the sink instead of silently dropped;
                         chunked transfer encoding is refused with a fatal
                         NtripError instead of being mis-forwarded as RTCM.
    0.11.2  2026-09-23  NtripFatalError (a narrower NtripError subclass) now
                         covers only 401/404/chunked; the arm_group latch in
                         _run_loop checks isinstance against it instead of
                         catching every NtripError, so a 503 or an
                         early-closed handshake retries instead of aborting
                         the session (final review I3). connect()'s
                         _one_connection now bails immediately if _stop_event
                         is already set right after publishing self._sock, so
                         a stop() racing create_connection() can't leave the
                         thread blocked in a header read (final review M3).
                         build_gga's docstring corrected: the altitude field
                         carries ellipsoidal height (GnssFix.alt), not MSL
                         (final review M2).
"""

from __future__ import annotations

import base64
import dataclasses
import logging
import os
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rover import __version__
from rover.config import RoverConfig

if TYPE_CHECKING:
    from rover.gnss import GnssFix

logger = logging.getLogger(__name__)


USER_AGENT = f"PiLiDAR-RTK-Rover/{__version__} (NTRIP)"
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
    """Raised by the request-building / response-parsing helpers on a caster
    rejection. Covers both retryable rejections (503, a malformed status
    line, a handshake closed early) and the fatal subset (NtripFatalError,
    below). Reconnectable transport errors (TCP reset, timeout) are not
    exposed via this exception type — those just trip the backoff loop."""


class NtripFatalError(NtripError):
    """Raised only for a caster response that will never succeed on retry:
    HTTP 401 (bad credentials), HTTP 404 (mountpoint doesn't exist), or
    chunked Transfer-Encoding (unsupported by design, not a transient
    condition). Every other NtripError — 503, an unexpected non-200/401/404
    status, a malformed status line, a handshake closed before any status
    line arrived — is presumed transient and must NOT latch
    NtripClient.fatal_error even in the arm_group profile; see
    NtripClient._run_loop's dispatch on this type."""


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
    creds = f"{username}:{password}".encode()
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
        raise NtripError(f"non-numeric status code: {code_str!r}")  # noqa: B904 — keep implicit exception chaining; revisited in stage 4

    return code, reason


def _is_chunked_transfer_encoding(head: bytes) -> bool:
    """True if *head* (the response status line + headers, no trailing blank
    line) declares `Transfer-Encoding: chunked` — a real header-name match,
    not a substring search, so it isn't fooled by an unrelated header whose
    value happens to contain the word "chunked", and it still catches an
    oddly-spaced or multi-valued line like `Transfer-Encoding:  gzip, chunked`.
    """
    for line in head.split(b"\r\n"):
        name, sep, value = line.partition(b":")
        if not sep:
            continue
        if name.strip().lower() == b"transfer-encoding" and b"chunked" in value.lower():
            return True
    return False


def _nmea_checksum(body: str) -> str:
    """XOR checksum of the sentence body (everything between `$` and `*`)."""
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"{x:02X}"


def _to_nmea(deg: float, is_lat: bool) -> tuple[str, str]:
    """Decimal degrees -> (ddmm.mmmm or dddmm.mmmm, hemisphere letter)."""
    hemi = ("N" if deg >= 0 else "S") if is_lat else ("E" if deg >= 0 else "W")
    d = abs(deg)
    whole = int(d)
    minutes = (d - whole) * 60.0
    width = 2 if is_lat else 3
    return f"{whole:0{width}d}{minutes:07.4f}", hemi


def build_gga(fix: GnssFix, when: time.struct_time | None = None) -> bytes:
    """Build a `$GPGGA` sentence from *fix* for VRS-style casters.

    Some casters (Virtual Reference Station networks) steer RTCM corrections
    off the rover's own approximate position, and expect the client to send
    its position back as periodic `$GPGGA` sentences — `[ntrip].gga_send_interval_sec`
    controls the cadence (see NtripClient._stream_body).

    Quality: 4 = RTK fix, 5 = RTK float, 1 = any other fix, 0 = none. Note the
    same FIX/FLOAT swap documented on rover.gnss._GGA_QUALITY_TO_FIX: our
    internal fix_type has FLOAT=4/FIX=5, but the GGA wire format we emit here
    uses the standard NMEA quality indicator (FIXED=4/FLOAT=5) — we're
    encoding back to the wire vocabulary, not echoing our internal enum.
    Altitude: GnssFix.alt is ellipsoidal height (WGS84), not MSL — gnss.py
    normalises both NAV-PVT and GGA sources to that datum before they reach
    GnssFix (see rover.gnss). It is placed directly in the GGA altitude
    field with a geoid separation of 0.0 rather than being converted back to
    MSL, since we have no orthometric height/geoid model here to convert
    with. Casters consume $GPGGA for its lat/lon only, so this does not
    matter in practice (final review M2).
    """
    if when is None:
        when = time.gmtime()
    lat, ns = _to_nmea(fix.lat, True)
    lon, ew = _to_nmea(fix.lon, False)
    quality = {5: 4, 4: 5}.get(fix.fix_type, 1 if fix.fix_type >= 1 else 0)
    body = (
        f"GPGGA,{time.strftime('%H%M%S', when)}.00,{lat},{ns},{lon},{ew},{quality},"
        f"{fix.sat_count:02d},{fix.hdop:.1f},{fix.alt:.1f},M,0.0,M,,"
    )
    return f"${body}*{_nmea_checksum(body)}\r\n".encode("ascii")


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
        gga_source: Optional callable returning the latest GnssFix (or None).
            When set and `[ntrip].gga_send_interval_sec` > 0, the connection
            sends a `$GPGGA` sentence upstream at that cadence for VRS-style
            casters that steer corrections off the rover's own position
            (Task 2 wires this up; unused until then).
    """

    def __init__(
        self,
        config: RoverConfig,
        rtcm_sink: Callable[[bytes], None],
        status_sink: Callable[[NtripStats], None] | None = None,
        gga_source: Callable[[], GnssFix | None] | None = None,
    ) -> None:
        self._cfg = config.ntrip
        self._profile = config.session.profile
        self._rtcm_sink = rtcm_sink
        self._status_sink = status_sink
        self._gga_source = gga_source
        self._stats = NtripStats()
        self._stats_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._fatal_error: str | None = None
        self._password = self._resolve_password()
        self._window_start = time.monotonic()
        self._window_bytes = 0

    @property
    def stats(self) -> NtripStats:
        """A snapshot; mutating it does not affect the client."""
        with self._stats_lock:
            return dataclasses.replace(self._stats)

    @property
    def fatal_error(self) -> str | None:
        """Set when the caster rejected us with an NtripFatalError (401, 404,
        or chunked Transfer-Encoding — never on a transient rejection like
        503 or an early-closed handshake) and the profile is arm_group; the
        loop has exited."""
        return self._fatal_error

    def _resolve_password(self) -> str:
        """Read password from environment per `[ntrip].password_env`.

        Empty string is a valid configured state (some casters allow blank
        passwords); a missing env var is treated the same as an explicit blank
        and logged at info level. The caster will reject if it doesn't like it.
        """
        env_name = self._cfg.password_env
        if not env_name:
            return ""
        value = os.environ.get(env_name)
        if value is None:
            logger.info("NTRIP password env var %r is not set; using blank password", env_name)
            return ""
        return value

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
            self._cfg.caster_host,
            self._cfg.caster_port,
            self._cfg.mountpoint,
            self._cfg.username,
        )

    def stop(self) -> None:
        """Stop the background loop and close the live socket promptly.

        Setting the stop event alone is not enough: a thread blocked in
        sock.recv() only notices at the next read timeout (up to
        _READ_TIMEOUT_SEC, 30s). shutdown() unblocks a pending recv() on
        POSIX; Windows sockets don't reliably wake a cross-thread recv() on
        shutdown() alone (measured on this platform — the reader thread
        stayed blocked for the full join timeout), so close() follows it —
        that does interrupt the read, with an OSError the read loop treats
        as just another transient error.
        """
        self._stop_event.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    # ------------------------------------------------------------------
    # Internal — stats bookkeeping (all mutation goes through the lock)
    # ------------------------------------------------------------------

    def _bump_error(self, message: str) -> None:
        with self._stats_lock:
            self._stats.error_count += 1
            self._stats.last_error = message

    # ------------------------------------------------------------------
    # Internal — run loop with exponential backoff
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        backoff = _BACKOFF_INITIAL_SEC
        warned_fatal = False
        while not self._stop_event.is_set():
            try:
                self._one_connection()
                # Successful connection — reset backoff
                backoff = _BACKOFF_INITIAL_SEC
                warned_fatal = False
            except NtripError as e:
                # NtripError covers both retryable rejections (503, a
                # handshake closed early) and the fatal subset
                # (NtripFatalError: 401/404/chunked). Only the fatal subset
                # latches fatal_error in arm_group — everything else falls
                # through to the normal warn + backoff/retry path below
                # (final review I3).
                self._bump_error(str(e))
                if self._profile == "arm_group" and isinstance(e, NtripFatalError):
                    self._fatal_error = str(e)
                    logger.error("NTRIP fatal in arm_group profile — refusing to continue: %s", e)
                    self._publish_stats()
                    return
                if not warned_fatal:
                    logger.warning(
                        "NTRIP caster rejected us (%s); retrying every %.0fs",
                        e,
                        _BACKOFF_MAX_SEC,
                    )
                    warned_fatal = True
                else:
                    logger.debug("NTRIP still rejected: %s", e)
                backoff = _BACKOFF_MAX_SEC
                self._publish_stats()
            except (OSError, TimeoutError) as e:
                self._bump_error(str(e))
                logger.info("NTRIP transient error: %s", e)
                self._publish_stats()
            except Exception as e:  # pragma: no cover — defensive
                self._bump_error(f"unexpected: {e!r}")
                logger.exception("NTRIP unexpected error")
                self._publish_stats()

            if self._stop_event.is_set():
                break

            # Backoff before reconnect attempt
            self._stop_event.wait(backoff)
            backoff = min(backoff * 2.0, _BACKOFF_MAX_SEC)

    def _one_connection(self) -> None:
        """Single connect-and-stream cycle. Returns when the stream ends or is closed."""
        with self._stats_lock:
            self._stats.last_connect_attempt_epoch = time.time()
        self._publish_stats()

        sock = socket.create_connection(
            (self._cfg.caster_host, self._cfg.caster_port),
            timeout=_CONNECT_TIMEOUT_SEC,
        )
        sock.settimeout(_READ_TIMEOUT_SEC)
        self._sock = sock

        if self._stop_event.is_set():
            # stop() may have raced create_connection(): by the time it ran,
            # self._sock was still None (or the previous connection's), so
            # stop() had nothing of ITS to shut down, and this thread was
            # about to proceed into a blocking header read that nothing will
            # ever interrupt again (measured: the full 30 s _READ_TIMEOUT_SEC
            # to time out, instead of returning promptly). Check again right
            # here, immediately after publishing self._sock, and bail before
            # the blocking read (final review M3).
            try:
                sock.close()
            except OSError:
                pass
            self._sock = None
            return

        try:
            request = build_request(
                host=self._cfg.caster_host,
                mountpoint=self._cfg.mountpoint,
                username=self._cfg.username,
                password=self._password,
            )
            sock.sendall(request)

            # Read response headers (small; terminated by \r\n\r\n). recv()
            # reads in chunks, so whatever arrived past the terminator in the
            # same chunk is already-received body — a "tail" that must be
            # forwarded, not dropped (it was previously silently lost here).
            header_buf = self._read_until(sock, b"\r\n\r\n", limit=4096)
            head, _, tail = header_buf.partition(b"\r\n\r\n")
            code, reason = parse_response_status(head)
            if code == 401:
                raise NtripFatalError(
                    f"caster rejected credentials (401) for mountpoint "
                    f"{self._cfg.mountpoint!r}; check ${self._cfg.password_env}"
                )
            if code == 404:
                raise NtripFatalError(
                    f"caster does not serve mountpoint {self._cfg.mountpoint!r} (404)"
                )
            if code != 200:
                raise NtripError(f"caster returned HTTP {code} {reason!r}")
            if _is_chunked_transfer_encoding(head):
                raise NtripFatalError(
                    "caster uses chunked transfer encoding, which is not supported"
                )

            with self._stats_lock:
                self._stats.connected = True
                self._stats.connect_count += 1
                self._stats.last_error = ""
            self._publish_stats()
            logger.info(
                "NTRIP connected to %s:%d/%s",
                self._cfg.caster_host,
                self._cfg.caster_port,
                self._cfg.mountpoint,
            )

            # Stream RTCM until close
            self._stream_body(sock, tail)
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._sock = None
            with self._stats_lock:
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

    def _stream_body(self, sock: socket.socket, tail: bytes = b"") -> None:
        """Read RTCM bytes from socket and dispatch them to the sink.

        The caster simply streams bytes — there's no chunked encoding, no
        framing. Whatever arrives is RTCM3 raw bytes that the F9P knows how to
        parse on its own. The received-bytes-per-second stat is computed from
        a monotonic window rather than wall-clock second boundaries, so it
        isn't skewed by a clock step.

        *tail* is body bytes that arrived bundled with the response headers
        in the same recv() chunk during the handshake (see _one_connection) —
        dispatched to the sink first, exactly as if they had arrived here.

        When `[ntrip].gga_send_interval_sec` > 0 and a gga_source was
        supplied, this also uploads a `$GPGGA` sentence on that cadence —
        required by VRS-style casters that steer corrections off the rover's
        own position. The socket read timeout is shortened to the GGA
        interval so the loop wakes up on schedule even with no RTCM traffic;
        that shortened per-tick timeout is not itself treated as a stall —
        only going _READ_TIMEOUT_SEC with zero bytes of any kind triggers a
        reconnect.
        """
        self._window_start = time.monotonic()
        self._window_bytes = 0
        interval = self._cfg.gga_send_interval_sec
        if interval > 0:
            sock.settimeout(min(_READ_TIMEOUT_SEC, interval))
        next_gga = time.monotonic()  # send one immediately, then every interval
        last_byte = time.monotonic()

        if tail:
            last_byte = time.monotonic()
            self._dispatch_chunk(tail)

        while not self._stop_event.is_set():
            if interval > 0 and self._gga_source is not None and time.monotonic() >= next_gga:
                fix = self._gga_source()
                if fix is not None and fix.fix_type >= 2:
                    try:
                        sock.sendall(build_gga(fix))
                    except OSError as e:
                        logger.info("NTRIP GGA send failed: %s", e)
                        with self._stats_lock:
                            self._stats.bytes_received_this_sec = 0
                        return
                next_gga = time.monotonic() + interval

            try:
                chunk = sock.recv(_READ_CHUNK_SIZE)
            except TimeoutError:
                if interval > 0 and time.monotonic() - last_byte < _READ_TIMEOUT_SEC:
                    # Just the shortened per-tick timeout that lets us send
                    # GGA on schedule — not a real stall.
                    continue
                logger.info("NTRIP read timeout; will reconnect")
                with self._stats_lock:
                    self._stats.bytes_received_this_sec = 0
                return
            if not chunk:
                logger.info("NTRIP caster closed connection; will reconnect")
                with self._stats_lock:
                    self._stats.bytes_received_this_sec = 0
                return

            last_byte = time.monotonic()
            self._dispatch_chunk(chunk)

    def _dispatch_chunk(self, chunk: bytes) -> None:
        """Forward one chunk of RTCM bytes to the sink and fold it into stats."""
        with self._stats_lock:
            self._stats.bytes_received_total += len(chunk)
            self._stats.last_byte_epoch = time.time()

        try:
            self._rtcm_sink(chunk)
        except Exception as e:
            # Sink errors should not kill the NTRIP loop — log and keep going
            logger.warning("RTCM sink raised: %s", e)

        now = time.monotonic()
        self._window_bytes += len(chunk)
        if now - self._window_start >= 1.0:
            with self._stats_lock:
                self._stats.bytes_received_this_sec = int(
                    self._window_bytes / (now - self._window_start)
                )
            self._window_start, self._window_bytes = now, 0
            self._publish_stats()

    def _publish_stats(self) -> None:
        if self._status_sink is None:
            return
        try:
            self._status_sink(self.stats)
        except Exception as e:  # pragma: no cover — defensive
            logger.warning("ntrip status_sink raised: %s", e)


__all__ = [
    "NtripClient",
    "NtripStats",
    "NtripError",
    "NtripFatalError",
    "build_request",
    "build_gga",
    "parse_response_status",
    "USER_AGENT",
    "NTRIP_VERSION",
]
