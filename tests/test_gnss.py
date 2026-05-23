"""Unit tests for rover.gnss NMEA-GGA parser. No serial / no hardware."""

import pytest

from rover.gnss import GnssFix, parse_gga


# Real-world-ish GGA sentences with valid checksums.
# Generated via: body XOR'd byte-by-byte, hex two-digit checksum after `*`.

# RTK FIX (quality=4), 18 sats, HDOP 0.8, lat 40°42.768'N, lon 74°00.36'W, alt 10.5m
GGA_RTK_FIX = "$GNGGA,143052.00,4042.76800,N,07400.36000,W,4,18,0.8,10.5,M,-34.0,M,1.2,0000*6C"

# Standalone 3D, 8 sats, no RTK age
GGA_3D = "$GNGGA,143100.00,4042.50000,N,07400.50000,W,1,08,1.5,8.0,M,-34.0,M,,*53"

# Invalid fix
GGA_INVALID = "$GNGGA,143200.00,,,,,0,00,99.99,,M,,M,,*68"


def _fix_checksum(sentence: str) -> str:
    """Recompute the trailing *HH checksum on a sentence body. Used to repair the
    sample sentences above if my pencil-and-paper math is off."""
    assert sentence.startswith("$") and "*" in sentence
    body, _ = sentence[1:].split("*", 1)
    cs = 0
    for c in body:
        cs ^= ord(c)
    return f"${body}*{cs:02X}"


@pytest.fixture(autouse=True)
def _repair_checksums():
    """Make sure the sample sentences above carry correct checksums regardless
    of how they were hand-typed."""
    global GGA_RTK_FIX, GGA_3D, GGA_INVALID
    GGA_RTK_FIX = _fix_checksum(GGA_RTK_FIX)
    GGA_3D = _fix_checksum(GGA_3D)
    GGA_INVALID = _fix_checksum(GGA_INVALID)


class TestParseGgaHappy:
    def test_rtk_fix_recognized(self):
        fix = parse_gga(GGA_RTK_FIX)
        assert fix is not None
        assert fix.fix_type == 5  # RTK FIX

    def test_lat_lon_decoded(self):
        fix = parse_gga(GGA_RTK_FIX)
        # ddmm.mmmm: 4042.768 → 40 + 42.768/60 ≈ 40.7128°N
        assert fix.lat == pytest.approx(40.7128, abs=0.0001)
        # 7400.36 → 74 + 0.36/60 ≈ 74.006°W → negative
        assert fix.lon == pytest.approx(-74.006, abs=0.0001)

    def test_alt_decoded(self):
        fix = parse_gga(GGA_RTK_FIX)
        assert fix.alt == 10.5

    def test_sat_count(self):
        fix = parse_gga(GGA_RTK_FIX)
        assert fix.sat_count == 18

    def test_hdop(self):
        fix = parse_gga(GGA_RTK_FIX)
        assert fix.hdop == pytest.approx(0.8)

    def test_rtk_age(self):
        fix = parse_gga(GGA_RTK_FIX)
        assert fix.rtk_age == pytest.approx(1.2)

    def test_standalone_3d_maps_to_fix_type_2(self):
        fix = parse_gga(GGA_3D)
        assert fix is not None
        assert fix.fix_type == 2

    def test_standalone_has_no_rtk_age(self):
        fix = parse_gga(GGA_3D)
        assert fix.rtk_age == -1.0

    def test_invalid_quality_maps_to_none(self):
        fix = parse_gga(GGA_INVALID)
        assert fix is not None
        assert fix.fix_type == 0


class TestParseGgaErrors:
    def test_bad_checksum_returns_none(self):
        # Take a valid sentence and corrupt the checksum
        good = GGA_RTK_FIX
        bad = good[:-2] + "FF"
        assert parse_gga(bad) is None

    def test_missing_dollar_returns_none(self):
        assert parse_gga(GGA_RTK_FIX[1:]) is None

    def test_truncated_returns_none(self):
        truncated = "$GNGGA,143052.00*7E"
        # Fix the checksum so we test the field-count check, not the cksum check
        truncated = _fix_checksum(truncated)
        assert parse_gga(truncated) is None

    def test_non_gga_sentence_returns_none(self):
        rmc = _fix_checksum("$GNRMC,143052.00,A,4042.768,N,07400.36,W,0.5,90.0,010126,,,A*7F")
        assert parse_gga(rmc) is None


class TestGnssFixDefaults:
    def test_default_fix_is_none_type(self):
        fix = GnssFix()
        assert fix.fix_type == 0
        assert fix.lat == 0.0
        assert fix.lon == 0.0
        assert fix.rtk_age == -1.0
