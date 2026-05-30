// ---------------------------------------------------------------------------
// Rover ESP32 firmware — two modes (DEC-031, DEC-032)
//
//   Mode A: lora_rtcm_relay   (default; preserves DEC-006 robustness)
//     - LoRa Rx: receives RTCM_CHUNK (LoRa frame v2 type=0x10) from the
//       arm-drone-lidar-workflow Base-Station Heltec, writes RTCM3 to F9P UART2.
//     - USB Rx: STATUS/LINK fields pushed from the Pi as raw LoRa-frame-v2
//       bytes (already encoded by src/rover/telemetry.py:LoRaPublisher). We
//       just relay them onto LoRa.
//
//   Mode B: ntrip_client      (alternate)
//     - WiFi: connect to NTRIP caster (mountpoint ARM_BASE on rtk-base.local
//       by default), stream RTCM into F9P UART2 directly.
//     - USB Rx + LoRa Tx: same as Mode A.
//
// Both modes also support a passthrough USB→LoRa "outbound" path: anything
// the Pi writes to our USB serial that looks like a v2 frame (starts with
// 0x02 version byte, valid header length) is relayed onto LoRa.
//
// LoRa frame v2 envelope:
//     [Version=0x02][Type:1][Seq:2 LE][Len:2 LE][Payload :N][CRC16-CCITT LE :2]
//
// Authoritative protocol spec:
//     ../../docs/BASE_STATION_INTEGRATION.md §4
//     ../../CLAUDE.md Appendix C
//
// Build:
//     pio run -e lora_rtcm_relay -t upload   # default
//     pio run -e ntrip_client    -t upload
//
// Configuration:
//     Before flashing: cp include/config.h.example include/config.h
//     Edit include/config.h with your WiFi + NTRIP credentials.
// ---------------------------------------------------------------------------

#include <Arduino.h>
#include <SPI.h>
#include <RadioLib.h>

#if defined(ROVER_MODE_NTRIP_CLIENT)
  #include <WiFi.h>
  #include <WiFiClient.h>
  #include "base64.h"
#endif

#include "config.h"

// ---------------------------------------------------------------------------
// Pin map — Heltec V3 SX1262 (matches Base-Station Heltec wiring)
// ---------------------------------------------------------------------------
static const int PIN_LORA_NSS  = 8;
static const int PIN_LORA_SCK  = 9;
static const int PIN_LORA_MOSI = 10;
static const int PIN_LORA_MISO = 11;
static const int PIN_LORA_RST  = 12;
static const int PIN_LORA_BUSY = 13;
static const int PIN_LORA_DIO1 = 14;

// F9P UART2 — wire to the F9P's UART2 RX (RTCM input on the receiver).
static const int PIN_F9P_TX = 17;  // ESP32 TX → F9P UART2 RX
static const int PIN_F9P_RX = 18;  // ESP32 RX ← F9P UART2 TX (unused for RTCM but wire it)
HardwareSerial F9PSerial(2);

// ---------------------------------------------------------------------------
// LoRa frame v2
// ---------------------------------------------------------------------------
static const uint8_t FRAME_VERSION = 0x02;

// Same poly as base-station/heltec-display + rover.lora_protocol.
static uint16_t crc16_ccitt(const uint8_t* data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= ((uint16_t) data[i]) << 8;
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x8000) ? ((crc << 1) ^ 0x1021) : (crc << 1);
        }
    }
    return crc;
}

// Encode a v2 frame in-place. Returns total frame length, or 0 on error.
static size_t encode_frame_v2(uint8_t type, uint16_t seq, const uint8_t* payload,
                              uint16_t payload_len, uint8_t* out, size_t out_cap) {
    const size_t total = 6 + payload_len + 2;
    if (total > out_cap) return 0;
    out[0] = FRAME_VERSION;
    out[1] = type;
    out[2] = (uint8_t)(seq & 0xFF);
    out[3] = (uint8_t)((seq >> 8) & 0xFF);
    out[4] = (uint8_t)(payload_len & 0xFF);
    out[5] = (uint8_t)((payload_len >> 8) & 0xFF);
    memcpy(out + 6, payload, payload_len);
    uint16_t crc = crc16_ccitt(out, 6 + payload_len);
    out[6 + payload_len]     = (uint8_t)(crc & 0xFF);
    out[6 + payload_len + 1] = (uint8_t)((crc >> 8) & 0xFF);
    return total;
}

// ---------------------------------------------------------------------------
// LoRa radio
// ---------------------------------------------------------------------------
SX1262 radio = new Module(PIN_LORA_NSS, PIN_LORA_DIO1, PIN_LORA_RST, PIN_LORA_BUSY);
static bool g_lora_ready = false;
static volatile bool g_lora_rx_flag = false;

static void IRAM_ATTR isr_lora_rx() { g_lora_rx_flag = true; }

static void lora_init() {
    SPI.begin(PIN_LORA_SCK, PIN_LORA_MISO, PIN_LORA_MOSI, PIN_LORA_NSS);
    int state = radio.begin(
        LORA_FREQ_MHZ, LORA_BW_KHZ, LORA_SF, LORA_CR_DENOM,
        LORA_SYNC_PRIVATE, LORA_TX_POWER_DBM,
        8 /* preamble */, LORA_TCXO_VOLTAGE, false
    );
    if (state == RADIOLIB_ERR_NONE) {
        radio.setDio2AsRfSwitch(true);
        radio.setPacketReceivedAction(isr_lora_rx);
        radio.startReceive();
        g_lora_ready = true;
        Serial.println("[lora] init ok, rx armed");
    } else {
        Serial.printf("[lora] begin failed: %d\n", state);
    }
}

// Forward a received LoRa frame to the F9P (if it's an RTCM_CHUNK).
static void lora_handle_rx() {
    if (!g_lora_rx_flag) return;
    g_lora_rx_flag = false;

    uint8_t buf[256];
    int rx_len = radio.getPacketLength();
    if (rx_len <= 0 || rx_len > (int) sizeof(buf)) {
        radio.startReceive();
        return;
    }
    int state = radio.readData(buf, rx_len);
    radio.startReceive();
    if (state != RADIOLIB_ERR_NONE) return;
    if (rx_len < 8) return;
    if (buf[0] != FRAME_VERSION) return;

    uint8_t type = buf[1];
    uint16_t seq = buf[2] | ((uint16_t) buf[3] << 8);
    uint16_t len = buf[4] | ((uint16_t) buf[5] << 8);
    if ((size_t) rx_len != 6 + (size_t) len + 2) return;

    uint16_t crc_expected = crc16_ccitt(buf, 6 + len);
    uint16_t crc_got = buf[6 + len] | ((uint16_t) buf[6 + len + 1] << 8);
    if (crc_got != crc_expected) return;

    if (type == 0x10 /* RTCM_CHUNK */) {
        // payload: [flags:1][rtcm bytes...] — flags bit 0 = more fragments follow.
        // F9P doesn't care about our chunking; just write the RTCM payload through.
        if (len >= 1) {
            F9PSerial.write(buf + 7, len - 1);
        }
        (void) seq;
    }
    // Other types (STATUS, LINK, DISPLAY, DEBUG_TEXT) are not relevant for the rover-side Rx role.
}

// ---------------------------------------------------------------------------
// USB↔LoRa passthrough — Pi-driven STATUS/LINK frames forwarded to LoRa
// ---------------------------------------------------------------------------
static uint8_t g_usb_buf[256];
static size_t g_usb_buf_pos = 0;
static uint32_t g_usb_byte_deadline_ms = 0;

static void usb_passthrough() {
    while (Serial.available()) {
        int c = Serial.read();
        if (c < 0) break;
        if (g_usb_buf_pos < sizeof(g_usb_buf)) {
            g_usb_buf[g_usb_buf_pos++] = (uint8_t) c;
        }
        g_usb_byte_deadline_ms = millis() + 50;  // commit ≥50ms after last byte
    }

    if (g_usb_buf_pos >= 8 && millis() > g_usb_byte_deadline_ms) {
        // Try to parse a single frame; relay it onto LoRa if valid.
        if (g_usb_buf[0] == FRAME_VERSION) {
            uint16_t len = g_usb_buf[4] | ((uint16_t) g_usb_buf[5] << 8);
            size_t total = 6 + len + 2;
            if (total == g_usb_buf_pos) {
                uint16_t crc_expected = crc16_ccitt(g_usb_buf, 6 + len);
                uint16_t crc_got = g_usb_buf[6 + len] | ((uint16_t) g_usb_buf[6 + len + 1] << 8);
                if (crc_got == crc_expected && g_lora_ready) {
                    radio.transmit(g_usb_buf, total);
                    radio.startReceive();
                }
            }
        }
        g_usb_buf_pos = 0;
    }
}

// ---------------------------------------------------------------------------
// NTRIP client (Mode B only)
// ---------------------------------------------------------------------------
#if defined(ROVER_MODE_NTRIP_CLIENT)
static WiFiClient g_ntrip_socket;
static uint32_t g_ntrip_last_connect_ms = 0;
static bool g_ntrip_connected = false;

static void ntrip_connect() {
    g_ntrip_last_connect_ms = millis();
    Serial.printf("[ntrip] connecting to %s:%d/%s as %s\n",
                  NTRIP_HOST, NTRIP_PORT, NTRIP_MOUNTPOINT, NTRIP_USERNAME);
    if (!g_ntrip_socket.connect(NTRIP_HOST, NTRIP_PORT)) {
        Serial.println("[ntrip] TCP connect failed");
        return;
    }
    String creds = String(NTRIP_USERNAME) + ":" + String(NTRIP_PASSWORD);
    String auth = base64::encode(creds);
    g_ntrip_socket.printf("GET /%s HTTP/1.1\r\n", NTRIP_MOUNTPOINT);
    g_ntrip_socket.printf("Host: %s\r\n", NTRIP_HOST);
    g_ntrip_socket.print("User-Agent: PiLiDAR-RTK-Rover-ESP32/0.10 (NTRIP)\r\n");
    g_ntrip_socket.print("Ntrip-Version: Ntrip/2.0\r\n");
    g_ntrip_socket.printf("Authorization: Basic %s\r\n", auth.c_str());
    g_ntrip_socket.print("Connection: close\r\n\r\n");

    // Read response headers; succeed only on HTTP 200 / ICY 200.
    uint32_t deadline = millis() + 5000;
    String status_line;
    while (millis() < deadline) {
        if (g_ntrip_socket.available()) {
            int c = g_ntrip_socket.read();
            if (c == '\n') break;
            if (c != '\r') status_line += (char) c;
        }
    }
    if (!(status_line.indexOf("200") >= 0)) {
        Serial.printf("[ntrip] caster rejected: %s\n", status_line.c_str());
        g_ntrip_socket.stop();
        return;
    }
    // Skip remaining headers (until empty line).
    int blanks = 0;
    deadline = millis() + 3000;
    while (millis() < deadline && blanks < 2) {
        if (g_ntrip_socket.available()) {
            int c = g_ntrip_socket.read();
            if (c == '\n') blanks++;
            else if (c != '\r') blanks = 0;
        }
    }
    g_ntrip_connected = true;
    Serial.println("[ntrip] connected, streaming RTCM to F9P UART2");
}

static void ntrip_pump() {
    if (!g_ntrip_connected) {
        if (millis() - g_ntrip_last_connect_ms > 5000) {
            if (WiFi.status() == WL_CONNECTED) ntrip_connect();
        }
        return;
    }
    if (!g_ntrip_socket.connected()) {
        Serial.println("[ntrip] caster closed, will reconnect");
        g_ntrip_socket.stop();
        g_ntrip_connected = false;
        return;
    }
    while (g_ntrip_socket.available()) {
        uint8_t buf[256];
        int n = g_ntrip_socket.read(buf, sizeof(buf));
        if (n > 0) {
            F9PSerial.write(buf, n);
        }
    }
}

static void wifi_init() {
    Serial.printf("[wifi] joining %s\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}
#endif  // ROVER_MODE_NTRIP_CLIENT

// ---------------------------------------------------------------------------
// Arduino lifecycle
// ---------------------------------------------------------------------------

void setup() {
    Serial.begin(PI_USB_BAUD);
    F9PSerial.begin(F9P_UART2_BAUD, SERIAL_8N1, PIN_F9P_RX, PIN_F9P_TX);
    delay(100);

#if defined(ROVER_MODE_LORA_RTCM_RELAY)
    Serial.println("[boot] mode = lora_rtcm_relay");
#elif defined(ROVER_MODE_NTRIP_CLIENT)
    Serial.println("[boot] mode = ntrip_client");
    wifi_init();
#else
    #error "No rover mode selected; set ROVER_MODE_LORA_RTCM_RELAY or ROVER_MODE_NTRIP_CLIENT"
#endif

    lora_init();
}

void loop() {
    // Always — handle inbound LoRa frames (RTCM in Mode A; STATUS-from-other-rovers
    // in any) and Pi-driven outbound frames.
    lora_handle_rx();
    usb_passthrough();

#if defined(ROVER_MODE_NTRIP_CLIENT)
    ntrip_pump();
#endif
}
