# Cross-Repo Backlog

**Document Status:** v0.10 — initial (deep-alignment overhaul, 2026-05-30)

Tracks work in `ixhlbxi/arm-drone-lidar-workflow` (the sibling Base-Station
repo) that this rover repo is waiting on. Items here are *not* tasks for the
rover — they're forward references that explain why some end-to-end paths
this rover documents and codes for are not yet field-functional.

When an item lands sibling-side, update its **Status** here and remove the
corresponding "rover-side ready, base-side pending" caveats from the
relevant rover docs.

---

## Items

### CR-001 — Heltec LoRa firmware: bump from v1 to v2 envelope

**What:** `arm-drone-lidar-workflow/base-station/heltec-display/src/main.cpp`
runs `LORA_PROTO_VERSION = 1`, which carries only the `DISPLAY` body. The
rover's [`src/rover/lora_protocol.py`](../src/rover/lora_protocol.py)
implements the v2 envelope (version byte `0x02`, type/seq/len/CRC) and
defines `STATUS` / `LINK` / `RTCM_CHUNK` / `DISPLAY` / `DEBUG_TEXT` types.

**Why we need it:**
- The rover's [LoRa STATUS / LINK telemetry channel (DEC-033)](DECISIONS.md#dec-033-triple-channel-telemetry-supersedes-dec-010)
  cannot be received by any sibling-repo handheld until those handhelds
  understand v2 frames.
- LoRa-RTCM fallback ([DEC-031](DECISIONS.md#dec-031-ntrip-primary-rtk-with-lora-fallback-supersedes-dec-005))
  needs sibling-side firmware to *transmit* `RTCM_CHUNK` (type `0x10`),
  which only makes sense in the v2 envelope.

**Status:** ⏳ Pending sibling PR.

**Rover-side ready:** yes — `lora_protocol.py` codec + tests, ESP32-rover
firmware's `lora_rtcm_relay` mode both consume v2 already.

**Cross-reference in this repo:**
- [`docs/BASE_STATION_INTEGRATION.md` §4](BASE_STATION_INTEGRATION.md#4-lora-frame-v2)
  — the shared spec.

---

### CR-002 — Base-side LoRa-RTCM transmitter daemon

**What:** A sibling-repo daemon (working name `rtk_base_rtcm_serial.py`,
running on the Base-Station Pi) that reads the RTCM3 stream from the local
F9P, fragments it, wraps each fragment in a v2 `RTCM_CHUNK` frame, and ships
it to the Heltec V3 over USB serial for LoRa transmission.

**Why we need it:**
- Without it, the LoRa-fallback path from
  [DEC-031](DECISIONS.md#dec-031-ntrip-primary-rtk-with-lora-fallback-supersedes-dec-005)
  has no transmitter — only the rover-side receiver
  (`firmware/esp32-rover/` in `lora_rtcm_relay` mode) exists.
- Currently the rover's NTRIP-primary path works end-to-end; the LoRa
  fallback is rover-side-ready but base-side-absent.

**Status:** ⏳ Pending sibling PR (sibling's "Phase D").

**Rover-side ready:** yes — ESP32 firmware receives + writes to F9P UART2;
`config.lora.role = "rtcm_rx+status_tx"` enables the receive path.

**Cross-reference:**
- [`docs/BASE_STATION_INTEGRATION.md` §2.2](BASE_STATION_INTEGRATION.md#22-fallback--lora-relayed-rtcm)
  — the fallback architecture diagram.

---

### CR-003 — Sibling-side recognition of rover STATUS / LINK frames

**What:** The sibling's handheld firmware (Heltec OLED unit, T-Deck) needs to
dispatch on the v2 frame `type` byte and render `STATUS` (`0x01`) +
`LINK` (`0x02`) packets coming from the rover.

**Why we need it:**
- Without it, rover field telemetry over LoRa is invisible to anyone holding
  a Base-Station handheld — the channel works on the wire but nobody listens.

**Status:** ⏳ Pending sibling work (depends on CR-001).

**Rover-side ready:** yes — `LoRaPublisher` emits STATUS + LINK frames at
configurable cadence.

**Cross-reference:**
- [`docs/BASE_STATION_INTEGRATION.md` §3.3](BASE_STATION_INTEGRATION.md#33-channel-c--lora-status--link-packets).

---

### CR-004 — Document `01_Raw/LiDAR/Rover/` subfolder split in sibling docs

**What:** The sibling's `base-station/docs/lidar-rover-integration.md` (or
equivalent) should document the `01_Raw/LiDAR/Rover/` subfolder convention
this rover writes into under the `arm_group` profile.

**Why we need it:**
- Right now the convention is only documented here (in
  [`BASE_STATION_INTEGRATION.md` §6](BASE_STATION_INTEGRATION.md#6-project-folder-conventions-arm_group-profile)).
  When sibling-repo operators look for "where does the LiDAR rover output
  go?" they should find it in their own repo's docs too.

**Status:** ⏳ Pending sibling docs PR.

**Rover-side ready:** yes — logger respects `[logging].output_dir` and
operators can point it at the project folder per the contract.

---

### CR-005 — Multi-client NTRIP caster on the Base-Station

**What:** The sibling's caster (`base-station/rtk_base_manager.py`
`NTRIPServer`) serves one client at a time. A newly authenticated client
replaces the current one, so a drone and this rover on the same base session
would evict each other every time either reconnects. Filed sibling-side as
BACKLOG **NC-1** (§NTRIP Caster) on 2026-09-23.

**Interim rule (owner, 2026-09-23):** the drone and this rover never share a
base session.

**Status:** ⏳ Pending sibling enhancement NC-1.

**Rover-side ready:** yes — nothing changes on the rover; it is an ordinary
NTRIP v1 client of `ARM_BASE`.

---

## Rover-side deferred (from the 2026-09-22 super-audit)

Items dispositioned `defer` or `track` in `docs/AUDIT_super_20260922_1810.md`, plus the
firmware rows deferred because PlatformIO is not installed on the dev machine. These are
rover-side, not sibling-side; they live here because this file is the repo's single
tracking file. Each carries its finding ID so the report and this list stay cross-referenced.

| ID | Where | What | Why deferred |
|---|---|---|---|
| T1-018 | `src/rover/imu.py` free-fall branch | Quaternion derivative uses already-modified q0 | Low; superseded when the MARG update lands in stage 3 |
| T1-021 | `src/rover/gnss.py` `_nmea_checksum_ok` | Non-hex checksum raises ValueError into the catch-all | Low; one 0.5 s stall on a corrupt sentence |
| T1-024 | `src/rover/ntrip.py` `stop()` / stats | [CLOSED 2026-09-23 167f4a2] Socket not closed on stop; stats handed live | Low; partially addressed in stage 4 |
| T1-028 | `src/rover/config.py` `_require_type` | bool passes int checks | Low; no config key plausibly set to a bool by mistake |
| T1-037 | `src/rover/main.py` scan_state | Stays SCAN_ERROR after a recovered stepper fault | Low; cosmetic on the telemetry channel |
| T1-038 | `src/rover/main.py` settle | Stop latency up to ~6 s | Low; the settle half is fixed in stage 2, the read_scan half waits for stage 3 |
| T1-040 | `src/rover/gnss.py` `line_buf` | Unbounded if the stream never contains newline | Low; capped in stage 4 while in the file |
| T1-045 | four driver modules | Shared `_Device` base class | Medium-effort refactor with no behaviour change; after v1.0 field validation |
| T1-048 | `src/rover/config.py` `_validate` | Declarative validation table | Medium-effort refactor with no behaviour change; after v1.0 field validation |
| D-016 | `deploy/systemd/rover.service:4` | Wrong sibling DEC reference | Track; removed in stage 2 if trivial |
| D-018 | workspace `../CLAUDE.md` | No row for this repo in the signpost table | Track; outside this repo, per-file confirm |
| T1-034 | `firmware/esp32-rover/src/main.cpp:233` | `"200"` substring accepts SOURCETABLE reply | Firmware: needs PlatformIO build + flash on hardware |
| T1-035 | `firmware/esp32-rover/src/main.cpp:170-196` | USB framing drops back-to-back frames; millis wrap | Firmware: needs PlatformIO build + flash on hardware |
| T1-051 | `firmware/esp32-rover/` | Dead `encode_frame_v2`, duplicated checks, unused ArduinoJson dep and macros | Firmware: needs PlatformIO build + flash on hardware |
| T1-042 (firmware half) | `firmware/esp32-rover/src/main.cpp` | Quote the golden frame vector from `tests/test_lora_protocol.py` | Firmware: Python half lands in stage 4 |

---

### Filed during stage 2 review (2026-09-22) — for stage 4

| ID | Where | What | Why here |
|---|---|---|---|
| S2-R1 | `src/rover/gnss.py` NAV-PVT + GGA paths | [CLOSED 2026-09-23 167f4a2] Altitude datum: NAV-PVT now logs `hMSL` (orthometric) and GGA logs MSL, but `GnssFix.alt` and SPECIFICATIONS.md say ellipsoidal | Stage 4 rewrites gnss.py: log ellipsoidal from both (NAV-PVT `height`; GGA alt + geoid separation field 11) or relabel the schema |
| S2-R2 | `src/rover/telemetry.py` RoverStatus | [CLOSED 2026-09-23 167f4a2] A tripped sensor gate and `logger.degraded` are not visible on the wire (status.json / LoRa STATUS) | Changes the Base-Station contract; stage 4 owns telemetry |
| S2-R3 | `src/rover/main.py` stepper failure branch | [CLOSED 2026-09-23 167f4a2] Warns every 0.5 s forever and its `continue` skips the telemetry publish, so SCAN_ERROR is never published | Gate it like the sensors; stage 4 touches the loop's publish block |
| S2-R4 | `src/rover/logger.py` `write()` Full path | [CLOSED 2026-09-23 167f4a2] Drop-oldest takes `_lock`, which `_flush` holds across disk I/O, so a stalled disk blocks the producer; drained-but-unwritten records on a failed flush are not counted | Needs a small design choice (separate counter lock, `lost_records`) |

### Pre-field-session blockers (from the stage 3 whole-branch review, merged 7ef5b1e)

These need the owner and a bench target before any session is georeferenced; none is coded yet.

| ID | Where | What | Decision needed |
|---|---|---|---|
| S3-R1 | `scripts/georef.py`, `src/rover/imu.py` | Madgwick's world frame is North-West-Up (x = magnetic north) and no declination is applied; georef adds ENU offsets to NWU points, so cloud azimuth in State Plane is arbitrary (with 6-DOF, yaw is the start-up heading; yaw is now stripped when no magnetometer) | Add the fixed NWU→ENU rotation plus a declination setting (about −11° in PA), or accept "orientation relative to first heading" and document it |
| S3-R2 | `src/rover/lidar.py`, `docs/HARDWARE.md` | LDRobot documents LD19 angles increasing clockwise (left-handed), so the side-mount mapping (LiDAR y → body up) is right for only one of the two ways the sensor can stand on its side | Bench check with a target above the scanner; then pin the mount orientation in HARDWARE.md or negate the angle at parse |
| S3-R3 | `docs/HARDWARE.md:451`, `scripts/georef.py` | HARDWARE.md says the IMU is on the rotating platform; the code assumes it is rigid to the fixed body. If it rides the mast, georef applies the mast angle twice | Owner confirms the IMU mount; if on the mast, georef takes yaw from the commanded angle only |
| S3-R4 | `src/rover/logger.py` `_schedule_flush`/`stop()` | [CLOSED 2026-09-23 167f4a2] Timer is now started before being published; a `stop()` in that window leaves one stray no-op timer callback | Cancel-then-check pattern or a `_stopping` flag; benign until then |
| S3-R5 | `tests/test_config.py` | [CLOSED 2026-09-23 167f4a2] `mag_offset` bool/non-finite rejection and the two-neighbour step-interval message have no tests | Add in stage 4 Task 5 |

### Upgrade hazards (from the stage 4 whole-branch review, merged 167f4a2)

| ID | Where | What | Decision needed |
|---|---|---|---|
| S4-R1 | `deploy/install.sh`, `src/rover/config.py` | `install.sh` keeps an existing `/etc/rover/config.toml`. One installed from pre-stage-4 defaults still has `[power]`, `imu.fusion_output_hz`, `survey_in_*`, `rtcm_profile`, `logging.format` (now rejected, exit 2, and with RestartPreventExitStatus the unit stays down) and `status_schema_version = 1` (labels v2 payloads as v1). No rover is deployed yet, so nothing is affected today | Have `install.sh` flag retired keys, or have `load_config` warn instead of raise for this set; stage 5 docs carry the upgrade note either way |

## How to use this file

- **Adding an item:** when you find a "rover side codes for X, sibling side
  doesn't have X yet" gap, record it here so future-you doesn't waste time
  searching for the missing piece.
- **Closing an item:** when the sibling PR lands, change Status to `✅`,
  add the sibling commit SHA, and on the next rover-docs pass, fold the
  cross-references into the relevant doc bodies (delete the "pending" caveats).
- **No silent deletes:** keep closed items here as historical record;
  prepend `[CLOSED YYYY-MM-DD]` to the title.
