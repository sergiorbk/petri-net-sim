"""Tests for low-level Petri net element tools (custom topology)."""

import pytest

from src.domain import DistributionType, PetriNet
from src.services.petri.builder import PetriNetBuilder
from src.services.petri.session import PetriNetSession


class TestBuilderRawPlace:
    def test_add_raw_place_basic(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("Buffer")
        assert pid.startswith("p")
        place = builder.net.get_place(pid)
        assert place is not None
        assert place.name == "Buffer"
        assert place.tokens == 0

    def test_add_raw_place_with_tokens_and_tag(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("Counter", tokens=5, tag="throughput")
        place = builder.net.get_place(pid)
        assert place.tokens == 5
        assert place.tag == "throughput"

    def test_add_raw_place_explicit_coords(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1", x=200.0, y=300.0)
        place = builder.net.get_place(pid)
        assert place.graphics.x == 200.0
        assert place.graphics.y == 300.0

    def test_add_raw_place_auto_coords(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        place = builder.net.get_place(pid)
        assert place.graphics.x > 0
        assert place.graphics.y > 0


class TestBuilderRawTransition:
    def test_add_raw_transition_immediate(self):
        builder = PetriNetBuilder()
        tid = builder.add_raw_transition("Fire")
        trans = builder.net.get_transition(tid)
        assert trans is not None
        assert trans.name == "Fire"
        assert trans.is_immediate

    def test_add_raw_transition_timed(self):
        builder = PetriNetBuilder()
        tid = builder.add_raw_transition(
            "Process",
            distribution=DistributionType.EXP,
            mean_delay=10.0,
        )
        trans = builder.net.get_transition(tid)
        assert trans.distribution == DistributionType.EXP
        assert trans.mean_delay == 10.0

    def test_add_raw_transition_with_priority_and_probability(self):
        builder = PetriNetBuilder()
        tid = builder.add_raw_transition("Choose", priority=3, probability=0.7)
        trans = builder.net.get_transition(tid)
        assert trans.priority == 3
        assert trans.probability == 0.7


class TestBuilderRawArc:
    def test_add_raw_arc_place_to_transition(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        aid = builder.add_raw_arc(pid, tid)
        assert aid.startswith("arc")
        arc = builder.net.get_arc(aid)
        assert arc.source_id == pid
        assert arc.target_id == tid

    def test_add_raw_arc_transition_to_place(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        aid = builder.add_raw_arc(tid, pid)
        arc = builder.net.get_arc(aid)
        assert arc.source_id == tid
        assert arc.target_id == pid

    def test_add_raw_arc_with_weight(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        aid = builder.add_raw_arc(pid, tid, weight=3)
        arc = builder.net.get_arc(aid)
        assert arc.weight == 3

    def test_add_raw_arc_inhibitor(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        aid = builder.add_raw_arc(pid, tid, arc_type="inhibitor")
        arc = builder.net.get_arc(aid)
        assert arc.is_inhibitor

    def test_add_raw_arc_read(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        aid = builder.add_raw_arc(pid, tid, arc_type="read")
        arc = builder.net.get_arc(aid)
        assert arc.is_read_arc

    def test_add_raw_arc_bipartite_violation(self):
        builder = PetriNetBuilder()
        p1 = builder.add_raw_place("P1")
        p2 = builder.add_raw_place("P2")
        with pytest.raises(ValueError, match="cannot connect"):
            builder.add_raw_arc(p1, p2)

    def test_add_raw_arc_nonexistent_source(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        with pytest.raises(ValueError, match="not found"):
            builder.add_raw_arc("nonexistent", pid)


class TestValidateNet:
    def test_valid_net(self):
        builder = PetriNetBuilder()
        p1 = builder.add_raw_place("P1", tokens=1)
        t1 = builder.add_raw_transition("T1")
        p2 = builder.add_raw_place("P2")
        builder.add_raw_arc(p1, t1)
        builder.add_raw_arc(t1, p2)
        is_valid, errors = builder.validate()
        assert is_valid
        assert errors == []

    def test_dangling_transition_no_input(self):
        builder = PetriNetBuilder()
        p1 = builder.add_raw_place("P1")
        t1 = builder.add_raw_transition("T1")
        builder.add_raw_arc(t1, p1)
        is_valid, errors = builder.validate()
        assert not is_valid
        assert any("no input arc" in e for e in errors)

    def test_dangling_transition_no_output(self):
        builder = PetriNetBuilder()
        p1 = builder.add_raw_place("P1", tokens=1)
        t1 = builder.add_raw_transition("T1")
        builder.add_raw_arc(p1, t1)
        is_valid, errors = builder.validate()
        assert not is_valid
        assert any("no output arc" in e for e in errors)


class TestEndToEnd:
    def test_build_simple_net_and_export(self):
        """Build P1 -> T1 -> P2 via low-level tools and export PNML."""
        from src.services.petri.exporter import get_pnml_exporter

        builder = PetriNetBuilder()
        p1 = builder.add_raw_place("Input", tokens=3)
        t1 = builder.add_raw_transition("Process", distribution=DistributionType.EXP, mean_delay=5.0)
        p2 = builder.add_raw_place("Output")
        builder.add_raw_arc(p1, t1)
        builder.add_raw_arc(t1, p2)

        is_valid, errors = builder.validate()
        assert is_valid, f"Validation errors: {errors}"

        exporter = get_pnml_exporter()
        pnml = exporter.export(builder.net)
        assert "Input" in pnml
        assert "Process" in pnml
        assert "Output" in pnml
        assert "<pnml" in pnml

    def test_complex_topology(self):
        """Build a mutex pattern: two transitions sharing a resource place."""
        builder = PetriNetBuilder()
        resource = builder.add_raw_place("Mutex", tokens=1)
        p_in1 = builder.add_raw_place("In1", tokens=2)
        p_in2 = builder.add_raw_place("In2", tokens=2)
        p_out1 = builder.add_raw_place("Out1")
        p_out2 = builder.add_raw_place("Out2")
        t1 = builder.add_raw_transition("Action1", distribution=DistributionType.EXP, mean_delay=3.0)
        t2 = builder.add_raw_transition("Action2", distribution=DistributionType.EXP, mean_delay=4.0)

        # T1 consumes from In1 + Mutex, produces to Out1 + Mutex
        builder.add_raw_arc(p_in1, t1)
        builder.add_raw_arc(resource, t1)
        builder.add_raw_arc(t1, p_out1)
        builder.add_raw_arc(t1, resource)

        # T2 consumes from In2 + Mutex, produces to Out2 + Mutex
        builder.add_raw_arc(p_in2, t2)
        builder.add_raw_arc(resource, t2)
        builder.add_raw_arc(t2, p_out2)
        builder.add_raw_arc(t2, resource)

        is_valid, errors = builder.validate()
        assert is_valid, f"Validation errors: {errors}"
        assert len(builder.net.places) == 5
        assert len(builder.net.transitions) == 2
        assert len(builder.net.arcs) == 8


class TestSessionCustomTopologyFlag:
    def test_flag_initially_false(self):
        session = PetriNetSession()
        assert session.has_custom_topology is False

    def test_mark_custom_topology(self):
        session = PetriNetSession()
        session.mark_custom_topology()
        assert session.has_custom_topology is True

    def test_flag_serialized_in_net_data(self):
        session = PetriNetSession()
        session.mark_custom_topology()
        data = session.to_net_data()
        assert data["_has_custom_topology"] is True

    def test_flag_restored_from_net_data(self):
        session = PetriNetSession()
        session.builder.add_raw_place("P1")
        session.mark_custom_topology()
        data = session.to_net_data()

        restored = PetriNetSession.from_net_data(data)
        assert restored.has_custom_topology is True

    def test_flag_reset_on_create_network(self):
        session = PetriNetSession()
        session.mark_custom_topology()
        session.create_network("New")
        assert session.has_custom_topology is False


# =========================================================================
# CRUD: Modify tests
# =========================================================================


class TestModifyPlace:
    def test_update_tokens(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1", tokens=0)
        builder.modify_place(pid, tokens=10)
        assert builder.net.get_place(pid).tokens == 10

    def test_update_name(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("OldName")
        builder.modify_place(pid, name="NewName")
        assert builder.net.get_place(pid).name == "NewName"

    def test_update_tag(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        builder.modify_place(pid, tag="throughput")
        assert builder.net.get_place(pid).tag == "throughput"

    def test_unchanged_fields_preserved(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1", tokens=5, tag="counter")
        builder.modify_place(pid, name="P1_renamed")
        place = builder.net.get_place(pid)
        assert place.tokens == 5
        assert place.tag == "counter"
        assert place.name == "P1_renamed"

    def test_nonexistent_raises(self):
        builder = PetriNetBuilder()
        with pytest.raises(ValueError, match="not found"):
            builder.modify_place("nonexistent", tokens=1)

    def test_negative_tokens_raises(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        with pytest.raises(ValueError, match="negative"):
            builder.modify_place(pid, tokens=-1)


class TestModifyTransition:
    def test_update_delay(self):
        builder = PetriNetBuilder()
        tid = builder.add_raw_transition("T1", distribution=DistributionType.EXP, mean_delay=5.0)
        builder.modify_transition(tid, mean_delay=20.0)
        assert builder.net.get_transition(tid).mean_delay == 20.0

    def test_update_distribution(self):
        builder = PetriNetBuilder()
        tid = builder.add_raw_transition(
            "T1", distribution=DistributionType.EXP, mean_delay=5.0,
        )
        builder.modify_transition(
            tid, distribution=DistributionType.NORM, standard_deviation=2.0,
        )
        trans = builder.net.get_transition(tid)
        assert trans.distribution == DistributionType.NORM
        assert trans.standard_deviation == 2.0

    def test_update_priority(self):
        builder = PetriNetBuilder()
        tid = builder.add_raw_transition("T1")
        builder.modify_transition(tid, priority=5)
        assert builder.net.get_transition(tid).priority == 5

    def test_unchanged_fields_preserved(self):
        builder = PetriNetBuilder()
        tid = builder.add_raw_transition(
            "T1", distribution=DistributionType.EXP, mean_delay=10.0, priority=3,
        )
        builder.modify_transition(tid, name="T1_renamed")
        trans = builder.net.get_transition(tid)
        assert trans.mean_delay == 10.0
        assert trans.priority == 3
        assert trans.name == "T1_renamed"

    def test_nonexistent_raises(self):
        builder = PetriNetBuilder()
        with pytest.raises(ValueError, match="not found"):
            builder.modify_transition("nonexistent", mean_delay=1.0)

    def test_invalid_distribution_params_raises(self):
        builder = PetriNetBuilder()
        tid = builder.add_raw_transition("T1", distribution=DistributionType.EXP, mean_delay=5.0)
        with pytest.raises(ValueError, match="standard_deviation"):
            builder.modify_transition(tid, distribution=DistributionType.NORM)


class TestModifyArc:
    def test_update_weight(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        aid = builder.add_raw_arc(pid, tid, weight=1)
        builder.modify_arc(aid, weight=5)
        assert builder.net.get_arc(aid).weight == 5

    def test_update_arc_type(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        aid = builder.add_raw_arc(pid, tid)
        from src.domain.models.arc import ArcType
        builder.modify_arc(aid, arc_type=ArcType.READ)
        assert builder.net.get_arc(aid).is_read_arc

    def test_nonexistent_raises(self):
        builder = PetriNetBuilder()
        with pytest.raises(ValueError, match="not found"):
            builder.modify_arc("nonexistent", weight=2)


# =========================================================================
# CRUD: Remove tests
# =========================================================================


class TestRemovePlace:
    def test_removes_place(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        builder.remove_place(pid)
        assert builder.net.get_place(pid) is None
        assert len(builder.net.places) == 0

    def test_cascades_arcs(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        builder.add_raw_arc(pid, tid)
        builder.remove_place(pid)
        assert len(builder.net.arcs) == 0

    def test_nonexistent_raises(self):
        builder = PetriNetBuilder()
        with pytest.raises(ValueError, match="not found"):
            builder.remove_place("nonexistent")


class TestRemoveTransition:
    def test_removes_transition(self):
        builder = PetriNetBuilder()
        tid = builder.add_raw_transition("T1")
        builder.remove_transition(tid)
        assert builder.net.get_transition(tid) is None

    def test_cascades_arcs(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        builder.add_raw_arc(pid, tid)
        builder.remove_transition(tid)
        assert len(builder.net.arcs) == 0

    def test_nonexistent_raises(self):
        builder = PetriNetBuilder()
        with pytest.raises(ValueError, match="not found"):
            builder.remove_transition("nonexistent")


class TestRemoveArc:
    def test_removes_arc(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        aid = builder.add_raw_arc(pid, tid)
        builder.remove_arc(aid)
        assert builder.net.get_arc(aid) is None

    def test_preserves_nodes(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1")
        tid = builder.add_raw_transition("T1")
        aid = builder.add_raw_arc(pid, tid)
        builder.remove_arc(aid)
        assert builder.net.get_place(pid) is not None
        assert builder.net.get_transition(tid) is not None

    def test_nonexistent_raises(self):
        builder = PetriNetBuilder()
        with pytest.raises(ValueError, match="not found"):
            builder.remove_arc("nonexistent")


# =========================================================================
# List elements
# =========================================================================


class TestListElements:
    def test_returns_all_elements(self):
        builder = PetriNetBuilder()
        pid = builder.add_raw_place("P1", tokens=3, tag="test")
        tid = builder.add_raw_transition("T1", distribution=DistributionType.EXP, mean_delay=5.0)
        aid = builder.add_raw_arc(pid, tid, weight=2)

        elements = builder.list_elements()
        assert len(elements["places"]) == 1
        assert len(elements["transitions"]) == 1
        assert len(elements["arcs"]) == 1

        p = elements["places"][0]
        assert p["id"] == pid
        assert p["name"] == "P1"
        assert p["tokens"] == 3
        assert p["tag"] == "test"

        t = elements["transitions"][0]
        assert t["id"] == tid
        assert t["distribution"] == "exp"
        assert t["mean_delay"] == 5.0

        a = elements["arcs"][0]
        assert a["id"] == aid
        assert a["weight"] == 2

    def test_empty_net(self):
        builder = PetriNetBuilder()
        elements = builder.list_elements()
        assert elements["places"] == []
        assert elements["transitions"] == []
        assert elements["arcs"] == []


# =========================================================================
# End-to-end: build with patterns, then edit
# =========================================================================


class TestEditEndToEnd:
    def test_modify_pattern_generated_transition(self):
        """Build an M/M/1 queue with patterns, then modify the service time."""
        builder = PetriNetBuilder()
        gen = builder.add_generator("Arrivals", interval=10.0)
        machine = builder.add_machine("Server", processing_time=5.0)
        builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)

        elements = builder.list_elements()
        service_transitions = [
            t for t in elements["transitions"]
            if t["mean_delay"] == 5.0
        ]
        assert len(service_transitions) >= 1

        tid = service_transitions[0]["id"]
        builder.modify_transition(tid, mean_delay=20.0)
        assert builder.net.get_transition(tid).mean_delay == 20.0

        is_valid, errors = builder.validate()
        assert is_valid, f"Validation errors: {errors}"

    def test_remove_element_and_validate(self):
        """Build a net, remove a place, check validation catches dangling."""
        builder = PetriNetBuilder()
        p1 = builder.add_raw_place("P1", tokens=1)
        t1 = builder.add_raw_transition("T1", distribution=DistributionType.EXP, mean_delay=5.0)
        p2 = builder.add_raw_place("P2")
        builder.add_raw_arc(p1, t1)
        builder.add_raw_arc(t1, p2)

        warnings = builder.remove_place(p2)
        assert any("no output arcs" in w for w in warnings)
        is_valid, errors = builder.validate()
        assert not is_valid
        assert any("no output arc" in e for e in errors)


class TestRemoveWarnings:
    def test_remove_transition_warns_isolated_places(self):
        """p1 -> t1 -> p2 -> t2 -> p3; remove t2 => p2 dead end, p3 isolated."""
        builder = PetriNetBuilder()
        p1 = builder.add_raw_place("P1", tokens=1)
        t1 = builder.add_raw_transition("T1", distribution=DistributionType.EXP, mean_delay=5.0)
        p2 = builder.add_raw_place("P2")
        t2 = builder.add_raw_transition("T2", distribution=DistributionType.EXP, mean_delay=3.0)
        p3 = builder.add_raw_place("P3")
        builder.add_raw_arc(p1, t1)
        builder.add_raw_arc(t1, p2)
        builder.add_raw_arc(p2, t2)
        builder.add_raw_arc(t2, p3)

        warnings = builder.remove_transition(t2)
        assert any("dead end" in w and "P2" in w for w in warnings)
        assert any("isolated" in w and "P3" in w for w in warnings)

    def test_remove_arc_warns_dangling_transition(self):
        """Remove input arc from transition => no input arcs warning."""
        builder = PetriNetBuilder()
        p1 = builder.add_raw_place("P1", tokens=1)
        t1 = builder.add_raw_transition("T1")
        p2 = builder.add_raw_place("P2")
        aid = builder.add_raw_arc(p1, t1)
        builder.add_raw_arc(t1, p2)

        warnings = builder.remove_arc(aid)
        assert any("no input arcs" in w and "T1" in w for w in warnings)

    def test_no_warnings_when_net_is_fine(self):
        """Remove an arc that doesn't orphan anything => no warnings."""
        builder = PetriNetBuilder()
        p1 = builder.add_raw_place("P1", tokens=1)
        t1 = builder.add_raw_transition("T1")
        p2 = builder.add_raw_place("P2")
        builder.add_raw_arc(p1, t1)
        a1 = builder.add_raw_arc(p1, t1)  # duplicate arc
        builder.add_raw_arc(t1, p2)

        warnings = builder.remove_arc(a1)
        # t1 still has input from p1 (first arc), so no warnings about t1
        assert not any("T1" in w and "no input" in w for w in warnings)
