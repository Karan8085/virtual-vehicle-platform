"""
Structured & User-Friendly Terminal Logger.

What this file does:
Provides clear, formatted, and optionally color-coded terminal output
so that someone inspecting the simulation can immediately understand
what is happening at each millisecond, without having to decipher cryptic hex codes.
"""

from typing import Optional
from virtual_vehicle.core.event_bus import EventRecord


class ConsoleLogger:
    """Prints event records to the console with clear badges and timestamps."""

    COLORS = {
        "CAN": "\033[94m",       # Blue
        "ETHERNET": "\033[96m",  # Cyan
        "ECU": "\033[92m",       # Green
        "GATEWAY": "\033[93m",   # Yellow
        "SECOC": "\033[95m",     # Magenta
        "OTA": "\033[35m",       # Dark Magenta
        "FAULT": "\033[91m",     # Red
        "RESET": "\033[0m"
    }

    def __init__(self, use_color: bool = True, verbose: bool = True):
        self.use_color = use_color
        self.verbose = verbose

    def log_event(self, record: EventRecord) -> None:
        """Formats and prints an EventRecord to terminal."""
        if not self.verbose and record.category in ["CAN_BIT"]:
            return

        ms_str = f"[{record.timestamp_us / 1000.0:8.2f} ms]"
        cat = record.category.upper()
        col = self.COLORS.get(cat, "") if self.use_color else ""
        reset = self.COLORS["RESET"] if self.use_color else ""

        tag = f"{col}[{cat:8s}]{reset}"
        source = f"({record.source})"

        print(f"{ms_str} {tag} {source:20s} {record.description}")

    def info(self, msg: str) -> None:
        print(f"[INFO] {msg}")

    def error(self, msg: str) -> None:
        col = self.COLORS["FAULT"] if self.use_color else ""
        reset = self.COLORS["RESET"] if self.use_color else ""
        print(f"{col}[ERROR]{reset} {msg}")

    def section(self, title: str) -> None:
        print("\n" + "=" * 70)
        print(f"  {title.upper()}")
        print("=" * 70)

