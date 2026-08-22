"""Pattern auto-registration registry.

The registry is the single source of truth for all available patterns.
Each pattern class decorated with ``@register_pattern`` is discovered
at import time and made available to all downstream layers (builder,
agent tools, MCP tools, dispatcher) without manual wiring.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BasePattern

_REGISTRY: dict[str, type[BasePattern]] = {}


def _to_snake(name: str) -> str:
    """Convert CamelCase to snake_case.

    >>> _to_snake("QualityCheck")
    'quality_check'
    >>> _to_snake("ConveyorWorkstation")
    'conveyor_workstation'
    """
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def register_pattern(cls: type[BasePattern]) -> type[BasePattern]:
    """Class decorator that registers a pattern in the global registry."""
    snake = _to_snake(cls.__name__.removesuffix("Pattern"))
    _REGISTRY[snake] = cls
    return cls


def get_registry() -> dict[str, type[BasePattern]]:
    """Return a snapshot of the current registry (snake_name -> class)."""
    return dict(_REGISTRY)
