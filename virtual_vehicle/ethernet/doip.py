"""
DoIP (ISO 13400 Diagnostic Communication over IP) & UDS Diagnostics.

What this file does:
Diagnostics in modern vehicles allow service tools and backend clouds
to query ECU health, read/clear DTCs (Diagnostic Trouble Codes), read software versions,
and switch into programming sessions.

ISO 13400 DoIP Protocol (Section 3.2 & 3.7):
- Routing Activation: An external diagnostic tester or telematics unit must activate
  its logical connection with the DoIP entity before sending diagnostic commands.
- Logical Addressing: Uses 16-bit logical addresses (e.g., 0x0E80 for Tester, 0x1001 for Powertrain ECU).
- Carries UDS (Unified Diagnostic Services - ISO 14229) payloads:
  * 0x10: DiagnosticSessionControl (Default, Programming, Extended)
  * 0x22: ReadDataByIdentifier (DID: VIN, Software Version, Hardware ID)
  * 0x14: ClearDTC (Clear fault codes)
  * 0x19: ReadDTC (Read fault codes)
  * 0x27: SecurityAccess (Challenge-response seed & key)
  * 0x31: RoutineControl (Self-test routines)
"""

from enum import IntEnum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple


class DoIPPayloadType(IntEnum):
    ROUTING_ACTIVATION_REQUEST = 0x0005
    ROUTING_ACTIVATION_RESPONSE = 0x0006
    DIAGNOSTIC_MESSAGE = 0x8001
    DIAGNOSTIC_POSITIVE_ACK = 0x8002
    DIAGNOSTIC_NEGATIVE_ACK = 0x8003


class UDSServiceId(IntEnum):
    DIAGNOSTIC_SESSION_CONTROL = 0x10
    CLEAR_DTC = 0x14
    READ_DTC_INFO = 0x19
    READ_DATA_BY_ID = 0x22
    SECURITY_ACCESS = 0x27
    ROUTINE_CONTROL = 0x31
    NEGATIVE_RESPONSE = 0x7F


@dataclass
class DoIPMessage:
    """Represents an ISO 13400 DoIP message."""
    payload_type: DoIPPayloadType
    source_address: int                 # E.g., 0x0E80 (Tester)
    target_address: int                 # E.g., 0x1000 (Gateway), 0x1001 (Powertrain)
    uds_payload: bytes = b""            # Raw UDS request or response bytes
    activation_code: int = 0            # 0x10 = Successfully activated

    def __repr__(self) -> str:
        return (f"DoIP({self.payload_type.name}, Src=0x{self.source_address:04X}, "
                f"Dst=0x{self.target_address:04X}, UDS_Len={len(self.uds_payload)})")


class UDSHandler:
    """
    Standard UDS request handler providing ECU identification,
    software/hardware versions, DTC management, and session control.
    """

    def __init__(self, ecu_name: str, sw_version: str = "v1.0.0", hw_id: str = "HW_REV_A"):
        self.ecu_name = ecu_name
        self.sw_version = sw_version
        self.hw_id = hw_id
        self.active_session: int = 0x01  # 0x01 = Default Session, 0x02 = Programming, 0x03 = Extended
        self.security_unlocked: bool = False
        self.active_dtcs: List[str] = []

    def handle_request(self, request: bytes) -> bytes:
        """Processes a UDS request and returns UDS response bytes."""
        if not request:
            return bytes([UDSServiceId.NEGATIVE_RESPONSE, 0x00, 0x13])  # Incorrect message length

        sid = request[0]

        # 0x10: DiagnosticSessionControl
        if sid == UDSServiceId.DIAGNOSTIC_SESSION_CONTROL:
            if len(request) < 2:
                return bytes([UDSServiceId.NEGATIVE_RESPONSE, sid, 0x13])
            session_type = request[1]
            self.active_session = session_type
            # Positive response: 0x50 + session_type
            return bytes([0x50, session_type])

        # 0x22: ReadDataByIdentifier
        elif sid == UDSServiceId.READ_DATA_BY_ID:
            if len(request) < 3:
                return bytes([UDSServiceId.NEGATIVE_RESPONSE, sid, 0x13])
            did = (request[1] << 8) | request[2]

            if did == 0xF189:  # Software Version
                sw_bytes = self.sw_version.encode("utf-8")
                return bytes([0x62, request[1], request[2]]) + sw_bytes
            elif did == 0xF191:  # Hardware ID
                hw_bytes = self.hw_id.encode("utf-8")
                return bytes([0x62, request[1], request[2]]) + hw_bytes
            elif did == 0xF190:  # VIN
                vin_bytes = b"WP0VIRTUAL123456"
                return bytes([0x62, request[1], request[2]]) + vin_bytes
            else:
                return bytes([UDSServiceId.NEGATIVE_RESPONSE, sid, 0x31])  # Request out of range

        # 0x19: ReadDTCInformation
        elif sid == UDSServiceId.READ_DTC_INFO:
            resp = bytearray([0x59, 0x02, len(self.active_dtcs)])
            for dtc in self.active_dtcs:
                resp.extend(dtc.encode("utf-8")[:4])
            return bytes(resp)

        # 0x14: ClearDiagnosticInformation
        elif sid == UDSServiceId.CLEAR_DTC:
            self.active_dtcs.clear()
            return bytes([0x54])  # Positive response

        # 0x27: SecurityAccess
        elif sid == UDSServiceId.SECURITY_ACCESS:
            subfunction = request[1] if len(request) > 1 else 0x01
            if subfunction == 0x01:  # Request Seed
                seed = b"\x12\x34\x56\x78"
                return bytes([0x67, 0x01]) + seed
            elif subfunction == 0x02:  # Send Key
                key = request[2:] if len(request) >= 6 else b""
                expected_key = b"\x87\x65\x43\x21"
                if key == expected_key:
                    self.security_unlocked = True
                    return bytes([0x67, 0x02])
                else:
                    return bytes([UDSServiceId.NEGATIVE_RESPONSE, sid, 0x35])  # Invalid Key

        # 0x31: RoutineControl
        elif sid == UDSServiceId.ROUTINE_CONTROL:
            return bytes([0x71, 0x01, 0x02, 0x03, 0x00])  # Routine completed successfully

        # Unknown service
        return bytes([UDSServiceId.NEGATIVE_RESPONSE, sid, 0x11])  # Service not supported

