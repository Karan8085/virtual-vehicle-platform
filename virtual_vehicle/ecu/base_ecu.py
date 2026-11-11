"""
Base ECU Model & State Machine.

What this file does (Report Section 3.6):
Defines the foundation for every virtual ECU in the vehicle:
1. Power & Operational State Machine:
   - OFF: ECU is powered off.
   - BOOTING: ECU powering up, running bootloader integrity checks.
   - OPERATIONAL: Normal operating state, running application logic and sending/receiving messages.
   - DEGRADED: Safe fallback mode entered when critical inputs time out or fail plausibility checks.
   - PROGRAMMING: Dedicated flash-update state during OTA flashing (vehicle disabled from driving).
   - RECOVERY: Safe recovery mode if a boot or update fails.
2. Dual Firmware Slots (A/B Partitioning):
   - Active slot ('A' or 'B') containing currently running firmware version.
   - Inactive slot for staging new OTA updates without disrupting current operation.
3. Diagnostic Handler (UDS over DoIP or CAN):
   - Reads/clears DTCs, identifies software/hardware versions, switches sessions.
4. Input Signal Monitoring & Freshness Timeouts:
   - Tracks when each input signal was last received.
   - Enters DEGRADED mode if a safety-critical signal is lost.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus
from virtual_vehicle.ethernet.doip import UDSHandler


class ECUPowerState(Enum):
    OFF = "OFF"
    BOOTING = "BOOTING"
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    PROGRAMMING = "PROGRAMMING"
    RECOVERY = "RECOVERY"


@dataclass
class FirmwareSlotInfo:
    """Represents a firmware partition slot."""
    slot_id: str                      # 'A' or 'B'
    version: str                      # E.g. 'v1.0.0'
    image_hash: str                   # SHA-256 hash of image
    is_valid: bool = True             # Signature / integrity verification flag
    is_confirmed: bool = True         # Passed post-install health check


class BaseECU:
    """
    Base class for all virtual ECUs.
    """

    def __init__(self, name: str, clock: SimulationClock, event_bus: EventBus,
                 sw_version: str = "v1.0.0", hw_id: str = "HW_REV_A", doip_address: int = 0x1000):
        self.name = name
        self.clock = clock
        self.event_bus = event_bus
        self.state = ECUPowerState.OFF
        self.doip_address = doip_address

        # Dual firmware slots (A/B)
        self.slots: Dict[str, FirmwareSlotInfo] = {
            "A": FirmwareSlotInfo(slot_id="A", version=sw_version, image_hash="INIT_HASH_A", is_valid=True, is_confirmed=True),
            "B": FirmwareSlotInfo(slot_id="B", version="v0.0.0", image_hash="", is_valid=False, is_confirmed=False)
        }
        self.active_slot: str = "A"

        # Diagnostics & UDS
        self.uds = UDSHandler(ecu_name=name, sw_version=sw_version, hw_id=hw_id)

        # Signal input store & timestamps
        self.input_signals: Dict[str, float] = {}
        self.signal_last_rx_us: Dict[str, int] = {}

    @property
    def current_version(self) -> str:
        return self.slots[self.active_slot].version

    def set_state(self, new_state: ECUPowerState, reason: str = "") -> None:
        """Transitions ECU state machine and logs the event."""
        old_state = self.state
        if old_state == new_state:
            return

        self.state = new_state
        self.event_bus.publish(
            self.clock.current_time_us, "ECU", self.name, "STATE_CHANGE",
            f"ECU state changed: {old_state.value} -> {new_state.value}. {reason}",
            {"old_state": old_state.value, "new_state": new_state.value, "reason": reason}
        )

    def power_on(self) -> None:
        """Boots the ECU from OFF -> BOOTING -> OPERATIONAL."""
        self.set_state(ECUPowerState.BOOTING, "Powering on")
        # Simulate quick boot check (e.g. 5ms)
        self.clock.schedule_ms(5.0, f"{self.name} boot complete", self._complete_boot)

    def _complete_boot(self) -> None:
        active = self.slots[self.active_slot]
        if not active.is_valid:
            self.set_state(ECUPowerState.RECOVERY, f"Active slot {self.active_slot} corrupt; falling back to recovery")
            return
        self.set_state(ECUPowerState.OPERATIONAL, f"Boot successful on slot {self.active_slot} ({active.version})")

    def power_off(self) -> None:
        """Powers down the ECU."""
        self.set_state(ECUPowerState.OFF, "Powering off")

    def record_signal_input(self, signal_name: str, value: float) -> None:
        """Records an incoming signal and updates freshness timestamp."""
        self.input_signals[signal_name] = value
        self.signal_last_rx_us[signal_name] = self.clock.current_time_us

    def check_signal_freshness(self, signal_name: str, max_timeout_ms: float) -> bool:
        """Returns True if signal was received within max_timeout_ms; False if timed out."""
        last_time = self.signal_last_rx_us.get(signal_name)
        if last_time is None:
            return False
        elapsed_ms = (self.clock.current_time_us - last_time) / 1000.0
        return elapsed_ms <= max_timeout_ms

