"""Unit tests for rover.gnss NMEA-GGA parser. No serial / no hardware."""

import threading
import time

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
        # alt 10.5 m MSL + geoid separation -34.0 m → -23.5 m ellipsoidal (Stage 4)
        fix = parse_gga(GGA_RTK_FIX)
        assert fix.alt == pytest.approx(-23.5)

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


def test_fix_from_nav_pvt_uses_pyubx2_scaled_attributes() -> None:
    """pyubx2 already scales lat/lon to degrees and pDOP to 0.01 units and
    expands the flags byte into carrSoln; dividing again zeroes the fix (T1-006).

    Stage 4 (S2-R1/T1-019/T1-020): alt now comes from `height` (ellipsoidal),
    not `hMSL` (orthometric), and pDOP lands in `pdop`, not `hdop` — NAV-PVT
    carries no HDOP so `hdop` is always 99.9 for this source.
    """
    import pyubx2

    from rover.gnss import _fix_from_nav_pvt

    msg = pyubx2.UBXMessage(
        "NAV",
        "NAV-PVT",
        pyubx2.GET,
        fixType=3,
        carrSoln=2,
        numSV=18,
        lat=40.712800,
        lon=-74.006000,
        height=12345,
        hMSL=10500,
        pDOP=1.2,
    )
    # Sanity: the library really does expose scaled values. If this constructor
    # rejects `carrSoln=` as a kwarg on the installed pyubx2, build the same
    # message with `flags=0b10000000` instead (carrSoln lives in bits 6-7 of
    # flags) and keep the assertions below unchanged.
    assert abs(msg.lat - 40.7128) < 1e-6
    assert msg.carrSoln == 2

    # Round-trip through a real parse rather than handing _fix_from_nav_pvt the
    # hand-built UBXMessage directly — this exercises the actual attribute
    # population path pyubx2 uses when parsing bytes off the wire.
    parsed = pyubx2.UBXReader.parse(msg.serialize())

    fix = _fix_from_nav_pvt(parsed)
    assert abs(fix.lat - 40.7128) < 1e-6
    assert abs(fix.lon - (-74.006)) < 1e-6
    assert abs(fix.alt - 12.345) < 1e-6  # ellipsoidal height (mm), not hMSL
    assert fix.fix_type == 5  # RTK FIX
    assert abs(fix.pdop - 1.2) < 1e-6
    assert fix.hdop == 99.9  # NAV-PVT has no HDOP
    assert fix.sat_count == 18


class TestStage4Gnss:
    def test_gga_alt_is_ellipsoidal(self):
        # alt 10.5 m MSL + geoid separation -34.0 m → -23.5 m ellipsoidal
        fix = parse_gga(
            _fix_checksum(
                "$GNGGA,143052.00,4042.76800,N,07400.36000,W,4,18,0.8,10.5,M,-34.0,M,1.2,0000*00"
            )
        )
        assert fix.alt == pytest.approx(-23.5)

    def test_nav_pvt_uses_ellipsoidal_height_and_pdop(self):
        import pyubx2

        from rover.gnss import _fix_from_nav_pvt

        msg = pyubx2.UBXMessage(
            "NAV",
            "NAV-PVT",
            pyubx2.GET,
            fixType=3,
            carrSoln=2,
            numSV=18,
            lat=40.7128,
            lon=-74.006,
            height=12345,
            hMSL=10500,
            pDOP=1.2,
        )
        fix = _fix_from_nav_pvt(pyubx2.UBXReader.parse(msg.serialize()))
        assert fix.alt == pytest.approx(12.345)
        assert fix.pdop == pytest.approx(1.2) and fix.hdop == 99.9

    def test_nav_pvt_is_sole_source_when_ubx_present(self):
        from rover.gnss import GnssReceiver

        r = GnssReceiver.__new__(GnssReceiver)
        r._lock = __import__("threading").Lock()
        r._latest = None
        r._ubx_active = True
        r._last_navpvt_mono = time.monotonic()  # fresh — not stale
        r._rtk_age_mono = 0.0
        nav = GnssFix(timestamp=1.0, fix_type=5, lat=40.0, lon=-75.0, alt=5.0, pdop=1.1)
        r._record_fix(nav, source="nav_pvt")
        gga = GnssFix(timestamp=1.2, fix_type=5, lat=41.0, lon=-76.0, alt=99.0, rtk_age=2.5)
        r._record_fix(gga, source="gga")
        latest = r.latest_fix()
        assert latest.lat == 40.0 and latest.alt == 5.0  # GGA did not replace the NAV-PVT fix
        assert latest.rtk_age == 2.5  # but its RTCM age was merged

    def test_nav_pvt_active_merges_gga_hdop(self):
        """NAV-PVT carries no HDOP of its own (always 99.9 — see
        _fix_from_nav_pvt); while NAV-PVT is the active source, a GGA
        sentence must still merge its HDOP onto the published fix, the same
        way it already merges rtk_age (final review I1)."""
        from rover.gnss import GnssReceiver

        r = GnssReceiver.__new__(GnssReceiver)
        r._lock = __import__("threading").Lock()
        r._latest = None
        r._ubx_active = True
        r._last_navpvt_mono = time.monotonic()  # fresh — not stale
        r._rtk_age_mono = 0.0
        nav = GnssFix(timestamp=1.0, fix_type=5, lat=40.0, lon=-75.0, alt=5.0, pdop=1.1)
        r._record_fix(nav, source="nav_pvt")
        assert r.latest_fix().hdop == 99.9  # NAV-PVT's own placeholder, unmerged so far

        gga = GnssFix(timestamp=1.2, fix_type=5, lat=41.0, lon=-76.0, alt=99.0, hdop=0.8)
        r._record_fix(gga, source="gga")
        latest = r.latest_fix()
        assert latest.lat == 40.0  # still the NAV-PVT position
        assert latest.hdop == 0.8  # but HDOP came from GGA

    def test_gga_is_source_without_ubx(self):
        from rover.gnss import GnssReceiver

        r = GnssReceiver.__new__(GnssReceiver)
        r._lock = __import__("threading").Lock()
        r._latest = None
        r._ubx_active = False
        r._last_navpvt_mono = 0.0
        r._rtk_age_mono = 0.0
        gga = GnssFix(timestamp=1.2, fix_type=5, lat=41.0, lon=-76.0, alt=99.0, rtk_age=2.5)
        r._record_fix(gga, source="gga")
        assert r.latest_fix().lat == 41.0

    def test_no_subscribe_api(self):
        from rover.gnss import GnssReceiver

        assert not hasattr(GnssReceiver, "subscribe")

    def test_gga_is_source_until_first_nav_pvt(self):
        """A fresh receiver has never seen NAV-PVT — GGA is the source until it
        actually arrives, not merely because pyubx2 is importable (fix round 1,
        Finding 1)."""
        from rover.gnss import GnssReceiver

        r = GnssReceiver.__new__(GnssReceiver)
        r._lock = threading.Lock()
        r._latest = None
        r._ubx_active = False
        r._last_navpvt_mono = 0.0
        r._rtk_age_mono = 0.0

        gga1 = GnssFix(timestamp=1.0, fix_type=2, lat=10.0, lon=-20.0, alt=1.0)
        r._record_fix(gga1, source="gga")
        assert r.latest_fix().lat == 10.0  # GGA is the source before any NAV-PVT is seen

        nav = GnssFix(timestamp=2.0, fix_type=5, lat=40.0, lon=-75.0, alt=5.0, pdop=1.1)
        r._ubx_active = True
        r._last_navpvt_mono = time.monotonic()
        r._record_fix(nav, source="nav_pvt")
        assert r.latest_fix().lat == 40.0  # first NAV-PVT takes over as the source

        gga2 = GnssFix(timestamp=2.2, fix_type=5, lat=41.0, lon=-76.0, alt=99.0, rtk_age=2.5)
        r._record_fix(gga2, source="gga")
        latest = r.latest_fix()
        assert latest.lat == 40.0  # still the NAV-PVT position
        assert latest.rtk_age == 2.5  # GGA only merged its age

    def test_gga_resumes_when_nav_pvt_goes_stale(self):
        """If NAV-PVT stops arriving, GGA must resume as the source rather than
        being dropped forever (fix round 1, Finding 1)."""
        from rover.gnss import GnssReceiver

        r = GnssReceiver.__new__(GnssReceiver)
        r._lock = threading.Lock()
        r._latest = GnssFix(timestamp=1.0, fix_type=5, lat=40.0, lon=-75.0, alt=5.0)
        r._ubx_active = True
        r._last_navpvt_mono = time.monotonic() - 10  # stale: > _NAVPVT_STALE_SEC (5.0)
        r._rtk_age_mono = 0.0

        gga = GnssFix(timestamp=2.0, fix_type=2, lat=41.0, lon=-76.0, alt=99.0)
        r._record_fix(gga, source="gga")
        latest = r.latest_fix()
        assert latest.lat == 41.0  # GGA resumed as the source
        assert r._ubx_active is False

    def test_carried_rtk_age_expires(self):
        """A carried-forward rtk_age must not freeze indefinitely (fix round 1,
        Finding 2)."""
        from rover.gnss import GnssReceiver

        r = GnssReceiver.__new__(GnssReceiver)
        r._lock = threading.Lock()
        r._ubx_active = True
        r._last_navpvt_mono = time.monotonic()
        r._rtk_age_mono = 0.0
        r._latest = GnssFix(timestamp=1.0, fix_type=5, lat=40.0, lon=-75.0, alt=5.0)

        gga = GnssFix(timestamp=1.2, fix_type=5, lat=41.0, lon=-76.0, alt=99.0, rtk_age=2.5)
        r._record_fix(gga, source="gga")
        assert r.latest_fix().rtk_age == 2.5  # merged

        # Simulate that the merge happened 30 s ago — well past _RTK_AGE_VALID_SEC (10.0).
        r._rtk_age_mono = time.monotonic() - 30
        r._last_navpvt_mono = time.monotonic()
        nav2 = GnssFix(timestamp=2.0, fix_type=5, lat=40.1, lon=-75.1, alt=6.0)
        r._record_fix(nav2, source="nav_pvt")
        assert r.latest_fix().rtk_age == -1.0  # expired; not carried forward
