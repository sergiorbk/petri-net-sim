"""Arc entity for Petri Net domain."""

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ArcType(str, Enum):
    """Arc types in Petri nets."""

    NORMAL = "normal"  # Standard arc
    INHIBITOR = "inhibitor"  # Fires only if place is empty
    READ = "read"  # Test arc (doesn't consume tokens)


class Arc(BaseModel):
    """
    Arc (edge) connecting places and transitions in a Petri Net.

    Arcs define the flow relation. They can only connect:
    - Place -> Transition (input arc)
    - Transition -> Place (output arc)

    Arcs cannot connect two places or two transitions directly.
    """

    id: str = Field(default_factory=lambda: f"arc_{uuid.uuid4().hex[:6]}")
    source_id: str = Field(..., description="ID of source node (place or transition)")
    target_id: str = Field(..., description="ID of target node (place or transition)")
    weight: int = Field(default=1, ge=1, description="Arc weight (tokens consumed/produced)")
    arc_type: ArcType = Field(default=ArcType.NORMAL, description="Type of arc")

    @field_validator("arc_type", mode="before")
    @classmethod
    def normalize_arc_type(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.lower()
        return v

    @property
    def is_inhibitor(self) -> bool:
        """Check if this is an inhibitor arc."""
        return self.arc_type == ArcType.INHIBITOR

    @property
    def is_read_arc(self) -> bool:
        """Check if this is a read (test) arc."""
        return self.arc_type == ArcType.READ
