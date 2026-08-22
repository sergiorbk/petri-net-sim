"""Buffer pattern - simple storage place between stations."""

from src.domain import PetriNet
from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class BufferPattern(BasePattern):
    """
    Buffer (Queue/Storage) pattern.

    A simple place for accumulating tokens between processing stations.
    Unlike Machine, it has no processing time - just stores items.

    Structure:
        [P: Buffer] (with optional capacity limit)

    Use cases:
    - Queue before a machine
    - Intermediate storage between stations
    - Accumulator for synchronization
    """

    tool_cursor_width = 100.0

    @property
    def name(self) -> str:
        return "Buffer"

    def apply(
            self,
            net: PetriNet,
            instance_name: str,
            x: float,
            y: float,
            initial_tokens: int = 0,
            capacity: int | None = None,
    ) -> PatternResult:
        """
        Apply the Buffer pattern.

        Args:
            net: Target PetriNet
            instance_name: Name (e.g., "Queue", "Storage", "Accumulator")
            x, y: Coordinates
            initial_tokens: Initial number of tokens. Default: 0.
            capacity: Optional capacity hint (for documentation, not enforced).

        Returns:
            PatternResult.
            input_place_id and output_place_id point to the same place.
        """
        place_ids = []
        transition_ids = []

        # Single buffer place
        p_buffer = net.add_place(
            name=f"{instance_name}_Buffer",
            tokens=initial_tokens,
            x=x,
            y=y,
        )
        place_ids.append(p_buffer.id)

        # Buffer is both input and output (items enter and leave from same place)
        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_buffer.id,
                output_place_id=p_buffer.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )
