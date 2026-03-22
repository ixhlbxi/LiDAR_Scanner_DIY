# System Architecture

**Document Status:** Frozen (v0.9.1)  
**Last Updated:** 2025-12-26

---

## 1. System Overview

The system comprises three physical units:

1. **Rover Unit** — Mobile scanning platform with LiDAR, camera, IMU, GNSS, and compute
2. **RTK Base Station** — Fixed GNSS reference broadcasting RTCM corrections
3. **Monitoring Terminal** — Handheld LoRa console for field status display

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
│  │             │    │             │    │             │                 │
│  │  UART/USB   │    │    CSI      │    │    I2C      │                 │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                 │
│         │                  │                  │                         │
│         │                  │                  │                         │
│  ┌──────▼──────────────────▼──────────────────▼──────┐                 │
│  │                                                    │                 │
│  │               RASPBERRY PI 4                       │                 │
│  │                                                    │                 │
│  │   • Sensor acquisition & timestamping             │                 │
│  │   • IMU fusion (Madgwick)                         │                 │
│  │   • Stepper motor control                         │                 │
│  │   • Data logging (JSONL)                          │                 │
│  │   • GNSS data parsing                             │                 │
│  │   • Telemetry generation                          │                 │
│  │                                                    │                 │
│  └──────┬──────────────────┬──────────────────┬──────┘                 │
│         │                  │                  │                         │
│         │ GPIO             │ USB/UART         │ USB                     │
│         │                  │                  │                         │
│  ┌──────▼──────┐    ┌──────▼──────┐    ┌──────▼──────┐                 │
│  │   A4988     │    │   ESP32     │    │  ZED-F9P   │                 │
│  │   Driver    │    │   LoRa      │    │   GNSS     │                 │
│  │             │    │             │    │            │                 │
│  └──────┬──────┘    └──────┬──────┘    └──────┬─────┘                 │
│         │                  │                  │                         │
│  ┌──────▼──────┐           │ LoRa             │ UART (RTCM in)         │
│  │   NEMA17    │           │                  │                         │
│  │   Stepper   │           │           ┌──────▼──────┐                 │
│  └─────────────┘           │           │   ESP32     │◄────────────────┤
│                            │           │   (RTCM)    │    RTCM direct  │
│                            │           └─────────────┘                 │
│                            │                                           │
└────────────────────────────┼───────────────────────────────────────────┘
                             │
                             ▼ LoRa 915 MHz
```

### 2.2 Subsystem Responsibilities

| Subsystem | Hardware | Responsibilities |
|-----------|----------|------------------|
| **Compute** | Raspberry Pi 4 | Orchestration, sensor fusion, logging, control |
| **Scanning** | LD19 LiDAR | 360° distance measurement, 2D slices |
| **Rotation** | NEMA17 + A4988 | Mechanical rotation for 3D scan stacking |
| **Imaging** | HQ Camera + Fisheye | Visual context capture per scan step |
| **Orientation** | MPU-9250 | Roll/pitch/yaw estimation via Madgwick filter |
| **Positioning** | ZED-F9P | RTK GNSS with cm-level accuracy |
| **RTCM Rx** | ESP32 LoRa | Receive RTCM corrections, forward to F9P |
| **Telemetry Tx** | ESP32 LoRa | Transmit rover status to monitoring terminal |

### 2.3 RTCM Correction Flow (Critical Path)

```
Base Station GNSS
       │
       ▼
RTCM3 Generation
       │
       ▼
ESP32 LoRa Tx (Base)
       │
       │ LoRa 915 MHz
       ▼
ESP32 LoRa Rx (Rover)
       │
       │ UART Direct (NOT through Pi)
       ▼
ZED-F9P (Rover)
       │
       ▼
RTK Fix Solution
```

**Key Decision:** RTCM flows ESP32 → F9P directly via UART, bypassing the Pi. This reduces latency, simplifies code, and keeps RTK alive if Linux hiccups.

The Pi can optionally monitor RTCM status via F9P's NMEA/UBX output, but never sits in the correction path.

---

## 3. RTK Base Station Architecture

### 3.1 Block Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                       RTK BASE STATION                          │
│                                                                 │
│  ┌─────────────────┐                                           │
│  │  Dual-Band      │                                           │
│  │  GNSS Antenna   │                                           │
│  │  (L1/L2)        │                                           │
│  └────────┬────────┘                                           │
│           │                                                     │
│  ┌────────▼────────┐                                           │
│  │    ZED-F9P      │                                           │
│  │    (Base Mode)  │                                           │
│  │                 │                                           │
│  │  • Survey-in    │                                           │
│  │  • RTCM gen     │                                           │
│  └────────┬────────┘                                           │
│           │ UART                                                │
│  ┌────────▼────────┐                                           │
│  │  Raspberry Pi   │  (or MCU for minimal base)                │
│  │  / Controller   │                                           │
│  │                 │                                           │
│  │  • RTCM routing │                                           │
│  │  • Status LED   │                                           │
│  └────────┬────────┘                                           │
│           │ UART                                                │
│  ┌────────▼────────┐                                           │
│  │   ESP32 LoRa    │                                           │
│  │   (Tx)          │────────────────────────────► LoRa 915 MHz │
│  │                 │                                           │
│  └─────────────────┘                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Base Station Responsibilities

- Survey-in to establish fixed position (5-10 min, ≤2 cm accuracy target)
- Generate RTCM3 correction messages
- Broadcast RTCM over LoRa at configured interval
- Indicate survey/fix status via LED

### 3.3 RTCM Message Set

**Profile A — Robust (default):**
| Message | Content | Constellation |
|---------|---------|---------------|
| 1005 | Base station position | — |
| 1077 | MSM7 observables | GPS |
| 1087 | MSM7 observables | GLONASS |
| 1097 | MSM7 observables | Galileo |
| 1127 | MSM7 observables | BeiDou |
| 1230 | GLONASS code-phase biases | GLONASS |

**Profile B — Low Bandwidth:**
| Message | Content | Constellation |
|---------|---------|---------------|
| 1005 | Base station position | — |
| 1077 | MSM7 observables | GPS |
| 1087 | MSM7 observables | GLONASS |
| 1230 | GLONASS code-phase biases | GLONASS |

Profile selection via config file.

---

## 4. Monitoring Terminal Architecture

### 4.1 Overview

The LILYGO T-Deck serves as a handheld field console for monitoring rover status without requiring a laptop or phone.

```
┌─────────────────────────────────────────────────────────────────┐
│                    MONITORING TERMINAL                          │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    LILYGO T-Deck                         │   │
│  │                                                          │   │
│  │   ┌────────────────────────────────────────────────┐    │   │
│  │   │              STATUS DISPLAY                     │    │   │
│  │   │                                                 │    │   │
│  │   │   RTK: [FIX]     Sats: 18    HDOP: 0.8        │    │   │
│  │   │   Batt: 78%      RSSI: -62   Scan: ACTIVE     │    │   │
│  │   │                                                 │    │   │
│  │   └────────────────────────────────────────────────┘    │   │
│  │                                                          │   │
│  │   [LoRa Rx] ◄──────────────────────────── LoRa 915 MHz  │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Display Fields

| Field | Source | Update Rate |
|-------|--------|-------------|
| RTK Status | F9P via Pi | 1 Hz |
| Satellite Count | F9P via Pi | 1 Hz |
| HDOP | F9P via Pi | 1 Hz |
| Battery Voltage | Pi ADC or monitor | 0.2 Hz |
| LoRa RSSI/SNR | ESP32 local | Per packet |
| Scan State | Pi | On change |

### 4.3 Operational Mode

- **Receive-only** in v1.0 (no remote commands)
- Custom firmware with structured UI
- Bidirectional command/control deferred to v1.1+

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

```
┌─────────────────────────────────────────────────────────────────┐
│                        ROVER                                    │
│                                                                 │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐                     │
│  │ ZED-F9P │───►│   Pi    │───►│  ESP32  │                     │
│  │ GNSS    │    │ (parse) │    │ (pack)  │                     │
│  └─────────┘    └─────────┘    └────┬────┘                     │
│                                     │                           │
│  Telemetry: fix, sats, HDOP,       │ LoRa Tx                   │
│             battery, scan state     │                           │
│                                     ▼                           │
└─────────────────────────────────────────────────────────────────┘
                                      │
                                      │ 915 MHz
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MONITORING TERMINAL                          │
│                                                                 │
│                     ┌─────────┐                                 │
│            LoRa Rx  │ T-Deck  │                                 │
│           ─────────►│ Display │                                 │
│                     └─────────┘                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

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
| Base → Rover | 915 MHz | LoRa SF9-10, 125kHz | RTCM corrections |
| Rover → Monitor | 915 MHz | LoRa SF9-10, 125kHz | Status telemetry |

### 6.3 LoRa Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Frequency | 915 MHz | ISM band (US) |
| Spreading Factor | 9-10 | Balance range vs. throughput |
| Bandwidth | 125 kHz | Standard, good noise immunity |
| Coding Rate | 4/5 | Light FEC overhead |
| Target Range | 1-3 km LOS | Adequate for field use |
| Max Range | ~5 km LOS | Hard limit for baseline |

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
