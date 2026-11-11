"""
Brake ECU Implementation.

What this file does (Report Section 1.6 & 3.6):
The Brake ECU controls braking and stability:
- Periodically broadcasts 0x150 (Brake_Status: pressure, pedal position, ABS active) every 20ms.
- Subscribes to 0x250 (Wheel_Speed_Report) from Powertrain ECU.
- Safety check: If wheel speed data is not received within 60ms (timeout),
  it logs a Diagnostic Trouble Code (DTC: C0031) and transitions into DEGRADED state!
"""

from typing import Optional
from virtual_vehicle.ecu.base_ecu import BaseECU, ECUPowerState
from virtual_vehicle.can.bus import CANBus
from virtual_vehicle.can.frame import CANFrame
from virtual_vehicle.can.dbc import VehicleDBC
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus


class BrakeECU(BaseECU):
    """Virtual Brake & Stability Controller."""

    def __init__(self, clock: SimulationClock, event_bus: EventBus, can_bus: CANBus, dbc: VehicleDBC,
                 sw_version: str = "v1.0.0"):
        super().__init__(name="Brake_ECU", clock=clock, event_bus=event_bus,
                         sw_version=sw_version, hw_id="HW_BRK_V1", doip_address=0x1002)
        self.can_bus = can_bus
        self.dbc = dbc
        self.can_controller = can_bus.register_node(self.name, filter_ids=[0x100, 0x250])

        # Brake system state variables
        self.brake_pressure: float = 0.0     # bar
        self.pedal_position: float = 0.0     # %
        self.abs_active: int = 0
        self.rolling_counter: int = 0

        self._periodic_running: bool = False

        # Listen to CAN bus frames
        self.can_bus.subscribe(self._on_can_frame_received)

    def start_periodic_broadcast(self) -> None:
        """Starts 20ms periodic CAN broadcast and freshness checking timer."""
        self._periodic_running = True
        self._schedule_next_brake_msg()
        self._schedule_freshness_watchdog()

    def stop_periodic_broadcast(self) -> None:
        self._periodic_running = False

    def _on_can_frame_received(self, frame: CANFrame) -> None:
        """Processes incoming CAN frames (0x100 or 0x250)."""
        if self.state == ECUPowerState.OFF:
            return

        if frame.arbitration_id == 0x250:
            msg_def = self.dbc.get_message(0x250)
            if msg_def:
                signals = msg_def.unpack(frame.data)
                for k, v in signals.items():
                    self.record_signal_input(k, v)

                # If we were degraded due to wheel speed loss, recover to operational
                if self.state == ECUPowerState.DEGRADED:
                    self.set_state(ECUPowerState.OPERATIONAL, "Wheel speed signal restored; exiting degraded state")

    def _schedule_freshness_watchdog(self) -> None:
        """Monitors signal freshness every 25ms."""
        if not self._periodic_running:
            return

        if self.state == ECUPowerState.OPERATIONAL:
            # Check wheel speed freshness (timeout = 60ms)
            is_fresh = self.check_signal_freshness("WheelSpeedFL", max_timeout_ms=60.0)
            if not is_fresh and "WheelSpeedFL" in self.signal_last_rx_us:
                # Signal lost!
                dtc_code = "C0031"  # Left Front Wheel Speed Sensor Loss
                if dtc_code not in self.uds.active_dtcs:
                    self.uds.active_dtcs.append(dtc_code)
                self.set_state(
                    ECUPowerState.DEGRADED,
                    f"Wheel speed data timed out (>60ms); logged DTC {dtc_code} and entered DEGRADED mode"
                )

        # Check again in 25ms
        self.clock.schedule_ms(25.0, "Brake freshness watchdog tick", self._schedule_freshness_watchdog)

    def _schedule_next_brake_msg(self) -> None:
        if not self._periodic_running or self.state not in [ECUPowerState.OPERATIONAL, ECUPowerState.DEGRADED]:
            return

        msg_def = self.dbc.get_message(0x150)
        if msg_def:
            data = msg_def.pack({
                "BrakePressure": self.brake_pressure,
                "BrakePedalPosition": self.pedal_position,
                "ABS_Active": float(self.abs_active),
                "RollingCounter": float(self.rolling_counter)
            })
            frame = CANFrame(arbitration_id=0x150, data=data, sender_ecu=self.name)
            self.can_bus.send_frame(frame)

            self.rolling_counter = (self.rolling_counter + 1) % 16

        # Schedule next message in 20ms
        self.clock.schedule_ms(20.0, "Brake 20ms periodic tick", self._schedule_next_brake_msg)

