# Base-Station Integration

**Document Status:** v0.10 — overhaul authoritative contract
**Companion repo:** `ixhlbxi/arm-drone-lidar-workflow`
**Last Updated:** 2026-09-23

This document is the single source of truth for how this rover interacts with the
production Base-Station built in `ixhlbxi/arm-drone-lidar-workflow`. Both repos refer
back here when they encode protocol details.

The integration is **optional** — the rover runs standalone in personal-DIY profile.
ARM Group companion profile turns the integration on; everything described below is
how that integration is wired.

---

## 1. Two Roles, One Rover

| Profile | When to use | Major behaviors |
|---|---|---|
| `personal` (default) | DIY use, off-grid, no project conventions | WGS84 / local ENU output; NTRIP optional; LoRa STATUS on (LINK is defined but never sent); HTTP `/status` typical observability |
| `arm_group` | Companion to ARM Group drone/LiDAR survey workflow | NTRIP required (default mountpoint `ARM_BASE`); project code + mission tag required; output in session-recorded CRS (e.g., NAD83(2011) / PA-N / ft-US); `status.json` published to a path the Base-Station's existing tooling can read |

Selection is per session via `[session].profile` in the rover's TOML config.
See DEC-030 in `docs/DECISIONS.md`.

---

## 2. RTK Correction Paths

NTRIP-over-IP is the rover's only RTK correction path (DEC-031 amended 2026-09-23).
LoRa carries status-only telemetry (§3.3) and never RTCM — there is no fallback
transport for corrections.

### 2.1 Primary — NTRIP over IP

```
┌──────────────────────┐    NTRIP/RTCM3    ┌───────────────────────────┐
│  arm-drone-lidar-    │  TCP :2101        │  Rover NTRIP client       │
│  workflow Base-      │  mountpoint       │  (Pi or ESP32, per        │
│  Station Pi          │  ARM_BASE         │  [ntrip].client_location) │
│  (NTRIP caster)      │ ─────────────────►│                           │
└──────────────────────┘                   └────────────┬──────────────┘
                                                        │ RTCM3 bytes
                                                        ▼
                                          ┌─────────────────────────┐
                                          │  Rover ZED-F9P          │
                                          │  USB (Pi client) or     │
                                          │  UART2 (ESP32 client)   │
                                          └─────────────────────────┘
```

**Endpoint defaults:**

| Setting | Default | Override |
|---|---|---|
| Caster host | `rtk-base.local` | `[ntrip].caster_host` |
| Port | `2101` | `[ntrip].caster_port` |
| Mountpoint | `ARM_BASE` | `[ntrip].mountpoint` |
| Username | `rover` | `[ntrip].username` |
| Password | (env var) | `[ntrip].password_env` (default `ROVER_NTRIP_PASSWORD`) |
| GGA upstream | `10.0` sec | `[ntrip].gga_send_interval_sec` (0 = never) |

Credentials are never committed to config files. The rover reads the password from
the environment variable named by `password_env`, mirroring the Base-Station's
`RTK_NTRIP_PASSWORD` convention.

**Network requirements:** rover Pi (or rover ESP32, if client lives there) must have IP
reach to the Base-Station Pi. Any of these topologies works:

1. Both Pis on the same WiFi (truck-mounted AP, office network).
2. Base-Station Pi runs as a WiFi AP, rover Pi joins it.
3. Phone hotspot bridges both.

### 2.2 Fallback — LoRa-Relayed RTCM

**Retired (DEC-031 amended 2026-09-23; `CR-002` not needed).** Earlier revisions of
this doc described a LoRa-relayed-RTCM fallback — now-retired `RTCM_CHUNK` frames
(base → rover, type `0x10`) — that was never built on the Base-Station side and is
not coming. The sibling backlog item `CR-002` (base-side LoRa-RTCM transmitter) is
closed not-needed.
`[lora].role` is `status_tx_only` or `disabled`; there is no RTCM-receive role, and
frame type `0x10` (described in §4) is retired and reserved so no future type reuses
it. NTRIP-over-IP (§2.1) is the rover's only RTK transport.

### 2.3 Caster Sharing (fact 16)

The Base-Station's NTRIP caster (`base-station/rtk_base_manager.py`) serves **one client at a time** —
a newly authenticated client replaces (evicts) whichever client is currently
connected, closing its socket. Filed sibling-side as backlog **NC-1** (§NTRIP
Caster, 2026-09-23). The rover has no protocol-level way to detect or negotiate
around this.

**Interim rule (owner, 2026-09-23):** the drone and this rover never share a base
session (`CR-005`) — confirm the caster is free before starting the rover's NTRIP
client.

Other caster behavior, measured 2026-09-23 in `arm-drone-lidar-workflow@e88c11b`
(`base-station/rtk_base_manager.py` ~1028-1208, `ntrip_auth.py`,
`config/base_config.yaml`, `rtk_io.py:155`):

| Behavior | Detail |
|---|---|
| Protocol | NTRIP v1 — a successful connect gets `ICY 200 OK`, not chunked |
| Auth | HTTP Basic, password only — no username check |
| Unauthenticated `GET /` | Returns the sourcetable |
| Wrong mountpoint | `404`, checked **before** auth |
| Bad password | `401` |
| GGA | Never read by the caster — sending it (§2.1) is a rover-side courtesy only |
| RTCM message types served | `1005`, `1077`, `1087`, `1097`, `1127`, `1230` |
| Availability | Only serves corrections while the Base-Station is in `main` mode, armed, and ready |

---

## 3. Telemetry — Three Independent Channels (DEC-033)

Each channel is independently enable-able via config. None is required.

### 3.1 Channel A — Base-Station-compatible `status.json`

Default path: `/run/rover/status.json`. Atomic write via mkstemp + rename, mirroring
`arm-drone-lidar-workflow/base-station/rtk_io.py:atomic_write_json`. Any process that
already knows how to read the Base-Station's `/run/rtk-base/status.json` can read the
rover's too — same shape, separate schema version.

**Rover-side schema v2:**

```json
{
  "schema_version": 2,
  "timestamp_epoch": 1758585600.123,
  "device": "rover-01",
  "profile": "arm_group",
  "mission": "WENTZ",
  "project_code": "2026-WENTZ-LIDR",
  "fix_type": 5,
  "sat_count": 18,
  "hdop": 0.85,
  "pdop": 1.42,
  "lat": 40.7128,
  "lon": -74.0060,
  "alt_m": 10.5,
  "rtk_age_s": 1.2,
  "scan_state": 1,
  "ntrip_connected": true,
  "ntrip_bytes_per_sec": 850,
  "sensors_disabled": [],
  "logger_degraded": false
}
```

`battery_mv`, `lora_link_rssi` and `lora_link_snr` are omitted above because they are
unmeasured in this example: `RoverStatus` treats `None` as "unmeasured," and
`build_payload()` (`src/rover/telemetry.py`) drops any field whose value is `None`
rather than sending a placeholder. `sensors_disabled` and `logger_degraded` are always
present, never omitted.

`schema_version` is versioned independently from the Base-Station's own status.json:
rover v2; the Base-Station's own status.json is v10 (a different schema). Adding a
field to the rover schema is a minor bump; removing or renaming is a major bump.

### 3.2 Channel B — Local HTTP Endpoint

Stdlib `http.server`, loopback-only by default. Mirrors the minimalism of
`arm-drone-lidar-workflow/base-station/rtk_base_api.py` so it stays auditable.

| Route | Returns |
|---|---|
| `GET /status` | The same JSON shape as Channel A's status.json |
| `GET /health` | `{"ok": true, "uptime_s": N}` |

Enable via `[telemetry].http_enabled = true`. Port defaults to `8090` (one above the
Base-Station's `8080` to avoid collision when both Pis share a host accidentally).

### 3.3 Channel C — LoRa STATUS / LINK Packets

LoRa frame v2 (§4) with `type = 0x01` (STATUS). The frame format also defines `0x02`
(LINK), but the rover never sends it — LINK is a decode-only type today, kept for a
future receiver. Payload bodies are laid out in §4's type table; the fields mirror
the JSONL record shapes described in
[`SPECIFICATIONS.md` §4.2](SPECIFICATIONS.md#42-jsonl-record-types):

- STATUS (10 bytes): `fix_type, sat_count, hdop×100, battery_mv, scan_state, 3×reserved`
- LINK (14 bytes, defined but never transmitted by the rover): `rssi+128, snr+128, rx_count, tx_count, err_count, 2×reserved`

Cadence: `[lora].telemetry_interval_sec` (default `10.0`) — STATUS every 10 s.

Survives the no-network case (Channels A and B require IP / filesystem). LoRa never
carries RTCM (§2.2, retired), so there is no on-air contention with a correction
stream to manage.

---

## 4. LoRa Frame v2

Shared envelope used by both repos, specified here in full. It is a strict superset
of the Heltec v1 display frame — receivers that only understood v1 (display body)
MUST reject v2 frames; v2-aware receivers handle both by dispatching on `type`.

> ⚠️ **Reality check (as of 2026-09-23):**
> the sibling `arm-drone-lidar-workflow` Heltec firmware in
> `base-station/heltec-display/src/main.cpp` still runs
> `LORA_PROTO_VERSION = 1` (DISPLAY-only body, no envelope), and the T-Deck
> handheld drops any frame it doesn't recognize — so the rover's v2 STATUS
> frames are unheard end-to-end until both land. This holds regardless of
> firmware version: LoRa is status-only on the rover side by design (DEC-031
> amended 2026-09-23), not merely because the sibling firmware hasn't caught
> up. The rover's
> [`src/rover/lora_protocol.py`](../src/rover/lora_protocol.py) and the
> rover ESP32 firmware in [`firmware/esp32-rover/`](../firmware/esp32-rover/)
> implement v2 fully and are forward-compatible, **but**:
>
>   * No sibling-side receiver currently parses rover STATUS frames.
>   * LoRa carries no RTCM in either direction — the fallback path formerly
>     described in §2.2 is retired.
>
> Sibling-side work is tracked in
> [`docs/CROSS_REPO_BACKLOG.md`](CROSS_REPO_BACKLOG.md): **CR-001** (Heltec
> v2 envelope bump) and **CR-003** (sibling handheld recognition of rover
> STATUS/LINK) are pending — CR-003 depends on CR-001. **CR-002** (base-side
> LoRa-RTCM transmitter) is closed not-needed now that §2.2 is retired.
>
> Until CR-001/CR-003 land, the rover's NTRIP-primary RTK path (§2.1) and the
> non-LoRa telemetry channels (status.json + HTTP, §3.1–§3.2) provide
> full end-to-end function on their own. NTRIP-only field validation
> can proceed independently — see
> [`ROADMAP.md` v1.0 Field Validation](ROADMAP.md#v10-field-validation-next).

```
┌─────────┬─────────┬─────────┬─────────┬──────────────┬─────────┐
│ Version │  Type   │ Seq LE  │ Len LE  │   Payload    │ CRC16   │
│ (1)     │ (1)     │ (2)     │ (2)     │ (Len bytes)  │ (2)     │
└─────────┴─────────┴─────────┴─────────┴──────────────┴─────────┘
```

| Field | Encoding | Notes |
|---|---|---|
| Version | `0x02` | Bumped from v1 (which was just `[0x01][display body]`) |
| Type | uint8 | See table below |
| Seq | uint16 LE | Wrapping per-source sequence |
| Len | uint16 LE | Payload length |
| Payload | N bytes | Type-specific |
| CRC16 | uint16 LE | CCITT, poly `0x1021`, init `0xFFFF`, no final XOR. Scope: Version through last Payload byte. |

**Total overhead:** 8 bytes per frame.

### Types

| ID | Name | Direction | Payload |
|---|---|---|---|
| `0x01` | STATUS | rover → handhelds / base | Rover STATUS body (10 bytes, see §3.3) |
| `0x02` | LINK | rover → handhelds / base | Rover LINK body (14 bytes, see §3.3) — defined, never sent by the rover |
| `0x10` | (retired, reserved) | — | Formerly `RTCM_CHUNK` (base → rover, `[flags:1][rtcm:N]`). Retired 2026-09-23 (DEC-031 amended); never encoded or decoded. The value stays reserved so no future type reuses it |
| `0x20` | DISPLAY | base → handhelds | Compact `/display` text body (the v1 payload kept verbatim) |
| `0x7F` | DEBUG_TEXT | any → any | ASCII string, no null terminator |

### Radio Parameters (US 915 MHz)

| Parameter | Value |
|---|---|
| Frequency | 915 MHz |
| Spreading Factor | 7 (all frame types) |
| Bandwidth | 125 kHz |
| Coding Rate | 4/5 |
| Sync Word | `0x12` (private, matches Heltec/T-Deck firmware) |

The Heltec V3 firmware runs SF7 for every frame type
(`firmware/esp32-rover/platformio.ini`). There is no higher-SF profile in use — SF9
was reserved for `RTCM_CHUNK`'s longer-range case, and that type is now retired.

---

## 5. Coordinate Handling (DEC-034)

The rover acquires and logs in SI units / WGS84. Coordinate conversion to the session's
`target_crs_epsg` happens at export time in `scripts/georef.py`.

| Profile | Default `target_crs_epsg` | Default units |
|---|---|---|
| `personal` | `0` (no conversion — keep WGS84 / local ENU) | meters |
| `arm_group` | (required, no default — operator sets per project) | US Survey Foot |

Common ARM Group EPSG codes:

| Zone | EPSG (NAD83(2011) ft-US) |
|---|---|
| PA North | `6563` |
| PA South | `6565` |
| (other zones) | confirm at first session |

**NAVD88 note:** the EPSG codes above are horizontal only. When NAVD88 output is
also requested, `scripts/georef.py` converts height via the GEOID18 grid (source CRS
NAD83(2011) geographic 3D `EPSG:6319`) into a compound CRS — the horizontal EPSG
above plus `6360` for a ftUS export, or plus `5703` for a metric one — and writes it
alongside the ellipsoidal file (`<prefix>_navd88.{ply,las}` next to
`<prefix>_ellipsoidal.{ply,las}`; see
[`SPECIFICATIONS.md` §4.4](SPECIFICATIONS.md#44-georeferenced-export-outputs)). A
missing geoid grid, or a units/CRS mismatch, exits **3** — the ellipsoidal file is
still written.

Export command:

```bash
python -m scripts.georef <session_dir> [--crs EPSG] [--units ft|m]
```

When `--crs` is omitted, the value recorded in `metadata.json` at session start is used.

---

## 6. Project Folder Conventions (arm_group profile)

When the rover is operated under `arm_group` profile, session output is intended to
drop into the ARM Group survey folder structure:

```
/Survey
  /<ProjectCode>_Survey
    /01_Raw
      /LiDAR
        /Rover                     ← rover sessions land here (new subfolder)
          /scan_YYYYMMDD_HHMMSS/
            ├── config.toml        ← session config snapshot
            ├── scan.jsonl
            ├── gnss.jsonl
            ├── images/
            └── metadata.json
```

The rover's `[logging].output_dir` should be set to
`/path/to/<ProjectCode>_Survey/01_Raw/LiDAR/Rover/` for ARM Group sessions. Personal
sessions can use any path.

This split is not yet documented in the sibling repo — `arm-drone-lidar-workflow`'s
`base-station/docs/lidar-rover-integration.md` (or equivalent) does not exist at the
sibling's tip (only an `_archive/` copy does). Filed sibling-side as
[`CR-004`](CROSS_REPO_BACKLOG.md#cr-004--document-01_rawlidarrover-subfolder-split-in-sibling-docs),
pending a sibling docs PR.

---

## 7. Failure Modes

| Failure | Detection | Rover behavior |
|---|---|---|
| NTRIP caster unreachable | TCP connect timeout (`_CONNECT_TIMEOUT_SEC`, 5 s) raises `OSError`/`TimeoutError` | Logged via Python logging (not a JSONL event); reconnect backoff doubles toward the 30 s cap; continues with degraded GNSS — there is no LoRa fallback (§2.2 retired) |
| NTRIP auth/mountpoint rejection within the 3 s startup grace, `arm_group` profile | `401`/`404` before `_NTRIP_FATAL_GRACE_SEC` elapses | Refuses to start — process exits **4**; `personal` profile warns and continues instead |
| Same rejection found mid-session, `arm_group` profile | Same latch, checked on every status publish | Logged once ("NTRIP fatal mid-session"); `scan_state = SCAN_ERROR` published continuously; session keeps logging without RTK — no exit |
| Caster rejects the handshake (busy mountpoint, 503, or an early-closed handshake) | Non-fatal `NtripError` | Retries every 30 s flat — no backoff growth |
| Caster evicts this client — another authenticates (§2.3) | Clean stream close, or a TCP reset (`OSError`) | Clean close resets reconnect backoff to 1 s; a reset doubles the current backoff toward the 30 s cap |
| `status.json` write fails | `OSError` on rename | Log warning at 1/min cadence; other publishers unaffected |
| Conflicting CRS at export | `metadata.json.session.target_crs_epsg = 0` in `arm_group` profile | `scripts/georef.py` exits non-zero and demands `--crs` |

---

## 8. Cross-References

| Concept | This repo | arm-drone-lidar-workflow |
|---|---|---|
| Atomic JSON write | `src/rover/telemetry.py` (port of) | `base-station/rtk_io.py:atomic_write_json` |
| Status schema | This doc §3.1 | `base-station/rtk_io.py:STATUS_SCHEMA_VERSION` |
| LoRa frame envelope | This doc §4 | `base-station/heltec-display/src/main.cpp` (v1 today; v2 pending `CR-001`) |
| NTRIP caster | (consumer) | `base-station/rtk_base_manager.py` (caster lifecycle) |
| Caster sharing rule | This doc §2.3 | `base-station/rtk_base_manager.py` (`NTRIPServer`, single-client, backlog `NC-1`) |
| Decision records | `docs/DECISIONS.md` DEC-030..DEC-035 (DEC-031 amended 2026-09-23) | `docs/decisions/decision-log.md` |
