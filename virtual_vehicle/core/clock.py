"""
Simulation Clock for Discrete-Event Simulation.

What this file does:
In real vehicles, ECUs, the CAN bus, and Ethernet networks all run in continuous time.
In our software simulator, we need a shared "clock" so that all events (such as sending
a CAN frame at 10ms, receiving an Ethernet packet at 12ms, or timing out an ECU signal at 50ms)
happen in exact chronological order.

This is called Discrete-Event Simulation (DES).
Time moves forward from one scheduled event to the next, measured in microseconds (us)
or milliseconds (ms).
"""

from dataclasses import dataclass, field
from typing import Callable, Any, List
import heapq


@dataclass(order=True)
class ScheduledEvent:
    """An event scheduled to occur at a specific simulation time."""
    timestamp_us: int  # Simulation time in microseconds (lower numbers happen first)
    sequence: int      # Secondary tie-breaker so events at the exact same time keep insertion order
    description: str = field(compare=False)
    callback: Callable[[], Any] = field(compare=False)


class SimulationClock:
    """
    Master clock that coordinates the timing of all virtual ECUs and network buses.
    """

    def __init__(self, start_time_us: int = 0):
        # Current simulation time in microseconds (1 second = 1,000,000 microseconds)
        self.current_time_us: int = start_time_us
        self._event_queue: List[ScheduledEvent] = []
        self._sequence_counter: int = 0

    @property
    def current_time_ms(self) -> float:
        """Returns the current simulation time in milliseconds (1 ms = 1,000 us)."""
        return self.current_time_us / 1000.0

    @property
    def current_time_s(self) -> float:
        """Returns the current simulation time in seconds."""
        return self.current_time_us / 1_000_000.0

    def schedule(self, delay_us: int, description: str, callback: Callable[[], Any]) -> None:
        """
        Schedule an action to happen after 'delay_us' microseconds from right now.
        
        Example:
            clock.schedule(10000, "Send Powertrain 10ms CAN message", send_msg_func)
        """
        target_time = self.current_time_us + max(0, delay_us)
        self._sequence_counter += 1
        event = ScheduledEvent(
            timestamp_us=target_time,
            sequence=self._sequence_counter,
            description=description,
            callback=callback
        )
        heapq.heappush(self._event_queue, event)

    def schedule_ms(self, delay_ms: float, description: str, callback: Callable[[], Any]) -> None:
        """Helper to schedule an action using milliseconds instead of microseconds."""
        self.schedule(int(delay_ms * 1000), description, callback)

    def step(self) -> bool:
        """
        Executes the very next scheduled event in time.
        Returns True if an event was processed, or False if no more events exist.
        """
        if not self._event_queue:
            return False

        event = heapq.heappop(self._event_queue)
        # Advance simulation time directly to this event's time
        self.current_time_us = event.timestamp_us
        # Run the callback function
        event.callback()
        return True

    def run_until(self, target_time_us: int) -> None:
        """Runs all scheduled events until simulation clock reaches target_time_us."""
        while self._event_queue and self._event_queue[0].timestamp_us <= target_time_us:
            self.step()
        self.current_time_us = max(self.current_time_us, target_time_us)

    def run_for_ms(self, duration_ms: float) -> None:
        """Advances simulation by duration_ms milliseconds, executing all events scheduled in that window."""
        target_time = self.current_time_us + int(duration_ms * 1000)
        self.run_until(target_time)

    def reset(self, start_time_us: int = 0) -> None:
        """Resets the simulation clock and clears any remaining events."""
        self.current_time_us = start_time_us
        self._event_queue.clear()
        self._sequence_counter = 0

