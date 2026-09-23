"""Unit tests for rover.ntrip helpers — no real caster, no hardware."""

import base64
import socket
import threading
import time
from dataclasses import replace

import pytest

from rover.config import load_config
from rover.ntrip import (
    NTRIP_VERSION,
    USER_AGENT,
    NtripClient,
    NtripError,
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
    streams `body`."""

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
