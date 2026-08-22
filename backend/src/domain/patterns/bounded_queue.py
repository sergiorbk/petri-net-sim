"""BoundedQueue pattern - capacity-limited FIFO with overflow rejection.

Standard M/M/1/K encoding using complementary capacity place + priority-based
choice between enqueue and reject. The simulation engine resolves contention
by transition priority (higher fires first), so when capacity is exhausted
only the lower-priority Reject transition has its precondition satisfied.
"""

from src.domain import DistributionType, PetriNet
from .registry import register_pattern

from .base import BasePattern, PatternInterface, PatternResult


@register_pattern
class BoundedQueuePattern(BasePattern):
    """
    Capacity-limited queue with overflow rejection.

    Topology:

        input ──> [TryEnqueue p=2] ──> queue (=output, downstream reads here)
          │              ▲
          │              │ (consumes 1 from capacity)
          │       capacity (init=K, refilled by downstream consumer)
          │
          └────> [Reject  p=1] ──> reject_output

    Behavior:
    - When capacity > 0: TryEnqueue is enabled and wins on priority.
      A token moves from input to queue and one capacity slot is consumed.
    - When capacity = 0: TryEnqueue's AND-precondition fails (no capacity
      tokens), so only Reject is enabled — the token moves from input to
      reject_output. Producer is never blocked.

    Recycling capacity slots: downstream consumer must produce a token to
    `capacity_place_id` whenever it consumes from `queue` (= output_place_id).
    Use PetriNetBuilder.connect_bounded_consumer(queue_result, consumer_result)
    to wire this automatically.

    Use cases:
    - M/M/1/K queueing systems (finite waiting room with loss).
    - "5-slot conveyor; arriving parts dropped when full".
    - "Connection pool with rejection".
    """

    tool_cursor_width = 400.0

    @property
    def name(self) -> str:
        return "BoundedQueue"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        capacity: int = 1,
    ) -> PatternResult:
        """
        Apply the BoundedQueue pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "BufferQueue")
            x, y: Base coordinates
            capacity: Maximum number of tokens that can simultaneously
                      reside in the queue (K in M/M/1/K). Must be ≥ 1.

        Returns:
            PatternResult with:
              - interface.input_place_id: where producers drop tokens
              - interface.output_place_id: queue (downstream reads here)
              - metadata["capacity_place_id"]: capacity slots; consumer
                must add one token here per dequeue
              - metadata["reject_output_id"]: where rejected tokens go
              - metadata["enqueue_transition_id"], metadata["reject_transition_id"]
        """
        if capacity < 1:
            raise ValueError(
                f"BoundedQueue capacity must be >= 1, got {capacity}"
            )

        place_ids: list[str] = []
        transition_ids: list[str] = []

        # 1. Input place — producers drop tokens here
        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        # 2. Capacity place — initial tokens = K free slots
        p_capacity = net.add_place(
            name=f"{instance_name}_Capacity",
            tokens=capacity,
            x=x + 100,
            y=y - 100,
        )
        place_ids.append(p_capacity.id)

        # 3. Queue place — current contents of the queue (= output port)
        p_queue = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_queue.id)

        # 4. Reject output place — overflow tokens land here
        p_reject = net.add_place(
            name=f"{instance_name}_Overflow",
            tokens=0,
            x=x + 200,
            y=y + 100,
        )
        place_ids.append(p_reject.id)

        # 5. TryEnqueue transition (priority=2). Fires only when both
        #    Input and Capacity have tokens. Consumes 1 from each, produces
        #    1 to Queue.
        t_enqueue = net.add_transition(
            name=f"{instance_name}_TryEnqueue",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=2,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_enqueue.id)

        # 6. Reject transition (priority=1). Fires only when Capacity is
        #    empty (then TryEnqueue's precondition fails and this one wins
        #    by being the only enabled choice). Consumes 1 from Input,
        #    produces 1 to Reject.
        t_reject = net.add_transition(
            name=f"{instance_name}_Reject",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=1,
            x=x + 100,
            y=y + 100,
        )
        transition_ids.append(t_reject.id)

        # --- Arcs ---

        # Input feeds both transitions (priority resolves the choice)
        net.add_arc(source_id=p_input.id, target_id=t_enqueue.id)
        net.add_arc(source_id=p_input.id, target_id=t_reject.id)

        # Capacity gates TryEnqueue (consumed on success)
        net.add_arc(source_id=p_capacity.id, target_id=t_enqueue.id)

        # TryEnqueue produces to Queue
        net.add_arc(source_id=t_enqueue.id, target_id=p_queue.id)

        # Reject produces to Reject output
        net.add_arc(source_id=t_reject.id, target_id=p_reject.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_queue.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "capacity_place_id": p_capacity.id,
                "reject_output_id": p_reject.id,
                "enqueue_transition_id": t_enqueue.id,
                "reject_transition_id": t_reject.id,
                "capacity": capacity,
            },
        )
