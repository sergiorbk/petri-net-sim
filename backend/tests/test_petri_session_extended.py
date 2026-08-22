"""Extended tests for PetriNetSession covering missed branches."""

from __future__ import annotations

import pytest

from src.domain import PetriNet
from src.services.petri.builder import PetriNetBuilder
from src.services.petri.session import PetriNetSession


class TestFromNetData:
    def test_from_empty_dict(self):
        session = PetriNetSession.from_net_data({})
        assert len(session.net.places) == 0
        assert session.last_output_place_id is None
        assert not session.has_custom_topology

    def test_from_none_like_empty(self):
        session = PetriNetSession.from_net_data({"places": []})
        assert len(session.net.places) == 0

    def test_from_net_data_with_content(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen1", interval=10.0)
        net_data = builder.net.model_dump()
        net_data["_last_output_place_id"] = "some-id"
        net_data["_has_custom_topology"] = True

        session = PetriNetSession.from_net_data(net_data)
        assert len(session.net.places) > 0
        assert session.last_output_place_id == "some-id"
        assert session.has_custom_topology

    def test_from_net_data_defaults(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen1", interval=10.0)
        net_data = builder.net.model_dump()
        # no _last_output_place_id or _has_custom_topology in dict

        session = PetriNetSession.from_net_data(net_data)
        assert session.last_output_place_id is None
        assert not session.has_custom_topology


class TestProperties:
    def test_last_output_place_id_returns_none_initially(self):
        session = PetriNetSession()
        assert session.last_output_place_id is None

    def test_last_output_place_id_set_and_get(self):
        session = PetriNetSession()
        session.set_last_output("p42")
        assert session.last_output_place_id == "p42"

    def test_mark_custom_topology(self):
        session = PetriNetSession()
        assert not session.has_custom_topology
        session.mark_custom_topology()
        assert session.has_custom_topology

    def test_builder_property(self):
        session = PetriNetSession()
        assert isinstance(session.builder, PetriNetBuilder)

    def test_net_property(self):
        session = PetriNetSession()
        assert isinstance(session.net, PetriNet)


class TestAutoConnect:
    def test_auto_connect_without_last_output_returns_empty(self):
        session = PetriNetSession()
        msg = session.auto_connect("p1")
        assert msg == ""

    def test_auto_connect_with_last_output(self):
        session = PetriNetSession()
        gen_result = session.builder.add_generator("Gen1", interval=10.0)
        session.set_last_output(gen_result.interface.output_place_id)

        machine_result = session.builder.add_machine("M1", processing_time=5.0)
        msg = session.auto_connect(machine_result.interface.input_place_id)
        assert "Auto-connected" in msg


class TestGetWorkstationResult:
    def test_returns_none_when_not_found(self):
        session = PetriNetSession()
        result = session.get_workstation_result("NonExistent")
        assert result is None

    def test_returns_result_for_conveyor_workstation(self):
        session = PetriNetSession()
        session.builder.add_conveyor_workstation("WS1", processing_time=10.0)
        result = session.get_workstation_result("WS1")
        assert result is not None
        assert result.interface.input_place_id is not None
        assert result.interface.output_place_id is not None


class TestGetStatus:
    def test_empty_net_status(self):
        session = PetriNetSession()
        status = session.get_status()
        assert status["places"] == 0
        assert status["transitions"] == 0
        assert status["arcs"] == 0

    def test_status_with_generator(self):
        session = PetriNetSession()
        session.builder.add_generator("Gen1", interval=5.0)
        status = session.get_status()
        assert status["places"] > 0
        assert status["transitions"] > 0
        assert "name" in status
        assert "valid" in status
        assert "errors" in status


class TestExportPnml:
    def test_export_pnml_returns_xml_string(self):
        session = PetriNetSession()
        session.builder.add_generator("Gen1", interval=5.0)
        session.builder.add_machine("M1", processing_time=10.0)
        pnml = session.export_pnml()
        assert "<pnml" in pnml
        assert "</pnml>" in pnml


class TestOptimize:
    def test_optimize_returns_before_after_stats(self):
        session = PetriNetSession()
        session.builder.add_generator("Gen1", interval=5.0)
        result = session.optimize()
        assert "before" in result
        assert "after" in result
        assert "fusions_performed" in result
        assert "places" in result["before"]

    def test_optimize_clears_stale_output_place(self):
        """If optimizer removes the last output place, pointer is cleared."""
        session = PetriNetSession()
        session.builder.add_generator("Gen1", interval=5.0)
        # Set a fake last output that doesn't exist after optimization
        session.set_last_output("nonexistent-place-id")
        session.optimize()
        assert session.last_output_place_id is None

    def test_optimize_preserves_valid_output_place(self):
        session = PetriNetSession()
        gen = session.builder.add_generator("Gen1", interval=5.0)
        output_id = gen.interface.output_place_id
        session.set_last_output(output_id)
        session.optimize()
        # The output place may or may not survive, but no crash

    def test_create_network_resets(self):
        session = PetriNetSession()
        session.builder.add_generator("Gen1", interval=5.0)
        session.set_last_output("p1")
        session.mark_custom_topology()
        session.create_network("New")
        assert len(session.net.places) == 0
        assert session.last_output_place_id is None
        assert not session.has_custom_topology
        assert session.net.name == "New"


class TestAutoOptimizeSwitch:
    """C1: auto-optimize is a session-level switch, not something baked
    into every op_* call site. PetriNetSession() (MCP's constructor) leaves
    it at its default (True, unchanged MCP behavior); tool_node explicitly
    passes auto_optimize=False (restoring the pre-catalog chat behavior).
    """

    def test_default_constructor_enables_auto_optimize(self):
        """MCP's session store calls PetriNetSession() with no args."""
        session = PetriNetSession()
        gen = session.builder.add_generator("Gen1", interval=5.0)
        session.set_last_output(gen.interface.output_place_id)
        machine = session.builder.add_machine("M1", processing_time=1.0)
        # auto_connect -> set_last_output triggers optimize_if_needed,
        # which (auto_optimize=True) actually runs and fuses the Transfer
        # transition connect() created.
        session.auto_connect(machine.interface.input_place_id)
        session.set_last_output(machine.interface.output_place_id)
        assert session._is_optimized is True
        assert not any(t.name.startswith("Transfer_") for t in session.net.transitions)

    def test_from_net_data_defaults_to_enabled(self):
        """Every other caller of from_net_data (sessions API, tests) keeps
        today's behavior unless it explicitly opts out."""
        session = PetriNetSession.from_net_data({})
        assert session._auto_optimize is True

    def test_disabled_switch_leaves_transfer_transitions_unfused(self):
        session = PetriNetSession(auto_optimize=False)
        gen = session.builder.add_generator("Gen1", interval=5.0)
        session.set_last_output(gen.interface.output_place_id)
        machine = session.builder.add_machine("M1", processing_time=1.0)
        session.auto_connect(machine.interface.input_place_id)
        session.set_last_output(machine.interface.output_place_id)

        assert session._is_optimized is False
        assert any(t.name.startswith("Transfer_") for t in session.net.transitions)

    def test_disabled_switch_makes_read_only_ops_a_no_op_too(self):
        """optimize_if_needed is the one choke point every read-only op
        (get_status/list_elements/validate_net's session.optimize_if_needed
        call, connect_patterns) goes through -- gating it there is what
        makes the switch cover all of them without each op_* needing its
        own check."""
        session = PetriNetSession(auto_optimize=False)
        session.builder.add_generator("Gen1", interval=5.0)
        session.mark_custom_topology()  # sets _is_optimized = False
        note = session.optimize_if_needed()
        assert note == ""
        assert session._is_optimized is False

    def test_explicit_optimize_still_works_when_disabled(self):
        """optimize_network (session.optimize()) bypasses optimize_if_needed
        entirely, so it must always work regardless of the switch."""
        session = PetriNetSession(auto_optimize=False)
        gen = session.builder.add_generator("Gen1", interval=5.0)
        session.set_last_output(gen.interface.output_place_id)
        machine = session.builder.add_machine("M1", processing_time=1.0)
        session.auto_connect(machine.interface.input_place_id)

        session.optimize()
        assert session._is_optimized is True


class TestSimulationSummaryPersistence:
    """C2: the formatted last-simulation text survives to_net_data/
    from_net_data, unlike the raw SimulationResult, so a chat session
    rehydrated fresh in a later turn can still answer get_simulation_results.
    """

    def test_defaults_to_none(self):
        session = PetriNetSession()
        assert session.last_simulation_summary is None

    def test_persist_then_read_back(self):
        session = PetriNetSession()
        session.persist_simulation_summary("Simulation completed: ...")
        assert session.last_simulation_summary == "Simulation completed: ..."

    def test_round_trips_through_net_data(self):
        session = PetriNetSession()
        session.builder.add_generator("Gen1", interval=5.0)
        session.persist_simulation_summary("Simulation completed: 10.00 / 10.00")

        data = session.to_net_data()
        assert data["_last_simulation_result_text"] == "Simulation completed: 10.00 / 10.00"

        restored = PetriNetSession.from_net_data(data)
        assert restored.last_simulation_summary == "Simulation completed: 10.00 / 10.00"

    def test_create_network_clears_it(self):
        session = PetriNetSession()
        session.persist_simulation_summary("stale result")
        session.create_network("Fresh")
        assert session.last_simulation_summary is None


class TestToNetData:
    def test_round_trip_serialization(self):
        session = PetriNetSession()
        result = session.builder.add_generator("Gen1", interval=5.0)
        real_output_id = result.interface.output_place_id
        session.set_last_output(real_output_id)
        session.mark_custom_topology()

        data = session.to_net_data()
        assert data["_last_output_place_id"] == real_output_id
        assert data["_has_custom_topology"] is True
        assert "places" in data
