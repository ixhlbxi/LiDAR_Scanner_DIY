# System Architecture

**Document Status:** v0.10 — in overhaul (Base-Station integration)
**Last Updated:** 2026-05-23

> **v0.10 overhaul:** The rover is being reframed as a consumer of the production
> Base-Station built in `ixhlbxi/arm-drone-lidar-workflow`. RTK corrections now come
> from that Base-Station's NTRIP caster (primary) with LoRa as fallback. The handheld
> monitor is owned by the Base-Station ecosystem. Integration contract:
> `docs/BASE_STATION_INTEGRATION.md`. See DEC-030 through DEC-034 in `docs/DECISIONS.md`.

---

## 1. System Overview

The rover is one of two physical units on the rover-operations side; the Base-Station
in `arm-drone-lidar-workflow` is the third party, owned by that repo:

1. **Rover Unit** — Mobile scanning platform with LiDAR, camera, IMU, GNSS, and compute.
2. **External Base-Station** (separate repo) — Production RTK Pi + ZED-F9P running the
   `arm-drone-lidar-workflow` `rtk-base-manager` services. Hosts the NTRIP caster
   (mountpoint `ARM_BASE` on port 2101), the `/run/rtk-base/status.json` consumer
   ecosystem, and the Heltec/T-Deck field displays. The rover talks to it but does not
   replicate it.

The legacy "Monitoring Terminal" as a third rover-side unit (a dedicated T-Deck) is
removed by DEC-033 — rover field visibility now comes from triple-channel telemetry
(see §5.3).

---

## 2. Rover Unit Architecture

### 2.1 Block Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            ROVER UNIT                                   │
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │   LD19      │    │  HQ Camera  │    │  MPU-9250   │                 │
│  │   LiDAR     │    │  + Fisheye  │    │    IMU      │                 │
│  │  UART/USB   │    │    CSI      │    │    I2C      │                 │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                 │
│         │                  │                  │                         │
│  ┌──────▼──────────────────▼──────────────────▼─────────────────────┐  │
│  │                     RASPBERRY PI 4                                │  │
│  │                                                                   │  │
│  │   • Acquisition + timestamping  • IMU fusion (Madgwick)          │  │
│  │   • Stepper control             • JSONL logging                  │  │
│  │   • NTRIP client (default; DEC-032)                                │  │
│  │   • TelemetryRouter — status.json + HTTP + LoRa pub (DEC-033)      │  │
│  └──┬────────────┬────────────────┬──────────────────┬──────────────┘  │
│     │ GPIO       │ USB (RTCM out  │ USB (telemetry,  │ USB (UBX/NMEA   │
│     │            │   if Pi-NTRIP) │   LoRa frames)   │   F9P status)   │
│  ┌──▼──┐    ┌────▼────────┐  ┌────▼────────┐    ┌────▼────────┐       │
│  │A4988│    │   ZED-F9P   │  │  ESP32 LoRa │    │ (same F9P)  │       │
│  │     │    │  (USB RTCM  │  │  Rover      │    │             │       │
│  └──┬──┘    │   in port)  │  │  • LoRa Rx  │    │             │       │
│     │       └─────────────┘  │    RTCM →   │    │             │       │
│  ┌──▼──┐                     │    F9P UART2│ ───┘             │       │
│  │NEMA-│                     │  • LoRa Tx  │                          │
│  │ 17  │                     │    STATUS / │                          │
│  └─────┘                     │    LINK     │                          │
│                              │  • OR NTRIP │                          │
│                              │    over WiFi│                          │
│                              └──────┬──────┘                          │
│                                     │                                  │
└─────────────────────────────────────┼──────────────────────────────────┘
                                      │
                          915 MHz LoRa ◄─► Base-Station Heltec (fallback)
                          and
                          2.4 GHz WiFi ◄─► Base-Station NTRIP caster
                                            (primary, via Pi NTRIP client)
```

Two RTK ingress paths share the F9P: USB (when the Pi's NTRIP client is running) and
UART2 (when the ESP32 is the NTRIP/LoRa-RTCM source). Only one is active per session.

### 2.2 Subsystem Responsibilities

| Subsystem | Hardware | Responsibilities |
|-----------|----------|------------------|
| **Compute** | Raspberry Pi 4 | Orchestration, sensor fusion, logging, control |
| **Scanning** | LD19 LiDAR | 360° distance measurement, 2D slices |
| **Rotation** | NEMA17 + A4988 | Mechanical rotation for 3D scan stacking |
| **Imaging** | HQ Camera + Fisheye | Visual context capture per scan step |
| **Orientation** | MPU-9250 | Roll/pitch/yaw estimation via Madgwick filter |
| **Positioning** | ZED-F9P | RTK GNSS with cm-level accuracy |
| **RTK ingress (primary)** | Pi NTRIP client OR ESP32 NTRIP-over-WiFi | NTRIP/RTCM from `ARM_BASE` caster (DEC-031, DEC-032) |
| **RTK ingress (fallback)** | Rover ESP32 LoRa Rx | Decode RTCM_CHUNK (LoRa frame v2 type 0x10) → F9P UART2 |
| **Telemetry Tx** | Rover ESP32 LoRa Tx + Pi `status.json` + Pi HTTP | Three-channel publisher (DEC-033) |

### 2.3 RTCM Correction Flow

Two paths, NTRIP primary (DEC-031) and LoRa fallback. Selected by config; not both
simultaneously feeding the same F9P input.

**Primary — NTRIP over IP:**

```
arm-drone-lidar-workflow Base-Station Pi
  (rtk_base_manager.py → NTRIP caster, mountpoint ARM_BASE @ :2101)
       │
       │ RTCM3 over TCP (auth via password env var)
       ▼
Rover NTRIP Client
  (Pi-hosted by default; ESP32-hosted optionally — DEC-032)
       │
       │ USB (Pi client) or UART2 (ESP32 client)
       ▼
Rover ZED-F9P → RTK FIX
```

**Fallback — LoRa-Relayed RTCM:**

```
Base-Station Heltec V3
  (LoRa frame v2, type=0x10 RTCM_CHUNK; Phase D of overhaul)
       │
       │ LoRa 915 MHz, SF7/BW125/CR4/5
       ▼
Rover ESP32
  (decodes RTCM_CHUNK, writes to F9P UART2 — direct, no Pi)
       │
       ▼
Rover ZED-F9P → RTK FIX
```

The LoRa-direct path preserves the original DEC-006 robustness property (RTK survives a
Pi crash) for the no-network case. The NTRIP path involves the Pi by default, which
DEC-032 explicitly accepts in exchange for the operational simplicity of a single
config surface.

**Mode selection:** `[ntrip].enabled` and `[ntrip].client_location` choose the NTRIP
behavior; `[lora].role` chooses whether the rover ESP32 acts as RTCM-Rx, STATUS/LINK-Tx
only, or is fully disabled.

---

## 3. External Base-Station Integration

This rover does not own a Base-Station design. The production Base-Station lives in
`ixhlbxi/arm-drone-lidar-workflow` and is fully specified there
(`base-station/CLAUDE.md`). Summary of what this rover relies on:

| Service | Owner | This rover's role |
|---|---|---|
| NTRIP caster (`ARM_BASE` on `:2101`) | `rtk_base_manager.py` (their repo) | Client (DEC-031) |
| `/run/rtk-base/status.json` schema + atomic-write convention | `rtk_io.py` (their repo) | Same shape mirrored for `/run/rover/status.json` (DEC-033) |
| Heltec V3 LoRa Tx (DISPLAY frames today; RTCM_CHUNK after their Phase D) | `heltec-display/` (their repo) | Receiver of fallback RTCM (DEC-031, DEC-032) |
| T-Deck BLE/LoRa field display | `t-deck/` (their repo) | Not consumed directly by rover; may be extended in v1.1+ to surface rover STATUS |

**Base-Station operating modes** that affect the rover:

- `main` mode — the only mode that serves RTCM to the rover (NTRIP caster running).
- `logging` mode — base is a redundant PPK logger; **no RTCM output**, so the rover's
  NTRIP path is dead in this mode. LoRa fallback also dies (no RTCM source to wrap).
  In `arm_group` profile, this is a hard failure-to-start condition the rover should
  surface clearly.
- `gcp` mode — base is acting as a static rover for GCP collection; **no RTCM output**.
  Same constraint as `logging`.

The rover does NOT bring up its own NTRIP caster, RTCM generator, or survey-in process.
For genuinely off-grid use with no Base-Station present, the rover degrades to whatever
the F9P can produce standalone (3D-only fix, ~2-3 m accuracy).

The RTCM message set served by `ARM_BASE` is controlled by `configure_base.py` in the
other repo. The "robust" profile (GPS+GLONASS+Galileo+BeiDou: messages 1005, 1077, 1087,
1097, 1127, 1230) is the established default there.

---

## 4. Field Visibility (Telemetry Channels)

Per DEC-033, the rover publishes status on three independent channels. Each is
individually enable-able and failure-isolated from the others. See
`docs/BASE_STATION_INTEGRATION.md` §3 for the schema and routes.

| Channel | Transport | Default | Best for |
|---|---|---|---|
| A — Base-Station-compatible `status.json` | Atomic file write (mirrors `rtk_io.atomic_write_json`) | On in `arm_group` | Base-Station handhelds (Heltec/T-Deck) consuming both base and rover status |
| B — Local HTTP `/status` & `/health` | Stdlib `http.server` on loopback (default :8090) | Off | Personal DIY: `curl rover.local:8090/status` from a laptop |
| C — LoRa STATUS / LINK | LoRa frame v2 types `0x01` / `0x02` | On | Off-network case — only channel that survives no IP and no filesystem |

The dedicated rover-attached T-Deck from v0.9 is removed (DEC-033). When operated in
`arm_group` profile, rover status surfaces through whatever Base-Station handheld the
operator is already carrying.

---

## 5. Data Flow Architecture

### 5.1 Scan Acquisition Flow

```
                    SCAN ACQUISITION FLOW
                    
┌─────────┐  step   ┌─────────┐  trigger  ┌─────────┐
│  Pi     │────────►│ NEMA17  │           │ Camera  │
│ Control │         │ Stepper │           │         │
└────┬────┘         └─────────┘           └────┬────┘
     │                                         │
     │ poll                                    │ capture
     ▼                                         ▼
┌─────────┐         ┌─────────┐         ┌─────────┐
│  LD19   │         │ MPU-9250│         │  JPEG   │
│ LiDAR   │         │   IMU   │         │  Frame  │
└────┬────┘         └────┬────┘         └────┬────┘
     │                   │                   │
     │ 2D scan           │ orientation       │ image
     │ points            │ quaternion        │
     ▼                   ▼                   ▼
┌─────────────────────────────────────────────────┐
│              TIMESTAMP & CORRELATE              │
│                                                 │
│   t_scan ←→ t_imu (slerp interpolation)        │
│   t_scan ←→ t_img (nearest association)        │
│                                                 │
└────────────────────────┬────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────┐
│                 JSONL LOG FILE                  │
│                                                 │
│  { scan_id, timestamp, points[], pose, gnss }  │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 5.2 Timestamp Synchronization Strategy

**Master Clock:** GNSS time (when available), monotonic system clock otherwise.

**IMU-LiDAR Correlation:**
1. IMU samples stored in ring buffer with timestamps
2. Each LiDAR scan packet timestamped at acquisition
3. Orientation at scan time computed via:
   - Bracket lookup (find IMU samples before/after scan timestamp)
   - Spherical linear interpolation (slerp) for quaternion orientation
   - Linear interpolation for angular rates if needed

**Camera-LiDAR Association:**
- Camera triggered per rotation step
- Each image timestamped and associated with step index
- Nearest-neighbor association to LiDAR slice batch

**PPS Signal:** Optional future enhancement; v1.0 uses software timestamps only.

### 5.3 Telemetry Flow

Three channels diverge from the Pi's `TelemetryRouter`:

```
Pi sensor stack
    │
    │ fix, sats, HDOP, battery, scan_state,
    │ LoRa link metrics, NTRIP byte rate
    ▼
TelemetryRouter (src/rover/telemetry.py)
    │
    ├── Channel A: atomic write /run/rover/status.json (Base-Station-shaped)
    │       └─► consumed by anything that reads /run/rtk-base/status.json today
    │
    ├── Channel B: http.server :8090/status, :8090/health
    │       └─► curl from operator laptop on same network
    │
    └── Channel C: USB serial to rover ESP32 → LoRa frame v2 (STATUS 0x01, LINK 0x02)
            └─► Base-Station handhelds in range, off-network operation
```

Each channel can be disabled independently in config; one failing doesn't take down
the others.

---

## 6. Communication Topology

### 6.1 Wired Interfaces

| Interface | Connection | Protocol | Data |
|-----------|------------|----------|------|
| USB | Pi ↔ ZED-F9P | UBX/NMEA | Position, time, status |
| USB-Serial | Pi ↔ LD19 | Proprietary | Scan points |
| USB | Pi ↔ ESP32 | Serial | Telemetry commands |
| CSI | Pi ↔ HQ Camera | MIPI | Image frames |
| I2C | Pi ↔ MPU-9250 | I2C | IMU samples |
| GPIO | Pi ↔ A4988 | Step/Dir | Motor control |
| UART | ESP32 ↔ ZED-F9P | RTCM3 | Corrections (direct) |

### 6.2 Wireless Interfaces

| Link | Frequency | Modulation | Purpose |
|------|-----------|------------|---------|
| Base → Rover (NTRIP primary) | 2.4/5 GHz WiFi (or cellular) | TCP/IP | RTCM3 corrections via NTRIP (DEC-031) |
| Base → Rover (LoRa fallback) | 915 MHz | LoRa SF7/BW125/CR4/5 | RTCM_CHUNK (LoRa frame v2 type 0x10) |
| Rover → Handhelds | 915 MHz | LoRa SF7/BW125/CR4/5 | STATUS / LINK (LoRa frame v2 types 0x01 / 0x02) |

### 6.3 LoRa Parameters

Per LoRa frame v2 (defined in `docs/BASE_STATION_INTEGRATION.md` §4), the rover and
Base-Station agree on:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Frequency | 915 MHz | ISM band (US) |
| Spreading Factor | 7 (default) | Matches Heltec/T-Deck firmware in arm-drone-lidar-workflow; ~5 kbps throughput |
| Bandwidth | 125 kHz | Standard, good noise immunity |
| Coding Rate | 4/5 | Light FEC overhead |
| Sync Word | `0x12` | Private; matches existing Base-Station handhelds |
| Target Range | 1-3 km LOS | Adequate for field use (raise SF for longer range) |

---

## 7. Indoor / GNSS-Denied Operation

### 7.1 Problem Statement

RTK GNSS fails or degrades:
- Indoors
- Under dense canopy
- In urban canyons
- Near large structures

### 7.2 v1.0 Fallback Strategy

| Layer | Role | Capability |
|-------|------|------------|
| IMU | Orientation stabilization | Roll/pitch/yaw tracking |
| LiDAR | Local geometry | Relative point positions |
| Geometry | Constraint | Scan-to-scan consistency |

**What v1.0 delivers indoors:**
- Orientation-stabilized relative point clouds
- Consistent local geometry
- No absolute georeferencing
- No trajectory estimation from IMU integration

**What v1.0 does NOT attempt:**
- IMU-based position dead-reckoning (drift is meters/minute)
- Real-time SLAM
- Loop closure

### 7.3 Indoor Scan Duration Limits

Due to IMU orientation drift (gyro bias, magnetometer disabled near motor), indoor scans should be kept short:
- **Recommended:** < 5 minutes per scan session
- **Maximum practical:** ~10 minutes before noticeable drift

### 7.4 Future Enhancement Path (v1.1+)

- SLAM integration (hector_slam, Cartographer, or custom ICP)
- Visual marker drift correction
- Scan-to-scan registration in post-processing

---

## 8. Power Architecture

### 8.1 Voltage Domains

| Rail | Voltage | Consumers | Source |
|------|---------|-----------|--------|
| Motor | 12V | NEMA17 via A4988 | Dedicated battery or DC-DC |
| Compute | 5V | Pi 4, Camera, ESP32 (via USB) | USB-C PD bank |
| Logic | 3.3V | ZED-F9P, IMU | Dedicated regulator (≥1A) |

### 8.2 Power Budget

| Subsystem | Typical | Peak | Notes |
|-----------|---------|------|-------|
| Raspberry Pi 4 | 5 W | 7 W | With camera active |
| ZED-F9P | 0.5 W | 0.8 W | RTK tracking |
| ESP32 LoRa | 0.3 W | 0.5 W | Tx bursts |
| MPU-9250 | <0.1 W | <0.1 W | Negligible |
| LD19 LiDAR | 1 W | 1.5 W | Continuous scan |
| NEMA17 Stepper | 5 W | 15 W | Holding vs. moving |
| **Total** | **~12 W** | **~25 W** | |

### 8.3 Runtime Targets

| Target | Capacity Required | Notes |
|--------|-------------------|-------|
| Minimum (2 hr) | ~50 Wh | Acceptable for short sessions |
| Goal (4 hr) | ~100 Wh | Full day fieldwork |

### 8.4 Split Power Strategy

**Decision:** Separate compute and motor power domains.

**Rationale:**
- Stepper motor transients don't brown out compute
- Independent battery management
- Compute stays alive if motor battery dies (graceful degradation)

**Implementation:**
- USB-C PD power bank (20-30 Ah) → 5V rail → Pi, Camera, ESP32
- 12V pack (LiPo or separate DC source) → Stepper
- 5V → 3.3V switching regulator (≥1A) → F9P, IMU

---

## 9. Failure Modes & Recovery

### 9.1 Failure Mode Table

| Failure | Detection | Behavior | Recovery |
|---------|-----------|----------|----------|
| LoRa link loss | Packet timeout | Continue logging locally | Auto-resume on reconnect |
| GNSS loss | Fix status = NONE | Switch to IMU-only orientation | Re-acquire when sky visible |
| RTK degradation | Fix status = FLOAT | Log with degraded accuracy flag | Wait for FIX |
| Pi crash | Watchdog timeout | — | Auto-restart, resume from last timestamp |
| Motor stall | Current sense or timeout | Pause scan, log error | Manual intervention |
| Storage full | Disk space monitor | Stop logging, alert via LoRa | Clear storage or swap card |

### 9.2 Data Integrity

- LoRa packets include CRC16
- JSONL logs flushed frequently (configurable)
- File-level validation on save
- Watchdog process monitors main acquisition loop

---

## 10. Coordinate Frames

### 10.1 Frame Definitions

| Frame | Origin | Orientation | Notes |
|-------|--------|-------------|-------|
| **LiDAR** | LD19 optical center | X forward, Z up | Raw scan points |
| **IMU** | MPU-9250 center | Aligned to LiDAR (calibration) | Orientation reference |
| **Body** | Rover geometric center | X forward, Z up | Unified rover frame |
| **GNSS** | Antenna phase center | — | Position reference |
| **Local** | Scan session origin | ENU | Working frame |
| **Global** | WGS84 | ECEF or geodetic | Georeferenced output |

### 10.2 Transform Chain

```
LiDAR Frame
    │
    │ T_lidar_imu (static, calibration)
    ▼
IMU Frame
    │
    │ T_imu_body (static, mounting)
    ▼
Body Frame
    │
    │ T_body_gnss (static, antenna offset)
    ▼
GNSS Frame
    │
    │ T_gnss_local (session origin)
    ▼
Local ENU Frame
    │
    │ T_local_global (geodetic transform)
    ▼
Global WGS84
```

### 10.3 Calibration Status (v1.0)

| Transform | Status | Method |
|-----------|--------|--------|
| T_lidar_imu | TBD | Measure or jig calibration |
| T_imu_body | TBD | Mounting geometry |
| T_body_gnss | TBD | Antenna offset measurement |
| T_gnss_local | Computed | Session start position |
| T_local_global | Computed | Standard geodetic |

**Note:** Extrinsic calibration directly impacts point cloud accuracy. Without calibration, v1.0 accuracy is ±5-10 cm (not ±2-3 cm).

### 10.4 Acquisition vs Export Coordinates (DEC-034)

The acquisition stack always logs in **SI units / WGS84** — meters, decimal degrees,
quaternions. The session-config field `[session].target_crs_epsg` records the desired
output CRS but does **not** affect the JSONL hot path.

`scripts/georef.py` reads `metadata.json.session.target_crs_epsg` and converts to that
CRS at export time using `pyproj`. ARM Group sessions typically convert to
NAD83(2011) State Plane in US Survey Foot (e.g., EPSG `6346` for PA-N).

| Profile | Acquisition CRS | Default export CRS |
|---|---|---|
| `personal` | WGS84 (EPSG `4326`) / local ENU | WGS84 (no conversion) |
| `arm_group` | WGS84 (EPSG `4326`) / local ENU | Session-config (e.g., `6346` ft-US) |

Re-exporting the same session to a different CRS is supported (`--crs EPSG` override on
`georef.py`) without re-acquiring data.
