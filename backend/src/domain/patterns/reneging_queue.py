"""Reneging Queue pattern - queue where customers abandon after timeout."""

from src.domain import ArcType, DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class RenegingQueuePattern(BasePattern):
    """
    Reneging Queue (M/M/c+G) pattern.

    Models a multi-channel server with customer abandonment: if service has not
    started within a random timeout, the customer leaves (reneges) to Abandoned.

    Structure:
        [Queue] + [Free(c)] --[Start prio=2]--> [Processing]
        [Queue]              --[Renege prio=1, EXP(timeout)]--> [Abandoned]
        [Processing]         --[Finish]--> [Done] + [Free recycled]

    Priority rules:
    - Start (prio=2) fires first when a channel is free → customer served.
    - Renege (prio=1) fires only when ALL channels are busy (Start not enabled).

    Use cases:
    - Call centre: customers hang up after waiting too long
    - Hospital ER: patients leave if not seen within timeout
    - HTTP request timeout; manufacturing WIP expiry
    """

    tool_cursor_width = 500.0

    @property
    def name(self) -> str:
        return "RenegingQueue"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        timeout: float = 300.0,
        service_time: float = 60.0,
        service_distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        channels: int = 1,
    ) -> PatternResult:
        """
        Apply the RenegingQueue pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "CallQueue", "ERQueue")
            x, y: Base coordinates
            timeout: Mean time before abandonment (EXP distribution)
            service_time: Mean service time per customer
            service_distribution: Distribution for service time (default: EXP)
            standard_deviation: Std dev for NORM/UNIF service distributions
            channels: Number of parallel servers (default: 1)

        Returns:
            PatternResult with:
              - interface.input_place_id: Queue (customers arrive here)
              - interface.output_place_id: Done (served customers)
              - metadata["abandoned_place_id"]: reneged customers (tagged "reneged")
              - metadata["consume_transition_ids"]: [Start] for connect_bounded_consumer
        """
        place_ids: list[str] = []
        transition_ids: list[str] = []

        p_queue = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_queue.id)

        p_free = net.add_place(
            name=f"{instance_name}_Free",
            tokens=channels,
            x=x + 100,
            y=y - 80,
        )
        place_ids.append(p_free.id)

        p_processing = net.add_place(
            name=f"{instance_name}_Processing",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_processing.id)

        p_done = net.add_place(
            name=f"{instance_name}_Done",
            tokens=0,
            x=x + 400,
            y=y,
        )
        place_ids.append(p_done.id)

        p_abandoned = net.add_place(
            name=f"{instance_name}_Abandoned",
            tokens=0,
            tag="reneged",
            x=x + 100,
            y=y + 120,
        )
        place_ids.append(p_abandoned.id)

        # Start (DET, prio=2): Queue + Free → Processing
        t_start = net.add_transition(
            name=f"{instance_name}_Start",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=2,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_start.id)

        # Finish (service_distribution): Processing → Done + Free recycled
        t_finish = net.add_transition(
            name=f"{instance_name}_Finish",
            mean_delay=service_time,
            distribution=service_distribution,
            standard_deviation=standard_deviation,
            x=x + 300,
            y=y,
        )
        transition_ids.append(t_finish.id)

        # Renege (EXP, prio=1): Queue → Abandoned
        t_renege = net.add_transition(
            name=f"{instance_name}_Renege",
            mean_delay=timeout,
            distribution=DistributionType.EXP,
            priority=1,
            x=x + 100,
            y=y + 60,
        )
        transition_ids.append(t_renege.id)

        # Start path
        net.add_arc(source_id=p_queue.id, target_id=t_start.id)
        net.add_arc(source_id=p_free.id, target_id=t_start.id)
        net.add_arc(source_id=t_start.id, target_id=p_processing.id)

        # Finish path
        net.add_arc(source_id=p_processing.id, target_id=t_finish.id)
        net.add_arc(source_id=t_finish.id, target_id=p_done.id)
        net.add_arc(source_id=t_finish.id, target_id=p_free.id)

        # Renege path
        net.add_arc(source_id=p_queue.id, target_id=t_renege.id)
        net.add_arc(source_id=t_renege.id, target_id=p_abandoned.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_queue.id,
                output_place_id=p_done.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "abandoned_place_id": p_abandoned.id,
                "consume_transition_ids": [t_start.id],
            },
        )
