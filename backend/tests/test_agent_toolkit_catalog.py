"""Unit tests for src/services/petri/agent_toolkit/catalog.py.

Covers ToolSpec/ToolParam shape, the explicit/pattern-introspection split,
the A1 patterns now exposing full schemas (buffer/terminator/quality_check/
feedback_loop, plus the four stragglers fixed alongside them), and the A2
doc merge (class docstring + apply()'s own Args section).
"""

from __future__ import annotations

import inspect

import pytest

from src.domain.patterns.registry import get_registry
from src.services.petri.agent_toolkit.catalog import (
    EXPLICIT_PATTERN_NAMES,
    EXPLICIT_TOOL_NAMES,
    ToolParam,
    ToolSpec,
    build_catalog,
    effective_type,
    list_tool_names,
)


class TestToolParam:
    def test_required_when_no_default(self):
        p = ToolParam(name="name", type=str)
        assert p.required is True

    def test_not_required_with_default(self):
        p = ToolParam(name="tokens", type=int, default=0)
        assert p.required is False

    def test_none_is_a_real_default_not_required(self):
        """default=None means 'optional, defaults to None', not 'no default'."""
        p = ToolParam(name="tag", type=str, default=None)
        assert p.required is False
        assert p.default is None


class TestBuildCatalog:
    def test_returns_dict_of_toolspec(self):
        catalog = build_catalog()
        assert catalog
        assert all(isinstance(spec, ToolSpec) for spec in catalog.values())

    def test_every_spec_name_matches_its_key(self):
        catalog = build_catalog()
        for key, spec in catalog.items():
            assert key == spec.name

    def test_every_spec_has_a_description(self):
        catalog = build_catalog()
        empty = [name for name, spec in catalog.items() if not spec.description.strip()]
        assert empty == []

    def test_every_spec_operation_is_callable(self):
        catalog = build_catalog()
        assert all(callable(spec.operation) for spec in catalog.values())

    def test_fresh_dict_each_call(self):
        """build_catalog() returns a new dict every call, like get_registry()."""
        first = build_catalog()
        first["add_generator"] = None  # type: ignore[assignment]
        second = build_catalog()
        assert second["add_generator"] is not None

    def test_covers_every_registered_pattern(self):
        catalog = build_catalog()
        for pattern_name in get_registry():
            assert f"add_{pattern_name}" in catalog, (
                f"No tool spec for registered pattern '{pattern_name}'"
            )

    def test_covers_every_explicit_tool_name(self):
        catalog = build_catalog()
        for tool_name in EXPLICIT_TOOL_NAMES:
            assert tool_name in catalog

    def test_pattern_specs_come_from_exactly_one_source(self):
        """Every add_<pattern> tool is either hand-written (explicit) or
        pattern-introspected (generic op_add_pattern via functools.partial)
        -- never neither, and the two routes never overlap.
        """
        import functools

        catalog = build_catalog()
        for pattern_name in get_registry():
            tool_name = f"add_{pattern_name}"
            assert tool_name in catalog
            spec = catalog[tool_name]
            is_generic = isinstance(spec.operation, functools.partial)
            assert is_generic == (pattern_name not in EXPLICIT_PATTERN_NAMES)


class TestExplicitToolNames:
    def test_no_duplicates_hiding_behind_dict_keys(self):
        # EXPLICIT_TOOL_NAMES is a frozenset built from a dict -- this just
        # documents the invariant that every entry is a distinct tool name.
        assert len(EXPLICIT_TOOL_NAMES) == len(set(EXPLICIT_TOOL_NAMES))

    def test_known_hand_written_tools_present(self):
        for name in (
            "create_network", "add_generator", "add_machine", "connect_patterns",
            "run_simulation", "get_simulation_results", "export_pnml",
            "optimize_network", "validate_net",
        ):
            assert name in EXPLICIT_TOOL_NAMES

    def test_explicit_pattern_names_are_all_real_patterns(self):
        registry = get_registry()
        assert EXPLICIT_PATTERN_NAMES
        for pname in EXPLICIT_PATTERN_NAMES:
            assert pname in registry

    def test_controller_is_the_one_documented_gap_vs_builder(self):
        """See catalog.py's _EXPLICIT_OPERATIONS docstring: add_controller is
        hand-written (no auto_connect/set_last_output) even though its
        apply() signature is clean enough for the generic builder method.
        """
        assert "controller" in EXPLICIT_PATTERN_NAMES


class TestListToolNames:
    def test_sorted_and_matches_catalog_keys(self):
        names = list_tool_names()
        assert names == sorted(names)
        assert set(names) == set(build_catalog())


class TestA1PatternsExposeFullSchemas:
    """The four contract-listed patterns, plus the four stragglers found by
    the same audit, used to declare apply(net, instance_name, x, y,
    **kwargs), so every generated ToolSpec for them had ONLY a `name` param.
    """

    @pytest.mark.parametrize(
        "tool_name, expected_params",
        [
            ("add_buffer", {"initial_tokens", "capacity"}),
            ("add_terminator", {"time_to_leave", "distribution"}),
            (
                "add_quality_check",
                {"inspection_time", "distribution", "pass_probability", "pass_name", "fail_name"},
            ),
            (
                "add_feedback_loop",
                {"processing_time", "rework_time", "distribution", "max_reworks"},
            ),
        ],
    )
    def test_previously_swallowed_params_now_visible(self, tool_name, expected_params):
        catalog = build_catalog()
        spec = catalog[tool_name]
        param_names = {p.name for p in spec.params}
        assert expected_params <= param_names, (
            f"{tool_name}: expected {expected_params} to be visible, "
            f"got {param_names}"
        )

    def test_buffer_defaults_match_original_kwargs_get_defaults(self):
        spec = build_catalog()["add_buffer"]
        by_name = {p.name: p for p in spec.params}
        assert by_name["initial_tokens"].default == 0
        assert by_name["capacity"].default is None

    def test_quality_check_defaults_match_original_kwargs_get_defaults(self):
        spec = build_catalog()["add_quality_check"]
        by_name = {p.name: p for p in spec.params}
        assert by_name["inspection_time"].default == 1.0
        assert by_name["distribution"].default == "det"
        assert by_name["pass_probability"].default == 0.9
        assert by_name["pass_name"].default == "Passed"
        assert by_name["fail_name"].default == "Failed"


class TestA2DocMerge:
    """Auto-generated tool descriptions must include apply()'s own Args
    section, not just the pattern class's structure/use-case prose.
    """

    def test_buffer_description_has_class_prose_and_args(self):
        spec = build_catalog()["add_buffer"]
        assert "Buffer" in spec.description
        assert "Args:" in spec.description
        assert "initial_tokens" in spec.description

    def test_quality_check_description_documents_every_param(self):
        spec = build_catalog()["add_quality_check"]
        for pname in ("inspection_time", "pass_probability", "pass_name", "fail_name"):
            assert pname in spec.description

    def test_boilerplate_params_never_leak_into_the_merged_doc(self):
        for tool_name in ("add_buffer", "add_wip_controller", "add_breakdown"):
            spec = build_catalog()[tool_name]
            args_section = spec.description.split("Args:")[-1]
            for boilerplate in ("net:", "instance_name:", "x, y:"):
                assert boilerplate not in args_section

    def test_pattern_with_no_extra_params_keeps_bare_class_doc(self):
        """A pattern whose only param is `name` (none exist today, but the
        merge helper must degrade gracefully) shouldn't grow a stray empty
        'Args:' section."""
        from src.services.petri.agent_toolkit.catalog import _merge_pattern_doc

        class Dummy:
            __doc__ = "Dummy pattern.\n\nDoes nothing."

        merged = _merge_pattern_doc(Dummy, {}, [])
        assert merged == "Dummy pattern.\n\nDoes nothing."
        assert "Args:" not in merged


class TestPatternSpecParamsMatchApplySignature:
    """E, first bullet: every registry pattern yields a spec whose params
    match the pattern's apply signature (minus net/instance_name/x/y, plus
    synthesized time_unit/deviation_unit for patterns with timed params).
    """

    @pytest.mark.parametrize("pattern_name", sorted(get_registry()))
    def test_generic_specs_cover_every_real_apply_param(self, pattern_name):
        registry = get_registry()
        pattern_cls = registry[pattern_name]
        if pattern_name in EXPLICIT_PATTERN_NAMES:
            pytest.skip(f"'{pattern_name}' is hand-written; covered by the explicit-spec tests")

        pattern_instance = pattern_cls()
        sig = inspect.signature(pattern_instance.apply)
        apply_params = {
            pname for pname in sig.parameters
            if pname not in ("self", "net", "instance_name", "x", "y")
            and sig.parameters[pname].kind != inspect.Parameter.VAR_KEYWORD
        }

        spec = build_catalog()[f"add_{pattern_name}"]
        spec_params = {p.name for p in spec.params} - {"name", "time_unit", "deviation_unit"}

        assert spec_params == apply_params, (
            f"add_{pattern_name}: catalog params {spec_params} != "
            f"apply() params {apply_params}"
        )

    def test_no_registry_pattern_still_has_var_keyword_apply(self):
        """A1: every registered pattern's apply() now declares real named
        params -- none of them fall back to **kwargs any more."""
        for pattern_name, pattern_cls in get_registry().items():
            sig = inspect.signature(pattern_cls().apply)
            has_var_keyword = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            assert not has_var_keyword, (
                f"{pattern_name}: apply() still accepts **kwargs -- its real "
                f"parameters are invisible to any introspection-based tool "
                f"generator."
            )


class TestChoicesNarrowing:
    """Every former `Literal[...]` on the old hand-written per-adapter tool
    signatures survives as ToolParam.choices, populated purely by parameter
    name (see catalog.py's _choices_for_param), since every hand-written
    op_* function in operations.py already declares these params as plain
    `str`, not DistributionType/RoutingStrategy.
    """

    def test_add_generator_distribution_and_time_unit_choices(self):
        spec = build_catalog()["add_generator"]
        by_name = {p.name: p for p in spec.params}
        assert by_name["distribution"].choices == ("exp", "norm", "unif", "det")
        assert by_name["time_unit"].choices == ("s", "min", "h", "d")
        assert by_name["deviation_unit"].choices == ("s", "min", "h", "d")

    def test_add_router_strategy_choices(self):
        spec = build_catalog()["add_router"]
        by_name = {p.name: p for p in spec.params}
        assert by_name["strategy"].choices == ("probability", "priority")

    def test_add_arc_and_modify_arc_arc_type_choices(self):
        for tool_name in ("add_arc", "modify_arc"):
            spec = build_catalog()[tool_name]
            by_name = {p.name: p for p in spec.params}
            assert by_name["arc_type"].choices == ("normal", "inhibitor", "read")

    def test_find_elements_element_type_choices(self):
        spec = build_catalog()["find_elements"]
        by_name = {p.name: p for p in spec.params}
        assert by_name["element_type"].choices == ("place", "transition")

    def test_direction_choices_differ_by_tool(self):
        """Same parameter name, two different meanings: auto_layout /
        set_layout_direction pick a layout flow; find_free_position picks a
        compass direction relative to an anchor element."""
        layout_spec = build_catalog()["auto_layout"]
        layout_direction = {p.name: p for p in layout_spec.params}["direction"]
        assert layout_direction.choices == ("LR", "TB")

        set_dir_spec = build_catalog()["set_layout_direction"]
        set_dir_direction = {p.name: p for p in set_dir_spec.params}["direction"]
        assert set_dir_direction.choices == ("LR", "TB")

        ffp_spec = build_catalog()["find_free_position"]
        ffp_direction = {p.name: p for p in ffp_spec.params}["direction"]
        assert ffp_direction.choices == ("above", "below", "left", "right")

    def test_distribution_variants_on_pattern_introspected_tools(self):
        """*_distribution params on generic (non-explicit) pattern tools get
        the same narrowing as the hand-written ones, e.g. transport_agent's
        grab_distribution/move_distribution/release_distribution/
        return_distribution."""
        spec = build_catalog()["add_transport_agent"]
        by_name = {p.name: p for p in spec.params}
        for pname in (
            "grab_distribution", "move_distribution",
            "release_distribution", "return_distribution",
        ):
            assert by_name[pname].choices == ("exp", "norm", "unif", "det")

    def test_plain_params_have_no_choices(self):
        spec = build_catalog()["add_machine"]
        by_name = {p.name: p for p in spec.params}
        assert by_name["name"].choices is None
        assert by_name["processing_time"].choices is None
        assert by_name["channels"].choices is None


class TestEffectiveType:
    def test_no_choices_returns_plain_type(self):
        p = ToolParam(name="processing_time", type=float, default=1.0)
        assert effective_type(p) is float

    def test_required_choices_become_bare_literal(self):
        from typing import Literal

        p = ToolParam(name="strategy", type=str, choices=("probability", "priority"))
        assert effective_type(p) == Literal["probability", "priority"]

    def test_optional_default_value_choices_stay_bare_literal(self):
        """distribution defaults to "exp" (not None): the Literal must NOT
        be unioned with None, since None is never a valid value here."""
        from typing import Literal

        p = ToolParam(name="distribution", type=str, default="exp", choices=("exp", "norm"))
        assert effective_type(p) == Literal["exp", "norm"]

    def test_optional_none_default_choices_union_with_none(self):
        from typing import Literal, Optional

        p = ToolParam(name="deviation_unit", type=str, default=None, choices=("s", "min"))
        assert effective_type(p) == Optional[Literal["s", "min"]]


class TestToolSpecFilterKwargs:
    """The shared dispatch-time guard against a hallucinated parameter
    name: both adapters call this before spec.operation(session, **kwargs),
    so a stray key never reaches op_* as a raw TypeError.
    """

    def test_known_kwargs_pass_through_unchanged(self):
        spec = build_catalog()["add_machine"]
        known, dropped = spec.filter_kwargs({"name": "M1", "processing_time": 5.0})
        assert known == {"name": "M1", "processing_time": 5.0}
        assert dropped == []

    def test_unknown_kwarg_is_dropped_and_reported(self):
        spec = build_catalog()["add_machine"]
        known, dropped = spec.filter_kwargs({"name": "M1", "bogus_param": 1})
        assert known == {"name": "M1"}
        assert dropped == ["bogus_param"]

    def test_dropped_names_come_back_sorted(self):
        spec = build_catalog()["add_machine"]
        _, dropped = spec.filter_kwargs({"zeta": 1, "alpha": 2, "name": "M1"})
        assert dropped == ["alpha", "zeta"]

    def test_empty_kwargs_round_trip(self):
        spec = build_catalog()["get_network_status"]
        known, dropped = spec.filter_kwargs({})
        assert known == {}
        assert dropped == []


class TestRestoredGuidanceProse:
    """C3: guidance text trimmed from client-visible descriptions against
    the phase-1 contract, restored verbatim (minus em dashes) from git
    history (develop:backend/src/mcp/tools/petri_tools.py).
    """

    def test_add_generator_has_canonical_translations(self):
        spec = build_catalog()["add_generator"]
        assert "Canonical translations:" in spec.description
        assert '"1 per minute ±10 sec"' in spec.description

    def test_add_place_has_layout_guidance(self):
        spec = build_catalog()["add_place"]
        assert "ALWAYS call find_free_position" in spec.description

    def test_add_transition_has_layout_guidance(self):
        spec = build_catalog()["add_transition"]
        assert "ALWAYS call find_free_position" in spec.description

    @pytest.mark.parametrize(
        "tool_name, expected_hint",
        [
            ("modify_place", "list_elements"),
            ("modify_transition", "list_elements"),
            ("modify_arc", "list_elements"),
        ],
    )
    def test_modify_tools_point_at_list_elements(self, tool_name, expected_hint):
        spec = build_catalog()[tool_name]
        assert expected_hint in spec.description
        assert "omitted fields stay unchanged" in spec.description

    def test_no_em_dashes_in_operations_py_sourced_descriptions(self):
        """C8: every explicit (operations.py-sourced) tool description must
        be em-dash free. Scoped to EXPLICIT_TOOL_NAMES, not the whole
        catalog: pattern-introspected tools also fold in each pattern
        CLASS's own docstring (domain/patterns/*.py), which this branch
        did not rewrite and so is out of scope for the em-dash sweep."""
        catalog = build_catalog()
        for name in EXPLICIT_TOOL_NAMES:
            assert chr(0x2014) not in catalog[name].description, f"{name}: description has an em dash"
