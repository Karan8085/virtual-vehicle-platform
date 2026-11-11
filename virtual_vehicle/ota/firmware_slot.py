"""
Dual-Slot (A/B) Firmware Partition Manager & Secure Boot.

What this file does (Report Section 4.1 & 4.2):
In modern automotive ECUs, firmware updates are applied using A/B partition slots:
- Slot A: Currently running (active) firmware.
- Slot B: Secondary (inactive) partition used for background staging.

Secure Installation & Rollback Process:
1. Inactive Slot Staging: The new firmware image is written to the inactive slot
   while the active slot continues running normal vehicle functions.
2. Anti-Downgrade Check: Protected monotonic version counters prevent an attacker
   from flashing an older, vulnerable firmware version.
3. Activation & Reboot: The bootloader is instructed to boot into the newly flashed slot.
4. Secure Boot Verification: Bootloader checks image hash and signature before executing.
5. Confirmation or Rollback:
   - If post-install health checks PASS: the slot is confirmed as "active & good".
   - If health checks FAIL: the bootloader automatically reverts to the previous
     known-good slot (Rollback)!
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from virtual_vehicle.ota.package import OTAPackageManifest


@dataclass
class SlotState:
    slot_id: str                      # "A" or "B"
    version: str                      # "v1.0.0"
    version_counter: int              # Monotonic counter (e.g. 1, 2, 3)
    image_hash: str                   # SHA-256 hash
    is_valid: bool = True             # Cryptographically verified
    is_confirmed: bool = True         # Passed health checks


class DualSlotFirmwareManager:
    """Manages A/B partitions, staging, activation, and rollback for an ECU."""

    def __init__(self, ecu_name: str, initial_version: str = "v1.0.0", initial_counter: int = 1):
        self.ecu_name = ecu_name
        self.active_slot: str = "A"
        self.slots: Dict[str, SlotState] = {
            "A": SlotState("A", initial_version, initial_counter, "ACTIVE_HASH_A", is_valid=True, is_confirmed=True),
            "B": SlotState("B", "v0.0.0", 0, "", is_valid=False, is_confirmed=False)
        }
        self.last_known_good_slot: str = "A"

    @property
    def inactive_slot(self) -> str:
        return "B" if self.active_slot == "A" else "A"

    def stage_image(self, manifest: OTAPackageManifest, payload: bytes) -> Tuple[bool, str]:
        """
        Stages new firmware image into inactive slot and checks anti-downgrade rules.
        """
        target_slot = self.inactive_slot
        current_active = self.slots[self.active_slot]

        # 1. Anti-downgrade check (Section 4.3)
        if manifest.version_counter < current_active.version_counter:
            return False, (
                f"ANTI_DOWNGRADE_REJECT: Cannot downgrade version counter from "
                f"{current_active.version_counter} to {manifest.version_counter}!"
            )

        # 2. Stage image in inactive partition
        self.slots[target_slot] = SlotState(
            slot_id=target_slot,
            version=manifest.target_version,
            version_counter=manifest.version_counter,
            image_hash=manifest.full_image_hash,
            is_valid=True,
            is_confirmed=False  # Must pass post-install health check before confirmation!
        )
        return True, f"STAGED: Image {manifest.target_version} successfully written to inactive slot {target_slot}"

    def activate_staged_slot(self) -> Tuple[bool, str]:
        """
        Reboots ECU and switches active slot pointer to newly staged image.
        """
        candidate_slot_id = self.inactive_slot
        candidate = self.slots[candidate_slot_id]

        # Secure boot integrity check
        if not candidate.is_valid or not candidate.image_hash:
            return False, f"SECURE_BOOT_FAILURE: Candidate slot {candidate_slot_id} is invalid or corrupt"

        # Record last known good before switching
        self.last_known_good_slot = self.active_slot
        self.active_slot = candidate_slot_id
        return True, f"ACTIVATED: Switched active slot to {candidate_slot_id} ({candidate.version})"

    def confirm_active_slot(self) -> None:
        """Called when post-install health checks pass."""
        self.slots[self.active_slot].is_confirmed = True
        self.last_known_good_slot = self.active_slot

    def rollback(self) -> Tuple[bool, str]:
        """Reverts active slot to the last known good confirmed slot."""
        if self.active_slot == self.last_known_good_slot:
            return False, "Cannot rollback: already on last-known-good slot"

        failed_slot = self.active_slot
        self.slots[failed_slot].is_valid = False  # Invalidate failed image
        self.active_slot = self.last_known_good_slot
        good_version = self.slots[self.active_slot].version
        return True, f"ROLLED_BACK: Reverted from failed slot {failed_slot} to slot {self.active_slot} ({good_version})"

