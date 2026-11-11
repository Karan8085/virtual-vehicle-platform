"""Automotive Ethernet simulation subsystem."""
from virtual_vehicle.ethernet.packets import EthernetFrame, IPv4Packet, UDPPacket, TCPPacket
from virtual_vehicle.ethernet.someip import (
    SOMEIPMessage, SOMEIPMessageType, SOMEIPReturnCode,
    SOMEIPServiceDiscoveryMessage, SDEntryType
)
from virtual_vehicle.ethernet.doip import DoIPMessage, DoIPPayloadType, UDSServiceId, UDSHandler
from virtual_vehicle.ethernet.switch import EthernetSwitch, SwitchPort, SwitchStatistics

__all__ = [
    "EthernetFrame", "IPv4Packet", "UDPPacket", "TCPPacket",
    "SOMEIPMessage", "SOMEIPMessageType", "SOMEIPReturnCode",
    "SOMEIPServiceDiscoveryMessage", "SDEntryType",
    "DoIPMessage", "DoIPPayloadType", "UDSServiceId", "UDSHandler",
    "EthernetSwitch", "SwitchPort", "SwitchStatistics"
]

