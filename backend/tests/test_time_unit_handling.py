"""Regression tests for time-unit handling in agent tool dispatch.

These guard the same two real-chat-session regressions the original version
of this file guarded, but against the phase-1 architecture: there is no
dispatch-level `_normalize_time_args`/`_apply_time_unit` any more (see
tool_node.py's module docstring) -- every op_* function in
agent_toolkit/operations.py does its own time-unit conversion, driven by
its own time_unit/deviation_unit params, exactly once. These tests call the
catalog's operations directly (the same callable tool_node.py dispatches
to), so they exercise the real conversion path end to end:

  1. `time_unit` was attached to args but never applied -- interval=1,
     time_unit="min" reached the builder as 1 second instead of 60.
  2. `standard_deviation` had no separate unit knob, so "1 min ±10 sec"
     forced the LLM to either lose precision or get the math wrong.

Pure-function coverage of time_units.py itself (to_seconds, echo_duration,
normalize_time_args, ...) lives in test_agent_toolkit_time_units.py.
"""

from __future__ import annotations

from src.services.petri.agent_toolkit.catalog import build_catalog
from src.services.petri.agent_toolkit.errors import ToolError
from src.services.petri.session import PetriNetSession

_CATALOG = build_catalog()


def _op(name):
    return _CATALOG[name].operation


class TestAddGeneratorTimeUnit:
    """End-to-end: op_add_generator reaches the builder with seconds."""

    def test_mixed_units_one_per_minute_plus_minus_ten_sec(self):
        """The canonical failing case from the chat: 1 token per minute ±10 sec."""
        session = PetriNetSession()
        message = _op("add_generator")(
            session,
            name="Gen",
            interval=1,
            time_unit="min",
            distribution="norm",
            standard_deviation=10,
            deviation_unit="s",
        )
        assert not isinstance(message, ToolError)
        gen = next(t for t in session.net.transitions if t.name == "Gen_Gen")
        assert gen.mean_delay == 60.0
        assert gen.standard_deviation == 10.0

    def test_pure_seconds_path_unchanged(self):
        session = PetriNetSession()
        _op("add_generator")(
            session, name="Gen", interval=60, time_unit="s",
            distribution="norm", standard_deviation=10,
        )
        gen = next(t for t in session.net.transitions if t.name == "Gen_Gen")
        assert gen.mean_delay == 60.0
        assert gen.standard_deviation == 10.0

    def test_deviation_unit_falls_back_to_time_unit_when_omitted(self):
        session = PetriNetSession()
        _op("add_generator")(
            session, name="Gen", interval=5, time_unit="min",
            distribution="norm", standard_deviation=1,
        )
        gen = next(t for t in session.net.transitions if t.name == "Gen_Gen")
        assert gen.mean_delay == 300.0
        assert gen.standard_deviation == 60.0

    def test_rate_per_minute_converts_to_interval_in_seconds(self):
        session = PetriNetSession()
        _op("add_generator")(session, name="Gen", rate=60, time_unit="min")
        gen = next(t for t in session.net.transitions if t.name == "Gen_Gen")
        # 60/min == 1/s -> interval == 1s
        assert gen.mean_delay == 1.0

    def test_deviation_unit_omitted_still_converts_via_time_unit(self):
        """If the LLM forgets deviation_unit, standard_deviation still
        converts via time_unit (deviation_unit falls back to it) rather
        than silently staying in raw units. NOTE: the old tool_node handler
        this file used to test also raised a "stdev dwarfs interval" ⚠
        sanity warning here; that heuristic was chat-only and was not
        carried into agent_toolkit.operations.op_add_generator during the
        phase-1 unification (the MCP body it was reconciled against never
        had it either) -- see this file's own report notes."""
        session = PetriNetSession()
        message = _op("add_generator")(
            session, name="Gen", interval=1, time_unit="min",
            distribution="norm", standard_deviation=10,
            # deviation_unit omitted -> falls back to time_unit ("min")
        )
        assert not isinstance(message, ToolError)
        gen = next(t for t in session.net.transitions if t.name == "Gen_Gen")
        assert gen.standard_deviation == 600.0


class TestRunSimulationTimeUnit:
    """The other regression: simulation_time must honor time_unit."""

    def _built_session(self) -> PetriNetSession:
        session = PetriNetSession()
        _op("add_generator")(session, name="Gen", interval=60, time_unit="s", distribution="det")
        _op("add_terminator")(session, name="T")
        return session

    def test_one_day_simulation_runs_full_horizon(self):
        session = self._built_session()
        message = _op("run_simulation")(session, simulation_time=1, time_unit="d")
        assert not isinstance(message, ToolError)
        assert "Simulation horizon: 86400s" in message
        assert "throughput" in message.lower()

    def test_seconds_path_unchanged(self):
        session = self._built_session()
        message = _op("run_simulation")(session, simulation_time=3600, time_unit="s")
        assert "Simulation horizon: 3600s" in message


class TestAddMachineTimeUnit:
    """Same conversion contract on a second hand-written op, for confidence
    the fix isn't a one-tool special case."""

    def test_processing_time_and_deviation_different_units(self):
        # Machine's "Start" transition is always immediate (delay=0) -- the
        # processing_time/standard_deviation land on "End" (see
        # MachinePattern.apply's own structure diagram).
        session = PetriNetSession()
        _op("add_generator")(session, name="Gen", interval=1, time_unit="s")
        _op("add_machine")(
            session, name="M", processing_time=1, time_unit="min",
            distribution="norm", standard_deviation=5, deviation_unit="s",
        )
        m = next(t for t in session.net.transitions if t.name == "M_End")
        assert m.mean_delay == 60.0
        assert m.standard_deviation == 5.0


class TestAddPatternGenericTimeUnit:
    """The generic op_add_pattern path (auto-generated tools) converts too."""

    def test_scheduled_availability_durations_convert_to_seconds(self):
        session = PetriNetSession()
        message = _op("add_scheduled_availability")(
            session, name="Shift", on_duration=8, off_duration=1, time_unit="h",
        )
        assert not isinstance(message, ToolError), message
        go_off = next(t for t in session.net.transitions if t.name == "Shift_GoOff")
        go_on = next(t for t in session.net.transitions if t.name == "Shift_GoOn")
        assert go_off.mean_delay == 8 * 3600.0
        assert go_on.mean_delay == 1 * 3600.0
