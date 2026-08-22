"""Controller pattern - implements information links (read-only access)."""

from src.domain import DistributionType, PetriNet
from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


@register_pattern
class ControllerPattern(BasePattern):
    """
    Controller (Gate) pattern.

    Implements the use of "Information Link".
    Allows a flow of tokens to proceed only if a control signal is present,
    without consuming the signal (Read-Only Logic).

    Structure:
       [P: Signal] <----(loop)----+
           |                      ^
           v                      |
       [T: Gate] <--- [P: Input] (Flow)
           |
           v
       [P: Output]

    - The Signal place represents the condition (e.g., "Traffic Light Green").
    - The Gate transition consumes a token from Input AND Signal.
    - It immediately puts the token back into Signal (preserving the condition).
    """

    @property
    def name(self) -> str:
        return "Controller"

    def apply(
            self,
            net: PetriNet,
            instance_name: str,
            x: float,
            y: float,
            initial_signal: bool = False,
    ) -> PatternResult:
        """
        Add a controller/gate pattern.

        Args:
            net: Target PetriNet
            instance_name: Name (e.g., "TrafficLightGate")
            x, y: Base coordinates
            initial_signal: If True, starts with 1 token in Signal place. Default False.

        Returns:
            PatternResult.
            - input_place_id: Where the flow arrives.
            - output_place_id: Where the flow goes after check.
            - Signal place is internal but accessible via place_ids if needed for external control.
        """
        place_ids = []
        transition_ids = []

        # 1. Flow Input (Entities waiting for permission)
        p_flow_in = net.add_place(
            name=f"{instance_name}_FlowIn",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_flow_in.id)

        # 2. Signal Place (The condition, e.g., "Green Light")
        # Positioned above the gate
        p_signal = net.add_place(
            name=f"{instance_name}_Signal",
            tokens=1 if initial_signal else 0,
            x=x + 100,
            y=y - 100,
        )
        place_ids.append(p_signal.id)

        # 3. Gate Transition (Immediate check)
        t_gate = net.add_transition(
            name=f"{instance_name}_Check",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=x + 100,
            y=y,
        )
        transition_ids.append(t_gate.id)

        # 4. Flow Output (Entities that passed)
        p_flow_out = net.add_place(
            name=f"{instance_name}_FlowOut",
            tokens=0,
            x=x + 200,
            y=y,
        )
        place_ids.append(p_flow_out.id)

        # --- Arcs ---

        # Flow path: In -> Gate -> Out
        net.add_arc(source_id=p_flow_in.id, target_id=t_gate.id)
        net.add_arc(source_id=t_gate.id, target_id=p_flow_out.id)

        # Control path (The Loop): Signal -> Gate -> Signal
        # This simulates the "dotted line" from the manual
        net.add_arc(source_id=p_signal.id, target_id=t_gate.id)  # Read
        net.add_arc(source_id=t_gate.id, target_id=p_signal.id)  # Restore

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_flow_in.id,
                output_place_id=p_flow_out.id,
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )