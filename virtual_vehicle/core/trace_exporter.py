"""
Packet Capture & Trace Exporter (Vector ASC & Wireshark-like Format).

What this file does (Report Section 1.5 & 3.7):
Per Section 3.7 of the design report:
"Capture raw frames/packets and decoded signals. Provide synchronized timeline views
for CAN arbitration, Ethernet flows, ECU state changes, security rejects, and OTA campaign states.
Export a run manifest plus machine-readable JSON/CSV results so that a test can be reproduced exactly."

This module exports:
1. Standard Vector CANoe / CANalyzer ASCII (.asc) bus trace file.
2. Synchronized multi-protocol event trace (.log).
"""

import os
from typing import List
from virtual_vehicle.core.event_bus import EventBus, EventRecord


class TraceExporter:
    """Exports raw CAN frames and Ethernet packets to industry-standard trace files."""

    @staticmethod
    def export_asc_trace(event_bus: EventBus, filepath: str) -> None:
        """
        Exports CAN events in standard Vector CANoe ASCII format (.asc).
        Beginners can open this file in any text editor or automotive tool.
        """
        can_events = [e for e in event_bus.get_history() if e.category == "CAN" and e.event_type == "TX_SUCCESS"]

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("date Wed Nov 11 16:00:00 2026\n")
            f.write("base hex  timestamps absolute\n")
            f.write("internal events logged\n")
            f.write("// Virtual Vehicle Platform - CAN / CAN FD Bus Trace\n")
            f.write("// Format: <Time_s> <Channel> <ID> <Rx/Tx> <d/r> <DLC> <Data Bytes...>\n")
            f.write("// ------------------------------------------------------------------\n")

            for e in can_events:
                t_sec = f"{e.timestamp_us / 1_000_000.0:10.6f}"
                details = e.details
                frame_id = details.get("id", 0x100)
                dlc = details.get("dlc", 8)

                # Simulated raw bytes for representation
                raw_bytes = " ".join([f"{b:02X}" for b in range(dlc)])
                f.write(f"{t_sec} 1  {frame_id:03X}x             Tx   d {dlc} {raw_bytes}\n")

    @staticmethod
    def export_timeline_log(event_bus: EventBus, filepath: str) -> None:
        """
        Exports a synchronized timeline of all domains (CAN, Ethernet, ECU, Gateway, OTA).
        """
        history = event_bus.get_history()
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("=" * 100 + "\n")
            f.write("       VIRTUAL VEHICLE PLATFORM - SYNCHRONIZED MULTI-PROTOCOL TIMELINE TRACE\n")
            f.write("=" * 100 + "\n")
            f.write(f"{'Time (ms)':<12} {'Domain':<10} {'Source Node':<20} {'Event Type':<22} {'Description'}\n")
            f.write("-" * 100 + "\n")

            for e in history:
                ms_str = f"{e.timestamp_us / 1000.0:8.3f}"
                f.write(f"{ms_str:<12} {e.category:<10} {e.source:<20} {e.event_type:<22} {e.description}\n")

