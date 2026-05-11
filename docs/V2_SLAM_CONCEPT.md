# V2 Concept — SLAM-Capable LiDAR Platform

**Document Status:** Active concept / pre-planning
**Last Updated:** 2026-05-11

> This document captures early thinking on a second-generation build that extends V1
> into a true SLAM-capable platform, with community research findings incorporated.
> Hardware choices and paths forward are informed by real-world builds documented below.
> Still pre-specification — decisions are directional, not final.

---

## 1. Motivation

V1 is a stationary scan platform: stop, rotate the LD19 through a stepper-driven arc to
stack 2D slices into a 3D point cloud, move, repeat. This works well for controlled outdoor
RTK surveys but has hard limits:

- Cannot scan while moving (motion distortion destroys the stacked-slice model)
- Indoor / GNSS-denied environments degrade to orientation-stabilized relative clouds only
- No real-time pose tracking or map building
- Mechanical rotation is the 3D source — remove motion and you have a 2D scanner

V2 targets two use modes:

1. **Stationary** — high-density 3D scan at a fixed position, native 3D without the stepper
   trick, georeferenced via RTK GNSS
2. **Mobile** — continuous LiDAR-IMU SLAM while moving, with GNSS priors to bound drift;
   mountable on a vehicle or handheld cart

A single hardware platform handles both modes via software profile selection.

---

## 2. Core Hardware Changes

### 2.1 LiDAR — LD19 → Livox MID-360S

**Recommendation: Livox MID-360S** (updated from MID-360)

The MID-360S is Livox's current-generation replacement for the MID-360, released in 2025.
Same housing dimensions (mechanically drop-in compatible), full SDK backward compatibility,
but with meaningful improvements relevant to this build:

- **Improved point cloud uniformity** — more consistent density across the full 360°×59° FOV,
  which directly reduces the need to tune SLAM parameters to compensate for weak spots
- **Better anti-interference** — improved filtering for outdoor/multi-sensor environments;
  relevant for vehicle use where stray IR is present
- **100 m max range** (vs. 70 m on original) — useful for open outdoor mapping sessions
- **Actively maintained SDK** — Livox is targeting the S version for firmware updates going
  forward

The MID-360S requires Livox SDK v1.3.0+ and Livox Viewer 2 v2.5.0+. Both are current
releases and a new build should start there regardless.

**Why Livox over Velodyne (resolved):** The community build evidence below confirms that
the Livox ecosystem around FAST-LIO2 is more active and better supported than VLP-16 for
new builds. VLP-16 has the larger historical research base, but most current DIY SLAM work
is targeting Livox natively. The non-repetitive scan pattern is a genuine advantage for
scan-matching in feature-sparse environments. Unless a used VLP-16 becomes available at a
price point that justifies the ecosystem trade-off, MID-360S is the path.

**Alternatives still worth knowing:**

| Unit | Price (approx.) | Notes |
|---|---|---|
| Unitree L1 | ~$500 | 18-line, good budget entry; less community SLAM support |
| Velodyne VLP-16 | ~$1,500 used | Research workhorse; LIO-SAM originally designed for it |
| Hesai XT16 | ~$1,200 | Solid mid-range, strong ROS support |
| Ouster OS0-32 | ~$3,500 | Professional tier; familiar from RESEPI payload |

**Impact on existing hardware:** NEMA17 stepper + A4988 driver become vestigial once a
multi-beam LiDAR is fitted. The mechanical frame is retained as a mount but the rotation
assembly is removed.

---

### 2.2 IMU — MPU-9250 → Tactical-Grade MEMS

The MPU-9250 is a consumer part. LiDAR-IMU SLAM stacks place the IMU in a tight fusion
loop requiring >200 Hz output and low in-run bias instability. Poor noise characteristics
cause pose drift that scan-matching cannot recover from.

**Primary candidate: ICM-42688-P breakout** (~$20–50)

- In-run bias stability ~3°/hr — significantly better than MPU-9250
- Up to 8 kHz output rate via SPI (deterministic timing, important for LiDAR-IMU sync)
- Standard pairing for Livox + FAST-LIO2 community builds; widely documented

**Upgrade for vehicle use: ADIS16470** (~$200)

- Industrial MEMS, ~10× better noise floor than ICM-42688
- Better vibration rejection — relevant when mounted on a truck or UTV
- SparkFun breakout available

**Note on imu.py:** The Madgwick fusion in `imu.py` is not reused for SLAM. Raw IMU samples
are handed directly to the SLAM stack. The driver code is stripped back to a raw sample
publisher feeding a ROS2 topic.

**Note on built-in IMUs:** The MID-360 and MID-360S both include an onboard IMU. Community
experience (including the NTU 2024 academic study and Belgian Defence mapping paper) shows
the built-in IMU is functional for SLAM but benefits meaningfully from an external
higher-quality unit, especially in vehicle-mounted or vibration-heavy scenarios. The
built-in IMU is a viable starting point for Phase 1 bench work.

---

### 2.3 Compute — Raspberry Pi 4 → Jetson Orin NX

The Pi 4 will fall over trying to run FAST-LIO2 in real time. SLAM is matrix-math bound,
not I/O bound.

**Confirmed: NVIDIA Jetson Orin NX 8GB + JetPack 6.0** (~$500)

A May 2024 YouTube demonstration confirmed FAST-LIO ROS2 running on exactly this
combination (Orin NX 16GB + JetPack 6.0 + ROS 2 Humble + MID-360). The 8GB variant is
the minimum acceptable configuration; the 16GB gives more headroom for the map during
longer mobile sessions.

Key platform notes:
- **ROS 2 Humble** is the confirmed distribution for JetPack 6 (Ubuntu 22.04 base)
- **Isaac ROS** (NVIDIA's accelerated robotics framework) provides Docker containers that
  simplify dependency management for ROS2 on Jetson; recommended as the dev environment
  rather than bare-metal ROS2 install
- CUDA is available for downstream processing (meshing, feature extraction, visual SLAM)
- Installing ROS2 + sensor drivers on Jetson is non-trivial without Isaac ROS containers —
  budget integration time; see ntcurran.com notes on Orin NX build experience

**Budget option: Orange Pi 5 Plus** (~$120)

- RK3588, 8-core, Mali GPU
- Community builds of FAST-LIO2 exist and run; acceptable for stationary mode or low-speed
  vehicle work (<15 km/h)

---

## 3. What Carries Forward from V1

| Component | V2 Status | Notes |
|---|---|---|
| ZED-F9P RTK GNSS | ✅ Keep | GNSS-aided SLAM is a force multiplier; see Section 6 |
| HQ Camera + Fisheye | ✅ Keep | Opens LiDAR-Visual-Inertial path; see Section 8 |
| ESP32 LoRa (RTCM Rx + telemetry Tx) | ✅ Keep | No change needed |
| T-Deck monitoring console | ✅ Keep | No change needed |
| RTK base station | ✅ Keep | Still valuable for georeferenced stationary output |
| Power architecture (split compute/motor rails) | ✅ Keep | May upsize 5V bank for Jetson |
| `gnss.py` driver | ✅ Reuse | Minimal changes; expose as ROS2 node |
| `camera.py` driver | ✅ Reuse | Adapt for ROS2 topic publication |
| `imu.py` | ⚠️ Rework | Strip Madgwick; expose raw samples on ROS2 IMU topic |
| `lidar.py` | ❌ Replace | LD19 protocol → livox_ros_driver2 (official ROS2 driver) |
| `stepper.py` | ❌ Remove | No longer needed |
| `logger.py` (JSONL) | ❌ Replace | ROS2 bag (.db3) for all sensor data |
| `main.py` orchestration | ❌ Rewrite | Step→scan→log → ROS2 node launch file |

---

## 4. Community Builds & Prior Art

Before committing to an architecture, it is worth documenting who has already done this
and what they found.

### 4.1 FAST-LIO2 + Jetson Orin NX + MID-360 (confirmed working)

A May 2024 demonstration (YouTube) confirmed FAST_LIO_ROS2 running on Jetson Orin NX 16GB,
JetPack 6.0, ROS 2 Humble, with Livox MID-360. This is the exact target stack. The
`Ericsii/FAST_LIO_ROS2` repository is the ROS2 port of the original HKU FAST-LIO2.

### 4.2 NTU Final Year Project (2024)

Nanyang Technological University published a study specifically evaluating SLAM algorithms
for LiDAR-inertial odometry using the Livox MID-360. Three algorithms were tested;
FAST-LIO emerged as the recommended choice for this sensor combination. Confirms fitness
for autonomous robot / UAV use cases.

### 4.3 TUM RoboRacer / F1Tenth (IEEE IV 2025)

TU Munich's autonomous racing team (RoboRacer, formerly F1Tenth) published a full stack in
March 2025 integrating the Livox MID-360 into their platform with Jetson and ROS2
(`TUM-AVS/RoboRacer-3DLiDAR`). Their stack uses `lidarslam_ros2` for SLAM mapping and
localization. Verified March 2025. Includes full mount and wiring documentation for the
MID-360 on a vehicle platform.

### 4.4 LIO-Livox — Car Platform, Highway Speed (Livox official)

Livox's own LIO-Livox system (`Livox-SDK/LIO-Livox`) is explicitly designed for car
platforms in large-scale outdoor environments. Published demonstrations include:
- Passing through a 4 km tunnel at highway speed (~80 km/h) using a Livox Horizon
- Robust localization in dense urban traffic with most of the FOV occluded by vehicles
- Dynamic object filtering (ground / background / foreground segmentation)

The system now supports MID-360. This is the validated reference for high-speed vehicle
mounting. It uses feature extraction + tightly coupled sliding window IMU fusion. This is
a more complex architecture than FAST-LIO2 but the performance envelope at speed is
directly relevant to mobile mode.

### 4.5 Belgian Defence / Emergency Services Wearable Mapping (2024)

A Belgian research group published a paper on ultra-portable 3D mapping using Livox MID-360
for emergency response. Notable for demonstrating:
- Velcro-mounted (non-rigid) dual-sensor configuration on a tactical jacket
- Outdoor operation at 40 m range
- Combination with camera sensors (Luxonis OAK-D Pro Wide) for colored point clouds
- Body-worn / handheld form factor as a viable deployment mode

Directly relevant to the handheld/cart mode of V2.

### 4.6 LiDAR-Visual-Inertial SLAM on Jetson Orin NX (valentinomario)

GitHub repository `valentinomario/LiDAR-Visual-Inertial-SLAM` implements ROS2
LiDAR-Visual-Inertial SLAM for Jetson Orin NX using Livox MID-360 and Arducam IMX219. The
Arducam IMX219 is a CSI camera, comparable to the HQ Camera already in the V1 build. This
is a direct reference implementation for the V2.1 visual integration path.

---

## 5. SLAM Stack — Resolved Architecture

The open question from v0.1 ("FAST-LIO2 vs LIO-SAM, do we need loop closure") is now
resolved by research.

### 5.1 Recommended Primary Stack: FAST-LIO-SAM

**Do not run bare FAST-LIO2 for mobile mapping.** FAST-LIO2 alone has no loop closure.
For any session covering more than a few hundred meters, accumulated odometry drift will
produce visible map discontinuities that GNSS alone may not fully correct.

The community solution is **FAST-LIO-SAM**: FAST-LIO2 as the front-end (LiDAR-IMU tight
fusion via ESIKF) combined with a factor graph back-end (from LIO-SAM's architecture) for
loop closure and global consistency. This gives the computational efficiency and Livox
compatibility of FAST-LIO2 with the map quality of a full SLAM system.

Why not bare LIO-SAM: LIO-SAM is a loosely coupled system and benchmarking evidence
(MSC-LIO paper, R3LIVE dataset evaluations) shows it can exhibit significant drift and
trajectory jumps on some sequences where FAST-LIO2 remains stable. LIO-SAM's loop closure
is its main advantage; FAST-LIO-SAM captures that advantage without the loose-coupling
limitations.

**Reference implementations:**
- `Yixin-F/better_fastlio2` — FAST-LIO-SAM + dynamic removal + multi-session mapping
  (ICRA 2022 Kim) + online relocalization (ICRA 2025). Active as of 2025.
- `hku-mars/LTA-OM` — FAST-LIO2 + Stable Triangle Descriptor loop closure + multi-session
  localization and mapping. Published January 2024.

### 5.2 Algorithm Comparison Summary

| Stack | Loop Closure | Livox Native | Compute | Recommended For |
|---|---|---|---|---|
| FAST-LIO2 (bare) | ❌ | ✅ | Low | Stationary; short mobile sessions |
| FAST-LIO-SAM | ✅ | ✅ | Medium | Primary mobile stack |
| LIO-SAM | ✅ | Adapter needed | Medium-High | VLP-16 / OS1 builds |
| KISS-ICP | ❌ | ✅ | Very low | Stationary / offline processing |
| LTA-OM | ✅ + multi-session | ✅ | Medium | Long sessions, return visits |
| LIO-Livox | ✅ (segmentation) | ✅ | Medium | High-speed vehicle mode |

### 5.3 Stationary Mode Stack

For stationary scans, loop closure is irrelevant. **KISS-ICP** or bare FAST-LIO2 is
sufficient and much simpler to set up. Stationary output fed through standard georeferencing
(transform to GNSS position, export PLY/LAS) as in V1.

---

## 6. GNSS-Aided SLAM — Quantified

**Key finding from RTK-SLAM dataset (arXiv 2604.07151, April 2026):**

A dataset and evaluation specifically designed for RTK + SLAM fusion was published with
direct comparison of LiDAR-aided methods under mixed GNSS conditions (open sky, building
obstruction, fully GNSS-denied underpasses). Results for FAST-LIO-SAM:

- **Drift in GNSS-denied zones: 9.2 cm/min (0.25% of path length)**
- **Standalone RTK degrades rapidly** once signal quality deteriorates
- In open-sky environments, RTK effectively anchors trajectories globally
- LiDAR-aided offline (batch pose graph optimization) outperforms online estimates —
  suggesting post-processing can further improve output quality after a vehicle session

This directly validates the architecture: use RTK as the global anchor when sky is
available, LiDAR-IMU odometry as the dead-reckoning bridge when it isn't. The ZED-F9P is
not redundant in mobile mode — it is the component that prevents unbounded drift at the
session level.

**Practical architecture for this build:**

```
ZED-F9P RTK fix → seed initial pose in factor graph
ZED-F9P position updates → GNSS factor (weighted by fix quality: FIX > FLOAT > NONE)
FAST-LIO2 front-end → odometry factor between keyframes
Loop closure detector (STD or ScanContext) → loop factor on revisit
Factor graph optimizer (GTSAM or g2o) → globally consistent trajectory
```

When GNSS is NONE (indoor / underground), FAST-LIO-SAM runs on odometry + loop closure
alone. 9.2 cm/min drift is acceptable for most mapping sessions up to ~30 minutes.

---

## 7. ROS2 Architecture — Resolved

**Decision: ROS2 Humble on JetPack 6 is the path.** This is confirmed working and the
community has converged here for Jetson-based LiDAR SLAM in 2024–2025.

Custom Python orchestration is not a viable alternative for real-time SLAM — the sensor
fusion math, tf tree management, and visualization tooling in ROS2 would take months to
replicate and maintain. ROS2 adds setup complexity but eliminates a much larger software
development burden.

**Setup path:**

1. Flash Jetson Orin NX with JetPack 6.0 (Ubuntu 22.04)
2. Install Isaac ROS CLI and container framework (simplifies dependency management)
3. Build `livox_ros_driver2` for MID-360S connectivity (Ethernet, static IP 192.168.1.1XX)
4. Build `FAST_LIO_ROS2` (`Ericsii/FAST_LIO_ROS2`) inside Isaac ROS dev container
5. Add FAST-LIO-SAM loop closure layer (`Yixin-F/better_fastlio2` or LTA-OM)
6. Adapt V1 sensor drivers as ROS2 nodes publishing standard message types

**Note on MID-360S network config:** The MID-360S uses Ethernet (not USB), static IP. The
Jetson Orin NX has a Gigabit Ethernet port; a direct connection with host IP set to
192.168.1.50 (or similar, same subnet) is the standard setup per Livox Quick Start Guide.
Wireless is not supported for sensor data.

**Isaac ROS Visual SLAM** (NVIDIA's GPU-accelerated vSLAM) is available and runs on Jetson,
but targets ROS2 Jazzy on current releases. Worth tracking for the V2.1 visual-inertial
path.

---

## 8. PPS Time Synchronization — Resolved

**Decision: Implement PPS sync in V2.0.** V1 deferred this; V2 mobile mode depends on it
for tight LiDAR-IMU-GNSS temporal alignment.

**Confirmed working pattern:**

```
ZED-F9P PPS pin → Jetson GPIO pin → GPSD + Chrony → system clock sync
```

This pattern is documented in NVIDIA developer forums with ZED-F9P + Jetson Xavier NX
(same GPIO architecture as Orin NX). Typical residual offset is ~6–7 ms with software
PPS via Chrony, which is acceptable for LiDAR-IMU sync at 10 Hz scan rates.

**Advanced option: Jetson GTE (Generic Timestamping Engine)**

Jetson Orin has hardware GPIO timestamping (GTE) which can timestamp GPIO events with
sub-microsecond precision. This requires kernel configuration (`CONFIG_TEGRA_HTS_GTE=y`)
and DTB modification, but eliminates the software timing jitter of Chrony-based sync.
Relevant primarily if point-per-shot timestamp accuracy matters (future multi-return or
dense scan modes). For V2.0 SLAM, software Chrony sync is sufficient.

**Implementation steps:**
1. Connect ZED-F9P PPS pin to a Jetson GPIO pin (3.3V logic; confirm level compatibility)
2. Install `gpsd` and configure for NMEA over USB from F9P
3. Configure `chrony` with PPS source
4. Validate with `ppstest` — should see sub-10ms offset on first attempt
5. (Optional) Enable GTE kernel support for hardware timestamping

---

## 9. Visual Integration Path (V2.1)

The HQ Camera + Fisheye from V1 is retained and opens the LiDAR-Visual-Inertial SLAM path
for V2.1. This is deferred from V2.0 but worth documenting the forward path now.

**Primary reference: FAST-LIVO2** (arXiv 2408.14035, August 2024)

FAST-LIVO2 fuses IMU, LiDAR, and image measurements through a sequential update ESIKF
(the same filter architecture as FAST-LIO2). Key property: when LiDAR degenerates (e.g.,
entering a featureless corridor), the visual measurement takes over. This is directly
relevant to the indoor/GNSS-denied use case where LiDAR alone may struggle.

The paper demonstrates operation across indoor-to-outdoor transitions with large illumination
variation — relevant for field survey workflows.

**Reference implementation for this hardware combination:**

`valentinomario/LiDAR-Visual-Inertial-SLAM` — ROS2 implementation specifically for
Jetson Orin NX + Livox MID-360 + Arducam IMX219 (CSI camera). The Arducam IMX219 is
directly comparable to the V1 HQ Camera on CSI. This is a near-exact hardware match and
should be the starting reference for V2.1 implementation.

---

## 10. Vehicle-Mounted Operation — Notes

**High-speed vehicle (>30 km/h): LIO-Livox architecture**

For vehicle speeds above roughly 30 km/h, FAST-LIO2's standard motion distortion
compensation starts to fall behind. LIO-Livox (Livox's own stack, `Livox-SDK/LIO-Livox`)
is specifically validated at highway speeds and includes dynamic object segmentation to
handle traffic. It supports MID-360. For slow UTV or pedestrian-cart use, FAST-LIO-SAM
is sufficient and simpler.

**Vibration isolation**

This is not optional for vehicle mounting. Two approaches:

1. **Passive isolation mount** (~$50–100): Rubber vibration dampers, 3D-printed adapter.
   Adequate for low-speed vehicles (UTVs, carts, slow trucks). Community reports that
   unshielded vibration causes scan distortion that software cannot fully recover.
2. **Active isolation / ADIS16470 IMU**: If budget allows, upgrading to ADIS16470 provides
   industrial-grade vibration rejection in the IMU itself, which relaxes mechanical
   isolation requirements.

**Power from vehicle**

Vehicle 12V rail can power the compute via a 12V→5V USB-C PD converter (replacing the
power bank). Motor power rail already matches. Ensure proper fusing and isolation from
vehicle electrical noise (especially relevant near engine or large alternators).

**Weatherproofing**

The MID-360S is rated IP67 — it can handle rain. The Jetson and F9P are not. A simple
weatherproof enclosure (project box or 3D-printed housing with a gasket) is sufficient for
most field conditions. Full IP65 enclosure is a V2.2 consideration.

---

## 11. Updated Hardware Summary

| Item | Recommendation | Est. Cost |
|---|---|---|
| LiDAR | Livox MID-360S | ~$700 |
| External IMU | ICM-42688-P (starter) or ADIS16470 (vehicle) | ~$30 / ~$200 |
| Compute | Jetson Orin NX 8GB (minimum) | ~$500 |
| NVMe SSD | 500 GB for map storage | ~$60 |
| Vibration isolation | Passive rubber mount | ~$60 |
| Ethernet cable + adapter | MID-360S to Jetson | ~$20 |
| Misc (power, cables, mount hardware) | | ~$100 |
| **Total new hardware** | | **~$1,470 – $1,640** |

V1 components retained: ZED-F9P ×2, antennas, HQ Camera, ESP32 LoRa, T-Deck, power
hardware (may upsize 5V bank for Jetson draw).

---

## 12. Revised Open Questions

| Question | Status | Resolution / Notes |
|---|---|---|
| Livox vs. Velodyne | ✅ Resolved | Livox MID-360S; ecosystem advantage confirmed |
| ROS2 vs. custom Python | ✅ Resolved | ROS2 Humble + Isaac ROS containers on JetPack 6 |
| PPS synchronization | ✅ Resolved | F9P PPS → GPIO → Chrony+GPSD; GTE for advanced sync |
| Loop closure architecture | ✅ Resolved | FAST-LIO-SAM; not bare LIO-SAM |
| Camera integration (V2.1) | 🔵 Deferred | FAST-LIVO2 + valentinomario repo as reference |
| Extrinsic calibration procedure | 🔵 Open | LiDAR↔IMU↔camera offsets need calibration jig or target-based procedure |
| High-speed vehicle (>30 km/h) | 🔵 Open | LIO-Livox is the candidate; needs bench testing |
| Multi-session / return-to-site mapping | 🔵 Open | LTA-OM supports this; evaluate in V2.1 |
| Map format and downstream pipeline | 🔵 Open | ROS2 bag → CloudCompare / PDAL for PLY/LAS export |

---

## 13. Rough Phase Plan

| Phase | Goal | Key Deliverables |
|---|---|---|
| 1 | Source hardware; bench connectivity | MID-360S point cloud in RViz2 on Jetson |
| 2 | FAST-LIO2 stationary map on Jetson | Known-space scan compared to V1 output |
| 3 | PPS sync implementation | GNSS time locked to Jetson system clock |
| 4 | FAST-LIO-SAM with GNSS prior | Indoor walk; drift measured vs. GNSS checkpoint |
| 5 | Stationary mode validation | Georeferenced PLY vs. V1 scan; accuracy report |
| 6 | Vibration isolation mount design | Hardware test on test vehicle at low speed |
| 7 | Mobile mode field test | Parking lot loop; map closure quality assessed |
| 8 | V2.0 freeze | Stationary + mobile validated; code and docs frozen |
| 9 | V2.1 planning | Visual-inertial integration; high-speed vehicle test |

---

## 14. Key References

| Resource | Relevance |
|---|---|
| `Ericsii/FAST_LIO_ROS2` | FAST-LIO2 ROS2 port; confirmed Orin NX + MID-360 |
| `Yixin-F/better_fastlio2` | FAST-LIO-SAM with loop closure + multi-session |
| `hku-mars/LTA-OM` | FAST-LIO2 + loop closure; January 2024 |
| `Livox-SDK/LIO-Livox` | Vehicle-speed LiDAR-inertial; car platform validated |
| `TUM-AVS/RoboRacer-3DLiDAR` | MID-360 on vehicle platform; March 2025 |
| `valentinomario/LiDAR-Visual-Inertial-SLAM` | Orin NX + MID-360 + camera; V2.1 reference |
| arXiv 2604.07151 (RTK-SLAM dataset) | RTK + FAST-LIO-SAM drift quantification |
| arXiv 2408.14035 (FAST-LIVO2) | LiDAR-visual-inertial fusion with Livox |
| NVIDIA Dev Forums (ZED-F9P + Jetson PPS) | PPS sync confirmed working pattern |

---

## 15. Changelog

| Version | Date | Notes |
|---|---|---|
| v0.2.0 | 2026-05-11 | Major update: community research incorporated; open questions resolved; FAST-LIO-SAM as primary stack; GNSS drift quantified; PPS sync path confirmed; visual path documented |
| v0.1.0 | 2026-05-11 | Initial rough concept; based on V1 architecture review |
