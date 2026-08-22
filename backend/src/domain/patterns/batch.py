"""Batch pattern - accumulate N individual tokens and release them as one unit."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class BatchPattern(BasePattern):
    """
    Batch (Accumulator) pattern.

    Collects exactly `batch_size` individual tokens and releases them as a
    single output token. The Release transition requires `batch_size` tokens
    in the buffer place (weighted arc) before it can fire.

    Structure:
        [P: Input] -> [T: Enqueue] -> [P: Buffer (accumulates)]
        [P: Buffer] -(weight=N)-> [T: Release] -> [P: Output]

    Use cases:
    - 12 bottles accumulate then 1 case is sealed and forwarded
    - 20 orders batched before nightly processing run
    - 48 boxes accumulated before a pallet is sent to warehouse
    """

    tool_cursor_width = 500.0

    @property
    def name(self) -> str:
        return "Batch"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        batch_size: int = 5,
    ) -> PatternResult:
        """
        Apply the Batch pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "CasePacker")
            x, y: Base coordinates
            batch_size: Number of individual items to collect before releasing.
                        Must be >= 2.

        Returns:
            PatternResult with:
              - interface.input_place_id: where individual items arrive
              - interface.output_place_id: where one batch token is produced
              - metadata["buffer_place_id"]: the accumulator place
              - metadata["batch_size"]: the configured batch size
        """
        if batch_size < 2:
            raise ValueError(f"Batch batch_size must be >= 2, got {batch_size}")

        place_ids: list[str] = []
        transition_ids: list[str] = []

        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        t_enqueue = net.add_transition(
            name=f"{instance_name}_Enqueue",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_enqueue.id)

        p_buffer = net.add_place(
            name=f"{instance_name}_Buffer",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_buffer.id)

        # Requires batch_size tokens to fire (weighted arc)
        t_release = net.add_transition(
            name=f"{instance_name}_Release",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 300,
            y=y,
        )
        transition_ids.append(t_release.id)

        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + 400,
            y=y,
        )
        place_ids.append(p_output.id)

        net.add_arc(source_id=p_input.id, target_id=t_enqueue.id)
        net.add_arc(source_id=t_enqueue.id, target_id=p_buffer.id)
        net.add_arc(source_id=p_buffer.id, target_id=t_release.id, weight=batch_size)
        net.add_arc(source_id=t_release.id, target_id=p_output.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "buffer_place_id": p_buffer.id,
                "batch_size": batch_size,
                "enqueue_transition_id": t_enqueue.id,
                "release_transition_id": t_release.id,
            },
        )
