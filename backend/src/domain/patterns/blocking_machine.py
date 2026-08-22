"""Blocking Machine pattern - machine that halts when downstream buffer is full."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class BlockingMachinePattern(BasePattern):
    """
    Blocking Machine (BAS — Blocking After Service) pattern.

    A machine that cannot release a finished entity until the downstream buffer
    has space. When the output buffer is full, the machine finishes processing
    but holds the entity internally (Holding state) until a slot opens.

    Structure:
        [Input] + [Free(c)] --[Start DET=0]--> [Processing]
        [Processing]         --[Finish]-------> [Holding] + [Free recycled]
        [Holding] + [Capacity] --[Release DET=0]--> [Output]

    The machine blocks when Capacity (downstream slots) is exhausted:
    - The Holding entity cannot Release → occupies a channel (Free slot consumed)
    - No new entity can Start → upstream naturally blocks

    Use `connect_blocking_consumer(blocking_result, downstream_result)` to wire
    the capacity recycling: each time the downstream machine *starts* an entity
    from the output buffer, one Capacity slot is returned.

    Difference from BoundedQueue:
    - BoundedQueue rejects new arrivals when full (producer never blocks)
    - BlockingMachine holds finished entities inside, blocking the channel

    Use cases:
    - Assembly line: station done but conveyor ahead is full → station stalls
    - Printer spooler: printed but output tray full → printer holds job
    - CPU pipeline: executed but next stage stalled → stall propagates upstream
    """

    tool_cursor_width = 600.0

    @property
    def name(self) -> str:
        return "BlockingMachine"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        processing_time: float = 60.0,
        distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        channels: int = 1,
        buffer_capacity: int = 5,
    ) -> PatternResult:
        """
        Apply the BlockingMachine pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "Lathe", "PaintBooth")
            x, y: Base coordinates
            processing_time: Mean processing time
            distribution: Distribution for processing time (default: EXP)
            standard_deviation: Std dev for NORM/UNIF distributions
            channels: Parallel machine channels (default: 1)
            buffer_capacity: Downstream buffer capacity — the number of slots
                available before the machine starts blocking (default: 5)

        Returns:
            PatternResult with:
              - interface.input_place_id: Input (where entities enter)
              - interface.output_place_id: Output (downstream buffer input)
              - metadata["holding_place_id"]: entities waiting for downstream slot
              - metadata["capacity_place_id"]: downstream capacity pool — wire to
                downstream consumer via connect_blocking_consumer
              - metadata["consume_transition_ids"]: [Start] for wiring helpers
        """
        place_ids: list[str] = []
        transition_ids: list[str] = []

        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        p_free = net.add_place(
            name=f"{instance_name}_Free",
            tokens=channels,
            x=x + 100,
            y=y - 80,
        )
        place_ids.append(p_free.id)

        p_processing = net.add_place(
            name=f"{instance_name}_Processing",
            tokens=0,
            x=x + 250,
            y=y,
        )
        place_ids.append(p_processing.id)

        p_holding = net.add_place(
            name=f"{instance_name}_Holding",
            tokens=0,
            x=x + 400,
            y=y,
        )
        place_ids.append(p_holding.id)

        p_capacity = net.add_place(
            name=f"{instance_name}_Capacity",
            tokens=buffer_capacity,
            x=x + 450,
            y=y - 80,
        )
        place_ids.append(p_capacity.id)

        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + 600,
            y=y,
        )
        place_ids.append(p_output.id)

        # Start (DET=0): Input + Free → Processing
        t_start = net.add_transition(
            name=f"{instance_name}_Start",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 150,
            y=y,
        )
        transition_ids.append(t_start.id)

        # Finish: Processing → Holding + Free (channel released immediately)
        t_finish = net.add_transition(
            name=f"{instance_name}_Finish",
            mean_delay=processing_time,
            distribution=distribution,
            standard_deviation=standard_deviation,
            x=x + 320,
            y=y,
        )
        transition_ids.append(t_finish.id)

        # Release (DET=0): Holding + Capacity → Output
        # Fires only when downstream has space (Capacity > 0)
        t_release = net.add_transition(
            name=f"{instance_name}_Release",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 510,
            y=y,
        )
        transition_ids.append(t_release.id)

        # Start path: Input + Free → Processing
        net.add_arc(source_id=p_input.id, target_id=t_start.id)
        net.add_arc(source_id=p_free.id, target_id=t_start.id)
        net.add_arc(source_id=t_start.id, target_id=p_processing.id)

        # Finish path: Processing → Holding + Free
        net.add_arc(source_id=p_processing.id, target_id=t_finish.id)
        net.add_arc(source_id=t_finish.id, target_id=p_holding.id)
        net.add_arc(source_id=t_finish.id, target_id=p_free.id)

        # Release path: Holding + Capacity → Output
        net.add_arc(source_id=p_holding.id, target_id=t_release.id)
        net.add_arc(source_id=p_capacity.id, target_id=t_release.id)
        net.add_arc(source_id=t_release.id, target_id=p_output.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "holding_place_id": p_holding.id,
                "capacity_place_id": p_capacity.id,
                "consume_transition_ids": [t_start.id],
            },
        )
