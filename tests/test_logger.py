"""Unit tests for rover.logger — runs anywhere, no hardware required."""

import json
import queue
import threading
import time
from pathlib import Path

import pytest

import rover
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

    def test_images_dir_not_precreated_by_start(self, cfg):
        """The logger no longer owns the images directory (T1-033) — the
        camera creates it lazily on first capture, so start() must not."""
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        session_dir = lg.start()
        try:
            assert not (session_dir / config.camera.output_folder).exists()
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
            data = json.loads((session_dir / "effective_config.json").read_text())
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
            gnss_lines = (session_dir / "gnss.jsonl").read_text().strip().split("\n")
            assert len(gnss_lines) == 1
            assert json.loads(gnss_lines[0])["type"] == "gnss"

            # Should also appear in scan.jsonl (all records go there)
            scan_lines = (session_dir / "scan.jsonl").read_text().strip().split("\n")
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
                    lg.write(
                        {
                            "type": "imu",
                            "thread": thread_id,
                            "seq": i,
                        }
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
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
        assert meta["firmware_version"] == rover.__version__
        assert "session_id" in meta
        assert "start_time" in meta
        assert "end_time" in meta
        assert "config_hash" in meta
        # v0.10 — session block added (DEC-030, DEC-034)
        assert "session" in meta
        assert meta["session"]["profile"] == "personal"
        assert meta["session"]["target_crs_epsg"] == 0
        assert meta["session"]["units"] == "m"

    def test_metadata_includes_extra_fields(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        lg.start()
        lg.stop(metadata={"total_steps": 180, "total_scans": 180})

        meta = json.loads((lg.session_dir / "metadata.json").read_text())
        assert meta["total_steps"] == 180
        assert meta["total_scans"] == 180

    def test_config_hash_is_sha256(self, cfg):
        config, config_path = cfg
        lg = SessionLogger(config, config_path)
        lg.start()
        lg.stop()

        meta = json.loads((lg.session_dir / "metadata.json").read_text())
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


# ---------------------------------------------------------------------------
# Fault-tolerant flush (T1-011, T1-032)
# ---------------------------------------------------------------------------


def test_flush_failure_keeps_timer_alive(fast_flush_cfg, monkeypatch):
    """A write error inside the timer thread must not stop future flushes (T1-011)."""
    config, path = fast_flush_cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    try:
        calls = {"n": 0}
        real = lg._write_record

        def _boom(record):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError(28, "No space left on device")
            real(record)

        monkeypatch.setattr(lg, "_write_record", _boom)
        lg.write({"type": "event", "event": "first"})
        time.sleep(0.3)  # first flush raises
        assert lg.degraded is True
        assert lg._flush_timer is not None and lg._flush_timer.is_alive()
        lg.write({"type": "event", "event": "second"})
        time.sleep(0.3)  # second flush succeeds
    finally:
        lg.stop()
    text = (lg.session_dir / "scan.jsonl").read_text()
    assert '"second"' in text


def test_queue_is_bounded_and_drops_oldest(cfg):
    config, path = cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    try:
        from rover import logger as logger_mod

        for i in range(logger_mod._QUEUE_MAX + 5):
            lg.write({"type": "event", "i": i})
        assert lg.dropped_records == 5
    finally:
        lg.stop()
    lines = (lg.session_dir / "scan.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    assert first["i"] == 5, "oldest five must have been dropped"


def test_stop_fsyncs_files(cfg, monkeypatch):
    import os as os_mod

    synced: list[int] = []
    monkeypatch.setattr(os_mod, "fsync", lambda fd: synced.append(fd))
    config, path = cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    lg.write({"type": "event", "event": "x"})
    lg.stop()
    assert len(synced) >= 2, "scan and gnss files must be fsync'd at stop"


def test_metadata_written_atomically(cfg, monkeypatch):
    from rover import logger as logger_mod

    called: list[str] = []

    def _fake_atomic(path, data):
        called.append(str(path))
        Path(path).write_text(json.dumps(data))

    monkeypatch.setattr(logger_mod, "atomic_write_json", _fake_atomic)
    config, path = cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    lg.stop()
    assert called and called[0].endswith("metadata.json")


# ---------------------------------------------------------------------------
# Fix round 1 — stop() metadata guard, drop-oldest locking (T1-011, T1-033)
# ---------------------------------------------------------------------------


def test_stop_closes_files_when_metadata_write_fails(cfg, monkeypatch):
    """A metadata-write failure must not skip _close_files() (Finding 1)."""
    from rover import logger as logger_mod

    def _boom(path, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(logger_mod, "atomic_write_json", _boom)
    config, path = cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    lg.write({"type": "event", "event": "x"})

    lg.stop()  # must not raise

    assert lg.degraded is True
    assert lg._scan_file is None or lg._scan_file.closed
    assert lg._gnss_file is None or lg._gnss_file.closed


def test_write_drop_only_counts_real_drops(cfg, monkeypatch):
    """A `queue.Empty` from the recovery `get_nowait()` means a concurrent
    `_flush()` already drained the queue for real — it must not be counted as
    a drop, and the record that triggered recovery must still be accepted
    (Finding 2). Simulated by forcing the fast-path `put_nowait()` to look
    full exactly once while the real queue is genuinely empty underneath —
    the same race the lock in `write()` is meant to survive."""
    config, path = cfg
    lg = SessionLogger(config, config_path=path)
    lg.start()
    try:
        assert lg._queue.empty()
        real_put_nowait = lg._queue.put_nowait
        calls = {"n": 0}

        def _full_once(item):
            calls["n"] += 1
            if calls["n"] == 1:
                raise queue.Full
            real_put_nowait(item)

        monkeypatch.setattr(lg._queue, "put_nowait", _full_once)

        lg.write({"type": "event", "event": "raced"})

        assert lg.dropped_records == 0
        assert lg._queue.qsize() == 1
        assert lg._queue.get_nowait()["event"] == "raced"
    finally:
        lg.stop()
