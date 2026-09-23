"""Smoke tests for scripts/georef.py — uses a synthetic session.

Pure-Python pieces (loading, NMEA-free pipeline) are testable without hardware.
The CRS-conversion path is skipped when pyproj isn't installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make scripts/ importable as `scripts.georef`
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

np = pytest.importorskip("numpy")

from scripts import georef  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic-session helpers
# ---------------------------------------------------------------------------


def _lidar_record(
    ts: float, step_index: int, mast_angle_deg: float, angles, distances, intensities
) -> dict:
    return {
        "type": "lidar",
        "timestamp": ts,
        "step_index": step_index,
        "mast_angle_deg": mast_angle_deg,
        "lidar_ms_start": 1000,
        "lidar_ms_end": 1090,
        "angle": list(angles),
        "distance": list(distances),
        "intensity": list(intensities),
    }


def _imu_batch(ts: list[float], orientation=(1.0, 0.0, 0.0, 0.0), mag=None) -> dict:
    return {
        "type": "imu",
        "timestamp": ts[-1],
        "t": list(ts),
        "accel": [[0, 0, 9.81]] * len(ts),
        "gyro": [[0, 0, 0]] * len(ts),
        "mag": [mag] * len(ts),
        "orientation": [list(orientation)] * len(ts),
    }


def _make_session(
    tmp_path: Path, with_gnss: bool = True, profile: str = "personal", target_crs: int = 0
) -> Path:
    """Create a minimal but valid session directory and return its path."""
    sess = tmp_path / "scan_20260523_120000"
    sess.mkdir()
    meta = {
        "session_id": sess.name,
        "device_name": "rover-01",
        "firmware_version": "0.10.0",
        "session": {
            "profile": profile,
            "project_code": "TEST" if profile == "arm_group" else "",
            "mission_tag": "BENCH",
            "target_crs_epsg": target_crs,
            "units": "m",
        },
    }
    (sess / "metadata.json").write_text(json.dumps(meta))
    lines = [json.dumps(_imu_batch([100.0, 100.1]))]
    if with_gnss:
        lines.append(
            json.dumps(
                {
                    "type": "gnss",
                    "timestamp": 100.05,
                    "fix_type": 5,
                    "lat": 40.7128,
                    "lon": -74.0060,
                    "alt": 10.0,
                    "hdop": 0.85,
                    "vdop": 1.2,
                    "sat_count": 18,
                    "rtk_age": 1.2,
                }
            )
        )
    lines.append(
        json.dumps(
            _lidar_record(
                100.05, 0, 0.0, [0.0, 90.0, 180.0, 270.0], [1.0, 2.0, 1.5, 0.5], [128, 200, 50, 100]
            )
        )
    )
    (sess / "scan.jsonl").write_text("\n".join(lines) + "\n")
    return sess


# ---------------------------------------------------------------------------
# Session loading
# ---------------------------------------------------------------------------


class TestLoadSession:
    def test_load_returns_records(self, tmp_path):
        sess = _make_session(tmp_path)
        data = georef.load_session(sess)
        assert len(data.lidar_records) == 1
        assert len(data.imu_records) == 2
        assert len(data.gnss_records) == 1
        assert data.metadata["device_name"] == "rover-01"

    def test_load_no_metadata_raises(self, tmp_path):
        sess = tmp_path / "empty"
        sess.mkdir()
        (sess / "scan.jsonl").write_text("")
        with pytest.raises(FileNotFoundError, match="metadata.json"):
            georef.load_session(sess)

    def test_load_flattens_imu_batches(self, tmp_path):
        sess = _make_session(tmp_path)
        data = georef.load_session(sess)
        assert [r["timestamp"] for r in data.imu_records] == [100.0, 100.1]
        assert data.imu_records[0]["orientation"] == [1.0, 0.0, 0.0, 0.0]

    def test_load_session_reads_rotated_files_in_order(self, tmp_path):
        sess = _make_session(tmp_path)
        # Two rotated segments after the base file, deliberately written out of
        # lexical order of creation to prove numeric ordering.
        (sess / "scan_002.jsonl").write_text(
            json.dumps(_lidar_record(300.0, 2, 3.0, [0.0], [1.0], [1])) + "\n"
        )
        (sess / "scan_001.jsonl").write_text(
            json.dumps(_lidar_record(200.0, 1, 1.5, [0.0], [1.0], [1])) + "\n"
        )
        (sess / "gnss.jsonl").write_text("")
        (sess / "gnss_001.jsonl").write_text(
            json.dumps(
                {
                    "type": "gnss",
                    "timestamp": 250.0,
                    "fix_type": 5,
                    "lat": 40.7,
                    "lon": -74.0,
                    "alt": 9.0,
                }
            )
            + "\n"
        )
        data = georef.load_session(sess)
        assert [r["step_index"] for r in data.lidar_records] == [0, 1, 2]
        assert [r["timestamp"] for r in data.gnss_records] == [100.05, 250.0]

    def test_load_session_dedupes_gnss_records_with_same_timestamp(self, tmp_path):
        """T1-053: gnss*.jsonl is now the unconditional GNSS source, merged
        with any legacy GNSS records still embedded in scan*.jsonl (pre-T1-053
        sessions). A record mirrored in both places at the same timestamp
        must be counted once, not twice."""
        sess = _make_session(tmp_path)  # scan.jsonl embeds one gnss record @ 100.05
        (sess / "gnss.jsonl").write_text(
            json.dumps(
                {
                    "type": "gnss",
                    "timestamp": 100.05,
                    "fix_type": 5,
                    "lat": 40.7128,
                    "lon": -74.0060,
                    "alt": 10.0,
                }
            )
            + "\n"
        )
        data = georef.load_session(sess)
        assert [r["timestamp"] for r in data.gnss_records] == [100.05]

    def test_load_session_gnss_file_wins_timestamp_tie_over_scan_embedded(self, tmp_path):
        """Fix round 1, item 3: gnss*.jsonl is the authoritative source — on
        a timestamp tie against a legacy scan-embedded record, the
        gnss-file record's data must survive the dedup, not whichever one
        happened to sort first."""
        sess = _make_session(tmp_path)  # scan.jsonl embeds one gnss record @ 100.05, lat=40.7128
        (sess / "gnss.jsonl").write_text(
            json.dumps(
                {
                    "type": "gnss",
                    "timestamp": 100.05,
                    "fix_type": 5,
                    "lat": 41.0,  # deliberately different from the scan-embedded 40.7128
                    "lon": -75.0,
                    "alt": 20.0,
                }
            )
            + "\n"
        )
        data = georef.load_session(sess)
        assert len(data.gnss_records) == 1
        assert data.gnss_records[0]["lat"] == 41.0

    def test_load_session_does_not_dedup_none_timestamp_gnss_records(self, tmp_path):
        """Fix round 1, item 4: two GNSS records that both lack a timestamp
        are not duplicates of each other — only equal, non-None timestamps
        collapse."""
        sess = tmp_path / "notimestamp"
        sess.mkdir()
        (sess / "metadata.json").write_text(
            json.dumps({"session": {"profile": "personal", "target_crs_epsg": 0, "units": "m"}})
        )
        (sess / "scan.jsonl").write_text("")
        (sess / "gnss.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {"type": "gnss", "timestamp": None, "fix_type": 5, "lat": lat, "lon": -74.0}
                )
                for lat in (1.0, 2.0)
            )
            + "\n"
        )
        data = georef.load_session(sess)
        assert len(data.gnss_records) == 2


# ---------------------------------------------------------------------------
# Quaternion + orientation_at
# ---------------------------------------------------------------------------


class TestOrientationAt:
    def test_identity_when_no_imu(self):
        q = georef.orientation_at(100.0, [])
        np.testing.assert_array_almost_equal(q, [1.0, 0.0, 0.0, 0.0])

    def test_returns_single_sample_when_only_one(self):
        recs = [{"timestamp": 1.0, "orientation": [0.0, 1.0, 0.0, 0.0]}]
        q = georef.orientation_at(1.0, recs)
        np.testing.assert_array_almost_equal(q, [0.0, 1.0, 0.0, 0.0])

    def test_slerps_between_brackets(self):
        # Half-way slerp between identity and 180° about X
        recs = [
            {"timestamp": 0.0, "orientation": [1.0, 0.0, 0.0, 0.0]},
            {"timestamp": 1.0, "orientation": [0.0, 1.0, 0.0, 0.0]},
        ]
        q = georef.orientation_at(0.5, recs)
        expected = np.array([1.0, 1.0, 0.0, 0.0]) / np.sqrt(2)
        np.testing.assert_array_almost_equal(q, expected, decimal=5)


# ---------------------------------------------------------------------------
# Full pipeline → PLY
# ---------------------------------------------------------------------------


class TestPipelinePly:
    def test_export_ply_personal_profile(self, tmp_path):
        sess = _make_session(tmp_path, with_gnss=True, profile="personal", target_crs=0)
        rc = georef.main([str(sess)])
        assert rc == 0
        ply = sess / "export" / f"{sess.name}.ply"
        assert ply.exists()
        # Header should announce 4 vertices (we passed 4 points)
        header = ply.read_bytes()[:200].decode("ascii", errors="replace")
        assert "element vertex 4" in header
        assert "format binary_little_endian" in header

    def test_no_gnss_warns_but_succeeds(self, tmp_path):
        sess = _make_session(tmp_path, with_gnss=False)
        rc = georef.main([str(sess)])
        assert rc == 0
        assert (sess / "export" / f"{sess.name}.ply").exists()

    def test_arm_group_requires_crs(self, tmp_path):
        # arm_group profile with target_crs_epsg == 0 must error out
        sess = _make_session(tmp_path, profile="arm_group", target_crs=0)
        with pytest.raises(SystemExit):
            georef.main([str(sess)])

    def test_arm_group_with_crs_override(self, tmp_path):
        sess = _make_session(tmp_path, profile="arm_group", target_crs=0)
        # Without pyproj, target_epsg != 0 should fail fast
        try:
            import pyproj  # noqa: F401

            has_pyproj = True
        except ImportError:
            has_pyproj = False

        if not has_pyproj:
            with pytest.raises(SystemExit):
                georef.main([str(sess), "--crs", "6563"])
        else:
            rc = georef.main([str(sess), "--crs", "6563", "--no-las"])
            assert rc == 0


# ---------------------------------------------------------------------------
# Point assembly geometry (mount rotation, mast rotation, IMU quaternion)
# ---------------------------------------------------------------------------


class TestGeometry:
    def test_empty_record_returns_tuple(self):
        pts, inten = georef.lidar_points_to_local(
            {"angle": [], "distance": [], "intensity": [], "mast_angle_deg": 0.0},
            np.array([1.0, 0.0, 0.0, 0.0]),
        )
        assert pts.shape == (0, 3) and inten.shape == (0,)

    def test_scan_plane_is_body_xz_at_mast_zero(self):
        rec = {
            "angle": [0.0, 90.0],
            "distance": [2.0, 3.0],
            "intensity": [1, 2],
            "mast_angle_deg": 0.0,
        }
        pts, _ = georef.lidar_points_to_local(rec, np.array([1.0, 0.0, 0.0, 0.0]))
        np.testing.assert_allclose(pts[0], [2.0, 0.0, 0.0], atol=1e-9)  # forward
        np.testing.assert_allclose(pts[1], [0.0, 0.0, 3.0], atol=1e-9)  # LiDAR +y → body up

    def test_mast_rotation_sweeps_forward_point_to_left(self):
        rec = {"angle": [0.0], "distance": [2.0], "intensity": [1], "mast_angle_deg": 90.0}
        pts, _ = georef.lidar_points_to_local(rec, np.array([1.0, 0.0, 0.0, 0.0]))
        np.testing.assert_allclose(
            pts[0], [0.0, 2.0, 0.0], atol=1e-9
        )  # +90° about Z: forward → left

    def test_imu_quaternion_applied_after_mast(self):
        """The rotation order must be mast (Z) THEN IMU quaternion, not the
        reverse. A prior version of this test used a 90 deg-about-Z IMU
        quaternion, which cannot distinguish the two orders — R_z and R_z
        commute, so it passed even if the code applied them backwards. A
        90 deg-about-X quaternion does distinguish them."""
        q = np.array([np.cos(np.pi / 4), np.sin(np.pi / 4), 0.0, 0.0])  # 90° about X
        rec = {"angle": [0.0], "distance": [1.0], "intensity": [1], "mast_angle_deg": 90.0}
        pts, _ = georef.lidar_points_to_local(rec, q)
        # R_x applied after R_z: forward -> left (mast) -> up (IMU)
        np.testing.assert_allclose(pts[0], [0.0, 0.0, 1.0], atol=1e-9)

        # Prove the order matters: the reversed order (IMU before mast) lands
        # somewhere else, [0, 1, 0] — and the function's actual output must
        # differ from it.
        r_z = georef._rot_z(90.0)
        r_x = georef._quat_to_rotmat(q)
        reversed_order = r_z @ (r_x @ np.array([1.0, 0.0, 0.0]))
        np.testing.assert_allclose(reversed_order, [0.0, 1.0, 0.0], atol=1e-9)
        assert not np.allclose(pts[0], reversed_order)

    def test_sweep_produces_a_volume(self, tmp_path):
        """A 2 m ring in the scan plane swept 0..180° about Z must fill a sphere:
        every axis spans about ±2 m and nothing is flat (T1-007)."""
        import json

        sess = tmp_path / "sweep"
        sess.mkdir()
        (sess / "metadata.json").write_text(
            json.dumps({"session": {"profile": "personal", "target_crs_epsg": 0, "units": "m"}})
        )
        angles = [float(a) for a in range(0, 360, 5)]
        lines = [json.dumps(_imu_batch([0.0, 1000.0]))]
        for i, mast in enumerate(range(0, 181, 5)):
            lines.append(
                json.dumps(
                    _lidar_record(
                        float(i), i, float(mast), angles, [2.0] * len(angles), [1] * len(angles)
                    )
                )
            )
        (sess / "scan.jsonl").write_text("\n".join(lines) + "\n")
        data = georef.load_session(sess)
        xyz, inten, origin = georef.session_to_pointcloud(data)
        assert xyz.shape[0] == len(angles) * 37
        for axis in range(3):
            assert xyz[:, axis].min() == pytest.approx(-2.0, abs=0.05)
            assert xyz[:, axis].max() == pytest.approx(2.0, abs=0.05)
        assert xyz[:, 1].std() > 0.5

    def test_nearest_gnss_bisect_matches_linear(self):
        fixes = [{"timestamp": float(t), "lat": 0, "lon": 0} for t in (1, 4, 9, 16)]
        assert georef._nearest_gnss(5.0, fixes)["timestamp"] == 4.0
        assert georef._nearest_gnss(12.6, fixes)["timestamp"] == 16.0
        assert georef._nearest_gnss(0.0, fixes)["timestamp"] == 1.0
        assert georef._nearest_gnss(100.0, fixes)["timestamp"] == 16.0


# ---------------------------------------------------------------------------
# CRS conversion (only runs if pyproj is installed)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pyproj_mod():
    return pytest.importorskip(
        "pyproj",
        reason="pyproj is in the [post] extra; install with `pip install -e .[post]` to test CRS",
    )


# Geographic words expected in each zone's pyproj CRS name — abbreviated keys
# (NJ, MD, DE) don't literally appear in their CRS names ("New Jersey", etc.),
# so this maps each ZONE_EPSG key to the substring its resolved crs.name must
# contain, independent of the key's own spelling.
_ZONE_NAME_WORDS = {
    "PA_NORTH": "Pennsylvania North",
    "PA_SOUTH": "Pennsylvania South",
    "NJ": "New Jersey",
    "MD": "Maryland",
    "DE": "Delaware",
    "NY_EAST": "New York East",
    "NY_CENTRAL": "New York Central",
    "NY_WEST": "New York West",
    "NY_LONG_ISLAND": "New York Long Island",
    "VA_NORTH": "Virginia North",
    "VA_SOUTH": "Virginia South",
    "WV_NORTH": "West Virginia North",
    "WV_SOUTH": "West Virginia South",
}


class TestZoneEpsg:
    def test_zone_epsg_table_resolves_to_named_ftus_crs(self, pyproj_mod):
        """Every ZONE_EPSG code must be a real NAD83(2011) ftUS State Plane CRS
        under the zone's own name (T1-009) — not e.g. a UTM zone."""
        assert set(georef.ZONE_EPSG) == set(_ZONE_NAME_WORDS)
        for name, code in georef.ZONE_EPSG.items():
            crs = pyproj_mod.CRS.from_epsg(code)
            assert _ZONE_NAME_WORDS[name] in crs.name, (
                f"{name}={code} resolved to {crs.name!r}, expected "
                f"{_ZONE_NAME_WORDS[name]!r} in the name"
            )
            assert crs.name.endswith("(ftUS)"), f"{name}={code} is {crs.name!r}, not ftUS"
            unit = crs.axis_info[0].unit_conversion_factor
            assert abs(unit - georef.US_SURVEY_FOOT_M) < 1e-9, (
                f"{name}={code} unit_conversion_factor={unit}, expected US survey foot"
            )


class TestProjectToCrs:
    def test_passthrough_when_epsg_zero(self):
        xyz = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        out, epsg = georef.project_to_crs(xyz, (40.7128, -74.006, 10.0), 0, "m")
        np.testing.assert_array_almost_equal(out, xyz)
        assert epsg == 0

    def test_ft_us_passthrough_scaling(self):
        xyz = np.array([[1.0, 0.0, 0.0]])
        out, epsg = georef.project_to_crs(xyz, (None, None, None), 0, "ft")
        # 1 meter -> 3.2808... US Survey Feet
        assert out[0, 0] == pytest.approx(3.28083, abs=0.001)
        assert epsg == 0

    def test_local_enu_to_pa_north_ftus(self, pyproj_mod):
        # 0 displacement should land roughly on the origin's projected coords
        origin = (40.7128, -74.006, 10.0)
        out, epsg = georef.project_to_crs(np.array([[0.0, 0.0, 0.0]]), origin, 6563, "ft")
        # Just check the result is finite and three columns
        assert out.shape == (1, 3)
        assert np.isfinite(out).all()
        assert epsg == 6563

    def test_no_origin_embeds_epsg_zero(self, caplog):
        """No GNSS fix means the output can't actually be in the requested
        CRS — epsg_to_embed must come back 0 even though target_epsg != 0,
        and a WARNING must explain why (T1-A)."""
        xyz = np.array([[1.0, 2.0, 3.0]])
        with caplog.at_level("WARNING", logger="georef"):
            out, epsg = georef.project_to_crs(xyz, (None, None, None), 6563, "m")
        np.testing.assert_array_almost_equal(out, xyz)
        assert epsg == 0
        assert any("no GNSS fix" in r.message for r in caplog.records)

    def test_geographic_target_raises(self, pyproj_mod):
        """A geographic CRS (e.g. WGS84 lat/lon) is not a valid export target —
        a point cloud needs planar coordinates."""
        origin = (40.7128, -74.006, 10.0)
        with pytest.raises(SystemExit, match="geographic"):
            georef.project_to_crs(np.array([[0.0, 0.0, 0.0]]), origin, 4326, "m")


# ---------------------------------------------------------------------------
# Export units: Z scaled to the CRS unit, --units honoured, double PLY,
# CRS-embed warning
# ---------------------------------------------------------------------------


class TestExportUnits:
    def test_project_to_crs_scales_z_to_crs_unit(self, pyproj_mod):
        """EPSG:6563 is ftUS: a 1 m rise must come out as ~3.2808 ft, not 1 (T1-009)."""
        origin = (40.7128, -74.006, 10.0)
        out, epsg = georef.project_to_crs(
            np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]), origin, 6563, "ft"
        )
        dz = out[1, 2] - out[0, 2]
        assert dz == pytest.approx(1.0 / georef.US_SURVEY_FOOT_M, rel=1e-6)
        # Absolute Z is the ellipsoidal height in feet
        assert out[0, 2] == pytest.approx(10.0 / georef.US_SURVEY_FOOT_M, rel=1e-6)
        assert epsg == 6563

    def test_units_m_on_ftus_crs_converts_all_axes(self, pyproj_mod):
        origin = (40.7128, -74.006, 10.0)
        pts = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        ft, ft_epsg = georef.project_to_crs(pts, origin, 6563, "ft")
        m, m_epsg = georef.project_to_crs(pts, origin, 6563, "m")
        np.testing.assert_allclose(m, ft * georef.US_SURVEY_FOOT_M, rtol=1e-9)
        assert ft_epsg == 6563

    def test_units_mismatch_embeds_epsg_zero_and_warns(self, pyproj_mod, caplog):
        """A units/CRS mismatch (--units m on a native-ftUS CRS) still converts
        the values (existing behaviour) but must now embed epsg 0, not 6563,
        with a WARNING naming the mismatch (T1-A)."""
        origin = (40.7128, -74.006, 10.0)
        pts = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        with caplog.at_level("WARNING", logger="georef"):
            _out, epsg = georef.project_to_crs(pts, origin, 6563, "m")
        assert epsg == 0
        assert any("converted" in r.message for r in caplog.records)

    def test_project_to_crs_native_ft_no_double_scaling(self, pyproj_mod, caplog):
        """EPSG:6563 (PA North) is natively ftUS: --units ft must take the
        unit-native path, not the units-disagree conversion path (T1-009).
        A prior test used EPSG:6346 believing it ftUS; 6346 is actually UTM
        17N (metric), so it silently exercised the mismatch-conversion branch
        instead and got the same numbers by coincidence — this test pins the
        native-ft branch specifically."""
        origin = (40.7128, -74.006, 10.0)
        with caplog.at_level("WARNING", logger="georef"):
            out, epsg = georef.project_to_crs(
                np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]), origin, 6563, "ft"
            )
        dz = out[1, 2] - out[0, 2]
        assert dz == pytest.approx(1.0 / georef.US_SURVEY_FOOT_M, rel=1e-6)
        assert not any("converted" in r.message for r in caplog.records)
        assert epsg == 6563

        crs = pyproj_mod.CRS.from_epsg(6563)
        transformer = pyproj_mod.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        exp_x, exp_y = transformer.transform(origin[1], origin[0])
        assert out[0, 0] == pytest.approx(exp_x, abs=1e-6)
        assert out[0, 1] == pytest.approx(exp_y, abs=1e-6)

    def test_project_to_crs_metric_crs_units_m_unscaled(self, pyproj_mod):
        """EPSG:6564 (PA South, metric) with --units m: no CRS-unit scaling and
        no ft/m mismatch conversion — Z stays exactly origin_alt + up (T1-009)."""
        origin = (40.7128, -74.006, 10.0)
        out, epsg = georef.project_to_crs(np.array([[0.0, 0.0, 1.0]]), origin, 6564, "m")
        assert out[0, 2] == origin[2] + 1.0
        assert epsg == 6564

        crs = pyproj_mod.CRS.from_epsg(6564)
        transformer = pyproj_mod.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        exp_x, exp_y = transformer.transform(origin[1], origin[0])
        assert out[0, 0] == pytest.approx(exp_x, abs=1e-6)
        assert out[0, 1] == pytest.approx(exp_y, abs=1e-6)

    def test_export_ply_is_double_precision(self, tmp_path):
        xyz = np.array([[1_234_567.123456, 2.0, 3.0]])
        inten = np.array([200], dtype=np.uint8)
        out = tmp_path / "p.ply"
        georef.export_ply(out, xyz, inten)
        raw = out.read_bytes()
        header, _, body = raw.partition(b"end_header\n")
        assert b"property double x" in header
        x = np.frombuffer(body[:8], dtype="<f8")[0]
        assert x == pytest.approx(1_234_567.123456, abs=1e-6)

    def test_export_las_warns_when_crs_cannot_be_embedded(self, tmp_path, monkeypatch, caplog):
        laspy = pytest.importorskip("laspy")

        class _NoCrsHeader(laspy.LasHeader):
            def add_crs(self, *_a, **_k):
                raise AttributeError("no add_crs")

        monkeypatch.setattr(laspy, "LasHeader", _NoCrsHeader)
        with caplog.at_level("WARNING", logger="georef"):
            ok = georef.export_las(
                tmp_path / "x.las", np.zeros((1, 3)), np.zeros(1, dtype=np.uint8), 6563
            )
        assert ok
        assert any("CRS" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Yaw handling without a magnetometer (T1-I)
# ---------------------------------------------------------------------------


class TestYawStripWithoutMag:
    """A 6-DOF (no-mag) Madgwick filter's yaw is gyro-drift, not a heading —
    session_to_pointcloud() must strip it and rely on the commanded mast angle
    instead, but only when NO IMU record in the session ever carried a mag
    sample."""

    def _session(self, tmp_path: Path, mag) -> Path:
        sess = tmp_path / "yawtest"
        sess.mkdir()
        (sess / "metadata.json").write_text(
            json.dumps({"session": {"profile": "personal", "target_crs_epsg": 0, "units": "m"}})
        )
        # 90° about Z — pure yaw, no roll/pitch.
        q = (float(np.cos(np.pi / 4)), 0.0, 0.0, float(np.sin(np.pi / 4)))
        lines = [
            json.dumps(_imu_batch([0.0, 1.0], orientation=q, mag=mag)),
            json.dumps(_lidar_record(0.5, 0, 0.0, [0.0], [1.0], [1])),
        ]
        (sess / "scan.jsonl").write_text("\n".join(lines) + "\n")
        return sess

    def test_yaw_stripped_without_mag(self, tmp_path, caplog):
        sess = self._session(tmp_path, mag=None)
        data = georef.load_session(sess)
        with caplog.at_level("INFO", logger="georef"):
            xyz, _intensity, _origin = georef.session_to_pointcloud(data)
        # Yaw stripped: the IMU's 90° Z rotation is discarded, so the forward
        # point stays forward.
        np.testing.assert_allclose(xyz[0], [1.0, 0.0, 0.0], atol=1e-9)
        assert any("no magnetometer data" in r.message for r in caplog.records)

    def test_yaw_kept_with_mag(self, tmp_path):
        """With mag at rest the heading is kept and converted from Madgwick's
        NWU frame to ENU (S3-R1). A 90° yaw in NWU turns body forward from
        magnetic north (NWU +x) to west (NWU +y), which is ENU -x. No GNSS, so
        no declination: the label is "magnetic"."""
        sess = self._session(tmp_path, mag=[1.0, 2.0, 3.0])
        data = georef.load_session(sess)
        xyz, _intensity, _origin = georef.session_to_pointcloud(data)
        np.testing.assert_allclose(xyz[0], [-1.0, 0.0, 0.0], atol=1e-9)


# ---------------------------------------------------------------------------
# Mast-angle-never-changed warning (T1-H)
# ---------------------------------------------------------------------------


class TestMastAngleNeverChangedWarning:
    def test_warns_when_every_record_shares_one_mast_angle(self, tmp_path, caplog):
        sess = tmp_path / "planar"
        sess.mkdir()
        (sess / "metadata.json").write_text(
            json.dumps({"session": {"profile": "personal", "target_crs_epsg": 0, "units": "m"}})
        )
        lines = [json.dumps(_lidar_record(float(i), i, 0.0, [0.0], [1.0], [1])) for i in range(3)]
        (sess / "scan.jsonl").write_text("\n".join(lines) + "\n")
        data = georef.load_session(sess)
        with caplog.at_level("WARNING", logger="georef"):
            georef.session_to_pointcloud(data)
        assert any("mast angle never changed" in r.message for r in caplog.records)

    def test_no_warning_when_mast_angle_varies(self, tmp_path, caplog):
        sess = tmp_path / "notplanar"
        sess.mkdir()
        (sess / "metadata.json").write_text(
            json.dumps({"session": {"profile": "personal", "target_crs_epsg": 0, "units": "m"}})
        )
        lines = [
            json.dumps(_lidar_record(float(i), i, float(i * 10), [0.0], [1.0], [1]))
            for i in range(3)
        ]
        (sess / "scan.jsonl").write_text("\n".join(lines) + "\n")
        data = georef.load_session(sess)
        with caplog.at_level("WARNING", logger="georef"):
            georef.session_to_pointcloud(data)
        assert not any("mast angle never changed" in r.message for r in caplog.records)


class TestDeclination:
    _WHEN = 1790121600.0  # 2026-09-23T00:00:00Z

    def test_state_college_known_answer(self):
        pytest.importorskip("pygeomag", reason="pygeomag not installed (post/dev extra)")
        d = georef.magnetic_declination_deg(40.79, -77.86, self._WHEN)
        assert d == pytest.approx(-10.5348, abs=0.01)

    def test_east_pa_is_more_westerly_than_central(self):
        pytest.importorskip("pygeomag", reason="pygeomag not installed (post/dev extra)")
        central = georef.magnetic_declination_deg(40.79, -77.86, self._WHEN)
        east = georef.magnetic_declination_deg(41.40, -75.66, self._WHEN)
        assert east < central < -9.0

    def test_outside_lifespan_returns_none(self, caplog):
        """Review Focus 5: WMM 2025 ends in 2030; a later session falls back."""
        pytest.importorskip("pygeomag", reason="pygeomag not installed (post/dev extra)")
        when_2031 = 1940000000.0  # 2031-06-23
        with caplog.at_level("WARNING", logger="georef"):
            assert georef.magnetic_declination_deg(40.79, -77.86, when_2031) is None
        assert any("life span" in r.message or "lifespan" in r.message for r in caplog.records)

    def test_missing_library_returns_none(self, monkeypatch, caplog):
        monkeypatch.setattr(georef, "_optional_import", lambda name: None)
        with caplog.at_level("WARNING", logger="georef"):
            assert georef.magnetic_declination_deg(40.79, -77.86, self._WHEN) is None
        assert any("pygeomag" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Heading model (S3-R1, S3-R3): NWU->ENU, per-sweep rest heading, tilt per
# scan, IMU mount, rotating antenna lever arm.
# ---------------------------------------------------------------------------


def _heading_session(
    tmp_path: Path,
    *,
    name: str = "hd",
    rest_q=(1.0, 0.0, 0.0, 0.0),
    scan_q=None,
    mag=(20.0, 0.0, -40.0),
    with_gnss: bool = True,
    mast_angles=(0.0,),
    mount: str = "base",
    antenna_offset=None,
    when: float = 1790121600.0,
    platform_q_follows_mast: bool = False,
) -> Path:
    """Rest IMU sample (with mag) at `when`, sweep_start at when+0.1, one lidar
    point 1 m straight ahead per mast angle, GNSS fix at State College."""
    sess = tmp_path / name
    sess.mkdir()
    meta = {
        "session": {"profile": "personal", "target_crs_epsg": 0, "units": "m"},
        "geometry": {"imu_mount": mount, "antenna_offset_m": antenna_offset},
    }
    (sess / "metadata.json").write_text(json.dumps(meta))
    lines = [json.dumps(_imu_batch([when], orientation=rest_q, mag=list(mag) if mag else None))]
    lines.append(
        json.dumps(
            {
                "type": "event",
                "timestamp": when + 0.1,
                "event": "sweep_start",
                "details": {"sweep": 0, "rest_sec": 0.1},
            }
        )
    )
    if with_gnss:
        lines.append(
            json.dumps(
                {
                    "type": "gnss",
                    "timestamp": when + 0.2,
                    "fix_type": 5,
                    "lat": 40.79,
                    "lon": -77.86,
                    "alt": 300.0,
                    "hdop": 0.8,
                    "vdop": 1.0,
                    "sat_count": 18,
                    "rtk_age": 1.0,
                }
            )
        )
    for i, m in enumerate(mast_angles):
        t = when + 1.0 + i
        q = scan_q if scan_q is not None else rest_q
        if platform_q_follows_mast:
            # IMU on the platform: R_platform = R_base · Rz(mast)
            q = tuple(
                float(v)
                for v in georef._rotmat_to_quat(georef._quat_to_rotmat(q) @ georef._rot_z(m))
            )
        lines.append(json.dumps(_imu_batch([t - 0.01, t + 0.01], orientation=q, mag=None)))
        rec = _lidar_record(t, i, float(m), [0.0], [1.0], [1])
        rec["sweep"] = 0
        lines.append(json.dumps(rec))
    (sess / "scan.jsonl").write_text("\n".join(lines) + "\n")
    return sess


class TestHeadingModel:
    D_STATE_COLLEGE = -10.5348  # Task 5 known answer, 2026-09-23

    def test_true_north_known_answer(self, tmp_path):
        """Body forward = magnetic north at rest (identity NWU quaternion). With
        D = -10.53°, a point 1 m ahead lies at true azimuth 349.47°:
        ENU (-sin 10.53°, cos 10.53°, 0)."""
        pytest.importorskip("pygeomag", reason="pygeomag not installed (post/dev extra)")
        import math

        data = georef.load_session(_heading_session(tmp_path))
        info: dict = {}
        xyz, _i, _o = georef.session_to_pointcloud(data, info=info)
        d = math.radians(-self.D_STATE_COLLEGE)
        np.testing.assert_allclose(xyz[0], [-math.sin(d), math.cos(d), 0.0], atol=1e-3)
        assert info["heading_reference"] == "true"
        assert info["declination_deg"] == pytest.approx(self.D_STATE_COLLEGE, abs=0.01)

    def test_magnetic_label_without_gnss(self, tmp_path):
        """Review Focus 4: mag at rest, no GNSS → 'magnetic', no declination,
        forward = magnetic north = ENU +y."""
        data = georef.load_session(_heading_session(tmp_path, with_gnss=False))
        info: dict = {}
        xyz, _i, _o = georef.session_to_pointcloud(data, info=info)
        np.testing.assert_allclose(xyz[0], [0.0, 1.0, 0.0], atol=1e-9)
        assert info["heading_reference"] == "magnetic"
        assert info["declination_deg"] is None

    def test_relative_label_without_mag(self, tmp_path):
        data = georef.load_session(_heading_session(tmp_path, mag=None, with_gnss=False))
        info: dict = {}
        xyz, _i, _o = georef.session_to_pointcloud(data, info=info)
        np.testing.assert_allclose(xyz[0], [1.0, 0.0, 0.0], atol=1e-9)
        assert info["heading_reference"] == "relative"

    def test_gyro_yaw_drift_during_sweep_is_ignored(self, tmp_path):
        """The scan-time quaternion carries 30° of gyro yaw drift (mag off while
        stepping, DEC-013). Yaw comes from the rest heading, so the point stays put."""
        import math

        h = math.radians(30.0) / 2
        drifted = (math.cos(h), 0.0, 0.0, math.sin(h))
        data = georef.load_session(_heading_session(tmp_path, scan_q=drifted, with_gnss=False))
        xyz, _i, _o = georef.session_to_pointcloud(data)
        np.testing.assert_allclose(xyz[0], [0.0, 1.0, 0.0], atol=1e-9)

    def test_tilt_applied_per_scan(self, tmp_path):
        """Base tilted 10° about body X, relative heading: at mast 90° the
        forward point goes left, then the tilt lifts it: (0, cos10°, sin10°)."""
        import math

        h = math.radians(10.0) / 2
        tilted = (math.cos(h), math.sin(h), 0.0, 0.0)
        data = georef.load_session(
            _heading_session(
                tmp_path, rest_q=tilted, mag=None, with_gnss=False, mast_angles=(90.0,)
            )
        )
        xyz, _i, _o = georef.session_to_pointcloud(data)
        t = math.radians(10.0)
        np.testing.assert_allclose(xyz[0], [0.0, math.cos(t), math.sin(t)], atol=1e-9)

    def test_scan_time_tilt_used_not_rest_time_tilt(self, tmp_path):
        """test_tilt_applied_per_scan (brief-verbatim) sets scan_q == rest_q, so
        it cannot tell whether the tilt came from the scan-time orientation or
        the rest-time one. Here the rest orientation is LEVEL (identity, mag
        present -> yaw_ref = 90 deg, magnetic heading) and only the scan-time
        orientation is tilted 10 deg about X; at mast 90 deg the point must
        show that tilt, which is possible only if tilt comes from q_t
        (orientation_at the scan timestamp), not from the rest sample:
        world = Rz(90) . Rx(10) . mast-rotated-forward = (-cos10, 0, sin10)."""
        import math

        h = math.radians(10.0) / 2
        tilted = (math.cos(h), math.sin(h), 0.0, 0.0)
        data = georef.load_session(
            _heading_session(tmp_path, scan_q=tilted, with_gnss=False, mast_angles=(90.0,))
        )
        xyz, _i, _o = georef.session_to_pointcloud(data)
        t = math.radians(10.0)
        np.testing.assert_allclose(xyz[0], [-math.cos(t), 0.0, math.sin(t)], atol=1e-9)

    def test_platform_mount_matches_base_mount(self, tmp_path):
        """An IMU riding the mast reports R_base · Rz(mast). With mount =
        'platform' the mast rotation is removed before the tilt is taken, so
        the cloud equals the base-mount cloud of the same scene.

        The base is TILTED 10° about X on purpose: with a level base, strip_yaw
        would discard a pure mast yaw anyway, and the test would pass even if
        the mount were ignored. With a tilt, ignoring the mount makes the tilt
        axis turn with the mast (strip_yaw(Rx·Rz(m)) != Rx), so the clouds differ."""
        import math

        h = math.radians(10.0) / 2
        tilted = (math.cos(h), math.sin(h), 0.0, 0.0)
        masts = (0.0, 45.0, 90.0, 135.0)
        base = georef.session_to_pointcloud(
            georef.load_session(
                _heading_session(
                    tmp_path, name="b", rest_q=tilted, mast_angles=masts, with_gnss=False
                )
            )
        )[0]
        plat = georef.session_to_pointcloud(
            georef.load_session(
                _heading_session(
                    tmp_path,
                    name="p",
                    rest_q=tilted,
                    mast_angles=masts,
                    with_gnss=False,
                    mount="platform",
                    platform_q_follows_mast=True,
                )
            )
        )[0]
        np.testing.assert_allclose(plat, base, atol=1e-9)
        # Same scene with the mount wrongly declared "base" must NOT match.
        wrong = georef.session_to_pointcloud(
            georef.load_session(
                _heading_session(
                    tmp_path,
                    name="w",
                    rest_q=tilted,
                    mast_angles=masts,
                    with_gnss=False,
                    mount="base",
                    platform_q_follows_mast=True,
                )
            )
        )[0]
        assert not np.allclose(wrong, base, atol=1e-6)

    def test_lever_arm_on_axis(self, tmp_path):
        """Antenna 0.5 m above the LiDAR: every point drops 0.5 m (relative heading)."""
        data = georef.load_session(
            _heading_session(tmp_path, mag=None, antenna_offset=[0.0, 0.0, 0.5])
        )
        xyz, _i, _o = georef.session_to_pointcloud(data)
        np.testing.assert_allclose(xyz[0], [1.0, 0.0, -0.5], atol=1e-6)

    def test_lever_arm_rotates_with_mast(self, tmp_path):
        """Antenna 0.2 m ahead and 0.5 m up at mast 0; at mast 90° the arm
        points left: forward point (0, 1, 0) minus arm (0, 0.2, 0.5)."""
        data = georef.load_session(
            _heading_session(
                tmp_path, mag=None, antenna_offset=[0.2, 0.0, 0.5], mast_angles=(90.0,)
            )
        )
        xyz, _i, _o = georef.session_to_pointcloud(data)
        np.testing.assert_allclose(xyz[0], [0.0, 0.8, -0.5], atol=1e-6)

    def test_lever_arm_uses_world_rotation_not_mast_alone(self, tmp_path):
        """test_lever_arm_on_axis and test_lever_arm_rotates_with_mast both use
        mag=None (relative heading, level rest_q), so r_world is the identity
        there and cannot show whether the arm subtraction actually rotates by
        r_world or just by the mast. Here the base is tilted 10 deg about X
        (mag off, so heading stays relative/yaw_ref=0, but r_world = Rx(10) is
        NOT identity) with antenna_offset_m = [0.2, 0.0, 0.5] at mast 0.

        By hand: forward point world = (1, 0, 0) (mast 0, X-axis is invariant
        under an X-tilt, so the point itself doesn't visibly move). GNSS has
        one fix == the origin, so no ENU offset. The arm is
        r_world @ (Rz(0) @ a) = Rx(10) @ (0.2, 0, 0.5)
          = (0.2, -0.5*sin10, 0.5*cos10),
        so the exported point is (1,0,0) - that arm =
        (0.8, 0.5*sin10, -0.5*cos10) -- NOT (0.8, 0, -0.5), which is what a
        mast-only (r_world-less) subtraction would give."""
        import math

        h = math.radians(10.0) / 2
        tilted = (math.cos(h), math.sin(h), 0.0, 0.0)
        data = georef.load_session(
            _heading_session(tmp_path, rest_q=tilted, mag=None, antenna_offset=[0.2, 0.0, 0.5])
        )
        xyz, _i, _o = georef.session_to_pointcloud(data)
        t = math.radians(10.0)
        expected = [0.8, 0.5 * math.sin(t), -0.5 * math.cos(t)]
        np.testing.assert_allclose(xyz[0], expected, atol=1e-6)
        # A mast-only subtraction (dropping r_world) would give (0.8, 0, -0.5)
        # instead -- confirm the two are not the same point.
        assert not np.allclose(xyz[0], [0.8, 0.0, -0.5], atol=1e-6)

    def test_old_session_without_geometry_or_events_loads(self, tmp_path):
        """Pre-stage-5 sessions: no geometry, no sweep field, no sweep_start."""
        sess = _make_session(tmp_path)
        data = georef.load_session(sess)
        assert data.sweep_starts == {}
        xyz, _i, _o = georef.session_to_pointcloud(data)
        assert len(xyz) == 4

    # -----------------------------------------------------------------------
    # Multi-sweep pinning (fix round 1): the brief's own _heading_session
    # always builds exactly one sweep, so none of the tests above can tell
    # the per-sweep rest window, the old-session rest_end fallback, or the
    # missing-sweep reuse rule apart from a bug that happens to look right on
    # a single sweep. These build a SessionData directly (bypassing the JSONL
    # round trip, which is already pinned by test_old_session_..._loads and
    # the true/magnetic/relative label tests above) to isolate
    # _rest_samples_by_sweep's window arithmetic precisely.
    # -----------------------------------------------------------------------

    def test_rest_window_excludes_other_sweeps_scan_time_and_post_start_samples(
        self, tmp_path, caplog
    ):
        """Three sweeps:
          - sweep 0's rest sample is at t=0.0 (NWU yaw 0 deg); a mag sample at
            t=1.5 sits DURING sweep 0's own scans (first lidar t=1.0, last
            t=2.0) and must not leak into sweep 1's rest window (it would, if
            the window dropped its prev_end lower bound).
          - sweep 1's rest sample is at t=3.0 (NWU yaw -90 deg,
            sweep_starts[1]=3.1); a mag sample at t=3.2, just AFTER that
            sweep_start, must not leak in either (it would, if the window
            dropped its rest_end upper bound).
          - sweep 2 has no rest samples at all (sweep_starts[2]=4.9 is used
            only as a rest_end bound, no mag sample falls in it) and must
            reuse sweep 1's yaw_ref, with exactly one WARNING naming it.
        No declination (no GNSS), so yaw_ref = yaw(Rz(90) . R(rest_q)):
        sweep 0 (NWU 0) -> ENU +Y forward; sweep 1 and the reused sweep 2
        (NWU -90) -> ENU +X forward."""
        import math

        def qz(deg):
            half = math.radians(deg) / 2
            return [math.cos(half), 0.0, 0.0, math.sin(half)]

        def lidar(t, sweep):
            return {
                "type": "lidar",
                "timestamp": t,
                "mast_angle_deg": 0.0,
                "angle": [0.0],
                "distance": [1.0],
                "intensity": [1],
                "sweep": sweep,
            }

        imu = [
            {"timestamp": 0.0, "orientation": qz(0.0), "mag": [1.0, 0.0, 0.0]},
            {"timestamp": 1.5, "orientation": qz(45.0), "mag": [1.0, 0.0, 0.0]},
            {"timestamp": 3.0, "orientation": qz(-90.0), "mag": [1.0, 0.0, 0.0]},
            {"timestamp": 3.2, "orientation": qz(45.0), "mag": [1.0, 0.0, 0.0]},
            {"timestamp": 5.0, "orientation": qz(45.0), "mag": None},
        ]
        session = georef.SessionData(
            metadata={},
            lidar_records=[lidar(1.0, 0), lidar(2.0, 0), lidar(3.5, 1), lidar(5.0, 2)],
            imu_records=imu,
            gnss_records=[],
            sweep_starts={0: 0.5, 1: 3.1, 2: 4.9},
        )
        imu_sorted = sorted(imu, key=lambda r: r["timestamp"])
        rest = georef._rest_samples_by_sweep(session, imu_sorted)
        assert [s["timestamp"] for s in rest[0]] == [0.0]
        assert [s["timestamp"] for s in rest[1]] == [3.0]
        assert rest[2] == []

        info: dict = {}
        with caplog.at_level("WARNING", logger="georef"):
            xyz, _i, _o = georef.session_to_pointcloud(session, info=info)
        np.testing.assert_allclose(xyz[0], [0.0, 1.0, 0.0], atol=1e-9)  # sweep 0 @ t=1.0
        np.testing.assert_allclose(xyz[1], [0.0, 1.0, 0.0], atol=1e-9)  # sweep 0 @ t=2.0
        np.testing.assert_allclose(xyz[2], [1.0, 0.0, 0.0], atol=1e-9)  # sweep 1
        np.testing.assert_allclose(xyz[3], [1.0, 0.0, 0.0], atol=1e-9)  # sweep 2, reused
        reuse_warnings = [
            r.message
            for r in caplog.records
            if r.levelname == "WARNING" and "rest heading" in r.message
        ]
        assert len(reuse_warnings) == 1
        assert "2" in reuse_warnings[0]

    def test_old_session_rest_end_falls_back_to_first_lidar_timestamp(self):
        """No sweep_start events at all (pre-stage-5 session): rest_end for
        sweep 0 must fall back to its FIRST lidar timestamp (10.0), not its
        last (11.0) and not +inf. A mag sample just before 10.0 counts; one
        just after must not, even though it is still well before the sweep's
        last scan."""

        def lidar(t):
            return {
                "type": "lidar",
                "timestamp": t,
                "mast_angle_deg": 0.0,
                "angle": [0.0],
                "distance": [1.0],
                "intensity": [1],
                "sweep": 0,
            }

        imu = [
            {"timestamp": 9.9, "orientation": [1.0, 0.0, 0.0, 0.0], "mag": [1.0, 0.0, 0.0]},
            {"timestamp": 10.1, "orientation": [1.0, 0.0, 0.0, 0.0], "mag": [1.0, 0.0, 0.0]},
        ]
        session = georef.SessionData(
            metadata={},
            lidar_records=[lidar(10.0), lidar(11.0)],
            imu_records=imu,
            gnss_records=[],
            # sweep_starts intentionally empty: no sweep_start events.
        )
        rest = georef._rest_samples_by_sweep(session, imu)
        assert [s["timestamp"] for s in rest[0]] == [9.9]

    def test_circular_mean_wraps_across_plus_minus_180(self):
        """Rest samples at yaw ~= +179 deg and -179 deg straddle the wrap
        boundary; their true circular mean is 180 deg. A naive arithmetic
        mean would silently give 0 deg -- the opposite heading."""
        assert georef._circular_mean_deg([179.0, -179.0]) == pytest.approx(180.0, abs=1e-6)
