"""Finite Population Queue pattern — closed queueing network (M/M/c/∞/N)."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class FinitePopulationQueuePattern(BasePattern):
    """Closed queueing network: N entities recirculate through a c-server queue.

    Models M/M/c/∞/N systems where N customers alternate between "thinking"
    (off-system rest) and waiting for service. After service completes the entity
    rests for `thinking_time` then re-enters the queue. No new entities are ever
    created; the same N circulate indefinitely.

    Structure:
        [IdlePool(N)] --[Request DET=0]--> [Queue]
        [Queue] + [FreeChannels(c)] --[Start DET=0]--> [InService]
        [InService] --[EndService]--> [Done] + FreeChannels returned
        [Done] --[Measure DET=0]--> [Resting] + [Counter(throughput)]
        [Resting] --[EndRest]--> [IdlePool]

    Token conservation: IdlePool + Queue + InService + Resting = N at all times.
    Counter accumulates as a monotone throughput counter (same convention as Terminator).

    Use cases:
    - Manufacturing: N pallets / fixtures circulating through work cells
    - Repair: N tools shared by technicians (tool → use → return to pool → reuse)
    - Taxi fleet: N taxis (idle → pickup → ride → return → idle)
    - Call centre agents: N agents serve customers, then become available again
    - Finite population M/M/c: classic Engset-style model

    When thinking_time=0 entities return immediately (pure circulation, no idle phase).
    """

    tool_cursor_width = 900.0
    tool_non_time_params = frozenset({"n_customers", "channels"})

    @property
    def name(self) -> str:
        return "FinitePopulationQueue"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        n_customers: int = 5,
        service_time: float = 60.0,
        service_distribution: DistributionType = DistributionType.EXP,
        standard_deviation: float = 0.0,
        channels: int = 1,
        thinking_time: float = 0.0,
        thinking_distribution: DistributionType = DistributionType.EXP,
    ) -> PatternResult:
        """Apply the FinitePopulationQueue pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "PalletLine", "TaxiFleet")
            x, y: Base coordinates
            n_customers: Population size N — initial tokens in IdlePool (>= 1)
            service_time: Mean service duration
            service_distribution: Distribution for service time (default: EXP)
            standard_deviation: Std dev for NORM/UNIF service distributions
            channels: Number of parallel servers c (default: 1)
            thinking_time: Mean rest time after service before re-entering queue.
                           0 = immediate recirculation (no idle phase).
            thinking_distribution: Distribution for thinking time (default: EXP)

        Returns:
            PatternResult with:
              - interface.input_place_id: Queue (external sources can also feed the queue)
              - interface.output_place_id: Counter (tagged "throughput", accumulates)
              - metadata["pool_place_id"]: IdlePool place
              - metadata["queue_place_id"]: Queue place
              - metadata["free_channels_place_id"]: FreeChannels resource pool
              - metadata["counter_place_id"]: throughput counter place
              - metadata["resting_place_id"]: Resting place (entity off-system rest)
        """
        place_ids: list[str] = []
        transition_ids: list[str] = []

        dx = 120.0

        # --- Places ---

        p_pool = net.add_place(
            name=f"{instance_name}_IdlePool",
            tokens=n_customers,
            x=x,
            y=y,
        )
        place_ids.append(p_pool.id)

        p_queue = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x + 2 * dx,
            y=y,
        )
        place_ids.append(p_queue.id)

        p_free = net.add_place(
            name=f"{instance_name}_FreeChannels",
            tokens=channels,
            x=x + 3 * dx,
            y=y - 80,
        )
        place_ids.append(p_free.id)

        p_service = net.add_place(
            name=f"{instance_name}_InService",
            tokens=0,
            x=x + 4 * dx,
            y=y,
        )
        place_ids.append(p_service.id)

        p_done = net.add_place(
            name=f"{instance_name}_Done",
            tokens=0,
            x=x + 6 * dx,
            y=y,
        )
        place_ids.append(p_done.id)

        p_counter = net.add_place(
            name=f"{instance_name}_Counter",
            tokens=0,
            tag="throughput",
            x=x + 7 * dx,
            y=y - 80,
        )
        place_ids.append(p_counter.id)

        p_rest = net.add_place(
            name=f"{instance_name}_Resting",
            tokens=0,
            x=x + 7 * dx,
            y=y + 100,
        )
        place_ids.append(p_rest.id)

        # --- Transitions ---

        t_request = net.add_transition(
            name=f"{instance_name}_Request",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + dx,
            y=y,
        )
        transition_ids.append(t_request.id)

        t_start = net.add_transition(
            name=f"{instance_name}_StartService",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 3 * dx,
            y=y,
        )
        transition_ids.append(t_start.id)

        t_end = net.add_transition(
            name=f"{instance_name}_EndService",
            mean_delay=service_time,
            distribution=service_distribution,
            standard_deviation=standard_deviation,
            x=x + 5 * dx,
            y=y,
        )
        transition_ids.append(t_end.id)

        t_measure = net.add_transition(
            name=f"{instance_name}_Measure",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 7 * dx,
            y=y,
        )
        transition_ids.append(t_measure.id)

        t_end_rest = net.add_transition(
            name=f"{instance_name}_EndRest",
            mean_delay=thinking_time,
            distribution=(
                thinking_distribution if thinking_time > 0.0 else DistributionType.DET
            ),
            x=x + 8 * dx,
            y=y + 100,
        )
        transition_ids.append(t_end_rest.id)

        # --- Arcs ---

        # Pool → Request → Queue
        net.add_arc(source_id=p_pool.id, target_id=t_request.id)
        net.add_arc(source_id=t_request.id, target_id=p_queue.id)

        # Queue + FreeChannels → StartService → InService
        net.add_arc(source_id=p_queue.id, target_id=t_start.id)
        net.add_arc(source_id=p_free.id, target_id=t_start.id)
        net.add_arc(source_id=t_start.id, target_id=p_service.id)

        # InService → EndService → Done + return FreeChannels
        net.add_arc(source_id=p_service.id, target_id=t_end.id)
        net.add_arc(source_id=t_end.id, target_id=p_done.id)
        net.add_arc(source_id=t_end.id, target_id=p_free.id)

        # Done → Measure → Resting + Counter
        net.add_arc(source_id=p_done.id, target_id=t_measure.id)
        net.add_arc(source_id=t_measure.id, target_id=p_rest.id)
        net.add_arc(source_id=t_measure.id, target_id=p_counter.id)

        # Resting → EndRest → IdlePool
        net.add_arc(source_id=p_rest.id, target_id=t_end_rest.id)
        net.add_arc(source_id=t_end_rest.id, target_id=p_pool.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_queue.id,
                output_place_id=p_counter.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "pool_place_id": p_pool.id,
                "queue_place_id": p_queue.id,
                "free_channels_place_id": p_free.id,
                "counter_place_id": p_counter.id,
                "resting_place_id": p_rest.id,
            },
        )
