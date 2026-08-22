"""ThresholdActivation pattern - activate resource when queue exceeds threshold."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class ThresholdActivationPattern(BasePattern):
    """
    Threshold Activation pattern for conditional resource engagement.

    Implements "activate secondary resource when queue > N" logic.
    Used when a backup resource should only engage when the queue
    exceeds a certain threshold.

    Structure:
        [P: Queue] ---(threshold+1)---> [T: Activate] ---(1)---> [P: ToResource]
                   <---(threshold)-----               ---(1)---> [P: ResourceFree]
                                                                     |
                                                                     v
                                                              [T: Process]
                                                                     |
                                                                     v
                                                              [P: Done] + [P: ResourceFree]

    Key behavior:
    - Takes (threshold+1) tokens from Queue
    - Returns (threshold) tokens to Queue
    - Sends 1 token to resource for processing
    - Net effect: fires when Queue > threshold, removes exactly 1 item

    Use cases:
    - "Second machine activates when queue > 3"
    - "Backup server engages when load > N"
    - "Additional worker joins when backlog exceeds threshold"
    """

    tool_cursor_width = 500.0

    @property
    def name(self) -> str:
        return "ThresholdActivation"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        threshold: int = 3,
        queue_place_id: str | None = None,
        processing_time: float = 1.0,
        distribution: DistributionType = DistributionType.EXP,
    ) -> PatternResult:
        """
        Apply the ThresholdActivation pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "BackupMachine", "SecondaryWorker")
            x, y: Base coordinates
            threshold: Queue must exceed this value to activate (default: 3)
                      "Queue > 3" means fires when 4+ items present
            queue_place_id: ID of existing queue place to connect to.
                           If None, creates a new input queue.
            processing_time: Processing time for the resource (default: 1.0)
            distribution: Time distribution (default: exp)

        Returns:
            PatternResult with:
            - interface.input_place_id: Queue place (created or existing)
            - interface.output_place_id: Done place (processed items)
            - place_ids includes resource-related places
        """
        place_ids = []
        transition_ids = []

        # 1. Queue place (input) - create if not provided
        if queue_place_id:
            p_queue = net.get_place(queue_place_id)
            if p_queue is None:
                raise ValueError(f"Queue place '{queue_place_id}' not found")
        else:
            p_queue = net.add_place(
                name=f"{instance_name}_Queue",
                tokens=0,
                x=x,
                y=y,
            )
            place_ids.append(p_queue.id)

        # 2. Resource Free place (starts with 1 token = resource available)
        p_resource_free = net.add_place(
            name=f"{instance_name}_Free",
            tokens=1,
            x=x + 100,
            y=y - 80,
        )
        place_ids.append(p_resource_free.id)

        # 3. Busy place (item being processed)
        p_busy = net.add_place(
            name=f"{instance_name}_Busy",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_busy.id)

        # 4. Done place (processed items)
        p_done = net.add_place(
            name=f"{instance_name}_Done",
            tokens=0,
            x=x + 400,
            y=y,
        )
        place_ids.append(p_done.id)

        # 5. Activation transition - fires only when queue > threshold
        # Takes (threshold+1) from queue, returns (threshold), sends 1 to process
        t_activate = net.add_transition(
            name=f"{instance_name}_Activate",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=1,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_activate.id)

        # 6. Process transition (timed)
        t_process = net.add_transition(
            name=f"{instance_name}_Process",
            mean_delay=processing_time,
            distribution=distribution,
            priority=1,
            x=x + 300,
            y=y,
        )
        transition_ids.append(t_process.id)

        # --- Arcs ---

        # Activation: Queue(threshold+1) + Free(1) -> Busy(1) + Queue(threshold)
        net.add_arc(source_id=p_queue.id, target_id=t_activate.id, weight=threshold + 1)
        net.add_arc(source_id=p_resource_free.id, target_id=t_activate.id, weight=1)
        net.add_arc(source_id=t_activate.id, target_id=p_busy.id, weight=1)
        net.add_arc(source_id=t_activate.id, target_id=p_queue.id, weight=threshold)

        # Process: Busy -> Done + Free
        net.add_arc(source_id=p_busy.id, target_id=t_process.id)
        net.add_arc(source_id=t_process.id, target_id=p_done.id)
        net.add_arc(source_id=t_process.id, target_id=p_resource_free.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_queue.id,
                output_place_id=p_done.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )
