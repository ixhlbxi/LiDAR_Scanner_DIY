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

**Status:** ⏳ Pending sibling PR. The RTCM_CHUNK reason above is retired (DEC-031 amended 2026-09-23, dae5776); v2 is still needed for STATUS/LINK (CR-003).

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

**Status:** ❌ Not needed — DEC-031 amended 2026-09-23 (dae5776): LoRa is status-only and NTRIP is the only RTK path.

**Rover-side ready:** retired — `config.lora.role` has no RTCM receive value since stage 5 (dae5776); the firmware's `lora_rtcm_relay` env awaits removal (row S5-F1).

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

**Status:** ⏳ Pending sibling work (depends on CR-001). LoRa carries STATUS/LINK only (DEC-031 amended 2026-09-23).

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

### CR-006 — Shared GCP targets: pattern description and scanner reuse

**What:** Sibling docs describe the Sky High Bull's-Eye GCP targets as a
bull's-eye pattern. Examples: `SOP/ARM_Drone_LiDAR_SOP.md` §1.2, "the deployed targets
are bull's-eye, not the checkerboard squares", and
`docs/reference/hardware_inventory.md`, "bull's-eye pattern". The vendor drawing
(owner-supplied, 2026-09-29) shows a 24 in 2×2 black/white checker with 12 in
quadrants, a centre eyelet at the saddle point, and a number 0–9. "Bull's-Eye" is
the brand name. Under DEC-036 the rover reuses these targets for camera-based
station resection: flat over the same nails by default, and vertical on rods
only for far targets on level ground.

**Why we need it:**
- The sibling pattern description should match the hardware. Its Keystone
  checkerboard spec and the "deployed targets differ" note may be reconcilable.
- Target numbers and surveyed nail coordinates should mean the same thing in
  both workflows, so one GCP export feeds both TBC and `scripts/georef.py`.
- Flat targets serve drone and scanner in the same session. A rod-mounted target
  cannot. The sibling SOP needs a note on sequencing for those few: fly first,
  then remount on rods, or reserve spare targets from the 10-pack for the scanner.
- Scanner use favours clearing grass or litter in front of targets. The drone
  workflow may want that noted in GCP placement guidance.

**Status:** ⏳ Pending sibling doc correction and SOP note.

**Rover-side ready:** partly. DEC-036 and `docs/HARDWARE.md` §4.4 record the
target geometry. Detection and resection code are v1.1.

---

### CR-007 — Backsight beacon on the base pole

**What:** A blinking LED (or IR LED) on the Base-Station pole at a measured height above
the ARP, with a unique blink code. Filed sibling-side as BACKLOG **SS-1**
(§Scanner-Support Upgrades) on 2026-10-02.

**Why we need it:**
- Gives every scanner station an automatic, known backsight: the cameras find the beacon
  by its blink pattern, so no target matching is needed for that point.
- RTCM 1005 already broadcasts the base ARP, so the rover learns the beacon position from
  the correction stream plus one configured height.

**Status:** ⏳ Pending sibling enhancement SS-1.

**Rover-side ready:** no. Needs blink-code detection in the camera pipeline (BS-R4 below).

---

### CR-008 — Retroreflective band on the base pole

**What:** A taped band at a measured height above the base ARP, so the base pole is also a
LiDAR target. Filed sibling-side as BACKLOG **SS-3** on 2026-10-02.

**Why we need it:**
- Backup to CR-007 when the beacon is out of camera view or washed out by sun.

**Status:** ⏳ Pending sibling SS-3 (trivial; a field task, not code).

**Rover-side ready:** partly. Intensity-band detection is the same code path as the PVC
pipe targets.

---

### CR-009 — Mission tag from the base `/status`

**What:** The Base-Station `/status` JSON already carries `mission`. The rover should stamp
it into every station's metadata so base RINEX and scanner sessions pair automatically.

**Why we need it:**
- Removes a manual pairing step during processing.

**Status:** ✅ Base side exists. Caveat: the base HTTP API binds to loopback by default; the
rover can only reach it over the field AP after `rtk-base field-mode on` (sibling FA-5).
No sibling work is owed.

**Rover-side ready:** no. See BS-R3 below.

---

### Rover-side — reuse of Base-Station work (filed 2026-10-02)

Rover tasks that reuse code or formats the sibling repo already ships, instead of building
parallel versions. From the 2026-10-02 review against the static-station scanner redesign.

| ID | What | Why |
|---|---|---|
| BS-R1 | Use the same 4.3" Freenove DSI touchscreen as the base, and port `display_touch.py` (accidental-touch filters, `evaluate_tap`) and `display_hold.py` (3 s destructive hold) | Those modules are pure and already tuned on that exact panel, which reports no contact size, so contact count plus a refractory window is the only palm defence |
| BS-R2 | In rover-GCP mode, write the sibling DEC-029 occupation-event JSONL format | Lets the sibling `slice_ubx_by_occupations.py` and `ubx_to_rinex.py` process scanner GCP occupations unchanged |
| BS-R3 | Read `mission` from the base `/status` on connect and stamp it into station metadata | Closes CR-009 rover-side |
| BS-R4 | Detect the base beacon (CR-007) by blink code and the pole band (CR-008) by intensity, and use the base ARP from RTCM 1005 as a known point in station resection | Gives the resection a known point that needs no target setup |

Already tracked elsewhere, not re-filed: the scanner sharing `ARM_BASE` is CR-005 (sibling
NC-1); the ANN-MB-00 phase-centre offset is the sibling DEC-021 back-calc, gated on F-8a
and AUD-9, and one result applies to both units since they use the same antenna model.

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
| S5-F1 | `firmware/esp32-rover/` | Retire the `lora_rtcm_relay` env and the RTCM_CHUNK (0x10) receive handler; `ntrip_client` becomes the only RTCM mode (DEC-031 amended 2026-09-23) | Firmware: needs PlatformIO build + flash |

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
| S3-R1 | `scripts/georef.py`, `src/rover/imu.py` | [CLOSED 2026-09-23 dae5776] Madgwick's world frame is North-West-Up (x = magnetic north) and no declination is applied; georef adds ENU offsets to NWU points, so cloud azimuth in State Plane is arbitrary (with 6-DOF, yaw is the start-up heading; yaw is now stripped when no magnetometer) | Add the fixed NWU→ENU rotation plus a declination setting (about −11° in PA), or accept "orientation relative to first heading" and document it |
| S3-R2 | `src/rover/lidar.py`, `docs/HARDWARE.md` | LDRobot documents LD19 angles increasing clockwise (left-handed), so the side-mount mapping (LiDAR y → body up) is right for only one of the two ways the sensor can stand on its side | Bench check with a target above the scanner; then pin the mount orientation in HARDWARE.md or negate the angle at parse |
| S3-R3 | `docs/HARDWARE.md:451`, `scripts/georef.py` | [CLOSED 2026-09-23 dae5776] Mount is now `[imu].mount`; the physical choice stays a bench item. HARDWARE.md says the IMU is on the rotating platform; the code assumes it is rigid to the fixed body. If it rides the mast, georef applies the mast angle twice | Owner confirms the IMU mount; if on the mast, georef takes yaw from the commanded angle only |
| S3-R4 | `src/rover/logger.py` `_schedule_flush`/`stop()` | [CLOSED 2026-09-23 167f4a2] Timer is now started before being published; a `stop()` in that window leaves one stray no-op timer callback | Cancel-then-check pattern or a `_stopping` flag; benign until then |
| S3-R5 | `tests/test_config.py` | [CLOSED 2026-09-23 167f4a2] `mag_offset` bool/non-finite rejection and the two-neighbour step-interval message have no tests | Add in stage 4 Task 5 |

### Upgrade hazards (from the stage 4 whole-branch review, merged 167f4a2)

| ID | Where | What | Decision needed |
|---|---|---|---|
| S4-R1 | `deploy/install.sh`, `src/rover/config.py` | [CLOSED 2026-09-24 2310f41] Upgrade note for both /etc/rover/*.toml in deploy/SMOKE_CHECKLIST.md and docs/SPECIFICATIONS.md; one gap remains as S6-R2. `install.sh` keeps an existing `/etc/rover/config.toml`. One installed from pre-stage-4 defaults still has `[power]`, `imu.fusion_output_hz`, `survey_in_*`, `rtcm_profile`, `logging.format` (now rejected, exit 2, and with RestartPreventExitStatus the unit stays down) and `status_schema_version = 1` (labels v2 payloads as v1). No rover is deployed yet, so nothing is affected today | Have `install.sh` flag retired keys, or have `load_config` warn instead of raise for this set; stage 5 docs carry the upgrade note either way Stage 5 adds one more: `[lora] role = "rtcm_rx+status_tx"` is now rejected (exit 2). |

### Stage 5 residuals (from the stage 5 whole-branch review, merged dae5776)

| ID | Where | What | Decision needed |
|---|---|---|---|
| S5-R1 | `src/rover/main.py` `_wait_for_heading_settle` | No test pins the ±180° yaw wrap (code verified correct); the first-rest settle can overrun `--duration-sec` by up to 60 s on bench runs | One wrap test; optionally bound the settle by the remaining duration |
| S5-R2 | `scripts/georef.py`, rover first rest | georef ignores `sweep_start` `heading_settled`, so a sweep 0 whose settle hit the 60 s cap is still labelled "true"; real magnetometer noise may exceed the 0.5°/1 s tolerance and make every session pay the cap | Bench-measure yaw noise at rest; then downgrade capped sweeps or list them in export.json |
| S5-R3 | mast mechanics (DEC-015) | Homing step in deploy/SMOKE_CHECKLIST.md (2310f41); home switch remains v1.1. No home switch: a crash or power loss mid-sweep leaves the mast out of position, and the next session calls it step 0 | Home by hand before each session (stage 6: `deploy/SMOKE_CHECKLIST.md`); a limit switch or index mark is the v1.1 fix |

### Stage 6 residuals (from the stage 6 whole-branch review, merged 2310f41)

| ID | Where | What | Decision needed |
|---|---|---|---|
| S6-R1 | `src/rover/watchdog.py:117`, `deploy/systemd/rover.service:39` | A heartbeat timeout calls `os._exit(2)`, but stage 4 added exit 2 (config error) to `RestartPreventExitStatus=2 4`, so a hung rover is **not** restarted; `watchdog.py` docstrings and `config/default.toml:105` still say it restarts. `rover-telemetry.service` has no such line and does restart. | Give the watchdog its own exit code (not 2 or 4) and a test pinning it against the unit file; fix the stale comments |
| S6-R2 | `deploy/SMOKE_CHECKLIST.md` upgrade item, `docs/SPECIFICATIONS.md` upgrade note, `tests/test_docs.py` | A Pi installed from `aa30447`/`e323f84` (2026-09-22) has `[stepper].step_interval_deg = 1.5`, now rejected (must be a multiple of 0.1125°; default 1.575) — the upgrade notes omit it. Guard looseness: paraphrases like "STATUS and LINK frames" escape; "never" is an allow-word; BASE_STATION_INTEGRATION is exempt from the RTCM-over-LoRa rule (anchor-locked heading). | Add the one clause to both notes; tighten the guard when next touched |

### Merge residuals (origin/main merged into the v0.11.0 main on 2026-10-11, merge a659304)

The 13 cloud-session commits of 2026-09-29 to 2026-10-02 (ELP stereo research, DEC-036, the
DEC-037–DEC-045 static-station redesign) were written against the v0.10 text and never saw the
v0.11 stage 5/6 work, which sat unpushed on the dev laptop until the merge. The merge kept both
sides; these rows are where they disagree. Flagged, not resolved, per §14's own rule.
`MR` = merge residual.

| ID | Where | What | Decision needed |
|---|---|---|---|
| MR-1 | `docs/DECISIONS.md` DEC-045 Implications | [CLOSED 2026-10-11 9864442] Corrected in place and dated; `tests/test_docs.py` gained an `RTCM fallback` pattern that flags the line as filed. Row as filed: Says the ESP32 LoRa boards "stay for the RTCM fallback (DEC-031)". DEC-031 was amended 2026-09-23: LoRa carries STATUS only and RTCM over LoRa is retired (S5-F1, CR-002). `tests/test_docs.py` let it through because "RTCM fallback" matches none of its FORBIDDEN patterns. | Amend DEC-045 to say the boards stay for STATUS telemetry (the Heltec's WiFi is the optional NTRIP client, DEC-032); add `RTCM fallback` to the guard with the usual allow-words |
| MR-2 | `docs/DECISIONS.md` DEC-039 Implications | [CLOSED 2026-10-11 9864442] Reworded in place and dated: supersedes the v0.11 rest-heading method, S3-R1 cited as closed, rest heading named as the fallback until resection exists. Row as filed: Says it "resolves the heading half of open item S3-R1". S3-R1 was closed 2026-09-23 (`dae5776`, this file): yaw comes from a per-sweep rest heading with WMM declination applied, not from Madgwick's magnetic frame. | Reword to "supersedes the v0.11 rest-heading method (S3-R1, closed) with target resection", and state that the rest heading stays the fallback until resection exists in `scripts/georef.py` |
| MR-3 | `docs/DECISIONS.md` DEC-041 Implications | [CLOSED 2026-10-11 9864442] Reworded in place and dated: the F9P stays on USB (`/dev/rover-f9p`), leaving the UARTs to the LD19, HWT906 and HoI laser. Row as filed: Says "the F9P moves to USB to free a UART". The v0.11 code already reads the F9P over USB: `config/default.toml` `[gnss].port = /dev/rover-f9p`, udev rule `deploy/udev/99-rover-f9p.rules`. Stale, not wrong. | Reword as "the F9P stays on USB (the case since v0.10), leaving the UARTs for the LD19, HWT906 and the HoI laser" |
| MR-4 | `src/rover/stepper.py`, `sweep.py`, `imu.py`, `camera.py`, `main.py`, `config.py`; `scripts/georef.py`; `tests/`; `tests/hardware/test_camera.py`; `CLAUDE.md` §7 pinout | **[RULED 2026-10-11, Brian: option 1.]** v0.11.0 is frozen as the mobile-rover baseline. The static station scanner (DEC-037–DEC-045) is built as a **separate v2 line**, not by rewriting these modules in place; it borrows what still applies (the `scripts/georef.py` export spine, config/logger/telemetry conventions, the docs guard harness). **Deferred (Brian, 2026-10-11): the v2 line does not start until v1 works** — gate: v1.0 field-validated per `docs/ROADMAP.md` success criteria (`deploy/SMOKE_CHECKLIST.md` passed on hardware, pre-field blockers S3-R2 and S5-R2 closed, outdoor RTK fix and repeatability measured). Until then DEC-037–DEC-045 stay documented-only; the form of the line (branch, package or repo) and its first stage plan are decided when the gate opens. No DEC-037+ code lands on this `main`. Row as filed: DEC-037–DEC-045 describe a different machine from the one v0.11.0 implements and tests: a static tripod scanner with a geared drive and AS5600 encoder, HWT906 on the base, two ELPs on a 75 cm tilt bar, step-and-scan, GCP/Scan modes — against v0.11's sweeping mast, A4988 direct drive, single MPU-9250 with Madgwick, picamera2. Measured 2026-10-11: about 4,100 code lines and 270 tests across the listed modules rest on the retired assumptions; `test_camera.py` still imports picamera2; DEC-040 itself flags the §7 pinout. Nothing is broken today because the redesign is documented, not implemented (CLAUDE.md §1 callout). | Rule before any DEC-037+ code lands: freeze v0.11.0 as the mobile-rover baseline and build the static scanner as a separate v2 line, or rewrite the listed modules in place under new stage plans. ROADMAP §3.4 and DEC-036 tests 11–14 gate the hardware side; this row gates the code side |

## How to use this file

- **Adding an item:** when you find a "rover side codes for X, sibling side
  doesn't have X yet" gap, record it here so future-you doesn't waste time
  searching for the missing piece.
- **Closing an item:** when the sibling PR lands, change Status to `✅`,
  add the sibling commit SHA, and on the next rover-docs pass, fold the
  cross-references into the relevant doc bodies (delete the "pending" caveats).
- **No silent deletes:** keep closed items here as historical record;
  prepend `[CLOSED YYYY-MM-DD]` to the title.
