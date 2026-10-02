# Design Decisions Log

**Document Status:** v0.10 — deep alignment with arm-drone-lidar-workflow
**Last Updated:** 2026-10-02 (DEC-037–DEC-045: static-station scanner redesign)

This document records all significant architectural and engineering decisions,
including rationale, alternatives considered, and implications.

> **v0.10 deep-alignment overhaul (Stage D.1):** Decision IDs renamed from
> `D-NNN` to `DEC-NNN` to match the sibling `arm-drone-lidar-workflow` repo's
> `docs/decisions/decision-log.md` format. Each entry now carries a
> Status / Date / Decided-by / Rationale metadata block before the existing
> Context / Rationale / Alternatives / Implications body. Dates are backfilled
> from git: `2026-03-22` for DEC-001–DEC-029 (planning-era block) and
> `2026-05-23` for DEC-030–DEC-034 (v0.10 integration block). Superseded
> entries (DEC-005 / DEC-006 / DEC-010) point at their replacements.

---

## Decision Format

Each decision starts with a metadata block:

```
**Status:** Accepted | Superseded by DEC-NNN | Provisional
**Date:** YYYY-MM-DD
**Decided by:** Brian
**Rationale:** one-line summary (the body that follows expands on this)
```

Followed by these sections:
- **Decision:** What was decided
- **Context:** Why a decision was needed
- **Rationale:** Why this option was chosen
- **Alternatives Considered:** What else was evaluated
- **Implications:** What this decision affects downstream

---

## 1. System-Level Decisions

### DEC-001: DIY Over Commercial Solution

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Custom build is ~10× cheaper than commercial RTK LiDAR; the
~5–10 cm accuracy tradeoff is acceptable for the intended use.

**Decision:** Build custom RTK scanning platform rather than purchase commercial equipment.

**Context:** Commercial RTK LiDAR systems exist but cost $10,000-$100,000+.

**Rationale:**
- Cost control (~$1000-1500 total vs $10k+ commercial)
- Full system understanding enables modification and repair
- Educational value in building
- Acceptable accuracy for intended use (not survey-certified)

**Alternatives Considered:**
- Lease commercial equipment (ongoing cost, no learning)
- Purchase used survey gear (still expensive, proprietary)

**Implications:**
- Must accept DIY accuracy limits (±5-10 cm vs ±1 cm commercial)
- More development time required
- Full customization possible

---

### DEC-002: PiLiDAR as Foundation

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** PiLiDAR validates the Pi + LD19 + stepper-rotation concept;
extending it lets us focus effort on RTK/IMU rather than basic scanning.

**Decision:** Extend the open-source PiLiDAR project rather than design from scratch.

**Context:** PiLiDAR demonstrates feasibility of Pi + LD19 + stepper rotation for 3D scanning.

**Rationale:**
- Proven concept reduces technical risk
- Existing community knowledge
- Focus effort on RTK/IMU extensions rather than basic scanning

**Alternatives Considered:**
- Clean-sheet design (more effort, higher risk)
- Different LiDAR (e.g., RPLIDAR A1/A2) — similar approach, LD19 already owned

**Implications:**
- Inherit some PiLiDAR limitations (rotation mechanism, LD19 range)
- Can leverage existing code and documentation

---

### DEC-003: Raspberry Pi Over MCU-Only

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Sensor fusion + camera + logging exceeds an MCU's comfort
zone; Pi's Linux + Python ecosystem accelerates everything else.

**Decision:** Use Raspberry Pi 4 as main controller, not bare microcontrollers.

**Context:** System requires sensor fusion, data logging, camera interface, and complex orchestration.

**Rationale:**
- Linux ecosystem enables rapid development
- Python libraries for all sensors
- Native camera interface (CSI)
- Sufficient compute for Madgwick fusion + logging
- Easier debugging and field updates

**Alternatives Considered:**
- ESP32-only (insufficient for camera + logging throughput)
- STM32/Teensy (possible but much harder development)
- Jetson Nano (overkill cost/power for v1.0 needs)

**Implications:**
- Higher power consumption than MCU (~5-7W vs <1W)
- Linux boot time (~20-30 sec)
- SD card reliability considerations

---

## 2. GNSS / RTK Decisions

### DEC-004: ZED-F9P for RTK

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** De-facto DIY-RTK standard with the documentation, dual-band
support, and vendor breadth a hobbyist project actually needs.

**Decision:** Use u-blox ZED-F9P for both base and rover GNSS receivers.

**Context:** RTK requires specific receiver capabilities (RTCM3, dual-band, low-latency).

**Rationale:**
- De-facto standard for DIY RTK
- Excellent documentation and community support
- Dual-band (L1/L2) improves fix reliability
- Native RTCM3 generation and parsing
- Multiple vendor options (SparkFun, ArduSimple, Beitian)

**Alternatives Considered:**
- u-blox NEO-M8P (older, single-band, worse convergence)
- Septentrio (excellent but expensive)
- Swift Navigation (good but less community support)

**Implications:**
- Need two F9P boards (~$400-500 total)
- Need dual-band antennas (~$100-200)
- Well-documented configuration process

---

### DEC-005: RTK via LoRa (Not Cellular)

**Status:** Superseded by DEC-031 (2026-05-23)
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale (original):** No subscription, no coverage dependency,
predictable ~1–2 s latency, full control of correction stream.

**Decision:** Deliver RTCM corrections via LoRa radio link, not cellular/internet.

**Context:** Corrections must flow from base to rover with low latency.

**Rationale (original):**
- No subscriptions or cellular coverage dependency
- Works in remote areas without infrastructure
- Predictable latency (~1-2 seconds)
- Full control of correction stream

**Alternatives Considered:**
- Cellular + NTRIP (requires coverage, subscription, adds latency uncertainty)
- Wi-Fi (limited range, requires AP infrastructure)
- Direct cable (limits mobility, impractical for rover)

**Implications:**
- Need LoRa radios on both base and rover
- Bandwidth constrained (~600-800 bytes/sec usable)
- Range limited to ~2-5 km LOS

**Supersession note:** The `arm-drone-lidar-workflow` Base-Station exposes
its corrections via an NTRIP caster (mountpoint `ARM_BASE` on port 2101);
LoRa is retained only as the off-network fallback. See DEC-031.

---

### DEC-006: RTCM Routing — ESP32 Direct to F9P

**Status:** Superseded by DEC-032 (2026-05-23)
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale (original):** Lower latency for corrections, RTK survives a
Linux crash, simpler ESP32 code as a "dumb pipe" for RTCM.

**Decision:** Route RTCM corrections directly from ESP32 (LoRa) to ZED-F9P via UART, bypassing the Raspberry Pi.

**Context:** Original plan had Pi in the RTCM path for logging/observability. This adds latency and creates Linux dependency.

**Rationale (original):**
- Lower latency for corrections
- RTK remains functional if Linux crashes
- Simpler code (ESP32 is "dumb pipe" for RTCM)
- Pi can still monitor RTK status via F9P's NMEA/UBX output

**Alternatives Considered:**
- ESP32 → Pi → F9P (original plan; higher latency, more code, Linux dependency)
- ESP32 tee to both (complex, unnecessary for v1.0)

**Implications:**
- Need direct UART wiring between ESP32 and F9P
- Pi not in critical path for positioning
- Less real-time RTCM visibility on Pi (acceptable)

**Supersession note:** The blanket "Pi never in the correction path" rule
no longer holds — the Pi runs the NTRIP client in the default configuration.
ESP32-as-direct-pipe is retained as a per-session opt-in. See DEC-032.

---

### DEC-007: RTCM Constellation Profiles

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Two profiles let the operator trade constellation coverage
against bandwidth at config time without code changes.

**Decision:** Implement two RTCM message profiles: Robust (GPS+GLONASS+Galileo+BeiDou) and Low-Bandwidth (GPS+GLONASS only).

**Context:** More constellations improve fix reliability but increase bandwidth.

**Rationale:**
- Robust profile for typical operation
- Low-bandwidth profile for marginal LoRa conditions
- User-selectable via config file
- Avoids hard-coding limitations

**Alternatives Considered:**
- Fixed minimal set only (misses Galileo/BeiDou benefits)
- All constellations always (may exceed bandwidth)

**Implications:**
- Config file must support profile selection
- Base station must generate appropriate RTCM set
- Monitor bandwidth utilization during testing

---

## 3. Communications Decisions

### DEC-008: LoRa Parameters

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** SF 9–10 / BW 125 kHz / CR 4/5 balances 1–3 km range with
throughput sufficient for RTCM + sparse telemetry.

**Decision:** Use LoRa with SF 9-10, 125 kHz bandwidth, CR 4/5.

**Context:** Balance between range, throughput, and reliability needed.

**Rationale:**
- SF 9-10 provides 1-3 km reliable range
- 125 kHz is standard, good noise immunity
- CR 4/5 provides light error correction
- Throughput sufficient for RTCM + sparse telemetry

**Alternatives Considered:**
- SF 7 (higher throughput but shorter range)
- SF 12 (longer range but too slow for RTCM)
- 250 kHz bandwidth (higher throughput but more noise sensitive)

**Implications:**
- RTCM latency ~1-2 seconds (acceptable)
- Telemetry must be sparse (multiplex with RTCM)
- Range adequate for typical field operations

---

### DEC-009: LoRa Packet Loss Handling

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** RTK tolerates occasional correction loss inherently;
retries add latency and code complexity without enough payoff.

**Decision:** Tolerate RTCM packet loss without retries; rover continues logging autonomously.

**Context:** Retries add complexity and latency; RTCM is inherently loss-tolerant.

**Rationale:**
- RTK can recover from occasional missing corrections
- Retries would increase latency and code complexity
- Rover should never stop logging due to link issues
- Loss rate trackable via sequence numbers

**Alternatives Considered:**
- ACK/retry protocol (complex, adds latency)
- Store-and-forward (unnecessary given RTK nature)

**Implications:**
- RTK may degrade to FLOAT briefly during loss
- Telemetry may have gaps
- Need sequence numbers to detect loss rate

---

### DEC-010: T-Deck Receive-Only (v1.0)

**Status:** Superseded by DEC-033 (2026-05-23)
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale (original):** Receive-only is simpler to implement; sufficient
for monitoring; reduces risk of accidental commands.

**Decision:** Monitoring terminal is receive-only in v1.0; no remote commands.

**Context:** Bidirectional command/control adds complexity and security considerations.

**Rationale (original):**
- Receive-only is simpler to implement
- Sufficient for monitoring use case
- Reduces risk of accidental commands
- Command/control can be added in v1.1

**Alternatives Considered:**
- Full bidirectional control (complex, deferred)
- No monitoring terminal (lose field visibility)

**Implications:**
- Must start/stop scans at rover directly
- Cannot change settings remotely
- Revisit in v1.1 for remote control

**Supersession note:** The T-Deck is now owned by the
`arm-drone-lidar-workflow` Base-Station (handheld for base monitoring),
not a rover-attached field monitor. Rover field visibility comes from the
triple-channel telemetry described in DEC-033. See DEC-033.

---

## 4. Sensor & Fusion Decisions

### DEC-011: MPU-9250 as Primary IMU

**Status:** Superseded by DEC-041
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** 9-axis gives indoor heading when GNSS is unavailable;
6-axis (MPU-6050) is bench-test only.

**Decision:** Use MPU-9250 (9-axis with magnetometer) as primary IMU; MPU-6050 for testing only.

**Context:** Heading estimation requires magnetometer indoors, but magnetometer has EMI challenges.

**Rationale:**
- 9-axis enables heading estimation when GNSS unavailable
- Fallback to gyro-only heading when mag disabled
- Well-supported, adequate accuracy

**Alternatives Considered:**
- MPU-6050 only (no heading without GNSS)
- BNO055 (built-in fusion, but proprietary algorithm, calibration issues)
- ICM-20948 (newer, similar capability, less community support)

**Implications:**
- Must manage magnetometer enable/disable around motor operation
- Calibration required (hard/soft iron)
- More complex than 6-axis but necessary

---

### DEC-012: Madgwick Filter for Sensor Fusion

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Computationally light, widely validated, adequate for the
rover's scan-rate orientation needs; EKF available if v1.1 needs it.

**Decision:** Use Madgwick filter for IMU sensor fusion (v1.0).

**Context:** Need to fuse accelerometer, gyroscope, and (optionally) magnetometer into orientation estimate.

**Rationale:**
- Computationally light (runs easily on Pi)
- Widely used and validated
- Adequate accuracy for scan stabilization
- Well-documented implementations available

**Alternatives Considered:**
- Complementary filter (simpler but less accurate)
- EKF (more accurate but more complex, deferred)
- Mahony filter (similar to Madgwick, either acceptable)

**Implications:**
- Output is quaternion orientation at 100 Hz
- Tuning parameter (beta) may need adjustment
- EKF path available for v1.1 if needed

---

### DEC-013: Magnetometer Disabled During Motor Operation

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Stepper EMI corrupts mag readings; shielding is expensive
and unreliable; gyro integration carries short-term heading instead.

**Decision:** Disable magnetometer readings while stepper motor is energized or rotating.

**Context:** Stepper motor and 12V wiring generate EMI that corrupts magnetometer readings.

**Rationale:**
- EMI from motor is unavoidable without expensive shielding
- Corrupted mag data poisons fusion filter
- Gyro integration provides short-term heading stability
- GNSS provides heading outdoors when moving

**Alternatives Considered:**
- Extensive shielding (expensive, uncertain effectiveness)
- Mount IMU far from motor (layout constrained)
- Ignore mag entirely (loses indoor heading capability)

**Implications:**
- Mag available only when motor idle
- Indoor scans rely on gyro (drift over time)
- Outdoor scans use GNSS-derived heading

---

### DEC-014: IMU-LiDAR Timestamp Correlation via Slerp

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Ring-buffer + bracket lookup + quaternion slerp gives
smooth O(1) per-scan orientation without gimbal-lock or hardware sync.

**Decision:** Correlate IMU orientation to LiDAR scan timestamps using ring buffer + bracket lookup + spherical linear interpolation (slerp).

**Context:** IMU and LiDAR sample at different rates and need alignment.

**Rationale:**
- Slerp provides smooth quaternion interpolation
- Ring buffer is memory-efficient
- Bracket lookup is O(1) with sorted buffer
- Produces accurate pose at scan timestamp

**Alternatives Considered:**
- Nearest-neighbor (simpler but introduces wobble artifacts)
- Linear interpolation of Euler angles (gimbal lock issues)
- Hardware sync via PPS (complex, deferred)

**Implications:**
- Requires quaternion math in logging code
- IMU must sample faster than LiDAR (200-400 Hz vs 5-10 Hz)
- Quality of point cloud depends on correct implementation

---

## 5. Mechanical Decisions

### DEC-015: Direct Drive Rotation (No Slip Ring)

**Status:** Accepted (no slip ring) · Amended by DEC-040 (drive is now geared)
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Slip ring adds cost and failure modes; ±180° with a
flexible cable loop is sufficient for v1.0 use cases.

**Decision:** Use direct drive from NEMA17 to rotating platform without slip ring; manage cables via flexible loop.

**Context:** Continuous rotation requires slip ring for power/data; limited rotation can use cable loops.

**Rationale:**
- Slip rings add cost, complexity, and potential failure point
- ±180° rotation or single-direction with reset sufficient for v1.0
- Flexible cable loop is simpler and cheaper

**Alternatives Considered:**
- Slip ring (enables continuous rotation but adds cost/complexity)
- Wireless data transfer (complex, latency)

**Implications:**
- Rotation limited to ±180° or full rotation with reset pause
- Cable fatigue is potential long-term issue
- Slip ring is v1.1+ upgrade path

---

### DEC-016: Open-Loop Stepper Indexing

**Status:** Superseded by DEC-040
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Steppers rarely miss steps at low speed; closed-loop adds
hardware for marginal benefit at v1.0 scale.

**Decision:** Use open-loop step counting for position; no limit switch or encoder in v1.0.

**Context:** Closed-loop control requires additional sensors but provides position verification.

**Rationale:**
- Steppers rarely miss steps at low speeds
- Open-loop is simpler and sufficient for initial scans
- Manual index mark for alignment
- Encoder/limit switch is easy upgrade if needed

**Alternatives Considered:**
- Limit switch homing (adds hardware, wiring)
- Encoder feedback (adds cost and complexity)
- Hall effect sensor (moderate complexity)

**Implications:**
- Must manually align starting position
- Potential for cumulative error over very long scans
- Revisit if step loss becomes problem

---

### DEC-017: 1/16 Microstepping

**Status:** Superseded by DEC-040
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Smoothest motion + finest position resolution the A4988
supports; torque adequate for light LiDAR payload.

**Decision:** Configure A4988 for 1/16 microstepping (3200 steps/rev).

**Context:** Microstepping affects smoothness, torque, and resolution.

**Rationale:**
- 1/16 provides smoothest motion (least vibration)
- Fine position control for scan alignment
- Sufficient torque for light payload
- Standard A4988 setting

**Alternatives Considered:**
- Full step (most torque but rough, noisy)
- 1/8 step (backup if torque insufficient)
- 1/32 (not available on A4988)

**Implications:**
- Step timing: 3200 steps per revolution
- Lower holding torque than full step (acceptable)
- Motor runs quieter

---

## 6. Power Decisions

### DEC-018: Split Power Domains

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Stepper transients can brown out shared compute power;
isolated rails keep the Pi alive when the motor battery dies.

**Decision:** Separate power supplies for compute (5V) and motors (12V).

**Context:** Stepper transients can cause brownouts on compute power.

**Rationale:**
- Motor current spikes don't affect compute stability
- Independent battery management
- Compute continues if motor battery dies
- Easier capacity planning per domain

**Alternatives Considered:**
- Single battery with DC-DC isolation (complex)
- Large single battery with filtering (still risky)

**Implications:**
- Two batteries to manage
- Separate charging
- Slightly more weight/complexity

---

### DEC-019: Dedicated 3.3V Regulator

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** F9P peaks at 150+ mA; the Pi's 3.3V GPIO rail tops out at
~50–100 mA; dedicated switching reg avoids brownouts and protects the Pi.

**Decision:** Power ZED-F9P and IMU from dedicated 3.3V switching regulator (≥1A), NOT from Pi's GPIO 3.3V rail.

**Context:** Pi's 3.3V GPIO rail is limited (~50-100 mA) and F9P can draw 150+ mA.

**Rationale:**
- F9P peak current exceeds Pi GPIO capability
- Switching regulator more efficient than LDO
- Stable 3.3V improves GNSS performance
- Protects Pi from overcurrent

**Alternatives Considered:**
- Power from Pi GPIO 3.3V (risky, insufficient current)
- LDO regulator (works but wastes power as heat)
- Power via F9P board's onboard regulator from 5V (check board support)

**Implications:**
- Need external regulator component
- Must verify F9P board power options (some accept 5V USB)
- Additional wiring complexity

---

## 7. Software Decisions

### DEC-020: Python on Raspberry Pi OS Lite

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Rapid development + extensive sensor libraries; OS Lite
drops GUI overhead while keeping 64-bit memory headroom.

**Decision:** Use Python 3 on Raspberry Pi OS Lite (64-bit) for rover software.

**Context:** Language and OS choice affects development speed and runtime capability.

**Rationale:**
- Python enables rapid development
- Extensive sensor libraries available
- Pi OS Lite is lightweight (no GUI overhead)
- 64-bit enables >4GB memory if needed

**Alternatives Considered:**
- C++ (faster but slower development)
- Rust (safe but ecosystem less mature for Pi sensors)
- Full Pi OS (unnecessary GUI overhead)
- Ubuntu (heavier, less Pi-optimized)

**Implications:**
- Performance adequate for v1.0 needs
- May need to optimize hot paths if issues arise
- Threading via Python threads (GIL limitations)

---

### DEC-021: JSONL for Logging

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Append-only + crash-safe + human-readable; size penalty
vs binary is acceptable for v1.0 data rates.

**Decision:** Log sensor data in JSONL (newline-delimited JSON) format.

**Context:** Need structured, timestamped logging of all sensor data.

**Rationale:**
- Human-readable for debugging
- Structured for parsing
- Append-only (crash-safe)
- Schema-flexible (add fields without breaking)
- Standard tools for processing

**Alternatives Considered:**
- Binary format (smaller but harder to debug)
- CSV (simpler but less structured)
- SQLite (more complex, overkill for append-only)

**Implications:**
- Larger file sizes than binary (~3-5× typical)
- Fast enough for v1.0 data rates
- Easy post-processing with Python/jq

---

### DEC-022: Post-Processed Georeferencing

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Real-time georef is significant complexity for no v1.0
benefit; post-processing also enables better tooling (PDAL, CloudCompare).

**Decision:** Georeferencing is post-processed in v1.0; not real-time.

**Context:** Real-time georeferencing requires tight integration and optimization.

**Rationale:**
- Simpler implementation for v1.0
- Post-processing allows correction of errors
- Real-time not required for mapping use case
- Enables use of better tools (PDAL, CloudCompare)

**Alternatives Considered:**
- Real-time georeferencing (complex, deferred)
- No georeferencing (defeats RTK purpose)

**Implications:**
- Scan output is raw + metadata; georef applied later
- Need robust metadata (timestamps, poses, GNSS fixes)
- Python scripts for georeferencing pipeline

---

### DEC-023: SLAM Deferred to v1.1+

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** SLAM is significant scope; v1.0 focus is RTK-outdoor;
relative scans are useful indoors without it.

**Decision:** No real-time SLAM in v1.0; indoor mode provides relative mapping only.

**Context:** SLAM would enable trajectory estimation and map building without GNSS.

**Rationale:**
- SLAM is significant complexity
- v1.0 focus is RTK-based outdoor mapping
- Relative scans still useful indoors
- Can add SLAM in v1.1 with hector_slam or Cartographer

**Alternatives Considered:**
- Include basic SLAM (significant scope increase)
- ICP-only in post-processing (reasonable middle ground)

**Implications:**
- Indoor scans are relative, not globally positioned
- No loop closure or drift correction
- Post-processing can apply ICP registration

---

## 8. Accuracy Decisions

### DEC-024: v1.0 Point Cloud Accuracy Target

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Honest accounting — RTK is cm-level at the antenna, but
the transform chain adds error without extrinsic calibration. ±5–10 cm is
what you actually get in v1.0.

**Decision:** v1.0 point cloud accuracy target is ±5-10 cm absolute; RTK solution accuracy is ±2-3 cm at antenna.

**Context:** Original spec claimed ±2-3 cm point cloud accuracy, but this requires extrinsic calibration not planned for v1.0.

**Rationale:**
- RTK position is cm-accurate at antenna phase center
- Transform chain (LiDAR→IMU→GNSS) adds error without calibration
- ±5-10 cm is achievable with careful mounting
- ±2-3 cm requires calibration procedure (v1.1)

**Alternatives Considered:**
- Claim ±2-3 cm (unrealistic without calibration)
- Define calibration procedure for v1.0 (scope increase)

**Implications:**
- Set realistic expectations
- Calibration is v1.1 upgrade path
- Still significantly better than non-RTK (~3m)

---

### DEC-025: Validation via Repeatability + Control Points

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Repeatability is self-verifiable; control points add ground
truth when accessible; CloudCompare catches gross errors visually.

**Decision:** Validate accuracy through repeatability testing and comparison to known control points (if available).

**Context:** Need to verify system actually achieves claimed accuracy.

**Rationale:**
- Repeatability is self-verifiable
- Control points provide ground truth if accessible
- Visual inspection in CloudCompare catches gross errors
- "Truth campaign" with survey gear if opportunity arises

**Alternatives Considered:**
- No validation (unacceptable)
- Formal survey comparison only (may not be accessible)

**Implications:**
- Define repeatability test procedure
- Seek opportunity to compare against survey data
- Document achieved vs. claimed accuracy

---

## 9. Camera Decisions

### DEC-026: Camera as Visual Reference (Not Photogrammetry)

**Status:** Superseded by DEC-036 (2026-09-29)
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Context imagery is high-value for QA; full photogrammetry
is significant scope and deferred to v1.2+.

**Decision:** Camera captures context imagery for visual reference; not integrated into 3D reconstruction in v1.0.

**Context:** Camera could enable texture mapping or photogrammetry but adds significant complexity.

**Rationale:**
- Context imagery is valuable for scan interpretation
- "What was I looking at?" is useful QA tool
- Full photogrammetry requires camera calibration and projection
- Deferred complexity keeps v1.0 achievable

**Alternatives Considered:**
- Full texture mapping (significant scope increase)
- No camera (lose valuable context)

**Implications:**
- Camera output is standalone JPEG images
- Associated with scans via timestamp/index
- Future colorization possible via nearest-frame lookup

---

### DEC-027: Camera Triggered Per Rotation Step

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Triggered capture matches scan structure, keeps storage
sane, and aligns naturally with step indices for post-processing.

**Decision:** Capture one image per rotation step (or per N steps), not continuous video.

**Context:** Need to balance coverage, storage, and processing.

**Rationale:**
- Triggered capture matches scan structure
- Reduces storage vs. continuous video
- Simpler synchronization (step index alignment)
- Fisheye covers wide FOV per frame

**Amendment 2026-09-29:** The HQ Camera and fisheye are retired. Two ELP 16MP USB
cameras (~118° each) on the rotating platform replace them (`docs/HARDWARE.md` §4.3).
Per-step triggering stands; capture from one camera at a time while the mast is at rest
(shared USB 2.0 bandwidth, rolling shutter). The fisheye bullet above no longer applies.

**Alternatives Considered:**
- Continuous video (storage heavy, sync complex)
- Manual trigger only (misses context)
- Every Nth step (acceptable variant, tunable)

**Implications:**
- Capture cadence tied to step timing
- Storage ~500KB-1MB per image
- Exact cadence tunable via config

---

## 10. Configuration Decisions

### DEC-028: TOML Configuration File

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** Typed, readable, comment-supporting; Python 3.11 stdlib
`tomllib` removes the dependency surface; less whitespace-fragile than YAML.

> **Cross-repo note:** The sibling `arm-drone-lidar-workflow` Base-Station
> uses YAML for the same role. The two repos deliberately differ here —
> alignment was discussed in the v0.10 overhaul and TOML was kept on the
> rover side because (a) Python 3.11 ships a TOML reader in stdlib but not
> a YAML one, and (b) the on-wire contract between the two systems is JSON,
> so the config-file format is internal and divergence costs nothing.

**Decision:** Use single TOML configuration file for all runtime parameters.

**Context:** Many parameters should be adjustable without code changes.

**Rationale:**
- TOML is readable and typed
- Less indentation-sensitive than YAML
- Better than INI for nested config
- Single file is simpler than per-subsystem files

**Alternatives Considered:**
- YAML (more common but whitespace-sensitive; also requires pyyaml dep)
- JSON (no comments, verbose)
- INI (limited structure)
- Per-subsystem files (more files to manage)

**Implications:**
- All tunable params in one place
- Must define config schema
- Can split to per-subsystem in future if needed

---

## 11. Upstream Compatibility Decisions

### DEC-029: GPIO Library — rpi-lgpio over RPi.GPIO

**Status:** Accepted
**Date:** 2026-03-22
**Decided by:** Brian
**Rationale:** `RPi.GPIO` is broken on Bookworm (sysfs GPIO removed);
`rpi-lgpio` is a drop-in API replacement using the lgpio backend.

**Decision:** Use `rpi-lgpio` (or `gpiozero`) for GPIO control on Raspberry Pi, NOT the legacy `RPi.GPIO` library.

**Context:** Raspberry Pi OS Bookworm (the current 64-bit release) deprecated the sysfs GPIO interface. The upstream PiLiDAR project migrated from `RPi.GPIO` to `rpi-lgpio` to address this. Since our project targets Pi OS Lite 64-bit (DEC-020), this affects stepper motor control and any future GPIO-based interfaces.

**Rationale:**
- `RPi.GPIO` fails on Bookworm with `RuntimeError: Failed to add edge detection`
- `rpi-lgpio` is a drop-in replacement (same API, different backend using lgpio)
- Upstream PiLiDAR has validated this migration path
- `gpiozero` is also acceptable (higher-level, uses lgpio under the hood)

**Alternatives Considered:**
- `RPi.GPIO` (broken on Bookworm, would require downgrade to Bullseye)
- `pigpio` (daemon-based, adds complexity)
- `gpiozero` (acceptable alternative; higher-level API)
- Direct `/dev/gpiochip` access (too low-level for v1.0)

**Implications:**
- `stepper.py` must use `rpi-lgpio` or `gpiozero` for step/dir/enable GPIO
- Install via: `pip install rpi-lgpio` or `sudo apt install python3-rpi-lgpio`
- lgpio creates temp files (`.lgd-nfy*`); set `LG_WD=/tmp` environment variable
- No code impact if `gpiozero` is chosen instead (different API but well-documented)

---

## 12. Base-Station Integration Decisions (v0.10 overhaul)

These decisions reframe the rover around `ixhlbxi/arm-drone-lidar-workflow`'s production
Base-Station rather than the original self-contained design. The integration contract is
documented in `docs/BASE_STATION_INTEGRATION.md`.

### DEC-030: Dual-Mode Operation — Personal DIY vs. ARM Group Companion

**Status:** Accepted
**Date:** 2026-05-23
**Decided by:** Brian
**Rationale:** Single binary + per-session profile switch avoids forking
the codebase while letting ARM Group projects pull project-specific
defaults (NTRIP, CRS, status.json output path).

**Decision:** Add a session-level `profile` selector: `"personal"` (DIY use, off-grid)
or `"arm_group"` (companion to the ARM Group drone/LiDAR survey workflow). All major
runtime behaviors that diverge between the two modes are gated by this single switch.

**Context:** The rover was originally designed in isolation. The user wants it usable
both for personal DIY work (any environment, no project conventions) and as a complement
to the ARM Group survey workflow (NAD83 / NAVD88 / State Plane / US Survey Foot,
project-code-tagged sessions, output destined for TBC + Civil 3D). One binary that
hard-codes either choice is a lock-in; one that branches on a config flag isn't.

**Rationale:**
- Single binary, single config path — operator picks the profile per session.
- ARM Group profile defaults pull from `docs/BASE_STATION_INTEGRATION.md` (NTRIP enabled,
  status.json publish enabled, target CRS required).
- Personal profile keeps the original simple defaults (NTRIP optional, WGS84/local ENU,
  no project tagging).
- Avoids a parallel "arm-group-fork" of the codebase.

**Alternatives Considered:**
- Always ARM Group conventions (cuts off personal DIY use).
- Always personal conventions (rover can't drop output into ARM Group's `01_Raw/LiDAR`).
- Build-time variant (two binaries; operationally fragile).

**Implications:**
- `[session]` config section is now required; defaults to `personal`.
- ARM Group profile cross-validates: `project_code` non-empty, `target_crs_epsg > 0`,
  `[base_station_integration].enabled = true`.
- Logger writes `session.profile` + tags into `metadata.json`.
- `scripts/georef.py` honors the session-recorded profile when picking export defaults.

---

### DEC-031: NTRIP-Primary RTK with LoRa Fallback (supersedes DEC-005)

**Status:** Accepted
**Date:** 2026-05-23
**Decided by:** Brian
**Rationale:** Network NTRIP is the cheap reliable case (Base-Station
already runs a caster the drone uses); LoRa is the rare-but-essential
off-grid fallback.

**Decision:** The rover's primary RTK transport is NTRIP-over-IP, consumed from the
`arm-drone-lidar-workflow` Base-Station's caster (mountpoint `ARM_BASE` on
`rtk-base.local:2101` by default). LoRa-relayed RTCM is retained as the off-network
fallback for deployments where no IP path to the Base-Station exists.

**Context:** The Base-Station already ships an NTRIP caster as its canonical RTK transport
(used by the WISPR SkyScout 2+ drone). Building a parallel LoRa-only path on the rover
would duplicate the correction infrastructure and lock the rover out of the proven, in-use
Base-Station path.

**Rationale:**
- Reuses an existing, tested correction transport.
- Network is the cheap, reliable case; LoRa is the rare-but-essential off-grid case.
- Both Base-Station and rover Pi typically share the truck/field-AP WiFi already.
- LoRa fallback survives the "no LAN, no hotspot" case (deep-rural).

**Alternatives Considered:**
- NTRIP-only (DEC-005 reversed but no fallback — fragile in genuinely remote work).
- LoRa-only (original DEC-005; ignores existing NTRIP infrastructure).
- Both always active, with the F9P picking the better stream (over-engineered for v1.0).

**Implications:**
- `[ntrip]` section in config; `[lora].role` configures whether LoRa carries RTCM-Rx
  in addition to STATUS/LINK-Tx.
- Base-Station gains a LoRa-RTCM-Tx path (Phase D in the overhaul plan, separate PR
  in the sibling repo — tracked in `docs/CROSS_REPO_BACKLOG.md`).
- Operator switches between paths via config; runtime hot-switching is v1.1+.
- Rover ESP32 firmware grows two modes (LoRa-RTCM-relay, NTRIP-over-WiFi-client) — see DEC-032.

---

### DEC-032: NTRIP Client Location — Pi or ESP32, Per-Session (supersedes DEC-006's blanket rule)

**Status:** Accepted
**Date:** 2026-05-23
**Decided by:** Brian
**Rationale:** Pi-hosted is simpler (single config surface, easier to
debug); ESP32-hosted preserves the "RTK survives Pi crash" property for
critical missions. Per-session config-driven choice covers both.

**Decision:** The NTRIP client can run on either the Pi or the ESP32, selected per session
via `[ntrip].client_location = "pi" | "esp32"`. Both paths terminate at the same F9P
(via USB or UART2 respectively).

**Context:** DEC-006 mandated that the Pi never sit in the correction path — that was a
sound rule for the LoRa-relay architecture, but the NTRIP-primary model means the
correction source is now usually a network endpoint, not an on-board LoRa packet stream.
Either the Pi or the ESP32 can be the network client.

**Rationale:**
- Pi-hosted NTRIP is simpler — credentials live in the Pi's environment, single config
  surface, easier to debug.
- ESP32-hosted NTRIP preserves the DEC-006 property (RTK survives a Pi crash) for missions
  where that matters.
- One binary supports both via config; no firmware-side either/or lock-in.
- Field experience will determine which one is the practical default for ARM Group sessions.

**Alternatives Considered:**
- Pi-only (loses the "Pi-out-of-path" robustness for critical missions).
- ESP32-only (forces every rover deployment to flash credentials and manage WiFi from
  the ESP32; awkward for development).

**Implications:**
- `src/rover/ntrip.py` implements the Pi-side client (Phase C).
- `firmware/esp32-rover/` PlatformIO project gains an `ntrip_client` mode alongside the
  existing `lora_rtcm_relay` mode (Phase C).
- Mode selection is a config field, not a build-time switch.
- When `client_location = "esp32"`, `src/rover/ntrip.py` does not start; `gnss.py` still
  reads NMEA/UBX from F9P USB for status.

---

### DEC-033: Triple-Channel Telemetry (supersedes DEC-010)

**Status:** Accepted
**Date:** 2026-05-23
**Decided by:** Brian
**Rationale:** Different deployment modes want different observability —
status.json for Base-Station tools, HTTP for personal DIY, LoRa for the
no-network case. Each channel is independently enable-able.

**Decision:** The rover publishes telemetry on three independent, individually enable-able
channels:

1. **Base-Station-compatible `status.json`** — atomic JSON writes to a configurable path
   (default `/run/rover/status.json`), shaped to be readable by anything that consumes
   the Base-Station's `rtk_io.atomic_write_json` convention.
2. **Own loopback HTTP endpoint** — stdlib `http.server` exposing `GET /status` and
   `GET /health`. Off by default; the personal DIY profile's primary observability path.
3. **LoRa STATUS / LINK packets** — the original Appendix C STATUS (`0x01`) and
   LINK (`0x02`) packets, updated to the LoRa frame v2 envelope shared with the
   Base-Station.

**Context:** The original DEC-010 assumed a custom rover-attached T-Deck consuming a
self-contained LoRa STATUS/LINK protocol. With the T-Deck now owned by the Base-Station,
that single channel isn't enough — different deployment modes want different observability
paths.

**Rationale:**
- `status.json` lets the Base-Station's existing handhelds (BLE-bonded T-Deck, HTTP-polled
  Heltec) display rover status alongside base status without a new transport.
- HTTP endpoint serves personal DIY use (curl from a laptop on the same network).
- LoRa packets are the only channel that survives the no-network case.
- Each channel can be turned off in config — no forced fan-out cost.

**Alternatives Considered:**
- Single canonical channel (no single channel works for all three deployment modes).
- Reuse Base-Station's BLE GATT service (binds rover to base BLE schema; rover becomes a
  satellite of the base process).

**Implications:**
- `src/rover/telemetry.py` becomes a `TelemetryRouter` with pluggable publishers
  (`StatusJsonPublisher`, `LocalHttpPublisher`, `LoRaPublisher`).
- Each publisher start/stop is independent; failures in one don't take down the others.
- Status schema is rover-side (versioned independently from the Base-Station's; sibling
  is at v9, rover at v1 — both grow additively).
- Atomic-write pattern is borrowed byte-for-byte from
  `arm-drone-lidar-workflow/base-station/rtk_io.py:atomic_write_json` for compatibility
  (extracted to `src/rover/_io.py` in Stage B of the deep-alignment overhaul).

---

### DEC-034: Rover Coordinate Handling — Log SI/WGS84, Convert at Export

**Status:** Accepted
**Date:** 2026-05-23
**Decided by:** Brian
**Rationale:** Logging hot path stays simple in native units; choice of
target CRS is recorded once in metadata.json and applied at export by
scripts/georef.py — also enables re-export to alternative CRS without
re-acquiring data.

**Decision:** Sensor acquisition and JSONL logging stay in SI units + WGS84 (the current
design). Coordinate-system conversion to the session's `target_crs_epsg` (e.g.,
NAD83(2011) / PA-N, US Survey Foot for ARM Group profile) happens at export time in
`scripts/georef.py`, not in the hot logging path.

**Context:** The ARM Group survey workflow standardizes on NAD83 / NAVD88 / GEOID18 /
State Plane / US Survey Foot (DEC-001 in the sibling repo). The rover's original
design implicitly assumed meters / WGS84 / local ENU; nothing in JSONL records the
target CRS.

**Rationale:**
- Logging hot path is simpler and faster in native units.
- Choice of CRS is recorded in `metadata.json` at session start; export reads it back.
- Allows re-export to a different CRS without re-acquiring data — useful for
  cross-project comparisons.
- Matches PCMaster Pro / TBC workflow shape (raw → post-process → georeferenced).

**Alternatives Considered:**
- Convert at acquisition (CRS errors at config time become permanent data loss).
- Two-format logging (doubles log size; no real benefit).
- Drop WGS84 entirely and acquire in target CRS (fragile, conflates concerns).

**Implications:**
- JSONL records remain unchanged (decimal degrees, meters, milliseconds).
- `metadata.json` gains `session.target_crs_epsg` + `session.units` fields.
- `scripts/georef.py` becomes the canonical CRS-conversion boundary (Phase E).
- Adds `pyproj` as an optional dependency (`[project.optional-dependencies].post`).
- `scripts/georef.py:ZONE_EPSG` mirrors the sibling repo's `configure_base.py:ZONE_EPSG`
  *naming* but uses NAD83(2011) ft-US codes (6346 etc.) where sibling uses
  NAD83(HARN) codes (2271 etc.) — divergence noted in code.

---

### DEC-035: Deep Alignment with arm-drone-lidar-workflow (v0.10 Overhaul)

**Status:** Accepted
**Date:** 2026-05-30
**Decided by:** Brian
**Rationale:** Two weeks of cross-repo divergence had already started
showing in conventions and missing pieces — finish the v0.10 integration
in a coordinated deep-alignment pass before more drift accumulates.

**Decision:** Treat this rover as a sibling project of `arm-drone-lidar-workflow`,
mirroring its conventions wherever doing so reduces cognitive load for someone working
across both repos. Specifically: schema-version constants and changelogs, atomic-write
helper extraction, ZONE_EPSG zone-name vocabulary, sd_notify integration, systemd +
udev deployment kit, decision-log format (DEC-NNN with Status/Date/Decided-by/Rationale
metadata), and explicit positioning of the DIY rover as the LiDAR-scanning companion
to the SparkFun RTK Facet (which the sibling repo selected as its production GNSS-only
rover).

**Context:** The v0.10 overhaul landed two weeks ago as a single broad commit that stood
up the integration **contract** but left the rover unable to run (main.py / watchdog.py
were stubs) and out of sync with the sibling repo's deployment patterns. The sibling has
matured significantly (status schema at v9, 12+ systemd units, 3 udev rules, mature
redeploy.sh) and the gap between repos was widening every week.

**Rationale:**
- Conventions copied: schema-version constants, atomic writes, env-var secrets via
  `/etc/{repo}/secret`, sd_notify, decision-log DEC-NNN naming + metadata blocks.
- Deployment infrastructure copied: deploy/systemd/, deploy/udev/, deploy/install.sh
  modeled on sibling's bin/redeploy.sh.
- Positioning made explicit: README and CLAUDE.md now state the DIY rover is a
  LiDAR-scanning companion to the SparkFun RTK Facet (which the sibling repo
  identified as the production rover for GCP occupations / single-point RTK).
- TOML config retained instead of switching to YAML — too invasive a refactor for
  marginal benefit; stdlib `tomllib` vs `pyyaml` dependency tilts back the other way.
  Flagged explicitly in DEC-028 cross-repo note.
- LoRa frame v2 kept rover-side-ready; flag that sibling's Heltec firmware is still
  at v1 in `docs/CROSS_REPO_BACKLOG.md` and `docs/BASE_STATION_INTEGRATION.md`.

**Alternatives Considered:**
- Continue ad-hoc divergence (cheap now, expensive at the first cross-repo
  field-debugging session).
- Hard-fork the sibling's `base-station/` patterns into this repo as a vendored
  copy (locks rover into a snapshot; misses sibling's ongoing improvements).
- Switch rover to YAML to match sibling exactly (huge refactor for marginal
  alignment payoff; sibling chose YAML for `pyyaml`-era reasons that don't apply
  to a Python 3.11+ stdlib-tomllib codebase).

**Implications:**
- `src/rover/_io.py` carries the atomic-write helper (Stage B).
- `src/rover/telemetry.py:STATUS_SCHEMA_VERSION = 1` exists as the canonical
  rover-side schema version (Stage B).
- `scripts/georef.py:ZONE_EPSG` mirrors sibling's zone-name vocabulary (Stage B).
- `src/rover/watchdog.py` sends `READY=1` / `WATCHDOG=1` to systemd via
  `NOTIFY_SOCKET` when present (Stage C).
- `deploy/` directory with systemd units, udev rules, and install.sh exists
  (Stage C).
- This DECISIONS.md uses DEC-NNN naming with sibling-style metadata headers (Stage D.1).
- `README.md` and `CLAUDE.md` explicitly position the DIY rover relative to the
  SparkFun Facet (Stage D.2).
- `docs/CROSS_REPO_BACKLOG.md` tracks sibling-side work the rover is waiting on
  (Stage D.4).
- `docs/BASE_STATION_INTEGRATION.md` §4 carries a clear callout that sibling's
  Heltec firmware is still on LoRa frame v1 (Stage E).

## 13. Camera Measurement Decisions

### DEC-036: ELP Stereo Pair as a Post-Processed Measurement Instrument (supersedes DEC-026)

**Status:** Accepted · Amended by DEC-038 (targets) and DEC-042 (camera rig); both flag open conflicts
**Date:** 2026-09-29
**Decided by:** Brian
**Rationale:** The retired HQ Camera was a context camera. The two ELP 16MP
cameras replacing it, mounted as a same-direction stereo pair on the rotating
platform, can measure target bearings to about 0.01° once calibrated. That is
the missing piece for locating the scanner where RTK fails: under canopy,
against facades, down stream banks. The same calibration also enables
per-point colorization. Both run offline, so DEC-022 still holds.

**Decision:** The ELP stereo pair is a measurement instrument whose images are
processed offline in `scripts/georef.py`. Its roles, in priority order:

1. **Target bearings for station resection.** Detect ARM's existing Sky High GCP
   targets, a 2×2 checker "X", over surveyed points, and solve station position
   and heading. Targets lie flat by default and go on rods only where geometry
   requires it (amendment below).
   - Targets within ~10 m: camera bearing plus LD19 plane-fit range; 2 targets
     suffice with the scanner leveled, 3 give a check. *(Flat targets: ~5 m, not
     ~10 m. See the 2026-09-30 amendment below.)*
   - Targets beyond ~10 m, where the LD19's 12 m spec runs out: bearings-only
     resection from 3 targets, 4 for a check, or GNSS/PPK position with the
     targets supplying heading only.
2. **Per-point colorization.** Project each LiDAR point into each calibrated
   camera at its capture mast angle, with occlusion (z-buffer) handling and a
   best-image choice per point. A panorama sampled from the scan origin is
   rejected; the cameras sit ~80–90 mm off the rotation axis.
3. **Stereo range as a cross-check only.** Stereo flags bad LiDAR range on a target.
   It is never the primary range: at 15 m its error is decimetres with the stock
   lenses.
4. **Context imagery,** as under DEC-026, continues unchanged.

On the rover, cameras only capture. Processing, detection and decoding happen
offline. Capture rules:
- One camera streams at a time, only with the mast stopped and the gyro quiet.
- Exposure, gain and white balance are locked, re-applied on every open, and
  read back.
- Raw MJPEG bytes are saved undecoded with a JSONL record: camera ID, USB path,
  kernel timestamp, mast angle, gyro RMS, and control values read back.
- Calibration sessions use lossless luma captures, not MJPEG.

**Target version:** Split across two releases.
- v1.0: the V4L2 capture backend. Retiring the HQ Camera broke context capture, so
  it can't wait.
- v1.1: target resection, colorization and stereo, alongside the extrinsic
  calibration they depend on.

**Gates before implementation** (tests in
`docs/research/elp-stereo/REPORT.md`):
- `lsusb -v` transfer type and `v4l2-ctl` formats/controls confirm the capture design.
- Dual-stream and serial-gap tests confirm camera capture does not starve the
  LD19 or F9P.
- ChArUco intrinsics settle the real focal length and lens model.
- Repeatability tests show the pair holds its relative yaw well enough to use.
- For v1.1 resection (not the v1.0 capture backend): tests 11–14 in
  `docs/research/elp-stereo/notes/target_placement_geometry.md` set the target
  field procedure (2026-09-30 amendment).

**Context:** 2026-09-29 deep dive (report above). Key facts:
- Likely model: ELP-USB16MP01-BH120.
- Focal length unpublished, ~1,400–2,500 px; "no distortion" is marketing.
- All Pi 4 USB 2.0 traffic shares one 480 Mbit/s hub.
- uvcvideo reserves isochronous bandwidth at stream start, so two full-res
  streams cannot run at once.
- No hardware sync between units.
- Identical units report the same serial.
- LD19 specified to 12 m.
- No DIY rotating-LiDAR build found using stereo cameras; PiLiDAR colorizes from
  an origin panorama without camera-offset correction.

**Rationale:**
- Bearing precision from calibrated checker corners, about 2 mm lateral at
  15 m, exceeds anything the LD19 gets from sphere fitting at the same range.
- ARM's existing Sky High GCP targets are already the right design: a 24 in
  (61 cm) 2×2 black/white checker with 12 in quadrants. The eyelet is at the
  saddle point and a number 0–9 gives each target an ID. At 15 m, one spans
  about 57–71 px across with the stock lenses, so the stock lenses stay. That keeps
  the wide view colorization needs, and no new targets are needed.
- One calibration serves both resection and colorization.
- Offline processing keeps the Pi's job to capture and matches DEC-022.

**Alternatives Considered:**
- Keep DEC-026: cameras stay context-only. Leaves canopy stations with no
  positioning path beyond GNSS and cloud-to-cloud registration.
- LiDAR sphere targets instead of camera targets: the LD19 gets only 2–3 points
  per scan line on a 200 mm sphere at 5 m, far too few to fit it reliably.
- Stereo as the primary range source: decimetre error at 15 m, and sensitive to
  0.008° of relative yaw drift.
- Structure-from-motion from the rotating cameras: a camera rotating in place has
  no baseline, so it recovers no depth.
- 6 mm M12 lenses now: better per-pixel resolution, but a 47° view that hurts
  colorization coverage. Deferred until calibration shows larger targets are not
  enough.

**Implications:**
- `src/rover/camera.py` moves from Picamera2 to a V4L2 backend. `[camera]` config
  covers two devices, and `deploy/udev/` names cameras by USB port path.
  `picamera2` leaves the dependency list.
- Camera intrinsics, stereo extrinsics and camera-to-LiDAR extrinsics join the
  v1.1 calibration procedure.
- `scripts/georef.py` gains target detection, resection and colorization.
- **Targets:** the field kit reuses the Sky High GCP targets over surveyed nails,
  flat by default and on rods only where needed (amendment below). The printed
  number is the target ID, so no ArUco marker is needed. Detection fits the four
  quadrant edges rather than trusting the centre pixel, because the eyelet sits
  on the saddle point.
- **Conflicts resolved on acceptance (2026-09-29):**
  - `CLAUDE.md` §9 and `docs/ROADMAP.md` now place colorization and target
    resection at v1.1. Full texture-mapped meshes and photogrammetry remain
    out of scope.
  - `CLAUDE.md` decision count and key-decision table include DEC-036.
- **Not decided here:**
  - Scanner GCP/SCAN operating modes.
  - Whether to upgrade the LD19.
  - The target field procedure.
  Each needs its own decision.

**Amendment 2026-09-29 — flat-by-default targets:**

- **Flat is the default.** Targets lie flat over their nails, the same as for the
  drone, whenever the viewing angle is at least ~12°. The viewing angle is the
  sight line's angle to the target surface: mast-height angle plus any ground
  tilt toward the scanner, or plus the drop when the scanner stands higher.
- **Why flat works.** A 24 in target needs ~20 px of foreshortened height, about
  10 px per quadrant, for reliable detection. From a 1.5 m mast on level ground
  that holds to ~7 m. It holds farther where ground tilts toward the scanner or
  the scanner stands higher, as on banks, swales and stream beds. Example: 10 m
  with 10° of tilt toward the scanner gives ~27–34 px.
- **Why flat is preferred:**
  - Drone and scanner share targets in the same session, with no remounting.
  - The survey point is the nail itself. A rod 1° off plumb moves a 1.5 m-high
    centre ~2.6 cm.
  - The same targets tie scanner data to the drone cloud.
  - Surveyed 3D coordinates plus camera azimuth and elevation allow camera-only
    resection from 3 targets beyond the LD19's range.
- **Rods are the exception.** Use them only for targets that must be far away on
  level or falling ground. On a rod:
  - The target is vertical, facing the scanner, with rigid backing.
  - The survey point is the eyelet centre, a known height above the nail.
  - A rod-mounted target cannot serve the drone at the same time. Fly first,
    then remount, or keep spare targets for the scanner. See
    `docs/CROSS_REPO_BACKLOG.md` CR-006.
- **Field risks for flat targets:**
  - Grass and leaf litter hide them at low angles. Clear a strip toward the
    scanner.
  - Sheen washes out the black quadrants near grazing.
  - Elevation angle is less precise than azimuth on a flat target.

**Amendment 2026-09-30: target placement geometry (hypothesis, pending tests 11–14):**

Worked numbers are in `docs/research/elp-stereo/notes/target_placement_geometry.md`.
They correct one part of this decision and flag one risk. Neither changes the
decision itself.

- **Correction: range plus bearing is a ~5 m method for flat targets, not ~10 m.**
  A flat 24 in target collects ~11 LD19 points at 5 m, ~4 at 7 m and ~1 at 10 m,
  so a plane fit on the target fails past ~5 m. Fitting the surrounding ground
  and intersecting the camera ray with it does not rescue longer ranges: range
  error is height error ÷ sin(viewing angle), about 7× at 10 m from a 1.5 m mast.
  - Flat targets within ~5 m: bearing plus LD19 range, as above.
  - Flat targets from 5 m to the ~7 m detection limit: azimuth-only resection,
    3 targets, 4 for a check.
  - The ~10 m range-plus-bearing case survives for vertical rod targets only,
    pending test 10.
- **Risk: mast angle, not the camera, likely sets the bearing error.** Each target is
  imaged at a different mast angle from the open-loop stepper (DEC-016/017).
  Microstep positions are not evenly spaced, and a 0.05–0.1° mast error is
  ~9–17 mm at 5–10 m against ~2 mm from the camera. That still fits the ±5–10 cm
  budget. Until test 12 measures it, quote system bearing precision as the mast
  figure, not 0.01°.
- **Elevation angles are secondary observations.** They carry the IMU's levelling
  error. Resect on azimuth; take station height from GNSS or the LD19 ground.
- **Provisional placement:** 3 flat targets at 4–6 m, similar distances, ~120°
  apart, scanner inside their triangle to stay off the danger circle. Beyond ~7 m
  on level ground, use rods. For heading only with a GNSS fix, use one target
  as far away as can be detected.
- **Still not decided:** the target field procedure. Tests 11–14 (detection
  floor, mast repeatability, ground-plane range, resection geometry) feed that
  decision.

---

## 14. Static-Station Scanner Redesign (2026-10-01 / 2026-10-02)

Recorded 2026-10-02 from a two-day design session with Brian. The session started from a
concrete use case: scanning the facades and roof soffits of a two-story school with clear
sky, then registering the result to a drone LiDAR flight in Trimble TBC with a base logging
RINEX. Working that case through turned the rover into a **static, station-based terrestrial
scanner**. DEC-037 sets that workflow; DEC-038 to DEC-045 are the hardware and software
choices that follow from it.

**Conflicts with earlier decisions are flagged in each entry, not resolved silently.** The
largest is the target method: DEC-036 makes flat checker targets the default for camera
resection, and DEC-038 adds tripod-hung PVC cylinders as the primary scanner target. See
DEC-038.

---

### DEC-037: Static Station-Based Scanning Workflow

**Status:** Accepted
**Date:** 2026-10-02
**Decided by:** Brian
**Rationale:** At facade and soffit ranges, absolute accuracy is set by station position and
heading, not by the LiDAR. A leveled, stationary scanner located from surveyed targets meets
±5–10 cm where a moving rover with consumer GNSS and a MEMS IMU cannot, especially where the
building blocks half the sky.

**Decision:** The scanner works as a terrestrial laser scanner: set up on a tripod at a series
of stations, scan with the head stepping and settling, and locate each station from surveyed
targets. The field sequence is:

1. Base station on a nail, logging static data for the whole session (submit to OPUS later to
   put the nail on NAD83(2011)).
2. Survey the GCP nails with the scanner's F9P in GCP mode: two occupations of 2–3 min each,
   at least 30–60 min apart. Hold 1–2 back as checkpoints.
3. Set a registration target over each nail (DEC-038).
4. Lay out stations so each sees 3 targets spread more than 30° apart in bearing, and
   neighbouring stations share at least 2.
5. At each station: GNSS fix if available, LiDAR scan, a 0° camera registration frame, then
   the tilted camera frames (DEC-042).
6. Log station ID, visible target IDs, target heights, timestamps and mode.

The scan loop is **step-and-scan**: step, settle (~0.5 s), confirm stillness on the gyro,
capture one or two full LD19 revolutions, read the encoder (DEC-040), repeat. Nothing moves
during a capture.

**Context:** For a two-story building (eave ~8.5 m, an estimate from Street View), the
workable LD19 standoff is ~8–10 m, where the facade blocks sky down to ~36–42° elevation over
nearly 180° of azimuth. GNSS degrades exactly where the scanner must stand. At 10 m, 0.3° of
heading error is ~5 cm.

**Rationale:**
- Targets give position *and* heading, so the station no longer depends on GNSS or a compass.
- Step-and-scan removes the timing problem: with nothing moving during a capture,
  LiDAR-to-IMU timestamp interpolation (DEC-014) stops mattering for point accuracy.
- It is the workflow TBC already registers natively (cloud-to-cloud and target-based).

**Alternatives Considered:**
- Mobile scanning with direct georeferencing (RTK + IMU): fails under eaves and next to tall
  walls; the MPU-9250 drifts within seconds without GNSS.
- Photogrammetry alone: textureless soffits and white trim do not match; needs more control,
  not less.

**Implications:**
- The LD19 stays for v1.0. Its ~12 m rated range (less on dark surfaces) caps standoff, which
  is the main argument for an upgrade. The upgrade fork stays open: Unitree L2 (~$400, 15 m at
  10% reflectivity), Livox Mid-360 (~$900–1,000, 40 m at 10%), used Livox Mid-40 (~$460–690,
  90 m at 10%, 38.4° cone, no IMU).
- The LD19's mounting offset from the rotation axis and its plane orientation (radial or
  tangential) are set in the case redesign and measured in the LiDAR-to-axis calibration.
  A tangential plane leaves a blind cylinder above the axis; a radial one does not.
- Insta360-style 360° cameras are rejected: proprietary stitching, poor calibratability,
  awkward Pi control, and no clean mount.
- `src/rover/main.py` orchestration becomes station-oriented (see DEC-043 modes).

---

### DEC-038: Registration Targets — Tripod-Hung Retroreflective PVC Cylinders (amends DEC-036)

**Status:** Accepted
**Date:** 2026-10-02
**Decided by:** Brian
**Rationale:** From a 1.3–1.5 m scanner height, a flat 24 in checker on the ground is a ~7°
grazing target at 10 m: ~11 px tall on camera and about zero LD19 points. A vertical cylinder
hung on a plumb line is self-plumbing, looks the same from every station, and gives the LD19
enough points to fit an axis.

**Decision:**
- **Target:** 4 in PVC pipe (Schedule 40 or thin-wall DWV), 60 cm long, wrapped in two or three
  bands of DOT-style retroreflective tape at measured heights, with plain stretches between.
- **Suspension:** hung from a small tripod by an eye bolt through a centred hole in the top end
  cap, on braided mason's line (not stretchy cord), with an 8–16 oz brass plumb bob below,
  tip just above the nail eyelet. Gravity plumbs the axis over the nail.
- **Quantity:** 10, matching the numbered 0–9 checker kit one-to-one. Around a rectangular
  building: one off each corner (diagonally), one at the midpoint of each side 10–15 m out in
  open sky, plus 2 checkpoints. Add one per extra corner for wings or an L-shape.
- **Per-target record (once):** eyelet-to-bottom-of-pipe height, band heights, and the pipe's
  GCP number painted on it.
- **Detection:** RANSAC cylinder fit on the LiDAR points, with the reflective bands as
  known-height intensity markers. The fitted axis gives the nail position.
- **Checker targets stay flat for the drone.** Same nails. Fly first, then hang the pipes.

**Conflict with DEC-036 (flagged, not resolved):** DEC-036 and its 2026-09-29 amendment make
flat checkers the scanner default, with rods as the exception. DEC-038 makes the PVC cylinder
the default **LiDAR** target. The two can coexist: the cylinder gives range and a LiDAR-fit
position; the flat checker still serves camera bearings within ~5–7 m and ties to the drone.
**Not yet decided:** whether camera resection (DEC-036 role 1) keeps targeting the flat checkers
or moves to detecting the cylinders. DEC-036 tests 11–14 should be re-scoped to include the
cylinders before that decision.

**Context:** Options considered in order during the session: flat 60 cm checkers, the same
checkers stood vertically on rods, 36 in traffic cones, tripods with a hanging chain, and
tripods with a hanging PVC cylinder.

**Alternatives Considered:**
- **Vertical checker on a rod:** good camera target (~84 × 84 px at 10 m) but faces one way,
  needs rotating per station, and leans unless plumbed.
- **36 in traffic cone over the nail:** symmetric, self-standing, reflective collars; but
  centring is manual and a 2° lean moves the top ~3 cm. Strong runner-up.
- **Hanging chain as the plumb line:** too thin for the LD19 at 10 m (mixed-pixel edge points
  corrupt the centreline) and sways in wind.

**Implications:**
- Field kit: 10 small tripods, 10 pipes, line, bobs, tape. Tripod legs appear in scans and can
  block sight lines.
- In wind, damp the bob in a bucket of water.
- Calibrate each hang indoors once: the bob tip should land within a few mm of a mark directly
  below the eye bolt.
- Software: cylinder detection joins `scripts/georef.py` alongside DEC-036's checker detection.

---

### DEC-039: Station Heading — Target Resection Primary, Magnetometer as Coarse Hint Only

**Status:** Accepted
**Date:** 2026-10-02
**Decided by:** Brian
**Rationale:** At 12 m range every 1° of heading error moves points ~21 cm; the budget needs
~0.1–0.2°. Only targets meet that with hardware already owned.

**Decision:**
- **Primary:** heading comes from resection on the DEC-038 targets. Matching is automatic:
  predicted ranges from the approximate station (pole GNSS or station fix) to every GCP are
  compared with detected cylinder ranges, or target-to-target triangle shapes are matched to
  the surveyed layout. A 2D best-fit rotation (Kabsch/Helmert) gives heading plus residuals.
- **Magnetometer:** coarse heading hint (±5° is enough) to seed target identification, and a
  "magnetically dirty station" flag from comparing measured field strength and dip to WMM
  values. Never a heading source.
- **Optional, cheap:** a backsight beacon on the base pole (sibling SS-1; this repo CR-007)
  and a retroreflective band on the base pole (sibling SS-3; CR-008).
- **Deferred to Phase 2:** dual-antenna GNSS heading (Unicore UM982, 0.1–0.2° per 1 m
  baseline), only if target matching proves unreliable in the field.

**Context:** Magnetometer weaknesses were verified for this use on 2026-10-02:
- Steel, rebar and chain-link deflect readings by degrees to tens of degrees. ArduPilot keeps
  drone compasses 5 m from steel-and-concrete buildings for degree-level tolerance.
- A stepper's residual field changes the offset after every step.
- At ~66° dip, 1° of tilt error costs 2–5° of heading.
- The WMM2025 declination model is good to ~0.4°; local anomalies of 3–4° are common.
- Best case in an open field with perfect calibration is ~0.5–0.6°, 3–5× worse than needed.

**Alternatives Considered:**
- Dual F9P moving base: ~0.4°, and both antennas must ride the rig, which conflicts with the
  offset pole (DEC-043).
- Sun compass from a sky-facing camera: viable secondary (the retired HQ Camera + fisheye is a
  candidate), weather-dependent; not built for v1.0.
- North-finding gyro: needs ~0.02°/h bias stability, thousands of dollars.
- Sighting scope zeroed on a backsight: accurate but one manual step per station.

**Implications:**
- Resolves the heading half of open item S3-R1 (`CROSS_REPO_BACKLOG.md`): absolute azimuth
  comes from targets, so Madgwick's magnetic-north frame no longer sets cloud orientation.
  The NWU→ENU frame fix is still owed for any magnetometer-derived output.
- `DEC-013` (magnetometer disabled during motor) still applies to the hint.

---

### DEC-040: Rotation Drive — Geared Stepper, Turntable Bearing, Absolute Encoder (supersedes DEC-016 and DEC-017; amends DEC-015)

**Status:** Accepted (encoder, bearing, driver) · Provisional (exact gearmotor)
**Date:** 2026-10-02
**Decided by:** Brian
**Rationale:** A 75 cm camera bar on the head (DEC-042) puts ~7,700:1 load-to-rotor inertia on a
direct-drive NEMA17, so it overshoots, rings and skips. Gearing cuts that to ~10:1. An encoder
on the output shaft reads the true angle, which DEC-036's 2026-09-30 amendment identified as
the likely limit on bearing accuracy.

**Decision:**
- **Motor:** NEMA17 with an integrated ~27:1 planetary gearbox (~$30–50). Provisional on the
  exact part.
- **Driver:** TMC2209 (quiet, microstepping, runs cool), replacing the A4988.
- **Bearing:** turntable ("lazy susan") bearing carries the head; the motor only supplies
  rotation.
- **Encoder:** AS5600 12-bit magnetic encoder on the **output** shaft, diametrically magnetized
  magnet, 0.5–3 mm air gap, DIR tied to GND, I2C 0x36. It is also the home reference.
  A bench correction table (stepper counts vs encoder over a full turn) removes off-centre error.
- **Balance:** centre the camera bar on the axis and use the LiDAR as counterweight.
- **Motion rules:** approach each position from the same direction (planetary backlash ~1°),
  settle ~0.5 s, and capture only when the gyro reports still.
- **Cables:** rotate and unwind, no slip ring (DEC-015's cable approach stands).

**Context:** Rough figures: 75 cm 2020 bar plus two ~100 g cameras ≈ 0.046 kg·m²; NEMA17 rotor
≈ 60 g·cm². A 5:1 belt still leaves ~300:1.

**Rationale:**
- Encoder closes the loop that DEC-016 left open, so missed steps or backlash cannot silently
  rotate a scan.
- Gearing gives fine angular steps without relying on uneven microstep positions (the DEC-017
  concern raised in DEC-036's amendment).

**Alternatives Considered:**
- Keep direct drive (DEC-015/016/017): inadequate for the camera bar.
- 5:1 belt reduction: not enough inertia reduction.
- Worm drive: self-locking and wind-resistant, but slower and fussier; revisit only if wind is a
  problem.
- Fixed (non-rotating) camera bar on the tripod: stiffer, but loses automated panoramas.

**Implications:**
- `src/rover/stepper.py` moves from A4988 step/dir timing to TMC2209 and reads the AS5600.
  GPIO pin assignments in `CLAUDE.md` §7 need revisiting when the driver changes.
- DEC-016 and DEC-017 are superseded. DEC-015 stands for "no slip ring" but not for "direct drive".

---

### DEC-041: Attitude Sensing — HWT906 on the Base, Two MPU-9250s on the Camera Bar (supersedes DEC-011)

**Status:** Accepted
**Date:** 2026-10-02
**Decided by:** Brian
**Rationale:** A static scanner needs a quiet, stable tilt reference and a bump detector, not a
fusion IMU. The single MPU-9250 next to the motor was the wrong sensor in the wrong place.

**Decision:**
- **WitMotion HWT906-TTL** on the **fixed base**, squared to the base edges. Jobs: leveling
  display, logged residual tilt per station, and gyro stillness/twist detection (catches a
  tripod nudged around the vertical axis, which no tilt sensor and no head encoder can see).
  TTL UART. Its magnetometer is used only for DEC-039's coarse hint.
- **Two MPU-9250s at the ends of the camera bar** (~15 in / ~38 cm from the motor), at I2C 0x68
  and 0x69 (AD0 high). Jobs: camera tilt angle (accelerometer, 0.5 s averaging, 180° flip zero
  calibration), bar twist and sag detection from end-to-end disagreement, and a two-point
  magnetic gradiometer as a better dirty-station detector. Both raw readings are logged every
  capture, not only their average.
- **Verify genuine parts:** WHO_AM_I must read 0x71 (MPU-9250); 0x70 is an MPU-6500 with no
  magnetometer. Buy both new boards from one listing; keep the owned unit as a bench spare.

**Context:** Options compared 2026-10-01: BNO055 (Pi I2C clock-stretching problems, silent
auto-calibration moves its zero), Murata SCL3300 inclinometer (best static tilt, hard to buy
outside distributors), WitMotion WT901 / HWT905 (single MPU-9250 inside), HWT901B-RS232 (RS232
levels would damage the Pi), HWT906 (four-chip array with temperature compensation).

**Rationale:**
- HWT906 averages four sensors and compensates temperature, which matters for a zero that must
  hold between sessions. Its "0.05°" claim is unverified; run a 180° reversal test on arrival.
- Moving the MPU-9250s away from the motor and pairing them turns a liability into a QC check.

**Alternatives Considered:** listed under Context. An AS5600 on the tilt hinge was the first
choice for camera tilt and was replaced by the bar MPU-9250s, which need no magnet alignment and
also read bar roll.

**Implications:**
- I2C bus: AS5600 (0x36), MPU-9250 (0x68), MPU-9250 (0x69). One bus, no mux. Run it at 100 kHz
  with twisted SDA/SCL pairs; the runs to the bar ends are ~40 cm plus the unwind bundle.
- UART devices: LD19, HWT906 and the HoI laser (DEC-044). The F9P moves to USB to free a UART.
- `src/rover/imu.py` and Madgwick (DEC-012) become secondary for static scanning.
- DEC-011 is superseded.

---

### DEC-042: Camera Rig — 75 cm Stereo Bar on a Manual Tilt Platform (amends DEC-036)

**Status:** Accepted
**Date:** 2026-10-02
**Decided by:** Brian
**Rationale:** Stereo depth error scales with range squared over baseline. At the ~12 m soffit
range a 10 cm baseline gives ~26 cm; 75 cm gives ~3.5 cm. Manual tilt points the cameras at
the soffits instead of the lawn.

**Decision:**
- **Baseline:** 75 cm (~30 in), on one stiff length of 2040 aluminium extrusion.
- **Mount:** the bar sits on a laser-level tilt platform on the rotating head, balanced on the
  hinge, with a second screw or stiff plate so the bar cannot twist about the single mount screw.
- **Tilt:** set by hand (e.g. 0°, 30°, 60°). The angle is **measured** by the bar-end MPU-9250s
  (DEC-041), not read from the platform's dial (±0.5–1° repeatability is ~10 cm at 12 m).
- **Calibration:** one stereo calibration (the cameras share the rigid bar), one bar-to-scanner
  calibration at 0°, plus the hinge axis. Each capture applies the measured tilt.
- **Camera settings:** lock focus, exposure and white balance before calibrating.
- **Registration frame:** every station shoots a 0° frame before tilting, so ground targets are
  in view.

**Conflict with DEC-036 (flagged):** DEC-036 places the cameras ~150–180 mm apart on a 200 mm
plate, ~80–90 mm off the rotation axis, and limits stereo to a cross-check because of
decimetre-level error at 15 m. At 75 cm the stereo error at 8–12 m is ~1.6–3.5 cm (assuming
~1,370 px focal length and 0.25 px matching), which may justify a larger stereo role. **Role
ordering in DEC-036 is unchanged until calibration measures the real error.** Colorization must
also account for cameras now ~37 cm off the axis.

**Alternatives Considered:**
- Commercial stereo cameras (ZED, OAK-D class): ~12 cm baselines, ~1.9 m error at 30 m.
- Baselines above ~1/10 of range: the views diverge too far to match.
- Motorized tilt axis: adds a motor, axis non-orthogonality and another boresight for no gain
  over a measured manual tilt. A vertically mounted LD19 already reaches the zenith.

**Implications:**
- Head inertia and balance drive DEC-040.
- `[camera]` config gains tilt angle and the hinge-axis calibration.
- Plain white soffits still won't match in stereo; LiDAR covers them.

---

### DEC-043: GNSS Antenna on an Offset Pole; Two Operating Modes

**Status:** Accepted
**Date:** 2026-10-02
**Decided by:** Brian
**Rationale:** Moving only the antenna into open sky keeps one Pi logging everything while
getting the fix away from the wall.

**Decision:**
- **Hardware:** the F9P and Pi stay in the scanner box. The ANN-MB-00 antenna (on its metal
  ground plate, same as the base) mounts on a survey pole, connected by its 5 m cable. Mount
  the F9P on the fixed base so the cable never winds. Clamp the cable at the box for strain relief.
- **Reach:** ~3 m horizontal after pole height and slack. A few metres of low-loss extension
  (RG316 or LMR-200, not RG174) should work given the antenna's built-in amplifier; check C/N0
  in u-center before and after.
- **Pole as a target:** wrap it in retroreflective tape so the LiDAR locates it each station.
- **Two top-level modes:**
  1. **GCP mode:** pole on a nail, average the fix, log the point ID. Writes the sibling DEC-029
     occupation-event format (BS-R2).
  2. **Scan mode,** with an antenna setting:
     - **On tripod:** antenna on a short side arm off the fixed base (not above the head, which
       is in the LD19's zenith sweep; mask the arm in software). Fixed calibrated offset to the
       scanner origin. Default for open-sky stations.
     - **Offset pole:** LiDAR finds the taped pole; measured offset. For close-in stations.
     - **None:** targets only. The scan still runs where no fix is available.
  Log the antenna setting and offset in every station's metadata.

**Context:** A distance from the pole alone places the scanner on a circle; a direction is also
needed. Seeing two known points (the live pole plus a target, or two targets) fixes both.

**Alternatives Considered:**
- Three separate modes (GCP, scan-on-tripod, scan-offset): the scan path is identical, so three
  modes would mean three code paths drifting apart.
- Splitting GNSS into a separate rover unit: unnecessary once the antenna, not the receiver, moves.

**Implications:**
- Dual-antenna heading (DEC-039 Phase 2) would require both antennas on the rig, which this
  mode does not provide.
- `src/rover/gnss.py` connects over USB.

---

### DEC-044: Height of Instrument — Phase-Shift Laser Module and Height Plate

**Status:** Provisional (part choice); Accepted (method)
**Date:** 2026-10-02
**Decided by:** Brian
**Rationale:** Station height from resection with 3+ 3D targets is already solved; a
millimetre-class measurement of height above the mark is the independent check, and the same
sensor detects tripod settling.

**Decision:**
- **Method:** a downward laser module on a short arm off the fixed base, clearing the tribrach
  and tripod head (~15–17 cm across), aimed at a light matte height plate (~25–30 cm across, with
  a centre hole or three short legs) set flush over the nail.
- **Height chain:** antenna height above mark = laser reading + (scanner bottom → antenna
  reference point) − plate thickness. Tilt correction is negligible (0.3° over 1.5 m ≈ 0.02 mm);
  log tilt anyway. Measure every height to one antenna reference point (e.g. the bottom of the
  ANN-MB-00 plate), the same point used for the base and for OPUS.
- **Part:** DFRobot SEN0366 (±1 mm SD, visible ~6 mm spot at 10 m, 3.3–5 V TTL UART, Python
  library `serial-laser-ranger`), unless an owned Bosch laser measure proves hackable first
  (C models over Bluetooth; non-C models via the battery-compartment serial port).
- **Checks:** tape the slant height each station as a blunder check; a resection-vs-taped
  disagreement over ~2 cm flags a misidentified target, an unrecorded target height or a moved
  tripod.

**Context:** Rejected after review on 2026-10-01: TOF10120, VL53L7CX 8×8, drone altimeter
(±2–3 cm), Benewake TFmini Plus (±5 cm), Parallax LaserPING (55° FOV) and PING ultrasonic,
Waveshare TOF (C) (±3 cm), DFRobot SEN0590 (19° cone). All are wide-beam or centimetre-class.
JRT M88B (±1 mm, but 0–40 °C and 2.0–3.3 V only) and Meskernel LDL-T are alternates.

**Alternatives Considered:** listed under Context. A short-range ultrasonic was kept as an idea
for a proximity guard (pause a capture when someone walks within ~2 m), not for height.

**Implications:**
- One more UART device (DEC-041 implications).
- Bench-test the SEN0366 at the actual mount height: one forum report gave out-of-range errors
  below 300 mm and up to 3 m, contradicting the 0.05 m spec.

---

### DEC-045: Operator Display — DSI Touchscreen on the Fixed Base

**Status:** Accepted
**Date:** 2026-10-02
**Decided by:** Brian
**Rationale:** The operator stands at the tripod; a screen on the scanner replaces a handheld,
and the sibling base station already runs and has tuned the same panel class.

**Decision:**
- A 4–5" capacitive DSI touchscreen on the fixed base, with a printed sun hood. Prefer the
  sibling's 4.3" Freenove panel so its `display_touch.py` and `display_hold.py` port directly
  (BS-R1).
- One screen carries the level display (bullseye plus X/Y bars, colour bands at ≤0.1° and
  ≤0.5°, 0.5 s smoothing), GNSS status, encoder and camera-tilt angles, a "STILL" flag and the
  scan controls.
- No T-Deck on the scanner. A phone can view the same UI if the Pi serves it as a web page.
- Optional: a 12–16 LED WS2812 ring as a sunlight-readable level.

**Context:** The T-Deck was already owned by the Base-Station under DEC-033. A 1.54" ST7789
SPI display was considered first and dropped when the touchscreen took over its role.

**Alternatives Considered:** 1.54" SPI TFT; T-Deck mirror over LoRa.

**Implications:**
- DSI frees SPI and GPIO.
- The ESP32 LoRa boards stay for the RTCM fallback (DEC-031); they are unaffected.

---

## Decision Index

| ID | Topic | Section |
|----|-------|---------|
| DEC-001 | DIY vs Commercial | System |
| DEC-002 | PiLiDAR Foundation | System |
| DEC-003 | Pi vs MCU | System |
| DEC-004 | ZED-F9P Selection | GNSS |
| DEC-005 | RTK via LoRa | GNSS — **superseded by DEC-031** |
| DEC-006 | RTCM Routing Direct | GNSS — **superseded by DEC-032** |
| DEC-007 | RTCM Profiles | GNSS |
| DEC-008 | LoRa Parameters | Comms |
| DEC-009 | Packet Loss Handling | Comms |
| DEC-010 | T-Deck Receive-Only | Comms — **superseded by DEC-033** |
| DEC-011 | MPU-9250 Primary | Sensor — **superseded by DEC-041** |
| DEC-012 | Madgwick Filter | Sensor |
| DEC-013 | Mag Disabled w/ Motor | Sensor |
| DEC-014 | Timestamp Slerp | Sensor |
| DEC-015 | Direct Drive | Mechanical — **amended by DEC-040** |
| DEC-016 | Open-Loop Indexing | Mechanical — **superseded by DEC-040** |
| DEC-017 | 1/16 Microstepping | Mechanical — **superseded by DEC-040** |
| DEC-018 | Split Power Domains | Power |
| DEC-019 | Dedicated 3.3V Reg | Power |
| DEC-020 | Python + Pi OS Lite | Software |
| DEC-021 | JSONL Logging | Software |
| DEC-022 | Post-Processed Georef | Software |
| DEC-023 | SLAM Deferred | Software |
| DEC-024 | Accuracy Target | Accuracy |
| DEC-025 | Validation Method | Accuracy |
| DEC-026 | Camera as Reference | Camera — **superseded by DEC-036** |
| DEC-027 | Triggered Capture | Camera |
| DEC-028 | TOML Config | Config |
| DEC-029 | GPIO Library (rpi-lgpio) | Upstream Compat |
| DEC-030 | Dual-Mode (personal / arm_group) | Base-Station Integration |
| DEC-031 | NTRIP-Primary + LoRa Fallback | Base-Station Integration |
| DEC-032 | NTRIP Client Location (Pi or ESP32) | Base-Station Integration |
| DEC-033 | Triple-Channel Telemetry | Base-Station Integration |
| DEC-034 | Coords: log SI/WGS84, convert at export | Base-Station Integration |
| DEC-035 | Deep Alignment with arm-drone-lidar-workflow | Deep-Alignment Overhaul |
| DEC-036 | ELP Stereo Pair as Measurement Instrument | Camera Measurement — **amended by DEC-038, DEC-042** |
| DEC-037 | Static Station-Based Scanning Workflow | Static-Station Redesign |
| DEC-038 | Tripod-Hung PVC Cylinder Targets | Static-Station Redesign |
| DEC-039 | Heading: Target Resection, Mag as Hint | Static-Station Redesign |
| DEC-040 | Geared Stepper + Turntable + AS5600 | Static-Station Redesign |
| DEC-041 | HWT906 Base + Two Bar MPU-9250s | Static-Station Redesign |
| DEC-042 | 75 cm Stereo Bar on Manual Tilt | Static-Station Redesign |
| DEC-043 | Offset-Pole Antenna; GCP / Scan Modes | Static-Station Redesign |
| DEC-044 | Height of Instrument: Laser + Plate | Static-Station Redesign |
| DEC-045 | DSI Touchscreen on Fixed Base | Static-Station Redesign |
