"""QualityCheck pattern - probabilistic inspection with pass/fail outcomes."""

from src.domain import DistributionType, PetriNet
from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class QualityCheckPattern(BasePattern):
    """
    Quality Check (Inspection) pattern.

    Combines processing with probabilistic branching.
    Items are inspected and routed to either "passed" or "failed" output
    based on probability.

    Structure:
        [P: Input] -> [T: Inspect] -> [P: Inspecting]
                                           |
                          +----------------+----------------+
                          |                                 |
                          v                                 v
                   [T: Pass (prob%)]               [T: Fail ((1-prob)%)]
                          |                                 |
                          v                                 v
                    [P: Passed]                       [P: Failed]

    Use cases:
    - "92% of products pass quality check"
    - "5% of TVs fail testing"
    - "96% success rate, 4% defect"
    """

    tool_cursor_width = 500.0

    @property
    def name(self) -> str:
        return "QualityCheck"

    def apply(
            self,
            net: PetriNet,
            instance_name: str,
            x: float,
            y: float,
            inspection_time: float = 1.0,
            distribution: DistributionType = DistributionType.DET,
            pass_probability: float = 0.9,
            pass_name: str = "Passed",
            fail_name: str = "Failed",
    ) -> PatternResult:
        """
        Apply the QualityCheck pattern.

        Args:
            net: Target PetriNet
            instance_name: Name (e.g., "Inspection", "QualityControl")
            x, y: Coordinates
            inspection_time: Time for inspection. Default: 1.0.
            distribution: Time distribution. Default: DET.
            pass_probability: Probability of passing (0.0-1.0). Default: 0.9.
            pass_name: Name for passed output. Default: "Passed".
            fail_name: Name for failed output. Default: "Failed".

        Returns:
            PatternResult.
            - input_place_id: Where items enter for inspection.
            - output_place_id: Points to Passed output (primary output).
            - place_ids includes both Passed and Failed places.
        """
        place_ids = []
        transition_ids = []

        # 1. Input place
        p_input = net.add_place(
            name=f"{instance_name}_Queue",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        # 2. Inspection transition (timed)
        t_inspect = net.add_transition(
            name=f"{instance_name}_Inspect",
            mean_delay=inspection_time,
            distribution=distribution,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_inspect.id)

        # 3. Inspecting place (item being checked)
        p_inspecting = net.add_place(
            name=f"{instance_name}_Checking",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_inspecting.id)

        # 4. Pass transition (immediate, with probability)
        t_pass = net.add_transition(
            name=f"{instance_name}_Pass",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            probability=pass_probability,
            x=x + 300,
            y=y - 60,
        )
        transition_ids.append(t_pass.id)

        # 5. Fail transition (immediate, with complementary probability)
        t_fail = net.add_transition(
            name=f"{instance_name}_Fail",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            probability=1.0 - pass_probability,
            x=x + 300,
            y=y + 60,
        )
        transition_ids.append(t_fail.id)

        # 6. Passed output place
        p_passed = net.add_place(
            name=f"{instance_name}_{pass_name}",
            tokens=0,
            x=x + 400,
            y=y - 60,
        )
        place_ids.append(p_passed.id)

        # 7. Failed output place
        p_failed = net.add_place(
            name=f"{instance_name}_{fail_name}",
            tokens=0,
            x=x + 400,
            y=y + 60,
        )
        place_ids.append(p_failed.id)

        # --- Arcs ---

        # Input -> Inspect -> Inspecting
        net.add_arc(source_id=p_input.id, target_id=t_inspect.id)
        net.add_arc(source_id=t_inspect.id, target_id=p_inspecting.id)

        # Inspecting -> Pass -> Passed
        net.add_arc(source_id=p_inspecting.id, target_id=t_pass.id)
        net.add_arc(source_id=t_pass.id, target_id=p_passed.id)

        # Inspecting -> Fail -> Failed
        net.add_arc(source_id=p_inspecting.id, target_id=t_fail.id)
        net.add_arc(source_id=t_fail.id, target_id=p_failed.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=p_passed.id,  # Primary output is Passed
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )
