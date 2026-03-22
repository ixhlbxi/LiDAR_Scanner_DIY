"""
Telemetry status packet generation for LoRa transmission.

Generates STATUS and LINK packets (per LoRa packet format spec)
and sends them to the ESP32 via serial for LoRa broadcast.

The monitoring terminal (T-Deck) receives these packets and
displays rover status. T-Deck is receive-only in v1.0 (D-010).

Packet format:
  Sync (0xAA55) | Version | Type | Length | Sequence | Payload | CRC16

Decision references:
    D-008  LoRa parameters
    D-009  Packet loss tolerance
    D-010  T-Deck receive-only

Dependencies:
    pyserial
"""

from __future__ import annotations

import logging

from rover.config import LoraConfig

logger = logging.getLogger(__name__)


class TelemetrySender:
    """Generates and sends telemetry packets to ESP32 for LoRa broadcast.

    Args:
        config: LoraConfig section from rover config.
    """

    def __init__(self, config: LoraConfig) -> None:
        self._config = config
        self._sequence = 0
        logger.info("TelemetrySender initialized (port=%s, interval=%.1fs)",
                     config.port, config.telemetry_interval_sec)

    def start(self) -> None:
        """Open serial connection to ESP32."""
        raise NotImplementedError("TelemetrySender.start() not yet implemented")

    def stop(self) -> None:
        """Close serial connection."""
        raise NotImplementedError("TelemetrySender.stop() not yet implemented")

    def send_status(
        self,
        fix_type: int,
        sat_count: int,
        hdop: float,
        battery_mv: int,
        scan_state: int,
    ) -> None:
        """Build and send a STATUS packet (type 0x01)."""
        raise NotImplementedError("TelemetrySender.send_status() not yet implemented")

    def send_link(
        self,
        rssi: int,
        snr: int,
        rx_count: int,
        tx_count: int,
        err_count: int,
    ) -> None:
        """Build and send a LINK packet (type 0x02)."""
        raise NotImplementedError("TelemetrySender.send_link() not yet implemented")
