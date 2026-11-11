"""
AUTOSAR SecOC (Secure Onboard Communication) Implementation.

What this file does:
In standard CAN, any node can forge any message ID because CAN has no authentication.
AUTOSAR SecOC solves this by appending cryptographic protection to critical CAN/CAN FD frames.

How SecOC Works (Report Section 2.6):
1. Data ID: A unique identifier for the authenticated message.
2. Freshness Value (FV): A monotonic counter or timestamp that increments with every message.
   - Prevents Replay Attacks (an attacker recording a valid message and sending it later).
   - Replay Window: Tolerate minor counter differences if within acceptable limits.
   - Rollover Handling: Safely handles when counter reaches maximum integer.
3. Message Authentication Code (MAC):
   Calculated using: HMAC-SHA256(Key, DataID + Payload + FreshnessValue).
   The MAC is truncated (e.g. 4 or 8 bytes) to fit inside CAN/CAN FD frames.
4. Verification:
   The receiver calculates the expected MAC using its own local key and verified freshness counter.
   If the MAC matches AND the freshness is fresh, the message is accepted; otherwise rejected!
"""

import hmac
import hashlib
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class SecOCPDU:
    """Represents a Secured PDU containing original payload, freshness counter, and MAC."""
    data_id: int
    payload: bytes
    freshness_counter: int
    mac: bytes  # Truncated cryptographic MAC


class SecOCManager:
    """
    Manages cryptographic keys, freshness counters, and SecOC authentication/verification.
    """

    def __init__(self, replay_window_size: int = 2):
        # Key storage: DataID -> Secret Symmetric Key (128/256 bits)
        self.key_store: Dict[int, bytes] = {}
        # Revoked keys list
        self.revoked_keys: set = set()

        # Transmitter freshness counters: DataID -> current counter
        self.tx_counters: Dict[int, int] = {}
        # Receiver freshness counters: DataID -> last verified counter
        self.rx_counters: Dict[int, int] = {}

        # Replay window: allow counter within (last_counter + 1) to (last_counter + window)
        self.replay_window_size = replay_window_size

    def provision_key(self, data_id: int, key: bytes) -> None:
        """Stores the symmetric key for a specific secured PDU."""
        self.key_store[data_id] = key

    def revoke_key(self, data_id: int) -> None:
        """Revokes a key to simulate compromised or outdated credentials."""
        self.revoked_keys.add(data_id)

    def _compute_mac(self, key: bytes, data_id: int, payload: bytes, freshness: int, mac_length: int = 4) -> bytes:
        """Computes truncated HMAC-SHA256 over (DataID || Payload || Freshness)."""
        data_to_sign = data_id.to_bytes(2, "big") + payload + freshness.to_bytes(8, "big")
        full_mac = hmac.new(key, data_to_sign, hashlib.sha256).digest()
        return full_mac[:mac_length]

    def build_secured_pdu(self, data_id: int, payload: bytes, mac_length: int = 4) -> SecOCPDU:
        """
        Called by transmitting ECU to sign a message before placing onto CAN / CAN FD.
        Increments the monotonic freshness counter.
        """
        key = self.key_store.get(data_id)
        if not key:
            raise KeyError(f"No key provisioned for SecOC DataID 0x{data_id:04X}")
        if data_id in self.revoked_keys:
            raise PermissionError(f"Key for SecOC DataID 0x{data_id:04X} is REVOKED")

        # Increment monotonic counter
        counter = self.tx_counters.get(data_id, 0) + 1
        self.tx_counters[data_id] = counter

        mac = self._compute_mac(key, data_id, payload, counter, mac_length)
        return SecOCPDU(data_id=data_id, payload=payload, freshness_counter=counter, mac=mac)

    def verify_secured_pdu(self, pdu: SecOCPDU, mac_length: int = 4) -> Tuple[bool, str]:
        """
        Called by receiving ECU to verify authenticity, integrity, and freshness.
        Returns: (is_valid: bool, reason: str)
        """
        key = self.key_store.get(pdu.data_id)
        if not key:
            return False, f"UNKNOWN_DATA_ID: No key registered for DataID 0x{pdu.data_id:04X}"
        if pdu.data_id in self.revoked_keys:
            return False, f"KEY_REVOKED: Key for DataID 0x{pdu.data_id:04X} has been revoked"

        last_counter = self.rx_counters.get(pdu.data_id, 0)

        # 1. Freshness Check (Monotonic Counter / Anti-Replay)
        if pdu.freshness_counter <= last_counter:
            return False, (
                f"REPLAY_OR_STALE: Received counter {pdu.freshness_counter} <= last counter {last_counter}. "
                "Possible replay attack!"
            )

        if pdu.freshness_counter > (last_counter + self.replay_window_size + 1):
            return False, (
                f"FRESHNESS_DESYNC: Counter {pdu.freshness_counter} jumped ahead of expected window "
                f"(last was {last_counter}, max window was {last_counter + self.replay_window_size + 1})."
            )

        # 2. Cryptographic MAC Check
        expected_mac = self._compute_mac(key, pdu.data_id, pdu.payload, pdu.freshness_counter, mac_length)
        if not hmac.compare_digest(pdu.mac, expected_mac):
            return False, (
                f"INVALID_MAC: Cryptographic signature mismatch! "
                f"Expected {expected_mac.hex().upper()}, got {pdu.mac.hex().upper()}."
            )

        # Passed all checks -> update receiver freshness state
        self.rx_counters[pdu.data_id] = pdu.freshness_counter
        return True, "ACCEPT: Freshness and MAC successfully verified"

    def pack_pdu_to_bytes(self, pdu: SecOCPDU) -> bytes:
        """Serializes SecOC PDU into bytes to transmit inside a CAN FD frame (Payload + 2B Counter + 4B MAC)."""
        # Format: [Payload] + [2-byte Counter] + [4-byte MAC]
        counter_bytes = (pdu.freshness_counter & 0xFFFF).to_bytes(2, "big")
        return pdu.payload + counter_bytes + pdu.mac

    def unpack_bytes_to_pdu(self, data_id: int, raw_bytes: bytes, mac_len: int = 4) -> SecOCPDU:
        """Deserializes raw bytes received from CAN FD frame into SecOCPDU."""
        if len(raw_bytes) < (2 + mac_len):
            raise ValueError("Raw bytes too short to contain SecOC counter and MAC")
        payload = raw_bytes[:-(2 + mac_len)]
        counter = int.from_bytes(raw_bytes[-(2 + mac_len):-mac_len], "big")
        mac = raw_bytes[-mac_len:]
        return SecOCPDU(data_id=data_id, payload=payload, freshness_counter=counter, mac=mac)

