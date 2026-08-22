"""Duplicate pattern - broadcast one token into N independent copies."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class DuplicatePattern(BasePattern):
    """
    Duplicate (Split / Broadcast) pattern.

    One arriving token is copied into N independent tokens flowing into
    N separate output places. The inverse of Merge.

    Structure:
                            /--> [P: Out_A]
        [P: Input] -> [T: Split] --> [P: Out_B]
                            \\--> [P: Out_C]

    Use cases:
    - One purchase order triggers parallel processing in warehouse, accounting
      and logistics simultaneously
    - One lab sample sent to multiple independent test stations
    - One event broadcast to N subscriber queues
    """

    @property
    def name(self) -> str:
        return "Duplicate"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        outputs: list[str] | None = None,
    ) -> PatternResult:
        """
        Apply the Duplicate pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "OrderBroadcast")
            x, y: Base coordinates
            outputs: Names for output branches (default: ["Copy_A", "Copy_B"]).
                     Each name yields a place "{instance_name}_{name}".

        Returns:
            PatternResult with:
              - interface.input_place_id: single input place
              - interface.output_place_id: first output place (for sequential chaining)
              - metadata["output_place_ids"]: dict name -> place_id for every output
        """
        if outputs is None:
            outputs = ["Copy_A", "Copy_B"]

        place_ids: list[str] = []
        transition_ids: list[str] = []
        output_place_ids: dict[str, str] = {}

        # Single input place
        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        # Single split transition — consumes 1 input, produces 1 token per output arc
        t_split = net.add_transition(
            name=f"{instance_name}_Split",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_split.id)
        net.add_arc(source_id=p_input.id, target_id=t_split.id)

        spacing_y = 100
        start_y = y - ((len(outputs) - 1) * spacing_y) / 2
        first_output_id: str | None = None

        for i, out_name in enumerate(outputs):
            cur_y = start_y + i * spacing_y

            p_out = net.add_place(
                name=f"{instance_name}_{out_name}",
                tokens=0,
                x=x + 200,
                y=cur_y,
            )
            place_ids.append(p_out.id)
            output_place_ids[out_name] = p_out.id

            if first_output_id is None:
                first_output_id = p_out.id

            net.add_arc(source_id=t_split.id, target_id=p_out.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=first_output_id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "output_place_ids": output_place_ids,
            },
        )
