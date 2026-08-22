"""Assembly pattern - synchronizes multiple flows into one."""

from src.domain import DistributionType, PetriNet
from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class AssemblyPattern(BasePattern):
    """
    Assembly (Join/Synchronization) pattern.

    Implements the "AND" logic for Petri Nets.
    A transition requires tokens in ALL input places to fire.
    This synchronizes independent parallel flows.

    Structure:
    [P: Part A] --\
                   v
    [P: Part B] ---> [T: Assemble] -> [P: Product]
                   ^
    [P: Part C] --/

    Supports weighted inputs (arc weights) for requiring multiple tokens:
    - "Requires 10 of Type1 AND 10 of Type2" -> sources with weights
    """

    @property
    def name(self) -> str:
        return "Assembly"

    def apply(
            self,
            net: PetriNet,
            instance_name: str,
            x: float,
            y: float,
            inputs: list[str | dict] | None = None,
            assembly_time: float = 1.0,
            distribution: DistributionType = DistributionType.DET,
            priority: int = 1,
            sources: list[str | dict] | None = None,
    ) -> PatternResult:
        """
        Apply the Assembly pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix (e.g., "CarAssembly")
            x, y: Coordinates for the central transition
            inputs: Names for the input slots this assembly creates. Each
                entry produces a NEW input place named
                "{instance_name}_In_{slot_name}" (the caller is
                responsible for wiring external sources into these slots
                via connect_patterns(external_id, slot_id)).
                Simple list: ["Body", "Engine"] (weight=1 each)
                Weighted: [{"name": "Body", "weight": 1}, {"name": "Bolts", "weight": 8}]
                Default: ["Part_A", "Part_B"]
            assembly_time: Mean firing time. Default 1.0.
            distribution: Time distribution.
            priority: Transition priority. Default 1.
            sources: Deprecated alias for `inputs`, kept for old call sites.
                Ignored when `inputs` is also given.

        Returns:
            PatternResult with metadata["input_place_ids"]: dict mapping each
            slot name to its created place_id, so callers can wire external
            sources by semantic name without guessing IDs.
        """
        # `inputs` is the canonical name; `sources` is accepted as a
        # deprecated alias to ease migration from old call sites.
        inputs_raw = inputs if inputs is not None else sources
        if not inputs_raw:
            inputs_raw = ["Part_A", "Part_B"]

        slots = []
        for src in inputs_raw:
            if isinstance(src, str):
                slots.append({"name": src, "weight": 1})
            elif isinstance(src, dict):
                slots.append({
                    "name": src.get("name", "Part"),
                    "weight": src.get("weight", 1)
                })
            else:
                slots.append({"name": str(src), "weight": 1})

        place_ids = []
        transition_ids = []
        input_place_ids: dict[str, str] = {}

        # 2. Create Assembly Transition (The "Join" point)
        t_assemble = net.add_transition(
            name=f"{instance_name}_Do",
            mean_delay=assembly_time,
            distribution=distribution,
            priority=priority,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_assemble.id)

        # 3. Create Input Places (The "Waiting" buffers for parts)
        # Fan them out vertically to the left of the transition
        spacing_y = 80
        start_y = y - ((len(slots) - 1) * spacing_y) / 2

        for i, slot in enumerate(slots):
            slot_name = slot["name"]
            weight = slot["weight"]
            cur_y = start_y + (i * spacing_y)

            p_input = net.add_place(
                name=f"{instance_name}_In_{slot_name}",
                tokens=0,
                x=x,
                y=cur_y,
            )
            place_ids.append(p_input.id)
            input_place_ids[slot_name] = p_input.id

            # Connect Input -> Assembly Transition with weight
            net.add_arc(source_id=p_input.id, target_id=t_assemble.id, weight=weight)

        # 4. Create Output Place (The Result)
        p_product = net.add_place(
            name=f"{instance_name}_Product",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_product.id)

        # Connect Assembly -> Output
        net.add_arc(source_id=t_assemble.id, target_id=p_product.id)

        return PatternResult(
            interface=PatternInterface(
                # Ambiguous input: Assembly has multiple entry points.
                # Wire external sources to specific slots via metadata["input_place_ids"].
                input_place_id=None,
                output_place_id=p_product.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
            metadata={
                "input_place_ids": input_place_ids,
                "consume_transition_ids": [t_assemble.id],
            },
        )