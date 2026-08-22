"""FeedbackLoop pattern - reprocessing/rework cycle for defective items."""

from src.domain import DistributionType, PetriNet
from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class FeedbackLoopPattern(BasePattern):
    """
    Feedback Loop (Rework/Reprocessing) pattern.

    Creates a cycle where items can be sent back for reprocessing.
    Typically used after quality check to rework defective items.

    Structure:
        [P: Input] -> [T: Process] -> [P: Processing] -> [T: Done] -> [P: Output]
                           ^                                  |
                           |                                  v
                           +-------- [T: Rework] <----- [P: ToRework]

    Use cases:
    - "Defective items are sent back for repair"
    - "Failed tests can be retried"
    - "Remanufacturing loop"
    """

    tool_cursor_width = 500.0

    @property
    def name(self) -> str:
        return "FeedbackLoop"

    def apply(
            self,
            net: PetriNet,
            instance_name: str,
            x: float,
            y: float,
            processing_time: float = 1.0,
            rework_time: float = 2.0,
            distribution: DistributionType = DistributionType.EXP,
            max_reworks: int | None = None,
    ) -> PatternResult:
        """
        Apply the FeedbackLoop pattern.

        Args:
            net: Target PetriNet
            instance_name: Name (e.g., "Rework", "Repair", "Retry")
            x, y: Coordinates
            processing_time: Time for main processing. Default: 1.0.
            rework_time: Time for rework. Default: 2.0 (usually longer).
            distribution: Time distribution. Default: EXP.
            max_reworks: Conceptual limit on reworks (for documentation).

        Returns:
            PatternResult.
            - input_place_id: Where items enter.
            - output_place_id: Where successfully processed items go.
            - place_ids includes ToRework place for connecting from QualityCheck.
        """
        place_ids = []
        transition_ids = []

        # 1. Input place (also receives rework items)
        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        # 2. Process transition
        t_process = net.add_transition(
            name=f"{instance_name}_Process",
            mean_delay=processing_time,
            distribution=distribution,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_process.id)

        # 3. Processing place
        p_processing = net.add_place(
            name=f"{instance_name}_Working",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_processing.id)

        # 4. Done transition (immediate)
        t_done = net.add_transition(
            name=f"{instance_name}_Done",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 300,
            y=y,
        )
        transition_ids.append(t_done.id)

        # 5. Output place
        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + 400,
            y=y,
        )
        place_ids.append(p_output.id)

        # 6. ToRework place (items waiting for rework)
        p_to_rework = net.add_place(
            name=f"{instance_name}_ToRework",
            tokens=0,
            x=x + 200,
            y=y + 100,
        )
        place_ids.append(p_to_rework.id)

        # 7. Rework transition (sends back to input)
        t_rework = net.add_transition(
            name=f"{instance_name}_Rework",
            mean_delay=rework_time,
            distribution=distribution,
            x=x + 100,
            y=y + 100,
        )
        transition_ids.append(t_rework.id)

        # --- Arcs ---

        # Main flow: Input -> Process -> Processing -> Done -> Output
        net.add_arc(source_id=p_input.id, target_id=t_process.id)
        net.add_arc(source_id=t_process.id, target_id=p_processing.id)
        net.add_arc(source_id=p_processing.id, target_id=t_done.id)
        net.add_arc(source_id=t_done.id, target_id=p_output.id)

        # Rework loop: ToRework -> Rework -> Input
        net.add_arc(source_id=p_to_rework.id, target_id=t_rework.id)
        net.add_arc(source_id=t_rework.id, target_id=p_input.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )
