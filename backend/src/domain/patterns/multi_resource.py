"""Multi-Resource pattern - operation requiring multiple simultaneous resource types."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class MultiResourcePattern(BasePattern):
    """
    Multi-Resource (AND-Resource) pattern.

    Models an operation that simultaneously seizes multiple different resource pools
    and releases all of them upon completion. Each pool has its own place with an
    initial capacity (pool_size tokens).

    Structure:
        [Queue]   --+
        [ResA]    --+--> [Start (DET)] --> [Processing] --> [Finish] --> [Done]
        [ResB]    --+                                           |
                                                               +--> [ResA] (return)
                                                               +--> [ResB] (return)

    Use cases:
    - Painting booth: worker + spray gun + booth must all be free
    - Medical procedure: doctor + room + equipment required simultaneously
    - CNC operation: operator + machine + fixture seized together
    - Welding: welder + welding machine + jig required
    """

    tool_cursor_width = 500.0

    @property
    def name(self) -> str:
        return "MultiResource"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        resources: list[dict] | None = None,
        processing_time: float = 60.0,
        distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
    ) -> PatternResult:
        """
        Apply the MultiResource pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "PaintBooth", "SurgeryRoom")
            x, y: Base coordinates
            resources: List of resource pool definitions.
                       Each dict: {"name": str, "pool_size": int}.
                       Default: two resources, each with pool_size=1.
            processing_time: Mean processing time
            distribution: Time distribution for processing
            standard_deviation: Std dev for NORM/UNIF distributions

        Returns:
            PatternResult with:
              - interface.input_place_id: Queue (jobs arrive here)
              - interface.output_place_id: Done (completed jobs)
              - metadata["resource_place_ids"]: {resource_name: place_id}
              - metadata["consume_transition_ids"]: [Start]
        """
        if resources is None:
            resources = [
                {"name": "ResourceA", "pool_size": 1},
                {"name": "ResourceB", "pool_size": 1},
            ]

        place_ids: list[str] = []
        transition_ids: list[str] = []
        resource_place_ids: dict[str, str] = {}

        p_queue = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_queue.id)

        for i, res in enumerate(resources):
            p_res = net.add_place(
                name=f"{instance_name}_{res['name']}",
                tokens=res.get("pool_size", 1),
                x=x + 100,
                y=y - 80 * (i + 1),
            )
            place_ids.append(p_res.id)
            resource_place_ids[res["name"]] = p_res.id

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

        # Start (DET, immediate): seizes Queue + all resource pools
        t_start = net.add_transition(
            name=f"{instance_name}_Start",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_start.id)

        # Finish: releases all resource pools back
        t_finish = net.add_transition(
            name=f"{instance_name}_Finish",
            mean_delay=processing_time,
            distribution=distribution,
            standard_deviation=standard_deviation,
            x=x + 300,
            y=y,
        )
        transition_ids.append(t_finish.id)

        # Queue → Start
        net.add_arc(source_id=p_queue.id, target_id=t_start.id)

        # Each resource pool: Start seizes, Finish releases
        for res_place_id in resource_place_ids.values():
            net.add_arc(source_id=res_place_id, target_id=t_start.id)
            net.add_arc(source_id=t_finish.id, target_id=res_place_id)

        # Start → Processing → Finish → Done
        net.add_arc(source_id=t_start.id, target_id=p_processing.id)
        net.add_arc(source_id=p_processing.id, target_id=t_finish.id)
        net.add_arc(source_id=t_finish.id, target_id=p_done.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_queue.id,
                output_place_id=p_done.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "resource_place_ids": resource_place_ids,
                "consume_transition_ids": [t_start.id],
            },
        )
