# PiLiDAR-RTK Rover — Claude Code Project Prompt

> **v0.11 — post-audit remediation (2026-09-23).** The v0.10 Base-Station
> integration overhaul (below) completed 2026-05-30. A 2026-09-22 super-audit
> (`docs/AUDIT_super_20260922_1810.md`) found 86 findings; the six-stage remediation
> campaign that closed them (design: `docs/superpowers/specs/2026-09-22-audit-remediation-design.md`)
> is v0.11. Current phase: **v1.0 field validation** — see §2. **Version:** the sole
> source is `src/rover/__init__.py` (`pyproject.toml` reads it via `dynamic=["version"]`);
> this doc's v0.11 label tracks the campaign, not the code's semver. Authoritative docs:
> `docs/BASE_STATION_INTEGRATION.md` (integration contract), `docs/DECISIONS.md`
> (DEC-030–DEC-035 supersede DEC-005/DEC-006/DEC-010; DEC-015 and DEC-031 amended
> 2026-09-23). Flag conflicts rather than papering over them.

## Where to find detail

This file is the operational core. Everything else lives in `docs/`:

| Topic | File |
|---|---|
| Full TOML config schema, JSONL records, metadata.json | `docs/SPECIFICATIONS.md` |
| LoRa frame v2 (rover emits STATUS only; LINK defined, never sent; RTCM_CHUNK retired/reserved), wire formats | `docs/BASE_STATION_INTEGRATION.md` §4 |
| All decisions DEC-001–DEC-035 with rationale + alternatives | `docs/DECISIONS.md` |
| System architecture, data/telemetry flow diagrams | `docs/ARCHITECTURE.md` |
| Wiring, power, BOM, GPIO pinout details | `docs/HARDWARE.md` |
| Phase plan, build order, success criteria | `docs/ROADMAP.md` |
| Performance budgets, failure modes, storage estimates | `docs/SPECIFICATIONS.md` + `docs/ARCHITECTURE.md` |
| Base-Station ↔ rover contract (endpoints, status.json) | `docs/BASE_STATION_INTEGRATION.md` |
| Sibling-side work this rover is waiting on + open backlog rows (`S3-R2`, `S5-R2`, `S5-R3`, `S5-F1`, `NC-1`) | `docs/CROSS_REPO_BACKLOG.md` |
| v2 SLAM-capable platform concept (deferred past v1.0, DEC-023) | `docs/V2_SLAM_CONCEPT.md` |
| systemd units, udev rules, install.sh | `deploy/` |

---

## 1. What This Is

Custom RTK LiDAR rover: LD19 LiDAR on a rotating mast (NEMA17 + A4988), Pi HQ Camera,
MPU-9250 IMU (Madgwick fusion), ZED-F9P RTK GNSS, ESP32 LoRa (STATUS telemetry only,
DEC-031 amended) + WiFi (optional NTRIP client, DEC-032). RTK corrections come over
NTRIP from the external `arm-drone-lidar-workflow` Base-Station's caster — this rover
is a client, not a parallel base. That caster serves one client at a time (sibling
`NC-1`); interim rule (owner, 2026-09-23): the drone and this rover never share a base session (`CR-005`).

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
| Planning | ✅ 35 decisions (DEC-001–DEC-035); DEC-015 and DEC-031 amended 2026-09-23 |
| Hardware in hand | LD19, MPU-9250, A4988+NEMA17, Pi HQ Cam, Pi 4B, ESP32 LoRa |
| Hardware NOT in hand | one ZED-F9P, one antenna (SparkFun GPS-RTK-SMA + u-blox ANN-MB-00, D-005), 3.3V regulator, batteries |
| Codebase | ✅ every module in `src/rover/` implemented — see `python -m pytest -q` for the current suite count |
| Current phase | **v1.0 field validation**, gated on `deploy/SMOKE_CHECKLIST.md` and the pre-field blockers `S3-R2` (LD19 angle direction) and `S5-R2` (rest-heading noise) |

## 3. Target Platform

- **Hardware:** Raspberry Pi 4B
- **OS:** Raspberry Pi OS Lite 64-bit (Bookworm)
- **Python:** 3.11+ (system)
- **GPIO:** `rpi-lgpio` or `gpiozero` — **NOT `RPi.GPIO`** (DEC-029: broken on Bookworm,
  raises `RuntimeError: Failed to add edge detection`). `rpi-lgpio` is drop-in. Set
  `LG_WD=/tmp` to suppress lgpio temp files.
- **Config:** TOML via stdlib `tomllib` (read), `tomli-w` only if writing.
- **Data:** JSONL.
- **Deps** (`pyproject.toml` optional-dependencies): `pi` — `rpi-lgpio`, `picamera2`,
  `smbus2`, `pyserial`, `pyubx2`. `dev` — `pytest`, `ruff`, `pyubx2`, `pygeomag`.
  `post` (CRS-aware export, DEC-034) — `laspy`, `pyproj`, `numpy`, `pygeomag`.

## 4. Repository Structure

```
LiDAR_Scanner_DIY/
├── pyproject.toml
├── config/
│   ├── default.toml             # full schema: docs/SPECIFICATIONS.md §2.2
│   └── telemetry-only.toml      # bench/smoke profile: stepper/lidar/camera/imu off, GNSS + telemetry on
├── src/rover/
│   ├── __init__.py              # __version__, the sole version source
│   ├── main.py                  # orchestrator: sweep planner, sensor gate, NTRIP abort, home-on-exit
│   ├── config.py                # TOML parse + validate (frozen dataclasses)
│   ├── _io.py                   # atomic-write helper
│   ├── lidar.py imu.py stepper.py camera.py logger.py
│   ├── sweep.py                 # 360° forward sweep + fast-rewind planner (DEC-015 amended)
│   ├── gnss.py                  # ZED-F9P NAV-PVT/GGA fusion driver
│   ├── ntrip.py                 # Pi-side NTRIP client (fatal-error handling, GGA upload)
│   ├── lora_protocol.py         # LoRa frame v2: defines STATUS/LINK; RTCM_CHUNK (0x10) retired/reserved
│   ├── telemetry.py             # TelemetryRouter — status.json + loopback HTTP + LoRa STATUS
│   └── watchdog.py              # sd_notify + heartbeat-timeout
├── firmware/esp32-rover/        # PlatformIO; modes: ntrip_client, lora_rtcm_relay (pending removal, S5-F1)
├── tests/                       # 29 files: unit tests off-Pi (mock hardware) + tests/hardware/ (needs device)
├── scripts/georef.py            # JSONL → georeferenced LAS/PLY (CRS-aware; ellipsoidal + NAVD88)
├── deploy/                      # install.sh, systemd/ (rover.service, rover-telemetry.service),
│                                 # udev/ (99-rover-lidar/f9p/esp32.rules), SMOKE_CHECKLIST.md
├── data/                        # .gitignored session output
└── docs/
    ├── SPECIFICATIONS.md ARCHITECTURE.md HARDWARE.md ROADMAP.md
    ├── BASE_STATION_INTEGRATION.md DECISIONS.md CROSS_REPO_BACKLOG.md
    ├── ATTRIBUTION.md V2_SLAM_CONCEPT.md AUDIT_super_20260922_1810.md
    ├── archive/                  # pre-v0.10 docs (README_v0.9.2.md)
    └── superpowers/              # audit-remediation design spec + per-stage plans
```

## 5. Coding Standards

- Python 3.11+, type hints on public APIs. Format and lint with `ruff` (config in
  `pyproject.toml`): `python -m ruff format src scripts tests` then
  `python -m ruff check src scripts tests`. Both must be clean before a merge.
  The format-only commit is listed in `.git-blame-ignore-revs`; run
  `git config blame.ignoreRevsFile .git-blame-ignore-revs` once per clone so
  `git blame` skips it.
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
- **Docs:** `tests/test_docs.py` pins facts that drifted before — when a doc and the
  code disagree, fix the doc and extend the guard.

## 6. Key Decisions (one-line reference — full text in `docs/DECISIONS.md`)

| ID | Decision |
|---|---|
| DEC-003 | Pi as main controller |
| DEC-005 | ~~RTK via LoRa~~ — superseded by **DEC-031** (NTRIP-primary; LoRa fallback retired 2026-09-23) |
| DEC-006 | ~~RTCM direct routing~~ — superseded by **DEC-032** (NTRIP client on Pi *or* ESP32 per config) |
| DEC-010 | ~~T-Deck Receive-Only~~ — superseded by **DEC-033** (T-Deck owned by Base-Station; triple-channel telemetry) |
| DEC-012 | Madgwick filter (lighter than EKF, scan-rate adequate) |
| DEC-013 | Magnetometer disabled during motor (stepper EMI) |
| DEC-014 | Timestamp sync via ring buffer + slerp |
| DEC-015 | Direct-drive mast rotation, no slip ring; amended 2026-09-23 — sweep is 360° forward then a fast rewind (not ±180° oscillation) |
| DEC-018 | Split 5V compute / 12V motor power domains |
| DEC-019 | Dedicated 3.3V regulator for F9P+IMU (not Pi GPIO 3.3V) |
| DEC-020 | Python + Pi OS Lite 64-bit (Bookworm) |
| DEC-021 | JSONL logging |
| DEC-022 | Post-processed georeferencing (offline in Phase 5) |
| DEC-023 | SLAM deferred to v1.1+ (v2 concept: `docs/V2_SLAM_CONCEPT.md`) |
| DEC-028 | TOML config |
| DEC-029 | `rpi-lgpio` over `RPi.GPIO` (Bookworm breakage) |
| DEC-030 | Dual-mode profile (`personal` / `arm_group`) |
| DEC-031 | NTRIP-primary RTK; amended 2026-09-23 — LoRa fallback retired, NTRIP is the sole RTK path (Base-Station `ARM_BASE` on `:2101`) |
| DEC-032 | NTRIP client location: Pi or ESP32 per `[ntrip].client_location` |
| DEC-033 | Triple-channel telemetry: `status.json` + loopback HTTP + LoRa STATUS/LINK (rover emits STATUS only) |
| DEC-034 | Log SI/WGS84, convert CRS at export via `scripts/georef.py` |
| DEC-035 | Deep alignment with `arm-drone-lidar-workflow` — sibling conventions, `deploy/` kit, DEC-NNN decision-log format |

## 7. GPIO Pinout & Serial Ports (quick reference for code)

**GPIO (BCM):** `17`=Stepper DIR, `27`=Stepper STEP, `22`=Stepper ENABLE (active low),
`2`=I2C SDA, `3`=I2C SCL. 4.7 kΩ pull-ups on SDA/SCL to 3.3V.

**Serial (udev stable symlinks, primary — `deploy/udev/99-rover-*.rules`):**
- `/dev/rover-lidar` — LD19 LiDAR @ 230400
- `/dev/rover-f9p` — ZED-F9P @ 115200 (NMEA/UBX)
- `/dev/rover-esp32` — ESP32 LoRa @ 115200 (STATUS telemetry)

Raw `/dev/ttyUSB0`, `/dev/ttyACM0`, `/dev/ttyUSB1` appear only as the pre-install
fallback, before `sudo deploy/install.sh` lays down the udev rules.

**I2C:** `0x68`/`0x69` MPU-9250 (AD0 low/high); `0x0C` AK8963 mag (via bypass).

**ESP32 rover wiring:** `TX2` → F9P UART2 RX; `TX0/USB` ↔ Pi USB (telemetry); SPI →
SX1262 LoRa radio. The wiring is unaffected by DEC-031's amendment — `[lora].role`
on the Pi side just no longer offers an RTCM-receive value.

Full wiring/power detail in `docs/HARDWARE.md`.

## 8. Coordinate Frames

| Frame | X | Y | Z |
|---|---|---|---|
| LiDAR / IMU / Body | Forward | Left | Up |
| Local ENU | East | North | Up |

**Mount geometry:** the LD19 scan plane is the body X-Z plane (vertical); the mast
rotates that plane about body Z. `[imu].mount` = `"base"` (fixed to the body,
default) | `"platform"` (turns with the mast) — real config key, physical choice
still a bench decision (`S3-R3`). `[calibration].antenna_offset_m` is the
LiDAR-centre → antenna-phase-centre lever arm (metres, platform frame at mast 0);
optional, `None` until measured.

**Heading:** yaw comes from a per-sweep rest-heading magnetometer reading —
Madgwick's NWU output converted to true-north ENU via WMM 2025 declination
(`pygeomag`) — never from GNSS or from gyro integration during the sweep;
roll/pitch come from the IMU every scan.

**Transform chain:**
`LiDAR → IMU → Body → GNSS → Local ENU → WGS84`
(notation: `T_A_B` = transform from frame B to A).

**Quaternion convention:** scalar-first `[w, x, y, z]`, right-handed.

Extrinsic calibration (`T_lidar_imu`, `T_body_gnss`) beyond the antenna lever arm
above is TBD for v1.0 — accuracy without it is ±5–10 cm; the rest of the
calibration procedure is v1.1.

## 9. Out of Scope for v1.0

- RTCM over LoRa (retired, DEC-031 amended) — LoRa carries STATUS telemetry only; the
  protocol still defines a LINK frame type but the rover never emits it. NTRIP is the
  sole RTK path. Firmware's `lora_rtcm_relay` mode pending removal (`S5-F1`).
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
