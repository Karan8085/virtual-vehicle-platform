"""
CAN & CAN FD Frame Definitions and Timing Models.

What this file does:
In a real vehicle CAN bus, frames are composed of specific bit fields:
1. Start of Frame (SOF): 1 dominant bit (0).
2. Arbitration Field: 11-bit (Standard) or 29-bit (Extended) identifier.
   Crucial rule: A dominant bit (0) wins over a recessive bit (1).
   Therefore, a lower numerical ID has higher priority during arbitration!
3. Control Field:
   - IDE: Identifier Extension (0 = 11-bit, 1 = 29-bit)
   - FDF: Flexible Data-rate Format (0 = Classical CAN, 1 = CAN FD)
   - BRS: Bit Rate Switch (1 = switch to fast data bit rate for payload & CRC)
   - ESI: Error State Indicator (0 = error active, 1 = error passive)
   - DLC: Data Length Code (0-8 bytes for Classical, up to 64 bytes for CAN FD)
4. Data Field: The actual payload bytes (up to 8 bytes in Classical CAN, up to 64 in CAN FD).
5. CRC Field: Cyclic Redundancy Check (15 bits for Classical, 17 or 21 bits for FD).
6. ACK Field: Acknowledge slot (1 bit) + delimiter (1 bit).
7. End of Frame (EOF): 7 recessive bits (1s).
8. Intermission: 3 recessive bits before the next frame can start.
"""

from dataclasses import dataclass, field
from typing import Optional, List
import math


# Standard CAN FD DLC to byte length conversion table (AUTOSAR / ISO 11898-1)
DLC_TO_BYTES_MAP = {
    0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8,
    9: 12, 10: 16, 11: 20, 12: 24, 13: 32, 14: 48, 15: 64
}


def bytes_to_dlc(byte_len: int, is_fd: bool = False) -> int:
    """Converts a byte length to the appropriate CAN / CAN FD DLC code."""
    if not is_fd:
        return min(8, max(0, byte_len))
    for dlc, num_bytes in sorted(DLC_TO_BYTES_MAP.items(), key=lambda x: x[1]):
        if num_bytes >= byte_len:
            return dlc
    return 15  # Max 64 bytes


@dataclass
class CANFrame:
    """
    Represents a Classical CAN or CAN FD frame.
    """
    arbitration_id: int          # 11-bit (0x000 - 0x7FF) or 29-bit (0x00000000 - 0x1FFFFFFF)
    data: bytes = b""            # Payload data bytes
    is_extended_id: bool = False # False = 11-bit ID, True = 29-bit ID
    is_fd: bool = False          # False = Classical CAN (max 8B), True = CAN FD (max 64B)
    bit_rate_switch: bool = False# BRS flag: If True and is_fd, payload and CRC are transmitted at higher baudrate
    error_state_indicator: bool = False # ESI flag: 0 = active, 1 = passive
    is_remote_frame: bool = False# Remote transmission request (RTR) - classical only
    sender_ecu: str = "Unknown"  # Name of the transmitting ECU for tracking/logging

    # Injected fault flags for test cases (Section 2.3)
    inject_crc_error: bool = False
    inject_ack_error: bool = False
    inject_stuff_error: bool = False
    inject_bit_error: bool = False

    # Timestamp metadata populated during transmission
    tx_queued_time_us: int = 0   # When ECU queued the frame
    tx_start_time_us: int = 0    # When arbitration was won and transmission started
    tx_end_time_us: int = 0      # When transmission finished (including ACK & EOF)

    def __post_init__(self):
        # Enforce Classical CAN vs CAN FD payload bounds
        max_payload = 64 if self.is_fd else 8
        if len(self.data) > max_payload:
            raise ValueError(
                f"Payload size {len(self.data)} exceeds maximum allowed "
                f"({max_payload} bytes) for {'CAN FD' if self.is_fd else 'Classical CAN'}"
            )
        if not self.is_extended_id and self.arbitration_id > 0x7FF:
            raise ValueError(f"11-bit arbitration ID cannot exceed 0x7FF (got 0x{self.arbitration_id:X})")
        if self.is_extended_id and self.arbitration_id > 0x1FFFFFFF:
            raise ValueError(f"29-bit arbitration ID cannot exceed 0x1FFFFFFF (got 0x{self.arbitration_id:X})")

    @property
    def dlc(self) -> int:
        return bytes_to_dlc(len(self.data), self.is_fd)

    def get_arbitration_bits(self) -> List[int]:
        """
        Returns the sequence of arbitration bits sent onto the bus during arbitration.
        0 = Dominant (Active voltage, wins arbitration)
        1 = Recessive (Passive voltage, loses to 0)
        """
        bits: List[int] = []
        if not self.is_extended_id:
            # 11-bit ID: MSB first
            for i in range(10, -1, -1):
                bits.append((self.arbitration_id >> i) & 1)
            # RTR bit (0 for data frame, 1 for remote request)
            bits.append(1 if self.is_remote_frame else 0)
            # IDE bit (0 for standard 11-bit)
            bits.append(0)
        else:
            # 29-bit Extended ID: Base 11 bits + SRR (1) + IDE (1) + 18 extended bits + RTR
            base_id = (self.arbitration_id >> 18) & 0x7FF
            ext_id = self.arbitration_id & 0x3FFFF
            for i in range(10, -1, -1):
                bits.append((base_id >> i) & 1)
            bits.append(1)  # Substitute Remote Request (SRR = 1)
            bits.append(1)  # IDE = 1 (Extended ID indicator)
            for i in range(17, -1, -1):
                bits.append((ext_id >> i) & 1)
            bits.append(1 if self.is_remote_frame else 0)  # RTR
        return bits

    def calculate_duration_us(self, nominal_baudrate: int = 500_000, data_baudrate: int = 2_000_000) -> int:
        """
        Calculates exact transmission time in microseconds based on baudrates,
        header length, payload, CRC, bit-stuffing overhead, ACK, and intermission.
        
        Default: 500 kbps nominal (2.0 us per bit), 2 Mbps fast data phase (0.5 us per bit).
        """
        nominal_bit_time_us = 1_000_000 / nominal_baudrate
        data_bit_time_us = 1_000_000 / data_baudrate if self.bit_rate_switch and self.is_fd else nominal_bit_time_us

        # Header fields in nominal phase:
        # SOF (1) + Arbitration (11 or 29+2) + Control (6 or 8)
        header_bits = 1 + (32 if self.is_extended_id else 12) + (8 if self.is_fd else 6)

        # Payload bits
        payload_bits = len(self.data) * 8

        # CRC bits (15 for classical CAN, 17/21 for FD)
        if not self.is_fd:
            crc_bits = 15 + 1  # CRC + CRC Delimiter
        else:
            crc_bits = (17 if len(self.data) <= 16 else 21) + 1

        # Trailer bits (ACK slot + Delimiter + EOF 7 bits + Intermission 3 bits = 12 bits)
        trailer_bits = 12

        # Bit stuffing: In CAN, after 5 identical consecutive bits, a reverse bit is inserted.
        # Average bit stuffing adds approximately 15% - 20% to header, payload, and CRC.
        stuffing_factor = 1.18

        if not (self.is_fd and self.bit_rate_switch):
            # Classical CAN or CAN FD without bit-rate switching (all at nominal speed)
            total_stuffed_bits = (header_bits + payload_bits + crc_bits) * stuffing_factor + trailer_bits
            duration_us = int(math.ceil(total_stuffed_bits * nominal_bit_time_us))
        else:
            # CAN FD with BRS: Header & trailer at nominal, payload & CRC at data baudrate
            nominal_duration = (header_bits * stuffing_factor + trailer_bits) * nominal_bit_time_us
            data_duration = ((payload_bits + crc_bits) * stuffing_factor) * data_bit_time_us
            duration_us = int(math.ceil(nominal_duration + data_duration))

        return max(duration_us, 1)  # At least 1 microsecond

    def __repr__(self) -> str:
        id_str = f"0x{self.arbitration_id:08X}" if self.is_extended_id else f"0x{self.arbitration_id:03X}"
        fd_tag = "FD" if self.is_fd else "CAN"
        brs_tag = "+BRS" if self.bit_rate_switch else ""
        hex_data = self.data.hex().upper() if self.data else "<empty>"
        return f"CANFrame({fd_tag}{brs_tag} ID={id_str}, DLC={self.dlc}, Data={hex_data}, From={self.sender_ecu})"

