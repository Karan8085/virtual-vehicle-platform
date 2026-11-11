"""
Automotive Ethernet Packet Models (Ethernet II, IEEE 802.1Q VLAN, IPv4, UDP, TCP).

What this file does:
Unlike CAN's shared broadcast wire, Automotive Ethernet is a switched packet network.
This file models standard network packet structures:
- Ethernet II Frame with IEEE 802.1Q VLAN tagging (e.g. VLAN 10 = Vehicle Control, VLAN 20 = Diagnostics, VLAN 30 = OTA).
- IPv4 Datagrams (Source & Destination IP addresses).
- UDP & TCP Transports:
  * UDP: Connectionless, low latency (used by SOME/IP events and time-critical telemetry).
  * TCP: Connection-oriented, reliable stream (used by DoIP diagnostics and OTA firmware downloads).
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class EthernetFrame:
    """Represents an Ethernet II frame, optionally tagged with IEEE 802.1Q VLAN."""
    src_mac: str
    dst_mac: str
    vlan_id: Optional[int] = None       # None (untagged) or 1..4094 (VLAN Tagged)
    ethertype: str = "IPv4"             # "IPv4", "ARP", etc.
    payload: Any = None                 # Typically an IPv4Packet or raw bytes
    frame_size_bytes: int = 64          # Size in bytes for bandwidth/delay modeling

    def __post_init__(self):
        # Default minimum Ethernet frame size is 64 bytes
        if self.frame_size_bytes < 64:
            self.frame_size_bytes = 64


@dataclass
class IPv4Packet:
    """Represents an IPv4 packet."""
    src_ip: str
    dst_ip: str
    protocol: str                       # "UDP" or "TCP"
    payload: Any = None                 # UDPPacket, TCPPacket, or raw payload
    ttl: int = 64


@dataclass
class UDPPacket:
    """Represents a UDP datagram."""
    src_port: int
    dst_port: int
    payload: Any = None                 # SOME/IP or raw bytes
    length_bytes: int = 8


@dataclass
class TCPPacket:
    """Represents a TCP segment."""
    src_port: int
    dst_port: int
    flags: str = "DATA"                 # "SYN", "ACK", "DATA", "FIN", "RST"
    seq_num: int = 0
    ack_num: int = 0
    payload: Any = None                 # DoIP message, OTA chunk, or raw payload
    length_bytes: int = 20

