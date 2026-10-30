"""ToolSpec catalog: every agent-facing Petri Net tool, described once.

Two sources feed the catalog:

- explicit specs, one per hand-written operation in operations.py
  (`_EXPLICIT_OPERATIONS`), for tools whose params don't fit the generic
  pattern-introspection shape (rate/interval duality, list/dict params,
  CRUD, wiring helpers, spatial ops, export/simulate/status). Each spec is
  built straight from its op_* function's own `inspect.signature` and
  docstring, so the function is the one source of truth for both its
  behavior and its schema.
- ONE pattern-introspection function, `_pattern_tool_spec`, that builds a
  ToolSpec from a registered pattern's `apply()` signature for every
  pattern NOT in the explicit set: the single replacement for the old
  MCP `_make_mcp_tool` and the chat agent's `_make_agent_tool`, including
  their time-param detection, their DistributionType/RoutingStrategy ->
  str translation, and (new, per A2) merging the pattern class's
  docstring with apply()'s own Args section so per-parameter semantics
  are no longer invisible on the 20 auto-generated tools.
"""

from __future__ import annotations

import functools
import inspect
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal

from src.domain import ArcType, DistributionType, RoutingStrategy
from src.domain.patterns.base import BasePattern
from src.domain.patterns.registry import get_registry
from src.services.petri.agent_toolkit import operations as ops
from src.services.petri.agent_toolkit import time_units as tu
from src.services.petri.agent_toolkit.errors import ToolError


@dataclass(frozen=True)
class ToolParam:
    """One parameter of a ToolSpec, as an agent-facing client would see it.

    `choices`, when set, is the closed list of string values this parameter
    accepts (mirrors what used to be a `Literal[...]` annotation on the old
    hand-written per-adapter tool signatures before both were generated
    from this one catalog). `type` stays a plain `str` for these params --
    see `_tool_annotation` -- so `choices` is the only place the narrowing
    survives; `effective_type()` below is what turns it back into a real
    `Literal[...]` for an adapter's own schema.
    """

    name: str
    type: Any
    default: Any = inspect.Parameter.empty
    description: str = ""
    choices: tuple[str, ...] | None = None

    @property
    def required(self) -> bool:
        return self.default is inspect.Parameter.empty


@dataclass(frozen=True)
class ToolSpec:
    """Everything an adapter needs to register or describe one tool.

    `operation` is always called as `operation(session, **kwargs)`: every
    op_* function in operations.py (and the functools.partial bindings
    _pattern_tool_spec produces) takes `session` first and every other
    param by name.
    """

    name: str
    description: str
    params: tuple[ToolParam, ...]
    operation: Callable[..., "str | ToolError"]

    def filter_kwargs(self, kwargs: dict) -> tuple[dict, list[str]]:
        """Split *kwargs* into (kwargs this spec declares, everything else).

        Shared by both adapters' dispatch layer (MCP's `_build_tool_fn` and
        chat's `tool_node`) so a hallucinated parameter name never reaches
        `self.operation(session, **kwargs)` raw -- that call is plain
        Python keyword-argument binding, and an unrecognized key there is a
        TypeError naming the internal op_* function, not a ToolError. The
        dropped names come back sorted so a caller can report them in a
        stable, deterministic order.
        """
        declared = {p.name for p in self.params}
        known = {k: v for k, v in kwargs.items() if k in declared}
        dropped = sorted(k for k in kwargs if k not in declared)
        return known, dropped


def effective_type(param: ToolParam) -> Any:
    """The type annotation a client-facing schema should use for *param*.

    Plain `param.type` for most parameters. For a parameter carrying
    `choices`, a dynamic `Literal[...]` built from them instead -- unioned
    with `None` when the parameter is optional and defaults to `None`, so
    an omitted value still validates. Shared by both adapters (MCP's
    `_build_tool_fn` and the chat StructuredTool builder) so the None-
    handling rule lives in exactly one place instead of being reimplemented
    twice with a chance of disagreeing on it.
    """
    if not param.choices:
        return param.type
    literal = Literal[param.choices]
    if param.default is None and not param.required:
        return literal | None
    return literal


# ---------------------------------------------------------------------------
# Domain-annotation -> tool-facing-annotation translation
# ---------------------------------------------------------------------------

def _tool_annotation(ann: Any) -> Any:
    """Map a domain annotation to a tool-facing one.

    DistributionType/RoutingStrategy are internal enums; a calling agent
    sees their string value instead ("exp", "probability", ...).
    """
    if ann is DistributionType or ann is RoutingStrategy:
        return str
    if ann is inspect.Parameter.empty:
        return Any
    return ann


def _tool_default(default: Any) -> Any:
    """Map a domain default to a tool-facing one (enum member -> its .value)."""
    if isinstance(default, (DistributionType, RoutingStrategy)):
        return default.value
    return default


# ---------------------------------------------------------------------------
# choices: the client-facing "which strings does this parameter accept"
# list, populated by parameter NAME rather than by domain annotation, since
# every hand-written op_* function in operations.py already declares its
# enum-like params as plain `str` (see _EXPLICIT_OPERATIONS) -- by the time
# either spec-building path sees them, the DistributionType/RoutingStrategy
# annotation is long gone. Naming convention is the one signal both paths
# (explicit ops and pattern introspection) share.
# ---------------------------------------------------------------------------

_DISTRIBUTION_CHOICES: tuple[str, ...] = tuple(d.value for d in DistributionType)
_STRATEGY_CHOICES: tuple[str, ...] = tuple(s.value for s in RoutingStrategy)
_ARC_TYPE_CHOICES: tuple[str, ...] = tuple(a.value for a in ArcType)
_ELEMENT_TYPE_CHOICES: tuple[str, ...] = ("place", "transition")
#: link_objects's own link_type: NOT the domain's full LinkType enum --
#: "placeToTransition" is deliberately excluded here, since link_objects
#: refuses to create one at runtime too (see operations.py's
#: _PLACE_TO_TRANSITION_RETIRED); a caller sees only the two link types it
#: can actually create.
_LINK_TYPE_CHOICES: tuple[str, ...] = ("placeFusion", "transitionToPlace")
_LAYOUT_DIRECTION_CHOICES: tuple[str, ...] = ("LR", "TB")
_COMPASS_DIRECTION_CHOICES: tuple[str, ...] = ("above", "below", "left", "right")

#: The two tools whose own "direction" parameter picks a layout flow
#: ("LR"/"TB"); every other "direction" parameter (find_free_position) is a
#: compass direction relative to an anchor element instead -- same name,
#: different meaning, so this is the one place that disambiguates by tool.
_LAYOUT_DIRECTION_TOOLS: frozenset[str] = frozenset({"auto_layout", "set_layout_direction"})


def _choices_for_param(tool_name: str, pname: str) -> tuple[str, ...] | None:
    """Pick the client-facing enum choice list for one parameter, by name.

    Covers every former `Literal[...]` on the old hand-written per-adapter
    tool signatures (distribution, every "*_distribution" variant, strategy,
    arc_type, time_unit, deviation_unit, direction, element_type), used by
    both `_spec_from_operation` and `_pattern_tool_spec` so a parameter's
    narrowing doesn't depend on which of the two spec-building paths built
    it.
    """
    if pname == "strategy":
        return _STRATEGY_CHOICES
    if pname == "distribution" or pname.endswith("_distribution"):
        return _DISTRIBUTION_CHOICES
    if pname == "arc_type":
        return _ARC_TYPE_CHOICES
    if pname == "link_type":
        return _LINK_TYPE_CHOICES
    if pname in ("time_unit", "deviation_unit"):
        return tu.CANONICAL_TIME_UNITS
    if pname == "element_type":
        return _ELEMENT_TYPE_CHOICES
    if pname == "direction":
        return (
            _LAYOUT_DIRECTION_CHOICES
            if tool_name in _LAYOUT_DIRECTION_TOOLS
            else _COMPASS_DIRECTION_CHOICES
        )
    return None


# ---------------------------------------------------------------------------
# A2: doc merge: class docstring (structure/use-cases) + apply()'s Args
# ---------------------------------------------------------------------------

#: Matches one Google-style "Args:" entry line, e.g. "pname: description" or
#: the older "pname (type): description" a few pattern docstrings still use.
_ARG_LINE_RE = re.compile(r"^(\w+)\s*(?:\([^)]*\))?:\s*(.*)$")
_SECTION_HEADERS = ("Returns:", "Raises:", "Yields:")
_DOC_BOILERPLATE_PARAMS = ("net", "instance_name", "x", "y", "kwargs")


def _extract_param_docs(doc: str | None) -> dict[str, str]:
    """Pull {param_name: description} out of a Google-style Args: section.

    Tolerant of wrapped continuation lines and of the "(type)" suffix a few
    pattern docstrings still carry after the parameter name.
    """
    if not doc:
        return {}
    lines = inspect.cleandoc(doc).splitlines()
    result: dict[str, str] = {}
    current: str | None = None
    in_args = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped == "Args:":
            in_args = True
            current = None
            continue
        if not in_args:
            continue
        if stripped in _SECTION_HEADERS:
            break
        if not raw_line.startswith(" "):
            break
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        match = _ARG_LINE_RE.match(stripped)
        if match and indent <= 4:
            current = match.group(1)
            result[current] = match.group(2)
        elif current and stripped:
            result[current] += " " + stripped
    for boilerplate in _DOC_BOILERPLATE_PARAMS:
        result.pop(boilerplate, None)
    return result


def _merge_pattern_doc(
    pattern_cls: type[BasePattern],
    param_docs: dict[str, str],
    param_names: list[str],
) -> str:
    """A2: merge the pattern CLASS docstring with apply()'s own Args section.

    The class docstring carries the structure diagram and use cases; the
    per-parameter semantics only ever lived in apply()'s own docstring.
    The old auto-generation (_make_mcp_tool / _make_agent_tool) surfaced
    only the class docstring for auto-generated tools, leaving every
    parameter described by nothing but its bare name/type/default.
    """
    class_doc = inspect.cleandoc(pattern_cls.__doc__ or "")
    if not param_docs:
        return class_doc
    lines = ["", "Args:"]
    for pname in param_names:
        if pname in param_docs:
            lines.append(f"    {pname}: {param_docs[pname]}")
    if len(lines) <= 2:
        return class_doc
    return class_doc + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Explicit specs: one hand-written op_* function per entry
# ---------------------------------------------------------------------------

#: tool name -> the operations.py function implementing it. This is the one
#: place that decides which tools are hand-written vs pattern-introspected;
#: cross-checked against the builder's own _EXPLICIT_METHODS by
#: test_pattern_signature_drift.py (see that test for why the two lists
#: aren't identical: "controller" is hand-written here for its wiring
#: behavior (no auto_connect/set_last_output) even though its apply()
#: signature is now clean enough that the builder installs a generic
#: method for it).
_EXPLICIT_OPERATIONS: dict[str, Callable[..., Any]] = {
    "create_network": ops.op_create_network,
    "add_generator": ops.op_add_generator,
    "add_machine": ops.op_add_machine,
    "add_controller": ops.op_add_controller,
    "add_assembly": ops.op_add_assembly,
    "add_router": ops.op_add_router,
    "add_conveyor": ops.op_add_conveyor,
    "add_conveyor_line": ops.op_add_conveyor_line,
    "add_conveyor_workstation": ops.op_add_conveyor_workstation,
    "connect_workstation_bypass": ops.op_connect_workstation_bypass,
    "connect_return_loop": ops.op_connect_return_loop,
    "add_transport_agent": ops.op_add_transport_agent,
    "add_priority_choice": ops.op_add_priority_choice,
    "add_merge": ops.op_add_merge,
    "add_duplicate": ops.op_add_duplicate,
    "add_multi_resource": ops.op_add_multi_resource,
    "add_nonstationary_generator": ops.op_add_nonstationary_generator,
    "connect_bounded_consumer": ops.op_connect_bounded_consumer,
    "add_fork_join": ops.op_add_fork_join,
    "connect_blocking_consumer": ops.op_connect_blocking_consumer,
    "add_resource_set": ops.op_add_resource_set,
    "connect_wip_return": ops.op_connect_wip_return,
    "connect_schedule_gate": ops.op_connect_schedule_gate,
    "connect_patterns": ops.op_connect_patterns,
    "get_network_status": ops.op_get_network_status,
    "create_object": ops.op_create_object,
    "set_active_object": ops.op_set_active_object,
    "list_objects": ops.op_list_objects,
    "rename_object": ops.op_rename_object,
    "remove_object": ops.op_remove_object,
    "move_elements_to_object": ops.op_move_elements_to_object,
    "link_objects": ops.op_link_objects,
    "list_links": ops.op_list_links,
    "remove_link": ops.op_remove_link,
    "validate_model": ops.op_validate_model,
    "add_place": ops.op_add_place,
    "add_transition": ops.op_add_transition,
    "add_arc": ops.op_add_arc,
    "validate_net": ops.op_validate_net,
    "modify_place": ops.op_modify_place,
    "modify_transition": ops.op_modify_transition,
    "modify_arc": ops.op_modify_arc,
    "remove_place": ops.op_remove_place,
    "remove_transition": ops.op_remove_transition,
    "remove_arc": ops.op_remove_arc,
    "list_elements": ops.op_list_elements,
    "set_positions": ops.op_set_positions,
    "find_free_position": ops.op_find_free_position,
    "find_elements": ops.op_find_elements,
    "get_network_bounds": ops.op_get_network_bounds,
    "move_elements_by": ops.op_move_elements_by,
    "auto_layout": ops.op_auto_layout,
    "set_layout_direction": ops.op_set_layout_direction,
    "arrange_patterns": ops.op_arrange_patterns,
    "list_pattern_instances": ops.op_list_pattern_instances,
    "get_pattern_bounds": ops.op_get_pattern_bounds,
    "optimize_network": ops.op_optimize_network,
    "export_pnml": ops.op_export_pnml,
    "export_image": ops.op_export_image,
    "export_training_data": ops.op_export_training_data,
    "open_training_bundle": ops.op_open_training_bundle,
    "inspect_training_bundle": ops.op_inspect_training_bundle,
    "compare_training_revisions": ops.op_compare_training_revisions,
    "training_bundle_image": ops.op_training_bundle_image,
    "export_training_review": ops.op_export_training_review,
    "run_training_simulation": ops.op_run_training_simulation,
    "import_pnml": ops.op_import_pnml,
    "run_simulation": ops.op_run_simulation,
    "get_simulation_results": ops.op_get_simulation_results,
}

#: Every hand-written tool name. Defined here only; nothing else
#: hand-maintains a second copy of this list.
EXPLICIT_TOOL_NAMES: frozenset[str] = frozenset(_EXPLICIT_OPERATIONS)

#: The subset of EXPLICIT_TOOL_NAMES that add a registered pattern (i.e.
#: "add_X" where X is a key in the pattern registry): the catalog-layer
#: analogue of the builder's own _EXPLICIT_METHODS.
EXPLICIT_PATTERN_NAMES: frozenset[str] = frozenset(
    name.removeprefix("add_")
    for name in EXPLICIT_TOOL_NAMES
    if name.startswith("add_") and name.removeprefix("add_") in get_registry()
)


def _spec_from_operation(tool_name: str, op_func: Callable[..., Any]) -> ToolSpec:
    """Build a ToolSpec straight from a hand-written op_* function.

    `inspect.signature` follows `functools.wraps`' `__wrapped__` link
    automatically, so this sees the operation's real parameters (minus
    `session`) and `op_func.__doc__` is the original docstring: the
    function itself is the one source of truth for its own schema, not a
    second hand-maintained param list living here.
    """
    sig = inspect.signature(op_func)
    params: list[ToolParam] = []
    for pname, param in sig.parameters.items():
        if pname == "session":
            continue
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            continue
        params.append(ToolParam(
            name=pname,
            type=_tool_annotation(param.annotation),
            default=_tool_default(param.default),
            choices=_choices_for_param(tool_name, pname),
        ))
    description = inspect.cleandoc(op_func.__doc__ or "")
    return ToolSpec(name=tool_name, description=description, params=tuple(params), operation=op_func)


# ---------------------------------------------------------------------------
# Pattern-introspection spec: the single replacement for
# _make_mcp_tool / _make_agent_tool
# ---------------------------------------------------------------------------

def _pattern_tool_spec(pattern_name: str, pattern_cls: type[BasePattern]) -> ToolSpec:
    """Build a ToolSpec for one registry pattern via apply() introspection."""
    pattern_instance = pattern_cls()
    sig = inspect.signature(pattern_instance.apply)
    time_params = tu.pattern_time_params(pattern_name, sig)
    param_docs = _extract_param_docs(pattern_cls.apply.__doc__)
    tool_name = f"add_{pattern_name}"

    params: list[ToolParam] = [
        ToolParam(name="name", type=str, description="Instance name for this pattern."),
    ]
    for pname, param in sig.parameters.items():
        if pname in ("self", "net", "instance_name", "x", "y"):
            continue
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            continue
        params.append(ToolParam(
            name=pname,
            type=_tool_annotation(param.annotation),
            default=_tool_default(param.default),
            description=param_docs.get(pname, ""),
            choices=_choices_for_param(tool_name, pname),
        ))

    if time_params:
        params.append(ToolParam(
            name="time_unit", type=str, default="s",
            description="Unit for time values: 's', 'min', 'h', or 'd'.",
            choices=tu.CANONICAL_TIME_UNITS,
        ))
        if "standard_deviation" in time_params:
            params.append(ToolParam(
                name="deviation_unit", type=str, default=None,
                description="Unit for standard_deviation. Defaults to time_unit if omitted.",
                choices=tu.CANONICAL_TIME_UNITS,
            ))

    description = _merge_pattern_doc(
        pattern_cls, param_docs, [p.name for p in params if p.name != "name"]
    )

    operation = functools.partial(ops.op_add_pattern, pattern_name=pattern_name)

    return ToolSpec(
        name=tool_name,
        description=description,
        params=tuple(params),
        operation=operation,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_catalog() -> dict[str, ToolSpec]:
    """Build the full tool catalog: every explicit spec plus one per
    registry pattern not already covered by an explicit spec.

    Returns a fresh dict on every call (mirroring get_registry()'s own
    snapshot-per-call convention): cheap enough to not bother caching,
    and it keeps callers from accidentally mutating shared state.
    """
    catalog: dict[str, ToolSpec] = {}
    for tool_name, op_func in _EXPLICIT_OPERATIONS.items():
        catalog[tool_name] = _spec_from_operation(tool_name, op_func)

    for pattern_name, pattern_cls in get_registry().items():
        if pattern_name in EXPLICIT_PATTERN_NAMES:
            continue
        spec = _pattern_tool_spec(pattern_name, pattern_cls)
        catalog[spec.name] = spec

    return catalog


def list_tool_names() -> list[str]:
    """Every tool name the catalog currently produces, sorted."""
    return sorted(build_catalog())
