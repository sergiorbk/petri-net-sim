"""PreemptiveMachine pattern - high-priority jobs interrupt normal processing."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class PreemptiveMachinePattern(BasePattern):
    """
    Preemptive Machine (Preempt-Restart) pattern.

    A machine that can be interrupted by high-priority arrivals. When a
    high-priority job arrives and the machine is busy with a normal job,
    the normal job is preempted (removed from processing) and returned to
    a preempted queue. It restarts from scratch when resumed.

    Structure:
        NormalQueue + Free → [StartNormal p=1] → Processing
        Processing → [FinishNormal] → Done + Free

        HighQueue + Free → [StartHigh p=3] → HighProcessing
        HighProcessing → [FinishHigh] → Done + Free

        HighQueue + Processing → [Preempt p=2] → PreemptedQueue + HighProcessing

    Priority rules:
    - StartHigh (prio=3): high-priority job starts immediately if channel free
    - Preempt (prio=2): high-priority job interrupts normal processing.
      Consumes token from Processing (preempted job) and HighQueue,
      produces to PreemptedQueue and HighProcessing. No Free token needed
      because it's "stealing" the channel from the normal job.
    - StartNormal (prio=1): normal job starts only if channel free and no
      high-priority jobs waiting

    Preempted jobs re-enter PreemptedQueue and eventually get picked up by
    StartNormal again (restart from scratch). PreemptedQueue feeds StartNormal
    via an additional input arc.

    Limitation: Preempt-Resume (continuing partial work) requires colored
    tokens to track remaining time and is not supported in P/T nets.

    Use cases:
    - Emergency room: critical patients interrupt routine care
    - CNC machine: emergency orders preempt normal jobs
    - CPU scheduling: high-priority process preempts running task
    """

    tool_cursor_width = 700.0

    @property
    def name(self) -> str:
        return "PreemptiveMachine"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        normal_time: float = 60.0,
        high_priority_time: float = 30.0,
        distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        channels: int = 1,
    ) -> PatternResult:
        """
        Apply the PreemptiveMachine pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "ER", "CNC")
            x, y: Base coordinates
            normal_time: Mean processing time for normal jobs
            high_priority_time: Mean processing time for high-priority jobs
            distribution: Distribution for both processing times
            standard_deviation: Std dev for NORM/UNIF
            channels: Number of parallel channels

        Returns:
            PatternResult with:
              - interface.input_place_id: normal queue
              - interface.output_place_id: completed jobs (all priorities)
              - metadata["high_priority_input_id"]: high-priority arrival queue
              - metadata["preempted_place_id"]: displaced jobs waiting to restart
              - metadata["consume_transition_ids"]: [StartNormal] for wiring
        """
        if channels < 1:
            raise ValueError(f"PreemptiveMachine channels must be >= 1, got {channels}")

        place_ids: list[str] = []
        transition_ids: list[str] = []

        # Normal queue
        p_normal = net.add_place(
            name=f"{instance_name}_NormalQueue",
            tokens=0,
            x=x, y=y,
        )
        place_ids.append(p_normal.id)

        # High-priority queue
        p_high = net.add_place(
            name=f"{instance_name}_HighQueue",
            tokens=0,
            x=x, y=y - 150,
        )
        place_ids.append(p_high.id)

        # Free channels
        p_free = net.add_place(
            name=f"{instance_name}_Free",
            tokens=channels,
            x=x + 150, y=y - 80,
        )
        place_ids.append(p_free.id)

        # Normal processing
        p_processing = net.add_place(
            name=f"{instance_name}_Processing",
            tokens=0,
            x=x + 300, y=y,
        )
        place_ids.append(p_processing.id)

        # High-priority processing
        p_high_proc = net.add_place(
            name=f"{instance_name}_HighProcessing",
            tokens=0,
            x=x + 300, y=y - 150,
        )
        place_ids.append(p_high_proc.id)

        # Preempted queue (displaced normal jobs restart here)
        p_preempted = net.add_place(
            name=f"{instance_name}_Preempted",
            tokens=0,
            x=x + 150, y=y + 100,
        )
        place_ids.append(p_preempted.id)

        # Done (all completed jobs)
        p_done = net.add_place(
            name=f"{instance_name}_Done",
            tokens=0,
            x=x + 600, y=y - 75,
        )
        place_ids.append(p_done.id)

        # StartNormal (prio=1): NormalQueue + Free → Processing
        # Also accepts from PreemptedQueue
        t_start_normal = net.add_transition(
            name=f"{instance_name}_StartNormal",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=1,
            x=x + 150, y=y,
        )
        transition_ids.append(t_start_normal.id)

        # RestartPreempted (prio=1): PreemptedQueue + Free → Processing
        t_restart = net.add_transition(
            name=f"{instance_name}_Restart",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=1,
            x=x + 150, y=y + 50,
        )
        transition_ids.append(t_restart.id)

        # FinishNormal: Processing → Done + Free
        t_finish_normal = net.add_transition(
            name=f"{instance_name}_FinishNormal",
            mean_delay=normal_time,
            distribution=distribution,
            standard_deviation=standard_deviation,
            x=x + 450, y=y,
        )
        transition_ids.append(t_finish_normal.id)

        # StartHigh (prio=3): HighQueue + Free → HighProcessing
        t_start_high = net.add_transition(
            name=f"{instance_name}_StartHigh",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=3,
            x=x + 150, y=y - 150,
        )
        transition_ids.append(t_start_high.id)

        # Preempt (prio=2): HighQueue + Processing → PreemptedQueue + HighProcessing
        # "Steals" the channel from normal job — no Free needed
        t_preempt = net.add_transition(
            name=f"{instance_name}_Preempt",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=2,
            x=x + 300, y=y - 75,
        )
        transition_ids.append(t_preempt.id)

        # FinishHigh: HighProcessing → Done + Free
        t_finish_high = net.add_transition(
            name=f"{instance_name}_FinishHigh",
            mean_delay=high_priority_time,
            distribution=distribution,
            standard_deviation=standard_deviation,
            x=x + 450, y=y - 150,
        )
        transition_ids.append(t_finish_high.id)

        # --- Arcs ---

        # StartNormal: NormalQueue + Free → Processing
        net.add_arc(source_id=p_normal.id, target_id=t_start_normal.id)
        net.add_arc(source_id=p_free.id, target_id=t_start_normal.id)
        net.add_arc(source_id=t_start_normal.id, target_id=p_processing.id)

        # Restart: PreemptedQueue + Free → Processing
        net.add_arc(source_id=p_preempted.id, target_id=t_restart.id)
        net.add_arc(source_id=p_free.id, target_id=t_restart.id)
        net.add_arc(source_id=t_restart.id, target_id=p_processing.id)

        # FinishNormal: Processing → Done + Free
        net.add_arc(source_id=p_processing.id, target_id=t_finish_normal.id)
        net.add_arc(source_id=t_finish_normal.id, target_id=p_done.id)
        net.add_arc(source_id=t_finish_normal.id, target_id=p_free.id)

        # StartHigh: HighQueue + Free → HighProcessing
        net.add_arc(source_id=p_high.id, target_id=t_start_high.id)
        net.add_arc(source_id=p_free.id, target_id=t_start_high.id)
        net.add_arc(source_id=t_start_high.id, target_id=p_high_proc.id)

        # Preempt: HighQueue + Processing → PreemptedQueue + HighProcessing
        net.add_arc(source_id=p_high.id, target_id=t_preempt.id)
        net.add_arc(source_id=p_processing.id, target_id=t_preempt.id)
        net.add_arc(source_id=t_preempt.id, target_id=p_preempted.id)
        net.add_arc(source_id=t_preempt.id, target_id=p_high_proc.id)

        # FinishHigh: HighProcessing → Done + Free
        net.add_arc(source_id=p_high_proc.id, target_id=t_finish_high.id)
        net.add_arc(source_id=t_finish_high.id, target_id=p_done.id)
        net.add_arc(source_id=t_finish_high.id, target_id=p_free.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_normal.id,
                output_place_id=p_done.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "high_priority_input_id": p_high.id,
                "preempted_place_id": p_preempted.id,
                "consume_transition_ids": [t_start_normal.id],
            },
        )
