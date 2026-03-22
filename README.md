# PiLiDAR-RTK Rover

RTK-enabled LiDAR scanning platform built on Raspberry Pi 4B.

Combines LD19 LiDAR, MPU-9250 IMU, ZED-F9P RTK GNSS, and Pi HQ Camera
on a rotating stepper mast to produce georeferenced 3D point clouds.

## Quick Start

```bash
# Install (on Pi, with hardware deps)
pip install -e ".[pi]"

# Install (dev, off-Pi)
pip install -e ".[dev]"

# Run tests
pytest
```

## Project Status

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full development roadmap.
Currently in **Phase 3: Rover Software Core**.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Engineering Decisions](docs/DECISIONS.md)
- [Hardware](docs/HARDWARE.md)
- [Specifications](docs/SPECIFICATIONS.md)
- [Roadmap](docs/ROADMAP.md)
