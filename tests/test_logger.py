"""Unit tests for rover.logger — runs anywhere, no hardware required."""

import json
import threading
import time
from pathlib import Path

import pytest

from rover.config import load_config
from rover.logger import SessionLogger


@pytest.fixture
def cfg(tmp_path):
    """Return a RoverConfig with output_dir pointed at tmp_path."""
    toml_content = f"""
[logging]
output_dir = "{tmp_path.as_posix()}"
session_prefix = "test"
format = "jsonl"
flush_interval_sec = 60.0
rotate_size_mb = 0
save_images = true
"""
    p = tmp_path / "test.toml"
    p.write_text(toml_content)
    return load_config(p), p


@pytest.fixture
def fast_flush_cfg(tmp_path):
    """Config with very fast flush interval for timing tests."""
    toml_content = f"""
[logging]
output_dir = "{tmp_path.as_posix()}"
session_prefix = "test"
flush_interval_sec = 0.1
rotate_size_mb = 0
"""
    p = tmp_path / "test.toml"
    p.write_text(toml_content)
    return load_config(p), p


@pytest.fixture
def small_rotate_cfg(tmp_path):
    """Config with tiny rotation size for testing rotation."""
    toml_content = f"""
[logging]
output_dir = "{tmp_path.as_posix()}"
session_prefix = "test"
flush_interval_sec = 60.0
rotate_size_mb = 1
"""
    p = tmp_path / "test.toml"
    p.write_text(toml_content)
    return load_config(p), p


# ---------------------------------------------------------------------------
# Session directory
# ---------------------------------------------------------------------------


class TestSessionDirectory:
    def test_start_creates_session_dir(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            assert session_dir.exists()
            assert session_dir.name.startswith("test_")
        finally:
            lg.stop()

    def test_session_dir_contains_scan_jsonl(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            assert (session_dir / "scan.jsonl").exists()
            assert (session_dir / "gnss.jsonl").exists()
        finally:
            lg.stop()

    def test_images_dir_created_when_camera_enabled(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            assert lg.images_dir is not None
            assert lg.images_dir.exists()
            assert lg.images_dir.name == config.camera.output_folder
        finally:
            lg.stop()

    def test_double_start_raises(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        lg.start()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                lg.start()
        finally:
            lg.stop()


# ---------------------------------------------------------------------------
# Config snapshot
# ---------------------------------------------------------------------------


class TestConfigSnapshot:
    def test_config_toml_copied(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            assert (session_dir / "config.toml").exists()
        finally:
            lg.stop()

    def test_effective_config_written_when_no_path(self, cfg):
        config, _ = cfg
        lg = SessionLogger(config, config_path=None)
        session_dir = lg.start()
        try:
            assert (session_dir / "effective_config.json").exists()
            data = json.loads(
                (session_dir / "effective_config.json").read_text()
            )
            assert data["general"]["device_name"] == "rover-01"
        finally:
            lg.stop()


# ---------------------------------------------------------------------------
# JSONL writing
# ---------------------------------------------------------------------------


class TestJSONLWriting:
    def test_write_and_read_back(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            record = {
                "type": "lidar",
                "timestamp": 1735226852.123456,
                "step_index": 0,
                "points": [],
            }
            lg.write(record)
            lg._flush()

            lines = (session_dir / "scan.jsonl").read_text().strip().split("\n")
            assert len(lines) == 1
            parsed = json.loads(lines[0])
            assert parsed["type"] == "lidar"
            assert parsed["timestamp"] == 1735226852.123456
        finally:
            lg.stop()

    def test_gnss_records_routed_to_gnss_file(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            gnss_record = {
                "type": "gnss",
                "timestamp": 1735226852.0,
                "fix_type": 5,
                "lat": 40.7128,
                "lon": -74.006,
            }
            lg.write(gnss_record)
            lg._flush()

            # Should appear in gnss.jsonl
            gnss_lines = (
                (session_dir / "gnss.jsonl").read_text().strip().split("\n")
            )
            assert len(gnss_lines) == 1
            assert json.loads(gnss_lines[0])["type"] == "gnss"

            # Should also appear in scan.jsonl (all records go there)
            scan_lines = (
                (session_dir / "scan.jsonl").read_text().strip().split("\n")
            )
            assert len(scan_lines) == 1
        finally:
            lg.stop()

    def test_non_gnss_not_in_gnss_file(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            lg.write({"type": "imu", "timestamp": 1.0, "accel": [0, 0, 9.81]})
            lg._flush()

            gnss_content = (session_dir / "gnss.jsonl").read_text().strip()
            assert gnss_content == ""
        finally:
            lg.stop()

    def test_write_when_not_running_raises(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        with pytest.raises(RuntimeError, match="not running"):
            lg.write({"type": "imu"})

    def test_multiple_records(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            for i in range(10):
                lg.write({"type": "imu", "timestamp": float(i)})
            lg._flush()

            lines = (session_dir / "scan.jsonl").read_text().strip().split("\n")
            assert len(lines) == 10
        finally:
            lg.stop()


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_writes(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()

        errors = []
        n_per_thread = 100
        n_threads = 4

        def writer(thread_id: int) -> None:
            try:
                for i in range(n_per_thread):
                    lg.write({
                        "type": "imu",
                        "thread": thread_id,
                        "seq": i,
                    })
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(t,))
            for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lg._flush()
        lg.stop()

        assert not errors
        lines = (session_dir / "scan.jsonl").read_text().strip().split("\n")
        assert len(lines) == n_per_thread * n_threads


# ---------------------------------------------------------------------------
# Periodic flush
# ---------------------------------------------------------------------------


class TestPeriodicFlush:
    def test_auto_flush(self, fast_flush_cfg):
        config, config_path = fast_flush_cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            lg.write({"type": "imu", "timestamp": 1.0})
            # Wait for auto-flush (interval is 0.1s)
            time.sleep(0.3)

            content = (session_dir / "scan.jsonl").read_text().strip()
            assert len(content) > 0
        finally:
            lg.stop()


# ---------------------------------------------------------------------------
# File rotation
# ---------------------------------------------------------------------------


class TestFileRotation:
    def test_rotation_creates_new_file(self, tmp_path):
        # Use a very small rotation size (1 byte effectively via direct manipulation)
        toml_content = f"""
[logging]
output_dir = "{tmp_path.as_posix()}"
session_prefix = "test"
flush_interval_sec = 60.0
rotate_size_mb = 1
"""
        p = tmp_path / "test.toml"
        p.write_text(toml_content)
        config = load_config(p)

        lg = SessionLogger(config, p)
        session_dir = lg.start()
        try:
            # Write enough to trigger rotation by artificially inflating file
            # Write a record first so scan.jsonl exists with content
            lg.write({"type": "imu", "timestamp": 1.0})
            lg._flush()

            # Pad the file to exceed 1 MB
            with open(session_dir / "scan.jsonl", "a") as f:
                f.write("x" * (1024 * 1024 + 1))

            # Next flush should trigger rotation
            lg.write({"type": "imu", "timestamp": 2.0})
            lg._flush()

            assert (session_dir / "scan_001.jsonl").exists()
        finally:
            lg.stop()

    def test_no_rotation_when_disabled(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            for i in range(100):
                lg.write({"type": "imu", "timestamp": float(i)})
            lg._flush()

            # No rotated files should exist
            rotated = list(session_dir.glob("scan_*.jsonl"))
            assert len(rotated) == 0
        finally:
            lg.stop()


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_metadata_written_on_stop(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        lg.stop()

        meta_path = session_dir / "metadata.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["device_name"] == "rover-01"
        assert meta["firmware_version"] == "0.1.0"
        assert "session_id" in meta
        assert "start_time" in meta
        assert "end_time" in meta
        assert "config_hash" in meta

    def test_metadata_includes_extra_fields(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        lg.start()
        lg.stop(metadata={"total_steps": 180, "total_scans": 180})

        meta = json.loads(
            (lg.session_dir / "metadata.json").read_text()
        )
        assert meta["total_steps"] == 180
        assert meta["total_scans"] == 180

    def test_config_hash_is_sha256(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        lg.start()
        lg.stop()

        meta = json.loads(
            (lg.session_dir / "metadata.json").read_text()
        )
        assert meta["config_hash"] is not None
        assert len(meta["config_hash"]) == 64  # SHA-256 hex length


# ---------------------------------------------------------------------------
# Double stop
# ---------------------------------------------------------------------------


class TestDoubleStop:
    def test_double_stop_is_safe(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        lg.start()
        lg.stop()
        lg.stop()  # Should not raise
