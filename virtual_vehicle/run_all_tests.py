"""
Virtual Vehicle Platform - Master Test Suite Runner.

What this file does:
Executes the full Section 4.5 Validation Matrix:
  Suite A: CAN & CAN FD Tests (Arbitration, BRS, Error States, TEC, SecOC)
  Suite B: Automotive Ethernet & Gateway Tests (VLAN Isolation, SOME/IP, DoIP, Policy ACL)
  Suite C: ECU Behavioral Tests (Lifecycle, Freshness Timeout -> Degraded Mode, DTCs)
  Suite D: Over-The-Air (OTA) Tests (10-Step Sequence, Signatures, Chunks, Anti-Downgrade, Rollback)
  Suite E: System Integration Tests (Cross-network CAN -> Gateway -> Ethernet, Spoofing, Repeatability)

Exports machine-readable test reports (JSON and CSV) for full observability.
"""

import sys
import os
import unittest
import time
import json
import csv

# Add workspace directory to python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from virtual_vehicle.tests.test_can import TestCANSuite
from virtual_vehicle.tests.test_ethernet import TestEthernetSuite
from virtual_vehicle.tests.test_ecu import TestECUSuite
from virtual_vehicle.tests.test_ota import TestOTASuite
from virtual_vehicle.tests.test_system import TestSystemSuite


def run_matrix():
    print("=" * 80)
    print("       VIRTUAL VEHICLE PLATFORM - VALIDATION MATRIX EXECUTION")
    print("       (Hardware-Independent Software-in-the-Loop Simulation)")
    print("=" * 80)
    print()

    suites = [
        ("Suite A: CAN / CAN FD Protocol & SecOC", TestCANSuite),
        ("Suite B: Automotive Ethernet & Gateway Routing", TestEthernetSuite),
        ("Suite C: ECU Behavioral & Degraded State Machine", TestECUSuite),
        ("Suite D: Secure OTA Update & Automatic Rollback", TestOTASuite),
        ("Suite E: System Integration & Deterministic Replay", TestSystemSuite),
    ]

    results_summary = []
    total_passed = 0
    total_failed = 0
    start_all = time.time()

    for suite_name, test_class in suites:
        print(f"\n>>> Running {suite_name}...")
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(test_class)
        runner = unittest.TextTestRunner(verbosity=1)
        result = runner.run(suite)

        passed = result.testsRun - len(result.failures) - len(result.errors)
        failed = len(result.failures) + len(result.errors)
        total_passed += passed
        total_failed += failed

        status = "PASSED" if failed == 0 else "FAILED"
        results_summary.append({
            "suite": suite_name,
            "tests_run": result.testsRun,
            "passed": passed,
            "failed": failed,
            "status": status
        })

    elapsed = round(time.time() - start_all, 3)

    print("\n" + "=" * 80)
    print("                     TEST SUMMARY REPORT")
    print("=" * 80)
    for res in results_summary:
        tag = "[ PASS ]" if res["status"] == "PASSED" else "[ FAIL ]"
        print(f" {tag}  {res['suite']:<50} {res['passed']}/{res['tests_run']} passed")

    print("-" * 80)
    print(f" TOTAL: {total_passed} Passed, {total_failed} Failed in {elapsed}s")
    print("=" * 80)

    # Export report to JSON & CSV
    export_dir = os.path.join(current_dir, "reports")
    os.makedirs(export_dir, exist_ok=True)

    json_path = os.path.join(export_dir, "validation_matrix_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_passed": total_passed,
            "total_failed": total_failed,
            "elapsed_seconds": elapsed,
            "suites": results_summary
        }, f, indent=2)

    csv_path = os.path.join(export_dir, "validation_matrix_results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Suite Name", "Tests Run", "Passed", "Failed", "Status"])
        for r in results_summary:
            writer.writerow([r["suite"], r["tests_run"], r["passed"], r["failed"], r["status"]])

    print(f"\n[REPORT EXPORT] JSON report saved: {json_path}")
    print(f"[REPORT EXPORT] CSV report saved:  {csv_path}\n")

    return total_failed == 0


if __name__ == "__main__":
    success = run_matrix()
    sys.exit(0 if success else 1)

