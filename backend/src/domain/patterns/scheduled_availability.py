"""ScheduledAvailability pattern - resource with cyclic on/off schedule."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class ScheduledAvailabilityPattern(BasePattern):
    """
    Scheduled Availability (Shift Schedule) pattern.

    A cyclic signal source that alternates between Active and Inactive states
    on fixed deterministic intervals. Consumers gate their Start transitions
    via READ arcs to the Active place — while Active has a token, the consumer
    can process; when the token is removed (shift end), the consumer is blocked.

    Structure:
        [Active (1|0)] -> [GoOff (DET, on_duration)]  -> [Inactive]
        [Inactive]     -> [GoOn  (DET, off_duration)] -> [Active]

    Consumers connect to Active via a READ arc (token required but not consumed):
        [Active] --(READ)--> [Consumer_Start]

    Use cases:
    - Factory runs two 8-hour shifts with 8-hour downtime
    - Office system available 9h (business hours) then off 15h
    - Scheduled maintenance: machine runs 23h, maintenance window 1h
    """

    tool_cursor_width = 500.0

    @property
    def name(self) -> str:
        return "ScheduledAvailability"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        on_duration: float = 28800.0,
        off_duration: float = 28800.0,
        starts_available: bool = True,
    ) -> PatternResult:
        """
        Apply the ScheduledAvailability pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "DayShift", "Maintenance")
            x, y: Base coordinates
            on_duration: Duration of active window in seconds (default: 8h)
            off_duration: Duration of inactive window in seconds (default: 8h)
            starts_available: If True (default), first token starts in Active.
                              If False, simulation starts in off-period.

        Returns:
            PatternResult with:
              - interface.input_place_id: Active place (attach READ arcs here)
              - interface.output_place_id: Active place (same)
              - metadata["signal_place_id"]: Active place ID
              - metadata["inactive_place_id"]: Inactive place ID
              - metadata["on_transition_id"]: GoOff transition ID
              - metadata["off_transition_id"]: GoOn transition ID
        """
        place_ids: list[str] = []
        transition_ids: list[str] = []

        # Active place — 1 token = resource is available
        p_active = net.add_place(
            name=f"{instance_name}_Active",
            tokens=1 if starts_available else 0,
            x=x + 100,
            y=y,
        )
        place_ids.append(p_active.id)

        # Inactive place — 1 token = resource is in off-period
        p_inactive = net.add_place(
            name=f"{instance_name}_Inactive",
            tokens=0 if starts_available else 1,
            x=x + 300,
            y=y,
        )
        place_ids.append(p_inactive.id)

        # GoOff: Active → Inactive (fires after on_duration; ends the active window)
        t_gooff = net.add_transition(
            name=f"{instance_name}_GoOff",
            mean_delay=on_duration,
            distribution=DistributionType.DET,
            x=x + 200,
            y=y,
        )
        transition_ids.append(t_gooff.id)

        # GoOn: Inactive → Active (fires after off_duration; starts the next active window)
        t_goon = net.add_transition(
            name=f"{instance_name}_GoOn",
            mean_delay=off_duration,
            distribution=DistributionType.DET,
            x=x + 400,
            y=y,
        )
        transition_ids.append(t_goon.id)

        net.add_arc(source_id=p_active.id, target_id=t_gooff.id)
        net.add_arc(source_id=t_gooff.id, target_id=p_inactive.id)

        net.add_arc(source_id=p_inactive.id, target_id=t_goon.id)
        net.add_arc(source_id=t_goon.id, target_id=p_active.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_active.id,
                output_place_id=p_active.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "signal_place_id": p_active.id,
                "inactive_place_id": p_inactive.id,
                "on_transition_id": t_gooff.id,
                "off_transition_id": t_goon.id,
            },
        )
