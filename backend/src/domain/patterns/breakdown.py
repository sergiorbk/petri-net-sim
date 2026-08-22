"""Breakdown (Failure/Repair) pattern - machine with random failures and recovery."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class BreakdownPattern(BasePattern):
    """
    Breakdown / Failure pattern.

    A processing station that can randomly fail and requires repair before
    resuming. The failure cycle competes with processing for the Operational
    token, so the machine can only break while idle (a common simplified model).

    Structure:
        [Queue] + [Operational(N)] -> [Start (immediate)] -> [Processing]
        [Processing] -> [Finish (service_dist)] -> [Done] + [Operational recycled]
        [Operational] -> [Break (EXP, MTBF)] -> [Failed]
        [Failed] -> [Repair (EXP, MTTR)] -> [Operational]

    Use cases:
    - CNC machine breaks on average every 4 hours, repair takes 30 min
    - Web server crashes every ~200 hours, restart takes 2 min
    - Conveyor motor fails every 8h, maintenance takes 45 min
    """

    tool_cursor_width = 500.0

    @property
    def name(self) -> str:
        return "Breakdown"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        channels: int = 1,
        mean_time_between_failures: float = 3600.0,
        mean_time_to_repair: float = 600.0,
        service_time: float = 60.0,
        service_dist: DistributionType = DistributionType.EXP,
    ) -> PatternResult:
        """
        Apply the Breakdown pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "Lathe", "WebServer")
            x, y: Base coordinates
            channels: Number of parallel processing channels (default: 1)
            mean_time_between_failures: Mean time between failures in seconds (default: 3600)
            mean_time_to_repair: Mean time to repair in seconds (default: 600)
            service_time: Mean processing time per item in seconds (default: 60)
            service_dist: Distribution for service time (default: EXP)

        Returns:
            PatternResult with:
              - interface.input_place_id: Queue (items waiting for processing)
              - interface.output_place_id: Done (processed items)
              - metadata["operational_place_id"]: free-channel counter
              - metadata["failed_place_id"]: breakdown indicator
              - metadata["consume_transition_ids"]: [Start] for connect_bounded_consumer
        """
        place_ids: list[str] = []
        transition_ids: list[str] = []

        # 1. Queue — input items wait here
        p_queue = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_queue.id)

        # 2. Operational — free channel counter, one token per channel
        p_operational = net.add_place(
            name=f"{instance_name}_Operational",
            tokens=channels,
            x=x + 100,
            y=y - 120,
        )
        place_ids.append(p_operational.id)

        # 3. Processing — items currently being served
        p_processing = net.add_place(
            name=f"{instance_name}_Processing",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_processing.id)

        # 4. Done — output
        p_done = net.add_place(
            name=f"{instance_name}_Done",
            tokens=0,
            x=x + 400,
            y=y,
        )
        place_ids.append(p_done.id)

        # 5. Failed — machine is broken
        p_failed = net.add_place(
            name=f"{instance_name}_Failed",
            tokens=0,
            x=x + 100,
            y=y + 120,
        )
        place_ids.append(p_failed.id)

        # T_Start (immediate): Queue + Operational → Processing
        t_start = net.add_transition(
            name=f"{instance_name}_Start",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_start.id)

        # T_Finish (service_dist): Processing → Done + Operational (recycled)
        t_finish = net.add_transition(
            name=f"{instance_name}_Finish",
            mean_delay=service_time,
            distribution=service_dist,
            x=x + 300,
            y=y,
        )
        transition_ids.append(t_finish.id)

        # T_Break (EXP, MTBF): Operational → Failed
        t_break = net.add_transition(
            name=f"{instance_name}_Break",
            mean_delay=mean_time_between_failures,
            distribution=DistributionType.EXP,
            x=x + 100,
            y=y + 60,
        )
        transition_ids.append(t_break.id)

        # T_Repair (EXP, MTTR): Failed → Operational
        t_repair = net.add_transition(
            name=f"{instance_name}_Repair",
            mean_delay=mean_time_to_repair,
            distribution=DistributionType.EXP,
            x=x + 100,
            y=y + 180,
        )
        transition_ids.append(t_repair.id)

        # --- Arcs ---

        # Processing path
        net.add_arc(source_id=p_queue.id, target_id=t_start.id)
        net.add_arc(source_id=p_operational.id, target_id=t_start.id)
        net.add_arc(source_id=t_start.id, target_id=p_processing.id)

        net.add_arc(source_id=p_processing.id, target_id=t_finish.id)
        net.add_arc(source_id=t_finish.id, target_id=p_done.id)
        net.add_arc(source_id=t_finish.id, target_id=p_operational.id)  # recycle slot

        # Failure cycle
        net.add_arc(source_id=p_operational.id, target_id=t_break.id)
        net.add_arc(source_id=t_break.id, target_id=p_failed.id)

        net.add_arc(source_id=p_failed.id, target_id=t_repair.id)
        net.add_arc(source_id=t_repair.id, target_id=p_operational.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_queue.id,
                output_place_id=p_done.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "operational_place_id": p_operational.id,
                "failed_place_id": p_failed.id,
                "consume_transition_ids": [t_start.id],
            },
        )
