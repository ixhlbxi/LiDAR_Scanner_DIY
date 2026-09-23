# Stage 4 — Comms and Config Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The NTRIP path fails loudly when it must and works against VRS casters, GNSS logs one consistent fix source with ellipsoidal heights, telemetry publishes on per-channel cadences with no placeholder values masquerading as readings, every config key has a consumer, the GPIO backend is verified, and the test tree has no duplicated fixtures or driver code.

**Architecture:** Nine code tasks on branch `fix/stage4-comms-config`, then merge. `NtripClient` gains profile awareness, a fatal-error latch that `run()` honours, GGA upload from the GNSS receiver, header-tail forwarding and chunked-encoding refusal. `GnssReceiver` picks one fix source, adds `pdop`, logs ellipsoidal heights from both paths, and locks writes only. `TelemetryRouter` owns per-channel cadence and a schema-v2 payload that omits unmeasured fields and reports degraded state. Config sheds dead sections. `stepper.py` detects the GPIO backend. The logger stops mirroring GNSS into the scan log and counts real losses. Test hygiene lands last.

**Tech Stack:** Python 3.11 stdlib (`socket`, `socketpair`, `threading`, `binascii`, `dataclasses`), pytest, pyubx2.

**Spec:** `docs/superpowers/specs/2026-09-22-audit-remediation-design.md` §6, plus backlog rows S2-R1..S2-R4 and T1-033 in `docs/CROSS_REPO_BACKLOG.md`.

**Carried to stage 5 (docs), not this stage:** stage 3 found `ZONE_EPSG` mislabelled (EPSG 6346 is UTM 17N, not PA North ftUS; the correct code is 6563) and fixed code/config/tests; the doc mentions at `docs/ARCHITECTURE.md:484,489`, `docs/BASE_STATION_INTEGRATION.md:252` (the §5 zone table, a cross-repo contract) and `docs/DECISIONS.md:1159` still say 6346 and must be corrected in stage 5 from the table in `scripts/georef.py`.

## Global Constraints

- `BASE_STATION_INTEGRATION.md` §7: a 401 in the `arm_group` profile refuses to start (loud failure); in `personal` it warns and continues.
- Sensors and channels never crash the system; a publisher failure never raises out of `publish()`.
- status.json is a cross-repo contract: adding fields is a minor bump (`STATUS_SCHEMA_VERSION` 1 → 2); no field is removed or renamed.
- `GnssFix.alt` is documented as ellipsoidal metres; both fix sources must honour that (S2-R1).
- `[lora]` radio parameters stay in config as documentation only and must equal the firmware build flags in `firmware/esp32-rover/platformio.ini`.
- Style `X | None`; ruff clean (`python -m ruff format` then `python -m ruff check` on touched files); commit trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; do not push.
- Suite baseline is measured at the stage 3 merge; it must not go down.
- Findings closed: T1-004, T1-019, T1-020, T1-022, T1-023, T1-025, T1-026, T1-030, T1-033, T1-041, T1-042 (Python half), T1-046, T1-047, T1-049, T1-053, T2-005 (remainder), T2-006, T2-007, T2-008, and backlog S2-R1, S2-R2, S2-R3, S2-R4.

## Review Focus

1. **A caster that answers 401 on an `arm_group` survey** must end the process with a distinct exit code before any scan data is written, not run for four hours without RTK. Pinned by Task 1 (`test_run_aborts_on_401_in_arm_group`).
2. **A VRS caster that needs GGA** must receive one within the first interval, built from the latest fix, with a valid checksum. Pinned by Task 2 (`test_gga_sent_on_interval`).
3. **A caster whose first read returns headers plus the start of the RTCM body** must not lose those body bytes. Pinned by Task 2 (`test_header_tail_forwarded_to_sink`).
4. **pyubx2 present, F9P emitting both GGA and NAV-PVT**: the logged fix must not alternate sources or datums epoch to epoch. Pinned by Task 3 (`test_nav_pvt_is_sole_source_when_ubx_present`).
5. **A LoRa channel at 1 Hz and status.json at 5 Hz** must each publish on its own cadence from one `publish()` call per loop. Pinned by Task 4 (`test_router_per_channel_cadence`).

---

### Task 1: NTRIP — profile-aware fatal errors, clean shutdown, stats snapshots

**Files:**
- Modify: `src/rover/ntrip.py` (`NtripClient.__init__`, `_run_loop`, `_one_connection`, `stop`, `_stream_body`, `_publish_stats`; docstrings)
- Modify: `src/rover/main.py` (`run()`: abort on `fatal_error` after NTRIP start)
- Test: `tests/test_ntrip.py`, `tests/test_main.py`

**Interfaces:**
- Produces: `NtripClient(config, rtcm_sink, status_sink=None, gga_source=None)`; property `fatal_error: str | None` (set on 401/404 when `config.session.profile == "arm_group"`, after which the loop exits); `stop()` shuts down the live socket; `stats` returns `dataclasses.replace(self._stats)` (a snapshot) and the sink receives snapshots; `bytes_received_this_sec` computed from a 1 s window; `_device_name` removed; `run()` returns exit code **4** when `ntrip_client.fatal_error` is set within `_NTRIP_FATAL_GRACE_SEC = 3.0` s of start, with one ERROR line. In `personal`, 401/404 log one WARNING then retry at DEBUG.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ntrip.py`)

```python
import socket
import threading
import time
from dataclasses import replace

from rover.config import load_config
from rover.ntrip import NtripClient, NtripStats


def _cfg(tmp_path, profile="personal", extra=""):
    p = tmp_path / "c.toml"
    p.write_text(
        f"""
[session]
profile = "{profile}"
project_code = "{'TEST' if profile == 'arm_group' else ''}"
target_crs_epsg = {6346 if profile == 'arm_group' else 0}

[base_station_integration]
enabled = {'true' if profile == 'arm_group' else 'false'}
status_json_path = "{(tmp_path / 'status.json').as_posix()}"

[gnss]
enabled = true

[ntrip]
enabled = true
client_location = "pi"
caster_host = "127.0.0.1"
caster_port = 1
mountpoint = "ARM_BASE"
{extra}
"""
    )
    return load_config(p)


class _FakeCaster:
    """One-shot TCP caster on 127.0.0.1: answers with `response` then optionally streams `body`."""

    def __init__(self, response: bytes, body: bytes = b"", hold_open: float = 0.0):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.response, self.body, self.hold_open = response, body, hold_open
        self.received = b""
        self.t = threading.Thread(target=self._serve, daemon=True)
        self.t.start()

    def _serve(self):
        conn, _ = self.srv.accept()
        conn.settimeout(2.0)
        try:
            self.received = conn.recv(4096)
            conn.sendall(self.response + self.body)
            if self.hold_open:
                time.sleep(self.hold_open)
        finally:
            conn.close()
            self.srv.close()


def _client(cfg, caster, sink=None, **kw):
    cfg = replace(cfg, ntrip=replace(cfg.ntrip, caster_port=caster.port))
    return NtripClient(cfg, rtcm_sink=sink or (lambda b: None), **kw)


class TestFatalErrors:
    def test_401_in_arm_group_sets_fatal_and_stops(self, tmp_path):
        caster = _FakeCaster(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
        c = _client(_cfg(tmp_path, "arm_group"), caster)
        c.start()
        deadline = time.monotonic() + 3
        while c.fatal_error is None and time.monotonic() < deadline:
            time.sleep(0.02)
        try:
            assert c.fatal_error is not None and "401" in c.fatal_error
            assert not c._thread.is_alive()
        finally:
            c.stop()

    def test_401_in_personal_is_not_fatal(self, tmp_path):
        caster = _FakeCaster(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
        c = _client(_cfg(tmp_path, "personal"), caster)
        c.start()
        time.sleep(0.5)
        try:
            assert c.fatal_error is None
            assert c.stats.error_count >= 1
        finally:
            c.stop()

    def test_stats_property_is_a_snapshot(self, tmp_path):
        caster = _FakeCaster(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
        c = _client(_cfg(tmp_path), caster)
        a = c.stats
        a.error_count = 999
        assert c.stats.error_count != 999

    def test_stop_closes_live_socket_promptly(self, tmp_path):
        caster = _FakeCaster(b"ICY 200 OK\r\n\r\n", body=b"\xd3\x00", hold_open=5.0)
        got = []
        c = _client(_cfg(tmp_path), caster, sink=got.append)
        c.start()
        time.sleep(0.3)
        t0 = time.monotonic()
        c.stop()
        assert time.monotonic() - t0 < 2.0, "stop() must not wait out the 30 s read timeout"
```

And in `tests/test_main.py`:

```python
def test_run_aborts_on_401_in_arm_group(tmp_path: Path, monkeypatch) -> None:
    """BASE_STATION_INTEGRATION §7: refuse to start in arm_group on a 401 (T1-004)."""
    import socket
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _serve():
        conn, _ = srv.accept()
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
        conn.close()
        srv.close()

    threading.Thread(target=_serve, daemon=True).start()

    class _FakeGnss:
        def __init__(self, *_a, **_kw): ...
        @property
        def available(self): return True
        def start(self): ...
        def stop(self): ...
        def latest_fix(self): return None
        def write_rtcm(self, b): ...

    monkeypatch.setattr(main_mod, "GnssReceiver", _FakeGnss)
    cfg = tmp_path / "ag.toml"
    cfg.write_text(
        f"""
[session]
profile = "arm_group"
project_code = "TEST"
target_crs_epsg = 6346
[base_station_integration]
enabled = true
status_json_path = "{(tmp_path / 'status.json').as_posix()}"
[gnss]
enabled = true
[ntrip]
enabled = true
client_location = "pi"
caster_host = "127.0.0.1"
caster_port = {port}
mountpoint = "ARM_BASE"
[lidar]
enabled = false
[stepper]
enabled = false
[imu]
enabled = false
[camera]
enabled = false
[lora]
enabled = false
role = "disabled"
[telemetry]
http_enabled = false
[watchdog]
enabled = false
[logging]
output_dir = "{(tmp_path / 'data').as_posix()}"
session_prefix = "ag"
"""
    )
    assert main_mod.run(config_path=cfg, duration_sec=5.0) == 4
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_ntrip.py -q -k Fatal
python -m pytest tests/test_main.py -q -k aborts_on_401
```

Expected: `fatal_error` AttributeError; snapshot test FAIL (same object); stop test FAIL (waits); `run()` returns 0.

- [ ] **Step 3: Implement** in `src/rover/ntrip.py`

`__init__` (drop `_device_name`; add profile, latch, socket ref, gga_source placeholder for Task 2, rate window):

```python
    def __init__(
        self,
        config: RoverConfig,
        rtcm_sink: Callable[[bytes], None],
        status_sink: Callable[[NtripStats], None] | None = None,
        gga_source: Callable[[], "GnssFix | None"] | None = None,
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
        """Set when the caster rejected us in a way that will not self-heal
        (401/404) and the profile is arm_group; the loop has exited."""
        return self._fatal_error
```

(add `import dataclasses`; the `GnssFix` name is a string annotation — import it under `TYPE_CHECKING` from `rover.gnss` to avoid a cycle.)

`_run_loop`: on `NtripError`, decide by profile:

```python
            except NtripError as e:
                self._bump_error(str(e))
                if self._profile == "arm_group":
                    self._fatal_error = str(e)
                    logger.error("NTRIP fatal in arm_group profile — refusing to continue: %s", e)
                    self._publish_stats()
                    return
                if not warned_fatal:
                    logger.warning("NTRIP caster rejected us (%s); retrying every %.0fs", e, _BACKOFF_MAX_SEC)
                    warned_fatal = True
                else:
                    logger.debug("NTRIP still rejected: %s", e)
                backoff = _BACKOFF_MAX_SEC
                self._publish_stats()
```

with `warned_fatal = False` initialised before the loop. `_bump_error` increments `error_count`/`last_error` under `_stats_lock`. All other `self._stats.x = ...` writes go under `_stats_lock` (a tiny `_with_stats()` context or direct `with self._stats_lock:` blocks).

`_one_connection`: store the socket: `self._sock = sock` right after `create_connection`, and in the `finally` set `self._sock = None` after closing.

`stop()`:

```python
    def stop(self) -> None:
        self._stop_event.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
```

`_stream_body` rate: replace the `sec_marker/sec_bytes` logic with a monotonic window:

```python
            now = time.monotonic()
            self._window_bytes += len(chunk)
            if now - self._window_start >= 1.0:
                with self._stats_lock:
                    self._stats.bytes_received_this_sec = int(self._window_bytes / (now - self._window_start))
                self._window_start, self._window_bytes = now, 0
                self._publish_stats()
```

and on a stall (read timeout / close) zero the rate before returning. `_publish_stats` passes `self.stats` (the snapshot). Module docstring: `status_sink` receives `NtripStats`; `_resolve_password`: drop the "logged at info level" claim or add `logger.info` when the env var is missing — add the info log. Changelog `0.11.0`.

In `src/rover/main.py::run()`, right after `ntrip_client.start()` succeeds and before `Watchdog`:

```python
            if ntrip_client is not None:
                # A caster rejection in arm_group must stop the session before any
                # scan data is written (BASE_STATION_INTEGRATION.md §7).
                deadline = time.monotonic() + _NTRIP_FATAL_GRACE_SEC
                while time.monotonic() < deadline and ntrip_client.fatal_error is None:
                    if stop_event.wait(0.05):
                        break
                if ntrip_client.fatal_error is not None:
                    logger.error("Aborting: %s", ntrip_client.fatal_error)
                    raise _FatalStartupError(ntrip_client.fatal_error)
```

with module constants `_NTRIP_FATAL_GRACE_SEC = 3.0`, a small `class _FatalStartupError(RuntimeError)`, and in `run()`'s `except`: `except _FatalStartupError: exit_code = 4` placed before the generic `except Exception`. Also check `fatal_error` once inside `_scan_loop`'s publish block: if it becomes set later (e.g. caster reboots into 401), set `status.scan_state = SCAN_ERROR` and log once — no abort mid-session (the data already logged is still valid).

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_ntrip.py tests/test_main.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/ntrip.py src/rover/main.py tests/test_ntrip.py tests/test_main.py && python -m ruff check src/rover/ntrip.py src/rover/main.py tests/test_ntrip.py tests/test_main.py
git add src/rover/ntrip.py src/rover/main.py tests/test_ntrip.py tests/test_main.py
git commit -m "fix(ntrip): 401/404 fatal in arm_group with exit 4; socket shutdown on stop; stats snapshots and windowed rate (T1-004, T1-024, T1-049)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: NTRIP — GGA upload, header-tail forwarding, chunked refusal

**Files:**
- Modify: `src/rover/ntrip.py` (`build_gga`, `_one_connection`, `_stream_body`, `parse_response_status` headers check)
- Modify: `src/rover/main.py` (`NtripClient(..., gga_source=sensors.gnss.latest_fix)`)
- Test: `tests/test_ntrip.py`

**Interfaces:**
- Produces: `build_gga(fix: GnssFix, when: time.struct_time | None = None) -> bytes` (a `$GPGGA,...*HH\r\n` sentence with a correct XOR checksum; quality 1 for any fix ≥ 2, 4 for RTK_FIX, 5 for RTK_FLOAT); `_stream_body(sock, tail: bytes)` forwards `tail` to the sink first, then sends GGA every `gga_send_interval_sec` s when `> 0` and `gga_source()` returns a fix; `_one_connection` raises `NtripError("chunked transfer encoding is not supported")` when the response headers contain `Transfer-Encoding: chunked` (case-insensitive).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ntrip.py`)

```python
from rover.gnss import GnssFix
from rover.ntrip import build_gga


def _nmea_ok(sentence: bytes) -> bool:
    s = sentence.decode().strip()
    body, _, cs = s[1:].partition("*")
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"{x:02X}" == cs[:2]


class TestGga:
    def test_build_gga_valid_checksum_and_fields(self):
        fix = GnssFix(timestamp=0.0, fix_type=5, lat=40.7128, lon=-74.006, alt=10.5, hdop=0.8, sat_count=18)
        s = build_gga(fix, when=time.gmtime(0))
        assert s.startswith(b"$GPGGA,000000.00,4042.7680,N,07400.3600,W,4,18,0.8,10.5,M,")
        assert s.endswith(b"\r\n") and _nmea_ok(s)

    def test_build_gga_float_quality(self):
        fix = GnssFix(fix_type=4, lat=1.0, lon=1.0, sat_count=9)
        assert b",5,09," in build_gga(fix, when=time.gmtime(0))

    def test_gga_sent_on_interval(self, tmp_path):
        caster = _FakeCaster(b"ICY 200 OK\r\n\r\n", body=b"\xd3\x00\x01", hold_open=1.5)
        fix = GnssFix(fix_type=5, lat=40.0, lon=-75.0, alt=1.0, sat_count=10, hdop=1.0)
        c = _client(_cfg(tmp_path, extra="gga_send_interval_sec = 0.2"), caster, gga_source=lambda: fix)
        c.start()
        time.sleep(1.0)
        c.stop()
        assert b"$GPGGA" in caster.received or b"$GPGGA" in getattr(caster, "received_after", b"")

    def test_header_tail_forwarded_to_sink(self, tmp_path):
        caster = _FakeCaster(b"ICY 200 OK\r\n\r\n", body=b"\xd3\x00\x13TAILBYTES", hold_open=0.5)
        got: list[bytes] = []
        c = _client(_cfg(tmp_path), caster, sink=got.append)
        c.start()
        time.sleep(0.6)
        c.stop()
        assert b"".join(got).startswith(b"\xd3\x00\x13TAILBYTES")

    def test_chunked_encoding_is_refused(self, tmp_path):
        caster = _FakeCaster(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n", body=b"5\r\nhello\r\n")
        got: list[bytes] = []
        c = _client(_cfg(tmp_path, "arm_group"), caster, sink=got.append)
        c.start()
        deadline = time.monotonic() + 3
        while c.fatal_error is None and time.monotonic() < deadline:
            time.sleep(0.02)
        c.stop()
        assert c.fatal_error and "chunked" in c.fatal_error
        assert got == []
```

`_FakeCaster` needs to keep reading after sending, so `test_gga_sent_on_interval` can observe the GGA: extend `_serve` so that after `sendall`, while `hold_open` remains, it loops `conn.recv(4096)` with a short timeout and appends to `self.received_after` (initialise `self.received_after = b""` in `__init__`).

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_ntrip.py -q -k Gga
```

Expected: `build_gga` ImportError; tail test FAIL (bytes after headers dropped); chunked test FAIL (no fatal).

- [ ] **Step 3: Implement**

`build_gga`:

```python
def _nmea_checksum(body: str) -> str:
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"{x:02X}"


def _to_nmea(deg: float, is_lat: bool) -> tuple[str, str]:
    hemi = ("N" if deg >= 0 else "S") if is_lat else ("E" if deg >= 0 else "W")
    d = abs(deg)
    whole = int(d)
    minutes = (d - whole) * 60.0
    width = 2 if is_lat else 3
    return f"{whole:0{width}d}{minutes:07.4f}", hemi


def build_gga(fix: GnssFix, when: time.struct_time | None = None) -> bytes:
    """Build a `$GPGGA` sentence from *fix* for VRS-style casters.

    Quality: 4 = RTK fix, 5 = RTK float, 1 = any other fix, 0 = none.
    Altitude is reported as MSL with a zero geoid separation (the F9P's own
    sentence is not available here); casters use only lat/lon.
    """
    if when is None:
        when = time.gmtime()
    lat, ns = _to_nmea(fix.lat, True)
    lon, ew = _to_nmea(fix.lon, False)
    quality = {5: 4, 4: 5}.get(fix.fix_type, 1 if fix.fix_type >= 2 else 0)
    body = (
        f"GPGGA,{time.strftime('%H%M%S', when)}.00,{lat},{ns},{lon},{ew},{quality},"
        f"{fix.sat_count:02d},{fix.hdop:.1f},{fix.alt:.1f},M,0.0,M,,"
    )
    return f"${body}*{_nmea_checksum(body)}\r\n".encode("ascii")
```

`_one_connection`: after `header_buf = self._read_until(...)`, split `head, _, tail = header_buf.partition(b"\r\n\r\n")`; parse the status from `head`; if `b"transfer-encoding: chunked" in head.lower()` raise `NtripError("caster uses chunked transfer encoding, which is not supported")`; pass `tail` into `self._stream_body(sock, tail)`.

`_stream_body(self, sock, tail=b"")`: if `tail`, feed it through the same sink path as a chunk first. Add the GGA timer:

```python
        next_gga = time.monotonic()  # send one immediately, then every interval
        interval = self._cfg.gga_send_interval_sec
        while not self._stop_event.is_set():
            if interval > 0 and self._gga_source is not None and time.monotonic() >= next_gga:
                fix = self._gga_source()
                if fix is not None and fix.fix_type >= 2:
                    try:
                        sock.sendall(build_gga(fix))
                    except OSError as e:
                        logger.info("NTRIP GGA send failed: %s", e)
                        return
                next_gga = time.monotonic() + interval
            ... existing recv loop ...
```

Set `sock.settimeout(min(_READ_TIMEOUT_SEC, interval) if interval > 0 else _READ_TIMEOUT_SEC)` so the loop wakes to send GGA; on `socket.timeout` with `interval > 0` treat it as "no data this tick" and `continue` unless no bytes have arrived for `_READ_TIMEOUT_SEC` (track `last_byte` monotonic). The 401 fatal test from Task 1 must still pass.

`src/rover/main.py`: `NtripClient(config, rtcm_sink=sensors.gnss.write_rtcm, gga_source=sensors.gnss.latest_fix)`.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_ntrip.py tests/test_main.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/ntrip.py src/rover/main.py tests/test_ntrip.py && python -m ruff check src/rover/ntrip.py src/rover/main.py tests/test_ntrip.py
git add src/rover/ntrip.py src/rover/main.py tests/test_ntrip.py
git commit -m "feat(ntrip): periodic GGA upload for VRS casters; forward header tail; refuse chunked encoding (T1-022, T1-023)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: GNSS — single fix source, `pdop`, ellipsoidal heights, write-only lock

**Files:**
- Modify: `src/rover/gnss.py`
- Modify: `src/rover/main.py` (gnss record gains `pdop`)
- Test: `tests/test_gnss.py`

**Interfaces:**
- Produces: `GnssFix` gains `pdop: float = 99.9`; `parse_gga` returns `alt` = field 9 + field 11 (geoid separation) so it is ellipsoidal, and exposes `rtk_age`; `_fix_from_nav_pvt` uses `height` (ellipsoidal mm) and stores `pDOP` in `pdop` with `hdop = 99.9`; when pyubx2 is present NAV-PVT is the sole source and a GGA only updates `rtk_age` on the latest fix (`_merge_gga_age`); `_serial_lock` guards `write_rtcm` and `close()` only; `subscribe()` and `_callbacks` removed; `line_buf` capped at `_LINE_BUF_MAX = 1024`; `FIX_*` imported from `rover.lora_protocol` and used in `_GGA_QUALITY_TO_FIX` and `_fix_from_nav_pvt`; a comment states fixType 1 (DR) and 5 (time-only) map to `FIX_NONE`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_gnss.py`)

```python
class TestStage4Gnss:
    def test_gga_alt_is_ellipsoidal(self):
        # alt 10.5 m MSL + geoid separation -34.0 m → -23.5 m ellipsoidal
        fix = parse_gga(_fix_checksum("$GNGGA,143052.00,4042.76800,N,07400.36000,W,4,18,0.8,10.5,M,-34.0,M,1.2,0000*00"))
        assert fix.alt == pytest.approx(-23.5)

    def test_nav_pvt_uses_ellipsoidal_height_and_pdop(self):
        import pyubx2
        from rover.gnss import _fix_from_nav_pvt

        msg = pyubx2.UBXMessage("NAV", "NAV-PVT", pyubx2.GET, fixType=3, carrSoln=2, numSV=18,
                                lat=40.7128, lon=-74.006, height=12345, hMSL=10500, pDOP=1.2)
        fix = _fix_from_nav_pvt(pyubx2.UBXReader.parse(msg.serialize()))
        assert fix.alt == pytest.approx(12.345)
        assert fix.pdop == pytest.approx(1.2) and fix.hdop == 99.9

    def test_nav_pvt_is_sole_source_when_ubx_present(self):
        from rover.gnss import GnssReceiver

        r = GnssReceiver.__new__(GnssReceiver)
        r._lock = __import__("threading").Lock()
        r._latest = None
        r._ubx_active = True
        nav = GnssFix(timestamp=1.0, fix_type=5, lat=40.0, lon=-75.0, alt=5.0, pdop=1.1)
        r._record_fix(nav, source="nav_pvt")
        gga = GnssFix(timestamp=1.2, fix_type=5, lat=41.0, lon=-76.0, alt=99.0, rtk_age=2.5)
        r._record_fix(gga, source="gga")
        latest = r.latest_fix()
        assert latest.lat == 40.0 and latest.alt == 5.0  # GGA did not replace the NAV-PVT fix
        assert latest.rtk_age == 2.5  # but its RTCM age was merged

    def test_gga_is_source_without_ubx(self):
        from rover.gnss import GnssReceiver

        r = GnssReceiver.__new__(GnssReceiver)
        r._lock = __import__("threading").Lock()
        r._latest = None
        r._ubx_active = False
        gga = GnssFix(timestamp=1.2, fix_type=5, lat=41.0, lon=-76.0, alt=99.0, rtk_age=2.5)
        r._record_fix(gga, source="gga")
        assert r.latest_fix().lat == 41.0

    def test_no_subscribe_api(self):
        from rover.gnss import GnssReceiver

        assert not hasattr(GnssReceiver, "subscribe")
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_gnss.py -q -k Stage4
```

Expected: alt 10.5 (not -23.5); `pdop` TypeError; `_record_fix` has no `source` kwarg; `subscribe` exists.

- [ ] **Step 3: Implement**

`GnssFix`: add `pdop: float = 99.9  # NAV-PVT position DOP; 99.9 when the source is GGA` and change the `alt` comment to `# Ellipsoidal (WGS84) metres — both sources normalise to this`.

`parse_gga`: after `alt`, parse `geoid = float(fields[11]) if len(fields) > 11 and fields[11] else 0.0` (try/except → 0.0) and set `alt = alt + geoid` with a comment `# GGA field 9 is MSL; field 11 is geoid separation (ellipsoid - geoid) → ellipsoidal`.

`_fix_from_nav_pvt`: `alt=float(getattr(msg, "height", 0)) / 1000.0` (ellipsoidal), `hdop=99.9`, `pdop=float(getattr(msg, "pDOP", 99.9))`; use `FIX_2D/FIX_3D/FIX_RTK_FLOAT/FIX_RTK_FIX/FIX_NONE`; comment on fixType 1/5 → `FIX_NONE`.

`GnssReceiver`: add `self._ubx_active = False` in `__init__`; set it True in `_read_loop` when the `UBXReader` is created; `_record_fix(self, fix, source: str)`:

```python
    def _record_fix(self, fix: GnssFix, source: str) -> None:
        with self._lock:
            if source == "gga" and self._ubx_active:
                # NAV-PVT is the position source; GGA only contributes the RTCM age.
                if self._latest is not None and fix.rtk_age >= 0:
                    self._latest = dataclasses.replace(self._latest, rtk_age=fix.rtk_age)
                return
            if source == "nav_pvt" and self._latest is not None and self._latest.rtk_age >= 0 and fix.rtk_age < 0:
                fix = dataclasses.replace(fix, rtk_age=self._latest.rtk_age)
            self._latest = fix
```

Call sites: `self._record_fix(fix, source="gga")` in both readers, `self._record_fix(_fix_from_nav_pvt(parsed), source="nav_pvt")`. Remove `subscribe`, `_callbacks`, and the `Callable` import if unused; remove the lock from `_read_nmea_only`'s read (keep it on `write_rtcm` and `close()`); cap `line_buf`: after appending, `if len(line_buf) > _LINE_BUF_MAX: line_buf = line_buf[-_LINE_BUF_MAX:]`. Import `from rover.lora_protocol import FIX_2D, FIX_3D, FIX_DGPS, FIX_NONE, FIX_RTK_FIX, FIX_RTK_FLOAT` and rewrite `_GGA_QUALITY_TO_FIX` values with them. Module docstring: drop `.subscribe`, add the source-selection rule and "heights are ellipsoidal", changelog `0.11.0`.

`src/rover/main.py` gnss record: add `"pdop": gnss_fix.pdop`.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_gnss.py tests/test_main.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/gnss.py src/rover/main.py tests/test_gnss.py && python -m ruff check src/rover/gnss.py src/rover/main.py tests/test_gnss.py
git add src/rover/gnss.py src/rover/main.py tests/test_gnss.py
git commit -m "fix(gnss): NAV-PVT sole source with GGA rtk_age merge; pdop field; ellipsoidal heights from both paths; write-only serial lock; FIX_* constants (T1-019, T1-020, T1-049, S2-R1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Telemetry — per-channel cadence, schema v2, no placeholders, dead code

**Files:**
- Modify: `src/rover/telemetry.py`
- Modify: `src/rover/config.py` (`base_station_integration.status_schema_version` optional; `[lora].telemetry_interval_sec` consumed)
- Modify: `src/rover/main.py` (`_scan_loop` calls `telemetry.publish(status)` every iteration; router decides; `publish_interval or 1.0` removed; `sensors_disabled`/`logger_degraded` fed into status)
- Test: `tests/test_telemetry.py`, `tests/test_main.py`

**Interfaces:**
- Produces: `STATUS_SCHEMA_VERSION = 2`; `RoverStatus` gains `sensors_disabled: list[str] = field(default_factory=list)` and `logger_degraded: bool = False`; `battery_mv`, `lora_link_rssi`, `lora_link_snr` become `int | None = None`; `build_payload(status, schema_version, device)` is a module function using `dataclasses.asdict` that OMITS keys whose value is None; `TelemetryRouter.publish(status)` calls each publisher only when `now - last[p] >= interval[p]` where `interval` = `base_station_integration.publish_interval_sec` for status_json and http, `lora.telemetry_interval_sec` for lora; `LoRaPublisher.publish_link` removed, STATUS payload encodes `battery_mv or 0` and the sentinel for missing link metrics; `status_schema_version` config key: `0` means "use the constant" (default 0).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_telemetry.py`)

```python
from rover.telemetry import STATUS_SCHEMA_VERSION, RoverStatus, TelemetryRouter, build_payload


class TestSchemaV2:
    def test_payload_omits_unmeasured_fields(self):
        s = RoverStatus()
        p = build_payload(s, schema_version=STATUS_SCHEMA_VERSION, device="r")
        assert "battery_mv" not in p and "lora_link_rssi" not in p and "lora_link_snr" not in p
        assert p["schema_version"] == 2
        assert p["sensors_disabled"] == [] and p["logger_degraded"] is False

    def test_payload_includes_measured_battery(self):
        s = RoverStatus(battery_mv=11800)
        assert build_payload(s, schema_version=2, device="r")["battery_mv"] == 11800

    def test_schema_version_zero_means_constant(self, tmp_toml, tmp_path):
        p = tmp_toml(
            f"""
            [base_station_integration]
            enabled = true
            status_json_path = "{(tmp_path / 's.json').as_posix()}"
            status_schema_version = 0
            """
        )
        from rover.config import load_config
        from rover.telemetry import StatusJsonPublisher

        pub = StatusJsonPublisher(load_config(p))
        assert pub.build_payload(RoverStatus())["schema_version"] == STATUS_SCHEMA_VERSION


class TestRouterCadence:
    def test_router_per_channel_cadence(self, tmp_toml, tmp_path, monkeypatch):
        p = tmp_toml(
            f"""
            [base_station_integration]
            enabled = true
            status_json_path = "{(tmp_path / 's.json').as_posix()}"
            publish_interval_sec = 0.2
            [lora]
            enabled = true
            role = "status_tx_only"
            telemetry_interval_sec = 1.0
            [telemetry]
            http_enabled = false
            """
        )
        from rover.config import load_config

        router = TelemetryRouter(load_config(p))
        calls = {pub.name: 0 for pub in router.publishers}

        for pub in router.publishers:
            monkeypatch.setattr(pub, "publish", lambda s, _n=pub.name: calls.__setitem__(_n, calls[_n] + 1))
        clock = [0.0]
        monkeypatch.setattr("rover.telemetry.time.monotonic", lambda: clock[0])
        s = RoverStatus()
        for i in range(21):  # 0.0 .. 2.0 s in 0.1 s steps
            clock[0] = i * 0.1
            router.publish(s)
        assert calls["status_json"] == 11  # every 0.2 s incl. t=0
        assert calls["lora"] == 3  # t=0, 1.0, 2.0
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_telemetry.py -q -k "SchemaV2 or Cadence"
```

Expected: `build_payload` ImportError etc.

- [ ] **Step 3: Implement**

`telemetry.py`: `STATUS_SCHEMA_VERSION = 2` with a v2 line in the docstring history (`sensors_disabled`, `logger_degraded` added; `battery_mv`/`lora_link_*` omitted when unmeasured). `RoverStatus` field changes as above. Module function:

```python
def build_payload(status: RoverStatus, schema_version: int, device: str) -> dict:
    """On-wire status.json shape: every RoverStatus field, minus unmeasured (None) ones."""
    payload = {k: v for k, v in dataclasses.asdict(status).items() if v is not None}
    payload["schema_version"] = schema_version
    payload["device"] = device or status.device
    return payload
```

`StatusJsonPublisher.__init__`: `self._schema_version = self._bsi.status_schema_version or STATUS_SCHEMA_VERSION` stays correct once the config default is 0; `build_payload` method delegates to the function. `LocalHttpPublisher`: drop `_bsi` and the borrowed publisher; store `schema_version`/`device` and call the function. `LoRaPublisher.publish`: `battery_mv=status.battery_mv or 0`; remove `publish_link` and the `role == "disabled"` checks. `TelemetryRouter`: drop `_config`; keep `(publisher, interval)` pairs and `_last: dict[str, float]`; `publish()` iterates and calls when due (`time.monotonic()`); add `interval_for(name)` for tests. Remove the `role == "disabled"` guard duplicates.

`config.py`: `base_station_integration.status_schema_version` default `0`, validation `>= 0` (0 = use the code constant); update the `_DEFAULTS` comment.

`main.py`: remove `publish_interval`/`last_publish` bookkeeping; call `telemetry.publish(status)` once per iteration after updating status; feed `status.sensors_disabled = [g.name for g in (lidar_gate, imu_gate, camera_gate) if g.tripped]` and `status.logger_degraded = session_logger.degraded`; drop the `or 1.0`.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_telemetry.py tests/test_main.py tests/test_config.py -q
```

Expected: all pass (update `test_payload_shape_matches_contract` for v2: the three None fields absent, two new fields present).

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/telemetry.py src/rover/config.py src/rover/main.py tests && python -m ruff check src/rover/telemetry.py src/rover/config.py src/rover/main.py tests
git add src/rover/telemetry.py src/rover/config.py src/rover/main.py tests/test_telemetry.py tests/test_main.py tests/test_config.py
git commit -m "feat(telemetry): schema v2 — per-channel cadence, unmeasured fields omitted, sensors_disabled/logger_degraded on the wire; dead code removed (T1-025, T1-026, T1-030, T1-047, S2-R2)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Config — remove dead sections, pin LoRa radio params to firmware

**Files:**
- Modify: `src/rover/config.py`, `config/default.toml`, `config/telemetry-only.toml`
- Modify: `src/rover/telemetry.py` (nothing reads `[power]` after Task 4; confirm)
- Test: `tests/test_config.py`, new `tests/test_firmware_parity.py`

**Interfaces:**
- Produces: `GnssConfig` loses `rtcm_profile`, `survey_in_duration_sec`, `survey_in_accuracy_m`; `PowerConfig` and `[power]` removed entirely (`RoverConfig.power` gone); `ImuConfig` loses `fusion_output_hz`; `LoggingConfig` loses `format`; `_DEFAULTS`, `_validate`, `_build_config` and the TOMLs updated; unknown keys in a user TOML still raise (existing behaviour) so an old `[power]` section fails loudly with the existing "unknown section" message; `[lora]` `spreading_factor`/`bandwidth_khz`/`coding_rate`/`sync_word` keep validation and gain the comment `# documentation only — must match firmware/esp32-rover/platformio.ini build_flags`; a parity test parses `platformio.ini` `build_flags` (`-D LORA_SF=7` etc.) and asserts equality with `default.toml`.

- [ ] **Step 1: Write the failing tests**

`tests/test_firmware_parity.py`:

```python
"""[lora] radio parameters are documentation: they must equal the firmware build flags (T1-041)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _build_flags() -> dict[str, str]:
    ini = (REPO / "firmware/esp32-rover/platformio.ini").read_text(encoding="utf-8")
    return dict(re.findall(r"-D\s*([A-Z_]+)=([^\s\\]+)", ini))


def test_lora_params_match_firmware_build_flags():
    toml = tomllib.loads((REPO / "config/default.toml").read_text(encoding="utf-8"))["lora"]
    flags = _build_flags()
    assert int(flags["LORA_SF"]) == toml["spreading_factor"]
    assert int(flags["LORA_BW_KHZ"]) == toml["bandwidth_khz"]
    assert flags["LORA_CR"].strip('"') == toml["coding_rate"]
    assert int(flags["LORA_SYNC_WORD"], 0) == toml["sync_word"]
```

Read `platformio.ini` first and adapt the flag names to what it actually defines (the file has ~58 lines); if the firmware does not define a flag for one of the four, add it to `platformio.ini` (the value the firmware hard-codes) so the parity is real — that is a documentation-only firmware change, allowed here.

Append to `tests/test_config.py`:

```python
class TestDeadConfigRemoved:
    def test_power_section_is_unknown(self, tmp_toml):
        p = tmp_toml("[power]\nmonitor_battery = true\n")
        with pytest.raises(ValueError, match="power"):
            load_config(p)

    def test_gnss_survey_keys_are_unknown(self, tmp_toml):
        p = tmp_toml("[gnss]\nsurvey_in_duration_sec = 300\n")
        with pytest.raises(ValueError, match="survey_in_duration_sec"):
            load_config(p)

    def test_logging_format_key_is_unknown(self, tmp_toml):
        p = tmp_toml('[logging]\nformat = "csv"\n')
        with pytest.raises(ValueError, match="format"):
            load_config(p)

    def test_no_power_attribute(self):
        assert not hasattr(load_config(), "power")
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_config.py -q -k DeadConfig
python -m pytest tests/test_firmware_parity.py -q
```

Expected: the dead-config tests FAIL (keys accepted); parity test may pass or fail depending on the ini — record it.

- [ ] **Step 3: Implement**

Remove the fields from the dataclasses, `_DEFAULTS`, `_validate` (whole `# -- power --` block; the three gnss keys; `imu.fusion_output_hz`; `logging.format` type/in checks) and `_build_config`; remove `PowerConfig` and `RoverConfig.power`. In both TOMLs delete the `[power]` section, the three gnss keys, `fusion_output_hz`, and `logging.format`; annotate the four `[lora]` radio keys. Grep `src/` and `tests/` for `fusion_output_hz`, `monitor_battery`, `battery_adc_channel`, `low_battery_mv`, `critical_battery_mv`, `rtcm_profile`, `survey_in_`, `format = "jsonl"`, `.power` and fix every fixture/test that used them (test_main's `_write_all_disabled_config` carries `[power]` keys — remove them). `SPECIFICATIONS.md` is stage 5.

- [ ] **Step 4: Run**

```bash
python -m pytest -q 2>&1 | tail -1
```

Expected: green; count reported.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src tests && python -m ruff check src tests
git add src/rover/config.py config tests firmware/esp32-rover/platformio.ini
git commit -m "chore(config): remove [power], gnss survey keys, imu.fusion_output_hz, logging.format; pin [lora] radio params to firmware build flags (T1-041)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Main loop — stepper-failure gate, constants, guards

**Files:**
- Modify: `src/rover/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `SCAN_*` imported from `rover.lora_protocol` (local re-declarations deleted); the stepper failure branch uses a `_SensorGate("stepper")`: on failure it records, sets `SCAN_ERROR`, waits 0.5 s but does NOT `continue` past the telemetry publish (publish happens; LiDAR/IMU/camera reads are skipped that iteration via a `stepped_ok` flag); after 5 consecutive failures the stepper is skipped (session continues in continuous mode with `mast_angle_deg` frozen) and `sensor_disabled` is logged; on a later success `scan_state` returns to `SCAN_SCANNING`; the module-level camera import guard is removed in favour of `camera.py`'s own; the `# noqa: F821` and nested `SIGTERM` try are flattened; `GnssReceiver(config)` unchanged (Task 3 kept its signature; T1-046's last item is closed by documenting why in a one-line comment).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_main.py`)

```python
class _BrokenStepper(_FakeStepper):
    fails = 0

    def step(self, steps: int) -> None:
        type(self).fails += 1
        raise RuntimeError("stall")


def test_stepper_failures_are_gated_and_still_publish(tmp_path: Path, monkeypatch) -> None:
    """A failing stepper must not spam warnings forever nor skip telemetry (S2-R3)."""
    import json

    _BrokenStepper.fails = 0
    published: list = []
    monkeypatch.setattr(main_mod, "StepperMotor", _BrokenStepper)
    monkeypatch.setattr(main_mod, "LidarScanner", _StaticLidar)
    monkeypatch.setattr(main_mod, "ImuDriver", _FakeImu)

    real_router = main_mod.TelemetryRouter

    class _SpyRouter(real_router):
        def publish(self, status):
            published.append(status.scan_state)
            return super().publish(status)

    monkeypatch.setattr(main_mod, "TelemetryRouter", _SpyRouter)
    assert main_mod.run(config_path=_stage3_config(tmp_path), duration_sec=4.0) == 0
    assert _BrokenStepper.fails == 5, "gate must stop retrying after 5 failures"
    assert any(s == main_mod.SCAN_ERROR for s in published), "SCAN_ERROR must be published"
    session = next((tmp_path / "data").glob("s3_*"))
    events = [json.loads(l)["event"] for l in (session / "scan.jsonl").read_text().splitlines() if '"event"' in l]
    assert "sensor_disabled" in events


def test_scan_constants_come_from_lora_protocol():
    from rover import lora_protocol

    assert main_mod.SCAN_ERROR is lora_protocol.SCAN_ERROR
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_main.py -q -k "stepper_failures or scan_constants"
```

Expected: `fails` ≫ 5 (retries every 0.5 s for 4 s = ~8); SCAN_ERROR never published because `continue` skipped it.

- [ ] **Step 3: Implement**

Replace the local `SCAN_IDLE/SCANNING/PAUSED/ERROR = ...` block with `from rover.lora_protocol import SCAN_ERROR, SCAN_IDLE, SCAN_PAUSED, SCAN_SCANNING`. Add `stepper_gate = _SensorGate("stepper")` beside the others. Step block:

```python
        stepped = False
        step_ok = True
        if sensors.stepper is not None and sensors.stepper.available and steps_per_increment > 0 and not stepper_gate.tripped:
            if sensors.imu is not None and sensors.imu.available:
                sensors.imu.enable_magnetometer(False)
            try:
                sensors.stepper.step(steps_per_increment)
                stepped = True
                stepper_gate.record_success()
                status.scan_state = SCAN_SCANNING
            except Exception as e:
                step_ok = False
                if stepper_gate.record_failure(e):
                    _note_gate_trip(session_logger, stepper_gate, e)
                status.scan_state = SCAN_ERROR
        if step_ok:
            stop_event.wait(settle_sec)
        else:
            stop_event.wait(0.5)
        if sensors.imu is not None and sensors.imu.available:
            sensors.imu.enable_magnetometer(config.imu.use_magnetometer)
```

and guard the LiDAR/IMU/camera reads with `if step_ok:` (a failed step yields no slice), leaving the GNSS block and the telemetry publish to run every iteration. Delete the module-level `try: from rover.camera import Camera ... except` in favour of a plain import (camera.py already guards picamera2) and drop `_CAMERA_IMPORT_OK`/`_CAMERA_IMPORT_ERROR` (update `_init_sensors` and the stage 2 test that monkeypatched `_CAMERA_IMPORT_OK`). Flatten the signal block:

```python
    if owns_signals:
        try:
            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)
        except ValueError:
            logger.debug("Signal handlers not installed (not main thread)")
```

Remove the `# noqa: F821`. Add a one-line comment above `GnssReceiver(config)`: `# takes the whole config: it needs [gnss] and [ntrip].client_location`.

- [ ] **Step 4: Run**

```bash
python -m pytest tests/test_main.py -q && python -m pytest -q 2>&1 | tail -1
```

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/main.py tests/test_main.py && python -m ruff check src/rover/main.py tests/test_main.py
git add src/rover/main.py tests/test_main.py
git commit -m "fix(main): gate stepper failures and keep publishing; SCAN_* from lora_protocol; drop duplicate camera guard and signal clutter (T1-046, S2-R3)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: LoRa protocol CRC via stdlib + golden vector

**Files:**
- Modify: `src/rover/lora_protocol.py` (`crc16_ccitt` body; `Tuple` typing)
- Test: `tests/test_lora_protocol.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_lora_protocol.py`)

```python
GOLDEN_STATUS_FRAME_HEX = None  # filled in step 3 from the CURRENT implementation


def test_golden_status_frame_is_stable():
    """Checked-in hex of a STATUS frame; the firmware quotes the same bytes (T1-042)."""
    from rover.lora_protocol import TYPE_STATUS, encode_frame, encode_status_payload

    payload = encode_status_payload(fix_type=5, sat_count=18, hdop=0.8, battery_mv=11800, scan_state=1)
    frame = encode_frame(TYPE_STATUS, 0x1234, payload)
    assert frame.hex() == GOLDEN_STATUS_FRAME_HEX


def test_crc_matches_binascii():
    import binascii

    from rover.lora_protocol import crc16_ccitt

    for data in (b"", b"\x00", b"123456789", bytes(range(256))):
        assert crc16_ccitt(data) == binascii.crc_hqx(data, 0xFFFF)
```

- [ ] **Step 2: Capture the golden vector from the CURRENT (bit-by-bit) implementation before changing it**

```bash
python -c "from rover.lora_protocol import *; p=encode_status_payload(fix_type=5,sat_count=18,hdop=0.8,battery_mv=11800,scan_state=1); print(encode_frame(TYPE_STATUS,0x1234,p).hex())"
```

Paste the printed hex into `GOLDEN_STATUS_FRAME_HEX`. Run the two tests: golden passes, binascii test passes too (they should already agree; if not, STOP and report — the firmware and this module would disagree on CRC).

- [ ] **Step 3: Implement**

```python
def crc16_ccitt(data: bytes) -> int:
    """CRC16-CCITT, poly 0x1021, init 0xFFFF, no final XOR — exactly ``binascii.crc_hqx``."""
    return binascii.crc_hqx(data, 0xFFFF)
```

Add `import binascii`; replace `Tuple[...]` with `tuple[...]` and drop the `typing` import if unused. Add a comment above the golden constant in the test naming `firmware/esp32-rover/src/main.cpp` as the place to quote it (firmware half deferred).

- [ ] **Step 4: Run** `python -m pytest tests/test_lora_protocol.py -q` — all pass.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/lora_protocol.py tests/test_lora_protocol.py && python -m ruff check src/rover/lora_protocol.py tests/test_lora_protocol.py
git add src/rover/lora_protocol.py tests/test_lora_protocol.py
git commit -m "refactor(lora): CRC16 via binascii.crc_hqx; golden STATUS frame vector (T1-042)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: GPIO backend detection + installer remedy (T1-033)

**Files:**
- Modify: `src/rover/stepper.py` (import block)
- Modify: `deploy/install.sh` (Validation section)
- Test: `tests/test_stepper.py`, `tests/test_deploy.py`

**Interfaces:**
- Produces: `stepper.GPIO_BACKEND: str` ∈ {"rpi-lgpio", "RPi.GPIO", "none"} decided at import from `GPIO.__file__` (contains `rpi_lgpio` or `lgpio`) with a WARNING when the legacy backend is detected (`DEC-029`); `StepperMotor.start()` refuses (`available = False`, one WARNING) when `GPIO_BACKEND == "RPi.GPIO"`; `install.sh` Validation warns when `python3 -c "import RPi.GPIO as g; print(g.__file__)"` does not mention lgpio and prints the apt remedy.

- [ ] **Step 1: Write the failing tests**

`tests/test_stepper.py`:

```python
def test_backend_detection_names_lgpio(monkeypatch):
    import importlib

    from rover import stepper

    fake = type("G", (), {"__file__": "/usr/lib/python3/dist-packages/RPi/_GPIO.cpython-311-aarch64-linux-gnu.so"})()
    assert stepper._detect_backend(fake) == "RPi.GPIO"
    fake2 = type("G", (), {"__file__": "/usr/lib/python3/dist-packages/rpi_lgpio/RPi/GPIO/__init__.py"})()
    assert stepper._detect_backend(fake2) == "rpi-lgpio"
    assert stepper._detect_backend(None) == "none"


def test_start_refuses_legacy_backend(stepper_config, monkeypatch):
    from rover import stepper

    monkeypatch.setattr(stepper, "_GPIO_AVAILABLE", True)
    monkeypatch.setattr(stepper, "GPIO", __import__("unittest.mock").mock.MagicMock())
    monkeypatch.setattr(stepper, "GPIO_BACKEND", "RPi.GPIO")
    m = stepper.StepperMotor(stepper_config)
    m.start()
    assert m.available is False
```

`tests/test_deploy.py`: `assert "python3-rpi-lgpio" in sh` and `assert "import RPi.GPIO" in sh` in a new `test_install_sh_checks_gpio_backend`.

- [ ] **Step 2: Run to confirm failure** — AttributeError on `_detect_backend`; installer test FAIL.

- [ ] **Step 3: Implement**

```python
def _detect_backend(gpio_module) -> str:
    """'rpi-lgpio' (DEC-029 drop-in), 'RPi.GPIO' (legacy, broken on Bookworm), or 'none'."""
    if gpio_module is None:
        return "none"
    path = (getattr(gpio_module, "__file__", "") or "").replace("\\", "/").lower()
    return "rpi-lgpio" if "lgpio" in path else "RPi.GPIO"


try:
    import RPi.GPIO as GPIO  # rpi-lgpio is a drop-in replacement

    _GPIO_AVAILABLE = True
except ImportError:
    GPIO = None  # type: ignore[assignment]
    _GPIO_AVAILABLE = False

GPIO_BACKEND = _detect_backend(GPIO)
if GPIO_BACKEND == "RPi.GPIO":
    logger.warning(
        "Legacy RPi.GPIO backend detected (%s) — broken on Bookworm (DEC-029); "
        "install rpi-lgpio: sudo apt remove python3-rpi.gpio && sudo apt install python3-rpi-lgpio",
        getattr(GPIO, "__file__", "?"),
    )
```

In `start()`, after the `_GPIO_AVAILABLE` check: `if GPIO_BACKEND == "RPi.GPIO": logger.warning("Refusing to drive the stepper on the legacy RPi.GPIO backend (DEC-029)"); return`.

`install.sh` Validation section, after the udev placeholder check:

```bash
gpio_file=$(python3 -c "import RPi.GPIO as g; print(g.__file__)" 2>/dev/null || true)
if [[ -n "$gpio_file" && "$gpio_file" != *lgpio* ]]; then
    echo "  WARNING: legacy RPi.GPIO backend at $gpio_file (DEC-029) — the stepper will refuse to run."
    echo "           Fix: sudo apt remove python3-rpi.gpio && sudo apt install python3-rpi-lgpio"
fi
```

Update `deploy/SMOKE_CHECKLIST.md` item 10 to say the installer now warns and the driver refuses.

- [ ] **Step 4: Run** `python -m pytest tests/test_stepper.py tests/test_deploy.py -q && bash -n deploy/install.sh` and the deploy line-ending check (0 CRLF).

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/stepper.py tests/test_stepper.py tests/test_deploy.py && python -m ruff check src/rover/stepper.py tests/test_stepper.py tests/test_deploy.py
git add src/rover/stepper.py deploy/install.sh deploy/SMOKE_CHECKLIST.md tests/test_stepper.py tests/test_deploy.py
git commit -m "fix(stepper): detect the GPIO backend and refuse legacy RPi.GPIO; installer warns with the apt remedy (T1-033)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Logger — single GNSS stream, generic rotation, counted losses, unblocked producer

**Files:**
- Modify: `src/rover/logger.py`
- Modify: `scripts/georef.py` (loader: gnss segments are now the only GNSS source; drop the "only if scan had none" condition)
- Test: `tests/test_logger.py`, `tests/test_georef.py`

**Interfaces:**
- Produces: GNSS records go ONLY to `gnss*.jsonl` (T1-053); `_Stream` helper (`path`, `file`, `index`, `stem`) with one `_rotate(stream)`; `lost_records: int` counts records drained but not written when a flush fails; the drop-oldest path uses a dedicated `_count_lock` and never waits on `_lock` (S2-R4); `write()` stays non-blocking; metadata gains `lost_records`; `georef.load_session` reads GNSS from `gnss*.jsonl` unconditionally and merges any GNSS records found in scan segments (legacy).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_logger.py`)

```python
def test_gnss_records_only_in_gnss_file(cfg):
    config, path = cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    lg.write({"type": "gnss", "lat": 1.0})
    lg.write({"type": "lidar", "angle": []})
    lg.stop()
    scan = (lg.session_dir / "scan.jsonl").read_text()
    gnss = (lg.session_dir / "gnss.jsonl").read_text()
    assert '"gnss"' not in scan and '"gnss"' in gnss


def test_lost_records_counted_on_flush_failure(fast_flush_cfg, monkeypatch):
    config, path = fast_flush_cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    monkeypatch.setattr(lg, "_write_record", lambda r: (_ for _ in ()).throw(OSError(28, "full")))
    for i in range(3):
        lg.write({"type": "event", "i": i})
    deadline = time.monotonic() + 3
    while lg.lost_records < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    lg.stop()
    assert lg.lost_records == 3


def test_write_does_not_block_behind_flush(cfg):
    """Drop-oldest must not wait on the flush lock (S2-R4)."""
    config, path = cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    from rover import logger as logger_mod

    for i in range(logger_mod._QUEUE_MAX):
        lg.write({"type": "event", "i": i})
    lg._lock.acquire()  # simulate a flush stalled on disk
    try:
        t0 = time.monotonic()
        lg.write({"type": "event", "i": -1})
        assert time.monotonic() - t0 < 0.5
        assert lg.dropped_records == 1
    finally:
        lg._lock.release()
        lg.stop()
```

And in `tests/test_georef.py`, adjust the rotated-files test: GNSS from `gnss*.jsonl` is read even when scan segments contain GNSS records (both merged, sorted by timestamp).

- [ ] **Step 2: Run to confirm failure** — first test FAIL (mirrored), `lost_records` AttributeError, third test blocks (>0.5 s).

- [ ] **Step 3: Implement**

```python
@dataclass
class _Stream:
    stem: str
    path: Path | None = None
    file: TextIO | None = None
    index: int = 0
```

Replace `_scan_*`/`_gnss_*` attributes with `self._scan = _Stream("scan")`, `self._gnss = _Stream("gnss")`; `_open_stream(stream)`, `_rotate(stream)` (open-new-first fail-safe from stage 2), `_maybe_rotate` loops over both; `_write_record` routes `type == "gnss"` to `_gnss` ONLY, everything else to `_scan`. Counters: `self._count_lock = threading.Lock()`; `_note_dropped()` and the new `_note_lost(n)` use it; `write()`'s Full path uses `_count_lock` only (never `_lock`). In `_flush`, wrap the per-record write loop so that on the first exception the remaining drained records are counted as lost (`_note_lost(len(records) - written)`) before re-raising to `_periodic_flush`. Metadata adds `"lost_records"`. `stop()` fsyncs both streams via the `_Stream` list.

`georef.load_session`: `gnss_files = _segment_files(session_dir, "gnss")`; `gnss.extend(r for r in _iter_jsonl(gnss_files) if r.get("type") == "gnss")`; sort by timestamp; de-duplicate by timestamp (legacy sessions with mirrored records).

- [ ] **Step 4: Run** `python -m pytest tests/test_logger.py tests/test_georef.py tests/test_main.py -q` then the full suite.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src/rover/logger.py scripts/georef.py tests && python -m ruff check src/rover/logger.py scripts/georef.py tests
git add src/rover/logger.py scripts/georef.py tests/test_logger.py tests/test_georef.py
git commit -m "fix(logger): GNSS only in gnss.jsonl; generic stream rotation; lost_records; non-blocking drop-oldest (T1-053, S2-R4)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Test hygiene — hardware scripts import the drivers, fixtures consolidated

**Files:**
- Modify: `tests/hardware/test_lidar.py` (delete the duplicated CRC table, `crc8`, `parse_packet`; import from `rover.lidar`; default `--port /dev/rover-lidar`)
- Modify: `tests/hardware/test_imu.py` (drive `ImuDriver` via `load_config()`; delete the re-implemented register I/O)
- Modify: `tests/hardware/test_stepper.py`, `test_camera.py` (defaults from `load_config()` / udev names)
- Modify: `tests/conftest.py` (delete `tmp_dir`, `sample_toml`, `default_toml_path`; add the shared `tmp_toml`)
- Modify: `tests/test_config.py`, `tests/test_config_session.py`, `tests/test_telemetry.py` (remove their local `tmp_toml`)
- Modify: `tests/test_main.py` (`_write_all_disabled_config` keeps only keys that differ from defaults)
- Modify: `src/rover/lidar.py` (CRC table reflowed 8 per row with `# fmt: skip` — the stage 1 deferred minor)

- [ ] **Step 1: Write the guard test** (append to `tests/test_deploy.py` or a new `tests/test_hygiene.py`)

```python
def test_hardware_scripts_import_drivers_not_copies():
    src = (REPO / "tests/hardware/test_lidar.py").read_text(encoding="utf-8")
    assert "_CRC_TABLE" not in src and "from rover.lidar import" in src
    src = (REPO / "tests/hardware/test_imu.py").read_text(encoding="utf-8")
    assert "from rover.imu import ImuDriver" in src and "_REG_" not in src


def test_single_tmp_toml_fixture():
    import re

    hits = [p for p in (REPO / "tests").glob("test_*.py") if re.search(r"^def tmp_toml", p.read_text(), re.M)]
    assert hits == [], hits
```

- [ ] **Step 2: Run** — both FAIL.

- [ ] **Step 3: Implement** the edits listed under Files. The hardware scripts keep their CLI shape (`argparse`, `--duration`, console summary) but call the real drivers; they still cannot run off-Pi, so the change is verified by `python -m py_compile tests/hardware/*.py` and by reading. `_write_all_disabled_config` becomes the minimal set (`[lidar] enabled=false` … `[logging] output_dir`, `session_prefix`) — confirm by running `test_main.py`.

- [ ] **Step 4: Run** the full suite and `python -m py_compile tests/hardware/*.py`.

- [ ] **Step 5: Commit**

```bash
python -m ruff format src tests && python -m ruff check src tests
git add -A tests src/rover/lidar.py
git commit -m "test: hardware scripts use the real drivers; one tmp_toml fixture; minimal disabled config; CRC table reflowed (T2-006, T2-007, T2-008)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Merge stage 4

- [ ] **Step 1: Full verification** — `python -m pytest -q`, `ruff check`, `ruff format --check`, `bash -n deploy/install.sh`, the CRLF one-liner on `deploy/*` and `config/*`. Report the measured count.
- [ ] **Step 2: Merge** `git checkout main && git merge --no-ff fix/stage4-comms-config -F <message file>`; delete the branch. Message subject: `Merge stage 4: comms and config cleanup (T1-004, T1-019, T1-020, T1-022, T1-023, T1-025, T1-026, T1-030, T1-033, T1-041, T1-042, T1-046, T1-047, T1-049, T1-053, T2-005..008, S2-R1..R4)`.
- [ ] **Step 3: Mark the rows** `done (<sha>)` in the audit report; T1-033 stays `done-unverified` pointing at checklist item 10 (the code guard is in; the hardware check remains). Mark S2-R1..R4 closed in `docs/CROSS_REPO_BACKLOG.md` with the SHA. Commit on `main`.
