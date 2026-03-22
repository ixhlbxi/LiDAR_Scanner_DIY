# PiLiDAR-RTK Rover — Claude Code Project Prompt

## What This Is

A custom RTK-enabled LiDAR rover that combines a rotating LD19 LiDAR, Raspberry Pi HQ camera, MPU-9250 IMU, and ZED-F9P RTK GNSS receivers into a mobile 3D scanning platform targeting 5–10 cm point cloud accuracy. The monitoring console is a LILYGO T-Deck (ESP32-S3 + LoRa).

**Architecture is frozen at v0.9.2.** All planning, specs, and decisions are finalized. We are entering the coding phase.

---

## Project Status

| What | Status |
|------|--------|
| Planning & specs | ✅ Complete — 6 docs, 29 engineering decisions (D-001 through D-029) |
| Hardware in hand | LD19 LiDAR, MPU-9250 IMU, A4988 stepper driver, NEMA 17 motor, Pi HQ Camera, Raspberry Pi 4B, ESP32 LoRa boards, T-Deck |
| Hardware NOT in hand | 2× ZED-F9P modules, 2× dual-band GNSS antennas, 3.3V regulator, batteries |
| 3D printer | ✅ Operational (Ender 3 Pro, Sprite direct drive, CR Touch) |
| Git repo | ❌ Not yet created |
| Codebase | ❌ Nothing written yet |
| Current phase | Phase 3 entry — Rover Software Core |

---

## Target Platform

- **OS:** Raspberry Pi OS Lite 64-bit (Bookworm) — decision D-020
- **Python:** 3.11+ (system Python on Bookworm)
- **GPIO library:** `rpi-lgpio` or `gpiozero` — NOT `RPi.GPIO` (broken on Bookworm; see D-029)
- **Config format:** TOML (stdlib `tomllib` for reading; `tomli-w` only if writing needed)

---

## Repo Structure (To Be Created)

```
pilidar-rtk/
├── README.md
├── LICENSE
├── pyproject.toml              # Project metadata, dependencies, entry points
├── config/
│   └── default.toml            # Default configuration (see schema below)
├── src/
│   └── rover/
│       ├── __init__.py
│       ├── main.py             # Orchestration, state machine
│       ├── config.py           # TOML parsing + validation
│       ├── lidar.py            # LD19 acquisition + packet parsing
│       ├── imu.py              # MPU-9250 polling + Madgwick fusion
│       ├── gnss.py             # ZED-F9P parsing (NMEA/UBX)
│       ├── stepper.py          # Motor control, step timing (rpi-lgpio)
│       ├── camera.py           # HQ Camera capture (picamera2)
│       ├── telemetry.py        # Status packet generation → ESP32
│       ├── logger.py           # JSONL file writing
│       └── watchdog.py         # Health monitoring, restart
├── tests/
│   ├── test_config.py          # Unit tests (runs anywhere)
│   ├── test_lidar.py           # Hardware test script (requires LD19)
│   ├── test_imu.py             # Hardware test script (requires MPU-9250)
│   ├── test_stepper.py         # Hardware test script (requires A4988 + motor)
│   ├── test_camera.py          # Hardware test script (requires Pi HQ Camera)
│   └── conftest.py
├── scripts/
│   └── ...                     # Utility scripts, data export, etc.
├── data/                       # .gitignored; session output goes here
└── docs/
    ├── ARCHITECTURE.md
    ├── DECISIONS.md
    ├── HARDWARE.md
    ├── SPECIFICATIONS.md
    └── ROADMAP.md
```

---

## Immediate Coding Tasks (Priority Order)

### 1. `config.py` — TOML Parsing + Validation (Zero Hardware Dependency)

This is the foundation module. Everything else imports it.

**Requirements:**
- Parse TOML config using `tomllib` (Python 3.11+ stdlib)
- Validate all fields against expected types and ranges
- Provide typed access (dataclass or similar) — no raw dict passing
- Merge user config over defaults (missing keys fall back to defaults)
- `enabled` flag per sensor section — disabled sensors skip initialization
- Immutable after load (frozen dataclass or similar)
- Log effective config at startup
- Copy config to session directory at scan start

**Full TOML schema** (this is the authoritative spec):

```toml
# RTK LiDAR Rover Configuration — v1.0

[general]
device_name = "rover-01"
log_level = "INFO"                # DEBUG, INFO, WARNING, ERROR

[lidar]
enabled = true
port = "/dev/ttyUSB0"
baud = 230400                     # LD19 default
scan_rate_hz = 10                 # Target 5–10

[stepper]
enabled = true
steps_per_rev = 3200              # With 1/16 microstepping
rpm = 1.0
step_interval_deg = 1.5           # Degrees per rotation step
direction_pin = 17                # BCM GPIO
step_pin = 27                     # BCM GPIO
enable_pin = 22                   # BCM GPIO (active low)

[imu]
enabled = true
bus = 1                           # I2C bus number
address = 0x68                    # MPU-9250 (or 0x69 if AD0 high)
sample_rate_hz = 200
fusion_output_hz = 100            # Madgwick output rate
use_magnetometer = true           # Disable during motor operation (D-013)
fusion_beta = 0.1                 # Madgwick filter gain

[gnss]
enabled = true
port = "/dev/ttyACM0"
baud = 115200
rtcm_profile = "robust"          # "robust" or "low_bandwidth"
survey_in_duration_sec = 300
survey_in_accuracy_m = 0.02

[lora]
enabled = true
port = "/dev/ttyUSB1"             # ESP32 serial
baud = 115200
spreading_factor = 9
bandwidth_khz = 125
coding_rate = "4/5"
telemetry_interval_sec = 1.0

[camera]
enabled = true
resolution = [1920, 1080]
capture_cadence = 1               # Every N steps (1 = every step)
jpeg_quality = 85
output_folder = "images"

[logging]
output_dir = "/home/pi/rover/data"
session_prefix = "scan"
format = "jsonl"
flush_interval_sec = 5.0
rotate_size_mb = 100              # 0 = no rotate
save_images = true

[watchdog]
enabled = true
timeout_sec = 30
heartbeat_interval_sec = 5

[power]
monitor_battery = true
battery_adc_channel = 0
low_battery_mv = 10500
critical_battery_mv = 10000
```

### 2. Git Repo + Project Structure

- Initialize with structure shown above
- `pyproject.toml` with dependencies, `[project.scripts]` entry point
- `.gitignore` (data/, __pycache__/, *.egg-info, .venv/, etc.)
- Placeholder `__init__.py` files with version string

### 3. `logger.py` — JSONL Output (Zero Hardware Dependency)

**Requirements:**
- Write JSONL records (one JSON object per line) to session files
- Create session directory: `{output_dir}/{prefix}_{YYYYMMDD}_{HHMMSS}/`
- Copy active config to session directory on start
- Periodic flush (configurable interval)
- File rotation by size (configurable)
- Write `metadata.json` on session close

**Session directory structure:**
```
/home/pi/rover/data/
└── scan_20260222_143052/
    ├── config.toml
    ├── scan.jsonl
    ├── gnss.jsonl              # Optional GNSS-only log
    ├── images/
    │   ├── img_000001.jpg
    │   └── ...
    └── metadata.json
```

**JSONL record types** (each line has a `type` field):

| type | Fields | Notes |
|------|--------|-------|
| `lidar` | timestamp, step_index, points[{angle, distance, intensity}] | angles in degrees, distance in meters |
| `imu` | timestamp, accel[3], gyro[3], mag[3], orientation[4] | quaternion = [w,x,y,z], mag null if disabled |
| `gnss` | timestamp, fix_type, lat, lon, alt, hdop, vdop, sat_count, rtk_age | fix_type: 0=NONE..5=FIX |
| `camera` | timestamp, step_index, filename | relative path |
| `event` | timestamp, event, details{} | scan_start, scan_complete, error, etc. |

### 4. Sensor Test Scripts (Hardware Required — Run on Pi)

Individual test scripts to validate each sensor in isolation. These are diagnostic tools, not unit tests.

**`test_lidar.py` — LD19 LiDAR**
- Open serial port at 230400 baud
- Parse LD19 packet stream (header 0x54, 12 measurement points per packet)
- Print scan rate, point count, min/max distance
- Run for N seconds then exit with summary
- LD19 protocol: each packet = 1 byte header (0x54) + 1 byte ver_len + 2 byte speed + 2 byte start_angle + 12×(2 byte distance + 1 byte intensity) + 2 byte end_angle + 2 byte timestamp + 1 byte CRC

**`test_imu.py` — MPU-9250**
- Open I2C bus 1, address 0x68
- Read WHO_AM_I register (expect 0x71 for MPU-9250, 0x73 for MPU-9255)
- Stream accel + gyro at configured rate
- Print orientation estimate (basic, no fusion needed for test)
- Magnetometer: read AK8963 via I2C bypass (address 0x0C)

**`test_stepper.py` — A4988 + NEMA 17**
- Use `rpi-lgpio` for GPIO (D-029)
- BCM pins: DIR=17, STEP=27, ENABLE=22 (active low)
- Rotate N degrees at configured speed, then reverse
- Print step count, timing accuracy
- Cleanly disable motor on exit (set ENABLE high)

**`test_camera.py` — Pi HQ Camera**
- Use `picamera2` library
- Capture single frame, save as JPEG
- Print resolution, file size, capture latency
- Test burst mode (N frames)

### 5. Module Stubs

Create well-documented stubs for remaining modules so the import graph works:
- `lidar.py`, `imu.py`, `gnss.py`, `stepper.py`, `camera.py`
- `telemetry.py`, `watchdog.py`, `main.py`
- Each stub: docstring explaining purpose, placeholder class with `__init__` and `start()`/`stop()` methods, `NotImplementedError` for unfinished methods

---

## Key Engineering Decisions (Reference)

These are settled. Don't revisit unless I flag a specific issue.

| ID | Decision | Summary |
|----|----------|---------|
| D-005 | LD19 LiDAR | Cost-effective, 4500 pts/sec, 12m range, USB-serial |
| D-007 | RTCM routing | ESP32 direct-to-F9P UART2 (bypasses Pi for latency) |
| D-012 | Madgwick filter | Lighter than EKF, adequate for scan-rate fusion |
| D-013 | Mag disabled w/ motor | Stepper EMI corrupts magnetometer; disable during rotation |
| D-014 | Timestamp sync | Ring buffer + bracket lookup + slerp interpolation |
| D-018 | Power domains | 5V compute / 12V motor / 3.3V logic — separate regulators |
| D-020 | Pi OS Lite 64-bit | Headless Bookworm, Python 3.11+ |
| D-021 | TOML config | stdlib `tomllib`, human-readable, per-section `enabled` flags |
| D-028 | TOML over YAML/JSON | No external deps, comment support, type-safe |
| D-029 | rpi-lgpio over RPi.GPIO | RPi.GPIO broken on Bookworm; rpi-lgpio is drop-in replacement |

---

## GPIO Pinout (BCM)

| GPIO | Function | Direction | Notes |
|------|----------|-----------|-------|
| 17 | Stepper DIR | Output | Direction control |
| 27 | Stepper STEP | Output | Step pulse |
| 22 | Stepper ENABLE | Output | Active low |
| 2 (SDA) | I2C Data | Bidir | IMU (MPU-9250) |
| 3 (SCL) | I2C Clock | Output | IMU (MPU-9250) |

## Serial Ports

| Port | Device | Baud | Purpose |
|------|--------|------|---------|
| /dev/ttyACM0 | ZED-F9P | 115200 | GNSS (NMEA/UBX) |
| /dev/ttyUSB0 | LD19 LiDAR | 230400 | Scan data |
| /dev/ttyUSB1 | ESP32 LoRa | 115200 | Telemetry |

---

## Coordinate Frames

| Frame | Origin | X | Y | Z |
|-------|--------|---|---|---|
| LiDAR | LD19 optical center | Forward | Left | Up |
| IMU | MPU-9250 center | Forward | Left | Up |
| Body | Rover center | Forward | Left | Up |
| GNSS | Antenna phase center | — | — | — |
| Local ENU | Session start position | East | North | Up |

- Quaternion convention: scalar-first [w, x, y, z]
- Transform notation: `T_A_B` = transform from frame B to frame A

---

## Coding Standards

- **Python 3.11+**, type hints on all public APIs
- **Formatting:** `ruff` (or `black` + `isort`)
- **Testing:** `pytest`; unit tests run off-Pi, hardware tests require the device
- **Logging:** stdlib `logging`; configured from `config.toml [general] log_level`
- **Error handling:** Sensors that fail to init should log and continue (if `enabled = true` but hardware absent, warn and mark unavailable — don't crash the system)
- **Concurrency:** Not decided yet. Start with sequential single-threaded design in stubs. We'll evaluate `asyncio` vs `threading` vs event loop when integrating.
- **Dependencies:** Prefer stdlib. Non-stdlib deps must be declared in `pyproject.toml`. Current expected external deps:
  - `rpi-lgpio` (GPIO)
  - `picamera2` (camera)
  - `smbus2` (I2C)
  - `pyserial` (serial ports)
  - `tomli-w` (only if config writing needed)
- **Scripts >50 lines:** Top-of-file header with purpose, dependencies, usage, changelog
- **Scripts <50 lines:** Minimal inline comments

---

## What's NOT in Scope Right Now

- ESP32 firmware (Phase 3, later)
- RTCM / LoRa integration (blocked on ZED-F9P hardware)
- Point cloud processing / 3D reconstruction (Phase 5)
- Monitoring console UI (Phase 4)
- Enclosure CAD (Phase 2, separate track)

---

## How to Work With Me

- I'm the project owner. Challenge assumptions and flag risks — I want peer review, not yes-man output.
- Ask before writing to disk or making structural decisions I haven't specified.
- If something in the specs seems wrong or underspecified, say so.
- Prefer showing me a plan before generating 500 lines of code.
- Default to minimal output. Skip auxiliary files unless I ask for them.
