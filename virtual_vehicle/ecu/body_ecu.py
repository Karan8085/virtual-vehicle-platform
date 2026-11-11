"""
Body ECU Implementation.

What this file does (Report Section 1.6 & 3.6):
The Body ECU controls interior and exterior comfort/lighting functions:
- Periodically broadcasts 0x200 (Body_Status: DoorOpen, HeadlightsOn, TurnSignal, rolling counter) every 50ms.
- Connected to CAN bus.
"""

from virtual_vehicle.ecu.base_ecu import BaseECU, ECUPowerState
from virtual_vehicle.can.bus import CANBus
from virtual_vehicle.can.frame import CANFrame
from virtual_vehicle.can.dbc import VehicleDBC
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus


class BodyECU(BaseECU):
    """Virtual Body Control Module."""

    def __init__(self, clock: SimulationClock, event_bus: EventBus, can_bus: CANBus, dbc: VehicleDBC,
                 sw_version: str = "v1.0.0"):
        super().__init__(name="Body_ECU", clock=clock, event_bus=event_bus,
                         sw_version=sw_version, hw_id="HW_BDY_V1", doip_address=0x1003)
        self.can_bus = can_bus
        self.dbc = dbc
        self.can_controller = can_bus.register_node(self.name)

        # Body state variables
        self.door_open: int = 0
        self.headlights_on: int = 1
        self.turn_signal: int = 0
        self.rolling_counter: int = 0

        self._periodic_running: bool = False

    def start_periodic_broadcast(self) -> None:
        """Starts 50ms periodic CAN broadcast."""
        self._periodic_running = True
        self._schedule_next_body_msg()

    def stop_periodic_broadcast(self) -> None:
        self._periodic_running = False

    def _schedule_next_body_msg(self) -> None:
        if not self._periodic_running or self.state not in [ECUPowerState.OPERATIONAL, ECUPowerState.DEGRADED]:
            return

        msg_def = self.dbc.get_message(0x200)
        if msg_def:
            data = msg_def.pack({
                "DoorOpen": float(self.door_open),
                "HeadlightsOn": float(self.headlights_on),
                "TurnSignal": float(self.turn_signal),
                "RollingCounter": float(self.rolling_counter)
            })
            frame = CANFrame(arbitration_id=0x200, data=data, sender_ecu=self.name)
            self.can_bus.send_frame(frame)

            self.rolling_counter = (self.rolling_counter + 1) % 16

        # Schedule next message in 50ms
        self.clock.schedule_ms(50.0, "Body 50ms periodic tick", self._schedule_next_body_msg)

