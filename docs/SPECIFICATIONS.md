# Technical Specifications

**Document Status:** v0.11 — reconciled with code (2026-09-23, stage 6 docs refresh)
**Last Updated:** 2026-09-23

Rover-internal specifications. Cross-repo / on-wire contracts live in
[BASE_STATION_INTEGRATION.md](BASE_STATION_INTEGRATION.md); this file is
the home for things only the rover cares about (TOML schema, JSONL records,
internal pinout, performance budgets).

---

## 1. LoRa Packet Format — Moved

The original v0.9.2 self-contained LoRa frame (Sync `0xAA 0x55`, Version `0x01`)
is **retired**. The current LoRa frame v2 envelope — shared with the
`arm-drone-lidar-workflow` Heltec/T-Deck firmware — lives in:

  * [BASE_STATION_INTEGRATION.md §4](BASE_STATION_INTEGRATION.md#4-lora-frame-v2)
    — authoritative wire format, packet types, CRC16-CCITT spec, radio parameters.

The v2 envelope defines five packet types (`STATUS`, `LINK`, `RTCM_CHUNK` — retired and reserved, see below —, `DISPLAY`, `DEBUG_TEXT`), but this rover only ever transmits `STATUS` (`0x01`):
`LINK` (`0x02`) is fully implemented in the shared codec, but the Pi-side
publisher that would send it (`LoRaPublisher.publish_link()`) was removed in
telemetry schema v2 (S2-R2), and `RTCM_CHUNK` (`0x10`) is retired and reserved
— no RTCM travels over LoRa (DEC-031 amended 2026-09-23; §7.3 below has the
STATUS-only airtime budget).

See also [`src/rover/lora_protocol.py`](../src/rover/lora_protocol.py) for the
codec implementation and [`docs/CROSS_REPO_BACKLOG.md`](CROSS_REPO_BACKLOG.md)
for the sibling-side firmware work still pending (CR-001, CR-003).

---

## 2. Configuration File Format (TOML)

### 2.1 File Location

```
/etc/rover/config.toml
```

Installed by `sudo deploy/install.sh` from `config/default.toml` — the first
run only; an existing file is never overwritten — and referenced directly by
`deploy/systemd/rover.service`'s `ExecStart=`. A second config, with
stepper/lidar/camera/imu all disabled, ships for bench tests:

```
/etc/rover/telemetry-only.toml
```

used by `rover-telemetry.service` (`Conflicts=rover.service` — the two units
never run together; both own `RuntimeDirectory=rover` and the same F9P serial
port).

### 2.2 Configuration Schema

`config/default.toml` is the authoritative, commented schema — every key, its
default, and its valid range live there, validated by `src/rover/config.py`'s
`_validate()`. Loading a TOML file with an unknown section or key is a
load-time `ValueError` (with a "did you mean ...?" suggestion when one is
close). The table below is a map, not a copy — read `config/default.toml` for
the real defaults and inline comments.

| Section | Purpose |
|---|---|
| `[general]` | Device name and log verbosity. |
| `[session]` | Per-session mode (`personal`\|`arm_group`), project/mission tags, target CRS and output units (DEC-030). |
| `[lidar]` | LD19 serial port, baud, scan rate. |
| `[stepper]` | NEMA17/A4988 pins, microstepping, and sweep geometry — `sweep_deg`/`rewind_rpm`/`rest_before_sweep_sec` (DEC-015 amended 2026-09-23). |
| `[imu]` | MPU-9250 bus/address/sample rate, magnetometer enable, Madgwick `fusion_beta`, and IMU `mount` location (S3-R3). |
| `[gnss]` | ZED-F9P serial port and baud. |
| `[ntrip]` | NTRIP-over-IP RTK client — caster host/port/mountpoint/credentials, `client_location` (`pi`\|`esp32`) (DEC-031, DEC-032). |
| `[lora]` | ESP32 LoRa serial port; radio parameters are documentation-only and must match `firmware/esp32-rover/platformio.ini`'s build flags; `telemetry_interval_sec` and `role` (`status_tx_only`\|`disabled`) govern the Pi-side STATUS cadence (DEC-031 amended 2026-09-23). |
| `[base_station_integration]` | Channel A — `status.json` path, schema-version override, publish interval (DEC-033). |
| `[telemetry]` | Channel B — loopback HTTP status endpoint bind/port (DEC-033). |
| `[camera]` | HQ Camera resolution, capture cadence, JPEG quality, output subfolder. |
| `[logging]` | Session output directory, filename prefix, flush interval, rotation size, image saving. |
| `[watchdog]` | Heartbeat/timeout for the systemd watchdog integration. |
| `[calibration]` | Optional extrinsic calibration — lidar/IMU/GNSS lever arms, hard-iron mag offset, antenna offset (§5.4). |

**Upgrade note:** a config.toml written for the pre-v0.11 schema may still carry keys the code no longer reads or accepts: `[power]` (no battery/ADC monitoring exists in this codebase), `[gnss].rtcm_profile` and `[gnss].survey_in_duration_sec`/`survey_in_accuracy_m` (RTCM-profile selection and base survey-in do not apply to an NTRIP client — DEC-031 makes the rover a client, never a base), `[imu].fusion_output_hz` (Madgwick now runs at the IMU's own `sample_rate_hz`; there is no separate output-rate knob), and `[logging].format` (JSONL is unconditionally the only format `SessionLogger` writes — there is no CSV path). Loading a config that still has any of these fails outright: `config.py`'s unknown-key check rejects them rather than silently ignoring them.

---

## 3. Firmware Boundaries

### 3.1 ESP32 LoRa (Rover) — STATUS-only modem, optional NTRIP client

From the Pi's side, the rover ESP32's LoRa job is narrow: relay whatever
`rover.telemetry.LoRaPublisher` pushes over USB onto LoRa. Since telemetry
schema v2 removed `publish_link()` (S2-R2), that traffic is a single STATUS
(`0x01`) frame every `[lora].telemetry_interval_sec` (default 10 s) — never
RTCM, never LINK (§7.3 has the airtime budget).

`firmware/esp32-rover/` (`platformio.ini`, `README.md`) ships two PlatformIO
environments, one of which documents a design the Pi side has already retired:

| Env | Role today |
|---|---|
| `ntrip_client` | Joins WiFi, pulls RTCM from the NTRIP caster itself, and writes it to the F9P's UART2 directly — used when `[ntrip].client_location = "esp32"` (DEC-032). Also relays the Pi's STATUS frames onto LoRa. |
| `lora_rtcm_relay` (`default_envs` in `platformio.ini`) | Still receives `RTCM_CHUNK` (`0x10`) over LoRa and forwards it to the F9P — a path the Pi side has already retired: `[lora].role` has offered no RTCM-receive value since stage 5, and `RTCM_CHUNK` is retired and reserved in `rover.lora_protocol`. Retiring this env and its `0x10` handler is tracked as backlog **S5-F1**; until that firmware change ships, treat this env as legacy and flash `ntrip_client` instead whenever ESP32-side NTRIP is wanted. |

Both envs relay STATUS (`0x01`) and LINK (`0x02`) frames the Pi pushes over
USB "as-is," per the firmware's own README — in practice the Pi-side
`LoRaPublisher` only ever sends STATUS, so the LINK-relay code path never
fires from this rover's current telemetry.

**Interfaces:**

| Interface | Connection | Data |
|---|---|---|
| LoRa | SX1262 radio (Heltec WiFi LoRa 32 V3) | Tx: STATUS frames, SF7/125 kHz/CR4-5 (§7.3) |
| UART2 | ZED-F9P | Tx: RTCM3 bytes — both firmware envs write here; source differs (below) |
| USB/UART0 | Raspberry Pi | Rx: STATUS frames from `rover.telemetry.LoRaPublisher` |

Both firmware envs wire UART2 to the F9P and forward RTCM there —
`F9PSerial.begin(...)` (`firmware/esp32-rover/src/main.cpp`) runs
unconditionally at boot regardless of which env was flashed. They differ
only in where the RTCM comes from: `lora_rtcm_relay`'s `0x10` (`RTCM_CHUNK` — retired and reserved, DEC-031 amended 2026-09-23) handler (`main.cpp:156`)
sources it from LoRa, but no Base-Station firmware sends that type any more
(CR-002 closed) — this path is legacy, pending removal under
**S5-F1**. `ntrip_client`'s
`ntrip_pump()` (`main.cpp:269`) sources it from the NTRIP caster over WiFi
(DEC-032). **When the Pi itself runs the NTRIP client**
(`[ntrip].client_location = "pi"`, the default), RTCM instead reaches the
F9P over its **USB** port directly from the Pi (`GnssReceiver.write_rtcm()`,
`src/rover/gnss.py`) — the ESP32 and its UART2 wiring carry no RTCM at all
in that mode.

### 3.2 Base-Station Firmware — out of scope

The Base-Station's own ESP32 (Heltec V3, `DISPLAY` Tx today) belongs to
`ixhlbxi/arm-drone-lidar-workflow`, not this repo. See
[`docs/CROSS_REPO_BACKLOG.md`](CROSS_REPO_BACKLOG.md) CR-001 (sibling
firmware is still on LoRa frame v1 and cannot yet parse this rover's v2
STATUS frames) and CR-002 (closed — no base-side LoRa-RTCM transmitter is
needed, DEC-031 amended 2026-09-23).

### 3.3 T-Deck Monitoring Console — out of scope

The T-Deck handheld also belongs to `arm-drone-lidar-workflow`; this rover
only produces the STATUS frames it would display. See
[`docs/CROSS_REPO_BACKLOG.md`](CROSS_REPO_BACKLOG.md) CR-003 (sibling
handheld firmware to recognize this rover's frames, pending on CR-001).

### 3.4 Raspberry Pi Software Modules

| Module | Responsibility | Interface |
|--------|----------------|-----------|
| `main.py` | Orchestration, acquisition state machine, sensor init/gating, teardown | All modules |
| `config.py` | TOML load, defaults merge, validation → frozen `RoverConfig` | Filesystem |
| `lidar.py` | LD19 acquisition, packet parsing, columnar scan assembly | USB-serial |
| `imu.py` | MPU-9250 polling, Madgwick fusion, magnetometer gating | I2C |
| `gnss.py` | ZED-F9P NMEA/UBX parsing, RTCM3 injection into the F9P | USB-serial |
| `ntrip.py` | Pi-side NTRIP client — caster connect, RTCM read, GGA upload (DEC-031, DEC-032) | TCP (NTRIP over HTTP); calls `gnss.write_rtcm` |
| `stepper.py` | NEMA17/A4988 motor control, step timing | GPIO (`rpi-lgpio`) |
| `sweep.py` | Sweep planner — rest/scan/rewind decision logic (DEC-015 amended) | Pure logic, no I/O |
| `camera.py` | HQ Camera capture, cadence gating | `picamera2` |
| `telemetry.py` | Triple-channel status routing — status.json / loopback HTTP / LoRa STATUS (DEC-033) | Filesystem, loopback HTTP, serial to ESP32 |
| `lora_protocol.py` | LoRa frame v2 codec — encode/decode, CRC16-CCITT | Pure logic, no I/O |
| `logger.py` | JSONL session logging, rotation, metadata.json | Filesystem |
| `watchdog.py` | Heartbeat monitor, systemd `sd_notify` integration | systemd (`NOTIFY_SOCKET`) |
| `_io.py` | Atomic JSON write helper shared by `logger.py` and `telemetry.py` | Filesystem |

**GPIO Library Note (DEC-029):** Use `rpi-lgpio` (drop-in replacement for `RPi.GPIO`) or `gpiozero` for all GPIO operations. The legacy `RPi.GPIO` is broken on Raspberry Pi OS Bookworm 64-bit. Install via `pip install rpi-lgpio` or `sudo apt install python3-rpi-lgpio`. Set environment variable `LG_WD=/tmp` to manage lgpio temp files.

---

## 4. Data Schema

### 4.1 Session Directory Structure

```
/var/lib/rover/data/                 # [logging].output_dir default (systemd StateDirectory)
└── scan_20260924_013735/            # <session_prefix>_YYYYMMDD_HHMMSS (UTC)
    ├── config.toml                  # copy of the TOML file run() was given, OR
    ├── effective_config.json        # ...a JSON dump of the effective config when run()
    │                                 #    got no --config path (only one of these exists)
    ├── scan.jsonl                   # lidar / imu / camera / event records
    ├── scan_001.jsonl               # rotated segment(s) once rotate_size_mb is exceeded
    ├── gnss.jsonl                   # gnss records ONLY (T1-053) — never in scan*.jsonl
    ├── gnss_001.jsonl               # gnss rotates independently of scan
    ├── images/                      # camera captures — only when [camera].enabled AND
    │   ├── img_000000.jpg           # [logging].save_images = true
    │   └── ...
    ├── export/                      # written by scripts/georef.py, NOT by the rover
    │   ├── ..._ellipsoidal.ply/.las # §4.4
    │   ├── ..._navd88.ply/.las      # §4.4
    │   └── export.json              # §4.4
    └── metadata.json                # written by SessionLogger.stop(); §4.3
```

`scripts/georef.py` reads every `scan*.jsonl` / `gnss*.jsonl` segment in
numeric order (rotation-aware).

### 4.2 JSONL Record Types

Each line in `scan.jsonl` (or a rotated `scan_NNN.jsonl` segment) is one
compact JSON object (`json.dumps(record, separators=(",", ":"))`) with a
`type` field. `gnss` records are the one exception — they are written ONLY to
`gnss.jsonl` / `gnss_NNN.jsonl`, never to `scan*.jsonl` (T1-053).

#### 4.2.1 LiDAR Scan Record (columnar)

```json
{"type":"lidar","timestamp":1735226852.123456,"step_index":47,"sweep":0,"mast_angle_deg":74.25,"lidar_ms_start":12345,"lidar_ms_end":12445,"angle":[0.0,0.801,1.602,...],"distance":[3.452,3.461,3.470,...],"intensity":[128,131,129,...]}
```

| Field | Type | Description |
|-------|------|--------------|
| type | string | `"lidar"` |
| timestamp | float | Unix time, captured immediately after `LidarScanner.read_scan()` returns |
| step_index | int | Rotation-step counter; increments once per completed scan step (rest/rewind iterations do not increment it) |
| sweep | int | `SweepPlanner.sweep_index` — which 360° sweep (0-based) this record belongs to |
| mast_angle_deg | float | Commanded mast angle at capture time; `0.0` when there is no available stepper |
| lidar_ms_start / lidar_ms_end | int | LD19's own onboard packet timestamp (ms) for the first/last point of this revolution; wraps at 30000 |
| angle | float[] | Per-point angle, degrees, `[0, 360)` |
| distance | float[] | Per-point distance, meters |
| intensity | int[] | Per-point return intensity, `0-255` |

There is no `points` list of per-point dicts — `angle`/`distance`/`intensity`
are parallel arrays, one element per returned point.

#### 4.2.2 IMU Record (batched)

```json
{"type":"imu","timestamp":1735226852.125000,"t":[1735226852.100,1735226852.105],"accel":[[0.012,-0.008,9.81],[0.011,-0.009,9.80]],"gyro":[[0.001,-0.002,0.0005],[0.001,-0.002,0.0006]],"mag":[null,[25.3,-12.1,42.8]],"orientation":[[0.707,0.0,0.0,0.707],[0.706,0.0,0.0,0.708]]}
```

| Field | Type | Description |
|-------|------|--------------|
| type | string | `"imu"` |
| timestamp | float | Unix time of the LAST sample in this batch |
| t | float[] | Per-sample Unix timestamps, one `ImuDriver.drain()` call |
| accel | [float,float,float][] | Per-sample accelerometer, m/s² |
| gyro | [float,float,float][] | Per-sample gyroscope, rad/s |
| mag | ([float,float,float]\|null)[] | Per-sample magnetometer, µT; `null` for a sample taken while the magnetometer was off (DEC-013: disabled during stepper motion / EMI) |
| orientation | [float,float,float,float][] | Per-sample Madgwick quaternion, scalar-first `[w, x, y, z]` |

`t`/`accel`/`gyro`/`mag`/`orientation` are parallel arrays of equal length —
one entry per sample `drain()` returned that call; the batch size is whatever
accumulated since the previous drain, not a fixed count (§7.1 assumes ~20
samples/batch at the default rates).

#### 4.2.3 GNSS Record

```json
{"type":"gnss","timestamp":1735226852.0,"fix_type":5,"lat":40.712776,"lon":-74.005974,"alt":12.345,"hdop":0.85,"vdop":1.2,"pdop":1.45,"sat_count":18,"rtk_age":1.2}
```

| Field | Type | Description |
|-------|------|--------------|
| type | string | `"gnss"` |
| timestamp | float | Unix timestamp at fix (GGA has no date, so this is receive-time, not GNSS time) |
| fix_type | int | `0`=NONE `1`=2D `2`=3D `3`=DGPS `4`=RTK_FLOAT `5`=RTK_FIX (rover's own monotonic enum — the wire NMEA/NAV-PVT quality codes are remapped; see `src/rover/gnss.py`) |
| lat / lon | float | WGS84 decimal degrees |
| alt | float | Ellipsoidal (WGS84) meters — both the GGA path (MSL + geoid separation) and the NAV-PVT path (`height`) are normalized to this before reaching `GnssFix` |
| hdop | float | Horizontal dilution of precision; `99.9` placeholder when unknown |
| vdop | float | Always `99.9` — neither GGA nor NAV-PVT breaks out a vertical DOP figure |
| pdop | float | NAV-PVT's position DOP; `99.9` when the fix source is GGA only (no NAV-PVT ever parsed) |
| sat_count | int | Satellites used |
| rtk_age | float | Seconds since the last applied RTCM correction; `-1` = unknown |

This record type is written ONLY to `gnss.jsonl` (T1-053) — it never appears
in `scan.jsonl`.

#### 4.2.4 Camera Record

```json
{"type":"camera","timestamp":1735226852.130000,"step_index":47,"filename":"images/img_000047.jpg"}
```

| Field | Type | Description |
|-------|------|--------------|
| type | string | `"camera"` |
| timestamp | float | Unix time at capture |
| step_index | int | Associated rotation step |
| filename | string | Path to the image, relative to the session directory |

#### 4.2.5 Event Record

```json
{"type":"event","timestamp":1735226850.0,"event":"sweep_start","details":{"sweep":0,"rest_sec":2.31,"heading_settled":true}}
```

| Field | Type | Description |
|-------|------|--------------|
| type | string | `"event"` |
| timestamp | float | Unix timestamp |
| event | string | Event name — see the table below |
| details | object | Present for five of the seven event types below; `scan_complete`/`scan_abort` are written with no `details` key at all |

**Event Types** (exactly seven; `src/rover/main.py` is the sole emitter):

| event | when | details |
|---|---|---|
| `scan_start` | once, right after `SessionLogger.start()` | `{"profile": <session.profile>}` |
| `sweep_start` | once per sweep, right after that sweep's pre-scan rest ends | `{"sweep": int, "rest_sec": float, "heading_settled": bool\|null}` — `rest_sec` is the actual seconds rested, including sweep 0's extra heading-settle wait; `heading_settled` is `null` for every sweep except the first, and is also `null` on sweep 0 itself unless `[imu].use_magnetometer = true` AND the IMU is present and available (`sensors.imu is not None and sensors.imu.available`) — the settle wait (`_wait_for_heading_settle`) only ever runs when `planner.sweep_index == 0` and all three of those hold |
| `sensor_disabled` | the instant a sensor's failure gate trips (5 consecutive read failures) | `{"sensor": <name>, "error": <str>}` |
| `returned_home` | teardown, after the mast successfully rewinds to step 0 | `{"steps": int}` |
| `return_home_failed` | teardown, if that rewind itself raises | `{"steps_from_home": int, "error": <str>}` — there is no home switch (S5-R3); home the mast by hand before the next session |
| `scan_complete` | teardown, `run()` exit code `0` | *(no `details` key)* |
| `scan_abort` | teardown, `run()` exit code non-zero | *(no `details` key)* |

### 4.3 Session Metadata

`metadata.json` is written by `SessionLogger._write_metadata()` on `stop()`.
It is **generated from the running code**, not hand-authored — the example
below is the literal output of an actual run, not an illustration.

**Command** (all sensors and telemetry channels disabled, 2-second bench run
— template: `tests/test_main.py::_write_all_disabled_config`, with
`[logging].output_dir` pointed at a temp directory):

```
python -m rover.main --config /tmp/rover_all_disabled.toml --duration-sec 2
```

**Resulting `metadata.json`** (session id and timestamps kept exactly as
produced, run 2026-09-24):

```json
{"session_id": "test_20260924_013735", "start_time": "2026-09-24T01:37:35.982337+00:00", "end_time": "2026-09-24T01:37:38.020656+00:00", "device_name": "test-rover", "firmware_version": "0.10.0", "config_hash": "6ca5896d434bae0d800da86d52a29054a5973f467ec16b88c9546342733c59f5", "logger_degraded": false, "dropped_records": 0, "lost_records": 0, "session": {"profile": "personal", "project_code": "", "mission_tag": "", "target_crs_epsg": 0, "units": "m"}, "geometry": {"imu_mount": "base", "antenna_offset_m": null, "sweep_deg": 360.0, "rewind_rpm": 10.0, "rest_before_sweep_sec": 2.0}}
```

| Field | Type | Description |
|---|---|---|
| session_id | string | Session directory name |
| start_time / end_time | string\|null | ISO-8601 UTC; `start_time` is `null` only if `stop()` is somehow called before `start()` recorded a start time |
| device_name | string | `[general].device_name` |
| firmware_version | string | `rover.__version__` — read from the running code, never hand-copied |
| config_hash | string\|null | SHA-256 of the copied `config.toml` (or `effective_config.json` when no `--config` was given); `null` if neither file exists |
| logger_degraded | bool | `true` once any flush has failed during the session |
| dropped_records | int | Records discarded because the write queue was full |
| lost_records | int | Records drained from the queue but never written, due to a failed flush |
| session | object | `profile` / `project_code` / `mission_tag` / `target_crs_epsg` / `units`, copied from `[session]` (DEC-030, DEC-034) — `scripts/georef.py` reads this to re-export without parsing `config.toml` |
| geometry | object | `imu_mount`, `antenna_offset_m`, `sweep_deg`, `rewind_rpm`, `rest_before_sweep_sec` — always present, sourced from `[imu]`/`[calibration]`/`[stepper]` regardless of whether the stepper subsystem itself is enabled that session |
| ntrip_stats | object, optional | Present only when `run()`'s local `ntrip_client` variable is not `None` at teardown — i.e. `[ntrip].enabled = true` AND `[ntrip].client_location == "pi"` AND `sensors.gnss is not None` (GNSS enabled and its `GnssReceiver` constructed successfully) AND `NtripClient(...)`/`.start()` did not raise. A raise there is caught, logged, and leaves `ntrip_client = None` — the field is silently absent, not present-but-empty, in that case. Value is `asdict(NtripClient.stats)`: `connected`, `bytes_received_total`, `bytes_received_this_sec`, `last_connect_attempt_epoch`, `last_byte_epoch`, `connect_count`, `error_count`, `last_error` |

### 4.4 Georeferenced Export Outputs

Written by `scripts/georef.py` as a **separate, offline post-processing
step** (DEC-022, DEC-034) — the rover process itself never writes to
`export/`. Invocation: `python -m scripts.georef <session_dir> [--crs EPSG]
[--units ft|m] [--out-prefix PREFIX] [--no-las]`.

For a projected `target_crs_epsg` (and no `--units`/CRS mismatch), two
point-cloud pairs are written into `<session_dir>/export/`:

* `<prefix>_ellipsoidal.ply` (+ `.las` unless `--no-las` or `laspy` is
  missing) — the raw ellipsoidal (NAD83(2011)) heights this pipeline has
  always produced.
* `<prefix>_navd88.ply` (+ `.las`) — those heights converted to NAVD88 via
  the GEOID18 grid (source CRS NAD83(2011) geographic 3D `EPSG:6319` →
  compound `EPSG:<horizontal>+6360` for a ftUS CRS, `+5703` for a metric
  one).

For local-ENU / LiDAR-relative output (`target_crs_epsg == 0`, or no GNSS fix
to project from) or a `--units`/CRS mismatch, only a single `<prefix>.ply`
(+ `.las`) pair is written — there is no embedded CRS to split an
ellipsoidal/NAVD88 pair on.

Every export also writes `export/export.json`:

```json
{
  "files": [{"path": "<prefix>_ellipsoidal.ply", "horizontal": "EPSG:6563", "vertical": "ellipsoidal NAD83(2011)"}],
  "navd88_error": null,
  "heading_reference": "true",
  "declination_deg": -9.9,
  "imu_mount": "base",
  "antenna_offset_m": null
}
```

| Field | Type | Description |
|---|---|---|
| files | array | One entry per `.ply` written (not `.las`): `path`, `horizontal` (an `EPSG:<n>` string or `"none"`), `vertical` (a datum label) |
| navd88_error | string\|null | Why NAVD88 was skipped (geoid grid unavailable, or a units/CRS mismatch dropped the CRS label); `null` when NAVD88 was produced or never applicable |
| heading_reference | string | `"true"` (declination applied), `"magnetic"` (no declination available), or `"relative"` (no rest magnetometer data at all — yaw comes from the commanded mast angle) |
| declination_deg | float\|null | WMM 2025 declination at the GNSS origin; `null` when not computed |
| imu_mount | string | `"base"` or `"platform"`, from `metadata.json`'s `geometry` block |
| antenna_offset_m | [float,float,float]\|null | From `metadata.json`'s `geometry` block |

**Exit codes:**

* **exit 0** — success (with or without a NAVD88 pair).
* **exit 1** — no points assembled (empty session — nothing to export).
* **exit code 3** — NAVD88 unavailable (the GEOID18 grid is missing and the
  network fetch was refused or failed), or a `--units`/CRS mismatch dropped
  the CRS label. In both cases the ellipsoidal file(s) are still written.

A missing geoid grid is installed with:

```
python -m pyproj sync --file us_noaa_g2018u0.tif
```

or PROJ's own `projsync --file us_noaa_g2018u0.tif`.

---

## 5. Coordinate Frame Conventions

### 5.1 Frame Definitions

| Frame | Origin | X | Y | Z |
|-------|--------|---|---|---|
| LiDAR | LD19 optical center | Forward | Left | Up |
| IMU | MPU-9250 center | Forward | Left | Up |
| Body | Rover center | Forward | Left | Up |
| GNSS | Antenna phase center | — | — | — |
| Local ENU | Session start position | East | North | Up |
| WGS84 | Earth center | ECEF or Geodetic | | |

### 5.2 Quaternion Convention

- Scalar-first format: [w, x, y, z]
- Represents rotation from reference frame to body frame
- Right-handed coordinate system

### 5.3 Transform Notation

`T_A_B` = Transform from frame B to frame A

Example: `T_body_lidar` transforms points from LiDAR frame to Body frame.

### 5.4 Extrinsic Calibration Parameters

```toml
# Extrinsic calibration — TBD, measured during the v1.1 calibration procedure (S3-R3)
[calibration]
# lidar_to_imu_translation = [0.0, 0.0, 0.05]    # [x, y, z] meters
# lidar_to_imu_rotation = [1.0, 0.0, 0.0, 0.0]   # [w, x, y, z] quaternion
# imu_to_gnss_translation = [0.0, 0.0, 0.30]     # [x, y, z] meters
mag_offset = [0.0, 0.0, 0.0]                      # hard-iron offset (x, y, z), µT, body frame —
                                                   # required before [imu].use_magnetometer = true (DEC-013)
antenna_offset_m = [0.0, 0.0, 0.35]               # LiDAR centre -> antenna phase centre, metres,
                                                   # platform frame at mast 0 (S3-R3)
```

All five keys are optional (`None` = uncalibrated); `config.py` validates
each as `[x, y, z]` (or `[w, x, y, z]` for the rotation), rejects a stray
`true`/`false` element, and rejects a non-finite `mag_offset` value.

---

## 6. Interface Pinouts

### 6.1 Raspberry Pi GPIO (BCM Numbering)

| GPIO | Function | Direction | Notes |
|------|----------|-----------|-------|
| GPIO17 | Stepper DIR | Output | Direction control |
| GPIO27 | Stepper STEP | Output | Step pulse |
| GPIO22 | Stepper ENABLE | Output | Active low |
| GPIO2 (SDA) | I2C Data | Bidirectional | IMU |
| GPIO3 (SCL) | I2C Clock | Output | IMU |

### 6.2 Serial Port Allocation

The udev symlinks are the primary, stable ports — installed by
`deploy/install.sh` from `deploy/udev/99-rover-*.rules`:

| Symlink | Device | Baud | udev rule |
|---|---|---|---|
| `/dev/rover-lidar` | LD19 LiDAR | 230400 | `99-rover-lidar.rules` |
| `/dev/rover-f9p` | ZED-F9P | 115200 | `99-rover-f9p.rules` |
| `/dev/rover-esp32` | ESP32 LoRa | 115200 | `99-rover-esp32.rules` |

Pre-install fallback (before the udev rules are applied, or if a rule's `*_SERIAL_PLACEHOLDER` was never filled in): `/dev/ttyUSB0` (LiDAR), `/dev/ttyACM0` (F9P), `/dev/ttyUSB1` (ESP32) — whichever device happens to enumerate there first; `deploy/install.sh` refuses to install a rule that still contains a placeholder serial.

### 6.3 ESP32 LoRa Connections (Rover)

| ESP32 Pin | Connection | Notes |
|-----------|------------|-------|
| TX2 | ZED-F9P UART2 RX | RTCM forwarding — both firmware envs write here (source differs, §3.1); carries nothing when the Pi itself runs the NTRIP client (`client_location = "pi"`) |
| RX2 | (Not connected) | F9P doesn't send to ESP32 |
| TX0/USB | Pi USB | Telemetry to Pi |
| RX0/USB | Pi USB | Commands from Pi (future) |
| SPI | SX1262 | LoRa radio |

### 6.4 I2C Bus

| Address | Device | Notes |
|---------|--------|-------|
| 0x68 | MPU-9250 | Primary (AD0 low) |
| 0x69 | MPU-9250 | Alternate (AD0 high) |

**Pull-ups:** 4.7kΩ on SDA and SCL to 3.3V

---

## 7. Performance Budgets

### 7.1 Data Rates

Recomputed for the columnar record formats (§4.2), using
`json.dumps(record, separators=(",", ":"))` — the exact call
`SessionLogger._write_record()` makes — on representative records.

**LiDAR:** the LD19 outputs roughly 450 points per revolution at the default
`scan_rate_hz = 10` (`POINTS_PER_PACKET = 12` per `src/rover/lidar.py`, at
its native packet rate). A synthetic 450-point record serializes to 8,367
bytes: the `angle`/`distance`/`intensity` arrays alone are 8,229 bytes
(~18.3 bytes/point), plus ~138 bytes of fixed per-record fields
(`timestamp`/`step_index`/`sweep`/`mast_angle_deg`/`lidar_ms_start`/
`lidar_ms_end`). One record per revolution: 8,367 B × 10/s ≈ **82 KB/s**.

**IMU:** at the default `[imu].sample_rate_hz = 200` and the main loop's
steady-state pace of `settle_sec = 1 / scan_rate_hz = 0.1 s` (10 Hz default),
`ImuDriver.drain()` returns roughly 20 samples per call. A 20-sample batch
(`t` + `accel`/`gyro`/`mag`/`orientation` parallel arrays) serializes to
2,893 bytes (~145 bytes/sample). At ~10 batches/s: 2,893 B × 10/s ≈
**28 KB/s**.

**GNSS:** one `gnss` record (with `pdop`) is 163 bytes (measured the same
way); the F9P reports at up to 1 Hz: 163 B × 1/s ≈ **0.16 KB/s**. Written to
`gnss.jsonl` only.

**Camera:** unchanged record shape (§4.2.4). `[camera].capture_cadence`
gates how often `capture()` fires relative to scan steps — the default is
`1` (every scan step), so at `scan_rate_hz = 10` a capture can fire up to
10 times/second, not at a fixed rate. Image size is scene-dependent; budget
roughly 300–600 KB/JPEG at the default 1920×1080, quality 85.

| Source | Rate | Size | Bandwidth |
|--------|------|------|-----------|
| LiDAR | 10 Hz (`scan_rate_hz`) | ~8.2 KB/record (450 pts × ~18.3 B/pt + ~138 B envelope) | ~82 KB/s |
| IMU | 200 Hz sampled, ~10 batches/s | ~2.9 KB/batch (~20 samples × ~145 B) | ~28 KB/s |
| GNSS | up to 1 Hz | 163 B/record | ~0.16 KB/s |
| Camera | up to `scan_rate_hz` (`capture_cadence = 1`) | ~300–600 KB/JPEG (scene-dependent) | bursty, not counted below |

**Total sustained write (scan.jsonl + gnss.jsonl, excluding images):**
82 + 28 + 0.16 ≈ **110 KB/s** at the default 10 Hz / 200 Hz / 1 Hz rates.

### 7.2 Storage Estimates

At ~110 KB/s sustained JSONL (§7.1):

| Duration | scan.jsonl + gnss.jsonl |
|----------|-------------------------|
| 1 hour | 110 KB/s × 3,600 s ≈ **387 MB** |
| 4 hours | ≈ **1.51 GB** |

Images are additive and, at the default `capture_cadence = 1`, scale with
the scan rate rather than a fixed cadence: 10 Hz × 3,600 s = 36,000 captures
in an hour, which at ~450 KB/JPEG is about **15 GB per hour**
(36,000 × 450 KB) — raise `[camera].capture_cadence` for any session longer
than a few minutes, or set
`[logging].save_images = false` to skip image writes entirely regardless of
cadence (`capture()` is then never called).

**Recommended storage:** 32 GB minimum, 64 GB+ preferred for JSONL-only
sessions; size for images separately based on the chosen `capture_cadence`.

### 7.3 LoRa Bandwidth Budget

One STATUS frame — 18 bytes total (8-byte envelope + 10-byte payload,
`src/rover/lora_protocol.py`) — every `[lora].telemetry_interval_sec`
(default 10 s), at SF7/125 kHz/CR4-5 (`firmware/esp32-rover/platformio.ini`).
No LINK, no RTCM traffic exists on this link (§1, §3.1).

Time-on-air, Semtech AN1200.13's LoRa airtime formula, assuming RadioLib's
defaults (8-symbol preamble, explicit header, CRC on, no low-data-rate
optimization at SF7):

```
T_symbol      = 2^SF / BW = 2^7 / 125000 = 1.024 ms
T_preamble    = (n_preamble + 4.25) * T_symbol = (8 + 4.25) * 1.024 ms = 12.544 ms

payloadSymbNb = 8 + max(ceil[(8*PL - 4*SF + 28 + 16*CRC - 20*IH) / (4*(SF - 2*DE))] * (CR + 4), 0)
              = 8 + max(ceil[(8*18 - 4*7 + 28 + 16*1 - 0) / (4*7)] * (1 + 4), 0)
              = 8 + max(ceil[160 / 28] * 5, 0) = 8 + (6 * 5) = 38 symbols

T_payload     = 38 * 1.024 ms = 38.912 ms
T_packet      = T_preamble + T_payload = 12.544 + 38.912 = 51.456 ms  (time-on-air)

duty cycle    = T_packet / 10 s = 51.456 ms / 10,000 ms ≈ 0.515%
```

| Frame | Cadence | Size | Time-on-air | Duty cycle |
|-------|---------|------|-------------|------------|
| STATUS (`0x01`) | every 10 s | 18 B (8 envelope + 10 payload) | ≈51.5 ms | ≈0.515% |

**Total:** ≈0.515% duty cycle — one STATUS frame every 10 s is the entire
load this rover puts on the radio link.

### 7.4 Latency Budgets

| Path | Target | Notes |
|------|--------|-------|
| RTCM caster → rover | <2 sec | NTRIP over IP (DEC-031); no LoRa RTCM path exists |
| Sensor → log | <100 ms | Local processing |
| Telemetry → monitor | <3 sec | LoRa STATUS every 10 s + display update (once a sibling handheld understands v2 frames — CR-001, CR-003) |
