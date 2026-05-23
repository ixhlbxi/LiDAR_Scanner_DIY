"""Unit tests for rover.ntrip helpers — no real caster, no hardware."""

import base64

import pytest

from rover.ntrip import (
    NTRIP_VERSION,
    USER_AGENT,
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
