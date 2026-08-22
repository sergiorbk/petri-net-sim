"""WIP Controller pattern — Kanban / CONWIP entry gate."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class WipControllerPattern(BasePattern):
    """WIP (Work In Progress) limiter — Kanban / CONWIP entry gate.

    Limits the number of entities in a controlled section to at most `wip_limit`
    simultaneously. When the limit is reached, entry is blocked (not rejected) until
    an entity exits the section and returns a WIP slot.

    Structure:
        [Input] + [WIPSlots(K)] --[Enter DET=0]--> [Output]

    After wiring the controlled section, call connect_wip_return to close the loop:
        each transition T that produces tokens into the section's exit place
        gets an extra output arc T -> [WIPSlots]. The entity is NOT consumed —
        it continues to flow through the exit place to its downstream consumer
        (terminator, next stage, etc.) while a WIP slot is recycled.

    Use cases:
    - CONWIP production lines: at most K pallets in the system at once
    - Kanban pull control: K kanban cards gate work entry
    - Pipeline stages: limit concurrent requests to K
    - Thread pool / worker pool modelling
    """

    tool_cursor_width = 300.0
    tool_non_time_params = frozenset({"wip_limit"})

    @property
    def name(self) -> str:
        return "WIPController"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        wip_limit: int = 5,
    ) -> PatternResult:
        """Apply the WIPController pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "KanbanGate", "ConwipLimit")
            x, y: Base coordinates
            wip_limit: Maximum concurrent entities in the controlled section (>= 1)

        Returns:
            PatternResult with:
              - interface.input_place_id: Input (entities arrive here, block when WIP full)
              - interface.output_place_id: Output (entities pass through when slot available)
              - metadata["wip_place_id"]: WIPSlots place — wire to connect_wip_return
        """
        if wip_limit < 1:
            raise ValueError(f"WIPController wip_limit must be >= 1, got {wip_limit}")

        place_ids: list[str] = []
        transition_ids: list[str] = []

        p_wip = net.add_place(
            name=f"{instance_name}_WIPSlots",
            tokens=wip_limit,
            x=x + 100,
            y=y - 80,
        )
        place_ids.append(p_wip.id)

        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        t_enter = net.add_transition(
            name=f"{instance_name}_Enter",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_enter.id)

        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_output.id)

        net.add_arc(source_id=p_input.id, target_id=t_enter.id)
        net.add_arc(source_id=p_wip.id, target_id=t_enter.id)
        net.add_arc(source_id=t_enter.id, target_id=p_output.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={"wip_place_id": p_wip.id},
        )
