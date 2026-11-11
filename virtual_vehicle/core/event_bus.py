"""
Event Bus & Observability for the Virtual Vehicle Platform.

What this file does:
In a complex vehicle system, many components (CAN bus, Ethernet switch, ECUs,
Gateway, and OTA Manager) produce events.
This EventBus allows:
1. Components to publish events (e.g. "CAN frame sent", "Gateway blocked packet", "OTA state changed").
2. Observers or dashboards to listen for specific events.
3. Recording of all events with simulation timestamps for timeline visualization,
   metrics calculation (bus load, latency, packet drop), and test report generation.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Callable, Optional
import json


@dataclass
class EventRecord:
    """A single logged event in the system timeline."""
    timestamp_us: int       # Simulation clock time in microseconds
    category: str           # E.g., 'CAN', 'ETHERNET', 'ECU', 'GATEWAY', 'SECOC', 'OTA', 'FAULT'
    source: str             # Node name, e.g., 'Powertrain_ECU', 'CAN_Bus', 'Gateway'
    event_type: str         # Specific event name, e.g., 'ARBITRATION_LOST', 'FRAME_TX', 'POLICY_DENY'
    details: Dict[str, Any] = field(default_factory=dict)
    description: str = ""   # Human-readable summary for beginner clarity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_us": self.timestamp_us,
            "timestamp_ms": round(self.timestamp_us / 1000.0, 3),
            "category": self.category,
            "source": self.source,
            "event_type": self.event_type,
            "details": self.details,
            "description": self.description
        }


class EventBus:
    """
    Central event distributor and history store.
    """

    def __init__(self):
        self._history: List[EventRecord] = []
        self._subscribers: Dict[str, List[Callable[[EventRecord], None]]] = {}

    def subscribe(self, category: str, callback: Callable[[EventRecord], None]) -> None:
        """Subscribe to events of a specific category (e.g., 'CAN', 'OTA', or '*' for all)."""
        if category not in self._subscribers:
            self._subscribers[category] = []
        self._subscribers[category].append(callback)

    def publish(self, timestamp_us: int, category: str, source: str,
                event_type: str, description: str, details: Optional[Dict[str, Any]] = None) -> EventRecord:
        """
        Record and notify an event.
        """
        record = EventRecord(
            timestamp_us=timestamp_us,
            category=category,
            source=source,
            event_type=event_type,
            details=details or {},
            description=description
        )
        self._history.append(record)

        # Notify category-specific subscribers
        if category in self._subscribers:
            for cb in self._subscribers[category]:
                cb(record)

        # Notify wildcard subscribers
        if "*" in self._subscribers:
            for cb in self._subscribers["*"]:
                cb(record)

        return record

    def get_history(self, category: Optional[str] = None) -> List[EventRecord]:
        """Retrieve recorded history, optionally filtered by category."""
        if category is None or category == "*":
            return list(self._history)
        return [e for e in self._history if e.category == category]

    def clear(self) -> None:
        """Clears all historical events."""
        self._history.clear()

    def export_json(self, filepath: str) -> None:
        """Exports the event history to a formatted JSON file."""
        data = [e.to_dict() for e in self._history]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def export_csv(self, filepath: str) -> None:
        """Exports the event history to a CSV file."""
        import csv
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp_us", "Timestamp_ms", "Category", "Source", "Event_Type", "Description"])
            for e in self._history:
                writer.writerow([
                    e.timestamp_us,
                    round(e.timestamp_us / 1000.0, 3),
                    e.category,
                    e.source,
                    e.event_type,
                    e.description
                ])

