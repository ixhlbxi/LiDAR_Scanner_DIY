# V2 Concept — SLAM-Capable LiDAR Platform

**Document Status:** Rough concept / pre-planning
**Last Updated:** 2026-05-11

> This document captures early thinking on a second-generation build that extends the V1
> stationary scanner into a true SLAM-capable platform. It is intentionally rough — the goal
> is to record intent and key decisions before hardware is selected, not to produce a complete
> specification.

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

A single hardware platform should handle both modes via software profile selection.

---

## 2. Core Hardware Changes

### 2.1 LiDAR — LD19 → Multi-Beam Unit

The LD19 is a single-plane 2D scanner. It cannot produce 3D data independently of the
stepper rotation, which makes it incompatible with motion-based SLAM. A multi-beam rotating
unit is required.

**Primary candidate: Livox Mid-360** (~$600–800)

- 40+ beam equivalent, 70° vertical FOV
- ~200k pts/sec
- Native ROS2 drivers; officially supported by FAST-LIO2 and LIO-SAM
- Non-repetitive scan pattern improves feature detection for scan-matching
- Compact form factor suitable for vehicle mounting

**Alternatives:**

| Unit | Price (approx.) | Notes |
|---|---|---|
| Unitree L1 | ~$500 | 18-line, good budget entry |
| Velodyne VLP-16 | ~$1,500 used | Research workhorse, large ecosystem |
| Hesai XT16 | ~$1,200 | Solid mid-range, strong ROS support |
| Ouster OS0-32 | ~$3,500 | Professional tier; familiar from RESEPI payload |

**Impact on existing hardware:** The NEMA17 stepper + A4988 driver become vestigial once a
multi-beam LiDAR is fitted. The mechanical frame may be retained as a mount but the rotation
assembly is removed.

---

### 2.2 IMU — MPU-9250 → Tactical-Grade MEMS

The MPU-9250 is a consumer part. LiDAR-IMU SLAM stacks (LIO-SAM, FAST-LIO2) place the IMU
in a tight fusion loop that requires >200 Hz output and low in-run bias instability. Poor IMU
noise characteristics cause pose drift that scan-matching cannot recover from.

**Primary candidate: ICM-42688-P breakout** (~$20–50)

- In-run bias stability ~3°/hr — significantly better than MPU-9250
- Up to 8 kHz output rate via SPI (deterministic timing, important for LiDAR-IMU sync)
- Standard pairing for Livox + FAST-LIO2 community builds

**Upgrade option for vehicle use: ADIS16470** (~$200)

- Industrial MEMS, ~10× better noise floor than ICM-42688
- Better vibration rejection — relevant when mounted on a truck or UTV
- SparkFun breakout available

**Note:** The Madgwick fusion in `imu.py` is not reused for SLAM. Raw IMU samples are handed
directly to the SLAM stack. The existing driver code can be stripped back to a raw sample
publisher.

---

### 2.3 Compute — Raspberry Pi 4 → Jetson Orin NX

The Pi 4 cannot run FAST-LIO2 or LIO-SAM in real time, particularly under vehicle-mounted
conditions where scan rates cannot be throttled. SLAM is matrix-math bound, not I/O bound.

**Primary candidate: NVIDIA Jetson Orin NX 8GB** (~$500)

- Standard embedded SLAM platform as of 2025
- Runs FAST-LIO2 and LIO-SAM at full rate with headroom for post-processing
- Same Linux environment — Python sensor drivers migrate without rewrite
- CUDA available for downstream mesh generation or feature extraction

**Budget option: Orange Pi 5 Plus** (~$120)

- RK3588, 8-core, Mali GPU
- Community builds of FAST-LIO2 exist
- Acceptable for stationary or low-speed vehicle work; marginal at higher speeds

---

## 3. What Carries Forward from V1

| Component | V2 Status | Notes |
|---|---|---|
| ZED-F9P RTK GNSS | ✅ Keep | GNSS-aided SLAM reduces drift significantly; absolute prior at session start |
| HQ Camera + Fisheye | ✅ Keep | Opens visual-inertial SLAM path (VINS-Mono, ORB-SLAM3) in V2.1+ |
| ESP32 LoRa (RTCM Rx + telemetry Tx) | ✅ Keep | No change needed |
| T-Deck monitoring console | ✅ Keep | No change needed |
| RTK base station | ✅ Keep | Still valuable for georeferenced output |
| Power architecture (split compute/motor rails) | ✅ Keep | May upsize 5V bank slightly for Jetson |
| `gnss.py` driver | ✅ Reuse | Minimal changes |
| `camera.py` driver | ✅ Reuse | Minimal changes |
| `imu.py` | ⚠️ Rework | Strip Madgwick; expose raw sample publisher |
| `lidar.py` | ❌ Replace | LD19 protocol → Livox SDK or ROS2 driver |
| `stepper.py` | ❌ Remove | No longer needed |
| `logger.py` (JSONL) | ❌ Replace | ROS2 bag or live topic architecture |
| `main.py` orchestration | ❌ Rewrite | Step→scan→log loop → SLAM node management |

---

## 4. SLAM Stack Candidates

| Stack | LiDAR Support | Notes |
|---|---|---|
| **FAST-LIO2** | Livox native, others via adapter | Lightweight, tightly-coupled LiDAR-IMU; good first choice |
| **LIO-SAM** | VLP-16, OS1, others | Loop closure support; heavier compute |
| **KISS-ICP** | Any point cloud | Simple, robust, no IMU required; good for stationary |
| **HDL Graph SLAM** | Velodyne family | Feature-rich but older codebase |

FAST-LIO2 is the recommended starting point given the Livox Mid-360 candidate and Jetson
compute target.

---

## 5. Dual-Use Operation

### Stationary Mode

- Lock platform position
- Run high-density scan sweep (software-controlled, no stepper)
- GNSS georeferences the output directly
- Output: georeferenced PLY / LAS point cloud
- Workflow largely unchanged from V1 post-processing pipeline

### Mobile / Vehicle Mode

- Continuous LiDAR-IMU SLAM
- GNSS seeds initial pose; periodic fixes constrain drift
- Output: trajectory + point cloud map
- Vehicle-specific considerations:
  - Vibration isolation mount between sensor assembly and vehicle body (especially for
    ICM-42688; less critical with ADIS16470)
  - PPS signal from ZED-F9P for hardware time synchronization (deferred from V1)
  - Weatherproofing if used on open vehicles

---

## 6. Rough Cost Delta

These are estimates; prices shift.

| Item | Estimated Cost |
|---|---|
| Livox Mid-360 | ~$700 |
| ICM-42688-P breakout | ~$30 |
| Jetson Orin NX 8GB | ~$500 |
| NVMe SSD for Jetson (map storage) | ~$60 |
| Vibration isolation mount | ~$50 |
| Miscellaneous (cables, adapters, mount hardware) | ~$100 |
| **Total new hardware** | **~$1,440** |

Components retained from V1 (F9P ×2, antennas, camera, ESP32 LoRa, T-Deck, power
hardware) are not counted above.

---

## 7. Open Questions

- **Livox vs. Velodyne:** Livox Mid-360 is the cost-optimized pick; VLP-16 has a larger
  community and more battle-tested SLAM integrations. Worth a bench comparison if a used
  VLP-16 becomes available.
- **ROS2 vs. custom Python:** ROS2 (Humble) is the natural home for this stack and has
  first-class Jetson support. Adds complexity but buys access to the full SLAM ecosystem
  without reinventing wheel odometry, tf trees, etc. Lean toward ROS2 unless there's a
  strong reason not to.
- **PPS synchronization:** V1 deferred this. V2 mobile mode really wants it for tight
  LiDAR-IMU-GNSS time alignment. The ZED-F9P exposes a PPS pin; Jetson GPIO can receive it.
  Evaluate during Phase 1.
- **Loop closure:** FAST-LIO2 does not have loop closure. LIO-SAM does. For large-area
  vehicle scans, loop closure matters. May want to start with FAST-LIO2 and migrate to
  LIO-SAM once the platform is stable.
- **Camera integration:** The fisheye camera is retained but not integrated into the SLAM
  pipeline in V2.0. Visual-inertial fusion (VINS-Fusion or ORB-SLAM3 with LiDAR) is a V2.1
  consideration.

---

## 8. Rough Phase Plan

This is notional — not a committed schedule.

| Phase | Goal |
|---|---|
| 1 | Source hardware; bench-test Livox + ICM-42688 + Jetson independently |
| 2 | FAST-LIO2 running on Jetson with Livox in stationary mode |
| 3 | Integrate ZED-F9P GNSS as pose prior |
| 4 | Stationary mode validated against V1 point cloud outputs |
| 5 | Vehicle mount design and vibration isolation |
| 6 | Mobile mode field test (slow speed, parking lot) |
| 7 | V2.0 release — freeze stationary + basic mobile |
| 8 | V2.1 planning (loop closure, visual-inertial, larger area tests) |

---

## 9. Changelog

| Version | Date | Notes |
|---|---|---|
| v0.1.0 | 2026-05-11 | Initial rough concept; based on V1 architecture review |
