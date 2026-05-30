# Roadmap & Next Steps

**Document Status:** v0.10 — current (deep-alignment overhaul applied 2026-05-30)
**Last Updated:** 2026-05-30

---

## 1. Version 1.0 Definition

### 1.1 Minimum Viable Feature Set

v1.0 is complete when the following capabilities are demonstrated:

| Feature | Criteria |
|---------|----------|
| **RTK-tagged LiDAR scans** | Point cloud with cm-level GNSS position per scan |
| **Local data logging** | JSONL files with all sensor data + images |
| **IMU orientation** | Madgwick fusion providing stable orientation |
| **NTRIP RTCM delivery (DEC-031)** | Corrections flowing from arm-drone-lidar-workflow Base-Station's `ARM_BASE` caster to rover F9P |
| **LoRa RTCM fallback (DEC-031)** | Off-network operation supported via Base-Station Heltec → rover ESP32 → F9P UART2 |
| **Triple-channel telemetry (DEC-033)** | Status visible via `status.json` (Base-Station-compatible), HTTP, and LoRa STATUS/LINK |
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
| Camera texture mapping | Context imagery sufficient | v1.2+ |
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

### v0.10 Deep-Alignment Overhaul (in progress, 2026-05-30)

Single coordinated pass to make this rover feel like a sibling of
`arm-drone-lidar-workflow` rather than a tangential project, and to finish the
unimplemented orchestrator + watchdog that were stubs after the original
2026-05-23 v0.10 commit. Five stages, each independently committable:

| Stage | Scope | Status |
|---|---|---|
| **A** | Operational completion — `main.py` orchestrator + `watchdog.py` heartbeat, with `tests/test_main.py` and `tests/test_watchdog.py` | ✅ shipped (`8bede00`) |
| **B** | Convention mirroring — `STATUS_SCHEMA_VERSION` constant, `ZONE_EPSG` dict, GGA cross-ref, `_io.atomic_write_json` extraction | ✅ shipped (`5a575f4`) |
| **C** | Deployment infrastructure — `deploy/systemd/`, `deploy/udev/`, `deploy/install.sh`, sd_notify, `/etc/rover/secret` convention | ✅ shipped (`f2792da`) |
| **D** | Doc refresh — DECISIONS.md rename + restructure, README/CLAUDE.md positioning, stale-doc cleanup, CROSS_REPO_BACKLOG.md | 🔄 in flight |
| **E** | LoRa frame v2 callout in BASE_STATION_INTEGRATION.md flagging the sibling Heltec firmware is still v1 | ⏳ pending |

See [DEC-035](DECISIONS.md#dec-035-deep-alignment-with-arm-drone-lidar-workflow-v010-overhaul)
for the decision record.

### v1.0 Field Validation (next)

**Objective:** Demonstrate every row in §1.1 above on real hardware in a real
scan session, against the live Base-Station `ARM_BASE` caster.

| Block | Tasks |
|---|---|
| Hardware acquisition | Order 2× ZED-F9P + antennas + 3.3V regulator + batteries (see [HARDWARE.md §1.1](HARDWARE.md#11-acquisition-status)) |
| Wiring + bench rig | Assemble per HARDWARE.md pinout; verify each sensor with `tests/hardware/test_*` diagnostic scripts |
| Integrated bench scan | `python -m rover.main` end-to-end with all sensors + NTRIP + Base-Station status.json reachable |
| Field shakedown | Outdoor RTK FIX achieved within ~60 s; runtime ≥4 h; LoRa fallback verified |
| Accuracy validation | Repeatability (<5 cm) and control-point comparison if accessible |
| Release | Tag `v1.0`; close out v1.1 backlog |

Cross-repo dependency: full LoRa-fallback validation needs sibling-side Heltec
v2 firmware + base LoRa-RTCM transmitter (tracked in
[CROSS_REPO_BACKLOG.md](CROSS_REPO_BACKLOG.md)). Until that lands, NTRIP-only
field validation proceeds independently.

### v1.1 Calibration (after v1.0)

**Objective:** Lift accuracy from ±5–10 cm to ±2–3 cm by adding extrinsic
calibration of the LiDAR → IMU → GNSS transform chain.

- Define calibration procedure (T_lidar_imu, T_body_gnss).
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

| Item | Options | Decision Point |
|------|---------|----------------|
| Exact step interval | 1° vs 1.5° vs 2° | After scan density evaluation |
| IMU sample rate | 200 Hz vs 400 Hz | After fusion performance testing |
| Camera capture cadence | Every step vs every 2nd step | After storage evaluation |
| Log rotation strategy | Size-based vs time-based | During logging implementation |

### 3.3 Mechanical TBDs

| Item | Options | Decision Point |
|------|---------|----------------|
| Enclosure design | 3D printed vs project box | After bench integration |
| Mounting bracket design | Custom vs adapted | After sensor layout finalized |
| Cable routing | Internal vs external | After enclosure decision |

---

## 4. Risk Register

### 4.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| LoRa bandwidth insufficient for RTCM | Medium | High | Test early; use low-BW profile |
| IMU drift exceeds tolerance | Medium | Medium | Limit indoor scan duration |
| Stepper vibration affects IMU | Medium | Medium | Damping mounts; disable mag during rotation |
| F9P convergence slow | Low | Medium | Ensure good antenna placement; patience |
| Pi thermal throttling | Low | Medium | Ensure ventilation; monitor temps |
| SD card corruption | Low | High | Use quality card; frequent flush; USB SSD option |

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
- Remote command/control via T-Deck
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

## 6. Documentation Backlog

Documents to create during implementation:

| Document | Phase | Priority |
|----------|-------|----------|
| `WIRING_AND_PINS.md` | Phase 1 | High |
| `SETUP_GUIDE.md` | Phase 3 | High |
| `OPERATION_MANUAL.md` | Phase 6 | High |
| `TROUBLESHOOTING.md` | Phase 6 | Medium |
| `CALIBRATION.md` | v1.1 | Medium |
| `API_REFERENCE.md` | v1.1 | Low |

---

## 7. Resource Requirements

### 7.1 Remaining Purchases

| Item | Est. Cost | Priority |
|------|-----------|----------|
| ZED-F9P × 2 | $400-500 | Critical |
| Dual-band antennas × 2 | $100-200 | Critical |
| 3.3V regulator | $10-20 | High |
| USB-C PD power bank | $50-80 | High |
| 12V battery + charger | $50-80 | High |
| Cables, connectors, misc | $50-100 | High |
| Enclosure materials | $30-50 | Medium |
| **Total** | **$700-1000** | |

### 7.2 Time Estimate

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 1: Hardware Integration | 2-4 weeks | 2-4 weeks |
| Phase 2: Base Station | 2-4 weeks | 4-8 weeks |
| Phase 3: Rover Software | 4-6 weeks | 8-14 weeks |
| Phase 4: Monitoring Console | 1-2 weeks | 9-16 weeks |
| Phase 5: Post-Processing | 2-3 weeks | 11-19 weeks |
| Phase 6: Field Testing | 2-4 weeks | 13-23 weeks |
| Phase 7: Release | 1 week | 14-24 weeks |

**Estimated v1.0 completion:** 3-6 months (depending on pace and issues)

---

## 8. Immediate Next Actions

**This Week:**
1. [ ] Order ZED-F9P modules and antennas
2. [ ] Order 3.3V regulator and power components
3. [ ] Create initial wiring diagram draft
4. [ ] Set up Git repository for code

**Next Week:**
1. [ ] Begin hardware integration (LD19 first)
2. [ ] Test IMU I2C communication
3. [ ] Verify stepper motor operation
4. [ ] Start `config.py` module

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| v0.9.2 | 2026-02-22 | Audit update: fix upstream repo URL, add DEC-029 (GPIO library), note upstream changes |
| v0.9.1 | 2025-12-26 | Architecture freeze; complete gap analysis |
| v0.9.0 | 2025-12-26 | Initial project documentation |
