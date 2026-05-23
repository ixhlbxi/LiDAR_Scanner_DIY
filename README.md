# PiLiDAR-RTK Rover

RTK-enabled DIY LiDAR scanning platform built on Raspberry Pi 4B.

Combines an LD19 LiDAR, MPU-9250 IMU, ZED-F9P RTK GNSS, and Pi HQ Camera on a
rotating stepper mast to produce georeferenced 3D point clouds.

The rover runs in two modes, selected per session:

- **`personal`** — DIY use, off-grid friendly. WGS84 / local ENU output. NTRIP optional.
- **`arm_group`** — Companion to the ARM Group drone/LiDAR survey workflow (separate
  repo: `ixhlbxi/arm-drone-lidar-workflow`). Consumes RTK from the Base-Station's
  NTRIP caster, tags output with project code + mission, exports to NAD83 State Plane
  in US Survey Foot for direct TBC import. See
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
- [Engineering Decisions](docs/DECISIONS.md) — D-001 to D-034 (latest: D-030–D-034
  cover the overhaul)
- [Hardware](docs/HARDWARE.md) — bill of materials, GPIO/serial map, power
- [Specifications](docs/SPECIFICATIONS.md) — sensors, accuracy targets, performance budgets
- [Roadmap](docs/ROADMAP.md) — phased delivery plan
