# Technical Specifications

**Document Status:** v0.10 — current (deep-alignment overhaul applied 2026-05-30)
**Last Updated:** 2026-05-30

Rover-internal specifications. Cross-repo / on-wire contracts live in
[BASE_STATION_INTEGRATION.md](BASE_STATION_INTEGRATION.md); this file is
the home for things only the rover cares about (TOML schema, JSONL records,
internal pinout, performance budgets).

---

## 1. LoRa Packet Format — Moved

The original v0.9.2 self-contained LoRa frame (Sync `0xAA 0x55`, Version `0x01`)
is **retired**. The current LoRa frame v2 envelope — shared with the
`arm-drone-lidar-workflow` Heltec/T-Deck firmware — lives in:

  * [BASE_STATION_INTEGRATION.md §4](BASE_STATION_INTEGRATION.md#4-lora-frame-v2)
    — authoritative wire format, packet types (`STATUS`, `LINK`, `RTCM_CHUNK`,
    `DISPLAY`, `DEBUG_TEXT`), CRC16-CCITT spec, radio parameters.

See also [`src/rover/lora_protocol.py`](../src/rover/lora_protocol.py) for the
codec implementation and [`docs/CROSS_REPO_BACKLOG.md`](CROSS_REPO_BACKLOG.md)
for the sibling-side Heltec-v2 firmware work that's still pending.

---

## 2. Configuration File Format (TOML)

### 2.1 File Location

```
/home/pi/rover/config.toml
```

### 2.2 Complete Configuration Schema

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
scan_rate_hz = 10                 # Target scan rate (5-10)

[stepper]
enabled = true
steps_per_rev = 3200              # With 1/16 microstepping
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
use_magnetometer = true           # Enable mag (disable during motor)
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
spreading_factor = 9              # 7-12
bandwidth_khz = 125               # 125, 250, or 500
coding_rate = "4/5"               # "4/5", "4/6", "4/7", "4/8"
telemetry_interval_sec = 1.0      # Status packet rate

[camera]
enabled = true
resolution = [1920, 1080]         # Width × Height
capture_cadence = 1               # Capture every N steps (1 = every step)
jpeg_quality = 85                 # JPEG compression (1-100)
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
low_battery_mv = 10500            # Warning threshold
critical_battery_mv = 10000       # Shutdown threshold
```

### 2.3 RTCM Profiles

**Profile: "robust"**
- Messages: 1005, 1077, 1087, 1097, 1127, 1230
- Constellations: GPS, GLONASS, Galileo, BeiDou
- Bandwidth: ~800-1000 bytes/sec

**Profile: "low_bandwidth"**
- Messages: 1005, 1077, 1087, 1230
- Constellations: GPS, GLONASS
- Bandwidth: ~500-600 bytes/sec

---

## 3. Firmware Boundaries

### 3.1 ESP32 LoRa (Rover) — RTCM Receiver

**Responsibilities:**
- Receive LoRa packets from base station
- Validate packet framing (sync bytes, CRC)
- Forward RTCM data directly to ZED-F9P via UART
- Generate LINK telemetry packets (RSSI, SNR, counters)
- Indicate status via LEDs

**Does NOT do:**
- Parse RTCM message content
- Filter or rate-limit RTCM by type
- Store-and-forward or retry
- OTA updates (v1.0)

**Interfaces:**
| Interface | Connection | Data |
|-----------|------------|------|
| LoRa | SX1262 radio | Rx: RTCM packets |
| UART1 | ZED-F9P | Tx: Raw RTCM bytes |
| USB/UART0 | Raspberry Pi | Tx: LINK packets; Rx: Commands (future) |
| GPIO | LEDs | Status indication |

**LED Indicators:**
| LED | Behavior |
|-----|----------|
| Power | Solid on when powered |
| LoRa RX | Blink on packet receive |
| RTCM Active | Solid when forwarding RTCM |
| Error | Blink on CRC error |

### 3.2 ESP32 LoRa (Base Station) — RTCM Transmitter

**Responsibilities:**
- Receive RTCM from ZED-F9P via UART
- Frame RTCM into LoRa packets (RTCM_CHUNK)
- Transmit over LoRa
- Indicate status via LEDs

**Does NOT do:**
- Parse RTCM message content
- Generate RTCM (that's F9P's job)
- Complex scheduling

**Interfaces:**
| Interface | Connection | Data |
|-----------|------------|------|
| UART1 | ZED-F9P | Rx: RTCM bytes |
| LoRa | SX1262 radio | Tx: RTCM packets |
| GPIO | LEDs | Status indication |

### 3.3 T-Deck Monitoring Console

**Responsibilities:**
- Receive LoRa telemetry packets (STATUS, LINK)
- Parse and display on screen
- Show: Fix type, sat count, HDOP, battery, RSSI/SNR, scan state

**Does NOT do:**
- Transmit commands (v1.0)
- Store logs locally
- Display raw RTCM

**Display Layout (Conceptual):**
```
┌────────────────────────────────┐
│  RTK LiDAR Rover Monitor       │
├────────────────────────────────┤
│  RTK:  [FIX]     Sats: 18     │
│  HDOP: 0.85      Batt: 11.8V  │
├────────────────────────────────┤
│  RSSI: -62 dBm   SNR: 9.5 dB  │
│  Rx: 1234        Err: 2       │
├────────────────────────────────┤
│  Scan: ACTIVE    Step: 47/180 │
│  Runtime: 00:12:34            │
└────────────────────────────────┘
```

### 3.4 Raspberry Pi Software Modules

| Module | Responsibility | Interface |
|--------|----------------|-----------|
| `main.py` | Orchestration, state machine | All modules |
| `lidar.py` | LD19 acquisition, parsing | USB-serial |
| `imu.py` | MPU-9250 polling, Madgwick fusion | I2C |
| `gnss.py` | ZED-F9P parsing (NMEA/UBX) | USB |
| `stepper.py` | Motor control, step timing | GPIO |
| `camera.py` | HQ Camera capture | picamera2 |
| `telemetry.py` | Status packet generation | Serial to ESP32 |
| `logger.py` | JSONL file writing | Filesystem |
| `config.py` | TOML parsing | Filesystem |
| `watchdog.py` | Health monitoring, restart | System |

**GPIO Library Note (DEC-029):** Use `rpi-lgpio` (drop-in replacement for `RPi.GPIO`) or `gpiozero` for all GPIO operations. The legacy `RPi.GPIO` is broken on Raspberry Pi OS Bookworm 64-bit. Install via `pip install rpi-lgpio` or `sudo apt install python3-rpi-lgpio`. Set environment variable `LG_WD=/tmp` to manage lgpio temp files.

---

## 4. Data Schema

### 4.1 Session Directory Structure

```
/home/pi/rover/data/
└── scan_20251226_143052/          # Session folder (prefix_YYYYMMDD_HHMMSS)
    ├── config.toml                 # Copy of config at session start
    ├── scan.jsonl                  # Main sensor log
    ├── gnss.jsonl                  # GNSS-only log (optional)
    ├── images/                     # Camera images
    │   ├── img_000001.jpg
    │   ├── img_000002.jpg
    │   └── ...
    └── metadata.json               # Session metadata
```

### 4.2 JSONL Record Types

Each line in `scan.jsonl` is a JSON object with a `type` field indicating record type.

#### 4.2.1 LiDAR Scan Record

```json
{
  "type": "lidar",
  "timestamp": 1735226852.123456,
  "step_index": 47,
  "points": [
    {"angle": 0.0, "distance": 3.452, "intensity": 128},
    {"angle": 0.5, "distance": 3.461, "intensity": 131},
    ...
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| type | string | Record type: "lidar" |
| timestamp | float | Unix timestamp (seconds, microsecond precision) |
| step_index | int | Rotation step index (0 to N-1) |
| points | array | Array of scan points |
| points[].angle | float | Angle in degrees (0-360) |
| points[].distance | float | Distance in meters |
| points[].intensity | int | Return intensity (0-255) |

#### 4.2.2 IMU Record

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
| type | string | Record type: "imu" |
| timestamp | float | Unix timestamp |
| accel | [float, float, float] | Accelerometer [x, y, z] in m/s² |
| gyro | [float, float, float] | Gyroscope [x, y, z] in rad/s |
| mag | [float, float, float] | Magnetometer [x, y, z] in µT (null if disabled) |
| orientation | [float, float, float, float] | Quaternion [w, x, y, z] from fusion |

#### 4.2.3 GNSS Record

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

| Field | Type | Description |
|-------|------|-------------|
| type | string | Record type: "gnss" |
| timestamp | float | Unix timestamp (GNSS time if available) |
| fix_type | int | 0=NONE, 1=2D, 2=3D, 3=DGPS, 4=FLOAT, 5=FIX |
| lat | float | Latitude in decimal degrees (WGS84) |
| lon | float | Longitude in decimal degrees (WGS84) |
| alt | float | Altitude in meters (ellipsoidal) |
| hdop | float | Horizontal dilution of precision |
| vdop | float | Vertical dilution of precision |
| sat_count | int | Number of satellites used |
| rtk_age | float | Age of RTK corrections in seconds |

#### 4.2.4 Camera Record

```json
{
  "type": "camera",
  "timestamp": 1735226852.130000,
  "step_index": 47,
  "filename": "images/img_000047.jpg"
}
```

| Field | Type | Description |
|-------|------|-------------|
| type | string | Record type: "camera" |
| timestamp | float | Unix timestamp at capture |
| step_index | int | Associated rotation step |
| filename | string | Relative path to image file |

#### 4.2.5 Event Record

```json
{
  "type": "event",
  "timestamp": 1735226850.000000,
  "event": "scan_start",
  "details": {"total_steps": 180}
}
```

| Field | Type | Description |
|-------|------|-------------|
| type | string | Record type: "event" |
| timestamp | float | Unix timestamp |
| event | string | Event name |
| details | object | Event-specific data |

**Event Types:**
- `scan_start` — Scan begun
- `scan_complete` — Scan finished
- `scan_pause` — Scan paused
- `scan_resume` — Scan resumed
- `scan_abort` — Scan aborted
- `gnss_fix_acquired` — RTK fix achieved
- `gnss_fix_lost` — Fix degraded
- `low_battery` — Battery warning
- `error` — Error condition

### 4.3 Session Metadata

`metadata.json` contains session-level information:

```json
{
  "session_id": "scan_20251226_143052",
  "start_time": "2025-12-26T14:30:52Z",
  "end_time": "2025-12-26T14:45:30Z",
  "device_name": "rover-01",
  "firmware_version": "0.9.1",
  "config_hash": "a1b2c3d4...",
  "total_steps": 180,
  "total_scans": 180,
  "total_images": 180,
  "gnss_fix_type_max": 5,
  "notes": ""
}
```

---

## 5. Coordinate Frame Conventions

### 5.1 Frame Definitions

| Frame | Origin | X | Y | Z |
|-------|--------|---|---|---|
| LiDAR | LD19 optical center | Forward | Left | Up |
| IMU | MPU-9250 center | Forward | Left | Up |
| Body | Rover center | Forward | Left | Up |
| GNSS | Antenna phase center | — | — | — |
| Local ENU | Session start position | East | North | Up |
| WGS84 | Earth center | ECEF or Geodetic | | |

### 5.2 Quaternion Convention

- Scalar-first format: [w, x, y, z]
- Represents rotation from reference frame to body frame
- Right-handed coordinate system

### 5.3 Transform Notation

`T_A_B` = Transform from frame B to frame A

Example: `T_body_lidar` transforms points from LiDAR frame to Body frame.

### 5.4 Extrinsic Calibration Parameters (TBD)

```toml
# Example calibration section (to be measured)
[calibration]
# LiDAR to IMU transform
lidar_to_imu_translation = [0.0, 0.0, 0.05]    # [x, y, z] meters
lidar_to_imu_rotation = [1.0, 0.0, 0.0, 0.0]   # [w, x, y, z] quaternion

# IMU to GNSS antenna offset
imu_to_gnss_translation = [0.0, 0.0, 0.30]     # [x, y, z] meters
```

---

## 6. Interface Pinouts

### 6.1 Raspberry Pi GPIO (BCM Numbering)

| GPIO | Function | Direction | Notes |
|------|----------|-----------|-------|
| GPIO17 | Stepper DIR | Output | Direction control |
| GPIO27 | Stepper STEP | Output | Step pulse |
| GPIO22 | Stepper ENABLE | Output | Active low |
| GPIO2 (SDA) | I2C Data | Bidirectional | IMU |
| GPIO3 (SCL) | I2C Clock | Output | IMU |

### 6.2 Serial Port Allocation

| Port | Device | Baud | Purpose |
|------|--------|------|---------|
| /dev/ttyACM0 | ZED-F9P | 115200 | GNSS data (NMEA/UBX) |
| /dev/ttyUSB0 | LD19 LiDAR | 230400 | Scan data |
| /dev/ttyUSB1 | ESP32 LoRa | 115200 | Telemetry |

### 6.3 ESP32 LoRa Connections (Rover)

| ESP32 Pin | Connection | Notes |
|-----------|------------|-------|
| TX2 | ZED-F9P UART2 RX | RTCM forwarding |
| RX2 | (Not connected) | F9P doesn't send to ESP32 |
| TX0/USB | Pi USB | Telemetry to Pi |
| RX0/USB | Pi USB | Commands from Pi (future) |
| SPI | SX1262 | LoRa radio |

### 6.4 I2C Bus

| Address | Device | Notes |
|---------|--------|-------|
| 0x68 | MPU-9250 | Primary (AD0 low) |
| 0x69 | MPU-9250 | Alternate (AD0 high) |

**Pull-ups:** 4.7kΩ on SDA and SCL to 3.3V

---

## 7. Performance Budgets

### 7.1 Data Rates

| Source | Rate | Size | Bandwidth |
|--------|------|------|-----------|
| LiDAR | 10 Hz | ~2 KB/scan | ~20 KB/s |
| IMU | 200 Hz | ~100 B/sample | ~20 KB/s |
| GNSS | 1 Hz | ~200 B/fix | ~0.2 KB/s |
| Camera | 0.5 Hz | ~500 KB/image | ~250 KB/s (burst) |

**Total sustained write:** ~40-50 KB/s (excluding images)

### 7.2 Storage Estimates

| Duration | Scan Data | Images | Total |
|----------|-----------|--------|-------|
| 1 hour | ~150 MB | ~1 GB | ~1.2 GB |
| 4 hours | ~600 MB | ~4 GB | ~4.6 GB |

**Recommended storage:** 32 GB minimum, 64 GB+ preferred

### 7.3 LoRa Bandwidth Budget

| Traffic | Rate | Size | Bandwidth |
|---------|------|------|-----------|
| RTCM (robust) | Continuous | — | ~800 B/s |
| STATUS | 1 Hz | 20 B | ~20 B/s |
| LINK | 0.2 Hz | 24 B | ~5 B/s |

**Total:** ~850 B/s (within LoRa SF9/125kHz capacity of ~1500 B/s)

### 7.4 Latency Budgets

| Path | Target | Notes |
|------|--------|-------|
| RTCM base→rover | <2 sec | LoRa + framing |
| Sensor→log | <100 ms | Local processing |
| Telemetry→monitor | <3 sec | LoRa + display update |
