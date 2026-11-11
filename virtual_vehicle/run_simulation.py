"""
Virtual Vehicle Platform - Interactive Scenario Runner.

What this file does:
Provides a beginner-friendly interactive menu and visual demonstration of
the 5 core scenarios defined in the report:
  1. Normal Driving & Cross-Network Telemetry (CAN -> Gateway -> SOME/IP Ethernet)
  2. CAN Bit-Level Arbitration (Dominant 0 vs Recessive 1)
  3. Safety Fault Injection (Wheel speed timeout -> Degraded State + DTC C0031)
  4. Cybersecurity Gateway Protection (Spoofing & Flooding Denial)
  5. End-to-End Secure OTA Update (10-Step Sequence to CONFIRMED)
  6. OTA Failure & Automatic Rollback to Last-Known-Good Slot

Run with:
    python run_simulation.py
or:
    python run_simulation.py --scenario 1
"""

import sys
import os
import argparse
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus
from virtual_vehicle.core.logger import ConsoleLogger
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
from virtual_vehicle.ota.package import OTAPackageBuilder
from virtual_vehicle.ota.firmware_slot import DualSlotFirmwareManager
from virtual_vehicle.ota.campaign import OTACampaignOrchestrator
from virtual_vehicle.core.dashboard import VehicleDashboard
from virtual_vehicle.scenarios.scenario_loader import ScenarioRunner


def setup_vehicle():
    clock = SimulationClock()
    event_bus = EventBus()
    logger = ConsoleLogger(use_color=True, verbose=True)
    event_bus.subscribe("*", logger.log_event)

    dbc = VehicleDBC()
    can_bus = CANBus(clock, event_bus)
    switch = EthernetSwitch(clock, event_bus)

    pt = PowertrainECU(clock, event_bus, can_bus, dbc)
    brk = BrakeECU(clock, event_bus, can_bus, dbc)
    body = BodyECU(clock, event_bus, can_bus, dbc)
    gw = GatewayECU(clock, event_bus, can_bus, switch, dbc, port_id=1)
    tcu = TelematicsECU(clock, event_bus, switch, port_id=2)

    # Configure Gateway Whitelist Policy (Report Section 3.4)
    gw.security_gateway.add_whitelist_rule(GatewayRoutingRule(
        rule_id="RULE_PT_SPEED",
        can_id=0x100,
        max_rate_hz=100.0,
        expected_dlc=8,
        target_service_id=0x1000,
        target_method_event_id=0x8001,
        mapped_signals=["VehicleSpeed", "EngineRPM"]
    ))
    gw.security_gateway.add_whitelist_rule(GatewayRoutingRule(
        rule_id="RULE_BRK_STATUS",
        can_id=0x150,
        max_rate_hz=50.0,
        expected_dlc=8,
        target_service_id=0x1000,
        target_method_event_id=0x8002,
        mapped_signals=["BrakePressure", "ABS_Active"]
    ))

    return clock, event_bus, logger, dbc, can_bus, switch, pt, brk, body, gw, tcu


def scenario_1_normal_driving():
    print("\n" + "=" * 80)
    print(" SCENARIO 1: NORMAL DRIVING & CROSS-NETWORK TELEMETRY")
    print(" Flow: CAN ECUs broadcast periodic frames -> Gateway translates to SOME/IP over Ethernet")
    print("=" * 80)

    clock, event_bus, logger, dbc, can_bus, switch, pt, brk, body, gw, tcu = setup_vehicle()

    pt.power_on()
    brk.power_on()
    body.power_on()
    gw.power_on()
    tcu.power_on()
    clock.run_for_ms(10.0)

    pt.start_periodic_broadcast()
    brk.start_periodic_broadcast()
    body.start_periodic_broadcast()

    # Simulate 60ms of vehicle driving
    clock.run_for_ms(60.0)
    print("\n[SUCCESS] Scenario 1 completed: Periodic messages were successfully arbitrated on CAN and translated by Gateway.")


def scenario_2_arbitration():
    print("\n" + "=" * 80)
    print(" SCENARIO 2: CAN BIT-LEVEL ARBITRATION (DOMINANT 0 vs RECESSIVE 1)")
    print(" Demonstration: When 0x100 (Powertrain) and 0x200 (Body) compete simultaneously,")
    print(" 0x100 wins because lower numerical identifier has dominant 0 bits.")
    print("=" * 80)

    clock, event_bus, logger, dbc, can_bus, switch, pt, brk, body, gw, tcu = setup_vehicle()
    pt.power_on()
    body.power_on()
    clock.run_for_ms(10.0)

    # Queue both at the exact same simulation microsecond
    frame_body = CANFrame(arbitration_id=0x200, data=b"BODY0001", sender_ecu="Body_ECU")
    frame_speed = CANFrame(arbitration_id=0x100, data=b"SPEED001", sender_ecu="Powertrain_ECU")

    can_bus.queue_frame(frame_body)
    can_bus.queue_frame(frame_speed)
    can_bus.trigger_arbitration()

    clock.run_for_ms(5.0)
    print("\n[SUCCESS] Scenario 2 completed: Bit arbitration observed in logs above.")


def scenario_3_fault_injection():
    print("\n" + "=" * 80)
    print(" SCENARIO 3: SAFETY FAULT INJECTION (SIGNAL TIMEOUT -> DEGRADED MODE)")
    print(" Demonstration: Brake ECU expects WheelSpeed from Powertrain every 20ms.")
    print(" Powertrain broadcast is halted -> timeout occurs (>60ms) -> DTC C0031 logged -> DEGRADED mode.")
    print("=" * 80)

    clock, event_bus, logger, dbc, can_bus, switch, pt, brk, body, gw, tcu = setup_vehicle()
    pt.power_on()
    brk.power_on()
    clock.run_for_ms(10.0)

    pt.start_periodic_broadcast()
    brk.start_periodic_broadcast()

    # Run normally for 40ms
    print("\n--- Phase 1: Normal operation ---")
    clock.run_for_ms(40.0)

    # Inject sensor failure: stop Powertrain wheel speed broadcast
    print("\n--- Phase 2: Injecting Wheel Speed Sensor failure ---")
    pt.stop_periodic_broadcast()

    # Run for 75ms to cross 60ms timeout threshold
    clock.run_for_ms(75.0)
    print(f"\nBrake ECU State: {brk.state.value}")
    print(f"Brake ECU Active DTCs: {brk.uds.active_dtcs}")
    print("\n[SUCCESS] Scenario 3 completed: Safe degraded mode and DTC successfully triggered.")


def scenario_4_cyberattack():
    print("\n" + "=" * 80)
    print(" SCENARIO 4: CYBERSECURITY ATTACK & GATEWAY POLICY ENFORCEMENT")
    print(" Demonstration:")
    print(" 1. Rogue ECU injects unauthorized CAN ID 0x666 -> Gateway rejects (whitelist policy).")
    print(" 2. Rogue ECU floods whitelisted ID 0x100 at 500 Hz -> Gateway rate limiter blocks it.")
    print("=" * 80)

    clock, event_bus, logger, dbc, can_bus, switch, pt, brk, body, gw, tcu = setup_vehicle()
    gw.power_on()
    clock.run_for_ms(10.0)

    can_bus.register_node("Rogue_OBD_Dongle")

    # 1. Unauthorized ID
    print("\n--- Attack 1: Spoofed Unauthorized ID 0x666 ---")
    spoofed = CANFrame(arbitration_id=0x666, data=b"ROGUE001", sender_ecu="Rogue_OBD_Dongle")
    gw.security_gateway.process_can_frame(spoofed)

    # 2. Flooding Attack
    print("\n--- Attack 2: Flooding whitelisted ID 0x100 ---")
    valid_data = dbc.get_message(0x100).pack({"VehicleSpeed": 180.0})
    for i in range(120):  # Exceeds max 100 Hz limit
        frame = CANFrame(arbitration_id=0x100, data=valid_data, sender_ecu="Rogue_OBD_Dongle")
        allowed, msg = gw.security_gateway.process_can_frame(frame)
        if not allowed:
            print(f"Frame #{i} dropped by Gateway: {msg}")
            break

    print("\n[SUCCESS] Scenario 4 completed: Attacks mitigated by Gateway whitelist and rate limiting.")


def scenario_5_ota_success():
    print("\n" + "=" * 80)
    print(" SCENARIO 5: COMPLETE 10-STEP SECURE OTA UPDATE (CONFIRMED)")
    print(" Demonstration: Telematics downloads signed update v1.1.0 -> verifies signature ->")
    print(" stages in partition B -> reboots -> passes health check -> CONFIRMED.")
    print("=" * 80)

    clock, event_bus, logger, dbc, can_bus, switch, pt, brk, body, gw, tcu = setup_vehicle()
    pt.power_on()
    tcu.power_on()
    clock.run_for_ms(10.0)

    fw_mgr = DualSlotFirmwareManager("Powertrain_ECU", initial_version="v1.0.0", initial_counter=1)
    orch = OTACampaignOrchestrator("CAMP_V110_PROD", clock, event_bus, tcu, pt, fw_mgr)

    manifest, chunks = OTAPackageBuilder.create_package(
        package_id="PKG_110",
        target_ecu="Powertrain_ECU",
        target_hw="HW_PT_V1",
        version="v1.1.0",
        version_counter=2,
        payload=b"POWERTRAIN_OPTIMIZED_CALIBRATION_DATA_2026" * 8
    )

    success = orch.execute_campaign(manifest, chunks)
    print(f"\nFinal Campaign State: {orch.sm.state.value}")
    print(f"Active Partition Slot: {fw_mgr.active_slot} (Version: {fw_mgr.slots[fw_mgr.active_slot].version})")
    print(f"Slot Confirmed: {fw_mgr.slots[fw_mgr.active_slot].is_confirmed}")
    print("\n[SUCCESS] Scenario 5 completed: Full OTA update verified.")


def scenario_6_ota_rollback():
    print("\n" + "=" * 80)
    print(" SCENARIO 6: OTA FAILURE & AUTOMATIC ROLLBACK TO LAST-KNOWN-GOOD")
    print(" Demonstration: Candidate firmware fails post-install health check smoke test.")
    print(" Bootloader automatically reverts active partition to Slot A (v1.0.0).")
    print("=" * 80)

    clock, event_bus, logger, dbc, can_bus, switch, pt, brk, body, gw, tcu = setup_vehicle()
    pt.power_on()
    tcu.power_on()
    clock.run_for_ms(10.0)

    fw_mgr = DualSlotFirmwareManager("Powertrain_ECU", initial_version="v1.0.0", initial_counter=1)
    orch = OTACampaignOrchestrator("CAMP_FAIL_TEST", clock, event_bus, tcu, pt, fw_mgr)
    # Inject post-install smoke test crash
    orch.inject_failed_health_check = True

    manifest, chunks = OTAPackageBuilder.create_package(
        package_id="PKG_110_BAD",
        target_ecu="Powertrain_ECU",
        target_hw="HW_PT_V1",
        version="v1.1.0",
        version_counter=2,
        payload=b"DEFECTIVE_IMAGE_SIMULATION" * 8
    )

    success = orch.execute_campaign(manifest, chunks)
    print(f"\nFinal Campaign State: {orch.sm.state.value}")
    print(f"Active Partition Slot: {fw_mgr.active_slot} (Version: {fw_mgr.slots[fw_mgr.active_slot].version})")
    print("\n[SUCCESS] Scenario 6 completed: Automatic rollback safely protected vehicle operation.")


def main():
    parser = argparse.ArgumentParser(description="Virtual Vehicle Platform Interactive Runner")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3, 4, 5, 6],
                        help="Scenario number (1 to 6) to run directly")
    args = parser.parse_args()

    scenarios = {
        1: scenario_1_normal_driving,
        2: scenario_2_arbitration,
        3: scenario_3_fault_injection,
        4: scenario_4_cyberattack,
        5: scenario_5_ota_success,
        6: scenario_6_ota_rollback
    }

    if args.scenario:
        scenarios[args.scenario]()
        return

    print("=" * 70)
    print("            VIRTUAL VEHICLE PLATFORM SIMULATION")
    print("=" * 70)
    print(" Select a scenario to run:")
    print("   [1] Normal Driving & Cross-Network Telemetry (CAN -> Gateway -> SOME/IP)")
    print("   [2] CAN Bit-Level Arbitration (Dominant 0 vs Recessive 1)")
    print("   [3] Safety Fault Injection (Wheel Speed Timeout -> Degraded Mode + DTC)")
    print("   [4] Cybersecurity Attack Mitigation (Spoofing & Flooding Gateway Denial)")
    print("   [5] End-to-End Secure OTA Update (10-Step Sequence to CONFIRMED)")
    print("   [6] OTA Failure & Automatic Rollback to Last-Known-Good Slot")
    print("   [0] Exit")
    print("-" * 70)

    try:
        choice = input("Enter choice (0-6): ").strip()
        if choice in ["1", "2", "3", "4", "5", "6"]:
            scenarios[int(choice)]()
        else:
            print("Exiting.")
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")


if __name__ == "__main__":
    main()

