"""Terminator pattern - exits tokens into a throughput counter place."""

from src.domain import DistributionType, PetriNet
from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class TerminatorPattern(BasePattern):
    """
    Terminator (Sink/Exit) pattern.

    Represents the end of a process lifecycle. Tokens flow in, traverse an
    immediate exit transition, and accumulate in a Counter place — its final
    marking IS the number of tokens that completed this exit path.

    Structure:
        [P: FinalBuffer] -> [T: Exit] -> [P: Counter (tag="throughput")]

    Why a Counter place rather than a dangling sink transition:
    - Bipartite invariant: every transition must be wired to places on both
      sides; "transition with no outputs" is not idiomatic Petri net.
    - Observability: counts belong in place markings, not in transition fire
      counts. The simulator surfaces tagged-throughput places as
      TerminatorStatistics so callers get a clean answer to "how many
      completed?" without having to inspect every place by hand.
    """

    tool_cursor_width = 200.0

    @property
    def name(self) -> str:
        return "Terminator"

    def apply(
            self,
            net: PetriNet,
            instance_name: str,
            x: float,
            y: float,
            time_to_leave: float = 0.0,
            distribution: DistributionType = DistributionType.DET,
    ) -> PatternResult:
        """
        Apply the Terminator pattern.

        Args:
            net: Target PetriNet
            instance_name: Name (e.g., "Shipped", "Rejected")
            x, y: Coordinates
            time_to_leave: Time the exit transition holds a token before
                depositing it in the counter (default 0.0).
            distribution: Distribution of exit time.

        Returns:
            PatternResult with input_place_id (where producers connect).
            output_place_id is None — terminator is a dead end. The counter
            place id is exposed via metadata["counter_place_id"].
        """
        place_ids = []
        transition_ids = []

        # 1. Input Place (Waiting to leave)
        p_input = net.add_place(
            name=f"{instance_name}_FinalBuffer",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        # 2. Exit transition — passes tokens from input buffer to counter.
        t_exit = net.add_transition(
            name=f"{instance_name}_Exit",
            mean_delay=time_to_leave,
            distribution=distribution,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_exit.id)

        # 3. Counter place — accumulates exited tokens. Its final marking is
        #    the throughput count for this terminator. Tagged so the
        #    optimizer cannot fuse it away and the simulator collects it
        #    into TerminatorStatistics.
        p_counter = net.add_place(
            name=f"{instance_name}_Counter",
            tokens=0,
            x=x + 200,
            y=y,
            tag="throughput",
        )
        place_ids.append(p_counter.id)

        # Connect: FinalBuffer -> Exit -> Counter
        net.add_arc(source_id=p_input.id, target_id=t_exit.id)
        net.add_arc(source_id=t_exit.id, target_id=p_counter.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=None,  # End of line — counter is internal
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "counter_place_id": p_counter.id,
            },
        )