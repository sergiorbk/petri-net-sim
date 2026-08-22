"""Transport Agent pattern - cyclic resource for moving items between locations."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class TransportAgentPattern(BasePattern):
    """
    Transport Agent with cyclic grab-move-release-return behavior.

    Models any resource that:
    1. Picks up an item from source location
    2. Moves to destination with the item
    3. Releases the item at destination
    4. Returns empty to source (ready for next item)

    Structure:
        [P: Free] (initial=1)
            |
            v
    [P: Queue] --> [T: Grab] --> [P: Grabbed] --> [T: Move] --> [P: Moved]
                  (grab_time)                    (move_time)       |
                                                                   v
                                                          [T: Release] --> [P: Output]
                                                         (release_time)     |
                                                                           v
                                                                    [P: Released]
                                                                           |
                                                                           v
                                                                    [T: Return] --> [P: Free]
                                                                   (return_time)

    Use cases:
    - "Robot picks parts from arrival, moves to machine, releases, returns"
    - "Forklift transports pallets between stations"
    - "Courier delivers packages and returns for next one"
    - "Crane moves containers from ship to storage"
    - "AGV (Automated Guided Vehicle) transports items"

    Key semantics:
    - Agent is a LIMITED RESOURCE (only 1 token in Free place)
    - Grab requires: item in Queue AND agent in Free
    - After Release, agent must Return before handling next item
    - Return time models empty/idle movement back to source
    """

    tool_cursor_width = 600.0

    @property
    def name(self) -> str:
        return "TransportAgent"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        grab_time: float = 8.0,
        grab_deviation: float = 1.0,
        grab_distribution: DistributionType = DistributionType.UNIF,
        move_time: float = 6.0,
        move_distribution: DistributionType = DistributionType.DET,
        release_time: float = 8.0,
        release_deviation: float = 1.0,
        release_distribution: DistributionType = DistributionType.UNIF,
        return_time: float | None = None,
        return_distribution: DistributionType = DistributionType.DET,
    ) -> PatternResult:
        """
        Apply the TransportAgent pattern.

        Args:
            net: Target PetriNet
            instance_name: Name for this agent (e.g., "Robot1", "Forklift", "AGV")
            x, y: Coordinates
            grab_time: Mean time to grab/pick item (default: 8.0)
            grab_deviation: Standard deviation for grab (default: 1.0)
            grab_distribution: Distribution for grab time (default: UNIF)
            move_time: Time to move with item (default: 6.0)
            move_distribution: Distribution for move (default: DET)
            release_time: Mean time to release/place item (default: 8.0)
            release_deviation: Standard deviation for release (default: 1.0)
            release_distribution: Distribution for release time (default: UNIF)
            return_time: Time to return empty (default: same as move_time)
            return_distribution: Distribution for return (default: DET)

        Returns:
            PatternResult
            - interface.input_place_id: Queue place (items waiting for transport)
            - interface.output_place_id: Output place (delivered items)
            - place_ids: [queue, free, grabbed, moved, output, released]
            - transition_ids: [grab, move, release, return]
        """
        if return_time is None:
            return_time = move_time

        place_ids = []
        transition_ids = []

        # 1. Queue place (items waiting for transport)
        p_queue = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_queue.id)

        # 2. Free place (agent available)
        p_free = net.add_place(
            name=f"{instance_name}_Free",
            tokens=1,
            x=x + 50,
            y=y - 100,
        )
        place_ids.append(p_free.id)

        # 3. Grabbed place (item picked up)
        p_grabbed = net.add_place(
            name=f"{instance_name}_Grabbed",
            tokens=0,
            x=x + 150,
            y=y,
        )
        place_ids.append(p_grabbed.id)

        # 4. Moved place (item at destination)
        p_moved = net.add_place(
            name=f"{instance_name}_Moved",
            tokens=0,
            x=x + 300,
            y=y,
        )
        place_ids.append(p_moved.id)

        # 5. Output place (item released/delivered)
        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + 450,
            y=y,
        )
        place_ids.append(p_output.id)

        # 6. Released place (agent finished release, needs to return)
        p_released = net.add_place(
            name=f"{instance_name}_Released",
            tokens=0,
            x=x + 400,
            y=y - 100,
        )
        place_ids.append(p_released.id)

        # --- Transitions ---

        # T1: Grab (pick up item)
        t_grab = net.add_transition(
            name=f"{instance_name}_Grab",
            mean_delay=grab_time,
            standard_deviation=grab_deviation,
            distribution=grab_distribution,
            priority=1,
            x=x + 75,
            y=y,
        )
        transition_ids.append(t_grab.id)

        # T2: Move (transport with item)
        t_move = net.add_transition(
            name=f"{instance_name}_Move",
            mean_delay=move_time,
            distribution=move_distribution,
            priority=1,
            x=x + 225,
            y=y,
        )
        transition_ids.append(t_move.id)

        # T3: Release (place item at destination)
        t_release = net.add_transition(
            name=f"{instance_name}_Release",
            mean_delay=release_time,
            standard_deviation=release_deviation,
            distribution=release_distribution,
            priority=1,
            x=x + 375,
            y=y,
        )
        transition_ids.append(t_release.id)

        # T4: Return (go back empty)
        t_return = net.add_transition(
            name=f"{instance_name}_Return",
            mean_delay=return_time,
            distribution=return_distribution,
            priority=1,
            x=x + 225,
            y=y - 100,
        )
        transition_ids.append(t_return.id)

        # --- Arcs ---

        # Grab: Queue + Free -> Grabbed
        net.add_arc(source_id=p_queue.id, target_id=t_grab.id)
        net.add_arc(source_id=p_free.id, target_id=t_grab.id)
        net.add_arc(source_id=t_grab.id, target_id=p_grabbed.id)

        # Move: Grabbed -> Moved
        net.add_arc(source_id=p_grabbed.id, target_id=t_move.id)
        net.add_arc(source_id=t_move.id, target_id=p_moved.id)

        # Release: Moved -> Output + Released
        net.add_arc(source_id=p_moved.id, target_id=t_release.id)
        net.add_arc(source_id=t_release.id, target_id=p_output.id)
        net.add_arc(source_id=t_release.id, target_id=p_released.id)

        # Return: Released -> Free
        net.add_arc(source_id=p_released.id, target_id=t_return.id)
        net.add_arc(source_id=t_return.id, target_id=p_free.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_queue.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )
