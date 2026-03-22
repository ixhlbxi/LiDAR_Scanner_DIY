# Roadmap & Next Steps

**Document Status:** Frozen (v0.9.2)  
**Last Updated:** 2026-02-22

---

## 1. Version 1.0 Definition

### 1.1 Minimum Viable Feature Set

v1.0 is complete when the following capabilities are demonstrated:

| Feature | Criteria |
|---------|----------|
| **RTK-tagged LiDAR scans** | Point cloud with cm-level GNSS position per scan |
| **Local data logging** | JSONL files with all sensor data + images |
| **IMU orientation** | Madgwick fusion providing stable orientation |
| **LoRa RTCM delivery** | Corrections flowing base → rover reliably |
| **LoRa telemetry** | Status visible on T-Deck monitoring console |
| **Post-processed point cloud** | PLY output, georeferenced via scripts |
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

## 2. Development Phases

### Phase 1: Hardware Integration (Current → +2-4 weeks)

**Objective:** All hardware connected and communicating.

**Tasks:**
- [ ] Order ZED-F9P modules (×2) and antennas (×2)
- [ ] Order/source 3.3V regulator, power banks, 12V battery
- [ ] Create wiring harness (UART, I2C, GPIO, power)
- [ ] Verify each sensor individually:
  - [ ] LD19 LiDAR scan acquisition
  - [ ] MPU-9250 IMU data over I2C
  - [ ] ZED-F9P NMEA output
  - [ ] ESP32 LoRa packet transmission
  - [ ] HQ Camera capture
  - [ ] Stepper motor rotation
- [ ] Integrate onto temporary test bench (not final enclosure)

**Deliverables:**
- [ ] `WIRING_AND_PINS.md` — Complete pinout and wiring diagram
- [ ] Bench test photos/video
- [ ] Individual sensor test scripts

### Phase 2: Base Station Setup (+2-4 weeks)

**Objective:** RTK base station operational and broadcasting corrections.

**Tasks:**
- [ ] Configure ZED-F9P as base station (survey-in mode)
- [ ] Verify RTCM3 message generation
- [ ] Flash ESP32 with RTCM transmitter firmware
- [ ] Test LoRa transmission range and reliability
- [ ] Mount on tripod/mast for field deployment

**Deliverables:**
- [ ] Base station assembly documentation
- [ ] RTCM transmission verification log
- [ ] Range test results

### Phase 3: Rover Software Core (+4-6 weeks)

**Objective:** Core acquisition and logging software operational.

**Tasks:**
- [ ] Implement Python modules:
  - [ ] `config.py` — TOML parsing
  - [ ] `lidar.py` — LD19 acquisition
  - [ ] `imu.py` — MPU-9250 + Madgwick
  - [ ] `gnss.py` — ZED-F9P parsing
  - [ ] `stepper.py` — Motor control (use `rpi-lgpio` per D-029)
  - [ ] `camera.py` — Image capture
  - [ ] `logger.py` — JSONL output
  - [ ] `main.py` — Orchestration
- [ ] Flash ESP32 with RTCM receiver + telemetry firmware
- [ ] Verify RTCM flow: Base → LoRa → ESP32 → F9P
- [ ] Verify RTK fix achieved on rover
- [ ] Run integrated acquisition test

**Deliverables:**
- [ ] Working rover software (v0.1)
- [ ] Sample scan dataset
- [ ] RTK fix verification log

### Phase 4: Monitoring Console (+1-2 weeks)

**Objective:** T-Deck displaying rover status.

**Tasks:**
- [ ] Implement T-Deck firmware:
  - [ ] LoRa packet reception
  - [ ] STATUS packet parsing
  - [ ] LINK packet parsing
  - [ ] Display rendering
- [ ] Verify telemetry flow: Rover → LoRa → T-Deck
- [ ] Field test monitoring range

**Deliverables:**
- [ ] T-Deck firmware (v0.1)
- [ ] Monitoring UI documentation

### Phase 5: Post-Processing Pipeline (+2-3 weeks)

**Objective:** Convert raw logs to georeferenced point cloud.

**Tasks:**
- [ ] Implement georeferencing script:
  - [ ] Parse JSONL logs
  - [ ] Apply IMU orientation to points
  - [ ] Transform to GNSS position
  - [ ] Output PLY format
- [ ] Test with PDAL for LAS/LAZ conversion
- [ ] Visualize in CloudCompare
- [ ] Validate accuracy against known features

**Deliverables:**
- [ ] `georef.py` — Georeferencing script
- [ ] Sample georeferenced point cloud
- [ ] Accuracy validation report

### Phase 6: Field Testing & Validation (+2-4 weeks)

**Objective:** Validate system in real-world conditions.

**Tasks:**
- [ ] Outdoor RTK scanning tests
- [ ] Indoor relative mapping tests
- [ ] Runtime/battery tests
- [ ] Range/reliability tests
- [ ] Repeatability tests
- [ ] Accuracy validation (control points if available)
- [ ] Document issues and iterate

**Deliverables:**
- [ ] Field test report
- [ ] Issue log with resolutions
- [ ] v1.0 release candidate

### Phase 7: v1.0 Release

**Objective:** Freeze v1.0 with documentation.

**Tasks:**
- [ ] Final code cleanup
- [ ] Update all documentation
- [ ] Create release package
- [ ] Archive known issues for v1.1

**Deliverables:**
- [ ] v1.0 release tag
- [ ] Complete documentation set
- [ ] v1.1 backlog

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
| v0.9.2 | 2026-02-22 | Audit update: fix upstream repo URL, add D-029 (GPIO library), note upstream changes |
| v0.9.1 | 2025-12-26 | Architecture freeze; complete gap analysis |
| v0.9.0 | 2025-12-26 | Initial project documentation |
