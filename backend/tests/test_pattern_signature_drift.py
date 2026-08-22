"""CI gate against pattern signature drift across the four layers.

Each pattern flows through four entry points:
    1. agent tool   src/services/agent/tools/petri_tools.py
    2. MCP tool     src/mcp/tools/petri_tools.py
    3. builder      src/services/petri/builder.py    method add_<name>
    4. domain       src/domain/patterns/<x>.py        BasePattern.apply

Each layer must accept every parameter that flows in from the layer above.
The previous bug — `add_assembly(priority=...)` accepted by agent/MCP but
not by builder — slipped through because nothing checked this. These tests
catch any future drift at CI time.

We do not require *equality* of parameter sets (lower layers may have extra
internal kwargs) — only that every parameter reachable from a higher layer
is accepted by everything below.
"""

from __future__ import annotations

import inspect

import pytest

from src.domain.patterns.registry import get_registry
from src.services.petri.builder import PetriNetBuilder

_BUILDER_TO_DOMAIN_PATTERNS = [
    (f"add_{snake_name}", snake_name)
    for snake_name in get_registry()
]


def _builder_user_params(builder_method) -> set[str]:
    """Parameters a caller actually passes to a builder method (excluding self)."""
    sig = inspect.signature(builder_method)
    return {name for name in sig.parameters if name != "self"}


def _domain_apply_params(pattern_instance) -> set[str]:
    """Parameters the domain pattern's apply() declares.

    Some patterns use **kwargs and pull values via kwargs.get(...) — those
    are not visible in the signature, so we accept either style.
    """
    sig = inspect.signature(pattern_instance.apply)
    params = set(sig.parameters.keys())
    params -= {"self", "net", "instance_name", "x", "y", "kwargs"}
    return params


def _has_var_keyword(callable_) -> bool:
    sig = inspect.signature(callable_)
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())


@pytest.mark.parametrize("builder_method_name, snake_name", _BUILDER_TO_DOMAIN_PATTERNS)
def test_builder_does_not_pass_unknown_kwargs_to_domain(
    builder_method_name: str, snake_name: str
) -> None:
    """Every parameter the builder forwards must be accepted by the domain pattern.

    Heuristic: read the source of the builder method, find the keyword args
    it passes into pattern.apply(...), and check each name is either an
    explicit parameter on apply() or apply uses **kwargs.
    """
    builder = PetriNetBuilder()
    method = getattr(builder, builder_method_name)
    pattern = builder._patterns[snake_name]

    if _has_var_keyword(pattern.apply):
        return

    domain_params = _domain_apply_params(pattern)
    builder_params = _builder_user_params(method) - {"name"}

    overlap_unknown = builder_params - domain_params - {
        "name",
    }
    assert not overlap_unknown, (
        f"{builder_method_name}: builder declares {sorted(overlap_unknown)} "
        f"but domain pattern apply() does not accept them. Add them to "
        f"{type(pattern).__name__}.apply or remove from builder."
    )


def test_all_registry_patterns_have_builder_methods() -> None:
    """Every registered pattern must have a corresponding add_X method on the builder."""
    builder = PetriNetBuilder()
    for snake_name in get_registry():
        method_name = f"add_{snake_name}"
        assert hasattr(builder, method_name), (
            f"Pattern '{snake_name}' is registered but PetriNetBuilder "
            f"has no '{method_name}' method."
        )


def test_assembly_priority_propagates() -> None:
    """Specific regression for the diploma bug: priority must reach the domain."""
    builder = PetriNetBuilder()
    result = builder.add_assembly("A", inputs=["X", "Y"], priority=7)
    t = builder.net.get_transition(result.transition_ids[0])
    assert t.priority == 7


def test_priority_choice_external_param_name() -> None:
    """Public API param name must match across all layers (no inline rename)."""
    sig = inspect.signature(PetriNetBuilder.add_priority_choice)
    assert "resource_place_ids" in sig.parameters
    assert "resource_requirements" not in sig.parameters

    from src.domain.patterns import PriorityChoicePattern
    pc_sig = inspect.signature(PriorityChoicePattern().apply)
    assert "resource_place_ids" in pc_sig.parameters
    assert "resource_requirements" not in pc_sig.parameters


def test_assembly_inputs_param_name() -> None:
    """Assembly's slot parameter is `inputs` everywhere — no `sources` drift."""
    sig = inspect.signature(PetriNetBuilder.add_assembly)
    assert "inputs" in sig.parameters
    assert "sources" not in sig.parameters


# ---------------------------------------------------------------------------
# Catalog-layer coverage (phase 1, part E): the agent_toolkit catalog is a
# FIFTH layer alongside agent tool / MCP tool / builder / domain above, and
# it is built directly from apply()'s own signature (for auto-generated
# tools) or from an op_* function's signature (for hand-written ones). This
# is the drift gate for that layer specifically.
# ---------------------------------------------------------------------------

from src.services.petri.agent_toolkit.catalog import (  # noqa: E402
    EXPLICIT_PATTERN_NAMES,
    build_catalog,
)


@pytest.mark.parametrize("snake_name", sorted(get_registry()))
def test_catalog_pattern_spec_params_match_apply_signature(snake_name: str) -> None:
    """For every registry pattern NOT hand-written, ToolSpec.params ==
    apply()'s own params (minus net/instance_name/x/y, plus synthesized
    time_unit/deviation_unit when apply() has timed params).
    """
    if snake_name in EXPLICIT_PATTERN_NAMES:
        pytest.skip(f"'{snake_name}' has a hand-written op_*, covered by "
                    "test_catalog_explicit_tool_params_match_operation_signature")

    pattern_cls = get_registry()[snake_name]
    sig = inspect.signature(pattern_cls().apply)
    apply_params = {
        pname for pname, param in sig.parameters.items()
        if pname not in ("self", "net", "instance_name", "x", "y")
        and param.kind != inspect.Parameter.VAR_KEYWORD
    }

    spec = build_catalog()[f"add_{snake_name}"]
    spec_params = {p.name for p in spec.params} - {"name", "time_unit", "deviation_unit"}

    assert spec_params == apply_params, (
        f"add_{snake_name}: ToolSpec params {sorted(spec_params)} != "
        f"apply() params {sorted(apply_params)}"
    )


def test_catalog_explicit_tool_params_match_operation_signature() -> None:
    """Every hand-written ToolSpec's params come straight from its op_*
    function's own signature; this is really a test of the introspection
    plumbing (_spec_from_operation), not of any one tool's business logic.
    """
    from src.services.petri.agent_toolkit.catalog import _EXPLICIT_OPERATIONS

    catalog = build_catalog()
    for tool_name, op_func in _EXPLICIT_OPERATIONS.items():
        op_sig = inspect.signature(op_func)
        expected = {
            pname for pname, param in op_sig.parameters.items()
            if pname != "session" and param.kind != inspect.Parameter.VAR_KEYWORD
        }
        spec_params = {p.name for p in catalog[tool_name].params}
        assert spec_params == expected, (
            f"{tool_name}: ToolSpec params {sorted(spec_params)} != "
            f"op_* signature params {sorted(expected)}"
        )


def test_catalog_explicit_names_are_a_superset_of_builder_explicit_methods() -> None:
    """The catalog's explicit-name list and the builder's own _EXPLICIT_METHODS
    are two independently hand-maintained "which patterns need custom code"
    lists; this is the cross-check the phase-1 contract asks for.

    They are not required to be EQUAL: "controller" is hand-written at the
    catalog/tool layer (its op_add_controller deliberately skips
    auto_connect/set_last_output, unlike the generic pattern op) even
    though its apply() signature is now clean enough that the builder
    installs a fully generic method for it (services/petri/builder.py's
    _install_builder_methods). Every pattern the BUILDER hand-writes a
    method for, though, must also be hand-written at the catalog layer:
    that direction has no legitimate exception, so it is checked as a
    strict subset relationship.
    """
    from src.services.petri.builder import _EXPLICIT_METHODS as builder_explicit

    assert builder_explicit <= EXPLICIT_PATTERN_NAMES, (
        f"Builder hand-writes {sorted(builder_explicit - EXPLICIT_PATTERN_NAMES)} "
        f"but the catalog treats them as auto-generated."
    )
    # Document the one known, deliberate extra rather than leaving it silent.
    extra = EXPLICIT_PATTERN_NAMES - builder_explicit
    assert extra == {"controller"}, (
        f"Catalog has unexpected extra hand-written pattern(s) vs the "
        f"builder: {sorted(extra - {'controller'})}. If this is deliberate, "
        f"extend this assertion with a comment explaining why."
    )
