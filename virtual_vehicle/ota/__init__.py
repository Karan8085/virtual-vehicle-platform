"""OTA Update and Campaign subsystem."""
from virtual_vehicle.ota.package import OTAPackageManifest, OTAPackageBuilder
from virtual_vehicle.ota.firmware_slot import DualSlotFirmwareManager, SlotState
from virtual_vehicle.ota.state_machine import OTACampaignState, OTACampaignStateMachine, OTATransitionLog
from virtual_vehicle.ota.campaign import OTACampaignOrchestrator

__all__ = [
    "OTAPackageManifest", "OTAPackageBuilder",
    "DualSlotFirmwareManager", "SlotState",
    "OTACampaignState", "OTACampaignStateMachine", "OTATransitionLog",
    "OTACampaignOrchestrator"
]

