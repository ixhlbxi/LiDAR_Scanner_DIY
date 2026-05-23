"""Unit tests for the LoRa frame v2 protocol (shared with arm-drone-lidar-workflow).

See docs/BASE_STATION_INTEGRATION.md §4 for the wire format.
"""

import struct

import pytest

from rover.lora_protocol import (
    FRAME_VERSION,
    LINK_PAYLOAD_SIZE,
    STATUS_PAYLOAD_SIZE,
    TYPE_LINK,
    TYPE_RTCM_CHUNK,
    TYPE_STATUS,
    FrameError,
    crc16_ccitt,
    decode_frame,
    decode_link_payload,
    decode_status_payload,
    encode_frame,
    encode_link_payload,
    encode_status_payload,
)


# ---------------------------------------------------------------------------
# CRC16-CCITT
# ---------------------------------------------------------------------------


class TestCrc:
    def test_empty_input_returns_init(self):
        assert crc16_ccitt(b"") == 0xFFFF

    def test_known_vector_123456789(self):
        # Canonical CRC16-CCITT-FALSE test vector for "123456789"
        # (poly 0x1021, init 0xFFFF, no final XOR) → 0x29B1
        assert crc16_ccitt(b"123456789") == 0x29B1

    def test_deterministic(self):
        data = b"\x01\x02\x03\xff\xfe\xfd"
        assert crc16_ccitt(data) == crc16_ccitt(data)


# ---------------------------------------------------------------------------
# Frame encode / decode
# ---------------------------------------------------------------------------


class TestFrameRoundtrip:
    def test_status_payload_roundtrip(self):
        payload = encode_status_payload(
            fix_type=5, sat_count=18, hdop=0.85, battery_mv=11800, scan_state=1
        )
        frame = encode_frame(TYPE_STATUS, 42, payload)
        ptype, seq, decoded = decode_frame(frame)
        assert ptype == TYPE_STATUS
        assert seq == 42
        assert decoded == payload

    def test_empty_payload_roundtrip(self):
        frame = encode_frame(TYPE_RTCM_CHUNK, 0, b"")
        ptype, seq, decoded = decode_frame(frame)
        assert ptype == TYPE_RTCM_CHUNK
        assert seq == 0
        assert decoded == b""

    def test_frame_has_expected_overhead(self):
        # Frame: [version 1][type 1][seq 2][len 2][payload N][crc 2] = N + 8
        frame = encode_frame(TYPE_STATUS, 1, b"\xAA" * 10)
        assert len(frame) == 10 + 8

    def test_frame_starts_with_version_byte(self):
        frame = encode_frame(TYPE_STATUS, 1, b"hello")
        assert frame[0] == FRAME_VERSION

    def test_sequence_wraps(self):
        # Encoder accepts up to 0xFFFF; values outside that should raise.
        frame = encode_frame(TYPE_STATUS, 0xFFFF, b"x")
        _, seq, _ = decode_frame(frame)
        assert seq == 0xFFFF


class TestFrameErrors:
    def test_unsupported_version_rejected(self):
        good = encode_frame(TYPE_STATUS, 1, b"\xAA\xBB")
        # Flip the version byte to 0x01 (the old self-contained spec)
        bad = bytes([0x01]) + good[1:]
        # Re-CRC so the failure is specifically version, not CRC
        # crc16 covers everything except the trailing 2 bytes
        body = bad[:-2]
        new_crc = crc16_ccitt(body)
        bad = body + struct.pack("<H", new_crc)
        with pytest.raises(FrameError, match="unsupported version"):
            decode_frame(bad)

    def test_short_frame_rejected(self):
        with pytest.raises(FrameError, match="too short"):
            decode_frame(b"\x02\x01\x00\x00")

    def test_length_mismatch_rejected(self):
        good = encode_frame(TYPE_STATUS, 1, b"\xAA\xBB")
        # Truncate the last payload byte (and its CRC), so declared length > actual
        bad = good[:-3]
        with pytest.raises(FrameError):
            decode_frame(bad)

    def test_crc_mismatch_rejected(self):
        good = encode_frame(TYPE_STATUS, 1, b"\xAA\xBB")
        # Flip a bit in the payload — CRC will no longer match
        mutable = bytearray(good)
        mutable[6] ^= 0x80  # payload starts at offset 6
        with pytest.raises(FrameError, match="CRC mismatch"):
            decode_frame(bytes(mutable))

    def test_encoder_rejects_huge_payload(self):
        # Payload length is uint16 — anything > 0xFFFF must error
        with pytest.raises(ValueError):
            encode_frame(TYPE_STATUS, 0, b"\x00" * (0x10000))

    def test_encoder_rejects_huge_sequence(self):
        with pytest.raises(ValueError):
            encode_frame(TYPE_STATUS, 0x10000, b"")


# ---------------------------------------------------------------------------
# STATUS payload
# ---------------------------------------------------------------------------


class TestStatusPayload:
    def test_status_size_is_10(self):
        payload = encode_status_payload(
            fix_type=5, sat_count=18, hdop=0.85, battery_mv=11800, scan_state=1
        )
        assert len(payload) == STATUS_PAYLOAD_SIZE == 10

    def test_status_roundtrip(self):
        payload = encode_status_payload(
            fix_type=5, sat_count=18, hdop=0.85, battery_mv=11800, scan_state=1
        )
        decoded = decode_status_payload(payload)
        assert decoded["fix_type"] == 5
        assert decoded["sat_count"] == 18
        assert decoded["hdop"] == pytest.approx(0.85, abs=0.01)
        assert decoded["battery_mv"] == 11800
        assert decoded["scan_state"] == 1

    def test_hdop_clamps_to_uint16_range(self):
        # hdop * 100 must fit in uint16 (max 655.35)
        payload = encode_status_payload(
            fix_type=5, sat_count=0, hdop=1000.0, battery_mv=0, scan_state=0
        )
        decoded = decode_status_payload(payload)
        assert decoded["hdop"] == pytest.approx(655.35, abs=0.01)

    def test_battery_clamps_to_uint16(self):
        payload = encode_status_payload(
            fix_type=0, sat_count=0, hdop=0, battery_mv=70000, scan_state=0
        )
        decoded = decode_status_payload(payload)
        assert decoded["battery_mv"] == 0xFFFF


# ---------------------------------------------------------------------------
# LINK payload
# ---------------------------------------------------------------------------


class TestLinkPayload:
    def test_link_size_is_14(self):
        payload = encode_link_payload(-78, 9, 100, 50, 2)
        assert len(payload) == LINK_PAYLOAD_SIZE == 14

    def test_link_roundtrip(self):
        payload = encode_link_payload(
            rssi_dbm=-78, snr_db=9, rx_count=1000, tx_count=500, err_count=2
        )
        decoded = decode_link_payload(payload)
        assert decoded["rssi_dbm"] == -78
        assert decoded["snr_db"] == 9
        assert decoded["rx_count"] == 1000
        assert decoded["tx_count"] == 500
        assert decoded["err_count"] == 2

    def test_link_negative_rssi_encodes_with_offset(self):
        # -128 dBm should encode to 0x00 (after +128 offset)
        payload = encode_link_payload(-128, -128, 0, 0, 0)
        assert payload[0] == 0
        assert payload[1] == 0

    def test_link_decode_via_decode_frame(self):
        """End-to-end: encode LINK, frame it, decode, parse."""
        payload = encode_link_payload(-60, 12, 1, 2, 0)
        frame = encode_frame(TYPE_LINK, 100, payload)
        ptype, seq, decoded_payload = decode_frame(frame)
        assert ptype == TYPE_LINK
        assert seq == 100
        parsed = decode_link_payload(decoded_payload)
        assert parsed["rssi_dbm"] == -60
        assert parsed["snr_db"] == 12
