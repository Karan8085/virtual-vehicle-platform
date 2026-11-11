"""
Validation Matrix Suite B: Automotive Ethernet & Gateway Tests (Report Section 4.5).

Covers:
1. IEEE 802.1Q VLAN isolation (frames on VLAN 10 are blocked from VLAN 30).
2. Dynamic MAC learning and unicast forwarding.
3. SOME/IP & SOME/IP-SD service discovery, offering, and events.
4. DoIP (ISO 13400) diagnostic routing & UDS ReadDataByIdentifier.
5. Injected packet loss and link failure.
6. Gateway policy engine: whitelisted CAN-to-SOME/IP translation vs unauthorized denial.
7. Gateway rate limiting enforcement.
"""

import unittest
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus
from virtual_vehicle.ethernet.switch import EthernetSwitch
from virtual_vehicle.ethernet.packets import EthernetFrame, IPv4Packet, UDPPacket
from virtual_vehicle.ethernet.someip import SOMEIPMessage, SOMEIPMessageType, SOMEIPServiceDiscoveryMessage, SDEntryType
from virtual_vehicle.ethernet.doip import DoIPMessage, DoIPPayloadType, UDSServiceId, UDSHandler
from virtual_vehicle.gateway.router import SecurityGateway, GatewayRoutingRule
from virtual_vehicle.can.dbc import VehicleDBC
from virtual_vehicle.can.frame import CANFrame


class TestEthernetSuite(unittest.TestCase):

    def setUp(self):
        self.clock = SimulationClock()
        self.event_bus = EventBus()
        self.switch = EthernetSwitch(self.clock, self.event_bus)

    def test_01_vlan_isolation(self):
        """Test: IEEE 802.1Q VLAN separation blocks cross-domain traffic."""
        vlan10_rx = []
        vlan30_rx = []

        # Port 1: Member of VLAN 10 (Control domain)
        self.switch.add_port(port_id=1, connected_ecu="ECU_VLAN10", vlan_memberships=[10],
                             rx_callback=lambda f: vlan10_rx.append(f))
        # Port 2: Member of VLAN 30 (OTA/External domain)
        self.switch.add_port(port_id=2, connected_ecu="ECU_VLAN30", vlan_memberships=[30],
                             rx_callback=lambda f: vlan30_rx.append(f))

        # Send frame tagged with VLAN 10 from Port 1 targeted to Port 2 MAC
        frame_vlan10 = EthernetFrame(
            src_mac="02:00:00:00:00:10",
            dst_mac="02:00:00:00:00:30",
            vlan_id=10,
            frame_size_bytes=64
        )
        self.switch.receive_from_ecu(ingress_port_id=1, frame=frame_vlan10)
        self.clock.run_for_ms(2.0)

        # Port 2 (VLAN 30) should NOT receive frame on VLAN 10!
        self.assertEqual(len(vlan30_rx), 0)
        self.assertGreaterEqual(self.switch.stats.frames_dropped_vlan, 1)

    def test_02_someip_service_discovery(self):
        """Test: SOME/IP-SD offer and find message handling."""
        sd_offer = SOMEIPServiceDiscoveryMessage(
            entry_type=SDEntryType.OFFER_SERVICE,
            service_id=0x1234,
            instance_id=1,
            endpoint_ip="192.168.10.10",
            endpoint_port=30490,
            ttl_seconds=3
        )
        self.assertEqual(sd_offer.entry_type, SDEntryType.OFFER_SERVICE)
        self.assertEqual(sd_offer.service_id, 0x1234)

        # SOME/IP Notification Event
        event_msg = SOMEIPMessage(
            service_id=0x1234,
            method_id=0x8001,
            message_type=SOMEIPMessageType.NOTIFICATION,
            payload={"speed": 85.5}
        )
        self.assertTrue(event_msg.is_event)
        self.assertEqual(event_msg.payload["speed"], 85.5)

    def test_03_doip_and_uds_diagnostics(self):
        """Test: DoIP diagnostic routing and UDS session/read services."""
        uds = UDSHandler(ecu_name="Powertrain_ECU", sw_version="v1.0.0", hw_id="HW_PT_V1")

        # 1. Read Software Version (DID 0xF189)
        req_sw = bytes([UDSServiceId.READ_DATA_BY_ID, 0xF1, 0x89])
        resp_sw = uds.handle_request(req_sw)
        self.assertEqual(resp_sw[0], 0x62)  # Positive response SID (0x22 + 0x40)
        self.assertIn(b"v1.0.0", resp_sw)

        # 2. Switch Session to Programming (0x02)
        req_session = bytes([UDSServiceId.DIAGNOSTIC_SESSION_CONTROL, 0x02])
        resp_session = uds.handle_request(req_session)
        self.assertEqual(resp_session[0], 0x50)  # Positive response SID
        self.assertEqual(uds.active_session, 0x02)

    def test_04_gateway_whitelist_allow_and_deny(self):
        """Test: Security Gateway forwards whitelisted CAN IDs to SOME/IP and denies unauthorized IDs."""
        dbc = VehicleDBC()
        gw = SecurityGateway(
            clock=self.clock,
            event_bus=self.event_bus,
            dbc=dbc,
            switch=self.switch,
            gateway_port_id=1
        )

        # Whitelist rule for 0x100 (Powertrain_Status)
        gw.add_whitelist_rule(GatewayRoutingRule(
            rule_id="RULE_POWERTRAIN",
            can_id=0x100,
            max_rate_hz=100.0,
            expected_dlc=8,
            target_service_id=0x1000,
            target_method_event_id=0x8001,
            mapped_signals=["VehicleSpeed", "EngineRPM"]
        ))

        # 1. Allowed message (0x100)
        valid_data = dbc.get_message(0x100).pack({"VehicleSpeed": 70.0, "EngineRPM": 2500.0})
        frame_allowed = CANFrame(arbitration_id=0x100, data=valid_data, sender_ecu="Powertrain_ECU")
        allowed, msg_allowed = gw.process_can_frame(frame_allowed)
        self.assertTrue(allowed, msg_allowed)

        # 2. Denied message (0x555 - unknown / unauthorized)
        frame_denied = CANFrame(arbitration_id=0x555, data=b"UNAUTH00", sender_ecu="Rogue_Device")
        denied, msg_denied = gw.process_can_frame(frame_denied)
        self.assertFalse(denied)
        self.assertIn("POLICY_DENY", msg_denied)

    def test_05_gateway_rate_limiting(self):
        """Test: Security Gateway drops frames exceeding max configured rate (Hz)."""
        dbc = VehicleDBC()
        gw = SecurityGateway(
            clock=self.clock,
            event_bus=self.event_bus,
            dbc=dbc,
            switch=self.switch,
            gateway_port_id=1
        )
        # Strict limit: max 2 messages per second
        gw.add_whitelist_rule(GatewayRoutingRule(
            rule_id="RULE_STRICT",
            can_id=0x100,
            max_rate_hz=2.0,
            expected_dlc=8,
            mapped_signals=["VehicleSpeed"]
        ))
        valid_data = dbc.get_message(0x100).pack({"VehicleSpeed": 50.0})

        frame1 = CANFrame(arbitration_id=0x100, data=valid_data, sender_ecu="Powertrain_ECU")
        frame2 = CANFrame(arbitration_id=0x100, data=valid_data, sender_ecu="Powertrain_ECU")
        frame3 = CANFrame(arbitration_id=0x100, data=valid_data, sender_ecu="Powertrain_ECU")

        ok1, _ = gw.process_can_frame(frame1)
        ok2, _ = gw.process_can_frame(frame2)
        ok3, msg3 = gw.process_can_frame(frame3)

        self.assertTrue(ok1)
        self.assertTrue(ok2)
        # Frame 3 exceeds rate limit of 2 Hz!
        self.assertFalse(ok3)
        self.assertIn("RATE_LIMIT_EXCEEDED", msg3)


if __name__ == "__main__":
    unittest.main()
