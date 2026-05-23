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


def _make_session(tmp_path: Path, with_gnss: bool = True,
                  profile: str = "personal", target_crs: int = 0) -> Path:
    """Create a minimal but valid session directory and return its path."""
    sess = tmp_path / "scan_20260523_120000"
    sess.mkdir()
    # metadata.json
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

    # scan.jsonl — 2 IMU samples, 1 lidar scan, optionally 1 gnss fix
    lines = []
    lines.append(json.dumps({
        "type": "imu", "timestamp": 100.0,
        "accel": [0, 0, 9.81], "gyro": [0, 0, 0],
        "mag": None, "orientation": [1.0, 0.0, 0.0, 0.0],
    }))
    lines.append(json.dumps({
        "type": "imu", "timestamp": 100.1,
        "accel": [0, 0, 9.81], "gyro": [0, 0, 0],
        "mag": None, "orientation": [1.0, 0.0, 0.0, 0.0],
    }))
    if with_gnss:
        lines.append(json.dumps({
            "type": "gnss", "timestamp": 100.05,
            "fix_type": 5, "lat": 40.7128, "lon": -74.0060, "alt": 10.0,
            "hdop": 0.85, "vdop": 1.2, "sat_count": 18, "rtk_age": 1.2,
        }))
    lines.append(json.dumps({
        "type": "lidar", "timestamp": 100.05, "step_index": 0,
        "points": [
            {"angle": 0.0, "distance": 1.0, "intensity": 128},
            {"angle": 90.0, "distance": 2.0, "intensity": 200},
            {"angle": 180.0, "distance": 1.5, "intensity": 50},
            {"angle": 270.0, "distance": 0.5, "intensity": 100},
        ],
    }))
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
