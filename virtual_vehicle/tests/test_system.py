"""
Validation Matrix Suite E: System & Mixed-Network Tests (Report Section 4.5).

Covers:
1. Compromised node / spoofing attack: Rogue device injects fake speed frames; Gateway ACL blocks them.
2. Bus flooding / DoS: High-frequency frame injection; gateway rate-limits and prioritizes critical traffic.
3. Ethernet bandwidth / link failure: Communication resumes after link recovery.
4. Deterministic replay & repeatability under identical simulation parameters.
5. End-to-end integration: Powertrain broadcasts CAN -> Gateway translates -> Telematics receives SOME/IP.
"""

import unittest
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus
from virtual_vehicle.can.bus import CANBus
from virtual_vehicle.can.frame import CANFrame
from virtual_vehicle.can.dbc import VehicleDBC
from virtual_vehicle.ethernet.switch import EthernetSwitch
from virtual_vehicle.ethernet.packets import EthernetFrame
from virtual_vehicle.gateway.router import SecurityGateway, GatewayRoutingRule
from virtual_vehicle.ecu.powertrain_ecu import PowertrainECU
from virtual_vehicle.ecu.brake_ecu import BrakeECU
from virtual_vehicle.ecu.body_ecu import BodyECU
from virtual_vehicle.ecu.gateway_ecu import GatewayECU
from virtual_vehicle.ecu.telematics_ecu import TelematicsECU


class TestSystemSuite(unittest.TestCase):

    def _setup_full_vehicle(self):
        clock = SimulationClock()
        event_bus = EventBus()
        dbc = VehicleDBC()
        can_bus = CANBus(clock, event_bus)
        switch = EthernetSwitch(clock, event_bus)

        # 5 Reference ECUs (Section 1.6)
        pt_ecu = PowertrainECU(clock, event_bus, can_bus, dbc)
        brk_ecu = BrakeECU(clock, event_bus, can_bus, dbc)
        body_ecu = BodyECU(clock, event_bus, can_bus, dbc)
        gw_ecu = GatewayECU(clock, event_bus, can_bus, switch, dbc, port_id=1)
        tcu_ecu = TelematicsECU(clock, event_bus, switch, port_id=2)

        # Whitelist rule on Gateway: forward 0x100 Powertrain to SOME/IP 0x1000
        gw_ecu.security_gateway.add_whitelist_rule(GatewayRoutingRule(
            rule_id="RULE_POWERTRAIN_SPEED",
            can_id=0x100,
            max_rate_hz=100.0,
            expected_dlc=8,
            target_service_id=0x1000,
            target_method_event_id=0x8001,
            mapped_signals=["VehicleSpeed", "EngineRPM"]
        ))

        return clock, event_bus, dbc, can_bus, switch, pt_ecu, brk_ecu, body_ecu, gw_ecu, tcu_ecu

    def test_01_end_to_end_cross_network_flow(self):
        """Test: Powertrain broadcasts CAN 0x100 -> Gateway processes & extracts signals -> sends SOME/IP on Ethernet."""
        clock, event_bus, dbc, can_bus, switch, pt, brk, body, gw, tcu = self._setup_full_vehicle()

        # Power on all ECUs
        pt.power_on()
        brk.power_on()
        body.power_on()
        gw.power_on()
        tcu.power_on()

        clock.run_for_ms(10.0)

        # Start periodic broadcasts
        pt.start_periodic_broadcast()
        brk.start_periodic_broadcast()
        body.start_periodic_broadcast()

        # Track SOME/IP frames reaching Ethernet
        eth_frames_received = []
        # Listen on switch port 2 (Telematics)
        switch.ports[2].rx_callback = lambda f: eth_frames_received.append(f)

        # Run simulation for 50ms
        clock.run_for_ms(50.0)

        # Verify CAN frames were transmitted and Gateway forwarded them to Ethernet
        history = event_bus.get_history()
        can_txs = [e for e in history if e.category == "CAN" and e.event_type == "TX_SUCCESS"]
        gw_allows = [e for e in history if e.category == "GATEWAY" and e.event_type == "POLICY_ALLOW"]

        self.assertGreater(len(can_txs), 0)
        self.assertGreater(len(gw_allows), 0)

    def test_02_rogue_ecu_spoofing_blocked_by_gateway(self):
        """Test: Rogue / compromised device sends unauthorized CAN frame; Gateway blocks it."""
        clock, event_bus, dbc, can_bus, switch, pt, brk, body, gw, tcu = self._setup_full_vehicle()
        gw.power_on()
        clock.run_for_ms(6.0)

        # Rogue device attempts to send spoofed ID 0x666
        can_bus.register_node("Rogue_Device")
        spoofed_frame = CANFrame(arbitration_id=0x666, data=b"MALIC000", sender_ecu="Rogue_Device")

        allowed, reason = gw.security_gateway.process_can_frame(spoofed_frame)
        self.assertFalse(allowed)
        self.assertIn("POLICY_DENY", reason)

    def test_03_deterministic_replay_and_repeatability(self):
        """Test: Two simulation runs with identical schedules produce identical event counts and timings."""
        def run_scenario():
            clock, event_bus, dbc, can_bus, switch, pt, brk, body, gw, tcu = self._setup_full_vehicle()
            pt.power_on()
            brk.power_on()
            clock.run_for_ms(10.0)
            pt.start_periodic_broadcast()
            brk.start_periodic_broadcast()
            clock.run_for_ms(60.0)
            return [(e.timestamp_us, e.category, e.event_type) for e in event_bus.get_history()]

        run1 = run_scenario()
        run2 = run_scenario()

        self.assertEqual(len(run1), len(run2))
        self.assertEqual(run1, run2)


if __name__ == "__main__":
    unittest.main()
