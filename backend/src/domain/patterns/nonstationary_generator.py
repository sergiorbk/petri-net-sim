"""NonStationaryGenerator pattern - arrival rate changes over time windows."""

from src.domain import ArcType, DistributionType, PetriNet

from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class NonstationaryGeneratorPattern(BasePattern):
    """
    Non-Stationary Generator (Time-Varying Arrivals) pattern.

    Arrival rate changes over time according to a cyclic schedule. Each time
    window has its own generator gated by an active-slot place. A master
    timer cycles through slots sequentially.

    Structure (2 windows example):
        Slot1Active (1) → [Timer1 DET d1] → Slot2Active
        Slot2Active     → [Timer2 DET d2] → Slot1Active

        Slot1Active ─READ─→ [Gen1 EXP interval1] → Output
        Slot2Active ─READ─→ [Gen2 EXP interval2] → Output

    The active-slot token circulates: Slot1Active → Timer1 → Slot2Active →
    Timer2 → Slot1Active → ... Each slot's generator only fires while that
    slot holds a token (READ arc = require but don't consume).

    Use cases:
    - Morning rush (rate 20/h) + afternoon (rate 5/h) + night (rate 1/h)
    - Factory: day shift (rate 10/min) + night shift (rate 3/min)
    - Call center: peak hours vs off-peak
    """

    tool_cursor_width = 800.0

    @property
    def name(self) -> str:
        return "NonstationaryGenerator"

    def apply(  # NOSONAR
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        schedule: list[dict] | None = None,
        batch_size: int = 1,
    ) -> PatternResult:
        """
        Apply the NonStationaryGenerator pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "CoffeeShop", "CallCenter")
            x, y: Base coordinates
            schedule: List of time windows, each dict:
                      {"duration": float (seconds), "rate": float (arrivals/sec)}
                      Default: single 1-hour window at rate 1/60s
            batch_size: Tokens per arrival (default: 1)

        Returns:
            PatternResult with:
              - interface.input_place_id: None (generator)
              - interface.output_place_id: combined output
              - metadata["slot_place_ids"]: list of active-slot place IDs
              - metadata["generator_transition_ids"]: list of generator transition IDs
        """
        if schedule is None:
            schedule = [{"duration": 3600.0, "rate": 1.0 / 60.0}]

        if len(schedule) < 1:
            raise ValueError("NonStationaryGenerator schedule must have >= 1 window")

        for i, entry in enumerate(schedule):
            if "duration" not in entry or "rate" not in entry:
                raise ValueError(
                    f"Schedule entry {i} must have 'duration' and 'rate' keys, "
                    f"got {entry}"
                )
            if entry["duration"] <= 0:
                raise ValueError(f"Schedule entry {i}: duration must be > 0")
            if entry["rate"] < 0:
                raise ValueError(f"Schedule entry {i}: rate must be >= 0")

        place_ids: list[str] = []
        transition_ids: list[str] = []
        slot_place_ids: list[str] = []
        gen_transition_ids: list[str] = []

        n_slots = len(schedule)

        # Single shared output
        p_output = net.add_place(
            name=f"{instance_name}_Out",
            tokens=0,
            x=x + 400, y=y,
        )
        place_ids.append(p_output.id)

        # Create slot places (only first one starts with token)
        for i in range(n_slots):
            p_slot = net.add_place(
                name=f"{instance_name}_Slot{i + 1}",
                tokens=1 if i == 0 else 0,
                x=x + i * 200, y=y - 120,
            )
            place_ids.append(p_slot.id)
            slot_place_ids.append(p_slot.id)

        # Create timer transitions (cycle through slots)
        for i in range(n_slots):
            next_i = (i + 1) % n_slots
            t_timer = net.add_transition(
                name=f"{instance_name}_Timer{i + 1}",
                mean_delay=schedule[i]["duration"],
                distribution=DistributionType.DET,
                x=x + i * 200 + 100, y=y - 120,
            )
            transition_ids.append(t_timer.id)

            # Slot[i] → Timer → Slot[next]
            net.add_arc(source_id=slot_place_ids[i], target_id=t_timer.id)
            net.add_arc(source_id=t_timer.id, target_id=slot_place_ids[next_i])

        # Create per-slot generators gated by READ arcs
        for i in range(n_slots):
            rate = schedule[i]["rate"]
            if rate <= 0:
                continue

            interval = 1.0 / rate

            # Ready place for this generator
            p_ready = net.add_place(
                name=f"{instance_name}_Ready{i + 1}",
                tokens=1,
                x=x + i * 200, y=y,
            )
            place_ids.append(p_ready.id)

            # Generator transition gated by slot's READ arc
            t_gen = net.add_transition(
                name=f"{instance_name}_Gen{i + 1}",
                mean_delay=interval,
                distribution=DistributionType.EXP,
                x=x + i * 200 + 80, y=y,
            )
            transition_ids.append(t_gen.id)
            gen_transition_ids.append(t_gen.id)

            # Ready → Gen → Ready (loop)
            net.add_arc(source_id=p_ready.id, target_id=t_gen.id)
            net.add_arc(source_id=t_gen.id, target_id=p_ready.id)

            # Gen → Output (with batch_size)
            net.add_arc(source_id=t_gen.id, target_id=p_output.id, weight=batch_size)

            # READ arc: Slot → Gen (gate — gen fires only when slot active)
            net.add_arc(
                source_id=slot_place_ids[i],
                target_id=t_gen.id,
                arc_type=ArcType.READ,
            )

        return PatternResult(
            interface=PatternInterface(
                input_place_id=None,
                output_place_id=p_output.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "slot_place_ids": slot_place_ids,
                "generator_transition_ids": gen_transition_ids,
            },
        )
