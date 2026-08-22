"""Resource Set pattern — entity seizes first available from a pool of alternatives."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class ResourceSetPattern(BasePattern):
    """Alternative resource pool: entity seizes the first available resource.

    Models Arena's "Resource Sets" — entity tries resources in priority order
    (first in list = highest priority) and seizes whichever is free first.
    Each resource has its own service time and channel count.

    Structure (for N resources):
        [Input] --conflict-->
            [TSeize_R0(p=N, DET=0)] with [FreeR0(ch0)] --> [InService_R0] --> [TEnd_R0] --> [Output]
            [TSeize_R1(p=N-1, DET=0)] with [FreeR1(ch1)] --> [InService_R1] --> [TEnd_R1] --> [Output]
            ...
        Each TEnd_Ri also returns a token to FreeRi (channel recycling).

    Priority rule: resource at index 0 has priority N, index 1 has N-1, etc.
    If R0 has a free channel, it is always preferred over R1, R1 over R2, etc.

    Difference from Machine(channels=N):
    - Machine: all channels identical, same service time
    - ResourceSet: each alternative can have a different service time, distribution,
      and number of channels; preference ordering is explicit

    Use cases:
    - Flexible manufacturing cell: 3 machines with different speeds, use fastest first
    - Healthcare: senior nurse (fast) preferred over junior (slow)
    - Server farm: fast server tried first, fallback to slower when busy
    - Parallel checkout lanes with different average speeds
    """

    tool_cursor_width = 600.0

    @property
    def name(self) -> str:
        return "ResourceSet"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        resources: list[dict] | None = None,
        standard_deviation: float = 0.0,
    ) -> PatternResult:
        """Apply the ResourceSet pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "MachinePool", "NursePool")
            x, y: Base coordinates
            resources: List of resource definitions, ordered by preference
                       (index 0 = highest priority). Each dict:
                         - "name": str (required)
                         - "service_time": float (default 60.0)
                         - "distribution": str (default "exp")
                         - "channels": int (default 1)
                         - "standard_deviation": float (overrides global default)
                       Example:
                         [{"name": "FastMachine", "service_time": 30.0, "channels": 1},
                          {"name": "SlowMachine", "service_time": 90.0, "channels": 2}]
            standard_deviation: Global std dev fallback for NORM/UNIF resources

        Returns:
            PatternResult with:
              - interface.input_place_id: Input (where entities arrive)
              - interface.output_place_id: Output (shared exit for all resources)
              - metadata["resource_free_place_ids"]: dict resource_name → FreeRi place id
        """
        if resources is None:
            resources = [{"name": "ResourceA"}]
        if not resources:
            raise ValueError("ResourceSet requires at least one resource")
        for i, r in enumerate(resources):
            if "name" not in r:
                raise ValueError(f"Resource at index {i} must have a 'name' key")
            ch = r.get("channels", 1)
            if ch < 1:
                raise ValueError(
                    f"Resource '{r['name']}' channels must be >= 1, got {ch}"
                )

        place_ids: list[str] = []
        transition_ids: list[str] = []
        resource_free_place_ids: dict[str, str] = {}

        n = len(resources)
        dx = 200.0
        dy = 100.0

        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + (n + 1) * dx,
            y=y,
        )
        place_ids.append(p_output.id)

        for i, r in enumerate(resources):
            rname = r["name"]
            stime = float(r.get("service_time", 60.0))
            dist = DistributionType(r.get("distribution", "exp"))
            channels = int(r.get("channels", 1))
            sd = float(r.get("standard_deviation", standard_deviation))
            priority = n - i  # R0 → highest priority

            p_free = net.add_place(
                name=f"{instance_name}_Free_{rname}",
                tokens=channels,
                x=x + (i + 1) * dx,
                y=y - (i + 1) * dy,
            )
            place_ids.append(p_free.id)
            resource_free_place_ids[rname] = p_free.id

            p_in_service = net.add_place(
                name=f"{instance_name}_InService_{rname}",
                tokens=0,
                x=x + (i + 1) * dx,
                y=y,
            )
            place_ids.append(p_in_service.id)

            t_seize = net.add_transition(
                name=f"{instance_name}_Seize_{rname}",
                mean_delay=0.0,
                distribution=DistributionType.DET,
                priority=priority,
                x=x + (i + 1) * dx - dx // 2,
                y=y,
            )
            transition_ids.append(t_seize.id)

            t_end = net.add_transition(
                name=f"{instance_name}_End_{rname}",
                mean_delay=stime,
                distribution=dist,
                standard_deviation=sd,
                x=x + (i + 1) * dx + dx // 2,
                y=y,
            )
            transition_ids.append(t_end.id)

            # Seize path: Input + Free → InService
            net.add_arc(source_id=p_input.id, target_id=t_seize.id)
            net.add_arc(source_id=p_free.id, target_id=t_seize.id)
            net.add_arc(source_id=t_seize.id, target_id=p_in_service.id)

            # End path: InService → Output + return Free
            net.add_arc(source_id=p_in_service.id, target_id=t_end.id)
            net.add_arc(source_id=t_end.id, target_id=p_output.id)
            net.add_arc(source_id=t_end.id, target_id=p_free.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={"resource_free_place_ids": resource_free_place_ids},
        )
