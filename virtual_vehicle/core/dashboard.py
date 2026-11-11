"""
Observability Dashboard & Metrics Reporter (Report Section 1.5 & 3.7).

What this file does:
Provides visual summaries and tabular reports for the simulation run:
- ECU Status Table (State, Active Slot, Running Version, Active DTCs)
- CAN Bus Performance Metrics (Total Frames, Collisions Resolved, Bus Load %, Average Latency)
- Ethernet Switch Metrics (Frames Forwarded, VLAN Drops, Bytes Transmitted)
- Security & Gateway Audit (Policy Denials, Rate Limit Drops, SecOC Checks)
"""

from typing import Dict, Any, List
from virtual_vehicle.can.bus import CANBus
from virtual_vehicle.ethernet.switch import EthernetSwitch
from virtual_vehicle.ecu.base_ecu import BaseECU
from virtual_vehicle.core.event_bus import EventBus


class VehicleDashboard:
    """Renders formatted simulation metrics and vehicle health dashboard."""

    @staticmethod
    def render(ecus: List[BaseECU], can_bus: CANBus, switch: EthernetSwitch, event_bus: EventBus) -> str:
        lines = []
        lines.append("=" * 80)
        lines.append("                   VIRTUAL VEHICLE PLATFORM DASHBOARD")
        lines.append("=" * 80)

        # 1. ECU Fleet Health Table
        lines.append("\n[1] ECU FLEET HEALTH & FIRMWARE STATUS:")
        lines.append("-" * 80)
        lines.append(f"{'ECU Name':<18} {'State':<14} {'Slot':<6} {'Version':<10} {'DTCs Logged'}")
        lines.append("-" * 80)
        for ecu in ecus:
            dtc_str = ", ".join(ecu.uds.active_dtcs) if ecu.uds.active_dtcs else "None"
            lines.append(f"{ecu.name:<18} {ecu.state.value:<14} {ecu.active_slot:<6} {ecu.current_version:<10} {dtc_str}")

        # 2. CAN Bus Metrics Table
        lines.append("\n[2] CAN / CAN FD BUS METRICS:")
        lines.append("-" * 80)
        latencies = []
        for l_list in can_bus.stats.latencies_us.values():
            latencies.extend(l_list)
        avg_latency_ms = (sum(latencies) / len(latencies) / 1000.0) if latencies else 0.0

        lines.append(f"  • Total Frames Transmitted:     {can_bus.stats.total_frames_sent}")
        lines.append(f"  • Arbitrations Resolved:        {can_bus.stats.total_arbitrations}")
        lines.append(f"  • Collisions Resolved:          {can_bus.stats.total_collisions_resolved}")
        lines.append(f"  • Bus Transmission Errors:      {can_bus.stats.total_errors}")
        lines.append(f"  • Automatic Retransmissions:    {can_bus.stats.total_retransmissions}")
        lines.append(f"  • Average Delivery Latency:     {avg_latency_ms:.3f} ms")

        # 3. Ethernet Switch Metrics Table
        lines.append("\n[3] AUTOMOTIVE ETHERNET SWITCH METRICS:")
        lines.append("-" * 80)
        lines.append(f"  • Frames Forwarded:             {switch.stats.frames_forwarded}")
        lines.append(f"  • VLAN Policy Drops:            {switch.stats.frames_dropped_vlan}")
        lines.append(f"  • Injected Packet Loss Drops:   {switch.stats.frames_dropped_loss_injection}")
        lines.append(f"  • Total Data Transferred:       {switch.stats.total_bytes_transmitted} bytes")

        # 4. Security & Audit Events
        lines.append("\n[4] SECURITY & GATEWAY AUDIT SUMMARY:")
        lines.append("-" * 80)
        history = event_bus.get_history()
        sec_rejects = [e for e in history if "REJECT" in e.event_type or "DENY" in e.event_type or "VIOLATION" in e.event_type]
        ota_events = [e for e in history if e.category == "OTA"]

        lines.append(f"  • Total Security Policy Rejects: {len(sec_rejects)}")
        lines.append(f"  • Total OTA Campaign Transitions: {len(ota_events)}")
        if sec_rejects:
            lines.append("  • Recent Security Audit Traces:")
            for r in sec_rejects[-3:]:
                lines.append(f"    - [{r.timestamp_us / 1000.0:6.2f} ms] [{r.source}] {r.description}")

        lines.append("=" * 80)
        return "\n".join(lines)

