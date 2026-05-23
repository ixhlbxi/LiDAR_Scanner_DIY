"""LoRa frame v2 — shared envelope with arm-drone-lidar-workflow.

Implements the LoRa frame v2 spec described in docs/BASE_STATION_INTEGRATION.md §4
and CLAUDE.md Appendix C. The same envelope is encoded/decoded on the Base-Station
Heltec V3 (DISPLAY + RTCM_CHUNK Tx) and the rover ESP32 (STATUS + LINK Tx,
RTCM_CHUNK Rx) firmware.

Frame layout (no Sync bytes — LoRa PHY preamble + sync_word handles synchronization):

    [Version=2 :1][Type :1][Seq LE :2][Len LE :2][Payload :N][CRC16-CCITT LE :2]

CRC16-CCITT — poly 0x1021, init 0xFFFF, no final XOR. Scope: Version through last
Payload byte (i.e. everything except the trailing CRC).

Public API:
    FRAME_VERSION
    TYPE_STATUS, TYPE_LINK, TYPE_RTCM_CHUNK, TYPE_DISPLAY, TYPE_DEBUG_TEXT
    encode_frame(packet_type, sequence, payload) -> bytes
    decode_frame(frame_bytes) -> (packet_type, sequence, payload)  | raises FrameError
    encode_status_payload(...) -> bytes
    encode_link_payload(...) -> bytes
    crc16_ccitt(data) -> int

Dependencies: stdlib only.

Changelog:
    0.10.0  2026-05-23  Initial v2 implementation (Phase B of overhaul).
"""

from __future__ import annotations

import struct
from typing import Tuple

FRAME_VERSION: int = 0x02

# Packet types (see BASE_STATION_INTEGRATION.md §4)
TYPE_STATUS: int = 0x01      # rover → handhelds/base
TYPE_LINK: int = 0x02        # rover → handhelds/base
TYPE_RTCM_CHUNK: int = 0x10  # base → rover
TYPE_DISPLAY: int = 0x20     # base → handhelds (rover ignores)
TYPE_DEBUG_TEXT: int = 0x7F  # any direction

_HEADER_FMT = "<BBHH"  # version, type, seq LE, len LE
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 6 bytes
_CRC_SIZE = 2
_FRAME_MIN_SIZE = _HEADER_SIZE + _CRC_SIZE


class FrameError(ValueError):
    """Raised when a frame fails to parse, validate, or CRC-check."""


def crc16_ccitt(data: bytes) -> int:
    """CRC16-CCITT, poly 0x1021, init 0xFFFF, no final XOR.

    Matches the polynomial used by every Heltec/T-Deck firmware in
    arm-drone-lidar-workflow. Implemented bit-by-bit — perf is not relevant
    at the byte volumes we push.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def encode_frame(packet_type: int, sequence: int, payload: bytes) -> bytes:
    """Encode a LoRa frame v2.

    Args:
        packet_type: One of TYPE_* constants (validation is not strict — unknown
            type IDs are encodable, since the spec defines receiver behavior
            (drop unknown), not sender restrictions).
        sequence: uint16 sequence number (wraps at 0x10000).
        payload: Raw payload bytes.

    Returns:
        Framed bytes ready to hand to the radio layer.

    Raises:
        ValueError: If sequence or payload size are out of range.
    """
    if not (0 <= packet_type <= 0xFF):
        raise ValueError(f"packet_type out of range: {packet_type}")
    if not (0 <= sequence <= 0xFFFF):
        raise ValueError(f"sequence out of range: {sequence}")
    if len(payload) > 0xFFFF:
        raise ValueError(f"payload too large: {len(payload)} bytes")

    header = struct.pack(_HEADER_FMT, FRAME_VERSION, packet_type,
                         sequence & 0xFFFF, len(payload))
    body = header + payload
    crc = crc16_ccitt(body)
    return body + struct.pack("<H", crc)


def decode_frame(frame: bytes) -> Tuple[int, int, bytes]:
    """Decode and CRC-verify a LoRa frame v2.

    Returns:
        (packet_type, sequence, payload)

    Raises:
        FrameError: On any structural or CRC failure. Receivers MUST treat
            FrameError as "drop this frame, increment err_count."
    """
    if len(frame) < _FRAME_MIN_SIZE:
        raise FrameError(f"frame too short: {len(frame)} < {_FRAME_MIN_SIZE}")

    version, packet_type, seq, length = struct.unpack(
        _HEADER_FMT, frame[:_HEADER_SIZE]
    )
    if version != FRAME_VERSION:
        # Receivers MUST drop unknown versions (see Heltec/T-Deck firmware).
        raise FrameError(
            f"unsupported version: 0x{version:02x} (expected 0x{FRAME_VERSION:02x})"
        )

    expected_total = _HEADER_SIZE + length + _CRC_SIZE
    if len(frame) != expected_total:
        raise FrameError(
            f"length mismatch: frame={len(frame)}, expected={expected_total} "
            f"(payload={length})"
        )

    payload = frame[_HEADER_SIZE:_HEADER_SIZE + length]
    received_crc = struct.unpack("<H", frame[-_CRC_SIZE:])[0]
    computed_crc = crc16_ccitt(frame[:-_CRC_SIZE])
    if received_crc != computed_crc:
        raise FrameError(
            f"CRC mismatch: got 0x{received_crc:04x}, computed 0x{computed_crc:04x}"
        )

    return packet_type, seq, payload


# ---------------------------------------------------------------------------
# STATUS payload (Type 0x01) — 10 bytes
# ---------------------------------------------------------------------------

_STATUS_FMT = "<BBHHB3s"  # fix_type, sat_count, hdop×100 LE, battery_mv LE, scan_state, reserved
STATUS_PAYLOAD_SIZE = struct.calcsize(_STATUS_FMT)  # 10

# Fix-type enum values (also used in metadata.json and status.json)
FIX_NONE = 0
FIX_2D = 1
FIX_3D = 2
FIX_DGPS = 3
FIX_RTK_FLOAT = 4
FIX_RTK_FIX = 5

# Scan-state enum values
SCAN_IDLE = 0
SCAN_SCANNING = 1
SCAN_PAUSED = 2
SCAN_ERROR = 3


def encode_status_payload(
    fix_type: int,
    sat_count: int,
    hdop: float,
    battery_mv: int,
    scan_state: int,
) -> bytes:
    """Encode a STATUS payload (10 bytes).

    Args:
        fix_type: 0..5 (see FIX_* constants).
        sat_count: 0..255.
        hdop: Floating-point HDOP; encoded as round(hdop*100) clamped to uint16.
        battery_mv: 0..65535.
        scan_state: 0..3 (see SCAN_* constants).
    """
    if not (0 <= fix_type <= 0xFF):
        raise ValueError(f"fix_type out of range: {fix_type}")
    if not (0 <= sat_count <= 0xFF):
        raise ValueError(f"sat_count out of range: {sat_count}")
    if not (0 <= scan_state <= 0xFF):
        raise ValueError(f"scan_state out of range: {scan_state}")

    hdop_x100 = max(0, min(0xFFFF, int(round(hdop * 100))))
    battery = max(0, min(0xFFFF, int(battery_mv)))

    return struct.pack(_STATUS_FMT, fix_type, sat_count, hdop_x100,
                       battery, scan_state, b"\x00\x00\x00")


def decode_status_payload(payload: bytes) -> dict:
    """Decode a STATUS payload back to a dict (for tests + monitor firmware parity)."""
    if len(payload) != STATUS_PAYLOAD_SIZE:
        raise FrameError(
            f"STATUS payload wrong size: {len(payload)} != {STATUS_PAYLOAD_SIZE}"
        )
    fix_type, sat_count, hdop_x100, battery_mv, scan_state, _reserved = struct.unpack(
        _STATUS_FMT, payload
    )
    return {
        "fix_type": fix_type,
        "sat_count": sat_count,
        "hdop": hdop_x100 / 100.0,
        "battery_mv": battery_mv,
        "scan_state": scan_state,
    }


# ---------------------------------------------------------------------------
# LINK payload (Type 0x02) — 14 bytes
# ---------------------------------------------------------------------------

_LINK_FMT = "<BBIIH2s"  # rssi+128, snr+128, rx_count LE, tx_count LE, err_count LE, reserved
LINK_PAYLOAD_SIZE = struct.calcsize(_LINK_FMT)  # 14


def encode_link_payload(
    rssi_dbm: int,
    snr_db: int,
    rx_count: int,
    tx_count: int,
    err_count: int,
) -> bytes:
    """Encode a LINK payload (14 bytes).

    RSSI and SNR use the +128 offset encoding (so int8 range -128..127 maps to
    uint8 0..255 on the wire). Matches the Heltec/T-Deck firmware convention.
    """
    rssi_enc = max(0, min(0xFF, rssi_dbm + 128))
    snr_enc = max(0, min(0xFF, snr_db + 128))
    return struct.pack(
        _LINK_FMT,
        rssi_enc,
        snr_enc,
        rx_count & 0xFFFFFFFF,
        tx_count & 0xFFFFFFFF,
        err_count & 0xFFFF,
        b"\x00\x00",
    )


def decode_link_payload(payload: bytes) -> dict:
    """Decode a LINK payload back to a dict."""
    if len(payload) != LINK_PAYLOAD_SIZE:
        raise FrameError(
            f"LINK payload wrong size: {len(payload)} != {LINK_PAYLOAD_SIZE}"
        )
    rssi_enc, snr_enc, rx_count, tx_count, err_count, _reserved = struct.unpack(
        _LINK_FMT, payload
    )
    return {
        "rssi_dbm": rssi_enc - 128,
        "snr_db": snr_enc - 128,
        "rx_count": rx_count,
        "tx_count": tx_count,
        "err_count": err_count,
    }
