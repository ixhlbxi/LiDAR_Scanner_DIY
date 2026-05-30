# Design Decisions Log

**Document Status:** v0.10 — deep alignment with arm-drone-lidar-workflow
**Last Updated:** 2026-05-30

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

**Status:** Accepted
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

**Status:** Accepted
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

**Status:** Accepted
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

**Status:** Accepted
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

**Status:** Accepted
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
| DEC-011 | MPU-9250 Primary | Sensor |
| DEC-012 | Madgwick Filter | Sensor |
| DEC-013 | Mag Disabled w/ Motor | Sensor |
| DEC-014 | Timestamp Slerp | Sensor |
| DEC-015 | Direct Drive | Mechanical |
| DEC-016 | Open-Loop Indexing | Mechanical |
| DEC-017 | 1/16 Microstepping | Mechanical |
| DEC-018 | Split Power Domains | Power |
| DEC-019 | Dedicated 3.3V Reg | Power |
| DEC-020 | Python + Pi OS Lite | Software |
| DEC-021 | JSONL Logging | Software |
| DEC-022 | Post-Processed Georef | Software |
| DEC-023 | SLAM Deferred | Software |
| DEC-024 | Accuracy Target | Accuracy |
| DEC-025 | Validation Method | Accuracy |
| DEC-026 | Camera as Reference | Camera |
| DEC-027 | Triggered Capture | Camera |
| DEC-028 | TOML Config | Config |
| DEC-029 | GPIO Library (rpi-lgpio) | Upstream Compat |
| DEC-030 | Dual-Mode (personal / arm_group) | Base-Station Integration |
| DEC-031 | NTRIP-Primary + LoRa Fallback | Base-Station Integration |
| DEC-032 | NTRIP Client Location (Pi or ESP32) | Base-Station Integration |
| DEC-033 | Triple-Channel Telemetry | Base-Station Integration |
| DEC-034 | Coords: log SI/WGS84, convert at export | Base-Station Integration |
| DEC-035 | Deep Alignment with arm-drone-lidar-workflow | Deep-Alignment Overhaul |
