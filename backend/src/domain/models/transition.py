"""Transition entity for Petri Net domain."""

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .types import DistributionType, Graphics


class Transition(BaseModel):
    """
    Transition in a Petri Net.

    Transitions represent events or actions. They fire when all input places
    have sufficient tokens. Supports timed transitions with various distributions.
    """

    id: str = Field(default_factory=lambda: f"t_{uuid.uuid4().hex[:6]}")
    name: str
    # ge=0, not ge=1: PetriObjModelPaint writes priority="0" as its own
    # default (and both the frontend and Python PNML importers deliberately
    # preserve an explicit 0 rather than treat it as unset -- see
    # pnml_importer.py's own comment on this), so a document that legally
    # states priority 0 must load. Conflict resolution (engine.py,
    # composed_engine.py) only ever compares priorities relationally
    # (sort/reverse, no special-casing of any particular value), so 0 needs
    # no extra handling there.
    priority: int = Field(default=1, ge=0, description="Firing priority (higher = first)")

    # Time parameters for timed Petri nets
    distribution: Optional[DistributionType] = Field(
        default=None, description="Time distribution type"
    )
    mean_delay: float = Field(default=0.0, ge=0.0, description="Mean delay time")
    standard_deviation: float = Field(
        default=0.0, ge=0.0, description="Standard deviation for NORM/UNIF"
    )

    # Probability for stochastic branching (0.0-1.0)
    # Used when multiple transitions compete for same token
    probability: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Firing probability for stochastic conflict resolution"
    )

    graphics: Graphics = Field(default_factory=Graphics)

    @field_validator("distribution", mode="before")
    @classmethod
    def normalize_distribution(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.lower()
        return v

    @model_validator(mode="after")
    def validate_distribution_params(self) -> "Transition":
        """
        Validate distribution parameters.

        Business rules:
        - NORM and UNIF distributions require standard_deviation > 0
        - EXP uses only mean_delay (rate = 1/mean)
        - DET uses only mean_delay (fixed time)
        """
        if self.distribution in [DistributionType.NORM, DistributionType.UNIF]:
            if self.standard_deviation <= 0:
                raise ValueError(
                    f"Distribution '{self.distribution.value}' requires "
                    f"standard_deviation > 0, got {self.standard_deviation}"
                )
        return self

    @property
    def is_timed(self) -> bool:
        """Check if this is a timed transition."""
        return self.distribution is not None or self.mean_delay > 0

    @property
    def is_immediate(self) -> bool:
        """Check if this is an immediate (instantaneous) transition."""
        return not self.is_timed
