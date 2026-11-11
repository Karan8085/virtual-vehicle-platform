"""
Scenario Execution, Log Capture, and Analysis Generator.

What this file does:
Runs all 6 scenarios and JSON scenario configurations, captures console outputs,
extracts metrics from the dashboard, and saves:
1. reports/scenario_execution_log.txt - Full execution log for all scenarios
2. reports/scenario_analysis_report.md - Structured beginner-friendly technical analysis
"""

import sys
import os
import io
import time
from contextlib import redirect_stdout

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from virtual_vehicle.run_simulation import (
    scenario_1_normal_driving,
    scenario_2_arbitration,
    scenario_3_fault_injection,
    scenario_4_cyberattack,
    scenario_5_ota_success,
    scenario_6_ota_rollback,
    setup_vehicle
)
from virtual_vehicle.core.dashboard import VehicleDashboard
from virtual_vehicle.scenarios.scenario_loader import ScenarioRunner


def run_all_and_capture():
    reports_dir = os.path.join(current_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    raw_log_path = os.path.join(reports_dir, "scenario_execution_log.txt")

    captured_logs = {}

    scenarios = [
        ("Scenario 1: Normal Driving & Cross-Network Telemetry", scenario_1_normal_driving),
        ("Scenario 2: CAN Bit-Level Arbitration", scenario_2_arbitration),
        ("Scenario 3: Safety Fault Injection (Timeout -> Degraded Mode)", scenario_3_fault_injection),
        ("Scenario 4: Cybersecurity Protection (Gateway Policy)", scenario_4_cyberattack),
        ("Scenario 5: 10-Step Secure OTA Update (Confirmed)", scenario_5_ota_success),
        ("Scenario 6: OTA Failure & Automatic Rollback", scenario_6_ota_rollback)
    ]

    full_output = io.StringIO()

    print("Executing all scenarios and capturing output...")

    for title, func in scenarios:
        print(f" -> Running: {title}")
        buf = io.StringIO()
        with redirect_stdout(buf):
            func()
        output_str = buf.getvalue()
        captured_logs[title] = output_str
        full_output.write(f"\n{'#'*80}\n# {title}\n{'#'*80}\n\n")
        full_output.write(output_str)
        full_output.write("\n\n")

    # Run JSON scenarios
    json_scenarios = [
        ("JSON Scenario: Highway Cruise", os.path.join(current_dir, "scenarios", "scenario_normal.json")),
        ("JSON Scenario: Wheel Speed Sensor Failure", os.path.join(current_dir, "scenarios", "scenario_sensor_loss.json"))
    ]

    for title, json_file in json_scenarios:
        if os.path.exists(json_file):
            print(f" -> Running: {title}")
            runner = ScenarioRunner.from_file(json_file)
            buf = io.StringIO()
            with redirect_stdout(buf):
                res = runner.execute()
                print(f"\n--- {title} Result ---")
                for k, v in res.items():
                    print(f"  {k}: {v}")
                print(VehicleDashboard.render([runner.pt, runner.brk, runner.body, runner.gw, runner.tcu],
                                             runner.can_bus, runner.switch, runner.event_bus))
            output_str = buf.getvalue()
            captured_logs[title] = output_str
            full_output.write(f"\n{'#'*80}\n# {title}\n{'#'*80}\n\n")
            full_output.write(output_str)
            full_output.write("\n\n")

    # Save raw log file
    with open(raw_log_path, "w", encoding="utf-8") as f:
        f.write(full_output.getvalue())

    print(f"All scenarios completed. Raw output saved to: {raw_log_path}")
    return captured_logs


if __name__ == "__main__":
    run_all_and_capture()

