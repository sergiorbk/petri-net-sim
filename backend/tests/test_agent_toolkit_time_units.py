"""Unit tests for src/services/petri/agent_toolkit/time_units.py.

This module is the single replacement for the three near-identical
_TIME_FACTORS/_s()/_echo_duration copies that used to live independently
in mcp/tools/petri_tools.py, services/agent/tools/petri_tools.py, and
services/agent/nodes/tool_node.py.
"""

import inspect

import pytest

from src.services.petri.agent_toolkit import time_units as tu

# Deliberately NOT using `from __future__ import annotations` in this file:
# several tests below build a throwaway `apply()` function locally and
# introspect its REAL annotation objects via inspect.signature to exercise
# detect_time_params -- PEP 563 would turn those into bare strings instead.


class TestToSeconds:
    def test_seconds_identity(self):
        assert tu.to_seconds(5.0, "s") == 5.0

    @pytest.mark.parametrize(
        "unit, factor",
        [
            ("s", 1.0), ("sec", 1.0),
            ("min", 60.0), ("m", 60.0),
            ("h", 3600.0), ("hr", 3600.0), ("hour", 3600.0),
            ("d", 86400.0), ("day", 86400.0),
        ],
    )
    def test_known_units(self, unit, factor):
        assert tu.to_seconds(2.0, unit) == pytest.approx(2.0 * factor)

    def test_case_insensitive(self):
        assert tu.to_seconds(1.0, "MIN") == 60.0
        assert tu.to_seconds(1.0, "Hour") == 3600.0

    def test_unknown_unit_falls_back_to_seconds(self):
        """Unrecognized unit strings are lenient no-ops (factor 1.0)."""
        assert tu.to_seconds(3.0, "fortnight") == 3.0

    def test_zero_and_negative_values(self):
        assert tu.to_seconds(0.0, "min") == 0.0
        assert tu.to_seconds(-2.0, "min") == -120.0


class TestEchoDuration:
    def test_positive_seconds_shows_all_four_units(self):
        text = tu.echo_duration(3600.0)
        assert "3600s" in text
        assert "60min" in text
        assert "1h" in text
        # 3600s / 86400 = 0.0416667d
        assert "0.0416667d" in text

    def test_zero_or_negative_short_circuits(self):
        assert tu.echo_duration(0.0) == "0s"
        assert tu.echo_duration(-5.0) == "-5s"


class TestEchoRate:
    def test_positive_interval(self):
        text = tu.echo_rate(60.0)
        assert "1/min" in text
        assert "0.0166667/s" in text

    def test_zero_interval_is_undefined(self):
        assert tu.echo_rate(0.0) == "rate undefined (interval=0)"

    def test_negative_interval_is_undefined(self):
        assert tu.echo_rate(-1.0) == "rate undefined (interval=0)"


class TestIsTimeParamName:
    @pytest.mark.parametrize(
        "name",
        [
            "processing_time", "grab_time", "assembly_time",
            "mean_delay_duration", "timeout", "interval",
            "release_delay", "standard_deviation", "_deviation",
            "mean_time_between_failures", "mean_time_to_repair",
        ],
    )
    def test_recognized_names(self, name):
        assert tu.is_time_param_name(name) is True

    @pytest.mark.parametrize(
        "name",
        ["channels", "priority", "capacity", "batch_size", "n_branches", "name"],
    )
    def test_unrecognized_names(self, name):
        assert tu.is_time_param_name(name) is False

    def test_non_time_override(self):
        """A name that would normally match can be excluded via non_time."""
        assert tu.is_time_param_name("wip_limit_time", non_time=frozenset({"wip_limit_time"})) is False


class TestDetectTimeParams:
    def test_detects_float_annotated_time_params(self):
        def apply(self, net, instance_name, x, y, processing_time: float = 1.0, channels: int = 1):
            pass

        sig = inspect.signature(apply)
        assert tu.detect_time_params(sig) == ["processing_time"]

    def test_detects_optional_float_time_params(self):
        def apply(self, net, instance_name, x, y, return_time: float | None = None):
            pass

        sig = inspect.signature(apply)
        assert tu.detect_time_params(sig) == ["return_time"]

    def test_detects_unannotated_time_params(self):
        """No annotation at all still counts by name alone (legacy signatures)."""
        def apply(self, net, instance_name, x, y, mean_delay=0.0):
            pass

        sig = inspect.signature(apply)
        assert tu.detect_time_params(sig) == ["mean_delay"]

    def test_skips_non_float_annotated_time_shaped_names(self):
        """A time-shaped NAME with a non-float annotation is not converted."""
        def apply(self, net, instance_name, x, y, queue_place_id: str | None = None):
            pass

        sig = inspect.signature(apply)
        assert tu.detect_time_params(sig) == []

    def test_boilerplate_params_never_detected(self):
        def apply(self, net, instance_name, x, y):
            pass

        sig = inspect.signature(apply)
        assert tu.detect_time_params(sig) == []

    def test_non_time_frozenset_excludes_a_match(self):
        def apply(self, net, instance_name, x, y, wip_limit_time: float = 1.0):
            pass

        sig = inspect.signature(apply)
        assert tu.detect_time_params(sig, non_time=frozenset({"wip_limit_time"})) == []


class TestPatternTimeParams:
    """pattern_time_params(pattern_name, sig): the one helper both
    catalog.py's _pattern_tool_spec and operations.py's op_add_pattern call,
    so a pattern's tool_non_time_params exclusions are consulted from
    exactly one place instead of op_add_pattern re-deriving time params
    from a different signature without them.
    """

    def test_looks_up_exclusions_from_the_real_registry(self):
        """FinitePopulationQueuePattern declares n_customers/channels as
        tool_non_time_params; both are int-annotated (so detect_time_params
        would already skip them by annotation alone), but this test locks
        in that the registry lookup itself works end to end -- the params
        that ARE time-shaped for this pattern still come back correctly.
        """
        from src.services.petri.builder import PetriNetBuilder

        builder = PetriNetBuilder()
        sig = inspect.signature(builder.add_finite_population_queue)
        result = tu.pattern_time_params("finite_population_queue", sig)
        assert "service_time" in result
        assert "standard_deviation" in result
        assert "thinking_time" in result
        assert "n_customers" not in result
        assert "channels" not in result

    def test_unknown_pattern_name_falls_back_to_no_exclusions(self):
        """A pattern_name not in the registry (shouldn't happen in practice,
        since op_add_pattern is only ever bound via functools.partial to a
        real registry entry) degrades to plain detect_time_params instead
        of raising."""
        def apply(self, net, instance_name, x, y, processing_time: float = 1.0):
            pass

        sig = inspect.signature(apply)
        assert tu.pattern_time_params("not_a_real_pattern", sig) == ["processing_time"]

    def test_matches_plain_detect_time_params_when_exclusion_would_not_apply(self):
        """A synthetic signature whose only float-shaped param does not
        collide with the pattern's exclusions: pattern_time_params must
        agree exactly with calling detect_time_params directly with that
        pattern's tool_non_time_params -- the whole point of sharing one
        helper instead of two independent call sites."""
        from src.domain.patterns.registry import get_registry

        pattern_cls = get_registry()["finite_population_queue"]

        def apply(self, net, instance_name, x, y, service_time: float = 1.0, channels: int = 1):
            pass

        sig = inspect.signature(apply)
        assert tu.pattern_time_params("finite_population_queue", sig) == (
            tu.detect_time_params(sig, pattern_cls.tool_non_time_params)
        )


class TestOpAddPatternRespectsNonTimeExclusions:
    """End-to-end proof (not just the helper in isolation): dispatching
    add_finite_population_queue through the catalog with a non-"s"
    time_unit must never scale n_customers/channels, since they are counts,
    not durations, even though op_add_pattern derives its time params from
    the BUILDER method's signature rather than apply()'s.
    """

    def test_n_customers_and_channels_are_not_time_scaled(self):
        from src.services.petri.agent_toolkit.catalog import build_catalog
        from src.services.petri.session import PetriNetSession

        # auto_optimize=False keeps the pattern's own places/transitions
        # intact (the optimizer would otherwise fuse its zero-delay DET
        # transitions), so this test can assert on them by name instead of
        # only on token conservation.
        session = PetriNetSession(auto_optimize=False)
        session.create_network("Test")
        spec = build_catalog()["add_finite_population_queue"]
        result = spec.operation(
            session,
            name="Pool1",
            n_customers=5,
            channels=3,
            service_time=2.0,
            time_unit="min",
        )
        assert isinstance(result, str)

        pool = next(p for p in session.net.places if p.name == "Pool1_IdlePool")
        free_channels = next(p for p in session.net.places if p.name == "Pool1_FreeChannels")
        end_service = next(
            t for t in session.net.transitions if t.name == "Pool1_EndService"
        )
        assert pool.tokens == 5
        assert free_channels.tokens == 3
        # service_time IS time-shaped and must still convert: 2 min = 120s.
        assert end_service.mean_delay == pytest.approx(120.0)


class TestCanonicalTimeUnits:
    def test_matches_the_four_documented_units(self):
        assert tu.CANONICAL_TIME_UNITS == ("s", "min", "h", "d")

    def test_every_canonical_unit_converts_via_to_seconds(self):
        for unit in tu.CANONICAL_TIME_UNITS:
            assert tu.to_seconds(1.0, unit) > 0


class TestUnitForParam:
    def test_standard_deviation_follows_deviation_unit(self):
        assert tu.unit_for_param("standard_deviation", "min", "s") == "s"

    def test_everything_else_follows_time_unit(self):
        assert tu.unit_for_param("processing_time", "min", "s") == "min"
        assert tu.unit_for_param("interval", "h", "s") == "h"


class TestNormalizeTimeArgs:
    def test_converts_listed_time_params(self):
        args = {"processing_time": 2.0, "channels": 3, "time_unit": "min"}
        result = tu.normalize_time_args(args, ["processing_time"])
        assert result["processing_time"] == 120.0
        assert result["channels"] == 3
        assert "time_unit" not in result

    def test_standard_deviation_uses_deviation_unit(self):
        args = {
            "processing_time": 1.0,
            "standard_deviation": 10.0,
            "time_unit": "min",
            "deviation_unit": "s",
        }
        result = tu.normalize_time_args(args, ["processing_time", "standard_deviation"])
        assert result["processing_time"] == 60.0
        assert result["standard_deviation"] == 10.0  # already seconds
        assert "deviation_unit" not in result

    def test_deviation_unit_defaults_to_time_unit(self):
        args = {"standard_deviation": 2.0, "time_unit": "min"}
        result = tu.normalize_time_args(args, ["standard_deviation"])
        assert result["standard_deviation"] == 120.0

    def test_missing_unit_keys_default_to_seconds(self):
        args = {"processing_time": 5.0}
        result = tu.normalize_time_args(args, ["processing_time"])
        assert result["processing_time"] == 5.0

    def test_non_numeric_values_left_untouched(self):
        args = {"distribution": "exp", "time_unit": "min"}
        result = tu.normalize_time_args(args, ["distribution"])
        assert result["distribution"] == "exp"

    def test_original_dict_is_not_mutated(self):
        args = {"processing_time": 1.0, "time_unit": "min"}
        tu.normalize_time_args(args, ["processing_time"])
        assert args == {"processing_time": 1.0, "time_unit": "min"}

    def test_param_not_in_time_params_is_unconverted(self):
        args = {"channels": 3, "time_unit": "min"}
        result = tu.normalize_time_args(args, ["processing_time"])
        assert result["channels"] == 3
