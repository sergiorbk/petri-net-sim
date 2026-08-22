"""Tests for Petri Net optimizer."""

import pytest

from src.domain import PetriNet, DistributionType
from src.services.petri import PetriNetBuilder, optimize_petri_net, PetriNetOptimizer


class TestPetriNetOptimizer:
    """Test suite for Petri Net optimization."""

    def test_optimize_empty_net(self):
        """Optimizing empty network should not fail."""
        net = PetriNet(name="Empty")
        optimized_net, stats = optimize_petri_net(net)

        assert len(optimized_net.places) == 0
        assert len(optimized_net.transitions) == 0
        assert stats.places_removed == 0
        assert stats.transitions_removed == 0

    def test_optimize_single_pattern_no_change(self):
        """Single pattern without connections should not be optimized."""
        builder = PetriNetBuilder()
        builder.add_generator("Gen1", interval=5.0)

        net = builder.build()
        places_before = len(net.places)
        transitions_before = len(net.transitions)

        optimized_net, stats = optimize_petri_net(net)

        # Single generator should not be changed
        assert len(optimized_net.places) == places_before
        assert len(optimized_net.transitions) == transitions_before

    def test_fuse_series_places(self):
        """Test fusion of places connected by zero-delay transition."""
        net = PetriNet(name="TestFusion")

        # Create simple sequence: P1 -> T_zero -> P2 -> T_process
        p1 = net.add_place("P1", tokens=1, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=200, y=100)
        p3 = net.add_place("P3", tokens=0, x=300, y=100)

        t_zero = net.add_transition(
            "Transfer",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=150,
            y=100
        )
        t_process = net.add_transition(
            "Process",
            mean_delay=5.0,
            distribution=DistributionType.EXP,
            x=250,
            y=100
        )

        net.add_arc(p1.id, t_zero.id)
        net.add_arc(t_zero.id, p2.id)
        net.add_arc(p2.id, t_process.id)
        net.add_arc(t_process.id, p3.id)

        places_before = len(net.places)
        transitions_before = len(net.transitions)

        optimized_net, stats = optimize_petri_net(net)

        # Should fuse P1 and P2, remove T_zero
        assert len(optimized_net.places) < places_before
        assert len(optimized_net.transitions) < transitions_before
        assert stats.fusions_performed > 0

    def test_preserve_timed_transitions(self):
        """Timed transitions should not be removed."""
        net = PetriNet(name="TestTimed")

        p1 = net.add_place("P1", tokens=1, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=200, y=100)

        t_timed = net.add_transition(
            "TimedTransition",
            mean_delay=10.0,
            distribution=DistributionType.EXP,
            x=150,
            y=100
        )

        net.add_arc(p1.id, t_timed.id)
        net.add_arc(t_timed.id, p2.id)

        optimized_net, stats = optimize_petri_net(net)

        # Timed transition should remain
        assert len(optimized_net.transitions) == 1
        assert optimized_net.transitions[0].mean_delay == 10.0

    def test_preserve_priority_transitions(self):
        """Transitions with non-default priority should be preserved."""
        net = PetriNet(name="TestPriority")

        p1 = net.add_place("P1", tokens=1, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=200, y=100)

        t_high_priority = net.add_transition(
            "HighPriority",
            mean_delay=0.0,
            priority=5,
            x=150,
            y=100
        )

        net.add_arc(p1.id, t_high_priority.id)
        net.add_arc(t_high_priority.id, p2.id)

        optimized_net, stats = optimize_petri_net(net)

        # High priority transition should remain
        assert len(optimized_net.transitions) == 1
        assert optimized_net.transitions[0].priority == 5

    def test_preserve_weighted_arcs(self):
        """Arcs with weight > 1 should prevent fusion."""
        net = PetriNet(name="TestWeighted")

        p1 = net.add_place("P1", tokens=5, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=200, y=100)

        t_zero = net.add_transition(
            "Transfer",
            mean_delay=0.0,
            x=150,
            y=100
        )

        net.add_arc(p1.id, t_zero.id, weight=5)  # Weight > 1
        net.add_arc(t_zero.id, p2.id, weight=5)

        places_before = len(net.places)

        optimized_net, stats = optimize_petri_net(net)

        # Weighted arcs should prevent fusion
        assert len(optimized_net.places) == places_before

    def test_preserve_initial_marking(self):
        """Initial tokens should be preserved after fusion."""
        net = PetriNet(name="TestMarking")

        p1 = net.add_place("P1", tokens=3, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=200, y=100)
        p3 = net.add_place("P3", tokens=0, x=300, y=100)

        t_zero = net.add_transition(
            "Transfer",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=150,
            y=100
        )
        t_process = net.add_transition(
            "Process",
            mean_delay=5.0,
            x=250,
            y=100
        )

        net.add_arc(p1.id, t_zero.id)
        net.add_arc(t_zero.id, p2.id)
        net.add_arc(p2.id, t_process.id)
        net.add_arc(t_process.id, p3.id)

        optimized_net, stats = optimize_petri_net(net)

        # Total tokens should be preserved
        total_tokens = sum(p.tokens for p in optimized_net.places)
        assert total_tokens == 3

    def test_surviving_ids_are_stable_across_optimize(self):
        """Optimize must never rename surviving elements.

        Session bookkeeping (_last_output_place_id), the composed session's
        id-addressed links and the chat canvas all hold element ids across an
        optimize call, so a surviving element keeps its original id even when
        earlier elements are fused away and the sequence stops being dense.
        """
        net = PetriNet(name="TestStableIds")

        p1 = net.add_place("Queue", x=100, y=100)
        p2 = net.add_place("Handoff", x=200, y=100)
        p3 = net.add_place("Done", tokens=1, x=400, y=100)

        transfer = net.add_transition("Transfer", mean_delay=0.0, x=150, y=100)
        worker = net.add_transition("Work", mean_delay=1.0, x=300, y=100)

        net.add_arc(p1.id, transfer.id)
        net.add_arc(transfer.id, p2.id)
        net.add_arc(p2.id, worker.id)
        net.add_arc(worker.id, p3.id)

        optimized_net, stats = optimize_petri_net(net)

        assert stats.places_removed > 0, "fusion should have removed a place"
        surviving_place_ids = {p.id for p in optimized_net.places}
        assert p3.id in surviving_place_ids, "survivor keeps its original id"
        assert worker.id in {t.id for t in optimized_net.transitions}
        for arc in optimized_net.arcs:
            assert arc.source_id in surviving_place_ids | {t.id for t in optimized_net.transitions}
            assert arc.target_id in surviving_place_ids | {t.id for t in optimized_net.transitions}

    def test_merge_duplicate_arcs(self):
        """Duplicate arcs between same nodes should be merged."""
        net = PetriNet(name="TestDuplicateArcs")

        p1 = net.add_place("P1", tokens=1, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=200, y=100)
        t1 = net.add_transition("T1", mean_delay=1.0, x=150, y=100)

        # Create duplicate arcs (this can happen during pattern composition)
        net.add_arc(p1.id, t1.id, weight=1)
        # Manually add duplicate (bypassing normal checks)
        from src.domain.models.arc import Arc
        dup_arc = Arc(id="arc_dup", source_id=p1.id, target_id=t1.id, weight=2)
        net.arcs.append(dup_arc)

        arcs_before = len(net.arcs)

        optimized_net, stats = optimize_petri_net(net)

        # Duplicate arcs should be merged
        assert len(optimized_net.arcs) < arcs_before
        # Weight should be summed
        arc_to_t1 = [a for a in optimized_net.arcs if a.target_id == "t1"]
        assert len(arc_to_t1) == 1
        assert arc_to_t1[0].weight == 3  # 1 + 2

    def test_builder_with_connect_creates_transfer(self):
        """Builder.connect() creates Transfer transitions that can be optimized."""
        builder = PetriNetBuilder()

        gen = builder.add_generator("Gen", interval=5.0)
        buf = builder.add_buffer("Buffer")
        builder.connect(gen.interface.output_place_id, buf.interface.input_place_id)
        # Add terminator so Buffer is not a sink place
        term = builder.add_terminator("Exit")
        builder.connect(buf.interface.output_place_id, term.interface.input_place_id)

        net = builder.build()

        # Should have Transfer transition
        transfer_transitions = [t for t in net.transitions if "Transfer" in t.name]
        assert len(transfer_transitions) > 0

        places_before = len(net.places)
        transitions_before = len(net.transitions)

        optimized_net, stats = optimize_petri_net(net)

        # After optimization, Transfer should be removed or fused
        assert stats.fusions_performed > 0 or stats.transitions_removed > 0

    def test_preserve_sink_places(self):
        """Sink places (final accumulators) should NOT be removed."""
        net = PetriNet(name="TestSinkPlace")

        # Create: P1 -> T_zero -> P2 (sink)
        p1 = net.add_place("Input", tokens=1, x=100, y=100)
        p2 = net.add_place("FinalStorage", tokens=0, x=300, y=100)  # sink place

        t_zero = net.add_transition(
            "Transfer",
            mean_delay=0.0,
            distribution=DistributionType.DET,
            x=200,
            y=100
        )

        net.add_arc(p1.id, t_zero.id)
        net.add_arc(t_zero.id, p2.id)

        places_before = len(net.places)

        optimized_net, stats = optimize_petri_net(net)

        # Sink place should be preserved - it's a final storage
        assert len(optimized_net.places) == places_before
        # The Transfer transition should also remain since we can't fuse into a sink
        sink_places = [p for p in optimized_net.places if p.name == "FinalStorage"]
        assert len(sink_places) == 1

    def test_complex_network_optimization(self):
        """Test optimization of a more complex network."""
        builder = PetriNetBuilder()

        # Build: Gen -> Buf1 -> Machine -> Buf2 -> Terminator
        gen = builder.add_generator("Arrivals", interval=10.0)
        buf1 = builder.add_buffer("Queue1")
        builder.connect(gen.interface.output_place_id, buf1.interface.input_place_id)

        machine = builder.add_machine("Server", processing_time=8.0)
        builder.connect(buf1.interface.output_place_id, machine.interface.input_place_id)

        term = builder.add_terminator("Exit")
        builder.connect(machine.interface.output_place_id, term.interface.input_place_id)

        net = builder.build()

        # Count Transfer transitions
        transfer_count_before = len([t for t in net.transitions if "Transfer" in t.name])
        assert transfer_count_before > 0, "Test requires Transfer transitions"

        optimized_net, stats = optimize_petri_net(net)

        # Should have fewer elements
        assert len(optimized_net.places) <= len(net.places)
        assert len(optimized_net.transitions) <= len(net.transitions)

        # Network should still be valid
        is_valid, errors = optimized_net.validate_topology()
        assert is_valid, f"Optimized network invalid: {errors}"


class TestProtectedElements:
    """A pattern's interface place is a port, not redundancy. Fusing the
    place one pattern hands off from into the place the next hands off to
    merges the two into one, and that single place is the seam a composed
    model would be cut along -- once it is gone the model cannot be
    separated into Petri-objects at all. `protected_ids` is how a caller
    that intends to do that separation says so."""

    def _two_connected_patterns(self) -> PetriNetBuilder:
        builder = PetriNetBuilder()
        gen = builder.add_generator("Gen", interval=5.0)
        machine = builder.add_machine("Mach", processing_time=10.0)
        builder.connect(
            gen.interface.output_place_id, machine.interface.input_place_id
        )
        return builder

    def _pattern_element_ids(self, builder: PetriNetBuilder) -> frozenset[str]:
        return frozenset(
            element
            for instance in builder.pattern_instances.values()
            for element in (*instance["place_ids"], *instance["transition_ids"])
        )

    def test_unprotected_run_fuses_the_connector_and_loses_a_port(self):
        builder = self._two_connected_patterns()
        before = {p.name for p in builder.net.places}
        optimize_petri_net(builder.net)
        after = {p.name for p in builder.net.places}
        assert "Mach_Queue" in before and "Mach_Queue" not in after

    def test_protected_run_keeps_both_ports_and_the_connector(self):
        builder = self._two_connected_patterns()
        protected = self._pattern_element_ids(builder)
        places_before = len(builder.net.places)
        transitions_before = len(builder.net.transitions)

        optimize_petri_net(builder.net, protected)

        assert len(builder.net.places) == places_before
        assert len(builder.net.transitions) == transitions_before
        assert {"Gen_Out", "Mach_Queue"} <= {p.name for p in builder.net.places}

    def test_protection_leaves_every_pattern_registration_valid(self):
        """The damage a fused port does is silent: the registry keeps
        pointing at a place that no longer exists."""
        builder = self._two_connected_patterns()
        optimize_petri_net(builder.net, self._pattern_element_ids(builder))
        alive = {p.id for p in builder.net.places} | {
            t.id for t in builder.net.transitions
        }
        for instance in builder.pattern_instances.values():
            members = {*instance["place_ids"], *instance["transition_ids"]}
            assert members <= alive

    def test_an_unprotected_connector_elsewhere_is_still_fused(self):
        """Protection is per element, not a switch that turns the pass off:
        a pass-through the patterns do not own stays fair game."""
        builder = PetriNetBuilder()
        net = builder.net
        first = net.add_place("A", tokens=0)
        second = net.add_place("B", tokens=0)
        sink = net.add_transition("Sink", mean_delay=1.0)
        transfer = net.add_transition(
            "Pass", mean_delay=0.0, distribution=DistributionType.DET
        )
        net.add_arc(source_id=first.id, target_id=transfer.id)
        net.add_arc(source_id=transfer.id, target_id=second.id)
        net.add_arc(source_id=second.id, target_id=sink.id)

        optimize_petri_net(net, frozenset({sink.id}))

        assert transfer.id not in {t.id for t in net.transitions}


class TestOptimizationStats:
    """Test optimization statistics."""

    def test_stats_str_representation(self):
        """Stats should have useful string representation."""
        from src.services.petri.optimizer import OptimizationStats

        stats = OptimizationStats(
            places_removed=2,
            transitions_removed=3,
            arcs_removed=5,
            arcs_redirected=4,
            fusions_performed=2
        )

        str_repr = str(stats)
        assert "2 places" in str_repr
        assert "3 transitions" in str_repr
        assert "5 arcs" in str_repr
        assert "4 arcs" in str_repr
        assert "2 fusions" in str_repr
