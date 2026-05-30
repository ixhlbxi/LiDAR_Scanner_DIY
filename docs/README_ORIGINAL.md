# RTK-Enabled LiDAR Scanner / Camera Rover

**Project Codename:** PiLiDAR-RTK Rover  
**Author:** Brian  
**Status:** Active Development — Architecture Frozen (v0.9.2)  
**Last Updated:** 2026-02-22

---

## Quick Context Rehydration

> This project is a modular, RTK-enabled LiDAR + camera rover based on the open-source PiLiDAR project, extended with ZED-F9P RTK GNSS, LoRa RTCM corrections, IMU-assisted orientation, and a handheld T-Deck monitoring console. The system supports outdoor centimeter-level mapping and indoor GNSS-denied relative mapping, prioritizing field reliability, redundancy, and modular growth.

---

## What This Project Does

A **portable, field-deployable 3D scanning platform** combining:

- **360° LiDAR scanning** — LD19 sensor on rotating mast, stacked 2D slices → 3D point cloud
- **Visual capture** — Raspberry Pi HQ Camera with fisheye lens for context imagery
- **Centimeter-level positioning** — RTK GNSS (ZED-F9P) with LoRa-delivered corrections
- **Orientation tracking** — MPU-9250 IMU with Madgwick sensor fusion
- **Offline/indoor fallback** — IMU-stabilized relative mapping when GNSS unavailable
- **Long-range telemetry** — LoRa link for RTCM corrections and status monitoring
- **Field monitoring** — LILYGO T-Deck handheld console for real-time status

---

## Design Philosophy

| Principle | Meaning |
|-----------|---------|
| **Modular** | Subsystems can be swapped or upgraded independently |
| **Redundant** | GNSS + IMU + geometry constraints; no single point of failure |
| **Field-repairable** | No fragile laptop-only dependencies |
| **Survey-adjacent** | Accuracy-focused but DIY; not survey-certified |

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         ROVER UNIT                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │  LD19   │  │   HQ    │  │ MPU-9250│  │ ZED-F9P │            │
│  │ LiDAR   │  │ Camera  │  │   IMU   │  │  GNSS   │            │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘            │
│       │            │            │            │                  │
│       └────────────┴─────┬──────┴────────────┘                  │
│                          │                                      │
│                   ┌──────▼──────┐      ┌──────────┐            │
│                   │ Raspberry   │      │  ESP32   │◄───LoRa────┐
│                   │   Pi 4      │      │  LoRa    │            │
│                   └──────┬──────┘      └──────────┘            │
│                          │                    ▲                 │
│                   ┌──────▼──────┐              │ RTCM           │
│                   │   NEMA17    │              │                │
│                   │  + A4988    │              │                │
│                   └─────────────┘              │                │
└───────────────────────────────────────────────┼─────────────────┘
                                                │
┌───────────────────────────────────────────────┼─────────────────┐
│                    RTK BASE STATION           │                 │
│  ┌─────────┐      ┌──────────┐      ┌─────────▼───┐            │
│  │ ZED-F9P │──────│   Pi /   │──────│   ESP32     │────LoRa────┘
│  │  Base   │      │  MCU     │      │   LoRa      │
│  └─────────┘      └──────────┘      └─────────────┘
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   MONITORING TERMINAL                           │
│                    ┌─────────────┐                              │
│                    │  LILYGO     │◄───────LoRa (telemetry)      │
│                    │  T-Deck     │                              │
│                    └─────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Documentation Index

| Document | Contents |
|----------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, subsystems, data flows, comms topology |
| [HARDWARE.md](HARDWARE.md) | Inventory (owned + planned), specs, part selection rationale |
| [DECISIONS.md](DECISIONS.md) | All architectural/engineering decisions with rationale |
| [SPECIFICATIONS.md](SPECIFICATIONS.md) | Packet formats, config schema, firmware boundaries, data schema |
| [ROADMAP.md](ROADMAP.md) | v1.0 scope, milestones, TBDs, future versions |

---

## Project Lineage

This project **extends** the [PiLiDAR project](https://github.com/PiLiDAR/PiLiDAR) (Raspberry Pi + LD19 LiDAR for low-cost 3D scanning).

> **Note:** The PiLiDAR repo moved from `Finin-Quincey/PiLiDAR` to the `PiLiDAR` organization in 2025. Last upstream commit: April 24, 2025 (34 total commits, 1.8k stars). The project is lightly maintained with 4 open issues and 4 open PRs.

| Capability | PiLiDAR | This Project |
|------------|---------|--------------|
| Positioning | None / basic | RTK GNSS (cm-level) |
| Orientation | Basic | IMU + sensor fusion |
| Communications | Wired | LoRa telemetry |
| Monitoring | Local only | Handheld LoRa console |
| Use case | Static scans | Mobile rover + field ops |

---

## Current Status

### Completed
- ✅ Hardware acquisition (core components)
- ✅ Architecture planning and documentation
- ✅ RTK Base/Rover separation defined
- ✅ LoRa telemetry concept validated
- ✅ Indoor fallback strategy defined
- ✅ Gap analysis and specification freeze

### Next Steps
1. Finalize RTK module vendor and order parts
2. Create wiring diagram and pin assignments
3. Define data schema (JSONL format)
4. Begin physical integration
5. Write core Python modules

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| v0.9.2 | 2026-02-22 | Audit update; fix upstream repo URL, add GPIO library decision (DEC-029), note upstream STL27L support |
| v0.9.1 | 2025-12-26 | Architecture freeze; all major decisions documented |
| v0.9.0 | 2025-12-26 | Initial dev guide created |

---

## License

TBD — Personal/educational project currently.
