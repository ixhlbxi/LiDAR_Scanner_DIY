# Design Decisions Log

**Document Status:** Frozen (v0.9.2)  
**Last Updated:** 2026-02-22

This document records all significant architectural and engineering decisions, including rationale, alternatives considered, and implications.

---

## Decision Format

Each decision follows this structure:
- **Decision:** What was decided
- **Context:** Why a decision was needed
- **Rationale:** Why this option was chosen
- **Alternatives Considered:** What else was evaluated
- **Implications:** What this decision affects downstream
- **Status:** Decided / Provisional / Revisit

---

## 1. System-Level Decisions

### D-001: DIY Over Commercial Solution

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

**Status:** Decided

---

### D-002: PiLiDAR as Foundation

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

**Status:** Decided

---

### D-003: Raspberry Pi Over MCU-Only

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

**Status:** Decided

---

## 2. GNSS / RTK Decisions

### D-004: ZED-F9P for RTK

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

**Status:** Decided

---

### D-005: RTK via LoRa (Not Cellular)

**Decision:** Deliver RTCM corrections via LoRa radio link, not cellular/internet.

**Context:** Corrections must flow from base to rover with low latency.

**Rationale:**
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

**Status:** Decided

---

### D-006: RTCM Routing — ESP32 Direct to F9P

**Decision:** Route RTCM corrections directly from ESP32 (LoRa) to ZED-F9P via UART, bypassing the Raspberry Pi.

**Context:** Original plan had Pi in the RTCM path for logging/observability. This adds latency and creates Linux dependency.

**Rationale:**
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

**Status:** Decided (revision from v0.9)

---

### D-007: RTCM Constellation Profiles

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

**Status:** Decided

---

## 3. Communications Decisions

### D-008: LoRa Parameters

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

**Status:** Decided

---

### D-009: LoRa Packet Loss Handling

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

**Status:** Decided

---

### D-010: T-Deck Receive-Only (v1.0)

**Decision:** Monitoring terminal is receive-only in v1.0; no remote commands.

**Context:** Bidirectional command/control adds complexity and security considerations.

**Rationale:**
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

**Status:** Decided

---

## 4. Sensor & Fusion Decisions

### D-011: MPU-9250 as Primary IMU

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

**Status:** Decided

---

### D-012: Madgwick Filter for Sensor Fusion

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

**Status:** Decided

---

### D-013: Magnetometer Disabled During Motor Operation

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

**Status:** Decided

---

### D-014: IMU-LiDAR Timestamp Correlation via Slerp

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

**Status:** Decided

---

## 5. Mechanical Decisions

### D-015: Direct Drive Rotation (No Slip Ring)

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

**Status:** Decided

---

### D-016: Open-Loop Stepper Indexing

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

**Status:** Decided

---

### D-017: 1/16 Microstepping

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

**Status:** Decided

---

## 6. Power Decisions

### D-018: Split Power Domains

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

**Status:** Decided

---

### D-019: Dedicated 3.3V Regulator

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

**Status:** Decided

---

## 7. Software Decisions

### D-020: Python on Raspberry Pi OS Lite

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

**Status:** Decided

---

### D-021: JSONL for Logging

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

**Status:** Decided

---

### D-022: Post-Processed Georeferencing

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

**Status:** Decided

---

### D-023: SLAM Deferred to v1.1+

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

**Status:** Decided

---

## 8. Accuracy Decisions

### D-024: v1.0 Point Cloud Accuracy Target

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

**Status:** Decided

---

### D-025: Validation via Repeatability + Control Points

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

**Status:** Decided

---

## 9. Camera Decisions

### D-026: Camera as Visual Reference (Not Photogrammetry)

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

**Status:** Decided

---

### D-027: Camera Triggered Per Rotation Step

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

**Status:** Decided

---

## 10. Configuration Decisions

### D-028: TOML Configuration File

**Decision:** Use single TOML configuration file for all runtime parameters.

**Context:** Many parameters should be adjustable without code changes.

**Rationale:**
- TOML is readable and typed
- Less indentation-sensitive than YAML
- Better than INI for nested config
- Single file is simpler than per-subsystem files

**Alternatives Considered:**
- YAML (more common but whitespace-sensitive)
- JSON (no comments, verbose)
- INI (limited structure)
- Per-subsystem files (more files to manage)

**Implications:**
- All tunable params in one place
- Must define config schema
- Can split to per-subsystem in future if needed

**Status:** Decided

---

## 11. Upstream Compatibility Decisions

### D-029: GPIO Library — rpi-lgpio over RPi.GPIO

**Decision:** Use `rpi-lgpio` (or `gpiozero`) for GPIO control on Raspberry Pi, NOT the legacy `RPi.GPIO` library.

**Context:** Raspberry Pi OS Bookworm (the current 64-bit release) deprecated the sysfs GPIO interface. The upstream PiLiDAR project migrated from `RPi.GPIO` to `rpi-lgpio` to address this. Since our project targets Pi OS Lite 64-bit (D-020), this affects stepper motor control and any future GPIO-based interfaces.

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

**Status:** Decided

---

## Decision Index

| ID | Topic | Section |
|----|-------|---------|
| D-001 | DIY vs Commercial | System |
| D-002 | PiLiDAR Foundation | System |
| D-003 | Pi vs MCU | System |
| D-004 | ZED-F9P Selection | GNSS |
| D-005 | RTK via LoRa | GNSS |
| D-006 | RTCM Routing Direct | GNSS |
| D-007 | RTCM Profiles | GNSS |
| D-008 | LoRa Parameters | Comms |
| D-009 | Packet Loss Handling | Comms |
| D-010 | T-Deck Receive-Only | Comms |
| D-011 | MPU-9250 Primary | Sensor |
| D-012 | Madgwick Filter | Sensor |
| D-013 | Mag Disabled w/ Motor | Sensor |
| D-014 | Timestamp Slerp | Sensor |
| D-015 | Direct Drive | Mechanical |
| D-016 | Open-Loop Indexing | Mechanical |
| D-017 | 1/16 Microstepping | Mechanical |
| D-018 | Split Power Domains | Power |
| D-019 | Dedicated 3.3V Reg | Power |
| D-020 | Python + Pi OS Lite | Software |
| D-021 | JSONL Logging | Software |
| D-022 | Post-Processed Georef | Software |
| D-023 | SLAM Deferred | Software |
| D-024 | Accuracy Target | Accuracy |
| D-025 | Validation Method | Accuracy |
| D-026 | Camera as Reference | Camera |
| D-027 | Triggered Capture | Camera |
| D-028 | TOML Config | Config |
| D-029 | GPIO Library (rpi-lgpio) | Upstream Compat |
