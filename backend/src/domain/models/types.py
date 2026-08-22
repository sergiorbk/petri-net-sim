"""Base types and value objects for Petri Net domain."""

from enum import Enum

from pydantic import BaseModel


class DistributionType(str, Enum):
    """Time distribution types for timed Petri nets (PetriObjModel compatible)."""

    EXP = "exp"  # Exponential distribution
    NORM = "norm"  # Normal distribution
    UNIF = "unif"  # Uniform distribution
    DET = "det"  # Deterministic (fixed delay)


class Graphics(BaseModel):
    """Value object for graphical coordinates in PNML."""

    x: float = 0.0
    y: float = 0.0
