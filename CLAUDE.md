# PiLiDAR-RTK Rover — Claude Code Project Prompt

> **Architecture frozen at v0.9.2.** All planning, specs, and decisions are finalized.
> We are entering the coding phase. Do not re-litigate architecture choices unless
> a specific implementation issue requires it — flag the conflict instead.

---

## Table of Contents

1. [What This Is](#1-what-this-is)
2. [Project Status](#2-project-status)
3. [Target Platform](#3-target-platform)
4. [Repository Structure](#4-repository-structure-to-be-created)
5. [Immediate Coding Tasks](#5-immediate-coding-tasks-priority-order)
6. [Coding Standards](#6-coding-standards)
7. [Key Engineering Decisions](#7-key-engineering-decisions-reference)
8. [GPIO Pinout & Serial Ports](#8-gpio-pinout--serial-ports)
9. [Coordinate Frames](#9-coordinate-frames)
10. [What's NOT in Scope Right Now](#10-whats-not-in-scope-right-now)
11. [How to Work With Me](#11-how-to-work-with-me)
12. [Appendix A — Full TOML Config Schema](#appendix-a--full-toml-config-schema)
13. [Appendix B — JSONL Data Schema](#appendix-b--jsonl-data-schema)
14. [Appendix C — LoRa Packet Format (Full Spec)](#appendix-c--lora-packet-format-full-spec)
15. [Appendix D — All Engineering Decisions (D-001–D-029)](#appendix-d--all-engineering-decisions-d-001d-029)
16. [Appendix E — Performance Budgets](#appendix-e--performance-budgets)
17. [Appendix F — Failure Modes & Recovery](#appendix-f--failure-modes--recovery)
18. [Appendix G — System Architecture Summary](#appendix-g--system-architecture-summary)
19. [Appendix H — Development Roadmap](#appendix-h--development-roadmap)

---

## 1. What This Is

A custom RTK-enabled LiDAR rover combining:

- **LD19 LiDAR** on a rotating mast (NEMA17 + A4988 stepper) — stacked 2D slices → 3D point cloud
- **Raspberry Pi HQ Camera** with fisheye lens — visual context imagery per scan step
- **MPU-9250 IMU** — Madgwick fusion for roll/pitch/yaw orientation
- **ZED-F9P RTK GNSS** — centimeter-level positioning via LoRa-delivered RTCM corrections
- **ESP32 LoRa** — RTCM correction relay (base→rover) and telemetry (rover→monitor)
- **LILYGO T-Deck** — handheld field monitoring console (receive-only in v1.0)

**Target accuracy:** ±5–10 cm absolute point cloud (v1.0); ±2–3 cm with calibration (v1.1)
**Inspiration:** [PiLiDAR/PiLiDAR](https://github.com/PiLiDAR/PiLiDAR) (upstream, validated approach)

---

## 2. Project Status

| What | Status |
|------|--------|
| Planning & specs | ✅ Complete — 6 docs, 29 engineering decisions (D-001–D-029) |
| Hardware in hand | LD19 LiDAR, MPU-9250 IMU, A4988 stepper driver, NEMA 17 motor, Pi HQ Camera, Raspberry Pi 4B, ESP32 LoRa boards, T-Deck |
| Hardware NOT yet in hand | 2× ZED-F9P modules, 2× dual-band GNSS antennas, 3.3V switching regulator, batteries |
| 3D printer | ✅ Operational (Ender 3 Pro, Sprite direct drive, CR Touch) |
| Git repo | ❌ Not yet created |
| Codebase | ❌ Nothing written yet |
| Current phase | **Phase 3 entry — Rover Software Core** |

---

## 3. Target Platform

| Item | Value |
|------|-------|
| **Hardware** | Raspberry Pi 4B |
| **OS** | Raspberry Pi OS Lite 64-bit (Bookworm) |
| **Python** | 3.11+ (system Python on Bookworm) |
| **GPIO library** | `rpi-lgpio` or `gpiozero` — **NOT `RPi.GPIO`** (broken on Bookworm — see D-029) |
| **Config format** | TOML — stdlib `tomllib` for reading; `tomli-w` only if writing needed |
| **Data format** | JSONL (newline-delimited JSON) |
| **Expected deps** | `rpi-lgpio`, `picamera2`, `smbus2`, `pyserial` |

> **Critical note on GPIO:** `RPi.GPIO` raises `RuntimeError: Failed to add edge detection` on
> Bookworm because the sysfs GPIO interface was removed. Install `rpi-lgpio` via
> `pip install rpi-lgpio` or `sudo apt install python3-rpi-lgpio`. It is a drop-in API
> replacement. Set `LG_WD=/tmp` to avoid lgpio temp file clutter.

---

## 4. Repository Structure (To Be Created)

```
pilidar-rtk/
├── README.md
├── LICENSE
├── pyproject.toml              # Project metadata, dependencies, entry points
├── config/
│   └── default.toml            # Default configuration (see Appendix A)
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
│   ├── test_config.py          # Unit tests (runs anywhere, no hardware)
│   ├── test_logger.py          # Unit tests (runs anywhere, no hardware)
│   ├── conftest.py
│   └── hardware/               # Diagnostic scripts (run on Pi with hardware)
│       ├── test_lidar.py       # LD19 LiDAR diagnostic
│       ├── test_imu.py         # MPU-9250 IMU diagnostic
│       ├── test_stepper.py     # A4988 + NEMA 17 diagnostic
│       └── test_camera.py      # Pi HQ Camera diagnostic
├── scripts/
│   └── georef.py               # Post-processing: JSONL → georeferenced PLY (Phase 5)
├── data/                       # .gitignored; session output goes here
└── docs/
    ├── ARCHITECTURE.md
    ├── DECISIONS.md
    ├── HARDWARE.md
    ├── SPECIFICATIONS.md
    └── ROADMAP.md
```

---

## 5. Immediate Coding Tasks (Priority Order)

### Task 1 — `config.py`: TOML Parsing + Validation
**Zero hardware dependency. Foundation — everything else imports this.**

Requirements:
- Parse TOML using `tomllib` (Python 3.11+ stdlib — no external dep)
- Validate all fields against expected types and ranges; raise on invalid values
- Provide typed access via frozen dataclasses — no raw dict passing to other modules
- Merge user config over defaults (missing keys fall back to defaults)
- Each sensor section has an `enabled` flag — disabled sensors skip initialization entirely
- Immutable after load
- Log effective config at startup (INFO level)
- Copy config to session directory at scan start

Full schema: see **Appendix A**.

---

### Task 2 — Git Repo + Project Structure

- Initialize repo with structure from Section 4
- `pyproject.toml` with dependencies, `[project.scripts]` entry point for `rover`
- `.gitignore` covering: `data/`, `__pycache__/`, `*.egg-info`, `.venv/`, `*.pyc`, `.DS_Store`
- Placeholder `__init__.py` files with version string
- Stub `README.md`

---

### Task 3 — `logger.py`: JSONL Output
**Zero hardware dependency.**

Requirements:
- Write JSONL records (one JSON object per line) to session files
- Session directory: `{output_dir}/{prefix}_{YYYYMMDD_HHMMSS}/`
- Copy active config.toml to session directory on start
- Periodic flush (configurable interval, default 5 sec)
- File rotation by size (configurable, 0 = disabled)
- Thread-safe write queue (sensors run concurrently)
- Write `metadata.json` on session close

Session directory layout:
```
/home/pi/rover/data/
└── scan_20260222_143052/
    ├── config.toml             # Snapshot at session start
    ├── scan.jsonl              # Main sensor log (lidar, imu, camera, event records)
    ├── gnss.jsonl              # GNSS-only log (optional, for easier RTK analysis)
    ├── images/
    │   ├── img_000001.jpg
    │   └── ...
    └── metadata.json           # Session summary written on close
```

JSONL record types: see **Appendix B**.

---

### Task 4 — Sensor Test Scripts (Hardware Required — Run on Pi)

Diagnostic scripts to validate each sensor in isolation before integration.
These are field tools, not pytest unit tests. Located in `tests/hardware/`.

**`tests/hardware/test_lidar.py` — LD19 LiDAR**
- Open `/dev/ttyUSB0` at 230400 baud
- Parse LD19 packet stream
- LD19 packet format: `[0x54][ver_len:1][speed:2LE][start_angle:2LE][12×(dist:2LE + intensity:1)][end_angle:2LE][timestamp:2LE][CRC:1]` = 47 bytes total
- Print: scan rate (Hz), points per scan, min/max distance, packet CRC error rate
- Run for N seconds (CLI arg), then exit with summary

**`tests/hardware/test_imu.py` — MPU-9250**
- Open I2C bus 1, address 0x68 (or 0x69 if AD0 high)
- Read WHO_AM_I register (expect `0x71` for MPU-9250, `0x73` for MPU-9255)
- Stream accel [m/s²] + gyro [rad/s] at configured rate
- Magnetometer via AK8963 I2C bypass (address `0x0C`) — print µT values
- Print sample rate achieved vs. target

**`tests/hardware/test_stepper.py` — A4988 + NEMA 17**
- Use `rpi-lgpio` for GPIO (D-029) — BCM pins: DIR=17, STEP=27, ENABLE=22 (active low)
- Rotate N degrees at configured speed, then reverse
- Print: step count, timing accuracy (step jitter), current draw estimate
- Cleanly disable motor (ENABLE → high) on exit or Ctrl-C

**`tests/hardware/test_camera.py` — Pi HQ Camera**
- Use `picamera2`
- Capture single JPEG frame, save to `/tmp/test_capture.jpg`
- Print: resolution, file size, capture latency
- Optional burst test: N frames, report average latency

---

### Task 5 — Module Stubs

Create documented stubs for remaining modules so the import graph works cleanly
before hardware integration begins:

Modules: `lidar.py`, `imu.py`, `gnss.py`, `stepper.py`, `camera.py`, `telemetry.py`,
`watchdog.py`, `main.py`

Each stub must include:
- Module-level docstring: purpose, hardware interface, key dependencies
- Placeholder class with `__init__(self, config: RoverConfig)` signature
- `start()` and `stop()` methods (raise `NotImplementedError`)
- Type hints on all signatures
- Import of `config.py` types

---

## 6. Coding Standards

- **Python 3.11+**, type hints on all public APIs
- **Formatting:** `ruff` (preferred) or `black` + `isort`
- **Testing:** `pytest`; unit tests run off-Pi (mock hardware), hardware tests require the device
- **Logging:** stdlib `logging`; level set from `config.toml [general] log_level`
- **Error handling:** Sensors that fail to init should log a warning and mark themselves
  unavailable — **do not crash the system**. If `enabled = true` but hardware absent,
  warn and continue with that subsystem disabled.
- **Concurrency:** Not finalized. Start with sequential single-threaded design in stubs.
  Evaluate `asyncio` vs `threading` vs event loop during integration.
- **Scripts >50 lines:** Top-of-file header — purpose, context, dependencies, usage,
  flags/I/O, limitations, changelog (date + semver)
- **Scripts <50 lines:** Minimal inline comments only
- **Dependencies:** Prefer stdlib. All non-stdlib deps declared in `pyproject.toml`.

Expected external dependencies:

| Package | Purpose |
|---------|---------|
| `rpi-lgpio` | GPIO control (Bookworm-compatible) |
| `picamera2` | Pi HQ Camera capture |
| `smbus2` | I2C for MPU-9250 |
| `pyserial` | Serial ports (LD19, F9P, ESP32) |
| `tomli-w` | Config writing (only if needed) |

---

## 7. Key Engineering Decisions (Reference)

Settled — don't revisit unless a concrete implementation problem forces it.

| ID | Decision | Summary |
|----|----------|---------|
| D-003 | Pi as main controller | Linux ecosystem, Python libs, CSI camera, sufficient compute |
| D-005 | RTK via LoRa | No cellular dependency, works remote, ~1–2 sec latency |
| D-006 | RTCM routing — direct | ESP32 UART → F9P directly; Pi NOT in correction path |
| D-012 | Madgwick filter | Lighter than EKF, adequate for scan-rate orientation |
| D-013 | Mag disabled during motor | Stepper EMI corrupts magnetometer — disable during rotation |
| D-014 | Timestamp sync via slerp | Ring buffer + bracket lookup + quaternion slerp |
| D-018 | Split power domains | 5V compute / 12V motor — stepper transients isolated from Pi |
| D-019 | Dedicated 3.3V regulator | F9P + IMU from switching reg, NOT Pi GPIO 3.3V rail |
| D-020 | Python + Pi OS Lite 64-bit | Bookworm, Python 3.11+, headless |
| D-021 | JSONL logging | Append-only, crash-safe, human-readable, easy post-processing |
| D-022 | Post-processed georef | Georeferencing runs offline in Phase 5, not real-time |
| D-023 | SLAM deferred to v1.1+ | Out of scope for v1.0; indoor = relative mapping only |
| D-028 | TOML config | No external read deps, typed, comment-supporting |
| D-029 | `rpi-lgpio` over `RPi.GPIO` | `RPi.GPIO` broken on Bookworm; `rpi-lgpio` is drop-in |

Full decision log with rationale and alternatives: see **Appendix D**.

---

## 8. GPIO Pinout & Serial Ports

### GPIO (BCM Numbering)

| GPIO | Function | Direction | Notes |
|------|----------|-----------|-------|
| 17 | Stepper DIR | Output | Direction control |
| 27 | Stepper STEP | Output | Step pulse |
| 22 | Stepper ENABLE | Output | Active low — high = disabled |
| 2 (SDA) | I2C Data | Bidirectional | MPU-9250 IMU |
| 3 (SCL) | I2C Clock | Output | MPU-9250 IMU |

Pull-ups: 4.7 kΩ on SDA and SCL to 3.3V.

### Serial Ports

| Port | Device | Baud | Purpose |
|------|--------|------|---------|
| /dev/ttyACM0 | ZED-F9P | 115200 | GNSS data (NMEA/UBX) |
| /dev/ttyUSB0 | LD19 LiDAR | 230400 | Scan data |
| /dev/ttyUSB1 | ESP32 LoRa | 115200 | Telemetry Tx / commands Rx (future) |

### I2C Bus

| Address | Device | Notes |
|---------|--------|-------|
| 0x68 | MPU-9250 | Primary (AD0 low) |
| 0x69 | MPU-9250 | Alternate (AD0 high) |
| 0x0C | AK8963 (mag) | Accessed via I2C bypass mode |

### ESP32 LoRa (Rover) Pin Connections

| ESP32 Pin | Connected To | Purpose |
|-----------|-------------|---------|
| TX2 | ZED-F9P UART2 RX | RTCM forwarding (ESP32 → F9P, direct) |
| RX2 | (not connected) | F9P doesn't send to ESP32 |
| TX0/USB | Pi USB | Telemetry LINK packets to Pi |
| RX0/USB | Pi USB | Future commands from Pi |
| SPI | SX1262 radio | LoRa transceiver |

---

## 9. Coordinate Frames

| Frame | Origin | X | Y | Z |
|-------|--------|---|---|---|
| LiDAR | LD19 optical center | Forward | Left | Up |
| IMU | MPU-9250 center | Forward | Left | Up |
| Body | Rover geometric center | Forward | Left | Up |
| GNSS | Antenna phase center | — | — | — |
| Local ENU | Session start position | East | North | Up |
| WGS84 | Earth center | ECEF or Geodetic | | |

**Transform chain:**
```
LiDAR Frame
    │ T_lidar_imu  (static, calibration — TBD for v1.0)
IMU Frame
    │ T_imu_body   (static, mounting geometry)
Body Frame
    │ T_body_gnss  (static, antenna offset measurement)
GNSS Frame
    │ T_gnss_local (session origin)
Local ENU Frame
    │ T_local_global (standard geodetic)
Global WGS84
```

**Quaternion convention:** scalar-first `[w, x, y, z]`, right-handed system.
**Transform notation:** `T_A_B` = transform **from frame B to frame A**.

> Note: Extrinsic calibration (T_lidar_imu, T_body_gnss) is TBD for v1.0.
> Without it, accuracy is ±5–10 cm, not ±2–3 cm. Calibration procedure is v1.1.

---

## 10. What's NOT in Scope Right Now

| Out of Scope | Reason | Target |
|---|---|---|
| ESP32 firmware (RTCM relay + telemetry) | Blocked on F9P hardware | Phase 3 later |
| RTCM / LoRa integration | Blocked on ZED-F9P | Phase 2 |
| Point cloud processing / 3D reconstruction | Phase 5 | Later |
| Monitoring console (T-Deck) firmware | Phase 4 | Later |
| Enclosure CAD | Separate track | Phase 1–2 |
| Real-time SLAM | D-023 deferred | v1.1+ |
| Real-time georeferencing | D-022 deferred | v1.1+ |
| Camera texture mapping | D-026 deferred | v1.2+ |
| Extrinsic calibration procedure | D-024 accepted limitation | v1.1 |

---

## 11. How to Work With Me

- **I'm the project owner.** Challenge assumptions and flag risks — I want peer review, not agreement.
- **Show me a plan before generating 500 lines of code.** Especially for new modules.
- **Ask before making structural decisions** I haven't specified (file names, APIs, module boundaries).
- **If something in the specs seems wrong or underspecified, say so** — don't silently paper over it.
- **Default to minimal output.** Skip auxiliary files, summaries, and extra docs unless I ask.
- When in doubt: implement plans, not speculation. If the spec doesn't cover a case, flag it.

---

---

# APPENDICES — Reference Specifications

---

## Appendix A — Full TOML Config Schema

File location: `/home/pi/rover/config.toml`

```toml
# RTK LiDAR Rover Configuration
# Version: 1.0

[general]
device_name = "rover-01"          # Device identifier
log_level = "INFO"                # DEBUG, INFO, WARNING, ERROR

[lidar]
enabled = true
port = "/dev/ttyUSB0"             # Serial port (USB-serial adapter)
baud = 230400                     # LD19 default baud rate
scan_rate_hz = 10                 # Target scan rate (5–10)

[stepper]
enabled = true
steps_per_rev = 3200              # With 1/16 microstepping (D-017)
rpm = 1.0                         # Rotation speed
step_interval_deg = 1.5           # Degrees per step
direction_pin = 17                # BCM GPIO
step_pin = 27                     # BCM GPIO
enable_pin = 22                   # BCM GPIO (active low)

[imu]
enabled = true
bus = 1                           # I2C bus number
address = 0x68                    # MPU-9250 address (or 0x69)
sample_rate_hz = 200              # IMU polling rate
fusion_output_hz = 100            # Madgwick output rate
use_magnetometer = true           # Enable mag (disable during motor — D-013)
fusion_beta = 0.1                 # Madgwick filter gain

[gnss]
enabled = true
port = "/dev/ttyACM0"             # ZED-F9P USB port
baud = 115200                     # Default F9P baud
rtcm_profile = "robust"           # "robust" or "low_bandwidth"
survey_in_duration_sec = 300      # Base station survey-in time
survey_in_accuracy_m = 0.02       # Target accuracy (2 cm)

[lora]
enabled = true
port = "/dev/ttyUSB1"             # ESP32 serial port
baud = 115200
spreading_factor = 9              # 7–12
bandwidth_khz = 125               # 125, 250, or 500
coding_rate = "4/5"               # "4/5", "4/6", "4/7", "4/8"
telemetry_interval_sec = 1.0      # Status packet transmit rate

[camera]
enabled = true
resolution = [1920, 1080]         # Width × Height
capture_cadence = 1               # Capture every N steps (1 = every step)
jpeg_quality = 85                 # JPEG compression (1–100)
output_folder = "images"          # Relative to session folder

[logging]
output_dir = "/home/pi/rover/data"
session_prefix = "scan"           # Session folder prefix
format = "jsonl"                  # "jsonl" or "csv"
flush_interval_sec = 5.0          # Force flush interval
rotate_size_mb = 100              # Rotate log at this size (0 = no rotate)
save_images = true                # Save camera images

[watchdog]
enabled = true
timeout_sec = 30                  # Restart if no heartbeat
heartbeat_interval_sec = 5        # Internal heartbeat rate

[power]
monitor_battery = true
battery_adc_channel = 0           # ADC channel for voltage divider
low_battery_mv = 10500            # Warning threshold (mV)
critical_battery_mv = 10000       # Shutdown threshold (mV)

[calibration]
# Extrinsic calibration — TBD, measured during v1.1 calibration procedure
# lidar_to_imu_translation = [0.0, 0.0, 0.05]    # [x, y, z] meters
# lidar_to_imu_rotation = [1.0, 0.0, 0.0, 0.0]   # [w, x, y, z] quaternion
# imu_to_gnss_translation = [0.0, 0.0, 0.30]      # [x, y, z] meters
```

### RTCM Profiles

**Profile "robust" (default):**
Messages: 1005, 1077, 1087, 1097, 1127, 1230
Constellations: GPS, GLONASS, Galileo, BeiDou
Bandwidth: ~800–1000 bytes/sec

**Profile "low_bandwidth":**
Messages: 1005, 1077, 1087, 1230
Constellations: GPS, GLONASS
Bandwidth: ~500–600 bytes/sec

---

## Appendix B — JSONL Data Schema

Each line in `scan.jsonl` is a valid JSON object. The `type` field discriminates record type.

### Session Directory Structure

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

### Record: `lidar`

```json
{
  "type": "lidar",
  "timestamp": 1735226852.123456,
  "step_index": 47,
  "points": [
    {"angle": 0.0, "distance": 3.452, "intensity": 128},
    {"angle": 0.5, "distance": 3.461, "intensity": 131}
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| timestamp | float | Unix time, microsecond precision |
| step_index | int | Rotation step index (0 to N-1) |
| points[].angle | float | Degrees (0–360) |
| points[].distance | float | Meters |
| points[].intensity | int | 0–255 |

### Record: `imu`

```json
{
  "type": "imu",
  "timestamp": 1735226852.125000,
  "accel": [0.012, -0.008, 9.81],
  "gyro": [0.001, -0.002, 0.0005],
  "mag": [25.3, -12.1, 42.8],
  "orientation": [0.707, 0.0, 0.0, 0.707]
}
```

| Field | Type | Description |
|-------|------|-------------|
| accel | [float×3] | m/s² [x, y, z] |
| gyro | [float×3] | rad/s [x, y, z] |
| mag | [float×3] or null | µT [x, y, z]; null if magnetometer disabled (D-013) |
| orientation | [float×4] | Quaternion [w, x, y, z] from Madgwick fusion |

### Record: `gnss`

```json
{
  "type": "gnss",
  "timestamp": 1735226852.000000,
  "fix_type": 5,
  "lat": 40.7128,
  "lon": -74.0060,
  "alt": 10.5,
  "hdop": 0.85,
  "vdop": 1.2,
  "sat_count": 18,
  "rtk_age": 1.2
}
```

| fix_type | Meaning |
|---|---|
| 0 | NONE |
| 1 | 2D |
| 2 | 3D |
| 3 | DGPS |
| 4 | RTK FLOAT |
| 5 | RTK FIX |

### Record: `camera`

```json
{
  "type": "camera",
  "timestamp": 1735226852.130000,
  "step_index": 47,
  "filename": "images/img_000047.jpg"
}
```

### Record: `event`

```json
{
  "type": "event",
  "timestamp": 1735226850.000000,
  "event": "scan_start",
  "details": {"total_steps": 180}
}
```

**Event names:** `scan_start`, `scan_complete`, `scan_pause`, `scan_resume`, `scan_abort`,
`gnss_fix_acquired`, `gnss_fix_lost`, `low_battery`, `error`

### Session Metadata (`metadata.json`)

```json
{
  "session_id": "scan_20260222_143052",
  "start_time": "2026-02-22T14:30:52Z",
  "end_time": "2026-02-22T14:45:30Z",
  "device_name": "rover-01",
  "firmware_version": "0.1.0",
  "config_hash": "a1b2c3d4...",
  "total_steps": 180,
  "total_scans": 180,
  "total_images": 180,
  "gnss_fix_type_max": 5,
  "notes": ""
}
```

---

## Appendix C — LoRa Packet Format (Full Spec)

All LoRa communication uses a common framing structure.

### Common Packet Frame

```
┌──────────┬─────────┬─────────┬──────────┬──────────┬─────────────┬─────────┐
│  Sync    │ Version │  Type   │  Length  │ Sequence │   Payload   │  CRC16  │
│ (2 bytes)│ (1 byte)│ (1 byte)│ (2 bytes)│ (2 bytes)│  (N bytes)  │(2 bytes)│
└──────────┴─────────┴─────────┴──────────┴──────────┴─────────────┴─────────┘
```

| Field | Value / Encoding | Notes |
|-------|-----------------|-------|
| Sync | `0xAA 0x55` | Magic bytes |
| Version | `0x01` | Protocol v1.0 |
| Type | See table below | Packet type |
| Length | uint16 LE | Payload length in bytes |
| Sequence | uint16 LE | Wrapping sequence number |
| Payload | N bytes | Type-specific |
| CRC16 | uint16 LE | CRC16-CCITT over Version→end of Payload |

**Total overhead:** 10 bytes/packet.

**CRC algorithm:** CRC16-CCITT — polynomial `0x1021`, init `0xFFFF`, no final XOR.
Scope: Version byte through last byte of Payload (excludes Sync).

### Packet Types

| Type ID | Name | Direction | Description |
|---------|------|-----------|-------------|
| `0x01` | STATUS | Rover → Monitor | Rover health + GNSS summary |
| `0x02` | LINK | Rover → Monitor | Link quality metrics |
| `0x10` | RTCM_CHUNK | Base → Rover | RTCM3 correction data |
| `0x7F` | DEBUG_TEXT | Any | Human-readable debug string |

### STATUS Payload (Type `0x01`) — 10 bytes

```
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ Fix Type │ Sat Count│   HDOP   │ Battery  │Scan State│ Reserved │ Reserved │
│ (1 byte) │ (1 byte) │ (2 bytes)│ (2 bytes)│ (1 byte) │ (1 byte) │ (2 bytes)│
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

| Field | Encoding | Values |
|-------|----------|--------|
| Fix Type | uint8 enum | 0=NONE, 1=2D, 2=3D, 3=DGPS, 4=RTK_FLOAT, 5=RTK_FIX |
| Sat Count | uint8 | Number of satellites |
| HDOP | uint16 LE, ×100 | e.g., `85` = HDOP 0.85 |
| Battery | uint16 LE, mV | Battery voltage in millivolts |
| Scan State | uint8 enum | 0=IDLE, 1=SCANNING, 2=PAUSED, 3=ERROR |
| Reserved | 3 bytes | Set to `0x00` |

### LINK Payload (Type `0x02`) — 14 bytes

```
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│   RSSI   │   SNR    │ Rx Count │ Tx Count │ Err Count│ Reserved │
│ (1 byte) │ (1 byte) │ (4 bytes)│ (4 bytes)│ (2 bytes)│ (2 bytes)│
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

| Field | Encoding | Notes |
|-------|----------|-------|
| RSSI | int8, offset +128 | dBm |
| SNR | int8, offset +128 | dB |
| Rx Count | uint32 LE | Total packets received |
| Tx Count | uint32 LE | Total packets transmitted |
| Err Count | uint16 LE | CRC error count |
| Reserved | 2 bytes | `0x00` |

### RTCM_CHUNK Payload (Type `0x10`) — variable

```
┌──────────┬────────────────────────────────────────────────────┐
│  Flags   │                   RTCM Data                        │
│ (1 byte) │                   (N bytes)                        │
└──────────┴────────────────────────────────────────────────────┘
```

| Flags bit | Meaning |
|---|---|
| Bit 0 | More fragments follow |
| Bits 1–7 | Reserved |

Notes:
- RTCM messages >~200 bytes span multiple packets
- Receiver reassembles using RTCM preamble (`0xD3`)
- No retry on loss — RTK tolerates occasional missing corrections (D-009)

### DEBUG_TEXT Payload (Type `0x7F`) — variable

Raw ASCII text string. Length from packet Length field. No null terminator.

### LoRa Radio Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Frequency | 915 MHz | ISM band (US) |
| Spreading Factor | 9–10 | 1–3 km range, adequate throughput |
| Bandwidth | 125 kHz | Standard, good noise immunity |
| Coding Rate | 4/5 | Light FEC overhead |
| Max usable throughput | ~1500 B/s | Leaves margin above ~850 B/s RTCM load |

---

## Appendix D — All Engineering Decisions (D-001–D-029)

### System Decisions

**D-001 — DIY Over Commercial**
Build custom RTK scanning platform vs. purchasing commercial equipment ($10k–$100k+).
Cost target: ~$1000–1500 total. Accuracy: ±5–10 cm (not survey-certified).

**D-002 — PiLiDAR as Foundation**
Extend open-source PiLiDAR project (PiLiDAR/PiLiDAR on GitHub) rather than clean-sheet design.
Proven Pi + LD19 + stepper concept reduces technical risk; focus effort on RTK/IMU additions.

**D-003 — Raspberry Pi Over MCU-Only**
Linux ecosystem, Python libraries, native CSI camera interface, sufficient compute for Madgwick
fusion + logging. Alternatives rejected: ESP32-only (insufficient throughput), Jetson (overkill).

### GNSS / RTK Decisions

**D-004 — ZED-F9P for RTK**
De-facto DIY RTK standard. Dual-band L1/L2, native RTCM3, excellent documentation.
Need 2 boards (~$400–500 total) + dual-band antennas (~$100–200).

**D-005 — RTK via LoRa (Not Cellular)**
No subscription, no coverage dependency, works remote, predictable ~1–2 sec latency.
Cellular/NTRIP rejected: coverage uncertainty, subscriptions.

**D-006 — RTCM Routing: ESP32 Direct to F9P** *(revised from v0.9)*
RTCM flows: ESP32 UART → ZED-F9P UART2 directly. Pi is NOT in the correction path.
Pi can read RTK status from F9P's NMEA/UBX output but never routes corrections.
Rationale: lower latency, RTK survives Pi crash, simpler ESP32 code.

**D-007 — RTCM Constellation Profiles**
Two profiles: "robust" (GPS+GLONASS+Galileo+BeiDou, ~800–1000 B/s) and
"low_bandwidth" (GPS+GLONASS only, ~500–600 B/s). User-selectable via config.

### Communications Decisions

**D-008 — LoRa Parameters**
SF 9–10, 125 kHz bandwidth, CR 4/5. Balances 1–3 km range with sufficient throughput
for RTCM + sparse telemetry.

**D-009 — LoRa Packet Loss: No Retry**
Tolerate RTCM loss without ACK/retry. RTK is inherently loss-tolerant; retries add
latency and complexity. Rover logs autonomously regardless of link state.

**D-010 — T-Deck Receive-Only (v1.0)**
Monitoring terminal is passive display only. Bidirectional command/control deferred to v1.1.

### Sensor & Fusion Decisions

**D-011 — MPU-9250 as Primary IMU**
9-axis (accel + gyro + mag) enables heading estimation when GNSS unavailable.
MPU-6050 acceptable for bench testing only. Magnetometer must be managed around motor EMI.

**D-012 — Madgwick Filter for Fusion**
Computationally light, widely validated, adequate for scan stabilization.
Output: quaternion orientation at 100 Hz. Tuning parameter: `fusion_beta`.
EKF deferred to v1.1 if accuracy insufficient.

**D-013 — Magnetometer Disabled During Motor Operation**
Stepper motor + 12V wiring generate EMI that corrupts mag readings.
During scan rotation: disable mag, rely on gyro integration for heading.
After rotation: re-enable if needed. Indoor scans use gyro heading (drift-limited).

**D-014 — IMU–LiDAR Timestamp Correlation via Slerp**
IMU samples stored in ring buffer with timestamps.
Each LiDAR scan timestamped at acquisition.
Orientation at scan time = bracket lookup (O(1)) + spherical linear interpolation (slerp).
IMU must sample significantly faster than LiDAR (200+ Hz vs 5–10 Hz).

### Mechanical Decisions

**D-015 — Direct Drive, No Slip Ring (v1.0)**
±180° rotation or full rotation with reset pause; cables looped.
Slip ring adds cost/complexity; deferred to v1.2+.

**D-016 — Open-Loop Stepper Indexing**
Step counting without encoder or limit switch. Steppers rarely miss steps at low speed.
Manual index mark for alignment. Closed-loop is v1.1 upgrade path.

**D-017 — 1/16 Microstepping**
A4988 configured for 1/16 step = 3200 steps/rev. Smoothest motion, minimal vibration,
sufficient torque for light payload.

### Power Decisions

**D-018 — Split Power Domains**
5V compute rail (Pi, Camera, ESP32 via USB-C PD bank) separate from 12V motor rail.
Stepper transients isolated from compute. Compute stays up if motor battery dies.

**D-019 — Dedicated 3.3V Switching Regulator**
ZED-F9P and IMU powered from external ≥1A switching regulator, NOT Pi GPIO 3.3V.
Pi GPIO 3.3V is limited to ~50–100 mA; F9P peaks at 150+ mA. Protects Pi, improves stability.

### Software Decisions

**D-020 — Python 3 on Pi OS Lite 64-bit**
Rapid development, extensive sensor libraries, lightweight headless OS.
Threading via Python threads (GIL noted; optimize hot paths if needed).

**D-021 — JSONL for Logging**
Append-only, crash-safe, human-readable, schema-flexible, easy post-processing with jq/Python.
Larger than binary (~3–5× typical) but fast enough for v1.0 data rates.

**D-022 — Post-Processed Georeferencing**
Georef runs offline in `georef.py` (Phase 5). Real-time georef deferred to v1.1.
Raw logs contain timestamps + poses + GNSS fixes needed for post-processing.

**D-023 — SLAM Deferred to v1.1+**
Indoor mode provides orientation-stabilized relative point clouds — no trajectory estimation.
No loop closure or drift correction in v1.0. hector_slam / Cartographer path open for v1.1.

### Accuracy Decisions

**D-024 — v1.0 Accuracy Target: ±5–10 cm**
RTK position is ±2–3 cm at antenna. Transform chain (LiDAR→IMU→GNSS) adds error
without extrinsic calibration. ±5–10 cm achievable with careful mounting.
±2–3 cm requires calibration procedure (v1.1).

**D-025 — Validation: Repeatability + Control Points**
Validate via multi-scan repeatability (<5 cm target) and comparison to known control points
when available. CloudCompare for visual inspection.

### Camera Decisions

**D-026 — Camera as Visual Reference (Not Photogrammetry)**
JPEG images per rotation step for scan context/QA. Full texture mapping deferred to v1.2.
Images associated to scans via timestamp and step index.

**D-027 — Camera Triggered Per Rotation Step**
One capture per step (or per N steps via `capture_cadence`). Avoids continuous video storage.
Fisheye lens provides wide FOV per frame.

### Configuration Decision

**D-028 — TOML Configuration File**
Single file, all runtime parameters. TOML is typed, comment-supporting, less
whitespace-sensitive than YAML, richer than INI. No external read dependency (Python 3.11+ stdlib).

### Upstream Compatibility Decision

**D-029 — `rpi-lgpio` Over `RPi.GPIO`**
`RPi.GPIO` fails on Bookworm (`RuntimeError: Failed to add edge detection`).
`rpi-lgpio` is a drop-in API replacement using the lgpio backend.
Upstream PiLiDAR has validated this migration. `gpiozero` is also acceptable.
Install: `pip install rpi-lgpio` or `sudo apt install python3-rpi-lgpio`.
Set `LG_WD=/tmp` to suppress lgpio temp file creation in working directory.

---

## Appendix E — Performance Budgets

### Data Rates

| Source | Rate | Size/unit | Bandwidth |
|--------|------|-----------|-----------|
| LiDAR | 10 Hz | ~2 KB/scan | ~20 KB/s |
| IMU | 200 Hz | ~100 B/sample | ~20 KB/s |
| GNSS | 1 Hz | ~200 B/fix | ~0.2 KB/s |
| Camera | 0.5 Hz | ~500 KB/image | ~250 KB/s burst |

**Sustained write (excluding images):** ~40–50 KB/s

### Storage Estimates

| Duration | Scan Data | Images | Total |
|----------|-----------|--------|-------|
| 1 hour | ~150 MB | ~1 GB | ~1.2 GB |
| 4 hours | ~600 MB | ~4 GB | ~4.6 GB |

**Recommended:** 32 GB minimum, 64 GB+ preferred.

### LoRa Bandwidth Budget

| Traffic | Rate | Size | Bandwidth |
|---------|------|------|-----------|
| RTCM (robust profile) | Continuous | — | ~800 B/s |
| STATUS packets | 1 Hz | 20 B | ~20 B/s |
| LINK packets | 0.2 Hz | 24 B | ~5 B/s |
| **Total** | | | **~825 B/s** |

LoRa SF9/125kHz capacity: ~1500 B/s — leaves ~45% headroom.

### Latency Budgets

| Path | Target |
|------|--------|
| RTCM base → rover | <2 sec |
| Sensor → log | <100 ms |
| Telemetry → monitor display | <3 sec |

### Power Budget

| Subsystem | Typical | Peak |
|-----------|---------|------|
| Raspberry Pi 4 | 5 W | 7 W |
| ZED-F9P | 0.5 W | 0.8 W |
| ESP32 LoRa | 0.3 W | 0.5 W |
| MPU-9250 | <0.1 W | <0.1 W |
| LD19 LiDAR | 1 W | 1.5 W |
| NEMA17 Stepper | 5 W | 15 W |
| **Total** | **~12 W** | **~25 W** |

Runtime targets: 50 Wh for 2 hours minimum; 100 Wh for 4-hour goal.

---

## Appendix F — Failure Modes & Recovery

| Failure | Detection | Behavior | Recovery |
|---------|-----------|----------|----------|
| LoRa link loss | Packet timeout | Continue logging locally | Auto-resume on reconnect |
| GNSS loss | Fix status = NONE | Switch to IMU-only orientation | Re-acquire when sky visible |
| RTK degradation | Fix = FLOAT | Log with degraded accuracy flag | Wait for FIX |
| Pi crash | Watchdog timeout | — | Auto-restart, resume from last timestamp |
| Motor stall | Current sense or timeout | Pause scan, log error | Manual intervention |
| Storage full | Disk space monitor | Stop logging, alert via LoRa | Clear storage or swap card |

**Indoor scan duration limits** (IMU drift):
- Recommended: <5 minutes per scan session
- Practical maximum: ~10 minutes before noticeable orientation drift
- Cause: Gyro bias accumulation with magnetometer disabled near motor

**Data integrity measures:**
- LoRa packets include CRC16
- JSONL logs flushed on configurable interval (default 5 sec)
- File-level validation on session close
- Watchdog process monitors main acquisition loop

---

## Appendix G — System Architecture Summary

### Three Physical Units

1. **Rover Unit** — Mobile scanning platform (Pi 4, LD19, HQ Camera, IMU, F9P, ESP32 LoRa, stepper)
2. **RTK Base Station** — Fixed GNSS reference (F9P base mode + ESP32 LoRa Tx)
3. **Monitoring Terminal** — LILYGO T-Deck handheld console (LoRa Rx only in v1.0)

### RTCM Correction Flow (Critical Path)

```
Base ZED-F9P (survey-in mode)
    │ RTCM3 generation
    ▼
Base ESP32 LoRa Tx
    │ LoRa 915 MHz
    ▼
Rover ESP32 LoRa Rx
    │ UART direct (NOT through Pi — D-006)
    ▼
Rover ZED-F9P → RTK FIX
```

### Scan Acquisition Flow

```
Pi Control → NEMA17 Stepper (step)
           → Camera (trigger)
           ← LD19 LiDAR (poll)
           ← MPU-9250 IMU (poll)
           
Timestamp & Correlate:
  t_scan ↔ t_imu via slerp (D-014)
  t_scan ↔ t_img via step index
  
→ JSONL log (scan, imu, camera, gnss, event records)
```

### Telemetry Flow

```
Rover: F9P → Pi (parse) → ESP32 (pack STATUS/LINK) → LoRa Tx
Monitor: LoRa Rx → T-Deck display
```

### Wired Interface Summary

| Interface | Connection | Protocol |
|-----------|------------|----------|
| USB | Pi ↔ ZED-F9P | UBX/NMEA |
| USB-Serial | Pi ↔ LD19 | LD19 proprietary |
| USB | Pi ↔ ESP32 | Serial (telemetry) |
| CSI | Pi ↔ HQ Camera | MIPI |
| I2C | Pi ↔ MPU-9250 | I2C |
| GPIO | Pi ↔ A4988 | Step/Dir/Enable |
| UART | ESP32 ↔ ZED-F9P | RTCM3 (direct, no Pi) |

---

## Appendix H — Development Roadmap

### v1.0 Success Criteria

| Metric | Target | Validation |
|--------|--------|------------|
| RTK fix rate (open sky) | >90% of scan duration | Log analysis |
| Point cloud accuracy | ±5–10 cm | Control point comparison |
| Scan repeatability | <5 cm deviation | Multi-scan overlay |
| Runtime | ≥4 hours | Timed field test |
| LoRa range | ≥1 km LOS | Field test |
| Data integrity | No corrupted logs | File validation |

### Phase Summary

| Phase | Objective | Key Deliverables |
|-------|-----------|-----------------|
| 1 | Hardware integration | Sensors communicating individually; wiring diagram |
| 2 | Base station | RTCM flowing base→rover via LoRa; RTK fix confirmed |
| **3 (Current)** | **Rover software core** | **All Python modules; integrated acquisition test** |
| 4 | Monitoring console | T-Deck firmware; telemetry display working |
| 5 | Post-processing | `georef.py`; PLY output; accuracy validation |
| 6 | Field testing | Runtime/range/repeatability/accuracy tests |
| 7 | v1.0 release | Code cleanup, docs, release tag |

### Python Module Build Order (Phase 3)

1. `config.py` — TOML parsing (no hardware dep)
2. `logger.py` — JSONL output (no hardware dep)
3. Module stubs — import graph complete
4. `stepper.py` — motor control (rpi-lgpio)
5. `lidar.py` — LD19 acquisition
6. `imu.py` — MPU-9250 + Madgwick
7. `gnss.py` — ZED-F9P NMEA/UBX (blocked on hardware)
8. `camera.py` — picamera2 capture
9. `telemetry.py` — STATUS/LINK packet generation
10. `watchdog.py` — health monitoring
11. `main.py` — orchestration + state machine

### Future Versions (Out of Scope for v1.0)

**v1.1 — Refinement:**
Extrinsic calibration procedure (→±2–3 cm), closed-loop motor control,
remote command via T-Deck, OTA ESP32 updates, ICP post-processing.

**v1.2 — Enhanced:**
Real-time SLAM (hector_slam or Cartographer), real-time georef, slip ring
for continuous rotation, IP65-rated enclosure, web monitoring interface.

**v2.0 — Platform:**
Camera photogrammetry + texture mapping, multi-rover coordination, cloud sync,
mobile app.

---

*Document compiled from project specs v0.9.2 (2026-02-22). Source docs in `docs/` folder.*
