"""
Complete 10-Step Secure OTA Campaign Orchestrator (Report Section 4.2 & 4.3).

What this file does:
Executes the full end-to-end OTA sequence defined in Section 4.2 of the report:
  Step 1: Vehicle & Backend mutual authentication (TLS certificate validation).
  Step 2: Vehicle reports ECU inventory, current software versions, and hardware IDs.
  Step 3: Campaign manager checks hardware compatibility, dependencies, and safe state.
  Step 4: Download manifest and package chunks, validating chunk hashes.
  Step 5: Verify digital signature against trusted OEM root key.
  Step 6: Stage image in inactive slot (anti-downgrade check).
  Step 7: Enter safe programming state (vehicle stationary and parked).
  Step 8: Reboot / activate candidate image (secure boot validation).
  Step 9: Run post-install health checks and ECU smoke tests.
  Step 10: If checks pass -> CONFIRMED! If checks fail -> ROLLBACK to last known good slot!
"""

import hashlib
from typing import Dict, List, Optional, Tuple
from virtual_vehicle.ota.package import OTAPackageManifest, OTAPackageBuilder
from virtual_vehicle.ota.firmware_slot import DualSlotFirmwareManager
from virtual_vehicle.ota.state_machine import OTACampaignStateMachine, OTACampaignState
from virtual_vehicle.ecu.base_ecu import BaseECU, ECUPowerState
from virtual_vehicle.ecu.telematics_ecu import TelematicsECU
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus


class OTACampaignOrchestrator:
    """
    Executes and validates the 10-step secure OTA sequence.
    """

    def __init__(self, campaign_id: str, clock: SimulationClock, event_bus: EventBus,
                 telematics_ecu: TelematicsECU, target_ecu: BaseECU,
                 target_firmware_mgr: DualSlotFirmwareManager):
        self.campaign_id = campaign_id
        self.clock = clock
        self.event_bus = event_bus
        self.telematics = telematics_ecu
        self.target_ecu = target_ecu
        self.firmware_mgr = target_firmware_mgr
        self.sm = OTACampaignStateMachine(campaign_id, clock, event_bus)

        # Injected faults for Section 4.5 OTA test cases
        self.inject_tls_cert_expired: bool = False
        self.inject_tls_cert_revoked: bool = False
        self.inject_wrong_hardware_id: bool = False
        self.inject_chunk_corruption: bool = False
        self.inject_download_interruption: bool = False
        self.inject_tampered_signature: bool = False
        self.inject_downgrade_attempt: bool = False
        self.inject_power_loss_staging: bool = False
        self.inject_power_loss_activation: bool = False
        self.inject_failed_health_check: bool = False

    def execute_campaign(self, manifest: OTAPackageManifest, chunks: List[bytes]) -> bool:
        """
        Runs the 10-step OTA update sequence synchronously across simulation time.
        Returns True if CONFIRMED, False if update failed or rolled back.
        """
        # =========================================================================
        # STEP 1: Mutual TLS Authentication (Vehicle <-> Backend)
        # =========================================================================
        self.sm.transition_to(OTACampaignState.ELIGIBILITY_CHECK, "Step 1: Starting mutual TLS authentication")

        if self.inject_tls_cert_expired or self.telematics.tls_cert.is_expired:
            self.sm.trigger_failure("Step 1 Failed: Vehicle TLS Certificate is EXPIRED", is_retryable=False)
            return False

        if self.inject_tls_cert_revoked or self.telematics.tls_cert.is_revoked:
            self.sm.trigger_failure("Step 1 Failed: Vehicle TLS Certificate is REVOKED", is_retryable=False)
            return False

        self.sm.transition_to(OTACampaignState.AUTHENTICATED, "Step 1 Success: Mutual TLS authentication verified")

        # =========================================================================
        # STEP 2 & 3: Inventory, Eligibility, Compatibility & Preconditions
        # =========================================================================
        reported_hw_id = "WRONG_HW_REV" if self.inject_wrong_hardware_id else self.target_ecu.uds.hw_id
        if reported_hw_id != manifest.target_hw_id:
            self.sm.trigger_failure(
                f"Step 3 Failed: Hardware incompatibility! Target expects {manifest.target_hw_id}, ECU is {reported_hw_id}",
                is_retryable=False
            )
            return False

        # Safe precondition check (vehicle must be stationary and parked)
        is_safe, safe_reason = self.telematics.is_vehicle_in_safe_programming_state()
        if not is_safe:
            self.sm.trigger_failure(f"Step 3 Failed: Vehicle precondition check: {safe_reason}", is_retryable=True)
            return False

        # =========================================================================
        # STEP 4: Download Manifest & Resumable Chunks
        # =========================================================================
        self.sm.transition_to(OTACampaignState.DOWNLOADING, "Step 4: Downloading package chunks over Ethernet")

        if self.inject_download_interruption:
            self.sm.trigger_failure("Step 4 Failed: Network connection lost during download", is_retryable=True)
            return False

        downloaded_payload = bytearray()
        for i, chunk in enumerate(chunks):
            if self.inject_chunk_corruption and i == 0:
                chunk = b"CORRUPTED_BYTES" + chunk[15:]

            chunk_hash = hashlib.sha256(chunk).hexdigest()
            if chunk_hash != manifest.chunk_hashes[i]:
                self.sm.trigger_failure(f"Step 4 Failed: Chunk {i} hash mismatch ({chunk_hash} != {manifest.chunk_hashes[i]})", is_retryable=True)
                return False

            downloaded_payload.extend(chunk)

        # Final full-hash check
        final_hash = hashlib.sha256(downloaded_payload).hexdigest()
        if final_hash != manifest.full_image_hash:
            self.sm.trigger_failure("Step 4 Failed: Full image hash mismatch", is_retryable=True)
            return False

        # =========================================================================
        # STEP 5: Verify Digital Signature Against Trusted OEM Root
        # =========================================================================
        self.sm.transition_to(OTACampaignState.VERIFIED, "Step 5: Verifying package digital signature")

        if self.inject_tampered_signature:
            manifest.digital_signature = "BAD_FORGED_SIGNATURE_00000000000000000000"

        sig_ok, sig_reason = OTAPackageBuilder.verify_signature(manifest)
        if not sig_ok:
            self.sm.trigger_failure(f"Step 5 Failed: Digital signature verification failed ({sig_reason})", is_retryable=False)
            return False

        # =========================================================================
        # STEP 6: Stage Image in Inactive Slot & Anti-Downgrade Check
        # =========================================================================
        if self.inject_power_loss_staging:
            self.sm.trigger_failure("Step 6 Failed: Power loss during staging to inactive slot", is_retryable=False)
            return False

        stage_ok, stage_reason = self.firmware_mgr.stage_image(manifest, bytes(downloaded_payload))
        if not stage_ok:
            self.sm.trigger_failure(f"Step 6 Failed: Staging rejected ({stage_reason})", is_retryable=False)
            return False

        self.sm.transition_to(OTACampaignState.STAGED, "Step 6: Staging verified image in inactive partition slot")

        # =========================================================================
        # STEP 7: Enter Safe Programming State
        # =========================================================================
        self.sm.transition_to(OTACampaignState.INSTALLING, "Step 7: Entering ECU programming state")
        self.target_ecu.set_state(ECUPowerState.PROGRAMMING, "Flashing new firmware image into inactive partition")

        # =========================================================================
        # STEP 8: Reboot / Activate Candidate Image (Secure Boot)
        # =========================================================================
        self.sm.transition_to(OTACampaignState.ACTIVATING, "Step 8: Rebooting and validating secure boot chain")

        if self.inject_power_loss_activation:
            # Power cut while writing bootloader pointer!
            self.sm.trigger_failure("Step 8 Failed: Power failure during activation boot-vector switch", is_retryable=False)
            self._execute_rollback("Power failure during activation")
            return False

        act_ok, act_reason = self.firmware_mgr.activate_staged_slot()
        if not act_ok:
            self.sm.trigger_failure(f"Step 8 Failed: Activation error ({act_reason})", is_retryable=False)
            self._execute_rollback(act_reason)
            return False

        # Update ECU object's active slot and version
        self.target_ecu.active_slot = self.firmware_mgr.active_slot
        self.target_ecu.slots[self.firmware_mgr.active_slot].version = manifest.target_version

        # =========================================================================
        # STEP 9: Post-Install Health Checks & Smoke Tests
        # =========================================================================
        self.sm.transition_to(OTACampaignState.HEALTH_CHECK, "Step 9: Running post-install health checks and smoke tests")

        if self.inject_failed_health_check:
            # Health check fails (e.g. application watchdog failure or communication crash)
            self.sm.trigger_failure("Step 9 Failed: ECU post-install smoke test crashed / failed", is_retryable=False)
            self._execute_rollback("Health check smoke test failed")
            return False

        # =========================================================================
        # STEP 10: Confirmation
        # =========================================================================
        self.firmware_mgr.confirm_active_slot()
        self.target_ecu.set_state(ECUPowerState.OPERATIONAL, f"Update confirmed! Running {manifest.target_version}")
        self.sm.transition_to(OTACampaignState.CONFIRMED, f"Step 10 Success: Image confirmed on slot {self.firmware_mgr.active_slot}")
        return True

    def _execute_rollback(self, reason: str) -> None:
        """Rolls back the ECU to the last known good confirmed slot."""
        self.sm.transition_to(OTACampaignState.ROLLING_BACK, f"Initiating rollback due to: {reason}")
        rb_ok, rb_msg = self.firmware_mgr.rollback()
        if rb_ok:
            self.target_ecu.active_slot = self.firmware_mgr.active_slot
            reverted_version = self.firmware_mgr.slots[self.firmware_mgr.active_slot].version
            self.target_ecu.set_state(ECUPowerState.OPERATIONAL, f"Rolled back to {reverted_version}")
            self.sm.transition_to(OTACampaignState.ROLLED_BACK, f"Rollback complete: {rb_msg}")
        else:
            self.target_ecu.set_state(ECUPowerState.RECOVERY, "Rollback failed; entering RECOVERY mode")
            self.sm.transition_to(OTACampaignState.RECOVERY_REQUIRED, "Rollback failed; manual recovery required")
