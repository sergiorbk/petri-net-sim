"""Machine pattern - multi-channel processing device."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class MachinePattern(BasePattern):
    """
    Multi-channel Machine (Server) pattern for queueing systems.

    Represents a processing station with multiple parallel channels.
    Each channel can process one item at a time.

    Structure:
        [P: Resource] ----+
              |           |
              v           |
        [T: Start] -------+
              |
              v
        [P: Processing]
              |
              v
        [T: End] -------> [P: Output]
              |
              +---------> [P: Resource] (return)

    - Resource place has N tokens (N = number of channels)
    - Start transition is immediate (deterministic, delay=0)
    - End transition has the processing time delay
    - When End fires, it returns a token to Resource (frees channel)
    """

    tool_cursor_width = 500.0

    @property
    def name(self) -> str:
        return "Machine"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        processing_time: float = 1.0,
        distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        channels: int = 1,
    ) -> PatternResult:
        """
        Add a machine pattern to the net.

        Args:
            net: Target PetriNet
            instance_name: Name for this machine (e.g., "Lathe")
            x, y: Base coordinates
            processing_time: Mean processing time
            distribution: Time distribution type
            standard_deviation: For NORM/UNIF distributions
            channels: Number of parallel processing channels

        Returns:
            PatternResult with input and output place IDs
        """
        place_ids = []
        transition_ids = []

        # 1. Input place (queue/buffer before machine)
        p_input = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        # 2. Resource place (available channels)
        p_resource = net.add_place(
            name=f"{instance_name}_Free",
            tokens=channels,
            x=x + 100,
            y=y - 80,
        )
        place_ids.append(p_resource.id)

        # 3. Start transition (immediate - just grabs item and channel)
        t_start = net.add_transition(
            name=f"{instance_name}_Start",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_start.id)

        # 4. Processing place (item being processed)
        p_processing = net.add_place(
            name=f"{instance_name}_Busy",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_processing.id)

        # 5. End transition (processing time happens here)
        t_end = net.add_transition(
            name=f"{instance_name}_End",
            mean_delay=processing_time,
            distribution=distribution,
            standard_deviation=standard_deviation,
            x=x + 300,
            y=y,
        )
        transition_ids.append(t_end.id)

        # 6. Output place (processed items)
        p_output = net.add_place(
            name=f"{instance_name}_Done",
            tokens=0,
            x=x + 400,
            y=y,
        )
        place_ids.append(p_output.id)

        # --- Arcs ---

        # Input -> Start (take item from queue)
        net.add_arc(source_id=p_input.id, target_id=t_start.id)

        # Resource -> Start (take free channel)
        net.add_arc(source_id=p_resource.id, target_id=t_start.id)

        # Start -> Processing (item enters processing)
        net.add_arc(source_id=t_start.id, target_id=p_processing.id)

        # Processing -> End (item finishes)
        net.add_arc(source_id=p_processing.id, target_id=t_end.id)

        # End -> Output (item leaves)
        net.add_arc(source_id=t_end.id, target_id=p_output.id)

        # End -> Resource (free channel - KEY for queueing!)
        net.add_arc(source_id=t_end.id, target_id=p_resource.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                # Start transition is what consumes from the upstream queue —
                # the BoundedQueue connector wires capacity recycling here.
                "consume_transition_ids": [t_start.id],
            },
        )
