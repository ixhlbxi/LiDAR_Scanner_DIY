# PiLiDAR-RTK Rover — Claude Code Project Prompt

> **v0.10 — Base-Station integration overhaul (2026-05-23).** v0.9.2 freeze lifted to
> integrate with the production Base-Station in `ixhlbxi/arm-drone-lidar-workflow`.
> Authoritative docs: `docs/BASE_STATION_INTEGRATION.md` (integration contract),
> `docs/DECISIONS.md` (DEC-030–DEC-034 supersede DEC-005/DEC-006/DEC-010). Flag conflicts
> rather than papering over them.

## Where to find detail

This file is the operational core. Everything else lives in `docs/`:

| Topic | File |
|---|---|
| Full TOML config schema, JSONL records, metadata.json | `docs/SPECIFICATIONS.md` |
| LoRa frame v2 (STATUS/LINK/RTCM_CHUNK), wire formats | `docs/BASE_STATION_INTEGRATION.md` §4 |
| All decisions DEC-001–DEC-035 with rationale + alternatives | `docs/DECISIONS.md` |
| System architecture, data/telemetry flow diagrams | `docs/ARCHITECTURE.md` |
| Wiring, power, BOM, GPIO pinout details | `docs/HARDWARE.md` |
| Phase plan, build order, success criteria | `docs/ROADMAP.md` |
| Performance budgets, failure modes, storage estimates | `docs/SPECIFICATIONS.md` + `docs/ARCHITECTURE.md` |
| Base-Station ↔ rover contract (endpoints, status.json) | `docs/BASE_STATION_INTEGRATION.md` |
| Sibling-side work this rover is waiting on (Heltec v2, etc.) | `docs/CROSS_REPO_BACKLOG.md` |
| systemd units, udev rules, install.sh | `deploy/` |

---

## 1. What This Is

Custom RTK LiDAR rover: LD19 LiDAR on a rotating mast (NEMA17 + A4988), Pi HQ Camera,
MPU-9250 IMU (Madgwick fusion), ZED-F9P RTK GNSS, ESP32 LoRa+WiFi for RTK fallback /
telemetry. RTK corrections from the external `arm-drone-lidar-workflow` Base-Station —
this rover is a client, not a parallel base.

**Position relative to the SparkFun RTK Facet** (DEC-035): the sibling
`arm-drone-lidar-workflow` repo selected the SparkFun Facet as its production
GNSS-only "rover" for GCP occupations / single-point RTK fixes. This DIY rover
is the **LiDAR-scanning companion** — different job (volumetric scans), same
ecosystem (same NTRIP base, same project conventions, same status.json shape).
Both rovers can run at the same site against the same `ARM_BASE` caster.

**Two session profiles** (DEC-030):
- `personal` — off-grid friendly, NTRIP optional, WGS84 / local ENU output.
- `arm_group` — companion to ARM Group drone/LiDAR workflow; NTRIP required; outputs
  land in `01_Raw/LiDAR/Rover/<session>/`; export to NAD83(2011) State Plane via
  `scripts/georef.py`.

**Accuracy target:** ±5–10 cm (v1.0); ±2–3 cm with calibration (v1.1).
**Inspiration:** [PiLiDAR/PiLiDAR](https://github.com/PiLiDAR/PiLiDAR).

## 2. Project Status

| What | Status |
|---|---|
| Planning | ✅ 35 decisions (DEC-001–DEC-035); DEC-030–DEC-034 cover v0.10 integration, DEC-035 covers the 2026-05-30 deep-alignment overhaul |
| Hardware in hand | LD19, MPU-9250, A4988+NEMA17, Pi HQ Cam, Pi 4B, ESP32 LoRa |
| Hardware NOT in hand | 2× ZED-F9P, 2× dual-band antennas, 3.3V regulator, batteries |
| Codebase | ✅ Phase 3 landed (config/logger/lidar/imu/stepper/camera + tests). ⚠️ v0.10 overhaul in progress (telemetry, ntrip, gnss, esp32 firmware) |
| Current phase | **v0.10 overhaul** — see Phase plan in `docs/ROADMAP.md` |

## 3. Target Platform

- **Hardware:** Raspberry Pi 4B
- **OS:** Raspberry Pi OS Lite 64-bit (Bookworm)
- **Python:** 3.11+ (system)
- **GPIO:** `rpi-lgpio` or `gpiozero` — **NOT `RPi.GPIO`** (DEC-029: broken on Bookworm,
  raises `RuntimeError: Failed to add edge detection`). `rpi-lgpio` is drop-in. Set
  `LG_WD=/tmp` to suppress lgpio temp files.
- **Config:** TOML via stdlib `tomllib` (read), `tomli-w` only if writing.
- **Data:** JSONL.
- **Deps:** `rpi-lgpio`, `picamera2`, `smbus2`, `pyserial`.

## 4. Repository Structure

```
LiDAR_Scanner_DIY/
├── pyproject.toml
├── config/default.toml          # see docs/SPECIFICATIONS.md for full schema
├── src/rover/
│   ├── main.py                  # orchestration (stub today)
│   ├── config.py                # TOML parse + validate (frozen dataclasses)
│   ├── lidar.py imu.py stepper.py camera.py logger.py
│   ├── gnss.py                  # ZED-F9P NMEA/UBX (Phase C — stub)
│   ├── ntrip.py                 # Pi-side NTRIP client (Phase C — new)
│   ├── telemetry.py             # TelemetryRouter — 3 channels (Phase B)
│   └── watchdog.py              # stub
├── firmware/esp32-rover/        # PlatformIO; modes: lora_rtcm_relay | ntrip_client
├── tests/
│   ├── test_config.py test_logger.py   # off-Pi unit tests
│   └── hardware/                # diagnostic scripts; run on Pi with hardware
├── scripts/georef.py            # JSONL → georeferenced LAS/PLY (CRS-aware, Phase E)
├── data/                        # .gitignored session output
└── docs/
```

## 5. Coding Standards

- Python 3.11+, type hints on public APIs. Format with `ruff` (preferred) or `black`+`isort`.
- **Testing:** `pytest`. Unit tests off-Pi (mock hardware). Hardware tests in
  `tests/hardware/` require the device.
- **Logging:** stdlib `logging`; level from `[general] log_level`.
- **Error handling:** sensors that fail to init log a warning and mark themselves
  unavailable — do not crash the system. `enabled=true` with absent hardware → warn
  and continue with that subsystem disabled.
- **Concurrency:** not finalized; start sequential, evaluate `asyncio`/`threading`
  during integration.
- **Scripts >50 lines:** top-of-file header (purpose, deps, usage, flags/I/O, limits,
  changelog). <50 lines: minimal inline comments only.
- **Deps:** prefer stdlib; declare non-stdlib in `pyproject.toml`.

## 6. Key Decisions (one-line reference — full text in `docs/DECISIONS.md`)

| ID | Decision |
|---|---|
| DEC-003 | Pi as main controller |
| DEC-005 | ~~RTK via LoRa~~ — superseded by **DEC-031** (NTRIP primary, LoRa fallback) |
| DEC-006 | ~~RTCM direct routing~~ — superseded by **DEC-032** (NTRIP client on Pi *or* ESP32 per config) |
| DEC-010 | ~~T-Deck Receive-Only~~ — superseded by **DEC-033** (T-Deck owned by Base-Station; triple-channel telemetry) |
| DEC-012 | Madgwick filter (lighter than EKF, scan-rate adequate) |
| DEC-013 | Magnetometer disabled during motor (stepper EMI) |
| DEC-014 | Timestamp sync via ring buffer + slerp |
| DEC-018 | Split 5V compute / 12V motor power domains |
| DEC-019 | Dedicated 3.3V regulator for F9P+IMU (not Pi GPIO 3.3V) |
| DEC-020 | Python + Pi OS Lite 64-bit (Bookworm) |
| DEC-021 | JSONL logging |
| DEC-022 | Post-processed georeferencing (offline in Phase 5) |
| DEC-023 | SLAM deferred to v1.1+ |
| DEC-028 | TOML config |
| DEC-029 | `rpi-lgpio` over `RPi.GPIO` (Bookworm breakage) |
| DEC-030 | Dual-mode profile (`personal` / `arm_group`) |
| DEC-031 | NTRIP-primary RTK + LoRa fallback (consumes Base-Station `ARM_BASE` on `:2101`) |
| DEC-032 | NTRIP client location: Pi or ESP32 per `[ntrip].client_location` |
| DEC-033 | Triple-channel telemetry: `status.json` + loopback HTTP + LoRa STATUS/LINK |
| DEC-034 | Log SI/WGS84, convert CRS at export via `scripts/georef.py` |

## 7. GPIO Pinout & Serial Ports (quick reference for code)

**GPIO (BCM):** `17`=Stepper DIR, `27`=Stepper STEP, `22`=Stepper ENABLE (active low),
`2`=I2C SDA, `3`=I2C SCL. 4.7 kΩ pull-ups on SDA/SCL to 3.3V.

**Serial:**
- `/dev/ttyACM0` — ZED-F9P @ 115200 (NMEA/UBX)
- `/dev/ttyUSB0` — LD19 LiDAR @ 230400
- `/dev/ttyUSB1` — ESP32 LoRa @ 115200 (telemetry + future commands)

**I2C:** `0x68`/`0x69` MPU-9250 (AD0 low/high); `0x0C` AK8963 mag (via bypass).

**ESP32 rover wiring:** `TX2` → F9P UART2 RX (RTCM forwarding); `TX0/USB` ↔ Pi USB
(telemetry); SPI → SX1262 LoRa radio.

Full wiring/power detail in `docs/HARDWARE.md`.

## 8. Coordinate Frames

| Frame | X | Y | Z |
|---|---|---|---|
| LiDAR / IMU / Body | Forward | Left | Up |
| Local ENU | East | North | Up |

**Transform chain:**
`LiDAR → IMU → Body → GNSS → Local ENU → WGS84`
(notation: `T_A_B` = transform from frame B to A).

**Quaternion convention:** scalar-first `[w, x, y, z]`, right-handed.

Extrinsic calibration (`T_lidar_imu`, `T_body_gnss`) is TBD for v1.0 — accuracy
without it is ±5–10 cm; calibration procedure is v1.1.

## 9. Out of Scope for v1.0

- Base-Station-side LoRa RTCM Tx (lives in `arm-drone-lidar-workflow`, Phase D sibling PR)
- T-Deck firmware (Base-Station owns it)
- Point cloud processing / 3D reconstruction (Phase 5: `scripts/georef.py`)
- Real-time SLAM / georef (DEC-022, DEC-023)
- Camera texture mapping (v1.2+)
- Extrinsic calibration procedure (v1.1)
- Rover→Base-Station bidirectional commands (rover publishes STATUS only)

## 10. How to Work With Me

- I'm the project owner. Challenge assumptions and flag risks — peer review, not agreement.
- Show me a plan before generating 500 lines of code, especially for new modules.
- Ask before making structural decisions I haven't specified (file names, APIs, module boundaries).
- If specs seem wrong or underspecified, say so — don't silently paper over.
- Default to minimal output. Skip auxiliary files, summaries, extra docs unless asked.
- Implement plans, not speculation. If spec doesn't cover a case, flag it.
