"""
Gateway ECU Model.

What this file does (Report Section 1.6 & 3.4):
The Gateway ECU connects both network domains:
- CAN / CAN FD adapter
- Ethernet adapter (connected to Switch Port 1)
- Security policy router (whitelisting, rate limiting, and signal translation)
- DoIP diagnostic routing
"""

from virtual_vehicle.ecu.base_ecu import BaseECU, ECUPowerState
from virtual_vehicle.can.bus import CANBus
from virtual_vehicle.can.frame import CANFrame
from virtual_vehicle.can.dbc import VehicleDBC
from virtual_vehicle.ethernet.switch import EthernetSwitch
from virtual_vehicle.ethernet.packets import EthernetFrame
from virtual_vehicle.gateway.router import SecurityGateway, GatewayRoutingRule
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus


class GatewayECU(BaseECU):
    """Virtual Central Gateway Controller."""

    def __init__(self, clock: SimulationClock, event_bus: EventBus,
                 can_bus: CANBus, switch: EthernetSwitch, dbc: VehicleDBC,
                 sw_version: str = "v1.0.0", port_id: int = 1):
        super().__init__(name="Gateway_ECU", clock=clock, event_bus=event_bus,
                         sw_version=sw_version, hw_id="HW_GW_V1", doip_address=0x1000)
        self.can_bus = can_bus
        self.switch = switch
        self.dbc = dbc
        self.port_id = port_id

        # Register on CAN bus
        self.can_controller = can_bus.register_node(self.name)

        # Register on Ethernet switch (VLAN 10=Control, VLAN 20=Diag, VLAN 30=OTA)
        self.switch_port = switch.add_port(
            port_id=port_id,
            connected_ecu=self.name,
            link_speed_mbps=1000,  # 1000BASE-T1 Gigabit backbone
            vlan_memberships=[10, 20, 30],
            rx_callback=self._on_ethernet_frame_received
        )

        # Initialize Security Gateway policy engine
        self.security_gateway = SecurityGateway(
            clock=clock,
            event_bus=event_bus,
            dbc=dbc,
            switch=switch,
            gateway_port_id=port_id,
            gateway_mac="02:00:00:00:00:01",
            gateway_ip="192.168.10.1"
        )

        # Wire incoming CAN messages to Security Gateway
        self.can_bus.subscribe(self._on_can_frame_received)

    def _on_can_frame_received(self, frame: CANFrame) -> None:
        """When a CAN frame is observed, route through security policy engine."""
        if self.state != ECUPowerState.OPERATIONAL:
            return
        self.security_gateway.process_can_frame(frame)

    def _on_ethernet_frame_received(self, frame: EthernetFrame) -> None:
        """Processes incoming Ethernet frames addressed to Gateway."""
        pass

