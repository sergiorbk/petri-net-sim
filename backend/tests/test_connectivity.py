"""Tests for PetriNet connectivity detection and related guards."""

import pytest

from src.domain import PetriNet, DistributionType
from src.services.petri import PetriNetBuilder
from src.services.petri.optimizer import optimize_petri_net
from src.services.petri.session import PetriNetSession


# ---------------------------------------------------------------------------
# find_connected_components
# ---------------------------------------------------------------------------


class TestFindConnectedComponents:
    def test_empty_net_returns_empty(self):
        net = PetriNet(name="Empty")
        assert net.find_connected_components() == []

    def test_single_place_is_one_component(self):
        net = PetriNet(name="Single")
        net.add_place("P1", x=0, y=0)
        components = net.find_connected_components()
        assert len(components) == 1
        assert "p1" in components[0]

    def test_single_transition_is_one_component(self):
        net = PetriNet(name="Single")
        # Must add places to create a valid transition context, but we test
        # the component detection on a bare transition
        net.add_place("P1", x=0, y=0)
        net.add_place("P2", x=100, y=0)
        t = net.add_transition("T1", mean_delay=1.0, x=50, y=0)
        net.add_arc("p1", t.id)
        net.add_arc(t.id, "p2")
        components = net.find_connected_components()
        assert len(components) == 1

    def test_fully_connected_chain_is_one_component(self):
        builder = PetriNetBuilder("Chain")
        gen = builder.add_generator("Gen", interval=1.0)
        machine = builder.add_machine("M", processing_time=5.0)
        builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)
        components = builder.net.find_connected_components()
        assert len(components) == 1

    def test_disconnected_net_has_multiple_components(self):
        """Simulate the bug scenario: Terminator added before Machine."""
        builder = PetriNetBuilder("Disconnected")
        builder.add_generator("Gen", interval=1.0)
        # Terminator auto-connects from generator output — last_output becomes None
        # Machine added separately with no connection
        builder.add_machine("Processor", processing_time=10.0)
        # Only generator and machine are in the net, not connected to each other
        # (builder.connect was never called)
        components = builder.net.find_connected_components()
        assert len(components) == 2

    def test_two_isolated_places_are_two_components(self):
        net = PetriNet(name="Islands")
        net.add_place("A", x=0, y=0)
        net.add_place("B", x=200, y=0)
        components = net.find_connected_components()
        assert len(components) == 2

    def test_arc_merges_two_places_via_transition(self):
        net = PetriNet(name="Linked")
        net.add_place("P1", x=0, y=0)
        net.add_place("P2", x=200, y=0)
        t = net.add_transition("T1", mean_delay=0.0, x=100, y=0)
        net.add_arc("p1", t.id)
        net.add_arc(t.id, "p2")
        components = net.find_connected_components()
        assert len(components) == 1

    def test_undirected_detection_ignores_arc_direction(self):
        """Connectivity check must be undirected — a cycle must be 1 component."""
        net = PetriNet(name="Cycle")
        net.add_place("P1", tokens=1, x=0, y=0)
        net.add_place("P2", x=200, y=0)
        t1 = net.add_transition("T1", mean_delay=1.0, x=100, y=0)
        t2 = net.add_transition("T2", mean_delay=1.0, x=300, y=0)
        net.add_arc("p1", t1.id)
        net.add_arc(t1.id, "p2")
        net.add_arc("p2", t2.id)
        net.add_arc(t2.id, "p1")
        components = net.find_connected_components()
        assert len(components) == 1


# ---------------------------------------------------------------------------
# validate_topology — connectivity errors
# ---------------------------------------------------------------------------


class TestValidateTopologyConnectivity:
    def test_connected_net_has_no_connectivity_error(self):
        builder = PetriNetBuilder("OK")
        gen = builder.add_generator("Gen", interval=1.0)
        machine = builder.add_machine("M", processing_time=5.0)
        builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)
        is_valid, errors = builder.net.validate_topology()
        connectivity_errors = [e for e in errors if "disconnected" in e]
        assert connectivity_errors == []

    def test_disconnected_net_fails_validate_topology(self):
        builder = PetriNetBuilder("Bad")
        builder.add_generator("Gen", interval=1.0)
        builder.add_machine("Proc", processing_time=10.0)
        # No connect call — two islands
        is_valid, errors = builder.net.validate_topology()
        assert not is_valid
        connectivity_errors = [e for e in errors if "disconnected" in e]
        assert len(connectivity_errors) == 1
        assert "2 disconnected components" in connectivity_errors[0]

    def test_component_label_included_in_error(self):
        net = PetriNet(name="Label")
        net.add_place("AlphaPlace", x=0, y=0)
        net.add_place("BetaPlace", x=300, y=0)
        _, errors = net.validate_topology()
        connectivity_errors = [e for e in errors if "disconnected" in e]
        assert len(connectivity_errors) == 1
        error_text = connectivity_errors[0]
        assert "AlphaPlace" in error_text or "BetaPlace" in error_text


# ---------------------------------------------------------------------------
# Session: simulate / export blocked on disconnected net
# ---------------------------------------------------------------------------


class TestSessionConnectivityGuards:
    def _make_disconnected_session(self) -> PetriNetSession:
        """Return a session with Generator and Machine not connected."""
        session = PetriNetSession()
        session.create_network("Bad")
        session.builder.add_generator("Gen", interval=1.0)
        session.builder.add_machine("Proc", processing_time=10.0)
        return session

    def _make_connected_session(self) -> PetriNetSession:
        session = PetriNetSession()
        session.create_network("Good")
        gen = session.builder.add_generator("Gen", interval=1.0)
        machine = session.builder.add_machine("Proc", processing_time=10.0)
        session.builder.connect(
            gen.interface.output_place_id,
            machine.interface.input_place_id,
        )
        return session

    def test_get_status_reports_island_count(self):
        session = self._make_disconnected_session()
        status = session.get_status()
        assert status["connected_components"] == 2
        assert len(status["islands"]) == 2

    def test_get_status_connected_reports_one_component(self):
        session = self._make_connected_session()
        status = session.get_status()
        assert status["connected_components"] == 1
        assert status["islands"] == []

    def test_validate_topology_detects_disconnected(self):
        session = self._make_disconnected_session()
        is_valid, errors = session.net.validate_topology()
        assert not is_valid
        assert any("disconnected" in e for e in errors)


# ---------------------------------------------------------------------------
# Optimizer: FSP covers Transfer cases; no orphans created
# ---------------------------------------------------------------------------


class TestOptimizerNoOrphans:
    def test_fsp_fuses_transfer_no_orphan(self):
        """After FSP fuses a Transfer transition, no orphan places remain."""
        builder = PetriNetBuilder("FSP")
        gen = builder.add_generator("Gen", interval=1.0)
        term_pattern = builder.add_terminator("Counter")
        # auto_connect creates Transfer_N between Gen output and Terminator input
        builder.connect(gen.interface.output_place_id, term_pattern.interface.input_place_id)
        net_before = len(builder.net.places)
        optimized, _ = optimize_petri_net(builder.net)
        # After optimization the net must still be connected
        components = optimized.find_connected_components()
        assert len(components) == 1

    def test_optimizer_preserves_connectivity_on_linear_chain(self):
        builder = PetriNetBuilder("Linear")
        gen = builder.add_generator("Gen", interval=1.0)
        m1 = builder.add_machine("M1", processing_time=5.0)
        m2 = builder.add_machine("M2", processing_time=3.0)
        builder.connect(gen.interface.output_place_id, m1.interface.input_place_id)
        builder.connect(m1.interface.output_place_id, m2.interface.input_place_id)
        optimized, _ = optimize_petri_net(builder.net)
        components = optimized.find_connected_components()
        assert len(components) == 1


# ---------------------------------------------------------------------------
# auto_connect feedback — human-readable names
# ---------------------------------------------------------------------------


class TestAutoConnectFeedback:
    def test_auto_connect_returns_human_readable_names(self):
        session = PetriNetSession()
        session.create_network("Test")
        gen_result = session.builder.add_generator("MyGen", interval=1.0)
        session.set_last_output(gen_result.interface.output_place_id)
        machine_result = session.builder.add_machine("MyMachine", processing_time=5.0)
        msg = session.auto_connect(machine_result.interface.input_place_id)
        assert "MyGen" in msg or "Gen" in msg
        assert "→" in msg

    def test_auto_connect_empty_when_no_last_output(self):
        session = PetriNetSession()
        session.create_network("Test")
        machine_result = session.builder.add_machine("M", processing_time=5.0)
        msg = session.auto_connect(machine_result.interface.input_place_id)
        assert msg == ""
