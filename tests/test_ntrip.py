"""Unit tests for rover.ntrip helpers — no real caster, no hardware."""

import base64
import socket
import threading
import time
from dataclasses import replace

import pytest

from rover.config import load_config
from rover.gnss import GnssFix
from rover.ntrip import (
    NTRIP_VERSION,
    USER_AGENT,
    NtripClient,
    NtripError,
    build_gga,
    build_request,
    parse_response_status,
)


class TestBuildRequest:
    def test_request_starts_with_get_line(self):
        req = build_request("rtk-base.local", "ARM_BASE", "rover", "pw")
        assert req.startswith(b"GET /ARM_BASE HTTP/1.1\r\n")

    def test_host_header_present(self):
        req = build_request("rtk-base.local", "ARM_BASE", "rover", "pw")
        assert b"Host: rtk-base.local\r\n" in req

    def test_ntrip_version_header(self):
        req = build_request("h", "M", "u", "p")
        assert f"Ntrip-Version: {NTRIP_VERSION}".encode("ascii") in req

    def test_user_agent_header(self):
        req = build_request("h", "M", "u", "p")
        assert f"User-Agent: {USER_AGENT}".encode("ascii") in req

    def test_user_agent_override(self):
        req = build_request("h", "M", "u", "p", user_agent="Custom/1.0")
        assert b"User-Agent: Custom/1.0\r\n" in req

    def test_basic_auth_encodes_correctly(self):
        req = build_request("h", "M", "alice", "wonderland")
        expected_b64 = base64.b64encode(b"alice:wonderland").decode("ascii")
        assert f"Authorization: Basic {expected_b64}".encode("ascii") in req

    def test_request_terminates_with_double_crlf(self):
        req = build_request("h", "M", "u", "p")
        assert req.endswith(b"\r\n\r\n")

    def test_blank_mountpoint_raises(self):
        with pytest.raises(NtripError, match="mountpoint"):
            build_request("h", "", "u", "p")

    def test_blank_password_still_builds(self):
        # Some casters allow blank passwords; the caster decides whether to reject.
        req = build_request("h", "M", "anon", "")
        expected_b64 = base64.b64encode(b"anon:").decode("ascii")
        assert f"Authorization: Basic {expected_b64}".encode("ascii") in req


class TestParseResponseStatus:
    def test_http_200(self):
        code, reason = parse_response_status(b"HTTP/1.1 200 OK\r\nFoo: bar\r\n\r\n")
        assert code == 200
        assert reason == "OK"

    def test_http_401(self):
        code, reason = parse_response_status(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
        assert code == 401
        assert reason == "Unauthorized"

    def test_http_404(self):
        code, _ = parse_response_status(b"HTTP/1.0 404 Not Found\r\n\r\n")
        assert code == 404

    def test_icy_200_legacy(self):
        """Legacy NTRIPv1 caster reply is `ICY 200 OK`."""
        code, reason = parse_response_status(b"ICY 200 OK\r\n\r\n")
        assert code == 200
        assert reason == "OK"

    def test_icy_non_200_rejected(self):
        with pytest.raises(NtripError):
            parse_response_status(b"ICY 401 BAD\r\n\r\n")

    def test_malformed_status_line(self):
        with pytest.raises(NtripError):
            parse_response_status(b"GIBBERISH\r\n\r\n")

    def test_unknown_protocol(self):
        with pytest.raises(NtripError, match="unknown protocol"):
            parse_response_status(b"FTP/1.0 200 OK\r\n\r\n")

    def test_non_numeric_status(self):
        with pytest.raises(NtripError, match="non-numeric"):
            parse_response_status(b"HTTP/1.1 OK\r\n\r\n")

    def test_no_reason_phrase_allowed(self):
        """RFC 2616 permits empty reason phrase."""
        code, reason = parse_response_status(b"HTTP/1.1 200 \r\n\r\n")
        assert code == 200
        assert reason == ""


# ---------------------------------------------------------------------------
# NtripClient — live-socket tests against a one-shot fake caster
# ---------------------------------------------------------------------------


def _cfg(tmp_path, profile="personal", extra=""):
    p = tmp_path / "c.toml"
    p.write_text(
        f"""
[session]
profile = "{profile}"
project_code = "{"TEST" if profile == "arm_group" else ""}"
target_crs_epsg = {6346 if profile == "arm_group" else 0}

[base_station_integration]
enabled = {"true" if profile == "arm_group" else "false"}
status_json_path = "{(tmp_path / "status.json").as_posix()}"

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
    """One-shot TCP caster on 127.0.0.1: answers with `response` then optionally
    streams `body`. While `hold_open` remains after sending, keeps reading from
    the connection (short-timeout poll loop) so a client that sends anything
    back — e.g. periodic GGA sentences — can be observed in `received_after`."""

    def __init__(self, response: bytes, body: bytes = b"", hold_open: float = 0.0):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.response, self.body, self.hold_open = response, body, hold_open
        self.received = b""
        self.received_after = b""
        self.t = threading.Thread(target=self._serve, daemon=True)
        self.t.start()

    def _serve(self):
        conn, _ = self.srv.accept()
        conn.settimeout(2.0)
        try:
            self.received = conn.recv(4096)
            conn.sendall(self.response + self.body)
            if self.hold_open:
                deadline = time.monotonic() + self.hold_open
                conn.settimeout(0.1)
                while time.monotonic() < deadline:
                    try:
                        chunk = conn.recv(4096)
                    except TimeoutError:
                        continue  # no data this tick — keep polling
                    except OSError:
                        break  # peer gone
                    if not chunk:
                        break
                    self.received_after += chunk
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

    def test_404_in_arm_group_sets_fatal_and_stops(self, tmp_path):
        """404 (mountpoint doesn't exist) never succeeds on retry — one of the
        three NtripFatalError cases, same as 401 (final review I3)."""
        caster = _FakeCaster(b"HTTP/1.1 404 Not Found\r\n\r\n")
        c = _client(_cfg(tmp_path, "arm_group"), caster)
        c.start()
        deadline = time.monotonic() + 3
        while c.fatal_error is None and time.monotonic() < deadline:
            time.sleep(0.02)
        try:
            assert c.fatal_error is not None and "404" in c.fatal_error
            assert not c._thread.is_alive()
        finally:
            c.stop()

    def test_503_in_arm_group_is_not_fatal(self, tmp_path):
        """A 503 is a transient caster rejection (not one of 401/404/chunked)
        — even in arm_group it must go through the normal retry path, not
        latch fatal_error (final review I3)."""
        caster = _FakeCaster(b"HTTP/1.1 503 Service Unavailable\r\n\r\n")
        c = _client(_cfg(tmp_path, "arm_group"), caster)
        c.start()
        time.sleep(0.5)
        try:
            assert c.fatal_error is None
            assert c.stats.error_count >= 1
        finally:
            c.stop()

    def test_handshake_closed_in_arm_group_is_not_fatal(self, tmp_path):
        """A caster that accepts then closes before sending a status line is
        a transient handshake failure, not one of the three fatal cases —
        even in arm_group it must retry rather than latch (final review I3)."""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def _serve():
            conn, _ = srv.accept()
            conn.recv(4096)  # consume the request, then close gracefully —
            conn.close()  # a graceful FIN gives recv() a clean EOF (b""),
            srv.close()  # not a reset, so this hits the NtripError path

        threading.Thread(target=_serve, daemon=True).start()

        cfg = _cfg(tmp_path, "arm_group")
        cfg = replace(cfg, ntrip=replace(cfg.ntrip, caster_port=port))
        c = NtripClient(cfg, rtcm_sink=lambda b: None)
        c.start()
        time.sleep(0.5)
        try:
            assert c.fatal_error is None
            assert c.stats.error_count >= 1
        finally:
            c.stop()


class TestConnectStopRace:
    def test_stop_set_before_connect_closes_socket_without_blocking(self, tmp_path):
        """A stop() landing between create_connection() and the header read
        must not leave the thread blocked in a blocking recv() that nothing
        will ever interrupt again (M3). Deterministic reproduction: the
        guard added right after `self._sock = sock` is published checks
        `self._stop_event` — that check behaves identically whether the
        event was set microseconds ago (the real race) or well before
        _one_connection() was even called, so setting it up front exercises
        the same code path without needing to win a real timing race.
        """
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        accepted: list[socket.socket] = []

        def _serve():
            try:
                conn, _ = srv.accept()
                accepted.append(conn)
            except OSError:
                pass

        threading.Thread(target=_serve, daemon=True).start()

        cfg = _cfg(tmp_path)
        cfg = replace(cfg, ntrip=replace(cfg.ntrip, caster_port=port))
        c = NtripClient(cfg, rtcm_sink=lambda b: None)
        c._stop_event.set()

        t0 = time.monotonic()
        c._one_connection()  # must return promptly, not block in a header read
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, "must not block in a header read after a raced stop()"
        assert c._sock is None

        srv.close()
        for conn in accepted:
            try:
                conn.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# GGA upload, header-tail forwarding, chunked-encoding refusal
# ---------------------------------------------------------------------------


def _nmea_ok(sentence: bytes) -> bool:
    s = sentence.decode().strip()
    body, _, cs = s[1:].partition("*")
    x = 0
    for ch in body:
        x ^= ord(ch)
    return f"{x:02X}" == cs[:2]


class TestGga:
    def test_build_gga_valid_checksum_and_fields(self):
        fix = GnssFix(
            timestamp=0.0, fix_type=5, lat=40.7128, lon=-74.006, alt=10.5, hdop=0.8, sat_count=18
        )
        s = build_gga(fix, when=time.gmtime(0))
        assert s.startswith(b"$GPGGA,000000.00,4042.7680,N,07400.3600,W,4,18,0.8,10.5,M,")
        assert s.endswith(b"\r\n") and _nmea_ok(s)

    def test_build_gga_float_quality(self):
        fix = GnssFix(fix_type=4, lat=1.0, lon=1.0, sat_count=9)
        assert b",5,09," in build_gga(fix, when=time.gmtime(0))

    @pytest.mark.parametrize(
        ("fix_type", "expected_quality"),
        [(0, 0), (1, 1), (2, 1), (3, 1), (4, 5), (5, 4)],
    )
    def test_build_gga_quality_mapping(self, fix_type, expected_quality):
        """0=NONE 1=2D 2=3D 3=DGPS -> quality 1 (or 0 for NONE); RTK_FLOAT=4
        -> quality 5; RTK_FIX=5 -> quality 4 (the wire-vs-internal swap)."""
        fix = GnssFix(fix_type=fix_type, lat=1.0, lon=1.0, sat_count=5)
        s = build_gga(fix, when=time.gmtime(0))
        assert f",{expected_quality},05,".encode() in s

    def test_gga_sent_on_interval(self, tmp_path):
        caster = _FakeCaster(b"ICY 200 OK\r\n\r\n", body=b"\xd3\x00\x01", hold_open=1.5)
        fix = GnssFix(fix_type=5, lat=40.0, lon=-75.0, alt=1.0, sat_count=10, hdop=1.0)
        c = _client(
            _cfg(tmp_path, extra="gga_send_interval_sec = 0.2"), caster, gga_source=lambda: fix
        )
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
        caster = _FakeCaster(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n", body=b"5\r\nhello\r\n"
        )
        got: list[bytes] = []
        c = _client(_cfg(tmp_path, "arm_group"), caster, sink=got.append)
        c.start()
        deadline = time.monotonic() + 3
        while c.fatal_error is None and time.monotonic() < deadline:
            time.sleep(0.02)
        c.stop()
        assert c.fatal_error and "chunked" in c.fatal_error
        assert got == []

    def test_chunked_encoding_odd_case_and_spacing_refused(self, tmp_path):
        """A header parse must catch this, not a lowercase-substring search:
        double space after the colon, mixed case, and a multi-valued line
        (`gzip, chunked`) rather than a bare `chunked`."""
        caster = _FakeCaster(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding:  Gzip, Chunked\r\n\r\n", body=b"5\r\nhello\r\n"
        )
        got: list[bytes] = []
        c = _client(_cfg(tmp_path, "arm_group"), caster, sink=got.append)
        c.start()
        deadline = time.monotonic() + 3
        while c.fatal_error is None and time.monotonic() < deadline:
            time.sleep(0.02)
        c.stop()
        assert c.fatal_error and "chunked" in c.fatal_error
        assert got == []
