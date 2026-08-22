"""PriorityChoice pattern - choice between alternatives based on resource availability."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class PriorityChoicePattern(BasePattern):
    """
    Priority Choice pattern for resource-dependent branching.

    Implements "do X if resources available, otherwise do Y" logic.
    Uses priority to ensure the preferred transition fires first when enabled.

    Structure:
        [P: Input] -----> [T: Primary] (priority=1) --> [P: Success]
            |                   ^
            |                   |
            |             [P: Resource] (required for Primary)
            |
            +-----------> [T: Alternative] (priority=0) --> [P: Fallback]

    Key behavior:
    - Primary requires Input + Resource tokens (AND logic)
    - Alternative requires only Input token
    - Primary has higher priority, so it fires first if Resource available
    - If Resource unavailable, Alternative fires (fallback behavior)

    Use cases:
    - "Fill conveyor section if parts available, else leave empty"
    - "Process order if inventory available, else backorder"
    - "Use primary server if free, else use backup"
    - Assembly with optional components
    """

    @property
    def name(self) -> str:
        return "PriorityChoice"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        resource_place_ids: list[dict] | None = None,
        primary_delay: float = 0.0,
        alternative_delay: float = 0.0,
        primary_name: str = "Success",
        alternative_name: str = "Fallback",
    ) -> PatternResult:
        """
        Apply the PriorityChoice pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "SectionFill")
            x, y: Base coordinates
            resource_place_ids: List of resource requirements for primary path.
                Each dict: {"place_id": str, "weight": int}
                If None, pattern creates its own resource place with 0 tokens.
            primary_delay: Delay for primary transition (default: 0, immediate)
            alternative_delay: Delay for alternative transition (default: 0, immediate)
            primary_name: Name suffix for success output (default: "Success")
            alternative_name: Name suffix for fallback output (default: "Fallback")

        Returns:
            PatternResult with:
            - interface.input_place_id: Input place
            - interface.output_place_id: Primary/Success output
            - place_ids[0]: Input
            - place_ids[1]: Success output
            - place_ids[2]: Fallback output
            - place_ids[3]: Resource place (if created internally)
        """
        place_ids = []
        transition_ids = []

        # 1. Input place (items/sections waiting for decision)
        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        # 2. Primary transition (high priority, requires resources)
        t_primary = net.add_transition(
            name=f"{instance_name}_Primary",
            mean_delay=primary_delay,
            distribution=DistributionType.DET,
            priority=2,  # Higher priority
            x=x + 100,
            y=y - 50,
        )
        transition_ids.append(t_primary.id)

        # 3. Alternative transition (low priority, fallback)
        t_alternative = net.add_transition(
            name=f"{instance_name}_Alternative",
            mean_delay=alternative_delay,
            distribution=DistributionType.DET,
            priority=1,  # Lower priority (minimum is 1)
            x=x + 100,
            y=y + 50,
        )
        transition_ids.append(t_alternative.id)

        # 4. Success output place
        p_success = net.add_place(
            name=f"{instance_name}_{primary_name}",
            tokens=0,
            x=x + 200,
            y=y - 50,
        )
        place_ids.append(p_success.id)

        # 5. Fallback output place
        p_fallback = net.add_place(
            name=f"{instance_name}_{alternative_name}",
            tokens=0,
            x=x + 200,
            y=y + 50,
        )
        place_ids.append(p_fallback.id)

        # --- Arcs ---

        # Input -> both transitions (conflict/choice)
        net.add_arc(source_id=p_input.id, target_id=t_primary.id)
        net.add_arc(source_id=p_input.id, target_id=t_alternative.id)

        # Primary -> Success
        net.add_arc(source_id=t_primary.id, target_id=p_success.id)

        # Alternative -> Fallback
        net.add_arc(source_id=t_alternative.id, target_id=p_fallback.id)

        # Connect resource requirements to Primary transition
        if resource_place_ids:
            for req in resource_place_ids:
                place_id = req.get("place_id")
                weight = req.get("weight", 1)
                if place_id:
                    net.add_arc(source_id=place_id, target_id=t_primary.id, weight=weight)
        else:
            # Create internal resource place (starts empty = alternative always fires)
            p_resource = net.add_place(
                name=f"{instance_name}_Resource",
                tokens=0,
                x=x + 50,
                y=y - 100,
            )
            place_ids.append(p_resource.id)
            net.add_arc(source_id=p_resource.id, target_id=t_primary.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_success.id,  # Primary output as default
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )
