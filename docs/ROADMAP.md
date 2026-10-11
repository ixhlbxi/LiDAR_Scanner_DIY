# Roadmap & Next Steps

**Document Status:** v0.11 — audit remediation complete (2026-09-23)
**Last Updated:** 2026-10-11 (merged the 2026-09-30 DEC-036 target placement tests and the 2026-10-02 DEC-037–DEC-045 redesign items)

---

## 1. Version 1.0 Definition

### 1.1 Minimum Viable Feature Set

v1.0 is complete when the following capabilities are demonstrated:

| Feature | Criteria |
|---------|----------|
| **RTK-tagged LiDAR scans** | Point cloud with cm-level GNSS position per scan |
| **Local data logging** | JSONL files with all sensor data + images |
| **IMU orientation** | Madgwick fusion providing stable orientation |
| **NTRIP RTCM delivery (DEC-031)** | Corrections flowing from arm-drone-lidar-workflow Base-Station's `ARM_BASE` caster to rover F9P — the sole RTK path (DEC-031 amended 2026-09-23) |
| **LoRa status telemetry (DEC-031 amended)** | STATUS frames only, every 10 s; RTCM never travels over LoRa |
| **Triple-channel telemetry (DEC-033)** | Status visible via `status.json` (Base-Station-compatible), HTTP, and LoRa STATUS (LINK is defined but never sent) |
| **Post-processed point cloud** | PLY output (always) + LAS in session CRS for ARM Group profile (DEC-034) |
| **ARM Group profile output** | LAS in NAD83(2011) State Plane / US Survey Foot, drops into project `01_Raw/LiDAR/Rover/` |
| **4-hour runtime** | Full scan session without battery swap |
| **Outdoor accuracy** | ±5-10 cm point cloud (validated) |
| **Indoor relative mapping** | Orientation-stabilized local point clouds |

### 1.2 Explicitly Out of Scope for v1.0

| Feature | Rationale | Target Version |
|---------|-----------|----------------|
| Real-time SLAM | Significant complexity | v1.1+ |
| Real-time georeferencing | Post-processing sufficient | v1.1+ |
| Camera colorization + target resection (DEC-036) | Needs camera and camera-to-LiDAR calibration | v1.1 |
| Texture-mapped meshes / photogrammetry | Colorized points sufficient | v2.0 |
| Remote command/control | Receive-only monitoring first | v1.1 |
| OTA firmware updates | Flash-and-forget acceptable | v1.1 |
| Slip ring continuous rotation | Cable loop sufficient | v1.2+ |
| Closed-loop motor control | Open-loop adequate | v1.1 |
| Formal IP rating | Splash-resistant sufficient | v1.2+ |
| Extrinsic calibration procedure | Accept wider accuracy | v1.1 |

### 1.3 Success Criteria

| Metric | Target | Validation Method |
|--------|--------|-------------------|
| RTK fix rate (open sky) | >90% of scan duration | Log analysis |
| Point cloud accuracy | ±5-10 cm | Control point comparison |
| Scan repeatability | <5 cm deviation | Multi-scan overlay |
| Runtime | ≥4 hours | Timed field test |
| LoRa range | ≥1 km LOS | Field test |
| Data integrity | No corrupted logs | File validation |

---

## 2. Phases

The v0.9.2 Phase 1–7 plan (sequential "hardware → base → rover → ..." waterfall)
has been replaced. The Base-Station now exists as a separate, production-grade
project (`arm-drone-lidar-workflow`); this rover plugs into it. Current phases
reflect that integration model.

### v0.10 Deep-Alignment Overhaul (complete, 2026-05-30)

Single coordinated pass to make this rover feel like a sibling of
`arm-drone-lidar-workflow` rather than a tangential project, and to finish the
unimplemented orchestrator + watchdog that were stubs after the original
2026-05-23 v0.10 commit. Five stages, each independently committable:

| Stage | Scope | Status |
|---|---|---|
| **A** | Operational completion — `main.py` orchestrator + `watchdog.py` heartbeat, with `tests/test_main.py` and `tests/test_watchdog.py` | ✅ shipped (`8bede00`) |
| **B** | Convention mirroring — `STATUS_SCHEMA_VERSION` constant, `ZONE_EPSG` dict, GGA cross-ref, `_io.atomic_write_json` extraction | ✅ shipped (`5a575f4`) |
| **C** | Deployment infrastructure — `deploy/systemd/`, `deploy/udev/`, `deploy/install.sh`, sd_notify, `/etc/rover/secret` convention | ✅ shipped (`f2792da`) |
| **D** | Doc refresh — DECISIONS.md rename + restructure, README/CLAUDE.md positioning, stale-doc cleanup, CROSS_REPO_BACKLOG.md | ✅ shipped (`2c133ca`) |
| **E** | LoRa frame v2 callout in BASE_STATION_INTEGRATION.md flagging the sibling Heltec firmware is still v1 | ✅ shipped (`6ab5a2a`) |

See [DEC-035](DECISIONS.md#dec-035-deep-alignment-with-arm-drone-lidar-workflow-v010-overhaul)
for the decision record.

### v0.11 — Audit Remediation (2026-09-22/23)

A 2026-09-22 super-audit (`docs/AUDIT_super_20260922_1810.md`) found 86
findings across code and docs. Six stages closed them, each merged `--no-ff`:

| Stage | Scope | Merge |
|---|---|---|
| **1** | Hygiene and identity (T1-036, T1-054, T1-055, T1-056, T3-003, D-008) | `d0cf54b` |
| **2** | First-boot blockers (T1-001..003, T1-005, T1-006, T1-011, T1-027, T1-029, T1-031, T1-032, T2-001..004, D-016) | `aac5b84` |
| **3** | Data pipeline (T1-007..010, T1-012..017, T1-039, T1-043, T1-044, T1-050, T1-052; mag_offset half of T1-041) | `7ef5b1e` |
| **4** | Comms and config | `167f4a2` |
| **5** | Scan geometry and field readiness | `dae5776` |
| **6** | Docs refresh — this document, CLAUDE.md, DECISIONS.md, ARCHITECTURE.md, SPECIFICATIONS.md, BASE_STATION_INTEGRATION.md, HARDWARE.md, SMOKE_CHECKLIST.md, and the `tests/test_docs.py` guard | stage 6 merge |

DEC-015 and DEC-031 carry the amendments this campaign closed. `src/rover/__init__.py`
moves to `0.11.0` at the stage 6 merge.

### v1.0 Field Validation (next)

**Objective:** Demonstrate every row in §1.1 above on real hardware in a real
scan session, against the live Base-Station `ARM_BASE` caster.

| Block | Tasks |
|---|---|
| Hardware acquisition | Order 1× ZED-F9P + ANN-MB-00 antenna + 3.3V regulator + batteries (see [HARDWARE.md §1.1](HARDWARE.md#11-acquisition-status)) |
| Wiring + bench rig | Assemble per HARDWARE.md pinout; verify each sensor with `tests/hardware/test_*` diagnostic scripts |
| Camera bench tests (DEC-036 gates) | Tests 1–5 and 9 from the table in `docs/research/elp-stereo/REPORT.md`: `lsusb -v` transfer type, `v4l2-ctl` formats and controls, dual-stream, LD19/F9P serial gaps while a camera streams, full-res YUY2 timing, power. Results set the capture design |
| Camera capture backend (DEC-036) | Plan first, then replace Picamera2 in `camera.py` with V4L2. Two cameras, one streams at a time at rest, locked controls, raw MJPEG, `[camera]` for two devices, udev by port path, `tests/hardware/test_camera.py` rewritten |
| Integrated bench scan | `python -m rover.main` end-to-end with all sensors + NTRIP + Base-Station status.json reachable |
| Field shakedown | Outdoor RTK FIX achieved within ~60 s; runtime ≥4 h; NTRIP connectivity to `ARM_BASE` verified in the field |
| Accuracy validation | Repeatability (<5 cm) and control-point comparison if accessible |
| Release | Tag `v1.0`; close out v1.1 backlog |

Cross-repo dependency: full triple-channel telemetry validation needs
sibling-side Heltec v2 firmware to recognize the rover's STATUS frames
(tracked in [CROSS_REPO_BACKLOG.md](CROSS_REPO_BACKLOG.md), CR-001/CR-003).
RTCM never travels over LoRa (DEC-031 amended 2026-09-23) — NTRIP against the
live `ARM_BASE` caster is the sole RTK path, and field validation proceeds on
it independently of that sibling work.

### v1.1 Calibration (after v1.0)

**Objective:** Lift accuracy from ±5–10 cm to ±2–3 cm by adding extrinsic
calibration of the LiDAR → IMU → GNSS transform chain.

- Define calibration procedure (T_lidar_imu, T_body_gnss).
- Camera calibration (DEC-036): ChArUco intrinsics per ELP (rational vs fisheye model),
  stereo extrinsics, camera-to-LiDAR extrinsics, and a repeatability test
  (power cycle, warm-up, transport).
- LD19 target-plate test: the Sky High target at 3, 6, 9 and 12 m, for real range
  and plane-fit σ.
- Target placement tests 11–13 (DEC-036 amendment 2026-09-30,
  `docs/research/elp-stereo/notes/target_placement_geometry.md`): flat-target
  detection floor at 3–9 m, mast bearing repeatability per microstep, and
  ray-to-ground-plane range at 5–9 m.
- Open-sky resection proof (test 14): resect a station from 3 targets, flat and
  rod-mounted, where RTK has a solid fix, and compare. Include the recommended
  layout (4–6 m, ~120° apart, scanner inside the triangle), a near-danger-circle
  layout and a two-targets-per-frame layout. This validates target resection
  before relying on it under canopy.
- Target field procedure decision, from tests 11–14.
- `scripts/georef.py`: target detection, resection (range+bearing ≤5 m on flat
  targets and ≤10 m on rods, azimuth-only beyond), per-camera colorization with
  occlusion handling.
- LiDAR upgrade decision (S2/S3 class) after the plate test and a midday sun test.
- Closed-loop motor control via encoder or limit switch.
- ICP-based scan-to-scan registration in post-processing for indoor scans.
- Configuration validation improvements based on v1.0 field experience.

See [DEC-024](DECISIONS.md#dec-024-v10-point-cloud-accuracy-target) for the
v1.0 / v1.1 accuracy split.

---

## 3. Open TBDs (To Be Determined)

These items require decisions during implementation:

### 3.1 Hardware TBDs

| Item | Options | Decision Point |
|------|---------|----------------|
| ZED-F9P vendor | SparkFun vs ArduSimple vs Beitian | Before ordering |
| GNSS antenna model | ArduSimple vs Tallysman vs other | Before ordering |
| Camera resolution | 1920×1080 vs 1640×1232 | After performance testing |
| 12V battery type | LiPo 3S vs DC pack | Before ordering |
| USB-serial adapter count | 2 vs 3 | After port mapping |

### 3.2 Software TBDs

Two items formerly listed here are decided and closed: the step interval is
`1.575°` (`config/default.toml`), and log rotation is size-based
(`rotate_size_mb`, `src/rover/config.py`).

| Item | Options | Decision Point |
|------|---------|----------------|
| IMU sample rate | 200 Hz vs 400 Hz | After fusion performance testing |
| Camera capture cadence | Every step vs every 2nd step | After storage evaluation |

### 3.3 Mechanical TBDs

| Item | Options | Decision Point |
|------|---------|----------------|
| Enclosure design | 3D printed vs project box | After bench integration |
| Mounting bracket design | Custom vs adapted | After sensor layout finalized |
| Cable routing | Internal vs external | After enclosure decision |
| LD19 mount: offset from axis, plane radial vs tangential (DEC-037) | Radial (no zenith blind zone) vs tangential (blind cylinder usable for an axis mast) | Case redesign |
| HoI laser placement (DEC-044) | Arm length to clear the tribrach and tripod head | Case redesign |

### 3.4 Static-station redesign TBDs (DEC-037–DEC-045)

| Item | Options | Decision Point |
|------|---------|----------------|
| Camera resection target (DEC-038 conflict with DEC-036) | Flat checkers vs PVC cylinders vs both | After DEC-036 tests 11–14 are re-scoped to include cylinders |
| Stereo role at 75 cm (DEC-042) | Cross-check only vs secondary range | After stereo calibration measures real error |
| Exact geared NEMA17 part (DEC-040) | ~27:1 planetary models | Before ordering |
| HoI sensor (DEC-044) | Owned Bosch (if hackable) vs SEN0366 vs JRT M88B | After checking for a Bosch "C" model |
| LiDAR upgrade (DEC-037) | Keep LD19 vs Unitree L2 vs Livox Mid-360 vs used Mid-40 | After a field test shows the LD19's range limit in practice |
| Dual-antenna heading (DEC-039) | Not needed vs UM982 | After field use of target matching |

---

## 4. Risk Register

### 4.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| IMU drift exceeds tolerance | Medium | Medium | Limit indoor scan duration |
| Stepper vibration affects IMU | Medium | Medium | Damping mounts; disable mag during rotation |
| F9P convergence slow | Low | Medium | Ensure good antenna placement; patience |
| Pi thermal throttling | Low | Medium | Ensure ventilation; monitor temps |
| SD card corruption | Low | High | Use quality card; frequent flush; USB SSD option |

*(The RTCM-over-a-radio-link bandwidth risk that used to sit here is removed:
DEC-031 was amended 2026-09-23 to retire that path outright, so there is no
longer a bandwidth budget to test — NTRIP is the only RTK path.)*

### 4.2 Schedule Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Parts shipping delays | Medium | Medium | Order early; have backup vendors |
| Integration issues | High | Medium | Test incrementally; budget debug time |
| Scope creep | Medium | High | Strict v1.0 boundary; defer to v1.1 |

### 4.3 Operational Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Field conditions damage hardware | Medium | High | Splash resistance; rugged handling |
| Battery life insufficient | Low | Medium | Test early; carry spares |
| User error during operation | Medium | Low | Clear procedures; status feedback |

---

## 5. Future Versions

### 5.1 Version 1.1 — Refinement

**Target:** 2-3 months after v1.0

**Features:**
- Extrinsic calibration procedure → ±2-3 cm accuracy
- Closed-loop motor control (encoder or limit switch)
- Remote monitoring via the Base-Station's T-Deck (owned by the sibling
  `arm-drone-lidar-workflow` repo, DEC-033) — this repo carries no T-Deck
  firmware of its own
- OTA firmware updates for ESP32
- ICP scan registration in post-processing
- Configuration validation and error reporting

### 5.2 Version 1.2 — Enhanced Capabilities

**Target:** 6+ months after v1.0

**Features:**
- Real-time SLAM (hector_slam or Cartographer integration)
- Real-time georeferencing
- Continuous rotation with slip ring
- Weather-sealed enclosure (IP65 target)
- Web-based monitoring interface

### 5.3 Version 2.0 — Platform Expansion

**Target:** 12+ months

**Features:**
- Camera photogrammetry integration
- Texture-mapped point clouds
- Multi-rover coordination
- Cloud data sync
- Mobile app for control

---

## 6. Remaining Work by Version

The Phase 1–7 documentation backlog this section used to carry belonged to
the waterfall plan §2 already says was replaced. Remaining work now maps to
the two horizons ahead of it:

**v1.0 — Field Validation**
- Run `deploy/SMOKE_CHECKLIST.md` on the Pi before every session.
- S3-R2: bench-check the LD19 mount orientation against LDRobot's angle
  convention before trusting the side-mount scan geometry.
- S5-R2: bench-measure rest-heading yaw noise; flag or downgrade capped
  `heading_settled` sweeps in `export.json` if noise exceeds tolerance.
- First field session against the live Base-Station `ARM_BASE` caster.

**v1.1 — Refinement**
- Extrinsic calibration procedure (`T_lidar_imu`, `T_body_gnss`).
- S5-R3: add a home switch or index mark — today a crash or power loss
  leaves the mast out of position and needs hand-homing before the next
  session.
- S5-F1: retire the ESP32-rover's `lora_rtcm_relay` firmware env and the
  retired RTCM_CHUNK (0x10) receive handler.
- NC-1: sibling Base-Station multi-client NTRIP caster, so the drone and
  this rover could one day share a base session (today: never at the same
  time, CR-005).

---

## 7. Resource Requirements

### 7.1 Remaining Purchases

| Item | Est. Cost | Priority |
|------|-----------|----------|
| ZED-F9P × 1 (SparkFun GPS-RTK-SMA) | $200-250 | Critical |
| ANN-MB-00 antenna × 1 | $50-100 | Critical |
| 3.3V regulator | $10-20 | High |
| USB-C PD power bank | $50-80 | High |
| 12V battery + charger | $50-80 | High |
| Cables, connectors, misc | $50-100 | High |
| Enclosure materials | $30-50 | Medium |
| **Total** | **$440-680** | |

### 7.2 Remaining Effort

The Phase 1–7 waterfall estimate this section used to carry predates the
Base-Station integration model in §2 and no longer describes real scope.
Remaining effort maps to the same two horizons as §6:

| Horizon | Remaining Work | Backlog / Doc |
|---|---|---|
| v1.0 — Field Validation | Run `deploy/SMOKE_CHECKLIST.md` on the Pi | — |
| v1.0 | Bench-check LD19 mount orientation | S3-R2 |
| v1.0 | Bench-measure rest-heading yaw noise | S5-R2 |
| v1.0 | First field session against the live `ARM_BASE` caster | — |
| v1.1 — Refinement | Extrinsic calibration procedure | — |
| v1.1 | Home switch / index mark for the mast | S5-R3 |
| v1.1 | Retire `lora_rtcm_relay` firmware mode | S5-F1 |
| v1.1 | Sibling multi-client NTRIP caster | NC-1 |

**Estimated v1.0 completion:** gated on the smoke checklist and one field
session, not a fixed duration.

---

## 8. Immediate Next Actions

1. [ ] Run `deploy/SMOKE_CHECKLIST.md` on the Pi.
2. [ ] Run the first field session against the live Base-Station `ARM_BASE`
   caster.

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| v0.11 | 2026-10-02 | Static-station redesign recorded as DEC-037–DEC-045; open items in §3.4 *(written on the cloud branch against the v0.10 text; merged 2026-10-11)* |
| v0.11 | 2026-09-23 | Post-audit remediation campaign (6 stages) closes 86 super-audit findings; DEC-015 and DEC-031 amended; `src/rover/__init__.py` bumped to 0.11.0 |
| v0.10 | 2026-05-30 | Deep-alignment overhaul with the `arm-drone-lidar-workflow` Base-Station (DEC-035); stages A–E |
| v0.9.2 | 2026-02-22 | Audit update: fix upstream repo URL, add DEC-029 (GPIO library), note upstream changes |
| v0.9.1 | 2025-12-26 | Architecture freeze; complete gap analysis |
| v0.9.0 | 2025-12-26 | Initial project documentation |
