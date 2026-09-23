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


def _imu_batch(ts: list[float], orientation=(1.0, 0.0, 0.0, 0.0)) -> dict:
    return {
        "type": "imu",
        "timestamp": ts[-1],
        "t": list(ts),
        "accel": [[0, 0, 9.81]] * len(ts),
        "gyro": [[0, 0, 0]] * len(ts),
        "mag": [None] * len(ts),
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
                georef.main([str(sess), "--crs", "6346"])
        else:
            rc = georef.main([str(sess), "--crs", "6346", "--no-las"])
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
        # 90° about body Z from the IMU, mast at 0: forward → left
        q = np.array([np.cos(np.pi / 4), 0.0, 0.0, np.sin(np.pi / 4)])
        rec = {"angle": [0.0], "distance": [1.0], "intensity": [1], "mast_angle_deg": 0.0}
        pts, _ = georef.lidar_points_to_local(rec, q)
        np.testing.assert_allclose(pts[0], [0.0, 1.0, 0.0], atol=1e-9)

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


class TestProjectToCrs:
    def test_passthrough_when_epsg_zero(self):
        xyz = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        out = georef.project_to_crs(xyz, (40.7128, -74.006, 10.0), 0, "m")
        np.testing.assert_array_almost_equal(out, xyz)

    def test_ft_us_passthrough_scaling(self):
        xyz = np.array([[1.0, 0.0, 0.0]])
        out = georef.project_to_crs(xyz, (None, None, None), 0, "ft")
        # 1 meter -> 3.2808... US Survey Feet
        assert out[0, 0] == pytest.approx(3.28083, abs=0.001)

    def test_local_enu_to_pa_north_ftus(self, pyproj_mod):
        # 0 displacement should land roughly on the origin's projected coords
        origin = (40.7128, -74.006, 10.0)
        out = georef.project_to_crs(np.array([[0.0, 0.0, 0.0]]), origin, 6346, "ft")
        # Just check the result is finite and three columns
        assert out.shape == (1, 3)
        assert np.isfinite(out).all()
