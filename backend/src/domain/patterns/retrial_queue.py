"""Retrial Queue pattern - customers retry after delay when server busy."""

from src.domain import DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class RetrialQueuePattern(BasePattern):
    """
    Retrial Queue (M/G/1 with retrial orbit) pattern.

    Models a server where busy arrivals go to an orbit and retry after a
    random delay, rather than leaving forever (unlike RenegingQueue).

    Structure:
        [Input] + [Free(c)] --[StartService prio=2]--> [Processing]
        [Input]              --[GoOrbit prio=1]------> [Orbit]
        [Orbit]              --[Retry EXP(delay)]----> [Input]  (retry loop)
        [Processing]         --[FinishService]-------> [Output] + [Free recycled]

    Priority rules:
    - StartService (prio=2) fires first when a channel is free.
    - GoOrbit (prio=1) fires only when ALL channels are busy (no Free token).
    - Retry feeds Input back from Orbit after the retrial delay.

    Use cases:
    - Telephone retrial: busy tone → caller tries again in a few minutes
    - HTTP 429 retry: exponential back-off retry loop
    - Doctor appointment: no slots today → call back tomorrow
    """

    tool_cursor_width = 600.0

    @property
    def name(self) -> str:
        return "RetrialQueue"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        service_time: float = 60.0,
        service_distribution: DistributionType = DistributionType.EXP,
        retrial_delay: float = 120.0,
        retrial_distribution: DistributionType = DistributionType.EXP,
        channels: int = 1,
    ) -> PatternResult:
        """
        Apply the RetrialQueue pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "PhoneServer", "APIGateway")
            x, y: Base coordinates
            service_time: Mean service time per customer
            service_distribution: Distribution for service time (default: EXP)
            retrial_delay: Mean delay between retry attempts
            retrial_distribution: Distribution for retrial delay (default: EXP)
            channels: Number of parallel server channels (default: 1)

        Returns:
            PatternResult with:
              - interface.input_place_id: Input (new arrivals + retrial customers)
              - interface.output_place_id: Output (successfully served customers)
              - metadata["orbit_place_id"]: customers currently retrying (tagged "orbit")
              - metadata["consume_transition_ids"]: [StartService] for connect_bounded_consumer
        """
        place_ids: list[str] = []
        transition_ids: list[str] = []

        p_input = net.add_place(
            name=f"{instance_name}_Input",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

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
            x=x + 250,
            y=y,
        )
        place_ids.append(p_processing.id)

        p_orbit = net.add_place(
            name=f"{instance_name}_Orbit",
            tokens=0,
            tag="orbit",
            x=x + 100,
            y=y + 130,
        )
        place_ids.append(p_orbit.id)

        p_output = net.add_place(
            name=f"{instance_name}_Output",
            tokens=0,
            x=x + 450,
            y=y,
        )
        place_ids.append(p_output.id)

        # StartService (DET=0, prio=2): Input + Free → Processing
        t_start = net.add_transition(
            name=f"{instance_name}_StartService",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=2,
            x=x + 150,
            y=y,
        )
        transition_ids.append(t_start.id)

        # GoOrbit (DET=0, prio=1): Input → Orbit  (fires when no Free token)
        t_go_orbit = net.add_transition(
            name=f"{instance_name}_GoOrbit",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            priority=1,
            x=x + 100,
            y=y + 65,
        )
        transition_ids.append(t_go_orbit.id)

        # FinishService: Processing → Output + Free recycled
        t_finish = net.add_transition(
            name=f"{instance_name}_FinishService",
            mean_delay=service_time,
            distribution=service_distribution,
            x=x + 350,
            y=y,
        )
        transition_ids.append(t_finish.id)

        # Retry: Orbit → Input (after retrial delay)
        t_retry = net.add_transition(
            name=f"{instance_name}_Retry",
            mean_delay=retrial_delay,
            distribution=retrial_distribution,
            x=x + 100,
            y=y + 210,
        )
        transition_ids.append(t_retry.id)

        # StartService path: Input + Free → Processing
        net.add_arc(source_id=p_input.id, target_id=t_start.id)
        net.add_arc(source_id=p_free.id, target_id=t_start.id)
        net.add_arc(source_id=t_start.id, target_id=p_processing.id)

        # GoOrbit path: Input → Orbit
        net.add_arc(source_id=p_input.id, target_id=t_go_orbit.id)
        net.add_arc(source_id=t_go_orbit.id, target_id=p_orbit.id)

        # FinishService path: Processing → Output + Free
        net.add_arc(source_id=p_processing.id, target_id=t_finish.id)
        net.add_arc(source_id=t_finish.id, target_id=p_output.id)
        net.add_arc(source_id=t_finish.id, target_id=p_free.id)

        # Retry loop: Orbit → Input
        net.add_arc(source_id=p_orbit.id, target_id=t_retry.id)
        net.add_arc(source_id=t_retry.id, target_id=p_input.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "orbit_place_id": p_orbit.id,
                "consume_transition_ids": [t_start.id],
            },
        )
