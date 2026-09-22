# Audit Remediation Campaign — Design

**Date:** 2026-09-22 · **Status:** approved in conversation, awaiting written review
**Source:** `docs/AUDIT_super_20260922_1810.md` (86 findings, triaged 2026-09-22 18:20)
**Outcome:** the tree boots under systemd on a fresh Pi, exports a real 3D point cloud in the right units, the docs describe the code as it is, and the licence is compliant. Tagged `v0.11.0`.

## 1. Scope

**In scope (72 findings):** every row dispositioned `fix` or `simplify` in the audit report, minus the firmware rows.

**Out of scope, recorded in the backlog (15 findings):**
- `defer` (9): T1-018, T1-021, T1-024, T1-028, T1-037, T1-038, T1-040, T1-045, T1-048.
- `track` (2): D-016 (fixed opportunistically in stage 2 if trivial), D-018 (workspace signpost, outside this repo).
- Firmware, deferred to a hardware session because PlatformIO is not installed here (4): T1-034, T1-035, T1-051, and the firmware half of T1-042.

**Owner rulings that shape the design:**
- Relicense to CC BY-NC-SA 4.0 (D-008).
- Rover needs one ZED-F9P and one antenna; the base unit belongs to the sibling Base-Station (D-005).
- Both a Heltec WiFi LoRa 32 V3 and a Muzi V3 clone are owned; Heltec is the documented target, Muzi the pin-compatible equivalent (D-017).
- Default session output directory is `/var/lib/rover/data` with full systemd hardening kept; other paths need a documented drop-in (T2-001).
- LD19 scan plane is vertical; the stepper rotates it about body Z (T1-007).
- IMU mounting location is undecided; the design assumes the fixed body and HARDWARE.md records the alternative.
- Tag once at the end as `v0.11.0`; the May tip is not retro-tagged.

## 2. Structure

Five thematic stages in dependency order. Each stage is a branch off `main`, merged `--no-ff`, with the test suite, `ruff check` and `ruff format --check` clean at every merge. A stage can be stopped after; the tree is better at every merge point.

| Stage | Branch | Closes |
|---|---|---|
| 1 Hygiene and identity | `fix/stage1-hygiene` | T1-036, T1-054, T1-055, T1-056, T3-003, D-008 |
| 2 First-boot blockers | `fix/stage2-first-boot` | T1-001, T1-002, T1-003, T1-005, T1-006, T1-011, T1-027, T1-029, T1-032, T1-033, T2-001, T2-002, T2-003, T2-004, part of T2-005 |
| 3 Data pipeline | `fix/stage3-pipeline` | T1-007, T1-008, T1-009, T1-010, T1-012, T1-013, T1-014, T1-015, T1-016, T1-017, T1-039, T1-043, T1-044, T1-050, T1-052, `[calibration].mag_offset` from T1-041 |
| 4 Comms and config | `fix/stage4-comms-config` | T1-004, T1-019, T1-020, T1-022, T1-023, T1-025, T1-026, T1-030, T1-041, T1-042 (Python), T1-046, T1-047, T1-049, T1-053, rest of T2-005, T2-006, T2-007, T2-008 |
| 5 Docs and close-out | `fix/stage5-docs` | D-001 to D-015, D-017, D-019, T3-001, T3-002; backlog entries for the 15 out-of-scope rows |

## 3. Stage 1 — Hygiene and identity

1. **`.gitattributes`**: `* text=auto eol=lf`; explicit `eol=lf` for `*.sh`, `*.service`, `*.rules`, `*.toml`, `deploy/**`; `binary` for `*.png`, `*.jpg`. Run `git add --renormalize .` and confirm an empty diff (index is already LF). Add one line to the `install.sh` header: the Pi must clone, not copy.
2. **Ruff**: `[tool.ruff]` in `pyproject.toml` with `line-length = 100`, `target-version = "py311"`, double quotes, `select = ["E", "F", "W", "I", "UP", "B"]`, `E501` handled by the formatter. Two commits: config, then a format-only commit (`ruff format` plus `ruff check --fix` for safe rules) so `git blame` can skip it. CLAUDE.md §5 names the two commands.
3. **Version**: `rover/__init__.py` is the single source at `0.10.0`. `pyproject.toml` uses `dynamic = ["version"]` reading `rover.__version__`. `logger.py` and `ntrip.py` import it. A test asserts the package version, the metadata `firmware_version` and the NTRIP user agent agree.
4. **Relicense**: `LICENSE` becomes the CC BY-NC-SA 4.0 legal code. `pyproject.toml` gains `license = "CC-BY-NC-SA-4.0"`. README gains Licence and Acknowledgements sections naming PiLiDAR, its author, the upstream URL and licence, and stating this project modifies the original. The `ATTRIBUTION.md` checklist is ticked with the commit SHA.
5. **`.gitignore` and `.gitkeep`**: drop the dead `/tmp/lg_*` line, add `.remember/` and `_graveyard/`, `git rm scripts/.gitkeep`.

## 4. Stage 2 — First-boot blockers

**Goal:** `sudo deploy/install.sh` on a fresh Bookworm Pi yields a `rover.service` that reaches READY, survives a sensor unplug, and stops cleanly.

- **Watchdog**: default timeout callback flushes logging handlers then calls `os._exit(2)`. `run()` always constructs and starts the Watchdog; `start()` already sends READY and skips the monitor when disabled. `_sd_notify` keeps one connected datagram socket per process.
- **Fail-soft loop**: every sensor read site in `_scan_loop` catches `(RuntimeError, TimeoutError, OSError)`; a per-sensor consecutive-failure counter marks the driver unavailable after 5 failures with one WARNING. Settle uses `stop_event.wait`.
- **Teardown**: telemetry, NTRIP and watchdog construction move inside the existing try/finally so any constructor failure still writes `scan_abort`, stops sensors and closes the logger. `ntrip_stats_holder` is removed; `_scan_loop` takes the client and reads `.stats`.
- **Camera**: `jpeg_quality` set through `self._cam.options["quality"]` in `start()`; the unit test mocks Picamera2 with `autospec`.
- **GNSS NAV-PVT**: use pyubx2's scaled `lat`, `lon`, `hMSL`, `pDOP`, `carrSoln` directly; the test fixture is a real pyubx2 parse.
- **Logger**: `_periodic_flush` catches exceptions, logs once, sets `degraded`, always reschedules. Queue `maxsize = 10000`, drop-oldest on overflow. `os.fsync` at `stop()` and every 10th flush. `metadata.json` via `atomic_write_json`. `save_images = false` gates capture in `main.py`; unused `images_dir` removed.
- **Config**: `_validate` raises when `[ntrip].enabled` with `client_location = "pi"` and `[gnss].enabled = false`.
- **Deploy**: both units gain `StateDirectory=rover`, `RuntimeDirectory=rover`, `PrivateTmp=true`; `output_dir` defaults to `/var/lib/rover/data` in both TOMLs. `install.sh` copies both TOMLs to `/etc/rover/` without overwriting, rsyncs `src/rover` to `/opt/rover/src`, restarts whichever unit is active, prints the drop-in recipe for a custom output path, and drops the `install -d /run/rover`. The stale sibling DEC-013 comment is removed.
- **Tests**: subprocess test that the default watchdog callback ends `run()`; `OSError` from a patched read leaves exit 0; telemetry constructor failure still writes `scan_abort`; flush failure keeps the timer alive; camera autospec; NAV-PVT fixture; config cross-check; static test that both units contain `StateDirectory=rover` and neither TOML points under `/home`.
- **Not verifiable here**: systemd behaviour. The stage ends with a documented on-Pi smoke checklist, not a claim of success.

## 5. Stage 3 — Data pipeline

**Goal:** a synthetic session with a known wall sweeps to a 3D volume in the right units.

**Geometry (written into HARDWARE.md and ARCHITECTURE.md):** the LD19 stands on its side so its scan plane is the body X-Z plane (LiDAR x forward, LiDAR y becomes body up). The stepper rotates that plane about body Z. The IMU is assumed rigid to the fixed body. Chain: LiDAR plane → body (fixed mount rotation) → `R_z(mast_angle)` → IMU quaternion → GNSS offset → ENU → target CRS.

- **LiDAR driver**: after every mast move, reset the serial input buffer, clear the parse buffer, drop packets until the first angle wrap, then collect one revolution. The wrap-triggering packet seeds the next call. CRC resync advances one byte and requires the `0x2C` VerLen byte. Buffer trimming uses `del` slices; one precompiled `Struct`. Each scan carries the LD19 `timestamp_ms` of its first and last packet.
- **Record format**: LiDAR records are columnar (`angle`, `distance`, `intensity` arrays) plus `mast_angle_deg`, `lidar_ms_start`, `lidar_ms_end`. IMU records are one batched columnar record per loop iteration. No shim for the old per-point format; fixtures are regenerated.
- **IMU driver**: `start()` launches a sampling thread at `sample_rate_hz` using `time.monotonic()` for `dt` and `time.time()` for stamps. The ring buffer is the single DEC-014 buffer; `drain()` hands batches to the main loop. `MadgwickFilter.update()` accepts an optional mag triple and runs the MARG step when present, applying `[calibration].mag_offset` as hard-iron correction; the 6-DOF branch remains. DEC-013: `main.py` disables the magnetometer before `stepper.step()` and re-enables after settle. `_MAG_SCALE_14BIT` renamed to `_MAG_SCALE_16BIT`; nine unpacks become two; duplicate derivative block collapsed. `use_magnetometer` defaults to `false` in `default.toml` until a hard-iron calibration exists.
- **Georef**: loader globs `scan*.jsonl` and `gnss*.jsonl` in index order and flattens IMU batches. `lidar_points_to_local` applies the mount rotation and `R_z(mast_angle)` before the quaternion and always returns a tuple. `project_to_crs` reads the target CRS horizontal unit from pyproj and scales Z to match; output metadata states heights are ellipsoidal. PLY writes `property double`. Bisect for both time lookups; hoisted ENU helpers and constants; numpy resolved once; `units` honoured; CRS-embed failure logged; `total_points` removed.
- **Tests**: synthetic wall-at-2 m session swept 180° must span all three axes; rotated-file loading; Z-unit assertion for EPSG:6346; PLY header; wrap carry-over and one-byte resync with hand-built packets; IMU thread sample count against a fake bus; mag flag toggled around a step; MARG convergence on a synthetic field.

## 6. Stage 4 — Comms and config cleanup

**Goal:** NTRIP fails loudly when it must, works against VRS casters, and every config key has a consumer.

- **NTRIP 401/404**: the client receives `session.profile`. In `arm_group`, a 401 or 404 sets `fatal_error`, stops the loop, and `run()` aborts with exit code 4 and one ERROR line. In `personal`, one WARNING then retries at the 30 s ceiling at DEBUG.
- **GGA upload**: a `gga_source` callable (wired to `GnssReceiver.latest_fix`) feeds a pure `build_gga(fix)` helper; sent every `gga_send_interval_sec` seconds when positive and a fix exists.
- **Header tail and chunking**: bytes after `\r\n\r\n` are forwarded to the sink. `Transfer-Encoding: chunked` is rejected as fatal; the client does not de-chunk.
- **Shutdown and stats**: `stop()` shuts down the live socket; the sink gets `dataclasses.replace(self._stats)`; per-second rate from a timestamped window. Dead `_device_name`, redundant `socket.timeout`, wrong docstrings removed.
- **GNSS**: `_serial_lock` guards writes and `close()` only. With pyubx2, NAV-PVT is the sole fix source; GGA supplies `rtk_age` merged into the next fix; `pDOP` lands in a new `pdop` field. `subscribe()` removed; `line_buf` capped at 1 KB; `FIX_*` imported from `lora_protocol`.
- **Telemetry**: per-channel cadence inside the router; `[lora].telemetry_interval_sec` drives channel C. `status_schema_version` optional (absent means the module constant). `lora_link_rssi`, `lora_link_snr`, `battery_mv` become `None`, omitted from `status.json`, sentinel on the wire; `publish_link()` removed. `build_payload` uses `asdict`; borrowed publisher, `_bsi`, `_config`, dead role checks removed.
- **Config**: removed with validation and tests: `[gnss].rtcm_profile`, `survey_in_*`, `[power]`, `imu.fusion_output_hz`, `logging.format`. Kept and marked documentation-only with a parity test against `platformio.ini` build flags: the four `[lora]` radio parameters. `[calibration]` and `gga_send_interval_sec` stay because they now have consumers.
- **Lora protocol**: CRC body becomes `binascii.crc_hqx(data, 0xFFFF)`; golden frame hex constant added to the test file.
- **Tests**: fake-caster socket pair covering 200, 401 in both profiles, 404, chunked rejection, header-tail forwarding, GGA timing; GNSS single-source selection; publisher cadence; build-flag parity. Test hygiene: hardware `test_lidar.py` imports from `rover.lidar`, `test_imu.py` drives `ImuDriver`, hardware scripts default to udev symlinks, `tmp_toml` fixture consolidated in `conftest.py`, dead fixtures removed, `test_main.py` config writes only differing keys.

## 7. Stage 5 — Docs refresh and close-out

Docs are written last, from the code, one commit per document.

- **CLAUDE.md**: overhaul complete 2026-05-30, campaign as v0.11, phase v1.0 field validation; §4 tree regenerated from `git ls-files`; §3 deps gain `pyubx2` and `[post]`; §5 gains ruff commands; §6 gains DEC-035; §7 lists udev symlinks first; §8 gains the mount geometry; hardware row says one F9P and one antenna.
- **README.md**: status rewritten; fifth diagnostic script added.
- **ROADMAP.md**: stages D/E done with SHAs; §6 and §7.2 remapped to v1.0/v1.1 blocks; next actions are the on-Pi checklist and first field session; changelog gains v0.10 and v0.11.
- **ARCHITECTURE.md**: restamped; failure-mode table reconciled to code; transform diagram gains mount and mast rotation.
- **SPECIFICATIONS.md**: §2.2 becomes a pointer to `config/default.toml` plus a section table; config path corrected; §3.1 rewritten from the firmware README; §3.2/§3.3 reduced to a sibling pointer; §3.4 refreshed; JSONL section documents the columnar formats; metadata example regenerated by running the logger; LoRa budget recomputed.
- **BASE_STATION_INTEGRATION.md**: schema version 10 as of 2026-09; six Appendix pointers repointed; sibling doc reworded as pending CR-004; §3.1 documents omitted placeholder fields; date bumped.
- **HARDWARE.md**: one F9P, one antenna, halved totals; mount geometry and IMU-location TBD; §7.1 names Heltec as target, Muzi as equivalent.
- **ATTRIBUTION.md**: Open3D dropped; Unitree L2 sentence cites `V2_SLAM_CONCEPT.md` after a one-line addition there; Project Lineage and v0.9.x history migrated in from `README_ORIGINAL.md`.
- **Files**: `README_ORIGINAL.md` → `docs/archive/README_v0.9.2.md` with a supersession banner; `V2_SLAM_CONCEPT.md` linked from README and CLAUDE.md.
- **Backlog**: the 15 out-of-scope rows appended to `docs/CROSS_REPO_BACKLOG.md` under a dated "Rover-side deferred" section with finding IDs and rationale.
- **Close-out**: every `fix`/`simplify` row set to `done` with its SHA in the audit report; a grep for "in progress", "stub", "Phase 1", `/dev/ttyUSB0` and `/dev/ttyACM0` across docs returns only the archive; version 0.11.0; annotated tag `v0.11.0` on the stage 5 merge.

## 8. Verification

At every merge: `python -m pytest -q` green; `ruff check` and `ruff format --check` clean; the line-ending one-liner reports zero lone LF on every deploy file. Final test count is measured at close-out and written into the report, never predicted. Hardware-dependent findings (T1-005, T1-006, T1-033, T2-002) are fixed by reasoning plus autospec'd tests and remain marked `probable` until the on-Pi checklist runs.

## 9. Risks

- **9-DOF yaw** depends on a hard-iron calibration nobody has measured; hence `use_magnetometer = false` by default.
- **IMU location** is assumed fixed-body. If it turns out to ride the mast, georef must take yaw from the commanded angle and only roll/pitch from the IMU; the transform helper is written so that is a one-function change.
- **Record-format break** is deliberate; no real sessions exist.
- **systemd behaviour** cannot be observed here; stage 2 ends with a checklist.
