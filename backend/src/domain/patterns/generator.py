"""Generator pattern - creates tokens at specified intervals."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class GeneratorPattern(BasePattern):
    """
    Generator (Source) pattern for queueing systems.

    Creates tokens at specified time intervals. This represents
    arrival of customers, parts, requests, etc.

    Structure:
        [P: Ready] -> [T: Generate] -> [P: Output]
            ^_____________|

    The Ready place contains 1 token that enables generation.
    After Generate fires, it returns the token to Ready (loop)
    and also produces a token in Output.

    Supports batch generation (batch_size > 1) where each firing
    produces multiple tokens at once. Useful for:
    - "5 parts arrive every 5 minutes" -> batch_size=5, interval=5
    - "20 items per batch every 20 minutes" -> batch_size=20, interval=20
    """

    @property
    def name(self) -> str:
        return "Generator"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        interval: float = 1.0,
        distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        batch_size: int = 1,
    ) -> PatternResult:
        """
        Add a generator pattern to the net.

        Args:
            net: Target PetriNet
            instance_name: Name for this generator (e.g., "Arrivals")
            x, y: Base coordinates
            interval: Mean time between generations
            distribution: Time distribution type
            standard_deviation: For NORM/UNIF distributions
            batch_size: Number of tokens to produce per firing (default: 1)
                        Use for "N items arrive every X time units"

        Returns:
            PatternResult with output_place_id as interface
        """
        place_ids = []
        transition_ids = []

        # 1. Ready place (enables generation, starts with 1 token)
        p_ready = net.add_place(
            name=f"{instance_name}_Ready",
            tokens=1,
            x=x,
            y=y - 60,
        )
        place_ids.append(p_ready.id)

        # 2. Generate transition (timed)
        t_generate = net.add_transition(
            name=f"{instance_name}_Gen",
            mean_delay=interval,
            distribution=distribution,
            standard_deviation=standard_deviation,
            x=x + 80,
            y=y,
        )
        transition_ids.append(t_generate.id)

        # 3. Output place (where generated tokens go)
        p_output = net.add_place(
            name=f"{instance_name}_Out",
            tokens=0,
            x=x + 180,
            y=y,
        )
        place_ids.append(p_output.id)

        # Arcs: Ready -> Generate -> Output
        #         ^________|
        net.add_arc(source_id=p_ready.id, target_id=t_generate.id)
        net.add_arc(source_id=t_generate.id, target_id=p_ready.id)  # Loop back
        # Output arc with batch_size as weight
        net.add_arc(source_id=t_generate.id, target_id=p_output.id, weight=batch_size)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=None,  # Generator has no input
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )
