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

## How to use this file

- **Adding an item:** when you find a "rover side codes for X, sibling side
  doesn't have X yet" gap, record it here so future-you doesn't waste time
  searching for the missing piece.
- **Closing an item:** when the sibling PR lands, change Status to `✅`,
  add the sibling commit SHA, and on the next rover-docs pass, fold the
  cross-references into the relevant doc bodies (delete the "pending" caveats).
- **No silent deletes:** keep closed items here as historical record;
  prepend `[CLOSED YYYY-MM-DD]` to the title.
