"""TOML configuration parsing and validation for PiLiDAR-RTK Rover.

Loads rover configuration from a TOML file, merges user values over built-in
defaults, validates all fields (type, range, enum membership), and returns
a hierarchy of frozen dataclasses.

Public API:
    load_config(path) -> RoverConfig

Dependencies:
    - tomllib (Python 3.11+ stdlib)

Usage:
    from rover.config import load_config, RoverConfig
    config = load_config(Path("config/default.toml"))
    print(config.lidar.port)

Changelog:
    0.1.0  2026-03-22  Initial implementation (Task 1, Phase 3)
"""

from __future__ import annotations

import copy
import logging
import tomllib
from dataclasses import asdict, dataclass, fields
from difflib import get_close_matches
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frozen dataclasses — one per TOML section
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeneralConfig:
    device_name: str
    log_level: str


@dataclass(frozen=True)
class SessionConfig:
    """Per-session mode + project metadata (DEC-030)."""

    profile: str
    project_code: str
    mission_tag: str
    target_crs_epsg: int
    units: str


@dataclass(frozen=True)
class NtripConfig:
    """NTRIP-over-IP RTK transport (DEC-031, DEC-032)."""

    enabled: bool
    client_location: str
    caster_host: str
    caster_port: int
    mountpoint: str
    username: str
    password_env: str
    gga_send_interval_sec: float


@dataclass(frozen=True)
class BaseStationIntegrationConfig:
    """status.json publisher targeting Base-Station-compatible consumers (DEC-033)."""

    enabled: bool
    status_json_path: str
    status_schema_version: int
    publish_interval_sec: float


@dataclass(frozen=True)
class TelemetryConfig:
    """Loopback HTTP status endpoint (DEC-033 channel B)."""

    http_enabled: bool
    http_bind: str
    http_port: int


@dataclass(frozen=True)
class LidarConfig:
    enabled: bool
    port: str
    baud: int
    scan_rate_hz: int


@dataclass(frozen=True)
class StepperConfig:
    enabled: bool
    steps_per_rev: int
    rpm: float
    step_interval_deg: float
    direction_pin: int
    step_pin: int
    enable_pin: int


@dataclass(frozen=True)
class ImuConfig:
    enabled: bool
    bus: int
    address: int
    sample_rate_hz: int
    fusion_output_hz: int
    use_magnetometer: bool
    fusion_beta: float


@dataclass(frozen=True)
class GnssConfig:
    enabled: bool
    port: str
    baud: int
    rtcm_profile: str
    survey_in_duration_sec: int
    survey_in_accuracy_m: float


@dataclass(frozen=True)
class LoraConfig:
    enabled: bool
    port: str
    baud: int
    spreading_factor: int
    bandwidth_khz: int
    coding_rate: str
    telemetry_interval_sec: float
    sync_word: int = 0x12
    role: str = "rtcm_rx+status_tx"


@dataclass(frozen=True)
class CameraConfig:
    enabled: bool
    resolution: tuple[int, int]
    capture_cadence: int
    jpeg_quality: int
    output_folder: str


@dataclass(frozen=True)
class LoggingConfig:
    output_dir: str
    session_prefix: str
    format: str
    flush_interval_sec: float
    rotate_size_mb: int
    save_images: bool


@dataclass(frozen=True)
class WatchdogConfig:
    enabled: bool
    timeout_sec: int
    heartbeat_interval_sec: int


@dataclass(frozen=True)
class PowerConfig:
    monitor_battery: bool
    battery_adc_channel: int
    low_battery_mv: int
    critical_battery_mv: int


@dataclass(frozen=True)
class CalibrationConfig:
    lidar_to_imu_translation: Optional[list[float]] = None
    lidar_to_imu_rotation: Optional[list[float]] = None
    imu_to_gnss_translation: Optional[list[float]] = None


@dataclass(frozen=True)
class RoverConfig:
    general: GeneralConfig
    session: SessionConfig
    lidar: LidarConfig
    stepper: StepperConfig
    imu: ImuConfig
    gnss: GnssConfig
    ntrip: NtripConfig
    lora: LoraConfig
    base_station_integration: BaseStationIntegrationConfig
    telemetry: TelemetryConfig
    camera: CameraConfig
    logging: LoggingConfig
    watchdog: WatchdogConfig
    power: PowerConfig
    calibration: CalibrationConfig

    def to_dict(self) -> dict:
        """Return a plain dict matching the TOML structure."""
        d = asdict(self)
        # Convert resolution tuple back to list for TOML compatibility
        d["camera"]["resolution"] = list(d["camera"]["resolution"])
        return d


# ---------------------------------------------------------------------------
# Built-in defaults (mirrors config/default.toml)
# ---------------------------------------------------------------------------

_DEFAULTS: dict = {
    "general": {
        "device_name": "rover-01",
        "log_level": "INFO",
    },
    "session": {
        "profile": "personal",
        "project_code": "",
        "mission_tag": "",
        "target_crs_epsg": 0,
        "units": "m",
    },
    "lidar": {
        "enabled": True,
        # Stable symlink from deploy/udev/99-rover-lidar.rules.
        # Pre-deploy fallback: /dev/ttyUSB0.
        "port": "/dev/rover-lidar",
        "baud": 230400,
        "scan_rate_hz": 10,
    },
    "stepper": {
        "enabled": True,
        "steps_per_rev": 3200,
        "rpm": 1.0,
        "step_interval_deg": 1.5,
        "direction_pin": 17,
        "step_pin": 27,
        "enable_pin": 22,
    },
    "imu": {
        "enabled": True,
        "bus": 1,
        "address": 0x68,
        "sample_rate_hz": 200,
        "fusion_output_hz": 100,
        "use_magnetometer": True,
        "fusion_beta": 0.1,
    },
    "gnss": {
        "enabled": True,
        # Stable symlink from deploy/udev/99-rover-f9p.rules.
        # Pre-deploy fallback: /dev/ttyACM0.
        "port": "/dev/rover-f9p",
        "baud": 115200,
        "rtcm_profile": "robust",
        "survey_in_duration_sec": 300,
        "survey_in_accuracy_m": 0.02,
    },
    "ntrip": {
        "enabled": False,
        "client_location": "pi",
        "caster_host": "rtk-base.local",
        "caster_port": 2101,
        "mountpoint": "ARM_BASE",
        "username": "rover",
        "password_env": "ROVER_NTRIP_PASSWORD",
        "gga_send_interval_sec": 10.0,
    },
    "lora": {
        "enabled": True,
        # Stable symlink from deploy/udev/99-rover-esp32.rules.
        # Pre-deploy fallback: /dev/ttyUSB1.
        "port": "/dev/rover-esp32",
        "baud": 115200,
        "spreading_factor": 7,
        "bandwidth_khz": 125,
        "coding_rate": "4/5",
        "telemetry_interval_sec": 1.0,
        "sync_word": 0x12,
        "role": "rtcm_rx+status_tx",
    },
    "base_station_integration": {
        "enabled": False,
        "status_json_path": "/run/rover/status.json",
        "status_schema_version": 1,
        "publish_interval_sec": 1.0,
    },
    "telemetry": {
        "http_enabled": False,
        "http_bind": "127.0.0.1",
        "http_port": 8090,
    },
    "camera": {
        "enabled": True,
        "resolution": [1920, 1080],
        "capture_cadence": 1,
        "jpeg_quality": 85,
        "output_folder": "images",
    },
    "logging": {
        "output_dir": "/home/pi/rover/data",
        "session_prefix": "scan",
        "format": "jsonl",
        "flush_interval_sec": 5.0,
        "rotate_size_mb": 100,
        "save_images": True,
    },
    "watchdog": {
        "enabled": True,
        "timeout_sec": 30,
        "heartbeat_interval_sec": 5,
    },
    "power": {
        "monitor_battery": True,
        "battery_adc_channel": 0,
        "low_battery_mv": 10500,
        "critical_battery_mv": 10000,
    },
    "calibration": {},
}

# ---------------------------------------------------------------------------
# Valid keys per section (for unknown-key detection)
# ---------------------------------------------------------------------------

_SECTION_DATACLASS: dict[str, type] = {
    "general": GeneralConfig,
    "session": SessionConfig,
    "lidar": LidarConfig,
    "stepper": StepperConfig,
    "imu": ImuConfig,
    "gnss": GnssConfig,
    "ntrip": NtripConfig,
    "lora": LoraConfig,
    "base_station_integration": BaseStationIntegrationConfig,
    "telemetry": TelemetryConfig,
    "camera": CameraConfig,
    "logging": LoggingConfig,
    "watchdog": WatchdogConfig,
    "power": PowerConfig,
    "calibration": CalibrationConfig,
}


def _valid_keys(section: str) -> set[str]:
    """Return the set of valid field names for a config section."""
    dc = _SECTION_DATACLASS[section]
    return {f.name for f in fields(dc)}


def _suggest(name: str, valid: set[str]) -> str:
    """Return a 'did you mean ...?' hint if a close match exists."""
    matches = get_close_matches(name, valid, n=1, cutoff=0.6)
    if matches:
        return f" Did you mean '{matches[0]}'?"
    return ""


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def _deep_merge(defaults: dict, overrides: dict) -> dict:
    """Recursively merge *overrides* over *defaults*. Returns a new dict."""
    merged = copy.deepcopy(defaults)
    for key, value in overrides.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _check_unknown_keys(raw: dict) -> None:
    """Raise ValueError for any unknown top-level section or key within a section."""
    valid_sections = set(_SECTION_DATACLASS.keys())
    for section in raw:
        if section not in valid_sections:
            hint = _suggest(section, valid_sections)
            raise ValueError(
                f"Unknown config section '[{section}]'.{hint}"
            )
        if isinstance(raw[section], dict):
            valid = _valid_keys(section)
            for key in raw[section]:
                if key not in valid:
                    hint = _suggest(key, valid)
                    raise ValueError(
                        f"Unknown key '{key}' in [{section}].{hint}"
                    )


def _validate(raw: dict) -> None:
    """Validate merged config dict. Raises ValueError on invalid values."""

    def _require_type(section: str, key: str, value, expected: type | tuple) -> None:
        if not isinstance(value, expected):
            raise ValueError(
                f"[{section}] {key}: expected {expected.__name__ if isinstance(expected, type) else expected}, "
                f"got {type(value).__name__} ({value!r})"
            )

    def _require_in(section: str, key: str, value, allowed: set) -> None:
        if value not in allowed:
            raise ValueError(
                f"[{section}] {key}: must be one of {sorted(allowed)}, got {value!r}"
            )

    def _require_range(section: str, key: str, value, lo, hi) -> None:
        if not (lo <= value <= hi):
            raise ValueError(
                f"[{section}] {key}: must be in [{lo}, {hi}], got {value}"
            )

    def _require_positive(section: str, key: str, value) -> None:
        if value <= 0:
            raise ValueError(f"[{section}] {key}: must be positive, got {value}")

    # -- general --
    g = raw["general"]
    _require_type("general", "device_name", g["device_name"], str)
    _require_type("general", "log_level", g["log_level"], str)
    _require_in("general", "log_level", g["log_level"].upper(),
                {"DEBUG", "INFO", "WARNING", "ERROR"})
    # Normalize to uppercase
    g["log_level"] = g["log_level"].upper()

    # -- session (DEC-030) --
    se = raw["session"]
    _require_type("session", "profile", se["profile"], str)
    _require_in("session", "profile", se["profile"], {"personal", "arm_group"})
    _require_type("session", "project_code", se["project_code"], str)
    _require_type("session", "mission_tag", se["mission_tag"], str)
    se["mission_tag"] = se["mission_tag"].upper()
    _require_type("session", "target_crs_epsg", se["target_crs_epsg"], int)
    if se["target_crs_epsg"] < 0:
        raise ValueError(
            f"[session] target_crs_epsg: must be >= 0 (0 = WGS84/no conversion), "
            f"got {se['target_crs_epsg']}"
        )
    _require_type("session", "units", se["units"], str)
    _require_in("session", "units", se["units"], {"m", "ft"})

    # -- lidar --
    li = raw["lidar"]
    _require_type("lidar", "enabled", li["enabled"], bool)
    _require_type("lidar", "port", li["port"], str)
    _require_type("lidar", "baud", li["baud"], int)
    _require_positive("lidar", "baud", li["baud"])
    _require_type("lidar", "scan_rate_hz", li["scan_rate_hz"], int)
    _require_range("lidar", "scan_rate_hz", li["scan_rate_hz"], 1, 20)

    # -- stepper --
    st = raw["stepper"]
    _require_type("stepper", "enabled", st["enabled"], bool)
    _require_type("stepper", "steps_per_rev", st["steps_per_rev"], int)
    _require_positive("stepper", "steps_per_rev", st["steps_per_rev"])
    _require_type("stepper", "rpm", st["rpm"], (int, float))
    _require_positive("stepper", "rpm", st["rpm"])
    st["rpm"] = float(st["rpm"])
    _require_type("stepper", "step_interval_deg", st["step_interval_deg"], (int, float))
    _require_positive("stepper", "step_interval_deg", st["step_interval_deg"])
    st["step_interval_deg"] = float(st["step_interval_deg"])
    for pin_key in ("direction_pin", "step_pin", "enable_pin"):
        _require_type("stepper", pin_key, st[pin_key], int)
        _require_range("stepper", pin_key, st[pin_key], 0, 27)

    # -- imu --
    im = raw["imu"]
    _require_type("imu", "enabled", im["enabled"], bool)
    _require_type("imu", "bus", im["bus"], int)
    # Address: accept int or hex string
    addr = im["address"]
    if isinstance(addr, str):
        try:
            im["address"] = int(addr, 0)
        except (ValueError, TypeError):
            raise ValueError(
                f"[imu] address: cannot parse {addr!r} as integer"
            )
    _require_type("imu", "address", im["address"], int)
    _require_type("imu", "sample_rate_hz", im["sample_rate_hz"], int)
    _require_positive("imu", "sample_rate_hz", im["sample_rate_hz"])
    _require_type("imu", "fusion_output_hz", im["fusion_output_hz"], int)
    _require_positive("imu", "fusion_output_hz", im["fusion_output_hz"])
    _require_type("imu", "use_magnetometer", im["use_magnetometer"], bool)
    _require_type("imu", "fusion_beta", im["fusion_beta"], (int, float))
    _require_range("imu", "fusion_beta", im["fusion_beta"], 0.0, 1.0)
    im["fusion_beta"] = float(im["fusion_beta"])

    # -- gnss --
    gn = raw["gnss"]
    _require_type("gnss", "enabled", gn["enabled"], bool)
    _require_type("gnss", "port", gn["port"], str)
    _require_type("gnss", "baud", gn["baud"], int)
    _require_positive("gnss", "baud", gn["baud"])
    _require_type("gnss", "rtcm_profile", gn["rtcm_profile"], str)
    _require_in("gnss", "rtcm_profile", gn["rtcm_profile"], {"robust", "low_bandwidth"})
    _require_type("gnss", "survey_in_duration_sec", gn["survey_in_duration_sec"], int)
    _require_positive("gnss", "survey_in_duration_sec", gn["survey_in_duration_sec"])
    _require_type("gnss", "survey_in_accuracy_m", gn["survey_in_accuracy_m"], (int, float))
    _require_positive("gnss", "survey_in_accuracy_m", gn["survey_in_accuracy_m"])
    gn["survey_in_accuracy_m"] = float(gn["survey_in_accuracy_m"])

    # -- ntrip (DEC-031, DEC-032) --
    nt = raw["ntrip"]
    _require_type("ntrip", "enabled", nt["enabled"], bool)
    _require_type("ntrip", "client_location", nt["client_location"], str)
    _require_in("ntrip", "client_location", nt["client_location"], {"pi", "esp32"})
    _require_type("ntrip", "caster_host", nt["caster_host"], str)
    _require_type("ntrip", "caster_port", nt["caster_port"], int)
    _require_range("ntrip", "caster_port", nt["caster_port"], 1, 65535)
    _require_type("ntrip", "mountpoint", nt["mountpoint"], str)
    _require_type("ntrip", "username", nt["username"], str)
    _require_type("ntrip", "password_env", nt["password_env"], str)
    _require_type("ntrip", "gga_send_interval_sec", nt["gga_send_interval_sec"], (int, float))
    if nt["gga_send_interval_sec"] < 0:
        raise ValueError(
            f"[ntrip] gga_send_interval_sec: must be >= 0 (0 = never), "
            f"got {nt['gga_send_interval_sec']}"
        )
    nt["gga_send_interval_sec"] = float(nt["gga_send_interval_sec"])

    # -- lora --
    lo = raw["lora"]
    _require_type("lora", "enabled", lo["enabled"], bool)
    _require_type("lora", "port", lo["port"], str)
    _require_type("lora", "baud", lo["baud"], int)
    _require_positive("lora", "baud", lo["baud"])
    _require_type("lora", "spreading_factor", lo["spreading_factor"], int)
    _require_range("lora", "spreading_factor", lo["spreading_factor"], 7, 12)
    _require_type("lora", "bandwidth_khz", lo["bandwidth_khz"], int)
    _require_in("lora", "bandwidth_khz", lo["bandwidth_khz"], {125, 250, 500})
    _require_type("lora", "coding_rate", lo["coding_rate"], str)
    _require_in("lora", "coding_rate", lo["coding_rate"], {"4/5", "4/6", "4/7", "4/8"})
    _require_type("lora", "telemetry_interval_sec", lo["telemetry_interval_sec"], (int, float))
    _require_positive("lora", "telemetry_interval_sec", lo["telemetry_interval_sec"])
    lo["telemetry_interval_sec"] = float(lo["telemetry_interval_sec"])
    _require_type("lora", "sync_word", lo["sync_word"], int)
    _require_range("lora", "sync_word", lo["sync_word"], 0, 0xFF)
    _require_type("lora", "role", lo["role"], str)
    _require_in("lora", "role", lo["role"], {"rtcm_rx+status_tx", "status_tx_only", "disabled"})

    # -- base_station_integration (DEC-033 channel A) --
    bsi = raw["base_station_integration"]
    _require_type("base_station_integration", "enabled", bsi["enabled"], bool)
    _require_type("base_station_integration", "status_json_path", bsi["status_json_path"], str)
    _require_type("base_station_integration", "status_schema_version", bsi["status_schema_version"], int)
    _require_positive("base_station_integration", "status_schema_version", bsi["status_schema_version"])
    _require_type("base_station_integration", "publish_interval_sec", bsi["publish_interval_sec"], (int, float))
    _require_positive("base_station_integration", "publish_interval_sec", bsi["publish_interval_sec"])
    bsi["publish_interval_sec"] = float(bsi["publish_interval_sec"])

    # -- telemetry (DEC-033 channel B) --
    tm = raw["telemetry"]
    _require_type("telemetry", "http_enabled", tm["http_enabled"], bool)
    _require_type("telemetry", "http_bind", tm["http_bind"], str)
    _require_type("telemetry", "http_port", tm["http_port"], int)
    _require_range("telemetry", "http_port", tm["http_port"], 1, 65535)

    # -- camera --
    ca = raw["camera"]
    _require_type("camera", "enabled", ca["enabled"], bool)
    res = ca["resolution"]
    if not isinstance(res, (list, tuple)) or len(res) != 2:
        raise ValueError(
            f"[camera] resolution: must be [width, height], got {res!r}"
        )
    if not all(isinstance(v, int) and v > 0 for v in res):
        raise ValueError(
            f"[camera] resolution: both values must be positive integers, got {res!r}"
        )
    _require_type("camera", "capture_cadence", ca["capture_cadence"], int)
    _require_positive("camera", "capture_cadence", ca["capture_cadence"])
    _require_type("camera", "jpeg_quality", ca["jpeg_quality"], int)
    _require_range("camera", "jpeg_quality", ca["jpeg_quality"], 1, 100)
    _require_type("camera", "output_folder", ca["output_folder"], str)

    # -- logging --
    lg = raw["logging"]
    _require_type("logging", "output_dir", lg["output_dir"], str)
    _require_type("logging", "session_prefix", lg["session_prefix"], str)
    _require_type("logging", "format", lg["format"], str)
    _require_in("logging", "format", lg["format"], {"jsonl", "csv"})
    _require_type("logging", "flush_interval_sec", lg["flush_interval_sec"], (int, float))
    _require_positive("logging", "flush_interval_sec", lg["flush_interval_sec"])
    lg["flush_interval_sec"] = float(lg["flush_interval_sec"])
    _require_type("logging", "rotate_size_mb", lg["rotate_size_mb"], int)
    if lg["rotate_size_mb"] < 0:
        raise ValueError(
            f"[logging] rotate_size_mb: must be >= 0, got {lg['rotate_size_mb']}"
        )
    _require_type("logging", "save_images", lg["save_images"], bool)

    # -- watchdog --
    wd = raw["watchdog"]
    _require_type("watchdog", "enabled", wd["enabled"], bool)
    _require_type("watchdog", "timeout_sec", wd["timeout_sec"], int)
    _require_positive("watchdog", "timeout_sec", wd["timeout_sec"])
    _require_type("watchdog", "heartbeat_interval_sec", wd["heartbeat_interval_sec"], int)
    _require_positive("watchdog", "heartbeat_interval_sec", wd["heartbeat_interval_sec"])

    # -- power --
    pw = raw["power"]
    _require_type("power", "monitor_battery", pw["monitor_battery"], bool)
    _require_type("power", "battery_adc_channel", pw["battery_adc_channel"], int)
    if pw["battery_adc_channel"] < 0:
        raise ValueError(
            f"[power] battery_adc_channel: must be >= 0, got {pw['battery_adc_channel']}"
        )
    _require_type("power", "low_battery_mv", pw["low_battery_mv"], int)
    _require_positive("power", "low_battery_mv", pw["low_battery_mv"])
    _require_type("power", "critical_battery_mv", pw["critical_battery_mv"], int)
    _require_positive("power", "critical_battery_mv", pw["critical_battery_mv"])
    if pw["critical_battery_mv"] >= pw["low_battery_mv"]:
        raise ValueError(
            f"[power] critical_battery_mv ({pw['critical_battery_mv']}) "
            f"must be less than low_battery_mv ({pw['low_battery_mv']})"
        )

    # -- cross-section: arm_group profile constraints (DEC-030) --
    if se["profile"] == "arm_group":
        if not se["project_code"]:
            raise ValueError(
                "[session] profile = 'arm_group' requires a non-empty project_code"
            )
        if se["target_crs_epsg"] == 0:
            raise ValueError(
                "[session] profile = 'arm_group' requires target_crs_epsg > 0 "
                "(e.g. 6346 = NAD83(2011) PA-N ft-US)"
            )
        if not bsi["enabled"]:
            raise ValueError(
                "[session] profile = 'arm_group' requires [base_station_integration].enabled = true"
            )
        if not nt["enabled"]:
            raise ValueError(
                "[session] profile = 'arm_group' requires [ntrip].enabled = true"
            )

    # -- calibration (all optional) --
    cal = raw.get("calibration", {})
    for key in ("lidar_to_imu_translation", "imu_to_gnss_translation"):
        if key in cal and cal[key] is not None:
            v = cal[key]
            if not isinstance(v, list) or len(v) != 3:
                raise ValueError(
                    f"[calibration] {key}: must be [x, y, z] (3 floats), got {v!r}"
                )
            if not all(isinstance(x, (int, float)) for x in v):
                raise ValueError(
                    f"[calibration] {key}: all values must be numeric, got {v!r}"
                )
    if "lidar_to_imu_rotation" in cal and cal["lidar_to_imu_rotation"] is not None:
        v = cal["lidar_to_imu_rotation"]
        if not isinstance(v, list) or len(v) != 4:
            raise ValueError(
                f"[calibration] lidar_to_imu_rotation: must be [w, x, y, z] (4 floats), got {v!r}"
            )
        if not all(isinstance(x, (int, float)) for x in v):
            raise ValueError(
                f"[calibration] lidar_to_imu_rotation: all values must be numeric, got {v!r}"
            )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _build_config(raw: dict) -> RoverConfig:
    """Construct frozen dataclass hierarchy from validated dict."""
    cal_raw = raw.get("calibration", {})
    return RoverConfig(
        general=GeneralConfig(**raw["general"]),
        session=SessionConfig(**raw["session"]),
        lidar=LidarConfig(**raw["lidar"]),
        stepper=StepperConfig(**raw["stepper"]),
        imu=ImuConfig(**raw["imu"]),
        gnss=GnssConfig(**raw["gnss"]),
        ntrip=NtripConfig(**raw["ntrip"]),
        lora=LoraConfig(**raw["lora"]),
        base_station_integration=BaseStationIntegrationConfig(**raw["base_station_integration"]),
        telemetry=TelemetryConfig(**raw["telemetry"]),
        camera=CameraConfig(
            enabled=raw["camera"]["enabled"],
            resolution=tuple(raw["camera"]["resolution"]),
            capture_cadence=raw["camera"]["capture_cadence"],
            jpeg_quality=raw["camera"]["jpeg_quality"],
            output_folder=raw["camera"]["output_folder"],
        ),
        logging=LoggingConfig(**raw["logging"]),
        watchdog=WatchdogConfig(**raw["watchdog"]),
        power=PowerConfig(**raw["power"]),
        calibration=CalibrationConfig(
            lidar_to_imu_translation=cal_raw.get("lidar_to_imu_translation"),
            lidar_to_imu_rotation=cal_raw.get("lidar_to_imu_rotation"),
            imu_to_gnss_translation=cal_raw.get("imu_to_gnss_translation"),
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(path: Path | None = None) -> RoverConfig:
    """Load, merge, validate, and return rover configuration.

    Args:
        path: Path to a user TOML config file. If None, returns defaults only.

    Returns:
        Frozen RoverConfig instance.

    Raises:
        FileNotFoundError: If path is given but does not exist.
        ValueError: If config contains invalid values or unknown keys.
        tomllib.TOMLDecodeError: If the TOML file is malformed.
    """
    if path is not None:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path, "rb") as f:
            user_raw = tomllib.load(f)
        _check_unknown_keys(user_raw)
        merged = _deep_merge(_DEFAULTS, user_raw)
    else:
        merged = copy.deepcopy(_DEFAULTS)

    _validate(merged)
    config = _build_config(merged)

    logger.info("Effective configuration loaded: %s", config.to_dict())
    return config
