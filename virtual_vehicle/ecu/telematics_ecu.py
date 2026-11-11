"""
Telematics / OTA Client ECU.

What this file does (Report Section 1.6, 3.5, & 4.1):
The Telematics ECU connects the in-vehicle network to the external cloud:
- Connected to Automotive Ethernet (Port 2, VLAN 30: Telematics/OTA domain).
- Holds device TLS identity certificate (subject, validity, root trust anchor).
- Polls for OTA campaigns, downloads packages in chunks, coordinates vehicle flashing,
  and reports status back to cloud.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
from virtual_vehicle.ecu.base_ecu import BaseECU, ECUPowerState
from virtual_vehicle.ethernet.switch import EthernetSwitch
from virtual_vehicle.ethernet.packets import EthernetFrame
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus


@dataclass
class TLSCertificate:
    """Represents a simulated X.509 TLS certificate for mutual authentication."""
    subject_cn: str
    issuer_cn: str
    is_expired: bool = False
    is_revoked: bool = False


class TelematicsECU(BaseECU):
    """Virtual Telematics Control Unit (TCU) & OTA Client."""

    def __init__(self, clock: SimulationClock, event_bus: EventBus, switch: EthernetSwitch,
                 sw_version: str = "v1.0.0", port_id: int = 2):
        super().__init__(name="Telematics_ECU", clock=clock, event_bus=event_bus,
                         sw_version=sw_version, hw_id="HW_TCU_V1", doip_address=0x1004)
        self.switch = switch
        self.port_id = port_id

        # Attach to Ethernet Switch on VLAN 30 (OTA/External domain)
        self.switch_port = switch.add_port(
            port_id=port_id,
            connected_ecu=self.name,
            link_speed_mbps=1000,
            vlan_memberships=[30],
            rx_callback=self._on_ethernet_frame_received
        )

        # Vehicle TLS Identity Certificate (for mutual authentication with cloud backend)
        self.tls_cert = TLSCertificate(
            subject_cn="vehicle_vin_wp0virtual123456",
            issuer_cn="Automotive_OEM_Root_CA",
            is_expired=False,
            is_revoked=False
        )

        # Vehicle safe preconditions (e.g., stationary, parked, high battery voltage)
        self.vehicle_speed: float = 0.0
        self.is_parked: bool = True
        self.battery_voltage: float = 13.8  # Volts (safe >= 12.0V)

    def is_vehicle_in_safe_programming_state(self) -> Tuple[bool, str]:
        """
        Precondition check before flashing (Report Section 4.2 & 4.3):
        Vehicle must be stationary, in PARK, and have sufficient battery charge!
        """
        if self.vehicle_speed > 0.1:
            return False, f"UNSAFE_STATE: Vehicle is moving ({self.vehicle_speed:.1f} km/h > 0)"
        if not self.is_parked:
            return False, "UNSAFE_STATE: Vehicle gear is not in PARK"
        if self.battery_voltage < 12.0:
            return False, f"UNSAFE_STATE: Battery voltage too low ({self.battery_voltage:.1f}V < 12.0V)"
        return True, "SAFE: Vehicle stationary, parked, and battery healthy"

    def _on_ethernet_frame_received(self, frame: EthernetFrame) -> None:
        """Processes incoming Ethernet frames."""
        pass
