"""Time-unit conversion shared by every agent-facing Petri Net tool.

Extracted from the three near-identical copies that used to live in
backend/src/mcp/tools/petri_tools.py, backend/src/services/agent/tools/
petri_tools.py, and backend/src/services/agent/nodes/tool_node.py. All
three grew the same `_TIME_FACTORS` table, the same `_s()` converter, and
the same "does this parameter name look like a duration" heuristic
independently; this module is the one copy every layer now calls into.
"""

from __future__ import annotations

import inspect
from typing import FrozenSet, Iterable

#: Recognized time-unit tokens, case-insensitive. Anything not listed here
#: is treated as seconds (factor 1.0), matching the lenient behavior every
#: prior copy of this table already had.
TIME_FACTORS: dict[str, float] = {
    "s": 1.0, "sec": 1.0,
    "min": 60.0, "m": 60.0,
    "h": 3600.0, "hr": 3600.0, "hour": 3600.0,
    "d": 86400.0, "day": 86400.0,
}

#: A parameter name is treated as time-valued if it ends with one of these
#: suffixes, or equals one outright once its leading underscore is stripped
#: (so "_deviation" also matches a bare "deviation" argument, etc.).
TIME_SUFFIXES = (
    "_time", "_duration", "timeout", "interval", "delay",
    "_deviation", "mean_time_between_failures", "mean_time_to_repair",
)

#: apply()'s boilerplate positional params: never time-shaped, never
#: tool-facing.
_NON_TIME_PARAMS = frozenset({"self", "net", "instance_name", "x", "y"})

#: The four time units every client-facing tool actually documents and
#: accepts (a curated subset of TIME_FACTORS' keys, which also carries a
#: few tolerant aliases like "sec"/"hr"/"day" that are accepted but never
#: advertised). Shared by catalog.py so the client-facing "choices" list for
#: every time_unit/deviation_unit parameter is built from one source.
CANONICAL_TIME_UNITS: tuple[str, ...] = ("s", "min", "h", "d")


def to_seconds(value: float, unit: str) -> float:
    """Convert *value*, expressed in *unit*, to seconds."""
    return value * TIME_FACTORS.get(unit.lower(), 1.0)


def echo_duration(seconds: float) -> str:
    """Render a duration in seconds alongside its value in min/h/d.

    Used to echo back what a caller's time_unit + value actually resolved
    to, so a human (or an LLM) can sanity-check the conversion.
    """
    if seconds <= 0:
        return f"{seconds:g}s"
    return (
        f"{seconds:g}s = {seconds / 60:g}min = "
        f"{seconds / 3600:g}h = {seconds / 86400:g}d"
    )


def echo_rate(interval_sec: float) -> str:
    """Render an inter-arrival interval as a rate in /s, /min, /h, /d."""
    if interval_sec <= 0:
        return "rate undefined (interval=0)"
    return (
        f"{1.0 / interval_sec:g}/s = {60.0 / interval_sec:g}/min = "
        f"{3600.0 / interval_sec:g}/h = {86400.0 / interval_sec:g}/d"
    )


def is_time_param_name(name: str, non_time: FrozenSet[str] = frozenset()) -> bool:
    """Whether *name* looks like a time-valued parameter by naming convention."""
    if name in non_time:
        return False
    return any(
        name.endswith(suffix) or name == suffix.lstrip("_")
        for suffix in TIME_SUFFIXES
    )


def detect_time_params(
    sig: inspect.Signature,
    non_time: FrozenSet[str] = frozenset(),
) -> list[str]:
    """Detect which parameters of *sig* represent time values.

    A parameter counts if its name matches `is_time_param_name` AND its
    annotation is float-shaped: bare `float`, `float | None`, or
    unannotated (so low-level/legacy signatures without type hints still
    get detected by name alone, matching every prior copy of this logic).
    """
    result = []
    for pname, param in sig.parameters.items():
        if pname in _NON_TIME_PARAMS:
            continue
        if not is_time_param_name(pname, non_time):
            continue
        ann = param.annotation
        if ann in (float, inspect.Parameter.empty) or ann is type(None):
            result.append(pname)
        elif hasattr(ann, "__args__") and float in ann.__args__:
            result.append(pname)
    return result


def pattern_time_params(pattern_name: str, sig: inspect.Signature) -> list[str]:
    """detect_time_params, but looking up *pattern_name*'s own exclusions.

    Both catalog.py's `_pattern_tool_spec` (building the client-facing
    schema from `apply()`'s signature) and operations.py's `op_add_pattern`
    (converting the same pattern's time params at call time, from the
    builder method's signature) need the exact same answer to "which
    params of this pattern are time-valued" -- including the pattern's own
    `tool_non_time_params` exclusions (see FinitePopulationQueuePattern's
    n_customers/channels, WIPControllerPattern's wip_limit). This is the one
    place that looks the pattern up in the registry and applies its
    exclusions, so the two call sites can never independently drift on it.
    """
    from src.domain.patterns.registry import get_registry

    pattern_cls = get_registry().get(pattern_name)
    non_time = pattern_cls.tool_non_time_params if pattern_cls is not None else frozenset()
    return detect_time_params(sig, non_time)


def unit_for_param(pname: str, time_unit: str, deviation_unit: str) -> str:
    """Pick the unit that applies to a given parameter name.

    `standard_deviation` follows `deviation_unit`; every other time
    parameter follows `time_unit`. This lets a caller say "interval=1 min,
    stdev=10 sec" without forcing both onto the same unit.
    """
    if pname == "standard_deviation":
        return deviation_unit
    return time_unit


def normalize_time_args(args: dict, time_params: Iterable[str]) -> dict:
    """Pop time_unit/deviation_unit from *args* and convert time params to seconds.

    Returns a NEW dict; *args* itself is left untouched. Only keys present
    in *args* AND listed in *time_params* AND numeric are converted; the
    "unit" keys are consumed either way (defaulting to "s").
    """
    working = dict(args)
    time_unit = working.pop("time_unit", "s")
    deviation_unit = working.pop("deviation_unit", None) or time_unit
    for pname in time_params:
        value = working.get(pname)
        if isinstance(value, (int, float)):
            unit = unit_for_param(pname, time_unit, deviation_unit)
            working[pname] = to_seconds(value, unit)
    return working
