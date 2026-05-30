# PiLiDAR-RTK Rover

RTK-enabled DIY LiDAR scanning platform built on Raspberry Pi 4B.

Combines an LD19 LiDAR, MPU-9250 IMU, ZED-F9P RTK GNSS, and Pi HQ Camera on a
rotating stepper mast to produce georeferenced 3D point clouds.

## How it fits the ARM Group workflow

The DIY Pi-LiDAR rover is the **LiDAR-scanning companion** to the SparkFun
RTK Facet — the GNSS-only field rover selected as the production "rover" in
[`ixhlbxi/arm-drone-lidar-workflow`](https://github.com/ixhlbxi/arm-drone-lidar-workflow).
Both rovers consume the same NTRIP corrections from the Base-Station's
`ARM_BASE` caster (`:2101`), so a single base setup feeds both. Different
jobs, same RTK source:

| Rover | Job |
|---|---|
| SparkFun RTK Facet | GCP occupations, single-point survey-grade fixes |
| **DIY Pi-LiDAR (this repo)** | Volumetric 3D LiDAR scans referenced to the same base |

The rover runs in two modes, selected per session:

- **`personal`** — DIY use, off-grid friendly. WGS84 / local ENU output. NTRIP optional.
- **`arm_group`** — Companion mode. Consumes RTK from the Base-Station's NTRIP
  caster, tags output with project code + mission, exports to NAD83(2011) State
  Plane in US Survey Foot for direct TBC import. See
  [docs/BASE_STATION_INTEGRATION.md](docs/BASE_STATION_INTEGRATION.md).

## Quick Start

```bash
# Install (on Pi, with hardware deps)
pip install -e ".[pi]"

# Install (dev, off-Pi)
pip install -e ".[dev]"

# Install (with post-processing CRS conversion)
pip install -e ".[post]"

# Run unit tests (anywhere, no hardware)
pytest tests/

# Hardware diagnostics (on Pi, with sensors attached)
python -m tests.hardware.test_lidar
python -m tests.hardware.test_imu
python -m tests.hardware.test_stepper
python -m tests.hardware.test_camera
```

## Project Status

**v0.10 — Base-Station integration overhaul.**
The v0.9.2 self-contained architecture has been lifted; the rover is being reframed
around the production Base-Station built in `arm-drone-lidar-workflow`. Implementation
proceeds in phases — see the approved plan and current state at
[docs/ROADMAP.md](docs/ROADMAP.md).

## Documentation

- [Base-Station Integration Contract](docs/BASE_STATION_INTEGRATION.md) — authoritative
  rover↔Base-Station interface (NTRIP, LoRa frame v2, status.json schema)
- [Architecture](docs/ARCHITECTURE.md) — system block diagrams, data flow, telemetry
- [Engineering Decisions](docs/DECISIONS.md) — DEC-001 to DEC-035 (DEC-030–DEC-034
  cover the v0.10 Base-Station integration; DEC-035 covers the deep-alignment overhaul)
- [Cross-Repo Backlog](docs/CROSS_REPO_BACKLOG.md) — sibling-side work this rover
  is waiting on (Heltec LoRa-frame-v2 upgrade, base-side LoRa-RTCM transmitter)
- [Hardware](docs/HARDWARE.md) — bill of materials, GPIO/serial map, power
- [Specifications](docs/SPECIFICATIONS.md) — sensors, accuracy targets, performance budgets
- [Roadmap](docs/ROADMAP.md) — phased delivery plan
