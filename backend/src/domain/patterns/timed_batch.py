"""TimedBatch pattern - release on count OR timeout, whichever comes first."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class TimedBatchPattern(BasePattern):
    """
    Timed Batch pattern.

    Accumulates items until either N items are collected OR a timeout elapses,
    whichever comes first. The batch is then released as a single token.

    Structure:
        Input → [Enqueue] → Buffer
                                │
               ┌────────────────┤
               │                │
          [CountRelease]   [TimerRelease]
          (weight=N, p=2)  (timeout, p=1)
               │                │
               └──→ Output ←────┘
                      │
                      └──→ TimerReady (recycled)

    Priority rules:
    - CountRelease (prio=2, weight=N): fires instantly when N tokens accumulate
    - TimerRelease (prio=1, timeout): fires after timeout consuming 1 token
      from buffer (partial batch). TimerReady place ensures one timer cycle
      per batch window.

    Both transitions produce 1 output token (the batch). CountRelease consumes
    N tokens from buffer; TimerRelease consumes 1 (partial release).

    Use cases:
    - Ship every hour or when 50 units accumulate
    - Database commit every 100 rows or every 5 seconds
    - Bus departs when full (40 seats) or every 15 minutes
    """

    tool_cursor_width = 500.0

    @property
    def name(self) -> str:
        return "TimedBatch"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        batch_size: int = 10,
        timeout: float = 300.0,
        timeout_distribution: DistributionType = DistributionType.DET,
    ) -> PatternResult:
        """
        Apply the TimedBatch pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "ShipBatch", "DBCommit")
            x, y: Base coordinates
            batch_size: Items to collect for count-based release (>= 2)
            timeout: Max wait time before timer-based release (seconds)
            timeout_distribution: Distribution for timeout (default: DET)

        Returns:
            PatternResult with:
              - interface.input_place_id: where items arrive
              - interface.output_place_id: where batch tokens depart
              - metadata["buffer_place_id"]: accumulation place
              - metadata["count_release_id"]: count-based release transition
              - metadata["timer_release_id"]: timer-based release transition
        """
        if batch_size < 2:
            raise ValueError(f"TimedBatch batch_size must be >= 2, got {batch_size}")
        if timeout <= 0:
            raise ValueError(f"TimedBatch timeout must be > 0, got {timeout}")

        place_ids: list[str] = []
        transition_ids: list[str] = []

        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x, y=y,
        )
        place_ids.append(p_input.id)

        t_enqueue = net.add_transition(
            name=f"{instance_name}_Enqueue",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100, y=y,
        )
        transition_ids.append(t_enqueue.id)

        p_buffer = net.add_place(
            name=f"{instance_name}_Buffer",
            tokens=0,
            x=x + 200, y=y,
        )
        place_ids.append(p_buffer.id)

        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + 400, y=y,
        )
        place_ids.append(p_output.id)

        # CountRelease: fires when buffer has N tokens (prio=2)
        t_count = net.add_transition(
            name=f"{instance_name}_CountRelease",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=2,
            x=x + 300, y=y - 60,
        )
        transition_ids.append(t_count.id)

        # TimerReady: enables one timer cycle, recycled after each release
        p_timer_ready = net.add_place(
            name=f"{instance_name}_TimerReady",
            tokens=1,
            x=x + 200, y=y + 80,
        )
        place_ids.append(p_timer_ready.id)

        # TimerRelease: fires after timeout (prio=1, lower than count)
        t_timer = net.add_transition(
            name=f"{instance_name}_TimerRelease",
            mean_delay=timeout,
            distribution=timeout_distribution,
            priority=1,
            x=x + 300, y=y + 60,
        )
        transition_ids.append(t_timer.id)

        # --- Arcs ---

        # Enqueue: Input → Buffer
        net.add_arc(source_id=p_input.id, target_id=t_enqueue.id)
        net.add_arc(source_id=t_enqueue.id, target_id=p_buffer.id)

        # CountRelease: Buffer (weight=N) → Output (independent of timer)
        net.add_arc(source_id=p_buffer.id, target_id=t_count.id, weight=batch_size)
        net.add_arc(source_id=t_count.id, target_id=p_output.id)

        # TimerRelease: Buffer (weight=1) + TimerReady → Output + TimerReady
        # TimerReady self-loop restarts the timer after each timeout fire
        net.add_arc(source_id=p_buffer.id, target_id=t_timer.id)
        net.add_arc(source_id=p_timer_ready.id, target_id=t_timer.id)
        net.add_arc(source_id=t_timer.id, target_id=p_output.id)
        net.add_arc(source_id=t_timer.id, target_id=p_timer_ready.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "buffer_place_id": p_buffer.id,
                "count_release_id": t_count.id,
                "timer_release_id": t_timer.id,
                "batch_size": batch_size,
            },
        )
