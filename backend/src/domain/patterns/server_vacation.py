"""Server Vacation (N-policy) pattern - server activates when N jobs accumulate."""

from src.domain import ArcType, DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class ServerVacationPattern(BasePattern):
    """
    Server Vacation / N-Policy pattern.

    Server is idle (on vacation) until the queue accumulates at least N jobs.
    Once the threshold is reached, the server activates and processes all waiting
    jobs one-by-one until the queue empties, then returns to vacation.

    Structure:
        [Vacation] + Queue(≥N) -> [Activate] -> [Active] + Queue(unchanged)
        [Active] --READ-- + [Queue] -> [StartJob (prio=2)] -> [Processing]
        [Processing] -> [FinishJob] -> [Done]
        [Active] -> [Deactivate (prio=1)] -> [Vacation]

    Priority competition (Active vs Queue):
    - StartJob (prio=2) wins over Deactivate (prio=1) when Queue has tokens.
    - Deactivate fires only when Queue is empty (StartJob not enabled).

    The Activate transition uses consume+return arcs (weight=N in and out) to
    atomically test Queue ≥ N without net change to the queue.

    Use cases:
    - Batch processor: activates when N jobs accumulated, drains queue, then sleeps
    - Bus dispatch: departs when N passengers board, returns to stop when empty
    - Furnace loading: fires batch when N parts loaded
    - Network packet scheduler: flush when N packets buffered
    """

    tool_cursor_width = 600.0

    @property
    def name(self) -> str:
        return "ServerVacation"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        threshold: int = 5,
        processing_time: float = 60.0,
        distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        starts_active: bool = False,
    ) -> PatternResult:
        """
        Apply the ServerVacation (N-policy) pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "BatchProc", "BusDispatch")
            x, y: Base coordinates
            threshold: Minimum queue depth to activate server (N ≥ 1).
                       Server activates when Queue ≥ threshold.
            processing_time: Mean time to process one job while active
            distribution: Time distribution for job processing
            standard_deviation: Std dev for NORM/UNIF distributions
            starts_active: If True, server starts active instead of on vacation

        Returns:
            PatternResult with:
              - interface.input_place_id: Queue (jobs arrive here)
              - interface.output_place_id: Done (processed jobs)
              - metadata["active_place_id"]: server-is-working signal place
              - metadata["vacation_place_id"]: server-on-vacation place
        """
        if threshold < 1:
            raise ValueError(f"ServerVacation threshold must be >= 1, got {threshold}")

        place_ids: list[str] = []
        transition_ids: list[str] = []

        p_queue = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_queue.id)

        p_vacation = net.add_place(
            name=f"{instance_name}_Vacation",
            tokens=0 if starts_active else 1,
            x=x + 100,
            y=y + 120,
        )
        place_ids.append(p_vacation.id)

        p_active = net.add_place(
            name=f"{instance_name}_Active",
            tokens=1 if starts_active else 0,
            x=x + 100,
            y=y - 80,
        )
        place_ids.append(p_active.id)

        p_processing = net.add_place(
            name=f"{instance_name}_Processing",
            tokens=0,
            x=x + 300,
            y=y,
        )
        place_ids.append(p_processing.id)

        p_done = net.add_place(
            name=f"{instance_name}_Done",
            tokens=0,
            x=x + 500,
            y=y,
        )
        place_ids.append(p_done.id)

        # Activate (DET, prio=2): Vacation + Queue(≥threshold) → Active + Queue unchanged.
        # Implemented via consume+return arcs of weight=threshold on Queue.
        t_activate = net.add_transition(
            name=f"{instance_name}_Activate",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=2,
            x=x + 50,
            y=y + 60,
        )
        transition_ids.append(t_activate.id)

        # StartJob (DET, prio=2): consumes from Queue, reads Active (READ arc)
        t_start_job = net.add_transition(
            name=f"{instance_name}_StartJob",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=2,
            x=x + 200,
            y=y,
        )
        transition_ids.append(t_start_job.id)

        # FinishJob: Processing → Done
        t_finish_job = net.add_transition(
            name=f"{instance_name}_FinishJob",
            mean_delay=processing_time,
            distribution=distribution,
            standard_deviation=standard_deviation,
            x=x + 400,
            y=y,
        )
        transition_ids.append(t_finish_job.id)

        # Deactivate (DET, prio=1): Active → Vacation (fires when Queue=0)
        t_deactivate = net.add_transition(
            name=f"{instance_name}_Deactivate",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=1,
            x=x + 100,
            y=y + 30,
        )
        transition_ids.append(t_deactivate.id)

        # Activate arcs: consume N from Queue + Vacation, produce N back + Active
        net.add_arc(source_id=p_vacation.id, target_id=t_activate.id)
        net.add_arc(source_id=p_queue.id, target_id=t_activate.id, weight=threshold)
        net.add_arc(source_id=t_activate.id, target_id=p_active.id)
        net.add_arc(source_id=t_activate.id, target_id=p_queue.id, weight=threshold)

        # StartJob arcs: consume Queue, read Active (don't consume)
        net.add_arc(source_id=p_queue.id, target_id=t_start_job.id)
        net.add_arc(source_id=p_active.id, target_id=t_start_job.id, arc_type=ArcType.READ)
        net.add_arc(source_id=t_start_job.id, target_id=p_processing.id)

        # FinishJob arcs
        net.add_arc(source_id=p_processing.id, target_id=t_finish_job.id)
        net.add_arc(source_id=t_finish_job.id, target_id=p_done.id)

        # Deactivate arcs: consume Active, produce Vacation
        net.add_arc(source_id=p_active.id, target_id=t_deactivate.id)
        net.add_arc(source_id=t_deactivate.id, target_id=p_vacation.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_queue.id,
                output_place_id=p_done.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "active_place_id": p_active.id,
                "vacation_place_id": p_vacation.id,
            },
        )
