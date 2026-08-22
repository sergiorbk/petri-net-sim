"""Base pattern class for Petri Net building blocks."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, FrozenSet, List, Optional

from src.domain import PetriNet


@dataclass
class PatternInterface:
    """
    Interface points for connecting patterns.

    Patterns expose input and output places that can be connected
    to other patterns via arcs.
    """

    input_place_id: Optional[str] = None  # Where to receive tokens
    output_place_id: Optional[str] = None  # Where to send tokens


@dataclass
class PatternResult:
    """
    Result of adding a pattern to a net.

    `metadata` is a free-form dict for patterns that expose more than the
    standard input/output ports — e.g. BoundedQueue exposes capacity and
    reject ports, Assembly exposes a slot-name-to-place-id map, Machine
    exposes its consume transition for downstream wiring.
    """

    interface: PatternInterface
    place_ids: List[str]
    transition_ids: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


class BasePattern(ABC):
    """
    Abstract base class for Petri Net patterns.

    Patterns are reusable building blocks that represent common
    constructs in queueing systems (generators, machines, queues, etc.).
    """

    tool_cursor_width: ClassVar[float] = 300.0
    tool_non_time_params: ClassVar[FrozenSet[str]] = frozenset()

    @property
    @abstractmethod
    def name(self) -> str:
        """Pattern type name."""
        pass

    @abstractmethod
    def apply(
        self,
        net: PetriNet,
        instance_name: str,
        x: float,
        y: float,
        **kwargs,
    ) -> PatternResult:
        """
        Apply this pattern to a Petri net.

        Args:
            net: The PetriNet to modify
            instance_name: Unique name for this pattern instance
            x, y: Base coordinates for placement
            **kwargs: Pattern-specific parameters

        Returns:
            PatternResult with interface points and created element IDs
        """
        pass
