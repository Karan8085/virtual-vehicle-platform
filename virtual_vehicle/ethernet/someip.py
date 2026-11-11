"""
SOME/IP (Scalable service-Oriented MiddlewarE over IP) & SOME/IP-SD Protocol.

What this file does:
In modern automotive architectures, ECUs communicate as clients and servers
using SOME/IP rather than simple signal broadcasts:
1. SOME/IP Message:
   - Service ID: Identifier for the service (e.g. 0x1234 for Powertrain Service)
   - Method ID / Event ID: Specific function or event (e.g. 0x0001 for GetSpeed, 0x8001 for SpeedEvent)
   - Message Type:
     * REQUEST: Client calls server method
     * RESPONSE: Server returns answer
     * NOTIFICATION: Server broadcasts event to subscribers
   - Return Code: E_OK (0x00), E_NOT_OK (0x01), E_UNKNOWN_SERVICE (0x02), etc.
2. SOME/IP Service Discovery (SOME/IP-SD):
   - Dynamic service discovery: ECUs announce what services they offer (OFFER_SERVICE),
     query what services exist (FIND_SERVICE), and subscribe to events (SUBSCRIBE_EVENTGROUP).
"""

from enum import IntEnum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


class SOMEIPMessageType(IntEnum):
    REQUEST = 0x00
    REQUEST_NO_RETURN = 0x01
    NOTIFICATION = 0x02
    RESPONSE = 0x80
    ERROR = 0x81


class SOMEIPReturnCode(IntEnum):
    E_OK = 0x00
    E_NOT_OK = 0x01
    E_UNKNOWN_SERVICE = 0x02
    E_UNKNOWN_METHOD = 0x03
    E_NOT_READY = 0x04
    E_NOT_REACHABLE = 0x05
    E_WRONG_INTERFACE_VERSION = 0x06
    E_MALFORMED_MESSAGE = 0x07


@dataclass
class SOMEIPMessage:
    """Represents a standard SOME/IP message."""
    service_id: int
    method_id: int                      # Method ID (0x0001..0x7FFF) or Event ID (0x8001..0xFFFF)
    client_id: int = 0x0001
    session_id: int = 0x0001
    message_type: SOMEIPMessageType = SOMEIPMessageType.REQUEST
    return_code: SOMEIPReturnCode = SOMEIPReturnCode.E_OK
    protocol_version: int = 1
    interface_version: int = 1
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_event(self) -> bool:
        """Events have method_id >= 0x8000 and message_type == NOTIFICATION."""
        return self.method_id >= 0x8000 or self.message_type == SOMEIPMessageType.NOTIFICATION

    def __repr__(self) -> str:
        t_name = self.message_type.name
        ret_name = self.return_code.name
        return (f"SOMEIP(Service=0x{self.service_id:04X}, Method/Event=0x{self.method_id:04X}, "
                f"Type={t_name}, Ret={ret_name}, Payload={self.payload})")


class SDEntryType(IntEnum):
    FIND_SERVICE = 0x00
    OFFER_SERVICE = 0x01
    STOP_OFFER = 0x02
    SUBSCRIBE_EVENTGROUP = 0x06
    SUBSCRIBE_ACK = 0x07


@dataclass
class SOMEIPServiceDiscoveryMessage:
    """Represents a SOME/IP-SD message for discovering services and managing event subscriptions."""
    entry_type: SDEntryType
    service_id: int
    instance_id: int = 1
    major_version: int = 1
    eventgroup_id: Optional[int] = None
    ttl_seconds: int = 3
    endpoint_ip: str = ""
    endpoint_port: int = 30490

    def __repr__(self) -> str:
        return (f"SOMEIP-SD({self.entry_type.name}, Service=0x{self.service_id:04X}, "
                f"Instance={self.instance_id}, TTL={self.ttl_seconds}s, EP={self.endpoint_ip}:{self.endpoint_port})")

