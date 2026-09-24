# Hardware Inventory

**Document Status:** v0.11 — reconciled with code (2026-09-23, stage 6 docs refresh)
**Last Updated:** 2026-09-23

> **Rover BOM is unchanged from v0.9.2** except: T-Deck moved out (now owned
> by Base-Station, per DEC-033); ESP32 LoRa role dual-mode (LoRa RTCM relay OR
> NTRIP-over-WiFi client, per DEC-032) — see §7.1 for the `lora_rtcm_relay`
> pending-removal note (backlog `S5-F1`).
>
> **Owner rulings applied here (2026-09-22 super-audit):**
> - **D-005** — the rover needs **one** ZED-F9P and **one** antenna; the
>   second F9P and antenna belong to the sibling Base-Station, not this repo
>   (§1.1, §6.2, §6.3, §10).
> - **D-017** — the LoRa/WiFi board target is the **Heltec WiFi LoRa 32 V3**;
>   an on-shelf Muzi-branded V3 clone is a pin-compatible equivalent (§7.1).
>
> **Cross-references:**
> - Rover-to-Base contract: [`BASE_STATION_INTEGRATION.md`](BASE_STATION_INTEGRATION.md)
> - Base-side wiring (the other end of the LoRa + network cables):
>   `arm-drone-lidar-workflow/base-station/HARDWARE_WIRING_CHECKLIST.md`
> - Stable device symlinks + serial-disambiguation guidance:
>   [`deploy/udev/`](../deploy/udev/) (`/dev/rover-f9p`, `/dev/rover-lidar`, `/dev/rover-esp32`)

---

## 1. Hardware Summary

### 1.1 Acquisition Status

| Category | Owned | Planned | Notes |
|----------|-------|---------|-------|
| Compute | ✅ | — | Pi 4 ready |
| LiDAR | ✅ | — | LD19 ready |
| Motion | ✅ | — | NEMA17 + A4988 ready |
| Camera | ✅ | — | HQ Camera + fisheye ready |
| IMU | ✅ | — | MPU-6050 and MPU-9250 available |
| GNSS (interim) | ✅ | — | Beitian BK122 for testing |
| GNSS (RTK) | — | 🔲 | ZED-F9P × 1 needed, rover-side only (D-005) — SparkFun GPS-RTK-SMA, same board as the Base-Station |
| Antennas | — | 🔲 | u-blox ANN-MB-00 × 1 needed, rover-side only (D-005), same model as the Base-Station |
| LoRa + WiFi (rover) | ✅ | — | Heltec WiFi LoRa 32 V3 ready (Muzi V3 clone equivalent, D-017) — `ntrip_client` kept (DEC-032); `lora_rtcm_relay` pending removal (S5-F1) |
| Handheld monitor | — | — | Owned by Base-Station; **removed from rover BOM** (DEC-033) |
| Power | — | 🔲 | Batteries + regulators needed |
| Network | — | — | Rover Pi shares WiFi/cellular path with Base-Station Pi |

---

## 2. Compute & Control

### 2.1 Raspberry Pi 4

| Attribute | Value |
|-----------|-------|
| **Role** | Main controller, sensor hub, data logger |
| **Model** | Raspberry Pi 4 Model B |
| **RAM** | 4GB or 8GB (TBD confirm) |
| **Storage** | microSD (32GB+) or USB SSD |
| **OS** | Raspberry Pi OS Lite 64-bit |
| **Status** | ✅ Owned |

**Interfaces Used:**
- USB × 3-4 (F9P, ESP32, LiDAR, storage)
- CSI (Camera)
- I2C (IMU)
- GPIO (Stepper control)
- Power: 5V @ 3A via USB-C

**Selection Rationale:**
- Linux ecosystem enables rapid prototyping
- Sufficient compute for sensor fusion and logging
- Camera interface native
- Large community support
- Alternative (MCU-only) rejected due to data handling complexity

---

## 3. Scanning Subsystem

### 3.1 LD19 LiDAR

| Attribute | Value |
|-----------|-------|
| **Role** | 360° distance scanning |
| **Type** | 2D scanning LiDAR (ToF) |
| **Range** | 0.02–12 m (practical ~8-10 m indoors) |
| **Angular Resolution** | ~0.5° (~720 points per revolution) |
| **Scan Rate** | 5–10 Hz (configurable) |
| **Interface** | UART (TTL serial, via USB adapter) |
| **Voltage** | 5V |
| **Status** | ✅ Owned |

**Selection Rationale:**
- Proven in PiLiDAR project
- Low cost, adequate range for indoor/outdoor mapping
- Simple serial interface
- Stacking 2D slices via rotation creates 3D point clouds

**Limitations:**
- Single-plane scan requires mechanical rotation for 3D
- Range limited in bright sunlight
- Not eye-safe at close range (Class 1)

### 3.2 NEMA17 Stepper Motor

| Attribute | Value |
|-----------|-------|
| **Role** | Rotate LiDAR/camera assembly |
| **Type** | NEMA17 bipolar stepper |
| **Step Angle** | 1.8° (200 steps/rev native) |
| **Holding Torque** | ~0.4 N·m (typical) |
| **Voltage** | 12V nominal |
| **Current** | ~1.5-2A per phase |
| **Status** | ✅ Owned |

**Microstepping:** 1/16 (3200 steps/rev effective)

**Selection Rationale:**
- Common, inexpensive, well-documented
- Sufficient torque for light sensor payload
- Precise positioning for scan alignment

### 3.3 A4988 Stepper Driver

| Attribute | Value |
|-----------|-------|
| **Role** | Stepper motor control |
| **Type** | Chopper driver with microstepping |
| **Microstepping** | Up to 1/16 |
| **Max Current** | 2A per phase |
| **Interface** | Step/Dir GPIO |
| **Status** | ✅ Owned |

**Configuration:**
- MS1, MS2, MS3 pins set for 1/16 microstepping
- Current limit set via potentiometer (~1.2A recommended)
- ENABLE pin controlled by Pi for motor power management

---

## 4. Imaging Subsystem

### 4.1 Raspberry Pi HQ Camera

| Attribute | Value |
|-----------|-------|
| **Role** | Visual context capture |
| **Sensor** | Sony IMX477 |
| **Resolution** | 12.3 MP (4056 × 3040) |
| **Interface** | CSI (MIPI) |
| **Lens Mount** | C/CS mount |
| **Status** | ✅ Owned |

**Operating Resolution (v1.0):** 1920×1080 or 1640×1232 (TBD after testing)

**Selection Rationale:**
- High quality sensor for detailed context imagery
- Native Pi interface (no USB bandwidth competition)
- Interchangeable lenses

### 4.2 Arducam M12 Fisheye Lens

| Attribute | Value |
|-----------|-------|
| **Role** | Wide field of view capture |
| **FOV** | ~180° (diagonal) |
| **Mount** | M12 (with CS adapter) |
| **Status** | ✅ Owned |

**Selection Rationale:**
- Captures maximum context per frame
- Reduces number of images needed per scan
- Distortion acceptable for reference imagery (not photogrammetry)

---

## 5. Orientation Subsystem

### 5.1 MPU-9250 (Primary)

| Attribute | Value |
|-----------|-------|
| **Role** | Orientation estimation |
| **Type** | 9-axis IMU (accel + gyro + mag) |
| **Accelerometer** | ±2/4/8/16 g |
| **Gyroscope** | ±250/500/1000/2000 °/s |
| **Magnetometer** | ±4800 µT |
| **Interface** | I2C (address 0x68 or 0x69) |
| **Update Rate** | Up to 1 kHz (gyro/accel) |
| **Status** | ✅ Owned |

**Operating Configuration:**
- Accel: ±4g
- Gyro: ±500 °/s
- Polling rate: 200-400 Hz
- Fusion output: 100 Hz

**Selection Rationale:**
- Magnetometer enables heading estimation indoors (when motor off)
- Well-supported with existing libraries
- Adequate accuracy for scan stabilization

**Magnetometer Constraints:**
- Disable during motor operation (EMI interference)
- Heading comes from a per-sweep rest magnetometer reading with WMM declination —
  never from GNSS or from gyro integration during a sweep (DEC-013 amendment)
- Requires hard/soft iron calibration; `use_magnetometer` stays `false` (heading
  labelled "relative") until `[calibration].mag_offset` is measured

### 5.2 MPU-6050 (Backup/Testing)

| Attribute | Value |
|-----------|-------|
| **Role** | Backup IMU, early testing |
| **Type** | 6-axis IMU (accel + gyro only) |
| **Interface** | I2C |
| **Status** | ✅ Owned |

**Limitations:**
- No magnetometer → no rest-heading source, so exported heading is always
  labelled "relative" (same label used when the 9-DOF IMU's magnetometer is
  off by default)

---

## 6. GNSS Subsystem

### 6.1 Beitian BK122 / u-blox M9 (Interim)

| Attribute | Value |
|-----------|-------|
| **Role** | Baseline testing, non-RTK positioning |
| **Type** | Single-band GNSS receiver |
| **Accuracy** | ~2-3 m CEP (standalone) |
| **Interface** | UART |
| **Status** | ✅ Owned |

**Use Case:**
- Software development and integration testing
- Verify data pipeline before RTK hardware arrives
- Not suitable for production accuracy

### 6.2 u-blox ZED-F9P (Planned — Critical)

| Attribute | Value |
|-----------|-------|
| **Role** | RTK GNSS receiver, rover-side only — the Base-Station owns its own unit (D-005) |
| **Type** | Dual-band (L1/L2) multi-constellation |
| **Constellations** | GPS, GLONASS, Galileo, BeiDou |
| **RTK Accuracy** | 1 cm + 1 ppm (horizontal) |
| **Convergence** | <10 sec (typical with good corrections) |
| **Interface** | USB, UART × 2 |
| **Protocol** | UBX, NMEA, RTCM3 |
| **Status** | 🔲 Planned (need 1 unit, rover-side — D-005) |

**Decided (D-005):** SparkFun GPS-RTK-SMA (ZED-F9P breakout) — the same board
the Base-Station uses, so spares and firmware notes are interchangeable.

**Other vendor options considered:** ArduSimple simpleRTK2B; Beitian BN-880Q (with F9P).

**Selection Rationale:**
- De-facto standard for DIY RTK
- Excellent documentation and community support
- Native RTCM3 input/output
- Dual-band improves fix reliability and convergence

**Quantity Required:** 1 (rover-side only; the Base-Station supplies its own — D-005)

### 6.3 GNSS Antenna — u-blox ANN-MB-00 (Decided, D-005)

| Attribute | Value |
|-----------|-------|
| **Role** | GNSS signal reception, rover-side only — the Base-Station owns its own antenna (D-005) |
| **Type** | u-blox ANN-MB-00 active multi-band patch antenna, same model as the Base-Station |
| **Gain** | Per the ANN-MB-00 datasheet |
| **Ground Plane** | Required (integrated or external) |
| **Connector** | SMA typical |
| **Status** | 🔲 Planned (need 1, rover-side — D-005) |

**Antenna placement:** decided at purchase, not before. Preferred: mount on
the rotation axis (mast centerline), giving a zero LiDAR-to-antenna lever
arm. If the mechanical build puts the antenna off-axis instead, measure the
offset and record it in `[calibration].antenna_offset_m` (§9.2; consumed by
`scripts/georef.py`).

**Selection Criteria:**
- Multi-band mandatory for F9P performance
- Survey-grade or near-survey quality
- Weather resistant for field use
- Ground plane for multipath rejection

**Quantity Required:** 1 (rover-side only; the Base-Station supplies its own — D-005)

---

## 7. Communications Subsystem

### 7.1 Heltec WiFi LoRa 32 V3 (SX1262) — Rover (D-017; Muzi V3 clone equivalent)

| Attribute | Value |
|-----------|-------|
| **Role** | Telemetry transmitter (STATUS only) + NTRIP-over-WiFi RTCM client (DEC-032). NTRIP is now the only RTK path (DEC-031 amended 2026-09-23) — the LoRa RTCM-receive mode below is dead code pending removal (S5-F1) |
| **MCU** | ESP32-S3 (WiFi-capable — required for NTRIP-over-WiFi mode) |
| **Radio** | Semtech SX1262 |
| **Frequency** | 915 MHz (US ISM) |
| **Power** | Up to +22 dBm |
| **Interface** | USB (to Pi for telemetry frames), UART (to F9P UART2 for RTCM — both firmware modes write here) |
| **Status** | ✅ Owned (Heltec WiFi LoRa 32 V3; a Muzi-branded V3 clone on the shelf is a pin-compatible equivalent, D-017) |

**Firmware Scope (v0.10 overhaul, Phase C):**

Two firmware modes selected via `platformio.ini` env (lives in `firmware/esp32-rover/`):

- **Mode A — `lora_rtcm_relay`** (pending removal, backlog `S5-F1`): historically received RTCM_CHUNK (LoRa frame v2 type `0x10`, now retired and reserved) from the Base-Station Heltec and wrote the payload to F9P UART2. That RTCM-receive path is dead now that NTRIP is the only RTK path (DEC-031 amended 2026-09-23); it awaits a PlatformIO build + flash to remove it. It still transmits rover STATUS (0x01) frames — it never sends LINK (0x02); that frame type is defined but never used.
- **Mode B — `ntrip_client`** (kept, DEC-032): Connects to the Base-Station NTRIP caster
  over WiFi, writes RTCM3 to F9P UART2 directly. Same STATUS-only Tx as Mode A.
  This is the supported RTK path — it does not depend on LoRa range, and
  keeps RTCM delivery off the Pi (preserves the DEC-006-style "Pi out of
  correction path" robustness).

WiFi credentials and NTRIP password live in a non-committed `include/config.h`
(`include/config.h.example` is the template). No OTA updates in v1.0.

> **Compatibility check:** confirm rover ESP32 model has both LoRa **and** WiFi
> (the Heltec/Muzi V3 does — bare SX1262 breakouts do not). Mode B requires WiFi.

### 7.2 LILYGO T-Deck — **Removed from rover BOM (DEC-033)**

The T-Deck is now owned by the `arm-drone-lidar-workflow` Base-Station, where its
firmware lives at `base-station/t-deck/`. It is **not flashed with rover-specific
firmware** in this project.

When the rover is operated in `arm_group` profile, the operator's existing
Base-Station T-Deck can surface rover STATUS via either:

- **Channel A** — the `/run/rover/status.json` file (if the rover and Base-Station Pis
  share a filesystem mount or replicate it), or
- **Channel C** — receiving LoRa STATUS (LoRa frame v2 type `0x01`) directly. LINK
  (`0x02`) is defined in the protocol but the rover never sends it. Requires a
  one-time T-Deck firmware extension to recognize rover frame types alongside
  the existing DISPLAY (`0x20`) handling.

The second-T-Deck-dedicated-to-rover idea from v0.9 is deferred. The rover's own HTTP
`/status` endpoint covers development and bench observability.

### 7.3 Network / Base-Station Connectivity

**Rover Pi must have IP reach to the Base-Station Pi (`rtk-base.local`)** in
`arm_group` profile, and ideally also in `personal` profile (for NTRIP-primary RTK).
Three supported field topologies, no new hardware required if any is workable:

1. **Shared WiFi** — Both Pis associate with the same AP (truck-mounted router, office
   network). Simplest; works on bench.
2. **Base-Station as AP** — Base-Station Pi runs `hostapd`/`dnsmasq` to act as its own
   WiFi access point; rover Pi joins it. Documented in
   `arm-drone-lidar-workflow/base-station/FIELD_DEPLOY_CHECKLIST.md`.
3. **Phone hotspot** — Phone bridges both Pis. Matches the ARM Group field-cellular
   pattern.

**Credentials handling:** the rover's NTRIP password is supplied via environment
variable (default name `ROVER_NTRIP_PASSWORD`), set via systemd `EnvironmentFile=`
or shell export. Mirrors the Base-Station's `RTK_NTRIP_PASSWORD` convention. Never
committed to config files.

**LoRa range:** LoRa is status-only (STATUS every 10 s, SF7/BW125/CR4/5, ~1–3 km
LOS in practice) — it no longer carries corrections. NTRIP is the only RTK path
(DEC-031 amended 2026-09-23); the historical LoRa-RTCM relay (`lora_rtcm_relay`,
§7.1) is dead code pending removal (S5-F1). Outside NTRIP network reach (WiFi or
cellular to the Base-Station), the rover degrades to non-RTK 3D fix (~2–3 m
accuracy).

### 7.4 CircuitMess Chatter (Optional)

| Attribute | Value |
|-----------|-------|
| **Role** | Optional relay nodes, backup terminal |
| **Type** | LoRa transceiver with display |
| **Status** | ✅ Owned |

**Use Case:** Range extension relay or backup monitoring (deferred)

---

## 8. Power Subsystem (Planned)

### 8.1 Compute Power (5V Rail)

| Attribute | Requirement |
|-----------|-------------|
| **Type** | USB-C PD Power Bank |
| **Capacity** | 20,000-30,000 mAh (74-111 Wh) |
| **Output** | 5V @ 3A minimum (USB-C PD preferred) |
| **Consumers** | Pi 4, Camera, ESP32 |
| **Status** | 🔲 Planned |

### 8.2 Motor Power (12V Rail)

| Attribute | Requirement |
|-----------|-------------|
| **Type** | LiPo 3S (11.1V) or 12V DC pack |
| **Capacity** | 2000-5000 mAh |
| **Output** | 12V @ 2A peak |
| **Consumers** | NEMA17 via A4988 |
| **Status** | 🔲 Planned |

### 8.3 Logic Power (3.3V Rail)

| Attribute | Requirement |
|-----------|-------------|
| **Type** | Switching regulator |
| **Input** | 5V |
| **Output** | 3.3V @ 1A minimum |
| **Consumers** | ZED-F9P, MPU-9250 |
| **Status** | 🔲 Planned |

**Critical Note:** Do NOT power F9P or IMU from Pi's 3.3V GPIO rail (insufficient current, unstable).

### 8.4 Power Distribution Summary

```
┌─────────────────┐     ┌─────────────────┐
│  USB-C PD Bank  │     │   12V Battery   │
│  (20-30 Ah)     │     │   (3S LiPo)     │
└────────┬────────┘     └────────┬────────┘
         │ 5V                    │ 12V
         │                       │
    ┌────┴────┐             ┌────┴────┐
    │         │             │         │
    ▼         ▼             ▼         │
┌───────┐ ┌───────┐    ┌───────┐     │
│  Pi 4 │ │ ESP32 │    │ A4988 │     │
│       │ │(USB)  │    │       │     │
└───────┘ └───────┘    └───┬───┘     │
    │                      │         │
    │ 5V out               │         │
    ▼                      ▼         │
┌──────────┐          ┌───────┐     │
│  3.3V    │          │NEMA17 │◄────┘
│  Reg     │          └───────┘
│  (≥1A)   │
└────┬─────┘
     │ 3.3V
     │
┌────┴────┐
│         │
▼         ▼
┌───────┐ ┌───────┐
│ZED-F9P│ │MPU-   │
│       │ │9250   │
└───────┘ └───────┘
```

---

## 9. Mechanical Components (TBD)

### 9.1 Enclosure

| Attribute | Target |
|-----------|--------|
| **Weather Resistance** | Splash resistant (no formal IP rating v1.0) |
| **Material** | 3D printed or off-the-shelf project box |
| **Status** | 🔲 TBD |

### 9.2 Mounting

Everything rotates with the case through the sweep **except the base** —
the stepper body and the tripod mount, which stay fixed (2026-09-23 design
session, spec §6a). That "everything" includes the Pi, the ESP32, and the
battery, not just the LiDAR and camera.

| Component | Mount Type | Status |
|-----------|------------|--------|
| LiDAR + Camera | Rotating case on stepper shaft | Rotates with the stepper |
| Pi + Electronics (compute, ESP32, battery) | Rotating case on stepper shaft | Rotates with the stepper; 🔲 TBD (mechanical enclosure) |
| IMU | `[imu].mount`: `base` (default — fixed to the stepper body/tripod mount; its cable crosses the rotating joint) or `platform` (on the rotating case) | Bench decision (S3-R3); physical mount 🔲 TBD |
| GNSS Antenna | Case-mounted on the rotation axis (mast centerline), preferred — zero lever arm and rotates with the case; otherwise fixed off-axis on the stepper body/tripod, with `[calibration].antenna_offset_m` measured (§6.3) | Decided at purchase |

**Rotation:** the mast sweeps 360° forward, then rewinds at `rewind_rpm` in
≤45° chunks (DEC-015 amended 2026-09-23); no lidar/IMU records are logged
during the rewind. Cabling to the rotating components uses a flexible cable
loop, not a slip ring — the rewind exists precisely because there is no slip
ring to allow continuous rotation.

### 9.3 Weight Budget

| Target | Value |
|--------|-------|
| Rover unit (complete) | < 3 kg |
| Base station | < 2 kg (excluding tripod) |

---

## 10. Bill of Materials — To Purchase

| Item | Qty | Est. Cost | Priority |
|------|-----|-----------|----------|
| ZED-F9P board (SparkFun GPS-RTK-SMA) | 1 | $200-250 | **Critical** |
| u-blox ANN-MB-00 GNSS antenna | 1 | $50-100 | **Critical** |
| 3.3V switching regulator (1A+) | 1-2 | $5-15 | High |
| USB-C PD power bank (20+ Ah) | 1 | $40-80 | High |
| 12V battery pack (3S LiPo or equiv) | 1 | $30-50 | High |
| USB-serial adapters (if needed) | 2-3 | $5-10 ea | Medium |
| Connectors, cables, mounting hardware | — | $30-50 | Medium |
| 3D printed enclosure/mounts | — | $20-50 | Low |

**Estimated Total:** $385-640 for remaining components (D-005 halves the F9P
and antenna lines from the v0.9.2 two-unit BOM to one each). Arithmetic —
low end: 200 + 50 + 5 + 40 + 30 + 10 + 30 + 20 = **385**; high end:
250 + 100 + 30 + 80 + 50 + 30 + 50 + 50 = **640**.

---

## 11. Recommended Vendors

| Component | Recommended Sources |
|-----------|---------------------|
| ZED-F9P | SparkFun, ArduSimple, Digi-Key |
| GNSS Antennas | ArduSimple, Beitian, Tallysman |
| Power Banks | Anker, RAVPower (ensure PD support) |
| LiPo Batteries | Amazon, HobbyKing (match connector) |
| Regulators | Pololu, Adafruit, Amazon |
| Connectors | Adafruit, SparkFun, Amazon |
