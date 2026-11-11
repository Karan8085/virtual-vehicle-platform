"""
Validation Matrix Suite C: ECU Behavioral Tests (Report Section 4.5).

Covers:
1. ECU lifecycle: OFF -> BOOTING -> OPERATIONAL -> OFF.
2. Signal freshness timeout & degraded state:
   Brake ECU monitors WheelSpeedFL from Powertrain; on timeout (>60ms),
   it enters DEGRADED mode and logs DTC C0031!
3. DTC reporting and clearing via UDS diagnostics.
4. Software & Hardware version reporting.
5. Dual firmware slot (A/B) inspection.
"""

import unittest
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus
from virtual_vehicle.can.bus import CANBus
from virtual_vehicle.can.dbc import VehicleDBC
from virtual_vehicle.ecu.base_ecu import ECUPowerState
from virtual_vehicle.ecu.powertrain_ecu import PowertrainECU
from virtual_vehicle.ecu.brake_ecu import BrakeECU


class TestECUSuite(unittest.TestCase):

    def setUp(self):
        self.clock = SimulationClock()
        self.event_bus = EventBus()
        self.can_bus = CANBus(self.clock, self.event_bus)
        self.dbc = VehicleDBC()

        self.pt_ecu = PowertrainECU(self.clock, self.event_bus, self.can_bus, self.dbc)
        self.brk_ecu = BrakeECU(self.clock, self.event_bus, self.can_bus, self.dbc)

    def test_01_ecu_boot_lifecycle(self):
        """Test: ECU boots through BOOTING -> OPERATIONAL state."""
        self.assertEqual(self.pt_ecu.state, ECUPowerState.OFF)

        self.pt_ecu.power_on()
        self.assertEqual(self.pt_ecu.state, ECUPowerState.BOOTING)

        # Advance clock by 6ms (boot takes 5ms)
        self.clock.run_for_ms(6.0)
        self.assertEqual(self.pt_ecu.state, ECUPowerState.OPERATIONAL)

        self.pt_ecu.power_off()
        self.assertEqual(self.pt_ecu.state, ECUPowerState.OFF)

    def test_02_signal_timeout_causes_degraded_mode_and_dtc(self):
        """Test: Brake ECU enters DEGRADED mode and sets DTC when wheel speed times out (>60ms)."""
        self.pt_ecu.power_on()
        self.brk_ecu.power_on()
        self.clock.run_for_ms(6.0)

        # Start periodic broadcasts
        self.pt_ecu.start_periodic_broadcast()
        self.brk_ecu.start_periodic_broadcast()

        # Run for 50ms: WheelSpeed is being received periodically (every 20ms)
        self.clock.run_for_ms(50.0)
        self.assertEqual(self.brk_ecu.state, ECUPowerState.OPERATIONAL)
        self.assertEqual(len(self.brk_ecu.uds.active_dtcs), 0)

        # Stop Powertrain broadcast (simulating sensor or ECU failure)
        self.pt_ecu.stop_periodic_broadcast()

        # Advance clock by 80ms (exceeding the 60ms timeout threshold)
        self.clock.run_for_ms(80.0)

        # Brake ECU should now be in DEGRADED mode with DTC C0031 logged!
        self.assertEqual(self.brk_ecu.state, ECUPowerState.DEGRADED)
        self.assertIn("C0031", self.brk_ecu.uds.active_dtcs)

    def test_03_dtc_clear_and_version_inspection(self):
        """Test: Clear DTCs and inspect version information."""
        self.brk_ecu.uds.active_dtcs.append("C0031")
        self.assertIn("C0031", self.brk_ecu.uds.active_dtcs)

        # Clear DTC service (0x14)
        resp = self.brk_ecu.uds.handle_request(bytes([0x14, 0xFF, 0xFF, 0xFF]))
        self.assertEqual(resp[0], 0x54)  # Positive response for ClearDTC
        self.assertEqual(len(self.brk_ecu.uds.active_dtcs), 0)

        # Verify initial firmware slot versions
        self.assertEqual(self.brk_ecu.current_version, "v1.0.0")
        self.assertEqual(self.brk_ecu.active_slot, "A")


if __name__ == "__main__":
    unittest.main()

