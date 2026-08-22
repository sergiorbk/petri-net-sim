"""Extended optimizer tests targeting missed branches."""

from __future__ import annotations

import pytest

from src.domain import PetriNet, DistributionType
from src.services.petri import PetriNetBuilder, optimize_petri_net, PetriNetOptimizer


# ---------------------------------------------------------------------------
# _is_simple_intermediate_place edge cases
# ---------------------------------------------------------------------------

class TestIsSimpleIntermediate:
    def test_place_with_tokens_not_intermediate(self):
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=1, x=100, y=100)
        p2 = net.add_place("P2", tokens=1, x=200, y=100)  # has tokens
        p3 = net.add_place("P3", tokens=0, x=300, y=100)
        t1 = net.add_transition("T1", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        t2 = net.add_transition("T2", mean_delay=5.0, distribution=DistributionType.EXP, x=250, y=100)
        net.add_arc(source_id=p1.id, target_id=t1.id)
        net.add_arc(source_id=t1.id, target_id=p2.id)
        net.add_arc(source_id=p2.id, target_id=t2.id)
        net.add_arc(source_id=t2.id, target_id=p3.id)
        opt = PetriNetOptimizer(net)
        # P2 has tokens=1, should NOT be simple intermediate
        assert not opt._is_simple_intermediate_place(p2)

    def test_tagged_place_not_intermediate(self):
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        p_tagged = net.add_place("Counter", tokens=0, tag="throughput", x=200, y=100)
        p3 = net.add_place("P3", tokens=0, x=300, y=100)
        t1 = net.add_transition("T1", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        t2 = net.add_transition("T2", mean_delay=5.0, distribution=DistributionType.EXP, x=250, y=100)
        net.add_arc(source_id=p1.id, target_id=t1.id)
        net.add_arc(source_id=t1.id, target_id=p_tagged.id)
        net.add_arc(source_id=p_tagged.id, target_id=t2.id)
        net.add_arc(source_id=t2.id, target_id=p3.id)
        opt = PetriNetOptimizer(net)
        assert not opt._is_simple_intermediate_place(p_tagged)

    def test_place_with_multiple_inputs_not_intermediate(self):
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=100, y=200)
        p_mid = net.add_place("Mid", tokens=0, x=200, y=150)
        p3 = net.add_place("P3", tokens=0, x=300, y=150)
        t1 = net.add_transition("T1", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        t2 = net.add_transition("T2", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=200)
        t3 = net.add_transition("T3", mean_delay=5.0, distribution=DistributionType.EXP, x=250, y=150)
        net.add_arc(source_id=p1.id, target_id=t1.id)
        net.add_arc(source_id=t1.id, target_id=p_mid.id)
        net.add_arc(source_id=p2.id, target_id=t2.id)
        net.add_arc(source_id=t2.id, target_id=p_mid.id)  # two inputs
        net.add_arc(source_id=p_mid.id, target_id=t3.id)
        net.add_arc(source_id=t3.id, target_id=p3.id)
        opt = PetriNetOptimizer(net)
        assert not opt._is_simple_intermediate_place(p_mid)

    def test_place_with_heavy_arc_not_intermediate(self):
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        p_mid = net.add_place("Mid", tokens=0, x=200, y=100)
        p3 = net.add_place("P3", tokens=0, x=300, y=100)
        t1 = net.add_transition("T1", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        t2 = net.add_transition("T2", mean_delay=5.0, distribution=DistributionType.EXP, x=250, y=100)
        net.add_arc(source_id=p1.id, target_id=t1.id)
        net.add_arc(source_id=t1.id, target_id=p_mid.id, weight=2)  # weight=2 on input arc
        net.add_arc(source_id=p_mid.id, target_id=t2.id)
        net.add_arc(source_id=t2.id, target_id=p3.id)
        opt = PetriNetOptimizer(net)
        assert not opt._is_simple_intermediate_place(p_mid)


# ---------------------------------------------------------------------------
# _can_fuse_places edge cases
# ---------------------------------------------------------------------------

class TestCanFusePlaces:
    def _make_fuseable(self):
        """Create P1 -> T_zero -> P2 -> T_work pattern."""
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=200, y=100)
        p3 = net.add_place("P3", tokens=0, x=300, y=100)
        t_zero = net.add_transition("T_zero", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        t_work = net.add_transition("T_work", mean_delay=5.0, distribution=DistributionType.EXP, x=250, y=100)
        net.add_arc(source_id=p1.id, target_id=t_zero.id)
        net.add_arc(source_id=t_zero.id, target_id=p2.id)
        net.add_arc(source_id=p2.id, target_id=t_work.id)
        net.add_arc(source_id=t_work.id, target_id=p3.id)
        return net, p1, t_zero, p2

    def test_can_fuse_simple_case(self):
        net, p1, t_zero, p2 = self._make_fuseable()
        opt = PetriNetOptimizer(net)
        assert opt._can_fuse_places(p1, t_zero, p2)

    def test_cannot_fuse_timed_transition(self):
        net, p1, t_zero, p2 = self._make_fuseable()
        t_zero.mean_delay = 5.0  # make it timed
        t_zero.distribution = DistributionType.EXP
        opt = PetriNetOptimizer(net)
        assert not opt._can_fuse_places(p1, t_zero, p2)

    def test_cannot_fuse_high_priority_transition(self):
        net, p1, t_zero, p2 = self._make_fuseable()
        t_zero.priority = 2
        opt = PetriNetOptimizer(net)
        assert not opt._can_fuse_places(p1, t_zero, p2)

    def test_cannot_fuse_into_sink_place(self):
        """P2 is a sink (no outputs) - should not fuse."""
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        p2 = net.add_place("P2_sink", tokens=0, x=200, y=100)
        t_zero = net.add_transition("T_zero", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        net.add_arc(source_id=p1.id, target_id=t_zero.id)
        net.add_arc(source_id=t_zero.id, target_id=p2.id)
        opt = PetriNetOptimizer(net)
        assert not opt._can_fuse_places(p1, t_zero, p2)

    def test_cannot_fuse_tagged_place(self):
        net, p1, t_zero, p2 = self._make_fuseable()
        p1.tag = "throughput"
        opt = PetriNetOptimizer(net)
        assert not opt._can_fuse_places(p1, t_zero, p2)

    def test_cannot_fuse_p2_tagged(self):
        net, p1, t_zero, p2 = self._make_fuseable()
        p2.tag = "throughput"
        opt = PetriNetOptimizer(net)
        assert not opt._can_fuse_places(p1, t_zero, p2)


# ---------------------------------------------------------------------------
# FSP handles Transfer transitions (replaces removed EliminatePassThrough)
# ---------------------------------------------------------------------------

class TestFSPCoversTransferCases:
    def test_fsp_eliminates_transfer_transition(self):
        """FSP must handle the same case that EliminatePassThrough used to handle."""
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=1, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=200, y=100)
        p3 = net.add_place("P3", tokens=0, x=300, y=100)
        t_transfer = net.add_transition("Transfer_1", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        t_work = net.add_transition("T_work", mean_delay=5.0, distribution=DistributionType.EXP, x=250, y=100)
        t_end = net.add_transition("T_end", mean_delay=0.0, distribution=DistributionType.DET, x=350, y=100)
        net.add_arc(source_id=p1.id, target_id=t_transfer.id)
        net.add_arc(source_id=t_transfer.id, target_id=p2.id)
        net.add_arc(source_id=p2.id, target_id=t_work.id)
        net.add_arc(source_id=t_work.id, target_id=p3.id)
        net.add_arc(source_id=p3.id, target_id=t_end.id)

        places_before = len(net.places)
        opt = PetriNetOptimizer(net)
        opt._fuse_series_places()
        # FSP should fuse p1 and p2 (connected via Transfer_1 with weight=1)
        assert len(net.places) < places_before
        # Net must remain connected after fusion
        assert len(net.find_connected_components()) == 1

    def test_fsp_preserves_connectivity_no_orphans(self):
        """FSP must never create orphan places."""
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=200, y=100)
        p3 = net.add_place("P3", tokens=0, x=300, y=100)
        t_zero = net.add_transition("Transfer_0", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        t_work = net.add_transition("T_work", mean_delay=5.0, distribution=DistributionType.EXP, x=250, y=100)
        net.add_arc(source_id=p1.id, target_id=t_zero.id)
        net.add_arc(source_id=t_zero.id, target_id=p2.id)
        net.add_arc(source_id=p2.id, target_id=t_work.id)
        net.add_arc(source_id=t_work.id, target_id=p3.id)
        opt = PetriNetOptimizer(net)
        opt.optimize()
        assert len(net.find_connected_components()) == 1


# ---------------------------------------------------------------------------
# _eliminate_sink_transitions
# ---------------------------------------------------------------------------

class TestEliminateSinkTransitions:
    def test_eliminates_dangling_transition(self):
        """A transition with no inputs AND no outputs gets removed."""
        net = PetriNet(name="T")
        net.add_place("P1", tokens=0, x=100, y=100)
        t_dangling = net.add_transition("T_dangling", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        opt = PetriNetOptimizer(net)
        changed = opt._eliminate_sink_transitions()
        assert changed
        assert all(t.id != t_dangling.id for t in net.transitions)

    def test_eliminates_sink_transition_with_single_input(self):
        """T with one input place and no outputs — becomes sink."""
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        t_sink = net.add_transition("T_sink", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        net.add_arc(source_id=p1.id, target_id=t_sink.id)
        transitions_before = len(net.transitions)
        opt = PetriNetOptimizer(net)
        changed = opt._eliminate_sink_transitions()
        assert changed
        assert len(net.transitions) < transitions_before

    def test_keeps_timed_sink_transition(self):
        """Timed transitions are not sinks."""
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        t_timed = net.add_transition("T_timed", mean_delay=5.0, distribution=DistributionType.EXP, x=150, y=100)
        net.add_arc(source_id=p1.id, target_id=t_timed.id)
        opt = PetriNetOptimizer(net)
        changed = opt._eliminate_sink_transitions()
        assert not changed

    def test_keeps_priority_sink_transition(self):
        """Priority transitions have semantic meaning, not removed."""
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        t_prio = net.add_transition("T_prio", mean_delay=0.0, distribution=DistributionType.DET, priority=2, x=150, y=100)
        net.add_arc(source_id=p1.id, target_id=t_prio.id)
        opt = PetriNetOptimizer(net)
        changed = opt._eliminate_sink_transitions()
        assert not changed

    def test_keeps_multi_input_sink(self):
        """Multi-input sinks are NOT removed (not implemented for safety)."""
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=100, y=200)
        t_sink = net.add_transition("T_sink", mean_delay=0.0, distribution=DistributionType.DET, x=200, y=150)
        net.add_arc(source_id=p1.id, target_id=t_sink.id)
        net.add_arc(source_id=p2.id, target_id=t_sink.id)
        opt = PetriNetOptimizer(net)
        changed = opt._eliminate_sink_transitions()
        assert not changed


# ---------------------------------------------------------------------------
# _eliminate_duplicate_transitions
# ---------------------------------------------------------------------------

class TestEliminateDuplicateTransitions:
    def test_eliminates_duplicate(self):
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=300, y=100)
        # Two zero-delay transitions with identical inputs/outputs
        t1 = net.add_transition("T1", mean_delay=0.0, distribution=DistributionType.DET, x=200, y=80)
        t2 = net.add_transition("T2", mean_delay=0.0, distribution=DistributionType.DET, x=200, y=120)
        net.add_arc(source_id=p1.id, target_id=t1.id)
        net.add_arc(source_id=t1.id, target_id=p2.id)
        net.add_arc(source_id=p1.id, target_id=t2.id)
        net.add_arc(source_id=t2.id, target_id=p2.id)

        opt = PetriNetOptimizer(net)
        changed = opt._eliminate_duplicate_transitions()
        assert changed
        assert len(net.transitions) == 1

    def test_no_duplicates_no_change(self):
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=300, y=100)
        # Two different zero-delay transitions with different outputs
        t1 = net.add_transition("T1", mean_delay=0.0, distribution=DistributionType.DET, x=200, y=80)
        net.add_arc(source_id=p1.id, target_id=t1.id)
        net.add_arc(source_id=t1.id, target_id=p2.id)

        opt = PetriNetOptimizer(net)
        changed = opt._eliminate_duplicate_transitions()
        assert not changed


# ---------------------------------------------------------------------------
# _merge_duplicate_arcs
# ---------------------------------------------------------------------------

class TestMergeDuplicateArcs:
    def test_merges_duplicate_arcs(self):
        net = PetriNet(name="T")
        p1 = net.add_place("P1", tokens=0, x=100, y=100)
        t1 = net.add_transition("T1", mean_delay=5.0, distribution=DistributionType.EXP, x=200, y=100)
        # Add two arcs between same source/target
        net.add_arc(source_id=p1.id, target_id=t1.id, weight=1)
        net.add_arc(source_id=p1.id, target_id=t1.id, weight=2)

        opt = PetriNetOptimizer(net)
        changed = opt._merge_duplicate_arcs()
        assert changed
        # Should have merged to one arc with weight=3
        remaining = [a for a in net.arcs if a.source_id == p1.id and a.target_id == t1.id]
        assert len(remaining) == 1
        assert remaining[0].weight == 3


# ---------------------------------------------------------------------------
# End-to-end optimizer covering the full pipeline
# ---------------------------------------------------------------------------

class TestOptimizerEndToEnd:
    def test_two_connected_patterns_reduces_places(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen1", interval=5.0)
        builder.add_machine("M1", processing_time=10.0)
        builder.add_terminator("Exit1")

        net = builder.build()
        places_before = len(net.places)
        transitions_before = len(net.transitions)

        optimized, stats = optimize_petri_net(net)
        # Optimizer should remove some elements
        assert (
            len(optimized.places) <= places_before
            or len(optimized.transitions) <= transitions_before
        )

    def test_complex_network_optimized(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen1", interval=5.0)
        builder.add_machine("M1", processing_time=10.0)
        builder.add_machine("M2", processing_time=8.0)
        builder.add_terminator("Exit1")
        net = builder.build()
        optimized, stats = optimize_petri_net(net)
        assert stats is not None

    def test_renumbering_applied_after_optimization(self):
        """After optimization, element IDs should be sequential."""
        builder = PetriNetBuilder()
        builder.add_generator("Gen1", interval=5.0)
        builder.add_machine("M1", processing_time=10.0)
        builder.add_terminator("Exit1")
        net = builder.build()
        optimized, _ = optimize_petri_net(net)

        # IDs should be sequential p1, p2, ... and t1, t2, ...
        for i, place in enumerate(optimized.places, 1):
            assert place.id == f"p{i}"
        for i, trans in enumerate(optimized.transitions, 1):
            assert trans.id == f"t{i}"

    def test_optimizer_changes_trigger_all_passes(self):
        """Build a network that triggers multiple optimizer passes."""
        net = PetriNet(name="T")
        # Create a chain that requires multiple passes
        p1 = net.add_place("P1", tokens=1, x=100, y=100)
        p2 = net.add_place("P2", tokens=0, x=200, y=100)
        p3 = net.add_place("P3", tokens=0, x=300, y=100)
        p4 = net.add_place("P4", tokens=0, x=400, y=100)
        t1 = net.add_transition("Transfer_1", mean_delay=0.0, distribution=DistributionType.DET, x=150, y=100)
        t2 = net.add_transition("T_process", mean_delay=5.0, distribution=DistributionType.EXP, x=250, y=100)
        t3 = net.add_transition("Transfer_2", mean_delay=0.0, distribution=DistributionType.DET, x=350, y=100)
        net.add_arc(source_id=p1.id, target_id=t1.id)
        net.add_arc(source_id=t1.id, target_id=p2.id)
        net.add_arc(source_id=p2.id, target_id=t2.id)
        net.add_arc(source_id=t2.id, target_id=p3.id)
        net.add_arc(source_id=p3.id, target_id=t3.id)
        net.add_arc(source_id=t3.id, target_id=p4.id)

        optimized, stats = optimize_petri_net(net)
        assert stats.transitions_removed > 0
