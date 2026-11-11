"""
Powertrain ECU Implementation.

What this file does (Report Section 1.6 & 3.6):
The Powertrain ECU controls engine and transmission parameters:
- Periodically broadcasts 0x100 (Powertrain_Status: speed, torque, RPM, rolling counter) every 10ms.
- Periodically broadcasts 0x250 (Wheel_Speed_Report: four wheel speeds) every 20ms.
- Connected to CAN bus.
"""

from typing import Optional
from virtual_vehicle.ecu.base_ecu import BaseECU, ECUPowerState
from virtual_vehicle.can.bus import CANBus
from virtual_vehicle.can.frame import CANFrame
from virtual_vehicle.can.dbc import VehicleDBC
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus


class PowertrainECU(BaseECU):
    """Virtual Powertrain Controller."""

    def __init__(self, clock: SimulationClock, event_bus: EventBus, can_bus: CANBus, dbc: VehicleDBC,
                 sw_version: str = "v1.0.0"):
        super().__init__(name="Powertrain_ECU", clock=clock, event_bus=event_bus,
                         sw_version=sw_version, hw_id="HW_PT_V1", doip_address=0x1001)
        self.can_bus = can_bus
        self.dbc = dbc
        self.can_controller = can_bus.register_node(self.name)

        # Vehicle physical variables
        self.vehicle_speed: float = 65.0      # km/h
        self.engine_torque: float = 240.0     # Nm
        self.engine_rpm: float = 2200.0       # rpm
        self.rolling_counter: int = 0

        # Periodic schedule flags
        self._periodic_running: bool = False

    def start_periodic_broadcast(self) -> None:
        """Starts 10ms and 20ms periodic CAN broadcasts."""
        self._periodic_running = True
        self._schedule_next_powertrain_msg()
        self._schedule_next_wheel_speed_msg()

    def stop_periodic_broadcast(self) -> None:
        self._periodic_running = False

    def _schedule_next_powertrain_msg(self) -> None:
        if not self._periodic_running or self.state not in [ECUPowerState.OPERATIONAL, ECUPowerState.DEGRADED]:
            return

        msg_def = self.dbc.get_message(0x100)
        if msg_def:
            data = msg_def.pack({
                "VehicleSpeed": self.vehicle_speed,
                "EngineTorque": self.engine_torque,
                "EngineRPM": self.engine_rpm,
                "RollingCounter": self.rolling_counter
            })
            frame = CANFrame(arbitration_id=0x100, data=data, sender_ecu=self.name)
            self.can_bus.send_frame(frame)

            self.rolling_counter = (self.rolling_counter + 1) % 16

        # Schedule next message in 10ms
        self.clock.schedule_ms(10.0, "Powertrain 10ms periodic tick", self._schedule_next_powertrain_msg)

    def _schedule_next_wheel_speed_msg(self) -> None:
        if not self._periodic_running or self.state not in [ECUPowerState.OPERATIONAL, ECUPowerState.DEGRADED]:
            return

        msg_def = self.dbc.get_message(0x250)
        if msg_def:
            data = msg_def.pack({
                "WheelSpeedFL": self.vehicle_speed,
                "WheelSpeedFR": self.vehicle_speed,
                "WheelSpeedRL": self.vehicle_speed,
                "WheelSpeedRR": self.vehicle_speed
            })
            frame = CANFrame(arbitration_id=0x250, data=data, sender_ecu=self.name)
            self.can_bus.send_frame(frame)

        # Schedule next message in 20ms
        self.clock.schedule_ms(20.0, "Wheel speed 20ms periodic tick", self._schedule_next_wheel_speed_msg)

