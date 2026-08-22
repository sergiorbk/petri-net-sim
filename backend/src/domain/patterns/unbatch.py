"""Unbatch pattern - expand one batch token into N individual tokens."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class UnbatchPattern(BasePattern):
    """
    Unbatch (Split / Unpack) pattern.

    One incoming token (representing a batch or container) is expanded into
    `batch_size` individual tokens. The inverse of Batch.

    Structure:
        [P: Input] -(weight=1)-> [T: Split] -(weight=N)-> [P: Output]

    Use cases:
    - One received pallet token expanded into 48 individual box tokens
    - One batch job record split into individual work orders
    - One container unloaded into individual items for independent processing
    """

    @property
    def name(self) -> str:
        return "Unbatch"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        batch_size: int = 5,
    ) -> PatternResult:
        """
        Apply the Unbatch pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "PalletUnpack")
            x, y: Base coordinates
            batch_size: Number of individual tokens to produce per input token.
                        Must be >= 2.

        Returns:
            PatternResult with:
              - interface.input_place_id: where one batch token arrives
              - interface.output_place_id: where batch_size individual tokens appear
              - metadata["batch_size"]: the configured expansion factor
        """
        if batch_size < 2:
            raise ValueError(f"Unbatch batch_size must be >= 2, got {batch_size}")

        place_ids: list[str] = []
        transition_ids: list[str] = []

        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        # Consumes 1 batch token, produces batch_size individual tokens
        t_split = net.add_transition(
            name=f"{instance_name}_Split",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_split.id)

        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_output.id)

        net.add_arc(source_id=p_input.id, target_id=t_split.id, weight=1)
        net.add_arc(source_id=t_split.id, target_id=p_output.id, weight=batch_size)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "batch_size": batch_size,
                "split_transition_id": t_split.id,
            },
        )
