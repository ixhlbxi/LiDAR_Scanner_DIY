# Base-Station Integration

**Document Status:** v0.10 — overhaul authoritative contract
**Companion repo:** `ixhlbxi/arm-drone-lidar-workflow`
**Last Updated:** 2026-05-23

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
| `personal` (default) | DIY use, off-grid, no project conventions | WGS84 / local ENU output; NTRIP optional; LoRa STATUS/LINK on; HTTP `/status` typical observability |
| `arm_group` | Companion to ARM Group drone/LiDAR survey workflow | NTRIP required (default mountpoint `ARM_BASE`); project code + mission tag required; output in session-recorded CRS (e.g., NAD83(2011) / PA-N / ft-US); `status.json` published to a path the Base-Station's existing tooling can read |

Selection is per session via `[session].profile` in the rover's TOML config.
See DEC-030 in `docs/DECISIONS.md`.

---

## 2. RTK Correction Paths

Two transports, NTRIP primary, LoRa fallback. The rover never enables both at once
for the same F9P input — that's the F9P's job to multiplex if both physical paths
were wired, which we don't.

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

```
┌──────────────────────────┐                     ┌──────────────────────────┐
│  Base-Station Heltec V3  │   915 MHz LoRa      │  Rover ESP32             │
│  (LoRa frame v2 type=    │ ──────────────────► │  (decodes RTCM_CHUNK,    │
│  0x10 RTCM_CHUNK)        │   SF7/BW125/CR4/5   │  pipes to F9P UART2)     │
└──────────────────────────┘                     └────────────┬─────────────┘
                                                              │
                                                              ▼
                                                ┌─────────────────────────┐
                                                │  Rover ZED-F9P UART2    │
                                                └─────────────────────────┘
```

LoRa frame v2 is described in §4 below. The Base-Station-side LoRa-RTCM transmitter
ships in `arm-drone-lidar-workflow`'s Phase D PR.

---

## 3. Telemetry — Three Independent Channels (DEC-033)

Each channel is independently enable-able via config. None is required.

### 3.1 Channel A — Base-Station-compatible `status.json`

Default path: `/run/rover/status.json`. Atomic write via mkstemp + rename, mirroring
`arm-drone-lidar-workflow/base-station/rtk_io.py:atomic_write_json`. Any process that
already knows how to read the Base-Station's `/run/rtk-base/status.json` can read the
rover's too — same shape, separate schema version.

**Rover-side schema v1:**

```json
{
  "schema_version": 1,
  "timestamp_epoch": 1716480000.123,
  "device": "rover-01",
  "profile": "arm_group",
  "mission": "WENTZ",
  "project_code": "2026-WENTZ-LIDR",
  "scan_state": "SCANNING",
  "fix_type": 5,
  "sat_count": 18,
  "hdop": 0.85,
  "lat": 40.7128,
  "lon": -74.0060,
  "alt_m": 10.5,
  "rtk_age_s": 1.2,
  "battery_mv": 11800,
  "lora_link_rssi": -78,
  "lora_link_snr": 9,
  "ntrip_connected": true,
  "ntrip_bytes_per_sec": 850
}
```

`schema_version` is versioned independently from the Base-Station's
`STATUS_SCHEMA_VERSION` (currently v7 in base, v1 in rover). Adding a field is a minor
bump; removing or renaming is a major bump.

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

LoRa frame v2 (§4) with `type = 0x01` (STATUS) or `0x02` (LINK). Same payload bodies
as the original Appendix C in `CLAUDE.md`:

- STATUS (10 bytes): `fix_type, sat_count, hdop×100, battery_mv, scan_state, 3×reserved`
- LINK (14 bytes): `rssi+128, snr+128, rx_count, tx_count, err_count, 2×reserved`

Cadence configurable via `[lora].telemetry_interval_sec` (default `1.0`).

Survives the no-network case (Channels A and B require IP / filesystem). On-air bandwidth
multiplexed with RTCM_CHUNK frames; STATUS/LINK packets are short (~30 B framed) and
infrequent, so collision with RTCM is acceptable.

---

## 4. LoRa Frame v2

Shared envelope used by both repos. Strict superset of the original Appendix C and the
Heltec v1 display frame — receivers that only understood v1 (display body) MUST reject
v2 frames; v2-aware receivers handle both by dispatching on `type`.

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
| `0x02` | LINK | rover → handhelds / base | Rover LINK body (14 bytes, see §3.3) |
| `0x10` | RTCM_CHUNK | base → rover | `[flags:1][rtcm:N]`; flags bit 0 = more fragments follow |
| `0x20` | DISPLAY | base → handhelds | Compact `/display` text body (the v1 payload kept verbatim) |
| `0x7F` | DEBUG_TEXT | any → any | ASCII string, no null terminator |

### Radio Parameters (US 915 MHz)

| Parameter | Value |
|---|---|
| Frequency | 915 MHz |
| Spreading Factor | 7 (DISPLAY/STATUS/LINK) or 9 (RTCM_CHUNK if range > throughput) |
| Bandwidth | 125 kHz |
| Coding Rate | 4/5 |
| Sync Word | `0x12` (private, matches Heltec/T-Deck firmware) |

The Heltec V3 firmware currently runs SF7 for DISPLAY. RTCM_CHUNK can run at SF7 too
(throughput ~5 kbps is comfortable for the "robust" RTCM profile's ~800 B/s). Higher
SF is reserved for the "marginal link" tuning later.

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
| PA North | `6346` |
| PA South | `6347` |
| (other zones) | confirm at first session |

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

This split is documented separately in `arm-drone-lidar-workflow/base-station/docs/
lidar-rover-integration.md` (Phase D deliverable in that repo).

---

## 7. Failure Modes

| Failure | Detection | Rover behavior |
|---|---|---|
| NTRIP caster unreachable | TCP connect timeout (5 s) | Log `event=ntrip_disconnect`; if LoRa configured, fall back automatically; else continue with degraded GNSS |
| NTRIP auth rejected | 401 on connect | Refuse to start in `arm_group` profile (loud failure); warn-and-continue in `personal` |
| LoRa link loss (fallback mode) | No RTCM_CHUNK frame for 10 s | Log `event=lora_rtcm_loss`; F9P degrades to FLOAT/3D; resume on next frame |
| `status.json` write fails | OSError on rename | Log warning at 1/min cadence; other publishers unaffected |
| Conflicting CRS at export | `metadata.json.session.target_crs_epsg = 0` in `arm_group` profile | `scripts/georef.py` exits non-zero and demands `--crs` |

---

## 8. Cross-References

| Concept | This repo | arm-drone-lidar-workflow |
|---|---|---|
| Atomic JSON write | `src/rover/telemetry.py` (port of) | `base-station/rtk_io.py:atomic_write_json` |
| Status schema | This doc §3.1 | `base-station/rtk_io.py:STATUS_SCHEMA_VERSION` |
| LoRa frame envelope | This doc §4 | `base-station/heltec-display/src/main.cpp` (v1 today, v2 after Phase D) |
| NTRIP caster | (consumer) | `base-station/rtk_base_manager.py` (caster lifecycle) |
| Decision records | `docs/DECISIONS.md` DEC-030..DEC-034 | `docs/decisions/decision-log.md` |
