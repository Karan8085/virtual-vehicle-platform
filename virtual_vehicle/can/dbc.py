"""
Signal Database (DBC) & Serialization Schema.

What this file does:
In automotive systems, raw CAN bytes represent physical vehicle signals
(such as vehicle speed in km/h, brake pressure in bar, or door status).
A DBC file defines:
- Signal start bit, bit length, scale, offset, unit.
- Periodic cycle times (e.g. 10ms for speed, 20ms for brake).
- Rolling counters (0 to 15) for message sequence tracking.
- Freshness timeout and behavior on signal loss:
  * "HOLD_LAST": keep previous valid value
  * "SAFE_DEFAULT": revert to predefined fail-safe value (e.g. 0 km/h)
  * "DEGRADED": trigger ECU transition into degraded mode
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import struct


@dataclass
class SignalDefinition:
    """Specification of an individual physical signal within a CAN frame."""
    name: str
    start_bit: int
    length_bits: int
    byte_order: str = "little_endian"  # Intel (little_endian) or Motorola (big_endian)
    is_signed: bool = False
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    min_val: float = 0.0
    max_val: float = 65535.0
    timeout_ms: float = 100.0          # Signal freshness timeout
    safe_default: float = 0.0          # Fail-safe value on signal loss
    loss_behavior: str = "SAFE_DEFAULT"# "HOLD_LAST", "SAFE_DEFAULT", "DEGRADED"


@dataclass
class MessageDefinition:
    """Specification of a CAN message containing one or more signals."""
    arbitration_id: int
    name: str
    dlc: int
    cycle_time_ms: float
    sender: str
    receivers: List[str]
    signals: Dict[str, SignalDefinition] = field(default_factory=dict)
    is_fd: bool = False

    def pack(self, values: Dict[str, float]) -> bytes:
        """
        Packs physical signal values into raw CAN payload bytes.
        """
        raw_int = 0
        for sig_name, sig_def in self.signals.items():
            val = values.get(sig_name, sig_def.safe_default)
            # Bound value
            val = max(sig_def.min_val, min(sig_def.max_val, val))
            # Convert physical value to raw integer: raw = (physical - offset) / scale
            raw_val = int(round((val - sig_def.offset) / sig_def.scale))
            mask = (1 << sig_def.length_bits) - 1
            raw_val &= mask

            # Place into bit position
            raw_int |= (raw_val << sig_def.start_bit)

        # Convert raw_int to bytes
        num_bytes = self.dlc
        packed_bytes = raw_int.to_bytes(num_bytes, byteorder="little")
        return packed_bytes

    def unpack(self, data: bytes) -> Dict[str, float]:
        """
        Decodes physical values from raw CAN payload bytes.
        """
        raw_int = int.from_bytes(data[:self.dlc], byteorder="little")
        results: Dict[str, float] = {}

        for sig_name, sig_def in self.signals.items():
            mask = (1 << sig_def.length_bits) - 1
            raw_val = (raw_int >> sig_def.start_bit) & mask

            if sig_def.is_signed and (raw_val & (1 << (sig_def.length_bits - 1))):
                raw_val -= (1 << sig_def.length_bits)

            # physical = raw * scale + offset
            phys_val = (raw_val * sig_def.scale) + sig_def.offset
            results[sig_name] = round(phys_val, 4)

        return results


class VehicleDBC:
    """
    Standard vehicle signal database containing all message definitions
    for the 5 reference ECUs defined in the report.
    """

    def __init__(self):
        self.messages: Dict[int, MessageDefinition] = {}
        self._build_default_catalog()

    def _build_default_catalog(self) -> None:
        # 1. 0x100: Powertrain_Status (Cycle: 10ms, DLC: 8)
        self.messages[0x100] = MessageDefinition(
            arbitration_id=0x100,
            name="Powertrain_Status",
            dlc=8,
            cycle_time_ms=10.0,
            sender="Powertrain_ECU",
            receivers=["Brake_ECU", "Gateway_ECU"],
            signals={
                "VehicleSpeed": SignalDefinition(
                    name="VehicleSpeed", start_bit=0, length_bits=16,
                    scale=0.01, offset=0.0, unit="km/h", min_val=0.0, max_val=300.0,
                    timeout_ms=50.0, safe_default=0.0, loss_behavior="DEGRADED"
                ),
                "EngineTorque": SignalDefinition(
                    name="EngineTorque", start_bit=16, length_bits=16,
                    scale=0.1, offset=-500.0, unit="Nm", min_val=-500.0, max_val=1500.0,
                    timeout_ms=50.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                ),
                "EngineRPM": SignalDefinition(
                    name="EngineRPM", start_bit=32, length_bits=16,
                    scale=0.25, offset=0.0, unit="rpm", min_val=0.0, max_val=10000.0,
                    timeout_ms=50.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                ),
                "RollingCounter": SignalDefinition(
                    name="RollingCounter", start_bit=48, length_bits=4,
                    scale=1.0, offset=0.0, unit="", min_val=0.0, max_val=15.0,
                    timeout_ms=50.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                )
            }
        )

        # 2. 0x150: Brake_Status (Cycle: 20ms, DLC: 8)
        self.messages[0x150] = MessageDefinition(
            arbitration_id=0x150,
            name="Brake_Status",
            dlc=8,
            cycle_time_ms=20.0,
            sender="Brake_ECU",
            receivers=["Powertrain_ECU", "Gateway_ECU"],
            signals={
                "BrakePressure": SignalDefinition(
                    name="BrakePressure", start_bit=0, length_bits=16,
                    scale=0.1, offset=0.0, unit="bar", min_val=0.0, max_val=250.0,
                    timeout_ms=80.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                ),
                "BrakePedalPosition": SignalDefinition(
                    name="BrakePedalPosition", start_bit=16, length_bits=8,
                    scale=0.5, offset=0.0, unit="%", min_val=0.0, max_val=100.0,
                    timeout_ms=80.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                ),
                "ABS_Active": SignalDefinition(
                    name="ABS_Active", start_bit=24, length_bits=1,
                    scale=1.0, offset=0.0, unit="", min_val=0.0, max_val=1.0,
                    timeout_ms=80.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                ),
                "RollingCounter": SignalDefinition(
                    name="RollingCounter", start_bit=28, length_bits=4,
                    scale=1.0, offset=0.0, unit="", min_val=0.0, max_val=15.0,
                    timeout_ms=80.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                )
            }
        )

        # 3. 0x200: Body_Status (Cycle: 50ms, DLC: 8)
        self.messages[0x200] = MessageDefinition(
            arbitration_id=0x200,
            name="Body_Status",
            dlc=8,
            cycle_time_ms=50.0,
            sender="Body_ECU",
            receivers=["Gateway_ECU"],
            signals={
                "DoorOpen": SignalDefinition(
                    name="DoorOpen", start_bit=0, length_bits=1,
                    scale=1.0, offset=0.0, unit="", min_val=0.0, max_val=1.0,
                    timeout_ms=200.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                ),
                "HeadlightsOn": SignalDefinition(
                    name="HeadlightsOn", start_bit=1, length_bits=1,
                    scale=1.0, offset=0.0, unit="", min_val=0.0, max_val=1.0,
                    timeout_ms=200.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                ),
                "TurnSignal": SignalDefinition(
                    name="TurnSignal", start_bit=2, length_bits=2,
                    scale=1.0, offset=0.0, unit="", min_val=0.0, max_val=3.0,
                    timeout_ms=200.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                ),
                "RollingCounter": SignalDefinition(
                    name="RollingCounter", start_bit=8, length_bits=4,
                    scale=1.0, offset=0.0, unit="", min_val=0.0, max_val=15.0,
                    timeout_ms=200.0, safe_default=0.0, loss_behavior="SAFE_DEFAULT"
                )
            }
        )

        # 4. 0x250: Wheel_Speed_Report (Cycle: 20ms, DLC: 8, Sender: Powertrain_ECU, Receiver: Brake_ECU)
        self.messages[0x250] = MessageDefinition(
            arbitration_id=0x250,
            name="Wheel_Speed_Report",
            dlc=8,
            cycle_time_ms=20.0,
            sender="Powertrain_ECU",
            receivers=["Brake_ECU"],
            signals={
                "WheelSpeedFL": SignalDefinition(name="WheelSpeedFL", start_bit=0, length_bits=16, scale=0.01, timeout_ms=60.0, safe_default=0.0, loss_behavior="DEGRADED"),
                "WheelSpeedFR": SignalDefinition(name="WheelSpeedFR", start_bit=16, length_bits=16, scale=0.01, timeout_ms=60.0, safe_default=0.0, loss_behavior="DEGRADED"),
                "WheelSpeedRL": SignalDefinition(name="WheelSpeedRL", start_bit=32, length_bits=16, scale=0.01, timeout_ms=60.0, safe_default=0.0, loss_behavior="DEGRADED"),
                "WheelSpeedRR": SignalDefinition(name="WheelSpeedRR", start_bit=48, length_bits=16, scale=0.01, timeout_ms=60.0, safe_default=0.0, loss_behavior="DEGRADED"),
            }
        )

    def get_message(self, arbitration_id: int) -> Optional[MessageDefinition]:
        return self.messages.get(arbitration_id)

