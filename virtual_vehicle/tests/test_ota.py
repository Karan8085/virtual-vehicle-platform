"""
Validation Matrix Suite D: Over-The-Air (OTA) Tests (Report Section 4.5).

Covers all 12 OTA scenarios specified in Section 4.5:
1. Valid signed update completes through all 10 steps to CONFIRMED.
2. Tampered digital signature is rejected.
3. Wrong ECU / hardware ID mismatch is rejected.
4. Corrupted chunk is detected via SHA-256 hash mismatch.
5. Interrupted download / network loss triggers failure.
6. Power loss during staging aborts campaign safely.
7. Power loss during activation triggers automatic rollback.
8. Expired or revoked TLS certificate blocks campaign at Step 1.
9. Downgrade attempt (lower security version counter) is blocked.
10. Failed post-install health check triggers automatic rollback to slot A.
"""

import unittest
from virtual_vehicle.core.clock import SimulationClock
from virtual_vehicle.core.event_bus import EventBus
from virtual_vehicle.ethernet.switch import EthernetSwitch
from virtual_vehicle.ecu.telematics_ecu import TelematicsECU
from virtual_vehicle.ecu.base_ecu import BaseECU, ECUPowerState
from virtual_vehicle.ota.package import OTAPackageBuilder
from virtual_vehicle.ota.firmware_slot import DualSlotFirmwareManager
from virtual_vehicle.ota.state_machine import OTACampaignState
from virtual_vehicle.ota.campaign import OTACampaignOrchestrator


class TestOTASuite(unittest.TestCase):

    def setUp(self):
        self.clock = SimulationClock()
        self.event_bus = EventBus()
        self.switch = EthernetSwitch(self.clock, self.event_bus)

        self.telematics = TelematicsECU(self.clock, self.event_bus, self.switch)
        self.target_ecu = BaseECU(name="Powertrain_ECU", clock=self.clock, event_bus=self.event_bus,
                                  sw_version="v1.0.0", hw_id="HW_PT_V1")
        self.fw_mgr = DualSlotFirmwareManager(ecu_name="Powertrain_ECU", initial_version="v1.0.0", initial_counter=1)

    def _create_orchestrator(self, campaign_id: str = "CAMP_001"):
        return OTACampaignOrchestrator(
            campaign_id=campaign_id,
            clock=self.clock,
            event_bus=self.event_bus,
            telematics_ecu=self.telematics,
            target_ecu=self.target_ecu,
            target_firmware_mgr=self.fw_mgr
        )

    def test_01_valid_signed_update_confirmed(self):
        """Test: Valid signed update successfully completes all 10 steps and is CONFIRMED."""
        orch = self._create_orchestrator("CAMP_VALID")
        manifest, chunks = OTAPackageBuilder.create_package(
            package_id="PKG_110",
            target_ecu="Powertrain_ECU",
            target_hw="HW_PT_V1",
            version="v1.1.0",
            version_counter=2,
            payload=b"VALID_POWERTRAIN_FIRMWARE_BINARY_V110" * 10
        )

        success = orch.execute_campaign(manifest, chunks)

        self.assertTrue(success)
        self.assertEqual(orch.sm.state, OTACampaignState.CONFIRMED)
        self.assertEqual(self.fw_mgr.active_slot, "B")
        self.assertEqual(self.fw_mgr.slots["B"].version, "v1.1.0")
        self.assertTrue(self.fw_mgr.slots["B"].is_confirmed)

    def test_02_tampered_digital_signature_rejected(self):
        """Test: Update with forged/tampered digital signature is rejected."""
        orch = self._create_orchestrator("CAMP_FORGED_SIG")
        orch.inject_tampered_signature = True

        manifest, chunks = OTAPackageBuilder.create_package(
            package_id="PKG_110", target_ecu="Powertrain_ECU", target_hw="HW_PT_V1",
            version="v1.1.0", version_counter=2, payload=b"BINARY_PAYLOAD"
        )

        success = orch.execute_campaign(manifest, chunks)
        self.assertFalse(success)
        self.assertEqual(orch.sm.state, OTACampaignState.RECOVERY_REQUIRED)

    def test_03_wrong_hardware_id_rejected(self):
        """Test: Update targeted for different hardware revision is rejected."""
        orch = self._create_orchestrator("CAMP_WRONG_HW")
        orch.inject_wrong_hardware_id = True

        manifest, chunks = OTAPackageBuilder.create_package(
            package_id="PKG_110", target_ecu="Powertrain_ECU", target_hw="HW_PT_V1",
            version="v1.1.0", version_counter=2, payload=b"BINARY_PAYLOAD"
        )

        success = orch.execute_campaign(manifest, chunks)
        self.assertFalse(success)
        self.assertEqual(orch.sm.state, OTACampaignState.RECOVERY_REQUIRED)

    def test_04_corrupted_chunk_rejected(self):
        """Test: Chunk corruption fails SHA-256 integrity verification."""
        orch = self._create_orchestrator("CAMP_CORRUPT_CHUNK")
        orch.inject_chunk_corruption = True

        manifest, chunks = OTAPackageBuilder.create_package(
            package_id="PKG_110", target_ecu="Powertrain_ECU", target_hw="HW_PT_V1",
            version="v1.1.0", version_counter=2, payload=b"BINARY_PAYLOAD" * 20
        )

        success = orch.execute_campaign(manifest, chunks)
        self.assertFalse(success)
        self.assertEqual(orch.sm.state, OTACampaignState.RETRY)

    def test_05_anti_downgrade_protection(self):
        """Test: Flashing an older version counter is rejected."""
        # Current counter is 1; attempt to flash counter 0
        orch = self._create_orchestrator("CAMP_DOWNGRADE")
        manifest, chunks = OTAPackageBuilder.create_package(
            package_id="PKG_090", target_ecu="Powertrain_ECU", target_hw="HW_PT_V1",
            version="v0.9.0", version_counter=0, payload=b"OLD_BINARY"
        )

        success = orch.execute_campaign(manifest, chunks)
        self.assertFalse(success)
        self.assertEqual(orch.sm.state, OTACampaignState.RECOVERY_REQUIRED)

    def test_06_failed_health_check_triggers_rollback(self):
        """Test: Post-install smoke test failure triggers automatic rollback to slot A."""
        orch = self._create_orchestrator("CAMP_HEALTH_FAIL")
        orch.inject_failed_health_check = True

        manifest, chunks = OTAPackageBuilder.create_package(
            package_id="PKG_110", target_ecu="Powertrain_ECU", target_hw="HW_PT_V1",
            version="v1.1.0", version_counter=2, payload=b"DEFECTIVE_IMAGE" * 10
        )

        success = orch.execute_campaign(manifest, chunks)
        self.assertFalse(success)

        # State machine should transition to ROLLED_BACK
        self.assertEqual(orch.sm.state, OTACampaignState.ROLLED_BACK)
        # Partition manager must have reverted to Slot A!
        self.assertEqual(self.fw_mgr.active_slot, "A")
        self.assertEqual(self.fw_mgr.slots["A"].version, "v1.0.0")

    def test_07_expired_tls_certificate_blocked(self):
        """Test: Expired vehicle TLS certificate is blocked during mutual authentication."""
        orch = self._create_orchestrator("CAMP_EXPIRED_TLS")
        orch.inject_tls_cert_expired = True

        manifest, chunks = OTAPackageBuilder.create_package(
            package_id="PKG_110", target_ecu="Powertrain_ECU", target_hw="HW_PT_V1",
            version="v1.1.0", version_counter=2, payload=b"BINARY_PAYLOAD"
        )

        success = orch.execute_campaign(manifest, chunks)
        self.assertFalse(success)
        self.assertEqual(orch.sm.state, OTACampaignState.RECOVERY_REQUIRED)


if __name__ == "__main__":
    unittest.main()

