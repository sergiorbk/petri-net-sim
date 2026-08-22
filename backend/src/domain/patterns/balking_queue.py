"""BalkingQueue pattern - entity observes queue and refuses to join if too long."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class BalkingQueuePattern(BasePattern):
    """
    Balking Queue pattern.

    An entity arrives, observes the queue length, and either joins (if
    length < capacity) or balks — leaves immediately. Unlike BoundedQueue
    (hard physical limit), balking is a behavioral decision.

    Integrates both queueing and multi-channel service in a single pattern
    for modeling convenience.

    Structure:
        Input + Capacity → [JoinQueue p=2] → Queue + (consume Capacity)
        Input             → [Balk p=1]     → Balked

        Queue + Free → [Start p=1] → Processing
        Processing   → [Finish]    → Done + Free (+ recycle Capacity)

    Priority rules:
    - JoinQueue (prio=2) fires when capacity > 0 (queue not "too long")
    - Balk (prio=1) fires only when capacity = 0 (JoinQueue blocked)
    - Capacity is recycled when Finish fires (served item frees a slot)

    Difference from BoundedQueue:
    - BoundedQueue: standalone queue module, consumer wired separately
    - BalkingQueue: integrated queue + server, self-contained M/M/c/K

    Use cases:
    - Customers see >5 people and leave a store
    - HTTP clients drop requests when buffer is "too full"
    - Callers hear "estimated wait 20 min" and hang up
    """

    tool_cursor_width = 600.0

    @property
    def name(self) -> str:
        return "BalkingQueue"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        capacity: int = 10,
        service_time: float = 60.0,
        service_distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        channels: int = 1,
    ) -> PatternResult:
        """
        Apply the BalkingQueue pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "ShopQueue")
            x, y: Base coordinates
            capacity: Max queue depth before balking (soft limit)
            service_time: Mean service time per customer
            service_distribution: Distribution for service time
            standard_deviation: Std dev for NORM/UNIF
            channels: Number of parallel service channels

        Returns:
            PatternResult with:
              - interface.input_place_id: where arrivals enter
              - interface.output_place_id: served entities exit
              - metadata["balked_place_id"]: where balking entities go
              - metadata["queue_place_id"]: the queue place
              - metadata["capacity_place_id"]: capacity token pool
              - metadata["consume_transition_ids"]: [Start] for wiring
        """
        if capacity < 1:
            raise ValueError(f"BalkingQueue capacity must be >= 1, got {capacity}")

        place_ids: list[str] = []
        transition_ids: list[str] = []

        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x, y=y,
        )
        place_ids.append(p_input.id)

        p_capacity = net.add_place(
            name=f"{instance_name}_Capacity",
            tokens=capacity,
            x=x + 100, y=y - 100,
        )
        place_ids.append(p_capacity.id)

        p_queue = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x + 200, y=y,
        )
        place_ids.append(p_queue.id)

        p_balked = net.add_place(
            name=f"{instance_name}_Balked",
            tokens=0,
            tag="balked",
            x=x + 100, y=y + 120,
        )
        place_ids.append(p_balked.id)

        p_free = net.add_place(
            name=f"{instance_name}_Free",
            tokens=channels,
            x=x + 300, y=y - 100,
        )
        place_ids.append(p_free.id)

        p_processing = net.add_place(
            name=f"{instance_name}_Processing",
            tokens=0,
            x=x + 400, y=y,
        )
        place_ids.append(p_processing.id)

        p_done = net.add_place(
            name=f"{instance_name}_Done",
            tokens=0,
            x=x + 600, y=y,
        )
        place_ids.append(p_done.id)

        # JoinQueue (DET, prio=2): Input + Capacity → Queue
        t_join = net.add_transition(
            name=f"{instance_name}_JoinQueue",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=2,
            x=x + 100, y=y,
        )
        transition_ids.append(t_join.id)

        # Balk (DET, prio=1): Input → Balked (fires when JoinQueue blocked)
        t_balk = net.add_transition(
            name=f"{instance_name}_Balk",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=1,
            x=x + 100, y=y + 60,
        )
        transition_ids.append(t_balk.id)

        # Start (DET, prio=1): Queue + Free → Processing
        t_start = net.add_transition(
            name=f"{instance_name}_Start",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 300, y=y,
        )
        transition_ids.append(t_start.id)

        # Finish: Processing → Done + Free + Capacity recycled
        t_finish = net.add_transition(
            name=f"{instance_name}_Finish",
            mean_delay=service_time,
            distribution=service_distribution,
            standard_deviation=standard_deviation,
            x=x + 500, y=y,
        )
        transition_ids.append(t_finish.id)

        # --- Arcs ---

        # Join path: Input + Capacity → Queue
        net.add_arc(source_id=p_input.id, target_id=t_join.id)
        net.add_arc(source_id=p_capacity.id, target_id=t_join.id)
        net.add_arc(source_id=t_join.id, target_id=p_queue.id)

        # Balk path: Input → Balked
        net.add_arc(source_id=p_input.id, target_id=t_balk.id)
        net.add_arc(source_id=t_balk.id, target_id=p_balked.id)

        # Service path: Queue + Free → Processing → Done + Free + Capacity
        net.add_arc(source_id=p_queue.id, target_id=t_start.id)
        net.add_arc(source_id=p_free.id, target_id=t_start.id)
        net.add_arc(source_id=t_start.id, target_id=p_processing.id)

        net.add_arc(source_id=p_processing.id, target_id=t_finish.id)
        net.add_arc(source_id=t_finish.id, target_id=p_done.id)
        net.add_arc(source_id=t_finish.id, target_id=p_free.id)
        net.add_arc(source_id=t_finish.id, target_id=p_capacity.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_done.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "balked_place_id": p_balked.id,
                "queue_place_id": p_queue.id,
                "capacity_place_id": p_capacity.id,
                "consume_transition_ids": [t_start.id],
            },
        )
