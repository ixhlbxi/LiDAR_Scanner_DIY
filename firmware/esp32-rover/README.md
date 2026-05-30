# Rover ESP32 Firmware

PlatformIO project for the rover-side ESP32. Two build environments:

| Env | Role | Replaces in rover |
|---|---|---|
| `lora_rtcm_relay` (default) | Receives RTCM_CHUNK (LoRa frame v2 type=`0x10`) from the Base-Station Heltec, writes to F9P UART2. Also relays STATUS/LINK (`0x01`/`0x02`) that the Pi pushes over USB. | RTK fallback for off-network operation (DEC-031). |
| `ntrip_client` | Connects to NTRIP caster over WiFi (default `rtk-base.local:2101/ARM_BASE`), streams RTCM into F9P UART2 directly. Same STATUS/LINK passthrough. | Alternate RTK path that keeps the Pi out of the correction stream (DEC-032). |

See `../../docs/BASE_STATION_INTEGRATION.md` for the protocol contract and
`../../docs/DECISIONS.md` DEC-031/DEC-032 for the design rationale.

## Hardware target

- **Heltec WiFi LoRa 32 V3** (ESP32-S3 + SX1262 + WiFi) — same module the
  Base-Station uses in `ixhlbxi/arm-drone-lidar-workflow/base-station/heltec-display/`.

Bare ESP32 + standalone SX1262 breakouts work too — update the LoRa pin map at
the top of `src/main.cpp`. The `ntrip_client` env requires a WiFi-capable board.

## Wiring

| ESP32 pin | Connects to | Purpose |
|---|---|---|
| GPIO 17 (TX) | ZED-F9P UART2 RX | RTCM3 → F9P |
| GPIO 18 (RX) | ZED-F9P UART2 TX (optional) | Unused for RTCM; wire for symmetry |
| USB-C | Raspberry Pi USB | Telemetry frame passthrough (Pi → LoRa) |
| LoRa antenna | SMA on board | Required before any transmit (PA damage risk) |

## Build & flash

```bash
# Default — LoRa RTCM relay
pio run -e lora_rtcm_relay -t upload

# NTRIP over WiFi
pio run -e ntrip_client -t upload

# Serial console (115200)
pio device monitor
```

## Configuration

Credentials and tunables live in `include/config.h` (gitignored). Copy the
template before flashing:

```bash
cp include/config.h.example include/config.h
$EDITOR include/config.h
```

Fields:

| Field | Used in | Notes |
|---|---|---|
| `WIFI_SSID` / `WIFI_PASSWORD` | `ntrip_client` only | Field WiFi or Pi-as-AP credentials |
| `NTRIP_HOST` / `NTRIP_PORT` | `ntrip_client` only | Default `rtk-base.local` / `2101` |
| `NTRIP_MOUNTPOINT` | `ntrip_client` only | Default `ARM_BASE` (matches arm-drone-lidar-workflow) |
| `NTRIP_USERNAME` / `NTRIP_PASSWORD` | `ntrip_client` only | Get the password from the Base-Station owner |
| `ROVER_DEVICE_NAME` | both | Identifies this rover in telemetry; ≤16 chars |
| `NTRIP_GGA_INTERVAL_SEC` | `ntrip_client` only | 0 disables; needed for VRS-style casters |

## LoRa parameters

Hard-coded in `platformio.ini` build flags to match the Base-Station Heltec
firmware (see `arm-drone-lidar-workflow/base-station/heltec-display/src/main.cpp`).

| Parameter | Value |
|---|---|
| Frequency | 915 MHz (US ISM) |
| Spreading Factor | 7 |
| Bandwidth | 125 kHz |
| Coding Rate | 4/5 |
| Sync Word | `0x12` (private) |
| TX Power | 14 dBm |

## Protocol

All LoRa frames use the v2 envelope:

```
[Version=0x02][Type:1][Seq:2 LE][Len:2 LE][Payload :N][CRC16-CCITT LE :2]
```

CRC16-CCITT poly `0x1021`, init `0xFFFF`, no final XOR. Scope: Version through
last Payload byte. Receivers MUST drop unknown versions or types.

Types this firmware handles:

| Type | Direction | Action |
|---|---|---|
| `0x01` STATUS | Pi → USB → LoRa | Relayed as-is onto LoRa |
| `0x02` LINK | Pi → USB → LoRa | Relayed as-is onto LoRa |
| `0x10` RTCM_CHUNK | LoRa → F9P UART2 (Mode A only) | Strip 1-byte flags, write RTCM payload to F9P |

Unhandled in v0.10:
- Frame fragmentation reassembly for RTCM messages > one frame (works in
  practice because the F9P happily accepts arbitrary chunking — the chunks
  reassemble at the RTCM3 protocol layer inside the F9P).
- ESP32-originated STATUS/LINK (currently we relay what the Pi pushes; future
  v1.1 could measure local LoRa RSSI/SNR and emit our own LINK frames).

## Verification

After flashing in `lora_rtcm_relay` mode:

1. Power on with antenna attached.
2. Open serial monitor — expect `[boot] mode = lora_rtcm_relay` and
   `[lora] init ok, rx armed`.
3. Trigger the Base-Station Heltec to send a v2 RTCM_CHUNK frame (Phase D
   work in the other repo).
4. Watch the F9P transition into RTK FLOAT then RTK FIX via NMEA GGA on its
   USB output (`tests/hardware/test_ntrip.py` does this end-to-end).

In `ntrip_client` mode:

1. Confirm WiFi join in the serial monitor (`[wifi] joining ...`).
2. Confirm NTRIP connect (`[ntrip] connected, streaming RTCM to F9P UART2`).
3. Same RTK FIX confirmation as above.

## Open items (v1.1+)

- True RTCM_CHUNK fragmentation (currently relies on per-frame integrity).
- OTA updates.
- Local STATUS/LINK frames (ESP32-measured, not Pi-relayed).
- Mode switching at runtime via a USB command instead of build-time.
