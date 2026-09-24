# System Architecture

**Document Status:** v0.11 — reconciled with code (2026-09-23 audit remediation)
**Last Updated:** 2026-09-23

> **v0.11 — post-audit remediation (2026-09-23).** The rover is a consumer of the
> production Base-Station built in `ixhlbxi/arm-drone-lidar-workflow`. RTK corrections
> come from that Base-Station's NTRIP caster only — LoRa is status-only telemetry
> (DEC-031 amended 2026-09-23); there is no LoRa RTK path. The handheld monitor is
> owned by the Base-Station ecosystem. Integration contract:
> `docs/BASE_STATION_INTEGRATION.md`. See DEC-030 through DEC-035 in `docs/DECISIONS.md`
> (DEC-013, DEC-015 and DEC-031 amended 2026-09-23).

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
│  │   • Acquisition + timestamping   • IMU fusion (Madgwick)          │  │
│  │   • Stepper control              • JSONL logging                  │  │
│  │   • NTRIP client (default; DEC-032) — sole RTK transport          │  │
│  │   • TelemetryRouter — status.json + HTTP + LoRa STATUS (DEC-033)  │  │
│  └──┬────────────┬────────────────┬──────────────────┬──────────────┘  │
│     │ GPIO       │ USB (RTCM in,  │ USB (LoRa STATUS │ USB (UBX/NMEA   │
│     │            │  when Pi is    │  frame, every    │  F9P status)    │
│     │            │  NTRIP client) │  10 s)            │                 │
│  ┌──▼──┐    ┌────▼────────┐  ┌────▼────────┐    ┌────▼────────┐       │
│  │A4988│    │   ZED-F9P   │  │  ESP32 LoRa │    │ (same F9P)  │       │
│  │     │    │ (USB, or    │  │  Rover      │    │             │       │
│  └──┬──┘    │  UART2 if   │  │  • LoRa Tx  │    │             │       │
│     │       │  ESP32 is   │  │    STATUS   │    │             │       │
│  ┌──▼──┐    │  the NTRIP  │  │    only     │    │             │       │
│  │NEMA-│    │  client —   │  │  • OR NTRIP │    │             │       │
│  │ 17  │    │  DEC-032)   │  │    client   │    │             │       │
│  └─────┘    └─────────────┘  │    over WiFi│    │             │       │
│                              └──────┬──────┘    │             │       │
│                                     │                                  │
└─────────────────────────────────────┼──────────────────────────────────┘
                                      │
                          915 MHz LoRa ───► Base-Station handhelds
                                             (STATUS only — no LINK sent)
                          2.4/5 GHz WiFi ◄─► Base-Station NTRIP caster
                                             (sole RTK transport, DEC-031;
                                              Pi or ESP32 client, DEC-032)
```

One RTK ingress path feeds the F9P: USB (Pi-hosted NTRIP client, the default) or UART2
(ESP32-hosted NTRIP client, `[ntrip].client_location = "esp32"` — DEC-032). Only one
runs per session. LoRa never carries RTCM — it is status-only (DEC-031 amended
2026-09-23).

### 2.2 Subsystem Responsibilities

| Subsystem | Hardware | Responsibilities |
|-----------|----------|------------------|
| **Compute** | Raspberry Pi 4 | Orchestration, sensor fusion, logging, control |
| **Scanning** | LD19 LiDAR | 360° distance measurement, 2D slices |
| **Rotation** | NEMA17 + A4988 | 360° forward sweep, then a fast rewind in ≤45° chunks (DEC-015 amended 2026-09-23) |
| **Imaging** | HQ Camera + Fisheye | Visual context capture per scan step |
| **Orientation** | MPU-9250 | Roll/pitch every scan (Madgwick); yaw from a per-sweep rest heading, never gyro or GNSS (DEC-013 amended 2026-09-23) |
| **Positioning** | ZED-F9P | RTK GNSS with cm-level accuracy |
| **RTK ingress (sole path)** | Pi NTRIP client OR ESP32 NTRIP-over-WiFi client | NTRIP/RTCM from `ARM_BASE` caster (DEC-031 amended 2026-09-23, DEC-032) |
| **Telemetry Tx** | Rover ESP32 LoRa Tx (status-only) + Pi `status.json` + Pi HTTP | Three-channel STATUS publisher (DEC-033); the protocol defines LINK but the rover never sends it |

### 2.3 RTCM Correction Flow

NTRIP-over-IP is the sole RTK transport (DEC-031 amended 2026-09-23).

**NTRIP over IP:**

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

**LoRa is status-only (DEC-031 amended 2026-09-23):** the LoRa-relayed-RTCM fallback
described in earlier revisions of this doc was never built on the Base-Station side
and is retired — `CR-002` closed not-needed. `[lora].role` is `status_tx_only` or
`disabled`; there is no RTCM-Rx role. LoRa frame type `0x10` (`RTCM_CHUNK`) is retired
and reserved — never encoded or decoded. The firmware's `lora_rtcm_relay` env is
pending removal (backlog `S5-F1`).

**Base-Station caster rule (fact 16):** the caster serves one client at a time
(sibling NC-1). The drone and this rover never share a base session (CR-005) — confirm
the caster is free before starting the rover's NTRIP client.

**Mode selection:** `[ntrip].enabled` and `[ntrip].client_location` choose which side
(Pi or ESP32) runs the NTRIP client; `[lora].role` only ever chooses status-only
telemetry or fully disabled — never an RTCM role.

---

## 3. External Base-Station Integration

This rover does not own a Base-Station design. The production Base-Station lives in
`ixhlbxi/arm-drone-lidar-workflow` and is fully specified there
(`base-station/CLAUDE.md`). Summary of what this rover relies on:

| Service | Owner | This rover's role |
|---|---|---|
| NTRIP caster (`ARM_BASE` on `:2101`) | `rtk_base_manager.py` (their repo) | Client (DEC-031) |
| `/run/rtk-base/status.json` schema + atomic-write convention | `rtk_io.py` (their repo) | Same shape mirrored for `/run/rover/status.json` (DEC-033) |
| Heltec V3 LoRa Tx (DISPLAY frames; RTCM_CHUNK is retired, never built — DEC-031 amended 2026-09-23) | `heltec-display/` (their repo) | Not part of the RTK path — the rover's own ESP32 LoRa Tx is status-only (§2.3) |
| T-Deck BLE/LoRa field display | `t-deck/` (their repo) | Not consumed directly by rover; may be extended in v1.1+ to surface rover STATUS |

**Base-Station operating modes** that affect the rover:

- `main` mode — the only mode that serves RTCM to the rover (NTRIP caster running).
- `logging` mode — base is a redundant PPK logger; **no RTCM output**, so the rover's
  NTRIP path is dead in this mode. In `arm_group` profile, this is a hard
  failure-to-start condition the rover should surface clearly.
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
| C — LoRa STATUS only, every 10 s | LoRa frame v2 type `0x01` | On | Off-network case — only channel that survives no IP and no filesystem. The protocol defines LINK (`0x02`) but the rover never sends it (`LoRaPublisher`, `src/rover/telemetry.py`) |

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
    └── Channel C: USB serial to rover ESP32 → LoRa frame v2 STATUS (0x01) only,
            every 10 s — no LINK (0x02) frames are sent
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
| UART | ESP32 ↔ ZED-F9P | RTCM3 | Corrections when the ESP32 is the NTRIP client (DEC-032) |

### 6.2 Wireless Interfaces

| Link | Frequency | Modulation | Purpose |
|------|-----------|------------|---------|
| Base → Rover (NTRIP, sole RTK transport) | 2.4/5 GHz WiFi (or cellular) | TCP/IP | RTCM3 corrections via NTRIP (DEC-031 amended 2026-09-23) |
| Rover → Handhelds | 915 MHz | LoRa SF7/BW125/CR4/5 | STATUS only (LoRa frame v2 type `0x01`), every 10 s — `0x10` (`RTCM_CHUNK`) is retired and reserved, never encoded |

### 6.3 LoRa Parameters

Per LoRa frame v2 (defined in `docs/BASE_STATION_INTEGRATION.md` §4), the rover and
Base-Station agree on:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Frequency | 915 MHz | ISM band (US) |
| Spreading Factor | 7 (fixed — DEC-031 amended 2026-09-23 retired the SF9/RTCM_CHUNK case) | Matches Heltec/T-Deck firmware in arm-drone-lidar-workflow; ~5 kbps throughput |
| Bandwidth | 125 kHz | Standard, good noise immunity |
| Coding Rate | 4/5 | Light FEC overhead |
| Sync Word | `0x12` | Private; matches existing Base-Station handhelds |
| Target Range | 1-3 km LOS | Adequate for STATUS-frame range at a fixed SF7 |

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
| Motor stall | 5 consecutive `stepper.step()` failures trip `_SensorGate` (`src/rover/main.py`) | `sensor_disabled` event logged, `scan_state = SCAN_ERROR` published | Teardown still runs `_return_home` before exit (mast rewinds if it can); operator investigates before the next session |
| Storage full | `SessionLogger` flush raises (`src/rover/logger.py`) | `logger_degraded` is set and every un-flushed record drained from the queue is counted in `lost_records`; both are published in `status.json`/telemetry | Clear storage or swap the card — the logger keeps running degraded rather than stopping |
| LoRa link loss | Serial write failure in `LoRaPublisher` (channel C) | Telemetry-only — channels A/B keep publishing and the scan itself is unaffected | Auto-resume once the ESP32 link comes back |
| GNSS loss | Fix status = NONE | Switch to IMU-only orientation | Re-acquire when sky visible |
| RTK degradation | Visible as `fix_type` / `rtk_age_s` in status — no separate degraded-accuracy flag exists | Logging continues at reduced accuracy | Wait for FIX; `rtk_age_s` shows how stale the last correction is |
| NTRIP 401/404 rejection within the 3 s startup grace, `arm_group` profile | `NtripClient.fatal_error` latches on `NtripFatalError` (bad credentials or an unknown mountpoint) before `_NTRIP_FATAL_GRACE_SEC` elapses, right after `ntrip_client.start()` | `_FatalStartupError` is raised — acquisition aborts before any scan data is written | Process exits with exit code 4; `RestartPreventExitStatus=2 4` in `deploy/systemd/rover.service` stops systemd restarting into the same rejection |
| NTRIP 401/404 rejection discovered mid-session (after the startup grace), `arm_group` profile | Same latch, checked on every status publish | Logged once ("NTRIP fatal mid-session"); `scan_state = SCAN_ERROR` published continuously | Session keeps logging without RTK corrections — no exit, no restart; fix credentials or the mountpoint before the next session |
| Caster rejects the handshake (e.g. a non-200 status — busy mountpoint, 503) | Non-fatal `NtripError` raised while connecting | `NtripClient` retries every 30 s (`_BACKOFF_MAX_SEC`, applied directly — no doubling) | Never share a base session with the drone (§2.3, fact 16) — confirm the caster is free, one client at a time, before connecting |
| Caster drops an already-connected stream (evicted when another client authenticates) | Either a clean close (`recv()` returns no data) or a TCP reset (`ConnectionResetError` on `recv()`) — a reset is the likelier outcome here, since this rover uploads `$GPGGA` every `gga_send_interval_sec` (10 s default) and the caster's `close()` doesn't read it, leaving unread data pending | Clean close: treated as a normal disconnect, backoff resets to 1 s (`_BACKOFF_INITIAL_SEC`). Reset: a transient `OSError` that leaves backoff unchanged, so the reconnect delay doubles from its current value toward the 30 s cap | Either way: never share a base session with the drone (§2.3, fact 16 — CR-005 / sibling NC-1) |
| Pi crash | Watchdog timeout | — | Auto-restart, resume from last timestamp |

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

Applied per scan in `scripts/georef.py` (`lidar_points_to_local`, `session_to_pointcloud`):

```
LiDAR polar (angle, distance)
    │
    │ mount: scan plane = body X-Z (the LiDAR's polar "up" axis becomes body Z)
    ▼
Body frame, mast at 0°
    │
    │ R_z(mast_angle_deg) — the commanded mast rotation for this scan
    ▼
Body frame, mast-rotated
    │
    │ tilt: IMU roll/pitch (Madgwick quaternion at t_scan) with yaw stripped;
    │ for [imu].mount = "platform" the mast rotation is removed from the
    │ quaternion FIRST — a base-mounted IMU (the default) needs no such
    │ correction
    ▼
Tilt-only orientation (roll/pitch, no yaw)
    │
    │ R_z(rest heading) in ENU — yaw comes from the sweep's per-sweep rest
    │ heading, never from in-sweep gyro yaw or GNSS; Madgwick's NWU world
    │ frame is converted to ENU via Rz(-D)·Rz(+90°), D = WMM 2025
    │ declination at the session's GNSS origin
    ▼
World-oriented per-scan points (local ENU, session-relative)
    │
    │ + this scan's GNSS ENU offset from the session origin
    │ minus the antenna lever arm (`[calibration].antenna_offset_m`, rotated
    │ with the mast and the world orientation) when configured
    ▼
Local ENU (metres, origin = first valid GNSS fix)
    │
    │ projection: pyproj → target_crs_epsg (e.g. EPSG 6563, PA North ftUS)
    ▼
Target CRS, ellipsoidal (NAD83(2011)) height
    │
    │ optional: NAVD88 via GEOID18 (source EPSG:6319 → EPSG:<horizontal>+6360
    │ ftUS or +5703 m)
    ▼
Target CRS, NAVD88 height — exits 3 (ellipsoidal files still written) if the
geoid grid is unavailable
```

Heading is labelled `true` (declination known), `magnetic` (no declination available),
or `relative` (no rest-heading magnetometer samples at all — yaw follows the commanded
mast angle instead). The magnetometer is off by default until `mag_offset` is measured,
so an unconfigured rover exports `relative` headings.

### 10.3 Calibration Status (v1.0)

| Transform | Status | Method |
|-----------|--------|--------|
| Mount + mast rotation (`R_z(mast_angle_deg)`) | Implemented | Commanded mast angle from the stepper — exact by construction |
| Tilt (IMU roll/pitch, `[imu].mount` base/platform correction) | Implemented | Madgwick quaternion at scan time; mount is a bench decision (S3-R3), not a numeric calibration |
| Rest heading → true / magnetic / relative | Implemented | Per-sweep magnetometer rest sample + WMM 2025 declination; hard-iron `mag_offset` is still TBD — measure before enabling the magnetometer |
| Antenna lever arm (`[calibration].antenna_offset_m`) | TBD | Measure LiDAR-centre-to-antenna-phase-centre offset, platform frame at mast 0 |
| GNSS ENU offset | Computed | Nearest GNSS fix per scan, relative to the session origin |
| Target CRS projection + NAVD88 | Computed | `pyproj` (e.g. EPSG 6563/6565) + GEOID18; a failed NAVD88 transform exits 3 rather than silently labelling ellipsoidal heights as NAVD88 |

**Note:** `mag_offset` and `antenna_offset_m` still directly affect point cloud accuracy
and heading trueness. Without them measured, v1.0 accuracy is ±5-10 cm (not ±2-3 cm).

### 10.4 Acquisition vs Export Coordinates (DEC-034)

The acquisition stack always logs in **SI units / WGS84** — meters, decimal degrees,
quaternions. The session-config field `[session].target_crs_epsg` records the desired
output CRS but does **not** affect the JSONL hot path.

`scripts/georef.py` reads `metadata.json.session.target_crs_epsg` and converts to that
CRS at export time using `pyproj`. ARM Group sessions typically convert to
NAD83(2011) State Plane in US Survey Foot (e.g., EPSG `6563` for PA North).

| Profile | Acquisition CRS | Default export CRS |
|---|---|---|
| `personal` | WGS84 (EPSG `4326`) / local ENU | WGS84 (no conversion) |
| `arm_group` | WGS84 (EPSG `4326`) / local ENU | Session-config (e.g., `6563` ft-US) |

Re-exporting the same session to a different CRS is supported (`--crs EPSG` override on
`georef.py`) without re-acquiring data.
