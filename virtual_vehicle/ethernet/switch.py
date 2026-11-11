"""
Switched Automotive Ethernet Model (Full-Duplex, IEEE 802.1Q VLANs, 100BASE-T1 / 1000BASE-T1).

What this file does:
Unlike CAN where all nodes share a single arbitration bus, Automotive Ethernet
is a switched network:
1. Switched Full-Duplex: ECUs send and receive simultaneously through dedicated switch ports.
2. Link Profiles:
   - 100BASE-T1: 100 Mbps automotive Ethernet (e.g., standard ECUs and gateways).
   - 1000BASE-T1: 1000 Mbps (1 Gbps) automotive Ethernet (e.g., central compute / telematics).
3. Dynamic MAC Learning & Forwarding Table:
   The switch learns which MAC address is on which port from incoming frames.
4. IEEE 802.1Q VLAN Segmentation:
   VLANs isolate network traffic. A packet on VLAN 10 (Control) is never forwarded
   to a port belonging only to VLAN 30 (Telematics), protecting vehicle domains.
5. Injected Faults & Metrics:
   - Link failure (disconnect port)
   - Packet loss rate
   - End-to-end latency and throughput calculation
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Set
from virtual_vehicle.ethernet.packets import EthernetFrame
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus


@dataclass
class SwitchPort:
    """A physical port on the automotive Ethernet switch."""
    port_id: int
    connected_ecu: str
    link_speed_mbps: int = 100          # 100 for 100BASE-T1, 1000 for 1000BASE-T1
    vlan_memberships: Set[int] = field(default_factory=lambda: {1})  # VLANs allowed on this port
    is_link_up: bool = True
    rx_callback: Optional[Callable[[EthernetFrame], None]] = None


@dataclass
class SwitchStatistics:
    """Metrics tracking for the Ethernet switch."""
    frames_forwarded: int = 0
    frames_dropped_vlan: int = 0
    frames_dropped_link_down: int = 0
    frames_dropped_loss_injection: int = 0
    total_bytes_transmitted: int = 0


class EthernetSwitch:
    """
    Automotive Ethernet Switch supporting VLAN isolation, MAC learning,
    and link speed transmission delays.
    """

    def __init__(self, clock: SimulationClock, event_bus: EventBus):
        self.clock = clock
        self.event_bus = event_bus
        self.ports: Dict[int, SwitchPort] = {}
        # Forwarding Table (MAC Address -> Port ID)
        self.mac_table: Dict[str, int] = {}
        self.stats = SwitchStatistics()

        # Injected fault controls
        self.inject_packet_loss: bool = False
        self.loss_probability: float = 0.0

    def add_port(self, port_id: int, connected_ecu: str,
                 link_speed_mbps: int = 100, vlan_memberships: Optional[List[int]] = None,
                 rx_callback: Optional[Callable[[EthernetFrame], None]] = None) -> SwitchPort:
        """Configures a new port on the switch."""
        vlans = set(vlan_memberships) if vlan_memberships else {1}
        port = SwitchPort(
            port_id=port_id,
            connected_ecu=connected_ecu,
            link_speed_mbps=link_speed_mbps,
            vlan_memberships=vlans,
            rx_callback=rx_callback
        )
        self.ports[port_id] = port
        return port

    def set_link_state(self, port_id: int, is_up: bool) -> None:
        """Simulates disconnecting or reconnecting an Ethernet cable."""
        if port_id in self.ports:
            self.ports[port_id].is_link_up = is_up
            state_str = "UP" if is_up else "DOWN"
            self.event_bus.publish(
                self.clock.current_time_us, "ETHERNET", f"SwitchPort_{port_id}", "LINK_STATE_CHANGE",
                f"Ethernet Port {port_id} ({self.ports[port_id].connected_ecu}) link state changed to {state_str}."
            )

    def receive_from_ecu(self, ingress_port_id: int, frame: EthernetFrame) -> None:
        """
        Called when an ECU sends an Ethernet frame into its switch port.
        """
        in_port = self.ports.get(ingress_port_id)
        if not in_port or not in_port.is_link_up:
            self.stats.frames_dropped_link_down += 1
            self.event_bus.publish(
                self.clock.current_time_us, "FAULT", f"Port_{ingress_port_id}", "PACKET_DROP",
                f"Ingress port {ingress_port_id} is down; frame dropped."
            )
            return

        # 1. Injected Packet Loss check
        if self.inject_packet_loss:
            self.stats.frames_dropped_loss_injection += 1
            self.event_bus.publish(
                self.clock.current_time_us, "FAULT", "Ethernet_Switch", "PACKET_DROP",
                f"Frame dropped by injected packet loss fault: {frame.src_mac} -> {frame.dst_mac}."
            )
            return

        # 2. Dynamic MAC Learning
        self.mac_table[frame.src_mac] = ingress_port_id

        # 3. Ingress VLAN verification
        frame_vlan = frame.vlan_id if frame.vlan_id is not None else 1
        if frame_vlan not in in_port.vlan_memberships:
            self.stats.frames_dropped_vlan += 1
            self.event_bus.publish(
                self.clock.current_time_us, "SECURITY", "Ethernet_Switch", "VLAN_VIOLATION",
                f"VLAN Drop: Port {ingress_port_id} is not member of VLAN {frame_vlan}."
            )
            return

        # 4. Determine destination ports
        dest_ports: List[SwitchPort] = []
        is_broadcast = (frame.dst_mac.upper() in ["FF:FF:FF:FF:FF:FF", "BROADCAST"] or
                        frame.dst_mac.startswith("01:00:5E"))  # Multicast range

        if is_broadcast:
            # Flood to all other ports that belong to this VLAN
            for p in self.ports.values():
                if p.port_id != ingress_port_id and p.is_link_up and (frame_vlan in p.vlan_memberships):
                    dest_ports.append(p)
        else:
            # Unicast lookup
            target_port_id = self.mac_table.get(frame.dst_mac)
            if target_port_id and target_port_id in self.ports:
                p = self.ports[target_port_id]
                if p.is_link_up and (frame_vlan in p.vlan_memberships):
                    dest_ports.append(p)
                else:
                    self.stats.frames_dropped_vlan += 1
                    self.event_bus.publish(
                        self.clock.current_time_us, "SECURITY", "Ethernet_Switch", "VLAN_ISOLATION",
                        f"VLAN Isolation: Target port {target_port_id} ({p.connected_ecu}) is NOT a member of VLAN {frame_vlan}; packet blocked."
                    )
            else:
                # Unknown unicast: flood to all ports in the same VLAN
                for p in self.ports.values():
                    if p.port_id != ingress_port_id and p.is_link_up and (frame_vlan in p.vlan_memberships):
                        dest_ports.append(p)
                if not dest_ports:
                    self.stats.frames_dropped_vlan += 1

        # 5. Forward frames with physical transmission delay
        for out_port in dest_ports:
            # Transmission delay (us) = (frame_size_bytes * 8 bits) / (speed_mbps * 1,000,000) * 1,000,000
            # Simplified: (frame_size_bytes * 8) / speed_mbps
            delay_us = max(1, int((frame.frame_size_bytes * 8) / out_port.link_speed_mbps))
            self.stats.frames_forwarded += 1
            self.stats.total_bytes_transmitted += frame.frame_size_bytes

            target_cb = out_port.rx_callback
            if target_cb:
                self.clock.schedule(
                    delay_us,
                    f"Deliver Ethernet frame to {out_port.connected_ecu}",
                    lambda cb=target_cb, f=frame: cb(f)
                )
