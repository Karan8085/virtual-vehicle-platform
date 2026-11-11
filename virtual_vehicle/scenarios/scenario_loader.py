"""
JSON Scenario Loader & Controller (Report Section 1.4 & 1.5).

What this file does:
Per Section 1.4 of the report:
"A test run should be repeatable and easy to inspect. Its scenario file should record
the network layout, ECU settings, message definitions, timing parameters, test keys or
certificates, firmware versions, and fault schedule."

This module allows beginners to define or modify vehicle scenarios using simple JSON
files without needing to change any Python code!
"""

import json
import os
from typing import Dict, Any, List, Optional
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus
from virtual_vehicle.can.bus import CANBus
from virtual_vehicle.can.frame import CANFrame
from virtual_vehicle.can.dbc import VehicleDBC
from virtual_vehicle.ethernet.switch import EthernetSwitch
from virtual_vehicle.gateway.router import GatewayRoutingRule
from virtual_vehicle.ecu.powertrain_ecu import PowertrainECU
from virtual_vehicle.ecu.brake_ecu import BrakeECU
from virtual_vehicle.ecu.body_ecu import BodyECU
from virtual_vehicle.ecu.gateway_ecu import GatewayECU
from virtual_vehicle.ecu.telematics_ecu import TelematicsECU


class ScenarioRunner:
    """Loads a JSON scenario configuration and executes the simulation run."""

    def __init__(self, scenario_dict: Dict[str, Any]):
        self.config = scenario_dict
        self.clock = SimulationClock()
        self.event_bus = EventBus()
        self.dbc = VehicleDBC()
        self.can_bus = CANBus(self.clock, self.event_bus)
        self.switch = EthernetSwitch(self.clock, self.event_bus)

        # 5 Reference ECUs
        self.pt = PowertrainECU(self.clock, self.event_bus, self.can_bus, self.dbc)
        self.brk = BrakeECU(self.clock, self.event_bus, self.can_bus, self.dbc)
        self.body = BodyECU(self.clock, self.event_bus, self.can_bus, self.dbc)
        self.gw = GatewayECU(self.clock, self.event_bus, self.can_bus, self.switch, self.dbc, port_id=1)
        self.tcu = TelematicsECU(self.clock, self.event_bus, self.switch, port_id=2)

        self._configure_gateway_rules()

    def _configure_gateway_rules(self):
        # Configure standard rules
        self.gw.security_gateway.add_whitelist_rule(GatewayRoutingRule(
            rule_id="RULE_PT_SPEED",
            can_id=0x100,
            max_rate_hz=100.0,
            expected_dlc=8,
            target_service_id=0x1000,
            target_method_event_id=0x8001,
            mapped_signals=["VehicleSpeed", "EngineRPM"]
        ))
        self.gw.security_gateway.add_whitelist_rule(GatewayRoutingRule(
            rule_id="RULE_BRK_STATUS",
            can_id=0x150,
            max_rate_hz=50.0,
            expected_dlc=8,
            target_service_id=0x1000,
            target_method_event_id=0x8002,
            mapped_signals=["BrakePressure", "ABS_Active"]
        ))

    @classmethod
    def from_file(cls, filepath: str) -> "ScenarioRunner":
        """Loads configuration from a JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    def execute(self) -> Dict[str, Any]:
        """Runs the simulation based on scenario configuration."""
        scenario_name = self.config.get("name", "Unnamed Scenario")
        duration_ms = self.config.get("duration_ms", 100.0)
        ecu_settings = self.config.get("ecu_settings", {})
        fault_schedule = self.config.get("fault_schedule", [])

        # Apply ECU settings
        pt_settings = ecu_settings.get("Powertrain_ECU", {})
        if "vehicle_speed" in pt_settings:
            self.pt.vehicle_speed = float(pt_settings["vehicle_speed"])

        # Power on ECUs
        self.pt.power_on()
        self.brk.power_on()
        self.body.power_on()
        self.gw.power_on()
        self.tcu.power_on()

        self.clock.run_for_ms(10.0)

        # Start periodic broadcasts
        self.pt.start_periodic_broadcast()
        self.brk.start_periodic_broadcast()
        self.body.start_periodic_broadcast()

        # Schedule injected faults from config
        for fault in fault_schedule:
            time_offset_ms = fault.get("time_ms", 30.0)
            fault_type = fault.get("type", "")

            if fault_type == "SENSOR_LOSS":
                self.clock.schedule_ms(time_offset_ms, "Inject Sensor Loss", lambda: self.pt.stop_periodic_broadcast())
            elif fault_type == "CAN_BUS_HOLD_DOMINANT":
                self.clock.schedule_ms(time_offset_ms, "Inject Bus Dominant Fault", lambda: setattr(self.can_bus, "bus_held_dominant", True))
            elif fault_type == "ETHERNET_LINK_DOWN":
                port = fault.get("port_id", 1)
                self.clock.schedule_ms(time_offset_ms, "Inject Link Down", lambda p=port: self.switch.set_link_state(p, False))

        # Advance clock to complete simulation
        self.clock.run_for_ms(duration_ms)

        # Collect summary
        summary = {
            "scenario": scenario_name,
            "duration_ms": duration_ms,
            "can_frames_sent": self.can_bus.stats.total_frames_sent,
            "can_bus_load_percent": round(self.can_bus.calculate_bus_load(self.clock.current_time_us), 2),
            "brake_ecu_state": self.brk.state.value,
            "brake_dtcs": list(self.brk.uds.active_dtcs),
            "ethernet_frames_forwarded": self.switch.stats.frames_forwarded,
            "total_events": len(self.event_bus.get_history())
        }
        return summary

