"""
Synchronized Timeline Viewer CLI (Report Section 1.5 & 3.7).

What this file does:
Allows beginners to easily inspect and filter the simulation timeline:
- View events within a specific time window (e.g. from 10ms to 50ms)
- Filter events by ECU or category (e.g. only CAN, only OTA, only Brake_ECU)
- Export standard Vector CANoe .asc traces and synchronized timeline logs

Examples:
    python view_timeline.py
    python view_timeline.py --category CAN
    python view_timeline.py --node Brake_ECU
    python view_timeline.py --from-ms 10 --to-ms 30
    python view_timeline.py --export-traces
"""

import sys
import os
import argparse

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from virtual_vehicle.run_simulation import setup_vehicle
from virtual_vehicle.core.trace_exporter import TraceExporter


def main():
    parser = argparse.ArgumentParser(description="Synchronized Simulation Timeline Viewer")
    parser.add_argument("--category", type=str, help="Filter by category (CAN, ETHERNET, ECU, GATEWAY, OTA, FAULT)")
    parser.add_argument("--node", type=str, help="Filter by node name (e.g. Powertrain_ECU, Brake_ECU, SecurityGateway)")
    parser.add_argument("--from-ms", type=float, default=0.0, help="Start time in milliseconds")
    parser.add_argument("--to-ms", type=float, default=100.0, help="End time in milliseconds")
    parser.add_argument("--export-traces", action="store_true", help="Generate Vector .asc and timeline .log files")
    args = parser.parse_args()

    # Run default highway driving to generate events
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
    clock.run_for_ms(args.to_ms)

    history = event_bus.get_history()

    # Filter by time window
    filtered = [
        e for e in history
        if (args.from_ms * 1000) <= e.timestamp_us <= (args.to_ms * 1000)
    ]

    # Filter by category
    if args.category:
        filtered = [e for e in filtered if e.category.upper() == args.category.upper()]

    # Filter by node
    if args.node:
        filtered = [e for e in filtered if args.node.lower() in e.source.lower()]

    print("=" * 100)
    print(f"       SIMULATION TIMELINE VIEW [{args.from_ms:.1f} ms to {args.to_ms:.1f} ms]")
    if args.category:
        print(f"       Filter: Category = {args.category.upper()}")
    if args.node:
        print(f"       Filter: Node = {args.node}")
    print("=" * 100)
    print(f"{'Time (ms)':<12} {'Domain':<10} {'Source Node':<20} {'Event Type':<22} {'Description'}")
    print("-" * 100)

    for e in filtered:
        ms_str = f"{e.timestamp_us / 1000.0:8.3f}"
        print(f"{ms_str:<12} {e.category:<10} {e.source:<20} {e.event_type:<22} {e.description}")

    print("-" * 100)
    print(f" Total events matching filter: {len(filtered)}")
    print("=" * 100)

    if args.export_traces:
        reports_dir = os.path.join(current_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        asc_path = os.path.join(reports_dir, "can_bus_traffic.asc")
        log_path = os.path.join(reports_dir, "synchronized_timeline.log")

        TraceExporter.export_asc_trace(event_bus, asc_path)
        TraceExporter.export_timeline_log(event_bus, log_path)

        print(f"\n[EXPORT] Standard Vector CANoe trace saved: {asc_path}")
        print(f"[EXPORT] Full synchronized timeline log saved: {log_path}\n")


if __name__ == "__main__":
    main()

