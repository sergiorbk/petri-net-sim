"""Conveyor Workstation pattern - Try-or-Bypass logic for buffer-less systems."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class ConveyorWorkstationPattern(BasePattern):
    """
    Conveyor Workstation with Try-or-Bypass logic.

    Implements "no buffer" constraint: if resource is free, process;
    if busy, bypass to next station via conveyor.

    Structure:
        [Approach] --+--> [T: Process] ----> [Exit]
                     |        ^     |
                     |        |     v
                     |   [Resource] (loop back)
                     |
                     +--> [T: Bypass] ----> [ToNext]

    Conflict resolution (CRITICAL for correct behavior):
    - Process transition has HIGHER PRIORITY (priority=1)
    - Bypass transition has LOWER PRIORITY (priority=0)
    - Process requires: Approach token + Resource token
    - Bypass requires: Only Approach token
    - If Resource has token → Process fires (higher priority wins)
    - If Resource empty → Process blocked → Bypass fires

    This ensures deterministic behavior: process if possible, bypass only if busy.

    Use cases:
    - "No buffer before machine - if busy, skip to next"
    - "Conveyor with workstations along the belt"
    - "5 robots along conveyor, no queue space"
    """

    @property
    def name(self) -> str:
        return "ConveyorWorkstation"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        processing_time: float = 1.0,
        distribution: DistributionType = DistributionType.EXP,
        transport_time: float = 1.0,
        channels: int = 1,
    ) -> PatternResult:
        """
        Apply the ConveyorWorkstation pattern.

        Args:
            net: Target PetriNet
            instance_name: Name (e.g., "Device1", "Robot1")
            x, y: Coordinates
            processing_time: Mean processing time (default: 1.0)
            distribution: Processing time distribution (default: EXP)
            transport_time: Time to bypass to next station (default: 1.0)
            channels: Number of parallel resources (default: 1)

        Returns:
            PatternResult
            - interface.input_place_id: Approach place
            - interface.output_place_id: Exit place (processed items leave system)
            - place_ids[3]: ToNext place (bypass output for chaining)
        """
        place_ids = []
        transition_ids = []

        # 1. Approach place (item arrived at this station)
        p_approach = net.add_place(
            name=f"{instance_name}_Approach",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_approach.id)

        # 2. Resource place (free workstation slots)
        p_resource = net.add_place(
            name=f"Resource_{instance_name}",
            tokens=channels,
            x=x + 100,
            y=y - 80,
        )
        place_ids.append(p_resource.id)

        # 3. Exit place (processed items - leave system)
        p_exit = net.add_place(
            name=f"Exit_{instance_name}",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_exit.id)

        # 4. ToNext place (bypassed items - go to next station)
        p_to_next = net.add_place(
            name=f"{instance_name}_ToNext",
            tokens=0,
            x=x + 200,
            y=y + 100,
        )
        place_ids.append(p_to_next.id)

        # 5. Process transition (requires resource) - HIGHER PRIORITY
        t_process = net.add_transition(
            name=f"Process_{instance_name}",
            mean_delay=processing_time,
            distribution=distribution,
            priority=2,  # Higher priority - fires first if resource available
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_process.id)

        # 6. Bypass transition (no resource needed) - LOWER PRIORITY
        t_bypass = net.add_transition(
            name=f"Bypass_{instance_name}",
            mean_delay=transport_time,
            distribution=DistributionType.DET,
            priority=1,  # Lower priority - fires only when Process is blocked
            x=x + 100,
            y=y + 100,
        )
        transition_ids.append(t_bypass.id)

        # --- Arcs ---

        # Process path: Approach + Resource -> Process -> Exit + Resource
        net.add_arc(source_id=p_approach.id, target_id=t_process.id)
        net.add_arc(source_id=p_resource.id, target_id=t_process.id)
        net.add_arc(source_id=t_process.id, target_id=p_exit.id)
        net.add_arc(source_id=t_process.id, target_id=p_resource.id)

        # Bypass path: Approach -> Bypass -> ToNext
        net.add_arc(source_id=p_approach.id, target_id=t_bypass.id)
        net.add_arc(source_id=t_bypass.id, target_id=p_to_next.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_approach.id,
                output_place_id=p_exit.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )
