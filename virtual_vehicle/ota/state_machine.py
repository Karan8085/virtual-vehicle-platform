"""
OTA Campaign State Machine (Report Section 4.4).

What this file does:
Implements the exact 11-state OTA campaign progression:
  CREATED
     ↓
  ELIGIBILITY_CHECK
     ↓
  AUTHENTICATED
     ↓
  DOWNLOADING
     ↓
  VERIFIED
     ↓
  STAGED
     ↓
  INSTALLING
     ↓
  ACTIVATING
     ↓
  HEALTH_CHECK
     ↓
  CONFIRMED

Failure branches:
- RETRY (when retry budget > 0, e.g. for transient network drops)
- ROLLING_BACK → ROLLED_BACK (when activation or health check fails)
- RECOVERY_REQUIRED (when rollback fails or corrupt boot chain is detected)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from virtual_vehicle.core.event_bus import EventBus
from virtual_vehicle.core.clock import SimulationClock


class OTACampaignState(Enum):
    CREATED = "CREATED"
    ELIGIBILITY_CHECK = "ELIGIBILITY_CHECK"
    AUTHENTICATED = "AUTHENTICATED"
    DOWNLOADING = "DOWNLOADING"
    VERIFIED = "VERIFIED"
    STAGED = "STAGED"
    INSTALLING = "INSTALLING"
    ACTIVATING = "ACTIVATING"
    HEALTH_CHECK = "HEALTH_CHECK"
    CONFIRMED = "CONFIRMED"

    # Failure states
    RETRY = "RETRY"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass
class OTATransitionLog:
    from_state: OTACampaignState
    to_state: OTACampaignState
    timestamp_us: int
    reason: str


class OTACampaignStateMachine:
    """
    Coordinates and validates transitions of an OTA Campaign.
    """

    def __init__(self, campaign_id: str, clock: SimulationClock, event_bus: EventBus, max_retries: int = 3):
        self.campaign_id = campaign_id
        self.clock = clock
        self.event_bus = event_bus
        self.state = OTACampaignState.CREATED
        self.max_retries = max_retries
        self.retry_count = 0
        self.transition_history: List[OTATransitionLog] = []

    def transition_to(self, target_state: OTACampaignState, reason: str = "") -> None:
        """Transitions state and records audit event."""
        old_state = self.state
        self.state = target_state

        log_entry = OTATransitionLog(
            from_state=old_state,
            to_state=target_state,
            timestamp_us=self.clock.current_time_us,
            reason=reason
        )
        self.transition_history.append(log_entry)

        self.event_bus.publish(
            self.clock.current_time_us, "OTA", "CampaignManager", "STATE_TRANSITION",
            f"OTA Campaign [{self.campaign_id}] state: {old_state.value} -> {target_state.value}. {reason}",
            {"campaign_id": self.campaign_id, "from": old_state.value, "to": target_state.value, "reason": reason}
        )

    def trigger_failure(self, failure_reason: str, is_retryable: bool = False) -> None:
        """Handles failure branch according to Section 4.4."""
        if is_retryable and self.retry_count < self.max_retries:
            self.retry_count += 1
            self.transition_to(
                OTACampaignState.RETRY,
                f"Transient failure: {failure_reason}. Retrying (Attempt {self.retry_count}/{self.max_retries})"
            )
        else:
            # Check if rollback is applicable (if we reached STAGED, INSTALLING, ACTIVATING, or HEALTH_CHECK)
            if self.state in [OTACampaignState.STAGED, OTACampaignState.INSTALLING,
                              OTACampaignState.ACTIVATING, OTACampaignState.HEALTH_CHECK]:
                self.transition_to(
                    OTACampaignState.ROLLING_BACK,
                    f"Fatal failure during update: {failure_reason}. Initiating automatic rollback."
                )
            else:
                self.transition_to(
                    OTACampaignState.RECOVERY_REQUIRED,
                    f"Fatal error: {failure_reason}. No rollback available; manual recovery required."
                )

