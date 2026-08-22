"""Merge pattern - OR-join: multiple independent input streams into one output."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class MergePattern(BasePattern):
    """
    Merge (OR-join / Funnel) pattern.

    Combines N independent input streams into a single output place.
    Unlike Assembly (AND-join), this fires as soon as ANY input has a token —
    no synchronization required.

    Structure:
        [P: In_A] -> [T: Route_A] --\\
        [P: In_B] -> [T: Route_B] --+--> [P: Output]
        [P: In_C] -> [T: Route_C] --/

    Use cases:
    - Orders from web, phone and fax merging into one processing queue
    - Parts from three parallel machines going to one inspection station
    - Multiple customer segments joining one service queue
    """

    @property
    def name(self) -> str:
        return "Merge"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        inputs: list[str] | None = None,
    ) -> PatternResult:
        """
        Apply the Merge pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "OrderMerge")
            x, y: Base coordinates
            inputs: Names of input streams (default: ["Stream_A", "Stream_B"]).
                    Each name yields a place "{instance_name}_In_{name}".
                    Wire external producers into those places via connect_patterns.

        Returns:
            PatternResult with:
              - interface.input_place_id: None (multiple inputs; use metadata)
              - interface.output_place_id: shared output place
              - metadata["input_place_ids"]: dict name -> place_id for each stream
        """
        if inputs is None:
            inputs = ["Stream_A", "Stream_B"]

        place_ids: list[str] = []
        transition_ids: list[str] = []
        input_place_ids: dict[str, str] = {}

        # Shared output place (all streams funnel here)
        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_output.id)

        spacing_y = 100
        start_y = y - ((len(inputs) - 1) * spacing_y) / 2

        for i, stream_name in enumerate(inputs):
            cur_y = start_y + i * spacing_y

            p_in = net.add_place(
                name=f"{instance_name}_In_{stream_name}",
                tokens=0,
                x=x,
                y=cur_y,
            )
            place_ids.append(p_in.id)
            input_place_ids[stream_name] = p_in.id

            t_route = net.add_transition(
                name=f"{instance_name}_Route_{stream_name}",
                mean_delay=0.0,
                distribution=DistributionType.DET,
                x=x + 100,
                y=cur_y,
            )
            transition_ids.append(t_route.id)

            net.add_arc(source_id=p_in.id, target_id=t_route.id)
            net.add_arc(source_id=t_route.id, target_id=p_output.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=None,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "input_place_ids": input_place_ids,
            },
        )
