"""Unit tests for rover.telemetry — TelemetryRouter + StatusJsonPublisher +
LocalHttpPublisher. No hardware required.

See D-033 in docs/DECISIONS.md and §3 of docs/BASE_STATION_INTEGRATION.md.
"""

import json
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest

from rover.config import load_config
from rover.telemetry import (
    LocalHttpPublisher,
    LoRaPublisher,
    RoverStatus,
    StatusJsonPublisher,
    TelemetryRouter,
    atomic_write_json,
    status_from_config,
)


@pytest.fixture
def tmp_toml(tmp_path):
    def _write(content: str) -> Path:
        p = tmp_path / "test_config.toml"
        p.write_text(textwrap.dedent(content))
        return p

    return _write


# ---------------------------------------------------------------------------
# atomic_write_json — Base-Station-compatible helper
# ---------------------------------------------------------------------------


class TestAtomicWriteJson:
    def test_writes_file(self, tmp_path):
        target = tmp_path / "status.json"
        atomic_write_json(target, {"foo": "bar"})
        assert target.exists()

    def test_content_parseable_as_json(self, tmp_path):
        target = tmp_path / "status.json"
        atomic_write_json(target, {"a": 1, "b": [1, 2, 3]})
        loaded = json.loads(target.read_text())
        assert loaded == {"a": 1, "b": [1, 2, 3]}

    def test_creates_parent_directories(self, tmp_path):
        target = tmp_path / "nested" / "deep" / "status.json"
        atomic_write_json(target, {"ok": True})
        assert target.exists()

    def test_trailing_newline(self, tmp_path):
        """Mirror of Base-Station's helper, which always writes a trailing newline."""
        target = tmp_path / "status.json"
        atomic_write_json(target, {"x": 1})
        assert target.read_text().endswith("\n")

    def test_no_tmp_files_left_behind(self, tmp_path):
        target = tmp_path / "status.json"
        atomic_write_json(target, {"k": "v"})
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []


# ---------------------------------------------------------------------------
# StatusJsonPublisher (Channel A)
# ---------------------------------------------------------------------------


class TestStatusJsonPublisher:
    def _make_cfg(self, tmp_toml, status_path: Path, profile: str = "personal"):
        # Personal profile so no cross-validation rules kick in
        return load_config(
            tmp_toml(
                f"""
                [session]
                profile = "{profile}"

                [base_station_integration]
                enabled = true
                status_json_path = "{status_path.as_posix()}"
                """
            )
        )

    def test_writes_status_json(self, tmp_toml, tmp_path):
        status_path = tmp_path / "rover_status.json"
        cfg = self._make_cfg(tmp_toml, status_path)
        pub = StatusJsonPublisher(cfg)
        st = RoverStatus(fix_type=5, sat_count=18, hdop=0.85, battery_mv=11800)
        pub.publish(st)
        assert status_path.exists()

    def test_payload_shape_matches_contract(self, tmp_toml, tmp_path):
        """Schema required by docs/BASE_STATION_INTEGRATION.md §3.1."""
        status_path = tmp_path / "rover_status.json"
        cfg = self._make_cfg(tmp_toml, status_path)
        pub = StatusJsonPublisher(cfg)
        st = RoverStatus(
            fix_type=5,
            sat_count=18,
            hdop=0.85,
            battery_mv=11800,
            lat=40.7128,
            lon=-74.0060,
            alt_m=10.5,
            scan_state=1,
            rtk_age_s=1.2,
        )
        payload = pub.build_payload(st)
        required = {
            "schema_version", "timestamp_epoch", "device", "profile",
            "mission", "project_code", "scan_state", "fix_type",
            "sat_count", "hdop", "lat", "lon", "alt_m", "rtk_age_s",
            "battery_mv", "lora_link_rssi", "lora_link_snr",
            "ntrip_connected", "ntrip_bytes_per_sec",
        }
        assert required.issubset(set(payload.keys()))

    def test_schema_version_from_config(self, tmp_toml, tmp_path):
        status_path = tmp_path / "rover_status.json"
        cfg = self._make_cfg(tmp_toml, status_path)
        pub = StatusJsonPublisher(cfg)
        payload = pub.build_payload(RoverStatus())
        assert payload["schema_version"] == cfg.base_station_integration.status_schema_version

    def test_failure_does_not_raise(self, tmp_toml, tmp_path):
        """status.json write failures are warning-logged, not propagated."""
        # Point at a path inside an unwritable parent (use a file as a "directory")
        unwritable = tmp_path / "blocking_file"
        unwritable.write_text("not a dir")
        bad_status_path = unwritable / "status.json"
        cfg = self._make_cfg(tmp_toml, bad_status_path)
        pub = StatusJsonPublisher(cfg)
        # Should NOT raise — publishers are isolated
        pub.publish(RoverStatus())


# ---------------------------------------------------------------------------
# LocalHttpPublisher (Channel B)
# ---------------------------------------------------------------------------


class TestLocalHttpPublisher:
    def _make_cfg(self, tmp_toml, port: int):
        return load_config(
            tmp_toml(
                f"""
                [telemetry]
                http_enabled = true
                http_bind = "127.0.0.1"
                http_port = {port}
                """
            )
        )

    def _get_free_port(self) -> int:
        # Bind to port 0, get the OS-assigned port, close, hand it to the test
        import socket

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def test_serves_health(self, tmp_toml):
        port = self._get_free_port()
        cfg = self._make_cfg(tmp_toml, port)
        pub = LocalHttpPublisher(cfg)
        pub.start()
        try:
            time.sleep(0.05)  # give server a moment
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2.0) as resp:
                body = json.loads(resp.read())
            assert body["ok"] is True
            assert "uptime_s" in body
        finally:
            pub.stop()

    def test_serves_status(self, tmp_toml):
        port = self._get_free_port()
        cfg = self._make_cfg(tmp_toml, port)
        pub = LocalHttpPublisher(cfg)
        pub.start()
        try:
            time.sleep(0.05)
            pub.publish(RoverStatus(fix_type=5, sat_count=18, hdop=0.85))
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=2.0) as resp:
                body = json.loads(resp.read())
            assert body["fix_type"] == 5
            assert body["sat_count"] == 18
        finally:
            pub.stop()

    def test_404_for_unknown_route(self, tmp_toml):
        port = self._get_free_port()
        cfg = self._make_cfg(tmp_toml, port)
        pub = LocalHttpPublisher(cfg)
        pub.start()
        try:
            time.sleep(0.05)
            req = urllib.request.Request(f"http://127.0.0.1:{port}/nope")
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(req, timeout=2.0)
            assert excinfo.value.code == 404
        finally:
            pub.stop()


# ---------------------------------------------------------------------------
# LoRaPublisher (Channel C)
# ---------------------------------------------------------------------------


class TestLoRaPublisher:
    def test_publish_no_serial_does_not_raise(self, tmp_path):
        """When the serial port can't be opened, publisher disables itself silently."""
        # Default config — points at /dev/ttyUSB1 which won't exist on the test host
        cfg = load_config()
        pub = LoRaPublisher(cfg)
        pub.start()  # serial will fail to open; publisher logs and disables itself
        # publish should be a no-op, not raise
        pub.publish(RoverStatus(fix_type=5, sat_count=18, hdop=0.85, battery_mv=11800))
        pub.stop()

    def test_disabled_role_no_publish(self, tmp_toml):
        cfg = load_config(
            tmp_toml(
                """
                [lora]
                role = "disabled"
                """
            )
        )
        pub = LoRaPublisher(cfg)
        # Don't start — confirm publish is still safe to call
        pub.publish(RoverStatus())


# ---------------------------------------------------------------------------
# TelemetryRouter — channel composition
# ---------------------------------------------------------------------------


class TestTelemetryRouter:
    def test_no_channels_when_all_disabled(self, tmp_toml):
        cfg = load_config(
            tmp_toml(
                """
                [lora]
                role = "disabled"
                """
            )
        )
        router = TelemetryRouter(cfg)
        assert router.publishers == []

    def test_status_json_only_channel(self, tmp_toml, tmp_path):
        cfg = load_config(
            tmp_toml(
                f"""
                [lora]
                role = "disabled"

                [base_station_integration]
                enabled = true
                status_json_path = "{(tmp_path / 'status.json').as_posix()}"
                """
            )
        )
        router = TelemetryRouter(cfg)
        names = [p.name for p in router.publishers]
        assert names == ["status_json"]

    def test_default_config_has_lora_only(self):
        """Default config: lora.enabled=true, role=rtcm_rx+status_tx, others off."""
        cfg = load_config()
        router = TelemetryRouter(cfg)
        names = [p.name for p in router.publishers]
        assert names == ["lora"]

    def test_publish_isolates_failures(self, tmp_toml, tmp_path):
        """A publisher that raises must not prevent other publishers from running."""
        cfg = load_config(
            tmp_toml(
                f"""
                [lora]
                role = "disabled"

                [base_station_integration]
                enabled = true
                status_json_path = "{(tmp_path / 'status.json').as_posix()}"
                """
            )
        )
        router = TelemetryRouter(cfg)
        # Inject a publisher that always raises
        class _Bomb:
            name = "bomb"

            def start(self):
                pass

            def publish(self, status):
                raise RuntimeError("boom")

            def stop(self):
                pass

        router._publishers.insert(0, _Bomb())  # type: ignore[arg-type]
        # Must not raise — and status.json should still be written
        router.publish(RoverStatus(fix_type=5))
        target = tmp_path / "status.json"
        assert target.exists()


# ---------------------------------------------------------------------------
# status_from_config — convenience builder
# ---------------------------------------------------------------------------


class TestStatusFromConfig:
    def test_pulls_session_fields(self, tmp_toml):
        cfg = load_config(
            tmp_toml(
                """
                [general]
                device_name = "rover-42"

                [session]
                profile = "personal"
                mission_tag = "test"
                """
            )
        )
        st = status_from_config(cfg)
        assert st.device == "rover-42"
        assert st.profile == "personal"
        assert st.mission == "TEST"
