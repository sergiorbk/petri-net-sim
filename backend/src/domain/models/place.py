"""Place entity for Petri Net domain."""

import uuid
from typing import Optional

from pydantic import BaseModel, Field

from .types import Graphics


class Place(BaseModel):
    """
    Place (position) in a Petri Net.

    Places hold tokens and represent states or conditions in the modeled system.
    """

    id: str = Field(default_factory=lambda: f"p_{uuid.uuid4().hex[:6]}")
    name: str
    tokens: int = Field(default=0, ge=0, description="Number of tokens (marking)")
    # Semantic tag for places with special meaning to optimizer/simulator.
    # Currently used: "throughput" — Terminator's counter place; protected
    # from fusion by the optimizer and surfaced as a TerminatorStatistics
    # entry whose total_consumed equals this place's final marking.
    tag: Optional[str] = Field(
        default=None,
        description="Semantic tag (e.g. 'throughput') consumed by optimizer/simulator",
    )
    graphics: Graphics = Field(default_factory=Graphics)

    def add_tokens(self, count: int) -> None:
        """Add tokens to this place."""
        if count < 0:
            raise ValueError("Cannot add negative tokens")
        self.tokens += count

    def remove_tokens(self, count: int) -> None:
        """Remove tokens from this place."""
        if count < 0:
            raise ValueError("Cannot remove negative tokens")
        if self.tokens < count:
            raise ValueError(
                f"Insufficient tokens in place '{self.name}': "
                f"has {self.tokens}, requested {count}"
            )
        self.tokens -= count

    def has_tokens(self, count: int = 1) -> bool:
        """Check if place has at least 'count' tokens."""
        return self.tokens >= count
