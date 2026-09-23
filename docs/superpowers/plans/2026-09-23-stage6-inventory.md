# Stage 6 docs-drift inventory — LiDAR_Scanner_DIY @ 2b96251

Read-only. Ground truth = code at `main`@`2b96251` (src/rover/*.py, scripts/georef.py,
config/*.toml, deploy/*, firmware/esp32-rover/platformio.ini, pyproject.toml, tests/).

## Counts per doc

| Doc | Stale/false items |
|---|---:|
| CLAUDE.md | 17 |
| README.md | 4 |
| docs/ROADMAP.md | 12 |
| docs/ARCHITECTURE.md | 14 |
| docs/SPECIFICATIONS.md | 16 |
| docs/BASE_STATION_INTEGRATION.md | 14 |
| docs/HARDWARE.md | 10 |
| docs/ATTRIBUTION.md | 3 |
| docs/DECISIONS.md (scoped: DEC-013/015/031/032/033 + EPSG 6346 / RTCM-over-LoRa hits) | 9 |
| docs/V2_SLAM_CONCEPT.md (links only) | 1 |
| docs/README_ORIGINAL.md | 5 |
| deploy/SMOKE_CHECKLIST.md | 2 (gaps; 0 false claims found) |
| **Total** | **107** |

## Cross-doc facts — must be stated identically everywhere (single correct value)

1. **Version:** `src/rover/__init__.py:3` `__version__ = "0.10.0"` is the sole source (pyproject.toml uses `dynamic=["version"]` off it). Current code is **0.10.0**; the stage-6 close-out step bumps to **0.11.0** + tags `v0.11.0` — that bump has **not happened yet** (only git tag is still `v0.1.0`).
2. **Serial ports:** primary = udev stable symlinks `/dev/rover-lidar`, `/dev/rover-f9p`, `/dev/rover-esp32` (`deploy/udev/99-rover-*.rules`; `config/default.toml:20,49,69`). Raw ttys (`/dev/ttyUSB0`, `/dev/ttyACM0`, `/dev/ttyUSB1`) are the **pre-install fallback only**, never primary.
3. **EPSG codes (NAD83(2011) ftUS State Plane):** PA North = **6563**, PA South = **6565**. `6346` is NAD83(2011)/UTM zone 17N (**metric**, not State Plane) — never a PA-North value. NAVD88 vertical: **6360** (ftUS) / **5703** (metric). Geoid-transform source CRS: NAD83(2011) geographic 3D **EPSG:6319**. Source: `scripts/georef.py:180-194` (`ZONE_EPSG`, comment states the fix was made 2026-09-22), `:871` (`_NAVD88_VERTICAL`).
4. **LoRa:** `[lora].role` ∈ `{"status_tx_only", "disabled"}` only — **no RTCM-receive role exists**. `TYPE_RTCM_CHUNK`/`0x10` retired from the Python protocol 2026-09-23 (DEC-031 amended); value reserved, never encoded/decoded (`src/rover/lora_protocol.py:41-44`). Default `telemetry_interval_sec` = **10.0 s** (was 1.0), matching the base beacon cadence (`config/default.toml:75`). Radio profile is **SF7** only (`firmware/esp32-rover/platformio.ini:36`) — there is no SF9/RTCM_CHUNK case any more.
5. **Mast sweep (DEC-015 amended 2026-09-23):** **360° forward sweep, then a fast rewind** (never ±180° oscillation, never one-direction-forever). `sweep_deg=360.0`, `rewind_rpm=10.0`, `rest_before_sweep_sec=2.0` (`config/default.toml:32-34`; `src/rover/sweep.py`). `SCAN_REWINDING` telemetry state exists (`src/rover/lora_protocol.py:143`). **No home switch** — mast returns to step 0 at shutdown on a best-effort basis (`src/rover/main.py:452-491` `_return_home`; logs `returned_home`/`return_home_failed` events); a crash mid-sweep still leaves the mast un-homed (open backlog `S5-R3`).
6. **IMU mount:** `[imu].mount` = `"base"` (fixed body, **default**) | `"platform"` (turns with the mast) — a real config key now (`src/rover/config.py:122-129,514-515`; `config/default.toml:43`). Physical choice still undecided at the bench (`S3-R3`, open).
7. **Antenna lever arm:** `[calibration].antenna_offset_m` — LiDAR-centre→antenna-phase-centre offset, metres, platform frame at mast 0; optional, `None` by default (`src/rover/config.py:185-187`; `config/default.toml:114`).
8. **Hardware counts/naming (owner rulings 2026-09-22):** rover needs **one** ZED-F9P + **one** antenna (base unit belongs to the sibling Base-Station) — **D-005**. Board: **Heltec WiFi LoRa 32 V3** is the documented *target* (`firmware/esp32-rover/platformio.ini:11,26` `board = heltec_wifi_lora_32_V3`); the Muzi V3 clone is the pin-compatible *equivalent* — **D-017**. Rover GNSS hardware = SparkFun GPS-RTK-SMA (ZED-F9P) + u-blox ANN-MB-00 — same as the Base-Station (per `docs/superpowers/specs/2026-09-22-audit-remediation-design.md` §6a; not yet in any target doc).
9. **JSONL record formats:** LiDAR records are **columnar** (`angle[]`/`distance[]`/`intensity[]`) plus `mast_angle_deg`, `sweep`, `lidar_ms_start`, `lidar_ms_end` — never a per-point dict list (`src/rover/main.py:737-751`). IMU records are **one batched record per loop iteration** with parallel arrays `t[]`/`accel[][]`/`gyro[][]`/`mag[][]`/`orientation[][]` — never one sample per record (`src/rover/main.py:365-374`). GNSS records live **only** in `gnss*.jsonl`, never mirrored into `scan*.jsonl` (T1-053; `src/rover/logger.py:375-382`), and carry a `pdop` field. New event types: `sweep_start`, `sensor_disabled`, `returned_home`, `return_home_failed` (`src/rover/main.py`).
10. **metadata.json:** has a `session` block (profile/project_code/mission_tag/target_crs_epsg/units), a `geometry` block (imu_mount/antenna_offset_m/sweep_deg/rewind_rpm/rest_before_sweep_sec), optional `ntrip_stats`, plus `logger_degraded`/`dropped_records`/`lost_records`; `firmware_version` = live `rover.__version__` (currently `"0.10.0"`, never a hardcoded `"0.9.1"`). Source: `src/rover/logger.py:438-476`; `src/rover/main.py:966-976`.
11. **georef.py export outputs:** for a projected CRS, writes **both** `<prefix>_ellipsoidal.{ply,las}` and `<prefix>_navd88.{ply,las}`, plus `export/export.json`. Exit codes: **0** success/local-ENU, **1** no points, **3** NAVD88 unavailable or units/CRS mismatch (ellipsoidal files still written either way). Source: `scripts/georef.py:30-60` (docstring), `:1107-1179` (`main()`).
12. **status.json schema:** rover `STATUS_SCHEMA_VERSION = 2` (v2 adds `sensors_disabled`, `logger_degraded`, `pdop`; `battery_mv`/`lora_link_rssi`/`lora_link_snr` are optional and **omitted** from the payload when unmeasured, never a placeholder) — `src/rover/telemetry.py:37-54,102,154-165`. Sibling Base-Station's `STATUS_SCHEMA_VERSION` is now **10** (sibling `base-station/rtk_io.py:155`, read 2026-09-23 at e88c11b) — every doc currently says a stale v1/v7/v9 pairing.
13. **Config keys removed** (must not appear as live/documented): `[power]` (whole section), `[gnss].rtcm_profile`, `[gnss].survey_in_duration_sec`/`survey_in_accuracy_m`, `[imu].fusion_output_hz`, `[logging].format`. **Config keys that exist but are undocumented anywhere in SPECIFICATIONS.md §2.2:** `[session]` (all 5 keys), `[ntrip]` (all 7 keys), `[base_station_integration]` (all 4), `[telemetry]` (all 3), `[stepper].sweep_deg`/`rewind_rpm`/`rest_before_sweep_sec`, `[imu].mount`, `[lora].sync_word`/`role`, `[calibration].mag_offset`/`antenna_offset_m`. Source: `src/rover/config.py:49-321` + `config/default.toml`.
14. **Heading reference:** yaw comes from a **per-sweep rest-heading magnetometer reading** (mast home, before each sweep), converted from Madgwick's NWU world frame to true-north ENU via WMM 2025 declination (auto-computed from the session's GNSS origin using `pygeomag`) — **never** from GNSS (GNSS gives position only, no heading) and **never** from gyro integration during the sweep. Roll/pitch come from the IMU every scan. No declination available → heading labelled "magnetic"; no rest magnetometer data at all → "relative". GEOID18 grid install: **`python -m pyproj sync --file us_noaa_g2018u0.tif`** (works with pip-installed pyproj; used on the dev PC 2026-09-23) or PROJ's own **`projsync --file us_noaa_g2018u0.tif`** (named in the code's error text). Docs give both. Source: `scripts/georef.py:14-29,532-558,561-568,694-718`.
15. **Dependencies/extras:** `pyproject.toml` extras are `pi` (rpi-lgpio, picamera2, smbus2, pyserial, **pyubx2**), `dev` (pytest, ruff, pyubx2, **pygeomag**), `post` (laspy, pyproj, numpy, **pygeomag**). Ruff commands: `python -m ruff format src scripts tests` then `python -m ruff check src scripts tests`; config in `[tool.ruff]` (line-length 100, py311, select E/F/W/I/UP/B, ignore E501/B008).
16. **Sibling caster / session-sharing rule** (not yet in any target doc): the Base-Station's NTRIP caster serves one client at a time (sibling `NC-1`); interim rule (owner, 2026-09-23): **the drone and this rover never share a base session** (`CR-005`).

---

## CLAUDE.md (17)

1. `CLAUDE.md:3-7` — stale: "v0.10 — Base-Station integration overhaul (2026-05-23) ... freeze lifted to integrate ..." — correct: v0.10 overhaul complete 2026-05-30; five further remediation stages (hygiene→scan-geometry) merged 2026-09-22/23. Code: git log (`2b96251` tip, merges `167f4a2`,`7ef5b1e`,`dae5776`).
2. `CLAUDE.md:57-59` — stale: "Codebase | ⚠️ v0.10 overhaul in progress (telemetry, ntrip, gnss, esp32 firmware)" / "Current phase: v0.10 overhaul" — correct: overhaul long done; current phase is the audit-remediation campaign, stage 6 (docs). Code: `docs/superpowers/specs/2026-09-22-audit-remediation-design.md`.
3. `CLAUDE.md:55` — incomplete: "35 decisions (DEC-001–DEC-035)" doesn't note DEC-015/DEC-031 were amended 2026-09-23. Code: commits `0e375fa`, `13f6805`.
4. `CLAUDE.md:56` — stale: "Hardware NOT in hand | 2× ZED-F9P, 2× dual-band antennas ..." — correct: **one** F9P + one antenna needed rover-side (D-005). Code: spec §1.
5. `CLAUDE.md:80` — false: `main.py # orchestration (stub today)` — correct: 993-line full orchestrator (sweep planner, NTRIP fatal-abort, heading-settle wait). Code: `src/rover/main.py` (whole file).
6. `CLAUDE.md:83` — false: `gnss.py # ZED-F9P NMEA/UBX (Phase C — stub)` — correct: 534-line NAV-PVT/GGA fusion driver. Code: `src/rover/gnss.py`.
7. `CLAUDE.md:84` — stale label: `ntrip.py # Pi-side NTRIP client (Phase C — new)` — correct: 710-line client with fatal-error handling, GGA upload, chunked-encoding refusal. Code: `src/rover/ntrip.py`.
8. `CLAUDE.md:86` — false: `watchdog.py # stub` — correct: 222-line sd_notify + heartbeat-timeout implementation. Code: `src/rover/watchdog.py`.
9. `CLAUDE.md:76-94` — tree omits `_io.py`, `lora_protocol.py`, `sweep.py`, `config/telemetry-only.toml`, all of `deploy/`, `docs/CROSS_REPO_BACKLOG.md`, `docs/ATTRIBUTION.md`, `docs/V2_SLAM_CONCEPT.md`, `docs/AUDIT_super_20260922_1810.md`, `docs/superpowers/`; lists 2 of 22 test files. Code: repo tree / `tests/*.py` (22 files).
10. `CLAUDE.md:71` — incomplete: "Deps: rpi-lgpio, picamera2, smbus2, pyserial" omits `pyubx2` and the `[dev]`/`[post]` extras (pytest, ruff, pygeomag, laspy, pyproj, numpy). Code: `pyproject.toml:16-36`.
11. `CLAUDE.md:116-139` — §6 table has no DEC-035 row (referenced by header/§2) and no "amended" flag on the DEC-031 row (LoRa fallback retired). Code: `docs/DECISIONS.md` DEC-035; `src/rover/lora_protocol.py:27-28`.
12. `CLAUDE.md:141-149` — stale: lists raw ttys (`/dev/ttyACM0`,`/dev/ttyUSB0`,`/dev/ttyUSB1`) as *the* serial ports. Correct: udev symlinks are primary (cross-doc fact #2). Code: `config/default.toml:18-20,47-49,67-69`; `deploy/udev/99-rover-*.rules`.
13. `CLAUDE.md:153-154` — needs a caveat: firmware LoRa-RTCM-relay wiring description is unaffected by DEC-031's amendment on the Python side, but should note the Pi-side `[lora].role` no longer offers an RTCM-receive value. Code: `config/default.toml:76`.
14. `CLAUDE.md:158-172` — §8 omits `[imu].mount` and `[calibration].antenna_offset_m`, both added in stage 5. Code: `src/rover/config.py:122-129,185-187`.
15. `CLAUDE.md:171-172` — stale: "Extrinsic calibration ... is TBD for v1.0" doesn't note the antenna-offset mechanism now exists in config (value still unmeasured/None, but the slot is real). Code: `config/default.toml:114`; `scripts/georef.py:686-689,754-757`.
16. No version anchor anywhere tying the doc to the code's actual `0.10.0` (or the pending `0.11.0` bump). Code: `src/rover/__init__.py:3`.
17. `CLAUDE.md:1-8` header block conflates the 2026-05-23 v0.10 kickoff with "now" — needs the full rewrite the spec calls for (overhaul complete, campaign = v0.11, phase = v1.0 field validation).

## README.md (4)

1. `README.md:52-58` — stale: "v0.10 — Base-Station integration overhaul. The v0.9.2 self-contained architecture has been lifted ... Implementation proceeds in phases" — correct: overhaul complete 2026-05-30; 5 further remediation stages merged since. Code: git log; `docs/superpowers/plans/*`.
2. `README.md:45-49` — incomplete: Quick Start hardware-diagnostics list has 4 scripts, omits `python -m tests.hardware.test_ntrip`. Code: `tests/hardware/test_ntrip.py` exists (5 files total).
3. `README.md:62-71` — Documentation index (7 entries) omits `docs/V2_SLAM_CONCEPT.md` (still zero inbound links anywhere — T3-002 not done). Code: `docs/V2_SLAM_CONCEPT.md` exists, 489 lines.
4. No mention of the audit-remediation campaign or its stage completions — per spec §7 "status rewritten." (Confirmed correct/unchanged: the Licence section, line 85, already matches ATTRIBUTION.md's 2026-09-22 resolution — not a finding.)

## docs/ROADMAP.md (12)

1. `docs/ROADMAP.md:3-4` — stale header: "v0.10 — current (deep-alignment overhaul applied 2026-05-30)" — 5 further stages have merged since (git tip `2b96251`).
2. `docs/ROADMAP.md:62` — stale: "### v0.10 Deep-Alignment Overhaul (in progress, 2026-05-30)" — it's complete.
3. `docs/ROADMAP.md:74` — stale: "**D** | Doc refresh ... | 🔄 in flight" — should be ✅.
4. `docs/ROADMAP.md:75` — stale: "**E** | LoRa frame v2 callout ... | ⏳ pending" — the callout already exists in `BASE_STATION_INTEGRATION.md:171-192` — should be ✅.
5. `docs/ROADMAP.md:87` — stale: "Order 2× ZED-F9P + antennas + 3.3V regulator + batteries" — correct: **one** F9P + one antenna (D-005).
6. `docs/ROADMAP.md:20` — false: "LoRa RTCM fallback (DEC-031) | Off-network operation supported via Base-Station Heltec → rover ESP32 → F9P UART2" — DEC-031 amended 2026-09-23; no RTCM path exists over LoRa. Code: `src/rover/lora_protocol.py:41-44`.
7. `docs/ROADMAP.md:153` — stale risk row: "LoRa bandwidth insufficient for RTCM" — moot; RTCM never travels over LoRa now.
8. `docs/ROADMAP.md:187` — ambiguous/stale: "Remote command/control via T-Deck" — T-Deck ownership moved to the Base-Station under DEC-033; rover doesn't own T-Deck firmware.
9. `docs/ROADMAP.md:132` — stale "open TBD": "Exact step interval | 1° vs 1.5° vs 2°" — already decided: `step_interval_deg = 1.575°`. Code: `config/default.toml:28`.
10. `docs/ROADMAP.md:135` — stale "open TBD": "Log rotation strategy: Size-based vs time-based" — already decided/implemented: size-based (`rotate_size_mb`). Code: `src/rover/config.py:166`.
11. `docs/ROADMAP.md:278-284` — Changelog ends at v0.9.2; missing v0.10 (2026-05-30) and the 2026-09-22/23 remediation-campaign rows.
12. `docs/ROADMAP.md:262-274` — §8 "Immediate Next Actions" still lists 2026-03-22-era startup tasks ("Order ZED-F9P...", "Set up Git repository", "Start config.py module") — all long done; per spec should be the on-Pi smoke checklist + first field session.

## docs/ARCHITECTURE.md (14)

1. `docs/ARCHITECTURE.md:3-10` — stale header/callout: "v0.10 — in overhaul", "Last Updated: 2026-05-23", "The rover is being reframed ..." — this is the doc the 2026-09-22 audit flagged (D-013) as never restamped even at Stage D; 5 more stages have landed since.
2. `docs/ARCHITECTURE.md:56-67,90-92` — false: block diagram/table depict ESP32 "LoRa Rx" decoding RTCM_CHUNK → F9P UART2 as a live path. Code: `src/rover/lora_protocol.py:41-44` (retired); `src/rover/config.py:565-566` (role enum has no RTCM value).
3. `docs/ARCHITECTURE.md:94-137` — §2.3 "Fallback — LoRa-Relayed RTCM" (lines 115-133) describes a path that no longer exists on the Pi/config side; needs rewrite to "LoRa is status-only; NTRIP is the sole RTK path; firmware relay mode pending removal (S5-F1)."
4. `docs/ARCHITECTURE.md:91` — false table row: "RTK ingress (fallback) | Rover ESP32 LoRa Rx | Decode RTCM_CHUNK ... → F9P UART2."
5. `docs/ARCHITECTURE.md:136-137` — false: "`[lora].role` chooses whether the rover ESP32 acts as RTCM-Rx, STATUS/LINK-Tx only, or is fully disabled" — correct: `role` ∈ `{status_tx_only, disabled}` only. Code: `config/default.toml:76`.
6. `docs/ARCHITECTURE.md:296` — stale table row: "Base → Rover (LoRa fallback) | 915 MHz | ... | RTCM_CHUNK (LoRa frame v2 type 0x10)."
7. `docs/ARCHITECTURE.md:299-311` — §6.3 LoRa Parameters text still frames RTCM_CHUNK-at-SF9 as a live case.
8. `docs/ARCHITECTURE.md:413` — false: "Motor stall | Current sense or timeout | Pause scan, log error" — no current-sensing exists; real behavior is a 5-failure `_SensorGate` trip + `SCAN_ERROR`. Code: `src/rover/main.py:313-346,667-671`.
9. `docs/ARCHITECTURE.md:414` — false: "Storage full | Disk space monitor | Stop logging, alert via LoRa" — no disk monitor or LoRa alert exists; real behavior is `SessionLogger` catching the flush exception, setting `degraded`, counting `lost_records`. Code: `src/rover/logger.py:220-227,327-339`.
10. `docs/ARCHITECTURE.md:409` — stale framing: "LoRa link loss | ... | Continue logging locally | Auto-resume on reconnect" — conflates the old RTCM-fallback meaning; LoRa now only carries STATUS/LINK telemetry.
11. `docs/ARCHITECTURE.md:411` — imprecise: "RTK degradation | ... | Log with degraded accuracy flag" — no such flag field exists; real signal is `fix_type`/`rtk_age_s`.
12. `docs/ARCHITECTURE.md:438-474` — §10.2/10.3 transform chain/calibration table omit mount rotation (`R_z(mast_angle)`), the mount-frame IMU handling (`[imu].mount`), and the per-sweep rest-heading yaw model entirely. Code: `scripts/georef.py:14-29,617-636,727-757`.
13. `docs/ARCHITECTURE.md:484,489` — wrong: "e.g., EPSG `6346` for PA-N" / "Session-config (e.g., `6346` ft-US)" — 6346 is UTM 17N (metric); correct PA-North = 6563 (cross-doc fact #3). Code: `scripts/georef.py:180-194`.
14. `docs/ARCHITECTURE.md` (whole doc) — no mention of the sibling's single-client caster rule / drone-rover session-sharing rule (cross-doc fact #16), nor of the new `telemetry_interval_sec=10.0` default in §4's channel table.

## docs/SPECIFICATIONS.md (16)

1. `docs/SPECIFICATIONS.md:3-4` — stale header, same "2026-05-30 current" pattern.
2. `docs/SPECIFICATIONS.md:20` — stale: lists `RTCM_CHUNK` as a still-current LoRa frame v2 type. Code: `src/rover/lora_protocol.py:41-44` (retired).
3. `docs/SPECIFICATIONS.md:34` — false: `File Location: /home/pi/rover/config.toml` — correct: `/etc/rover/config.toml` / `/etc/rover/telemetry-only.toml`. Code: `deploy/install.sh:175-186`; `deploy/systemd/rover.service:20`.
4. `docs/SPECIFICATIONS.md:39-113` — §2.2 "Complete Configuration Schema" is a stale, hand-copied snapshot: missing `[session]`, `[ntrip]`, `[base_station_integration]`, `[telemetry]`, `[calibration]` entirely; shows raw-tty ports; missing `[stepper].sweep_deg/rewind_rpm/rest_before_sweep_sec`; `[imu]` still has removed key `fusion_output_hz` and lacks `mount`; `[gnss]` still has removed keys `rtcm_profile`/`survey_in_*`; `[lora].spreading_factor=9` (real value 7), missing `sync_word`/`role`, `telemetry_interval_sec=1.0` (real default 10.0); `[logging].format="jsonl"` (key removed, format is unconditionally JSONL) and `output_dir=/home/pi/rover/data` (real default `/var/lib/rover/data`); whole `[power]` section shown though removed from code. Code: `src/rover/config.py:49-321`; `config/default.toml`.
5. `docs/SPECIFICATIONS.md:131-160` — §3.1 "ESP32 LoRa (Rover) — RTCM Receiver" + LED table describes the deferred/legacy `lora_rtcm_relay` firmware mode as the unqualified current design; needs the "pending retirement, S5-F1" caveat and a rewrite from `firmware/esp32-rover/README.md` per spec §7.
6. `docs/SPECIFICATIONS.md:162-208` — §3.2/§3.3 describe the sibling's Base-Station ESP32 and T-Deck hardware (owned by `arm-drone-lidar-workflow`) as if in scope here; spec §7 calls for reducing to a pointer + CR-001..003.
7. `docs/SPECIFICATIONS.md:210-224` — §3.4 module table omits `ntrip.py`, `lora_protocol.py`, `_io.py`, `sweep.py`.
8. `docs/SPECIFICATIONS.md:250-274` — §4.2.1 LiDAR record example is the obsolete per-point-dict-list shape; real format is columnar with `mast_angle_deg`/`sweep`/`lidar_ms_start`/`lidar_ms_end` (cross-doc fact #9). Code: `src/rover/main.py:737-751`.
9. `docs/SPECIFICATIONS.md:276-296` — §4.2.2 IMU record example is one-sample-per-record; real format is a batched record with parallel arrays. Code: `src/rover/main.py:365-374`.
10. `docs/SPECIFICATIONS.md:298-326` — §4.2.3 GNSS record example missing the `pdop` field. Code: `src/rover/main.py:771-786`; `src/rover/gnss.py:107`.
11. `docs/SPECIFICATIONS.md:363-372` — §4.2.5 Event Types list missing `sweep_start`, `sensor_disabled`, `returned_home`, `return_home_failed`.
12. `docs/SPECIFICATIONS.md:378-392` — §4.3 metadata.json example: `"firmware_version": "0.9.1"` (should reflect live `rover.__version__`, currently 0.10.0); missing `session`, `geometry`, `ntrip_stats`, `logger_degraded`, `dropped_records`, `lost_records`; shows `total_steps`/`total_scans`/`total_images`/`gnss_fix_type_max` fields the real writer never emits. Code: `src/rover/logger.py:438-476`; `src/rover/main.py:966-976`.
13. `docs/SPECIFICATIONS.md:421-432` — §5.4 calibration example missing the two new keys `mag_offset` and `antenna_offset_m`. Code: `src/rover/config.py:178-187`; `config/default.toml:108-114`.
14. `docs/SPECIFICATIONS.md:448-454` — §6.2 lists raw ttys as *the* serial ports (same issue as CLAUDE.md item 12).
15. `docs/SPECIFICATIONS.md:479-497` — §7.1/§7.2 data-rate/storage tables not recomputed for the columnar record format (per spec §7 "recomputed").
16. `docs/SPECIFICATIONS.md:499-507` — §7.3 LoRa Bandwidth Budget entirely stale: "STATUS | 1 Hz" (now 10 s cadence), "LINK | 0.2 Hz" (LINK is not emitted by the rover at all — `publish_link()` removed, S2-R2/T1-026), "RTCM (robust) | Continuous | ~800 B/s" (no RTCM over LoRa), total computed against SF9 (real profile is SF7). Code: `src/rover/telemetry.py:308-372`; `firmware/esp32-rover/platformio.ini:36`.

## docs/BASE_STATION_INTEGRATION.md (14)

1. `docs/BASE_STATION_INTEGRATION.md:5` — stale: "Last Updated: 2026-05-23" — unchanged since before even Stage E (2026-05-30), let alone the 2026-09 stages.
2. `docs/BASE_STATION_INTEGRATION.md:29-33,75-92` — false: the whole "Fallback — LoRa-Relayed RTCM" path (§2.2) and its lead-in; DEC-031 amended 2026-09-23. `CR-002` (the sibling transmitter this section depends on) is now marked "❌ Not needed" in `docs/CROSS_REPO_BACKLOG.md:60`.
3. `docs/BASE_STATION_INTEGRATION.md:108-130` — stale example: `"schema_version": 1`; missing v2 fields `sensors_disabled`/`logger_degraded`/`pdop`; shows `battery_mv`/`lora_link_rssi`/`lora_link_snr` as always-present instead of omitted-when-None. Code: `src/rover/telemetry.py:37-54,102,154-165`.
4. `docs/BASE_STATION_INTEGRATION.md:133` — stale: "currently v7 in base, v1 in rover" — correct: rover v2, sibling v10 (cross-doc fact #12).
5. `docs/BASE_STATION_INTEGRATION.md:157` — stale: "Cadence configurable via `[lora].telemetry_interval_sec` (default `1.0`)" — real default is **10.0**. Code: `config/default.toml:75`.
6. `docs/BASE_STATION_INTEGRATION.md:152,167` — dangling ref: "the original Appendix C in `CLAUDE.md`" — CLAUDE.md has no appendices. Same dangling text also still lives in `src/rover/gnss.py:96` and `src/rover/lora_protocol.py:4` (code comments, not part of the stage-6 doc list but worth fixing alongside). Correct target: this doc's own §3.3/§4 + `SPECIFICATIONS.md` §4.2 (per audit D-011's own fix direction).
7. `docs/BASE_STATION_INTEGRATION.md:171-192` — "Reality check" callout only covers the Stage-E (2026-05-30) v1/v2 firmware gap; needs a further note for the 2026-09-23 DEC-031 amendment (LoRa is status-only Python-side regardless of sibling firmware version).
8. `docs/BASE_STATION_INTEGRATION.md:218` — stale table row: `0x10 | RTCM_CHUNK | base → rover | ...` still listed live; code marks it retired/reserved. Code: `src/rover/lora_protocol.py:41-44`.
9. `docs/BASE_STATION_INTEGRATION.md:222-234` — stale: "Spreading Factor | 7 (DISPLAY/STATUS/LINK) or 9 (RTCM_CHUNK if range > throughput)" and the SF9 paragraph below — only SF7 exists now. Code: `firmware/esp32-rover/platformio.ini:36`.
10. `docs/BASE_STATION_INTEGRATION.md:252-253` — **wrong**: "PA North | `6346`" / "PA South | `6347`" — correct: PA North=6563, PA South=6565 (cross-doc fact #3). Code: `scripts/georef.py:180-194`.
11. `docs/BASE_STATION_INTEGRATION.md:289-290` — stale: cites `arm-drone-lidar-workflow/base-station/docs/lidar-rover-integration.md`, which doesn't exist at the sibling's tip (only `_archive/`); should be reworded as pending, citing `CR-004`.
12. `docs/BASE_STATION_INTEGRATION.md:300` — false: "LoRa link loss (fallback mode) | No RTCM_CHUNK frame for 10 s | Log `event=lora_rtcm_loss`; F9P degrades to FLOAT/3D" — no such event string exists in `main.py`'s event list, and the whole mode is retired.
13. `docs/BASE_STATION_INTEGRATION.md` (whole doc) — missing the sibling single-client-caster / no-shared-session rule (cross-doc fact #16) — this is the natural home for it and it's absent.
14. `docs/BASE_STATION_INTEGRATION.md:311` — §8 cross-reference row "Decision records | DEC-030..DEC-034" should extend to DEC-035 and flag the 2026-09-23 DEC-031 amendment.

## docs/HARDWARE.md (10)

1. `docs/HARDWARE.md:3-4` — stale header, same "2026-05-30 current" pattern; doesn't reflect the 2026-09-22 D-005/D-017 rulings that directly affect this doc.
2. `docs/HARDWARE.md:6-9` — top callout omits the D-005 (F9P count) and D-017 (Heltec/Muzi naming) rulings, both of which contradict §1.1/§6/§7 below.
3. `docs/HARDWARE.md:31` — stale: "ZED-F9P × 2 needed (one for the Base-Station Pi, one for this rover)" — correct: **one**, rover-side only (D-005).
4. `docs/HARDWARE.md:32` — stale: "Antennas ... × 2 needed" — same halving.
5. `docs/HARDWARE.md:255` — stale: "Quantity Required: 2 (one base, one rover)" (F9P section).
6. `docs/HARDWARE.md:274` — stale: "Quantity Required: 2" (antenna section).
7. `docs/HARDWARE.md:246` — generic vendor list ("SparkFun GPS-RTK2 Board / ArduSimple simpleRTK2B / Beitian BN-880Q") doesn't name the actually-decided hardware: SparkFun GPS-RTK-SMA (ZED-F9P) + u-blox ANN-MB-00 (cross-doc fact #8).
8. `docs/HARDWARE.md:280` — stale naming: "### 7.1 Muzi ESP32 LoRa V3 (SX1252) — Rover" — has it backwards; Heltec WiFi LoRa 32 V3 is the documented target (D-017). Code: `firmware/esp32-rover/platformio.ini:11,26`.
9. `docs/HARDWARE.md:292-303` — describes the firmware's `lora_rtcm_relay` mode without flagging it as pending retirement (backlog `S5-F1`) and inconsistent with the Pi-side `[lora].role` enum, which no longer offers an RTCM-receive value.
10. `docs/HARDWARE.md:451` — table says IMU mount is "Fixed to rotating platform | 🔲 TBD"; code's default assumption is `[imu].mount = "base"` (fixed BODY) — the doc's stated default and the code's default disagree; physical choice is still open per `S3-R3`. Code: `src/rover/config.py:129`; `config/default.toml:43`.

## docs/ATTRIBUTION.md (3)

1. `docs/ATTRIBUTION.md:21` — unsupported: "If the Unitree L2 path is adopted (retiring DEC-015 through DEC-017 ...)" — no DEC/roadmap entry records an L2 path; `docs/V2_SLAM_CONCEPT.md` mentions only L1 (line ~67). Needs a citation added there or the sentence dropped (D-009).
2. `docs/ATTRIBUTION.md:86` — false: lists "Open3D" among dependencies — it appears nowhere in `pyproject.toml` or the codebase, only as a future idea in `V2_SLAM_CONCEPT.md`. Code: `pyproject.toml:11,17-36`.
3. `docs/ATTRIBUTION.md` (whole doc) — the Project Lineage table and v0.9.x version history from `docs/README_ORIGINAL.md` have not been migrated in (spec §7 stage-6 action; T3-001 still `fix`, not `done`; confirmed no `docs/archive/` dir exists).

## docs/DECISIONS.md — scoped (9)

1. `docs/DECISIONS.md:439-440` (DEC-013 Implications) — stale: "Indoor scans rely on gyro (drift over time)" / "Outdoor scans use GNSS-derived heading" — neither is true under the new heading model: yaw is never gyro-integrated during a sweep, and GNSS never supplies heading (position only). Code: `scripts/georef.py:646-651,694-718`; `src/rover/main.py:596-613`.
2. `docs/DECISIONS.md:481-498` (DEC-015) — superseded, not flagged: decision/implications still say "±180° rotation or full rotation with reset pause"; amended 2026-09-23 to "360° forward, then rewind" (commit `0e375fa`). Code: `src/rover/sweep.py`; `config/default.toml:32`.
3. `docs/DECISIONS.md:1248` — Decision Index row for DEC-015 carries no "amended" flag (unlike the DEC-005/006/010 rows, which do say "superseded by ...").
4. `docs/DECISIONS.md:999-1002,1021-1022` (DEC-031) — superseded, not flagged: "LoRa-relayed RTCM is retained as the off-network fallback" and "`[lora].role` configures whether LoRa carries RTCM-Rx in addition to STATUS/LINK-Tx" — both wrong post-amendment (2026-09-23, commit `13f6805`). Code: `src/rover/lora_protocol.py:27-28,41-44`; `src/rover/config.py:140-150,565-566`.
5. `docs/DECISIONS.md:1264` — Decision Index row for DEC-031 carries no "amended" flag.
6. ⚠ **Anchor-stability risk:** `docs/CROSS_REPO_BACKLOG.md:30,54` link to `DECISIONS.md#dec-031-ntrip-primary-rtk-with-lora-fallback-supersedes-dec-005`, an anchor generated from DEC-031's current heading text. Renaming that heading to reflect the amendment without updating those two links will silently break them (GitHub anchors are heading-text-derived, no redirect). Recommend: keep the heading text, add an "amended" note in the body, OR update both backlog links in the same change.
7. `docs/DECISIONS.md:1113-1114` (DEC-033 Implications) — stale: "sibling is at v9, rover at v1" — correct: rover is now v2, sibling now v10 (cross-doc fact #12). Code: `src/rover/telemetry.py:37-54,102`.
8. `docs/DECISIONS.md:1159` (DEC-034 Implications) — **wrong** example: "NAD83(2011) ft-US codes (6346 etc.)" — 6346 is UTM 17N (metric), not a State Plane ftUS code; correct examples PA North=6563/PA South=6565. Code: `scripts/georef.py:175-194` (comment documents this exact former bug + its 2026-09-22 fix).
9. *(bonus, technically outside the DEC-013/015/031-033 + EPSG-6346/RTCM-over-LoRa scope, but directly duplicates item 7 above)* `docs/DECISIONS.md:1213` (DEC-035 Implications) — stale: "`STATUS_SCHEMA_VERSION = 1`" — code constant is now `2`.

## docs/V2_SLAM_CONCEPT.md — links only (1)

1. Zero inbound links from any doc: neither `README.md`'s Documentation index nor `CLAUDE.md`'s doc-locator table link to this file — confirmed by a repo-wide grep (only the audit report and the remediation spec ever name it). This is audit finding **T3-002**, still dispositioned `fix`, not `done`. The file itself has no outbound markdown links to check for breakage.

## docs/README_ORIGINAL.md (5)

1. Whole file — still at `docs/README_ORIGINAL.md`; **not** moved to `docs/archive/README_v0.9.2.md` with a supersession banner (spec §7; audit **T3-001**, still `fix` not `done`). Confirmed: no `docs/archive/` directory exists anywhere in the repo.
2. `docs/README_ORIGINAL.md:5-6` — "Status: Active Development — Architecture Frozen (v0.9.2)" / "Last Updated: 2026-02-22" — superseded twice over (v0.10 overhaul, then the 2026-09 campaign); belongs under a supersession banner, not a live edit.
3. `docs/README_ORIGINAL.md:142` — "License: TBD" — superseded; LICENSE is CC BY-NC-SA 4.0 as of 2026-09-22 (`docs/ATTRIBUTION.md` resolution log).
4. `docs/README_ORIGINAL.md:43-78` — System Overview diagram/Design Philosophy describe the v0.9.2 self-contained dual-Pi + T-Deck architecture, fully superseded by DEC-030–035. Archive-don't-edit, same as items 2-3.
5. `docs/README_ORIGINAL.md:95-137` — its unique content (Project Lineage table, PiLiDAR comparison table, v0.9.x version history) has **not** been migrated into `docs/ATTRIBUTION.md` yet (confirmed: no such table exists there) — this is the substantive part of T3-001 still outstanding.

## deploy/SMOKE_CHECKLIST.md (2 gaps; 0 false claims)

Every existing item (watchdog log strings, `output_dir` paths, install.sh's "kept $ETC_DIR/config.toml" message, the GPIO-backend detection step) was cross-checked against current code and **matched** — no false/stale claims found here.

1. Gap tied to an open backlog row: `docs/CROSS_REPO_BACKLOG.md` **S5-R3** explicitly calls for a stage-6 addition here — "Home by hand before each session (stage 6: `deploy/SMOKE_CHECKLIST.md`)" — because there's no home switch and a crash/power-loss mid-sweep leaves the mast un-homed for the next session (`src/rover/main.py:452-491`). No checklist item currently tells the operator to do this.
2. Gap (not required by any specific backlog row, but the checklist predates stage 5): no item exercises the 360°-then-rewind sweep, the up-to-60-s sweep-0 heading-settle wait (which runs past the 30 s default watchdog timeout but heartbeats through it — `src/rover/main.py:388-449`), or the `SCAN_REWINDING` telemetry state.

---

## §7 "already done?" check

- **"15 out-of-scope rows appended to CROSS_REPO_BACKLOG"** — **DONE** (already present, filed in an earlier stage, not stage 6 itself): `docs/CROSS_REPO_BACKLOG.md:127-151` "## Rover-side deferred (from the 2026-09-22 super-audit)" holds exactly this set (T1-018/021/024/028/037/038/040/045/048, D-016/018, T1-034/035/051, T1-042-firmware-half), with `S5-F1` added later in the same section. Two rows (T1-024, D-016) are since marked `[CLOSED ...]` inline per the file's own "no silent deletes" rule rather than removed.
- **"README_ORIGINAL → docs/archive"** — **NOT DONE**. Confirmed: `docs/README_ORIGINAL.md` still lives at its original path; no `docs/archive/` directory exists (Glob returned nothing).

## Audit report rows (docs/AUDIT_super_20260922_1810.md) still `fix`/`simplify`

**Owned by stage 6 (docs, or a repo-level close-out action):** D-001, D-002, D-003, D-004, D-005, D-006, D-007, D-009, D-010, D-011, D-012, D-013, D-014, D-015, D-017, D-019 (tag `v0.11.0` — repo action, not a markdown edit), T3-001, T3-002. (18 rows.)

**NOT owned by stage 6** (firmware, deferred to a hardware session per the design spec §1 — PlatformIO not installed here): T1-034 (`fix`), T1-035 (`fix`), T1-051 (`simplify`). (3 rows.)

**`track`, not `fix`/`simplify`, and outside this repo:** D-018 (workspace-level `../CLAUDE.md` signpost row) — not stage 6's concern.

**Already `done`** (for contrast, correctly excluded above): D-008, D-016, T3-003, plus all T1-0xx/T2-0xx code rows except the `defer`-dispositioned low-severity ones (T1-018, 021, 028, 037, 038, 040, 045, 048) and T1-024 (closed via stage 4, marked inline in the backlog).
