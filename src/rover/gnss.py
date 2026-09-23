"""ZED-F9P GNSS receiver — NMEA + UBX parsing, RTCM injection.

Two responsibilities, owned by GnssReceiver:

1. **Read** position / fix info from the F9P over USB serial. NMEA GGA gives us
   the basics (lat, lon, alt, fix quality, sat count, HDOP); UBX NAV-PVT is
   used opportunistically when pyubx2 is available (gives us a finer fix-type
   discrimination including RTK FLOAT vs FIX).

   Source selection: `_ubx_active` becomes True only once a NAV-PVT message
   has actually been parsed — constructing the UBXReader doesn't guarantee
   the F9P ever emits one. Once active, NAV-PVT is the sole position source;
   a GGA sentence arriving in the same session only contributes its
   `rtk_age` and `hdop` to the latest NAV-PVT fix (see `_record_fix`) — NAV-PVT
   itself has neither. If NAV-PVT then
   goes quiet for more than `_NAVPVT_STALE_SEC`, GGA resumes as the source
   (one warning logged) until NAV-PVT reappears. Without pyubx2, GGA is the
   only source there ever is. A GGA-carried `rtk_age` merged onto a NAV-PVT
   fix expires after `_RTK_AGE_VALID_SEC` rather than freezing forever if
   RTCM stops arriving. Heights from both paths are normalised to
   ellipsoidal (WGS84) metres before they reach GnssFix — GGA field 9 (MSL)
   is corrected by field 11 (geoid separation); NAV-PVT uses `height`, not
   `hMSL`.

2. **Write** RTCM3 corrections **to** the F9P when [ntrip].client_location =
   "pi". This is the data path that supersedes the original DEC-006 "Pi never in
   the correction path" rule — see DEC-032. NtripClient calls `write_rtcm(bytes)`
   on us; we forward to the open serial port.

When [ntrip].client_location = "esp32", the ESP32 firmware writes RTCM to the
F9P's UART2 directly and we do nothing on the write side.

The receiver runs a background thread that reads the serial port and parses
incoming sentences into GnssFix snapshots. Other modules call `latest_fix()`
for the current snapshot.

Public API:
    GnssFix         — frozen dataclass; one position snapshot
    GnssReceiver    — driver class
        .start(), .stop(), .latest_fix(), .write_rtcm(bytes)

Decision references:
    DEC-004  ZED-F9P selection
    DEC-031  NTRIP-primary RTK (rover is a client; was DEC-005)
    DEC-032  NTRIP client location pi or esp32 (was DEC-006)

Dependencies:
    pyserial (required for actual hardware)
    pyubx2   (optional; better UBX parsing — Base-Station uses this)

Changelog:
    0.10.0  2026-05-23  Replaced stub with NMEA/UBX reader + RTCM writer (Phase C).
    0.11.0  2026-09-23  NAV-PVT sole fix source when pyubx2 present (GGA now only
                        merges rtk_age); added pdop; ellipsoidal heights from both
                        GGA and NAV-PVT; _serial_lock guards writes only;
                        subscribe()/_callbacks removed; line_buf capped;
                        FIX_* constants imported from rover.lora_protocol
                        (T1-019, T1-020, T1-049, S2-R1).
    0.11.1  2026-09-23  Fix round 1: NAV-PVT becomes the source only once a
                        NAV-PVT message has actually been parsed (not merely
                        when the UBXReader is constructed), and GGA resumes
                        as the source if NAV-PVT goes quiet for more than
                        _NAVPVT_STALE_SEC; a carried-forward rtk_age expires
                        after _RTK_AGE_VALID_SEC instead of freezing forever;
                        write_rtcm's serial-None check moved inside the lock.
    0.11.2  2026-09-23  _record_fix's NAV-PVT-active branch now also merges
                        the latest GGA hdop onto the published fix (NAV-PVT
                        itself has no HDOP field) instead of leaking the
                        99.9 placeholder into telemetry and build_gga
                        (final review I1).
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from dataclasses import dataclass

from rover.config import RoverConfig
from rover.lora_protocol import FIX_2D, FIX_3D, FIX_DGPS, FIX_NONE, FIX_RTK_FIX, FIX_RTK_FLOAT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class GnssFix:
    """Single GNSS position fix.

    Fields mirror the JSONL `gnss` record schema (Appendix B in CLAUDE.md) so
    serialization is straightforward.
    """

    timestamp: float = 0.0  # Unix timestamp at fix
    fix_type: int = 0  # 0=NONE 1=2D 2=3D 3=DGPS 4=RTK_FLOAT 5=RTK_FIX
    lat: float = 0.0  # WGS84 decimal degrees
    lon: float = 0.0  # WGS84 decimal degrees
    alt: float = 0.0  # Ellipsoidal (WGS84) metres — both sources normalise to this
    hdop: float = 99.9
    vdop: float = 99.9
    pdop: float = 99.9  # NAV-PVT position DOP; 99.9 when the source is GGA
    sat_count: int = 0
    rtk_age: float = -1.0  # Seconds since last RTCM; -1 = unknown


# ---------------------------------------------------------------------------
# NMEA helpers — stdlib-only so they're testable off-Pi
# ---------------------------------------------------------------------------


def _nmea_checksum_ok(sentence: str) -> bool:
    """Verify a `$...*HH` NMEA sentence's XOR checksum."""
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, _, checksum = sentence[1:].partition("*")
    checksum = checksum.strip()
    if len(checksum) < 2:
        return False
    want = int(checksum[:2], 16)
    got = 0
    for c in body:
        got ^= ord(c)
    return want == got


def _nmea_to_decimal(coord: str, hemi: str) -> float:
    """Convert ddmm.mmmm/[NSEW] to signed decimal degrees. Returns 0.0 on parse failure."""
    if not coord:
        return 0.0
    try:
        # NMEA: lat=ddmm.mmmm, lon=dddmm.mmmm
        if "." not in coord:
            return 0.0
        dot = coord.index(".")
        # The two digits immediately left of the decimal are minutes' integer part
        deg_str = coord[: dot - 2]
        min_str = coord[dot - 2 :]
        if not deg_str:
            return 0.0
        degrees = int(deg_str)
        minutes = float(min_str)
        result = degrees + minutes / 60.0
        if hemi in ("S", "W"):
            result = -result
        return result
    except (ValueError, IndexError):
        return 0.0


# Mapping from NMEA GGA quality indicator → our internal fix_type enum.
#
# NMEA-0183 GGA quality (key side, the wire vocabulary the F9P emits — and
# the same vocabulary the sibling Base-Station speaks; see
# arm-drone-lidar-workflow/base-station/manager_nav_pvt.py:nav_pvt_to_quality):
#   0=no fix, 1=SPS, 2=DGPS, 4=RTK FIXED, 5=RTK FLOAT.
#
# Rover internal fix_type (value side, the enum the rest of this codebase
# uses — see GnssFix above):
#   0=NONE, 1=2D, 2=3D, 3=DGPS, 4=RTK_FLOAT, 5=RTK_FIX.
#
# Watch the swap: NMEA puts FIXED=4 and FLOAT=5; we put FLOAT=4 and FIX=5 so
# the enum is monotonic-in-quality. Any external consumer that reads our
# status.json must therefore use the rover's enum, not the GGA wire one. This
# divergence is called out in BASE_STATION_INTEGRATION.md.
_GGA_QUALITY_TO_FIX = {
    0: FIX_NONE,  # invalid → NONE
    1: FIX_3D,  # GPS standalone → 3D (approximation; we don't distinguish 2D here)
    2: FIX_DGPS,  # DGPS
    3: FIX_DGPS,  # PPS (rare; map to DGPS for our buckets)
    4: FIX_RTK_FIX,  # GGA "RTK Fixed" → rover RTK_FIX
    5: FIX_RTK_FLOAT,  # GGA "RTK Float" → rover RTK_FLOAT
    6: FIX_3D,  # estimated/dead-reckoning → call it 3D-ish
    7: FIX_NONE,  # manual → NONE
    8: FIX_NONE,  # simulator → NONE
}


def parse_gga(sentence: str) -> GnssFix | None:
    """Parse a `$GPGGA`/`$GNGGA` sentence into a GnssFix.

    Returns None if checksum fails or the sentence doesn't have enough fields.
    Time is *not* extracted as Unix time (the receiver fills that in with
    time.time() at sentence arrival — GNSS time-of-day → Unix conversion needs
    a date source the GGA sentence doesn't carry).
    """
    if not _nmea_checksum_ok(sentence):
        return None
    body = sentence[1:].split("*")[0]
    fields = body.split(",")
    # Minimum field positions: 0=type 1=time 2=lat 3=NS 4=lon 5=EW 6=quality
    # 7=sats 8=hdop 9=alt 10=alt_unit 11=geoid 12=geoid_unit 13=age_dgps 14=ref
    if len(fields) < 11:
        return None
    if fields[0][2:] != "GGA":
        return None

    try:
        quality = int(fields[6]) if fields[6] else 0
    except ValueError:
        quality = 0
    fix_type = _GGA_QUALITY_TO_FIX.get(quality, 0)

    try:
        sat_count = int(fields[7]) if fields[7] else 0
    except ValueError:
        sat_count = 0

    try:
        hdop = float(fields[8]) if fields[8] else 99.9
    except ValueError:
        hdop = 99.9

    try:
        alt = float(fields[9]) if fields[9] else 0.0
    except ValueError:
        alt = 0.0

    try:
        geoid = float(fields[11]) if len(fields) > 11 and fields[11] else 0.0
    except ValueError:
        geoid = 0.0
    # GGA field 9 is MSL; field 11 is geoid separation (ellipsoid - geoid) → ellipsoidal
    alt = alt + geoid

    rtk_age = -1.0
    if len(fields) >= 14 and fields[13]:
        try:
            rtk_age = float(fields[13])
        except ValueError:
            rtk_age = -1.0

    lat = _nmea_to_decimal(fields[2], fields[3])
    lon = _nmea_to_decimal(fields[4], fields[5])

    return GnssFix(
        timestamp=time.time(),
        fix_type=fix_type,
        lat=lat,
        lon=lon,
        alt=alt,
        hdop=hdop,
        vdop=99.9,
        sat_count=sat_count,
        rtk_age=rtk_age,
    )


# ---------------------------------------------------------------------------
# GnssReceiver — background-thread serial reader + RTCM injector
# ---------------------------------------------------------------------------

_LINE_BUF_MAX = 1024  # cap on the NMEA-only read buffer; drop oldest overflow
_NAVPVT_STALE_SEC = 5.0  # no NAV-PVT for this long while active → GGA resumes as source
_RTK_AGE_VALID_SEC = 10.0  # a carried-forward rtk_age older than this is dropped (unknown)
_NAV_PVT_NO_HDOP = 99.9  # GnssFix.hdop placeholder: NAV-PVT carries no HDOP


class GnssReceiver:
    """ZED-F9P GNSS reader and RTCM injector.

    Args:
        config: RoverConfig (we read .gnss).
    """

    def __init__(self, config: RoverConfig) -> None:
        self._cfg = config.gnss
        self._ntrip_cfg = config.ntrip
        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial = None  # opened in start(); pyserial is a Pi-only dep
        self._serial_lock = threading.Lock()  # protects write_rtcm() and close() only
        self._lock = threading.Lock()
        self._latest: GnssFix | None = None
        self._ubx_active = False  # True once a NAV-PVT message has actually been parsed
        self._last_navpvt_mono = 0.0  # time.monotonic() of the most recent NAV-PVT parse
        self._rtk_age_mono = 0.0  # time.monotonic() when the last valid rtk_age was merged

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open serial port, start read thread."""
        if self._running:
            logger.warning("GnssReceiver.start() called twice — ignoring")
            return
        if not self._cfg.enabled:
            logger.info("GNSS disabled in config; receiver not starting")
            return

        try:
            import serial  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("GnssReceiver: pyserial not available; receiver disabled this run")
            return

        try:
            self._serial = serial.Serial(self._cfg.port, self._cfg.baud, timeout=0.5)
        except OSError as e:
            logger.warning(
                "GnssReceiver: cannot open %s @ %d: %s",
                self._cfg.port,
                self._cfg.baud,
                e,
            )
            return

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._read_loop, name="rover-gnss-reader", daemon=True
        )
        self._thread.start()
        logger.info("GnssReceiver started: %s @ %d", self._cfg.port, self._cfg.baud)

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._serial is not None:
            with self._serial_lock:
                try:
                    self._serial.close()
                except OSError:
                    pass
            self._serial = None

    # ------------------------------------------------------------------
    # Read path — parse NMEA (and UBX if pyubx2 is present)
    # ------------------------------------------------------------------

    def _read_loop(self) -> None:
        """Background thread: read lines from serial, parse, fan out."""
        # Try to enable richer UBX parsing if pyubx2 is around — but the NMEA
        # GGA fallback always works.
        ubx_reader = None
        try:
            from pyubx2 import UBXReader  # type: ignore[import-not-found]

            ubx_reader = UBXReader(self._serial, protfilter=3)  # NMEA+UBX
            # _ubx_active is set True only once a NAV-PVT message is actually
            # parsed (see _read_with_pyubx2) — constructing the reader doesn't
            # guarantee the F9P ever emits one.
        except ImportError:
            logger.info("pyubx2 not available — GnssReceiver using NMEA-GGA only")
        except Exception as e:
            logger.warning("pyubx2 init failed (%s); falling back to NMEA only", e)
            ubx_reader = None

        line_buf = b""
        while not self._stop_event.is_set():
            try:
                if ubx_reader is not None:
                    self._read_with_pyubx2(ubx_reader)
                else:
                    line_buf = self._read_nmea_only(line_buf)
            except OSError as e:
                logger.warning("GnssReceiver read error: %s", e)
                time.sleep(0.5)
            except Exception as e:  # pragma: no cover — defensive
                logger.exception("GnssReceiver unexpected error: %s", e)
                time.sleep(0.5)

    def _read_nmea_only(self, line_buf: bytes) -> bytes:
        """Read bytes and emit complete `$...\\r\\n` NMEA sentences.

        Not guarded by `_serial_lock` — that lock protects writes (and close())
        against a concurrent read; a blocking 0.5 s read here must not stall
        RTCM writes from the NTRIP thread.
        """
        chunk = self._serial.read(256) if self._serial else b""
        if not chunk:
            return line_buf
        line_buf += chunk
        if len(line_buf) > _LINE_BUF_MAX:
            # No sentence boundary found in a long stretch of bytes — drop the
            # oldest overflow rather than growing this buffer unbounded.
            line_buf = line_buf[-_LINE_BUF_MAX:]
        while True:
            nl_idx = line_buf.find(b"\n")
            if nl_idx < 0:
                break
            line = line_buf[: nl_idx + 1]
            line_buf = line_buf[nl_idx + 1 :]
            text = line.decode("ascii", errors="replace").strip()
            if text.startswith("$") and "GGA" in text[:10]:
                fix = parse_gga(text)
                if fix is not None:
                    self._record_fix(fix, source="gga")
        return line_buf

    def _read_with_pyubx2(self, ubx_reader) -> None:  # noqa: ANN001 (3rd-party type)
        """One iteration of the pyubx2 read loop."""
        raw, parsed = ubx_reader.read()
        if parsed is None:
            return
        identity = getattr(parsed, "identity", "")
        if identity in ("GNGGA", "GPGGA"):
            fix = parse_gga(raw.decode("ascii", errors="replace").strip())
            if fix is not None:
                self._record_fix(fix, source="gga")
        elif identity == "NAV-PVT":
            # NAV-PVT becomes the position source only once it's actually seen.
            self._ubx_active = True
            self._last_navpvt_mono = time.monotonic()
            self._record_fix(_fix_from_nav_pvt(parsed), source="nav_pvt")

    def _record_fix(self, fix: GnssFix, source: str) -> None:
        with self._lock:
            if source == "gga" and self._ubx_active:
                if time.monotonic() - self._last_navpvt_mono > _NAVPVT_STALE_SEC:
                    logger.warning("NAV-PVT stopped; falling back to GGA")
                    self._ubx_active = False
                    # Fall through — GGA is accepted as the source below.
                else:
                    # NAV-PVT is the position source; GGA only contributes the
                    # RTCM age and HDOP — NAV-PVT itself carries no HDOP (see
                    # _fix_from_nav_pvt) and would otherwise leak its 99.9
                    # placeholder into telemetry/build_gga forever (I1).
                    if self._latest is not None:
                        updates: dict[str, float] = {"hdop": fix.hdop}
                        if fix.rtk_age >= 0:
                            updates["rtk_age"] = fix.rtk_age
                            self._rtk_age_mono = time.monotonic()
                        self._latest = dataclasses.replace(self._latest, **updates)
                    return
            if (
                source == "nav_pvt"
                and self._latest is not None
                and self._latest.rtk_age >= 0
                and fix.rtk_age < 0
                and time.monotonic() - self._rtk_age_mono <= _RTK_AGE_VALID_SEC
            ):
                fix = dataclasses.replace(fix, rtk_age=self._latest.rtk_age)
            if (
                source == "nav_pvt"
                and self._latest is not None
                and self._latest.hdop < _NAV_PVT_NO_HDOP
            ):
                # Keep GGA's last real HDOP across NAV-PVT epochs; otherwise
                # every epoch resets it to the 99.9 placeholder until the next
                # GGA arrives, and the main loop only reads new timestamps.
                fix = dataclasses.replace(fix, hdop=self._latest.hdop)
            self._latest = fix

    def latest_fix(self) -> GnssFix | None:
        with self._lock:
            return self._latest

    # ------------------------------------------------------------------
    # Write path — RTCM into F9P (Pi-NTRIP mode only)
    # ------------------------------------------------------------------

    def write_rtcm(self, data: bytes) -> None:
        """Forward RTCM3 bytes to the F9P. Called by NtripClient when
        client_location = "pi".

        When client_location = "esp32", this method should never be called
        (ESP32 writes RTCM directly to F9P UART2); we log a one-shot warning
        if it happens, since it indicates a misconfiguration.
        """
        if self._ntrip_cfg.client_location != "pi":
            logger.warning(
                "GnssReceiver.write_rtcm called but client_location=%r — "
                "ignoring (ESP32 owns the RTCM path in that mode)",
                self._ntrip_cfg.client_location,
            )
            return
        with self._serial_lock:
            if self._serial is None:
                return
            try:
                self._serial.write(data)
            except OSError as e:
                logger.warning("write_rtcm failed: %s", e)


def _fix_from_nav_pvt(msg) -> GnssFix:  # noqa: ANN001 (pyubx2 type)
    """Convert a pyubx2 NAV-PVT message to a GnssFix.

    pyubx2 (default `scaling=True`) already delivers `lat`/`lon` in degrees,
    `height`/`hMSL` in mm, `pDOP` scaled, and expands the flags byte into its
    own `carrSoln` attribute (0=none 1=float 2=fix) — do not re-divide or
    re-shift any of these. `height` is ellipsoidal (WGS84); `hMSL` is
    orthometric — we use `height` so both fix sources agree on datum.
    NAV-PVT carries no HDOP, so `hdop` is always 99.9 here; `pdop` carries the
    real DOP figure instead. `_record_fix` overwrites this placeholder from
    the latest GGA sentence, if one has been seen, once this fix becomes the
    published `_latest` (I1). fixType is 1=DR 2=2D 3=3D 4=GNSS+DR 5=time-only;
    combined with carrSoln we translate that pair back into our 0..5 enum.
    """
    fix_type_raw = getattr(msg, "fixType", 0)
    carr_soln = getattr(msg, "carrSoln", 0)

    fix_type = FIX_NONE
    if fix_type_raw == 2:
        fix_type = FIX_2D
    elif fix_type_raw in (3, 4):
        fix_type = FIX_3D  # 3D (4 = GNSS + dead reckoning)
    # fixType 1 (dead-reckoning only) and 5 (time-only) carry no position fix;
    # fix_type stays FIX_NONE for both.
    if carr_soln == 1:
        fix_type = FIX_RTK_FLOAT
    elif carr_soln == 2:
        fix_type = FIX_RTK_FIX

    return GnssFix(
        timestamp=time.time(),
        fix_type=fix_type,
        lat=float(getattr(msg, "lat", 0.0)),
        lon=float(getattr(msg, "lon", 0.0)),
        alt=float(getattr(msg, "height", 0)) / 1000.0,  # ellipsoidal, mm → m
        hdop=99.9,  # NAV-PVT has no HDOP
        vdop=99.9,  # NAV-PVT doesn't break out vDOP
        pdop=float(getattr(msg, "pDOP", 99.9)),
        sat_count=int(getattr(msg, "numSV", 0)),
        rtk_age=-1.0,  # NAV-PVT iTOW differs from RTCM age; merged from GGA by _record_fix
    )


__all__ = [
    "GnssFix",
    "GnssReceiver",
    "parse_gga",
]
