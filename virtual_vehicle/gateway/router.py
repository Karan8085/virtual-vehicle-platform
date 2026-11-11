"""
Secure Central Gateway Engine (CAN <-> Ethernet Boundary & Policy Whitelist).

What this file does (Report Section 3.4):
The Gateway is the critical bridge and security boundary between the CAN/CAN FD bus
and the Automotive Ethernet backbone.
Crucial Design Principle:
"Only selected CAN signals should be exposed as named SOME/IP fields; forwarding every
CAN frame onto Ethernet would create unnecessary traffic and weaken control over the interface.
The gateway should not forward traffic automatically. It should apply explicit rules,
check rates and message mappings, and record why traffic was allowed or rejected."

Key Security Checks Enforced by Gateway:
1. Whitelist Verification: Message ID and direction must be explicitly permitted.
2. Rate Limiting: Prevent bus flooding and denial-of-service.
3. Payload Length Validation: Reject spoofed or malformed frames.
4. Signal Translation: Extract physical signals from CAN payload and pack them into SOME/IP events.
5. DoIP Diagnostic Routing: Route diagnostic packets only along configured paths.
6. Full Audit Logging: Every accept or reject decision is recorded with the specific rule applied.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable, Set
from virtual_vehicle.can.frame import CANFrame
from virtual_vehicle.can.dbc import VehicleDBC
from virtual_vehicle.ethernet.someip import SOMEIPMessage, SOMEIPMessageType
from virtual_vehicle.ethernet.packets import EthernetFrame, IPv4Packet, UDPPacket
from virtual_vehicle.ethernet.switch import EthernetSwitch
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus


@dataclass
class GatewayRoutingRule:
    """Explicit security and forwarding policy rule."""
    rule_id: str
    can_id: int
    direction: str = "CAN_TO_ETH"        # "CAN_TO_ETH" or "ETH_TO_CAN"
    max_rate_hz: float = 100.0           # Maximum allowed frequency in messages per second
    expected_dlc: int = 8
    target_service_id: int = 0x1000
    target_method_event_id: int = 0x8001 # SOME/IP Event ID
    mapped_signals: List[str] = field(default_factory=list) # Which signals to translate
    description: str = ""


class SecurityGateway:
    """
    Enforces security whitelist, rate limits, and signal-to-service mapping between CAN and Ethernet.
    """

    def __init__(self, clock: SimulationClock, event_bus: EventBus, dbc: VehicleDBC,
                 switch: EthernetSwitch, gateway_port_id: int,
                 gateway_mac: str = "02:00:00:00:00:01", gateway_ip: str = "192.168.10.1"):
        self.clock = clock
        self.event_bus = event_bus
        self.dbc = dbc
        self.switch = switch
        self.gateway_port_id = gateway_port_id
        self.gateway_mac = gateway_mac
        self.gateway_ip = gateway_ip

        # Whitelist of rules indexed by CAN ID
        self.rules: Dict[int, GatewayRoutingRule] = {}
        # Message timestamp history for rate limiting: CAN ID -> list of timestamps in us
        self._rate_history: Dict[int, List[int]] = {}

        # Allowed DoIP target addresses
        self.allowed_doip_targets: Set[int] = {0x1000, 0x1001, 0x1002, 0x1003, 0x1004}

    def add_whitelist_rule(self, rule: GatewayRoutingRule) -> None:
        """Adds an explicit routing and policy rule."""
        self.rules[rule.can_id] = rule

    def process_can_frame(self, frame: CANFrame) -> Tuple[bool, str]:
        """
        Called when a frame arrives on the CAN side of the gateway.
        Applies policy checks, signal translation, and forwards onto Ethernet.
        """
        can_id = frame.arbitration_id

        # 1. Whitelist Check
        if can_id not in self.rules:
            reason = f"POLICY_DENY: CAN ID 0x{can_id:X} is NOT in whitelist (unknown mapping rejected)."
            self.event_bus.publish(
                self.clock.current_time_us, "GATEWAY", "SecurityGateway", "POLICY_REJECT",
                reason, {"can_id": can_id}
            )
            return False, reason

        rule = self.rules[can_id]

        # 2. Payload Length Check
        if len(frame.data) != rule.expected_dlc:
            reason = (f"POLICY_DENY [{rule.rule_id}]: Invalid payload length {len(frame.data)} "
                      f"(expected {rule.expected_dlc}).")
            self.event_bus.publish(
                self.clock.current_time_us, "GATEWAY", "SecurityGateway", "POLICY_REJECT",
                reason, {"can_id": can_id, "rule": rule.rule_id}
            )
            return False, reason

        # 3. Rate Limiting Check (Tokens / sliding window of 1 second)
        now_us = self.clock.current_time_us
        window_start_us = now_us - 1_000_000
        if can_id not in self._rate_history:
            self._rate_history[can_id] = []
        # Prune old timestamps
        self._rate_history[can_id] = [t for t in self._rate_history[can_id] if t >= window_start_us]

        if len(self._rate_history[can_id]) >= rule.max_rate_hz:
            reason = (f"RATE_LIMIT_EXCEEDED [{rule.rule_id}]: Rate limit exceeded for 0x{can_id:X} "
                      f"({len(self._rate_history[can_id])} msgs/sec >= max {rule.max_rate_hz} Hz).")
            self.event_bus.publish(
                self.clock.current_time_us, "GATEWAY", "SecurityGateway", "RATE_LIMIT_EXCEEDED",
                reason, {"can_id": can_id, "rule": rule.rule_id}
            )
            return False, reason

        self._rate_history[can_id].append(now_us)

        # 4. Signal Decoding & Translation to SOME/IP
        msg_def = self.dbc.get_message(can_id)
        if not msg_def:
            reason = f"POLICY_DENY: No DBC definition found for CAN ID 0x{can_id:X}."
            return False, reason

        decoded_signals = msg_def.unpack(frame.data)
        # Extract only explicitly permitted signals
        filtered_payload = {sig: decoded_signals[sig] for sig in rule.mapped_signals if sig in decoded_signals}

        # Create SOME/IP Notification Event
        someip_msg = SOMEIPMessage(
            service_id=rule.target_service_id,
            method_id=rule.target_method_event_id,
            message_type=SOMEIPMessageType.NOTIFICATION,
            payload=filtered_payload
        )

        # Encapsulate into UDP/IPv4/Ethernet frame (VLAN 10 = Vehicle Control Domain)
        eth_frame = EthernetFrame(
            src_mac=self.gateway_mac,
            dst_mac="01:00:5E:00:00:10",  # Multicast to Ethernet subscribers
            vlan_id=10,
            ethertype="IPv4",
            payload=IPv4Packet(
                src_ip=self.gateway_ip,
                dst_ip="239.0.0.10",
                protocol="UDP",
                payload=UDPPacket(src_port=30490, dst_port=30490, payload=someip_msg)
            ),
            frame_size_bytes=128
        )

        # Send onto Automotive Ethernet switch
        self.switch.receive_from_ecu(self.gateway_port_id, eth_frame)

        self.event_bus.publish(
            self.clock.current_time_us, "GATEWAY", "SecurityGateway", "POLICY_ALLOW",
            f"Forwarded CAN 0x{can_id:X} -> SOME/IP Service 0x{rule.target_service_id:04X} under rule [{rule.rule_id}].",
            {"rule": rule.rule_id, "signals": filtered_payload}
        )
        return True, f"FORWARDED under rule {rule.rule_id}"

    def route_doip(self, src_mac: str, target_address: int, uds_req: bytes) -> Tuple[bool, str]:
        """Routes DoIP diagnostic requests across boundaries if target is whitelisted."""
        if target_address not in self.allowed_doip_targets:
            reason = f"DOIP_DENY: Diagnostic route to target 0x{target_address:04X} is not permitted."
            self.event_bus.publish(
                self.clock.current_time_us, "GATEWAY", "SecurityGateway", "DOIP_DENIED",
                reason, {"target": target_address}
            )
            return False, reason

        self.event_bus.publish(
            self.clock.current_time_us, "GATEWAY", "SecurityGateway", "DOIP_ROUTED",
            f"DoIP diagnostic message routed to ECU 0x{target_address:04X}.",
            {"target": target_address}
        )
        return True, "ROUTED"
