"""Router pattern - implements branching via probability OR priority."""

from enum import Enum
from typing import List, Dict, Any
from src.domain import DistributionType, PetriNet
from .base import BasePattern, PatternInterface, PatternResult
from .registry import register_pattern


class RoutingStrategy(Enum):
    PROBABILITY = "probability"  # Random split (e.g., 70% / 30%)
    PRIORITY = "priority"        # Deterministic order (Try A first, then B)


@register_pattern
class RouterPattern(BasePattern):
    """
    Router (Splitter) pattern for directing flow.

    Handles two types of conflict resolution:
    1. Probability: Stochastic branching.
    2. Priority: Deterministic branching (e.g., "Main path" vs "Backup path").

    Structure:
                  /-> [T: Route A] -> [P: Out A]
    [P: Input] --+
                  \\-> [T: Route B] -> [P: Out B]
    """

    @property
    def name(self) -> str:
        return "Router"

    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        strategy: RoutingStrategy | str = RoutingStrategy.PROBABILITY,
        routes: List[Dict[str, Any]] | None = None,
    ) -> PatternResult:
        """
        Apply the Router pattern.

        Args:
            net: Target PetriNet
            instance_name: Name prefix
            x, y: Coordinates
            strategy: 'probability' (default) or 'priority'.
            routes: Configuration for branches.
                For PROBABILITY: [{"name": "A", "prob": 0.7}, ...]
                For PRIORITY:    [{"name": "High", "priority": 2}, {"name": "Low", "priority": 1}]
                                 (Higher number = higher priority, fires first, same as add_transition)

        Returns:
            PatternResult.
        """
        # 1. Determine Strategy
        strategy = RoutingStrategy(strategy) if isinstance(strategy, str) else strategy

        # 2. Get Routes
        if not routes:
            routes = [{"name": "Main", "prob": 0.5, "priority": 2},
                      {"name": "Alt", "prob": 0.5, "priority": 1}]

        place_ids = []
        transition_ids = []

        # 3. Input Place
        p_input = net.add_place(
            name=f"{instance_name}_In",
            tokens=0,
            x=x,
            y=y,
        )
        place_ids.append(p_input.id)

        # 4. Build Branches
        spacing_y = 100
        start_y = y - ((len(routes) - 1) * spacing_y) / 2

        for i, route in enumerate(routes):
            r_name = route.get("name", f"Path_{i}")
            cur_y = start_y + (i * spacing_y)

            # Prepare Transition Parameters based on Strategy
            t_params = {
                "name": f"{instance_name}_To_{r_name}",
                "mean_delay": 0.0,
                "distribution": DistributionType.DET,
                "x": x + 100,
                "y": cur_y,
            }

            # Inject strategy-specific attributes
            if strategy == RoutingStrategy.PROBABILITY:
                # Use probability attribute for stochastic branching
                prob = route.get("prob", 1.0 / len(routes))
                t_params["probability"] = prob

            elif strategy == RoutingStrategy.PRIORITY:
                # Higher priority value fires first (consistent with engine and all other tools).
                # Routes with a higher "priority" number are preferred when multiple are enabled.
                t_params["priority"] = route.get("priority", len(routes) - i)

            # Create Transition
            # We use **t_params to unpack arguments dynamically
            # Ensure your net.add_transition method accepts **kwargs or these specific args
            t_route = net.add_transition(**t_params)
            transition_ids.append(t_route.id)

            # Output Place
            p_route_out = net.add_place(
                name=f"{instance_name}_{r_name}",
                tokens=0,
                x=x + 200,
                y=cur_y,
            )
            place_ids.append(p_route_out.id)

            # Connect
            net.add_arc(source_id=p_input.id, target_id=t_route.id)
            net.add_arc(source_id=t_route.id, target_id=p_route_out.id)

        return PatternResult(
            interface=PatternInterface(
                input_place_id=p_input.id,
                output_place_id=None
            ),
            place_ids=place_ids,
            transition_ids=transition_ids,
        )