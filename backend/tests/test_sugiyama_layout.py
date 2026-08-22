"""Tests for Sugiyama hierarchical layout algorithm and builder integration."""

from __future__ import annotations

import random

import pytest

from src.domain.models.net import PetriNet
from src.domain.layout.sugiyama import (
    layout,
    layout_stats,
    MARGIN,
    PLACE_W,
    PLACE_H,
    TRANS_W,
    TRANS_H,
    LAYER_GAP,
    LAYER_GUTTER,
    CLUSTER_GAP,
    NODE_GAP,
    LABEL_H,
    RAW_CLUSTER,
)
from src.services.petri.builder import PetriNetBuilder
from src.services.petri.session import PetriNetSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_linear_net() -> PetriNet:
    """Generator → Lathe → Terminator (linear chain, no cycles)."""
    net = PetriNet(name="Linear")
    p1 = net.add_place("Input", tokens=1, x=0, y=0)
    t1 = net.add_transition("Process", x=0, y=0)
    p2 = net.add_place("Output", x=0, y=0)
    net.add_arc(p1.id, t1.id)
    net.add_arc(t1.id, p2.id)
    return net


def _make_diamond_net() -> PetriNet:
    """Input → T1, T2 → Output (two parallel transitions)."""
    net = PetriNet(name="Diamond")
    src = net.add_place("Source", tokens=1, x=0, y=0)
    t1 = net.add_transition("Path1", x=0, y=0)
    t2 = net.add_transition("Path2", x=0, y=0)
    mid1 = net.add_place("Mid1", x=0, y=0)
    mid2 = net.add_place("Mid2", x=0, y=0)
    sink_t = net.add_transition("Merge", x=0, y=0)
    snk = net.add_place("Sink", x=0, y=0)
    net.add_arc(src.id, t1.id)
    net.add_arc(src.id, t2.id)
    net.add_arc(t1.id, mid1.id)
    net.add_arc(t2.id, mid2.id)
    net.add_arc(mid1.id, sink_t.id)
    net.add_arc(mid2.id, sink_t.id)
    net.add_arc(sink_t.id, snk.id)
    return net


def _make_cycle_net() -> PetriNet:
    """Simple two-node cycle: P1 → T1 → P2 → T2 → P1."""
    net = PetriNet(name="Cycle")
    p1 = net.add_place("P1", tokens=1, x=0, y=0)
    p2 = net.add_place("P2", x=0, y=0)
    t1 = net.add_transition("T1", x=0, y=0)
    t2 = net.add_transition("T2", x=0, y=0)
    net.add_arc(p1.id, t1.id)
    net.add_arc(t1.id, p2.id)
    net.add_arc(p2.id, t2.id)
    net.add_arc(t2.id, p1.id)
    return net


# ---------------------------------------------------------------------------
# layout() — basic contracts
# ---------------------------------------------------------------------------

class TestLayoutBasicContracts:
    def test_empty_net_returns_empty(self):
        net = PetriNet(name="Empty")
        assert layout(net) == []

    def test_returns_all_nodes(self):
        net = _make_linear_net()
        positions = layout(net)
        ids = {p["id"] for p in positions}
        expected = {pl.id for pl in net.places} | {t.id for t in net.transitions}
        assert ids == expected

    def test_positions_have_required_keys(self):
        net = _make_linear_net()
        for pos in layout(net):
            assert "id" in pos
            assert "x" in pos
            assert "y" in pos

    def test_positions_are_numeric(self):
        net = _make_diamond_net()
        for pos in layout(net):
            assert isinstance(pos["x"], (int, float))
            assert isinstance(pos["y"], (int, float))

    def test_margin_respected_lr(self):
        net = _make_linear_net()
        positions = layout(net, direction="LR")
        for pos in positions:
            assert pos["x"] >= MARGIN - 1
            assert pos["y"] >= MARGIN - 1

    def test_margin_respected_tb(self):
        net = _make_linear_net()
        positions = layout(net, direction="TB")
        for pos in positions:
            assert pos["x"] >= MARGIN - 1
            assert pos["y"] >= MARGIN - 1


# ---------------------------------------------------------------------------
# layout() — LR direction correctness
# ---------------------------------------------------------------------------

class TestLayoutLR:
    def test_linear_chain_layered_left_to_right(self):
        """In a linear chain P→T→P, each node should be to the right of the previous."""
        net = _make_linear_net()
        positions = {p["id"]: p for p in layout(net, direction="LR")}
        p1 = net.places[0]
        t1 = net.transitions[0]
        p2 = net.places[1]
        # Each successor is further right
        assert positions[t1.id]["x"] > positions[p1.id]["x"]
        assert positions[p2.id]["x"] > positions[t1.id]["x"]

    def test_parallel_nodes_same_x_different_y(self):
        """In a diamond, the two parallel transitions should share the same X."""
        net = _make_diamond_net()
        positions = {p["id"]: p for p in layout(net, direction="LR")}
        t1, t2 = net.transitions[0], net.transitions[1]
        assert abs(positions[t1.id]["x"] - positions[t2.id]["x"]) < 2
        assert abs(positions[t1.id]["y"] - positions[t2.id]["y"]) > 10

    def test_no_overlapping_nodes(self):
        """No two nodes should overlap each other's bounding boxes."""
        net = _make_diamond_net()
        positions = layout(net, direction="LR")

        def get_bbox(pos):
            nid = pos["id"]
            node_type = "place" if net.get_place(nid) else "transition"
            w = PLACE_W if node_type == "place" else TRANS_W
            h = PLACE_H if node_type == "place" else TRANS_H
            return pos["x"], pos["y"], pos["x"] + w, pos["y"] + h

        bboxes = [get_bbox(p) for p in positions]
        for i, (x1, y1, x2, y2) in enumerate(bboxes):
            for j, (ax1, ay1, ax2, ay2) in enumerate(bboxes):
                if i == j:
                    continue
                overlap = x1 < ax2 and x2 > ax1 and y1 < ay2 and y2 > ay1
                assert not overlap, (
                    f"Nodes {positions[i]['id']} and {positions[j]['id']} overlap"
                )


# ---------------------------------------------------------------------------
# layout() — TB direction
# ---------------------------------------------------------------------------

class TestLayoutTB:
    def test_linear_chain_layered_top_to_bottom(self):
        net = _make_linear_net()
        positions = {p["id"]: p for p in layout(net, direction="TB")}
        p1 = net.places[0]
        t1 = net.transitions[0]
        p2 = net.places[1]
        assert positions[t1.id]["y"] > positions[p1.id]["y"]
        assert positions[p2.id]["y"] > positions[t1.id]["y"]

    def test_parallel_nodes_same_y_different_x(self):
        net = _make_diamond_net()
        positions = {p["id"]: p for p in layout(net, direction="TB")}
        t1, t2 = net.transitions[0], net.transitions[1]
        assert abs(positions[t1.id]["y"] - positions[t2.id]["y"]) < 2
        assert abs(positions[t1.id]["x"] - positions[t2.id]["x"]) > 10


# ---------------------------------------------------------------------------
# layout() — cycle handling
# ---------------------------------------------------------------------------

class TestLayoutCycles:
    def test_cycle_net_returns_all_nodes(self):
        net = _make_cycle_net()
        positions = layout(net, direction="LR")
        ids = {p["id"] for p in positions}
        expected = {pl.id for pl in net.places} | {t.id for t in net.transitions}
        assert ids == expected

    def test_cycle_net_no_crash(self):
        """Cycle removal must not crash or loop infinitely."""
        net = _make_cycle_net()
        result = layout(net, direction="LR")
        assert len(result) == 4


# ---------------------------------------------------------------------------
# layout_stats()
# ---------------------------------------------------------------------------

class TestLayoutStats:
    def test_stats_keys(self):
        net = _make_linear_net()
        stats = layout_stats(net, direction="LR")
        assert "positions" in stats
        assert "layer_count" in stats
        assert "element_count" in stats

    def test_element_count_matches_positions(self):
        net = _make_diamond_net()
        stats = layout_stats(net)
        assert stats["element_count"] == len(stats["positions"])

    def test_layer_count_linear(self):
        net = _make_linear_net()
        stats = layout_stats(net)
        # Linear chain has 3 nodes → 3 distinct layers
        assert stats["layer_count"] == 3

    def test_layer_count_diamond(self):
        net = _make_diamond_net()
        stats = layout_stats(net)
        # Source → {T1,T2} → {Mid1,Mid2} → Merge → Sink = 5 layers
        # but T1 and T2 are at the same layer, as are mid1/mid2
        assert stats["layer_count"] >= 3


# ---------------------------------------------------------------------------
# net.auto_layout()
# ---------------------------------------------------------------------------

class TestNetAutoLayout:
    def test_positions_updated_in_net(self):
        net = _make_linear_net()
        net.auto_layout(direction="LR")
        # All nodes should have non-zero coordinates after layout
        for p in net.places:
            assert p.graphics.x >= MARGIN - 1
        for t in net.transitions:
            assert t.graphics.x >= MARGIN - 1

    def test_returns_stats_dict(self):
        net = _make_linear_net()
        result = net.auto_layout(direction="LR")
        assert "layers" in result
        assert "element_count" in result
        assert result["element_count"] == 3

    def test_tb_direction(self):
        net = _make_linear_net()
        net.auto_layout(direction="TB")
        for p in net.places:
            assert p.graphics.y >= MARGIN - 1


# ---------------------------------------------------------------------------
# PetriNetBuilder — pattern registration + auto-layout
# ---------------------------------------------------------------------------

class TestBuilderPatternRegistration:
    def test_pattern_registered_after_add(self):
        builder = PetriNetBuilder()
        builder.add_generator("Arrivals", interval=30.0)
        assert "Arrivals" in builder._pattern_instances

    def test_pattern_type_stored(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        assert builder._pattern_instances["Gen"]["type"] == "generator"

    def test_place_ids_in_instance(self):
        builder = PetriNetBuilder()
        result = builder.add_machine("Lathe", processing_time=60.0)
        inst = builder._pattern_instances["Lathe"]
        assert len(inst["place_ids"]) > 0
        for pid in inst["place_ids"]:
            assert builder.net.get_place(pid) is not None

    def test_auto_layout_runs_after_add(self):
        """After add_generator, places should not all be at (0,0)."""
        builder = PetriNetBuilder()
        builder.add_generator("Source", interval=30.0)
        positions = [(p.graphics.x, p.graphics.y) for p in builder.net.places]
        assert any(x > 0 or y > 0 for x, y in positions)

    def test_layout_locked_blocks_auto_layout(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        builder._custom_layout_locked = True
        # Manually shift all places to a known position
        for p in builder.net.places:
            p.graphics.x = 999.0
            p.graphics.y = 999.0
        # Adding another pattern should NOT run layout (locked)
        builder.add_machine("M", processing_time=5.0)
        # Original places still at 999 (layout didn't run)
        gen_places = builder._pattern_instances["Gen"]["place_ids"]
        assert all(builder.net.get_place(pid).graphics.x == 999.0 for pid in gen_places)

    def test_extra_state_serializes_instances(self):
        builder = PetriNetBuilder()
        builder.add_generator("G", interval=5.0)
        state = builder.extra_state()
        assert "_pattern_instances" in state
        assert "G" in state["_pattern_instances"]
        assert "_layout_direction" in state
        assert "_custom_layout_locked" in state


# ---------------------------------------------------------------------------
# PetriNetBuilder — get_pattern_bounds
# ---------------------------------------------------------------------------

class TestBuilderPatternBounds:
    def test_bounds_returns_dict(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        bounds = builder.get_pattern_bounds("Gen")
        for key in ("min_x", "max_x", "min_y", "max_y", "width", "height"):
            assert key in bounds

    def test_bounds_unknown_name_raises(self):
        builder = PetriNetBuilder()
        with pytest.raises(ValueError, match="not found"):
            builder.get_pattern_bounds("NoSuchPattern")

    def test_bounds_width_positive(self):
        builder = PetriNetBuilder()
        builder.add_machine("Lathe", processing_time=30.0)
        bounds = builder.get_pattern_bounds("Lathe")
        assert bounds["width"] > 0
        assert bounds["height"] > 0

    def test_bounds_min_lte_max(self):
        builder = PetriNetBuilder()
        builder.add_generator("G", interval=5.0)
        b = builder.get_pattern_bounds("G")
        assert b["min_x"] <= b["max_x"]
        assert b["min_y"] <= b["max_y"]


# ---------------------------------------------------------------------------
# PetriNetBuilder — arrange_patterns
# ---------------------------------------------------------------------------

class TestBuilderArrangePatterns:
    def test_moves_pattern_to_target(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        builder.arrange_patterns([{"name": "Gen", "x": 500.0, "y": 300.0}])
        bounds = builder.get_pattern_bounds("Gen")
        assert abs(bounds["min_x"] - 500.0) < 1
        assert abs(bounds["min_y"] - 300.0) < 1

    def test_sets_layout_locked(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        assert not builder._custom_layout_locked
        builder.arrange_patterns([{"name": "Gen", "x": 100, "y": 100}])
        assert builder._custom_layout_locked

    def test_multiple_placements(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        builder.add_machine("M", processing_time=30.0)
        builder.arrange_patterns([
            {"name": "Gen", "x": 100, "y": 100},
            {"name": "M", "x": 600, "y": 100},
        ])
        b_gen = builder.get_pattern_bounds("Gen")
        b_m = builder.get_pattern_bounds("M")
        assert abs(b_gen["min_x"] - 100) < 1
        assert abs(b_m["min_x"] - 600) < 1

    def test_unknown_name_raises(self):
        builder = PetriNetBuilder()
        with pytest.raises(ValueError, match="not found"):
            builder.arrange_patterns([{"name": "Missing", "x": 0, "y": 0}])


# ---------------------------------------------------------------------------
# PetriNetBuilder — set_layout_direction
# ---------------------------------------------------------------------------

class TestBuilderSetLayoutDirection:
    def test_updates_direction(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        builder.set_layout_direction("TB")
        assert builder._layout_direction == "TB"

    def test_clears_lock(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        builder._custom_layout_locked = True
        builder.set_layout_direction("LR")
        assert not builder._custom_layout_locked

    def test_invalid_direction_raises(self):
        builder = PetriNetBuilder()
        with pytest.raises(ValueError, match="direction"):
            builder.set_layout_direction("INVALID")

    def test_tb_positions_are_vertical(self):
        """TB layout: elements should be stacked vertically (increasing Y)."""
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        builder.set_layout_direction("TB")
        for p in builder.net.places:
            assert p.graphics.y >= MARGIN - 1


# ---------------------------------------------------------------------------
# PetriNetSession — serialization round-trip
# ---------------------------------------------------------------------------

class TestSessionSerialization:
    def test_round_trip_preserves_pattern_instances(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        builder.add_machine("M", processing_time=30.0)
        net_data = builder.net.model_dump()
        net_data.update(builder.extra_state())
        net_data["_last_output_place_id"] = None
        net_data["_has_custom_topology"] = False
        net_data["_is_optimized"] = False

        session = PetriNetSession.from_net_data(net_data)
        assert "Gen" in session.builder._pattern_instances
        assert "M" in session.builder._pattern_instances

    def test_round_trip_preserves_direction(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        builder._layout_direction = "TB"
        net_data = builder.net.model_dump()
        net_data.update(builder.extra_state())
        net_data["_last_output_place_id"] = None
        net_data["_has_custom_topology"] = False
        net_data["_is_optimized"] = False

        session = PetriNetSession.from_net_data(net_data)
        assert session.builder._layout_direction == "TB"

    def test_round_trip_preserves_lock(self):
        builder = PetriNetBuilder()
        builder.add_generator("Gen", interval=10.0)
        builder._custom_layout_locked = True
        net_data = builder.net.model_dump()
        net_data.update(builder.extra_state())
        net_data["_last_output_place_id"] = None
        net_data["_has_custom_topology"] = False
        net_data["_is_optimized"] = False

        session = PetriNetSession.from_net_data(net_data)
        assert session.builder._custom_layout_locked is True

    def test_to_net_data_includes_extra_state(self):
        session = PetriNetSession()
        session.builder.add_generator("G", interval=5.0)
        data = session.to_net_data()
        assert "_pattern_instances" in data
        assert "_layout_direction" in data
        assert "_custom_layout_locked" in data
        assert "_cluster_bounds" in data

    def test_round_trip_preserves_cluster_bounds(self):
        builder = PetriNetBuilder()
        builder.add_generator("G", interval=5.0)
        builder.add_machine("M", processing_time=30.0)
        net_data = builder.net.model_dump()
        net_data.update(builder.extra_state())
        net_data["_last_output_place_id"] = None
        net_data["_has_custom_topology"] = False
        net_data["_is_optimized"] = False
        session = PetriNetSession.from_net_data(net_data)
        bounds = session.builder.cluster_bounds()
        # Both pattern groups should survive serialisation
        assert "G" in bounds
        assert "M" in bounds


# ---------------------------------------------------------------------------
# Cluster-aware layout — pattern grouping invariants
# ---------------------------------------------------------------------------


def _bbox_for_pattern(net, place_ids, transition_ids):
    """Return (min_x, min_y, max_x, max_y) covering elements' bounding boxes."""
    xs_lo, xs_hi, ys_lo, ys_hi = [], [], [], []
    for pid in place_ids:
        p = net.get_place(pid)
        if not p:
            continue
        xs_lo.append(p.graphics.x)
        ys_lo.append(p.graphics.y)
        xs_hi.append(p.graphics.x + PLACE_W)
        ys_hi.append(p.graphics.y + PLACE_H)
    for tid in transition_ids:
        t = net.get_transition(tid)
        if not t:
            continue
        xs_lo.append(t.graphics.x)
        ys_lo.append(t.graphics.y)
        xs_hi.append(t.graphics.x + TRANS_W)
        ys_hi.append(t.graphics.y + TRANS_H)
    return min(xs_lo), min(ys_lo), max(xs_hi), max(ys_hi)


def _bboxes_overlap(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1


class TestClusterAwareLayout:
    def test_terminator_is_rightmost(self):
        """LR pipeline: Terminator must end up in the largest-x layer."""
        b = PetriNetBuilder()
        gen = b.add_generator("Gen", interval=10.0)
        m = b.add_machine("M", processing_time=20.0)
        term = b.add_terminator("Done")
        b.connect(gen.interface.output_place_id, m.interface.input_place_id)
        b.connect(m.interface.output_place_id, term.interface.input_place_id)
        b.auto_layout(direction="LR")

        counter_pid = term.metadata["counter_place_id"]
        counter = b.net.get_place(counter_pid)
        max_x_other = max(
            (pl.graphics.x for pl in b.net.places if pl.id != counter_pid),
            default=0.0,
        )
        assert counter.graphics.x >= max_x_other - 1, (
            f"Terminator counter x={counter.graphics.x} should be the rightmost; "
            f"other max x={max_x_other}"
        )

    def test_clusters_do_not_overlap(self):
        """Independent pattern bounding boxes must not intersect."""
        b = PetriNetBuilder()
        gen = b.add_generator("Gen", interval=10.0)
        m1 = b.add_machine("M1", processing_time=20.0)
        m2 = b.add_machine("M2", processing_time=20.0)
        b.connect(gen.interface.output_place_id, m1.interface.input_place_id)
        b.connect(gen.interface.output_place_id, m2.interface.input_place_id)
        b.auto_layout(direction="LR")

        bbox_m1 = _bbox_for_pattern(b.net, m1.place_ids, m1.transition_ids)
        bbox_m2 = _bbox_for_pattern(b.net, m2.place_ids, m2.transition_ids)
        bbox_gen = _bbox_for_pattern(b.net, gen.place_ids, gen.transition_ids)
        assert not _bboxes_overlap(bbox_m1, bbox_m2), (
            f"Machine bboxes overlap: M1={bbox_m1}, M2={bbox_m2}"
        )
        assert not _bboxes_overlap(bbox_gen, bbox_m1)
        assert not _bboxes_overlap(bbox_gen, bbox_m2)

    def test_machine_free_place_adjacent_to_start(self):
        """Recycling Free place is pinned near its gating transition."""
        b = PetriNetBuilder()
        m = b.add_machine("M", processing_time=20.0, channels=2)
        b.auto_layout(direction="LR")
        # place_ids order: [queue, free, busy, done]; transitions: [start, end]
        free_pid = m.place_ids[1]
        start_tid = m.transition_ids[0]
        free = b.net.get_place(free_pid)
        start = b.net.get_transition(start_tid)
        # Free should be close to Start (within one node + gap on either axis)
        dx = abs(free.graphics.x - start.graphics.x)
        dy = abs(free.graphics.y - start.graphics.y)
        assert dx <= PLACE_W + NODE_GAP + 5, f"Free is too far horizontally: dx={dx}"
        assert dy <= PLACE_H + TRANS_H + NODE_GAP + 5, (
            f"Free is too far vertically: dy={dy}"
        )

    def test_bounded_queue_capacity_adjacent_to_enqueue(self):
        """BoundedQueue.Capacity must sit near its gating TryEnqueue transition."""
        b = PetriNetBuilder()
        bq = b.add_bounded_queue("BQ", capacity=5)
        b.auto_layout(direction="LR")
        cap_pid = bq.metadata["capacity_place_id"]
        enq_tid = bq.metadata["enqueue_transition_id"]
        cap = b.net.get_place(cap_pid)
        enq = b.net.get_transition(enq_tid)
        dx = abs(cap.graphics.x - enq.graphics.x)
        dy = abs(cap.graphics.y - enq.graphics.y)
        assert dx <= PLACE_W + NODE_GAP + 5
        assert dy <= PLACE_H + TRANS_H + NODE_GAP + 5

    def test_generator_ready_above_or_below_gen_transition(self):
        """Generator.Ready (recycling, 1 token) is pinned to gen-transition."""
        b = PetriNetBuilder()
        g = b.add_generator("Arr", interval=10.0)
        b.auto_layout(direction="LR")
        ready_pid = g.place_ids[0]
        gen_tid = g.transition_ids[0]
        ready = b.net.get_place(ready_pid)
        gen = b.net.get_transition(gen_tid)
        dx = abs(ready.graphics.x - gen.graphics.x)
        dy = abs(ready.graphics.y - gen.graphics.y)
        assert dx <= PLACE_W + NODE_GAP + 5
        assert dy >= TRANS_H / 2  # vertically displaced (above or below)

    def test_cluster_bounds_returned_from_auto_layout(self):
        b = PetriNetBuilder()
        b.add_generator("G", interval=5.0)
        b.add_machine("M", processing_time=10.0)
        stats = b.auto_layout()
        assert "cluster_bounds" in stats
        assert "G" in stats["cluster_bounds"]
        assert "M" in stats["cluster_bounds"]
        g_box = stats["cluster_bounds"]["G"]
        assert {"x", "y", "width", "height", "type"} <= set(g_box)
        assert g_box["type"] == "generator"
        assert g_box["width"] > 0 and g_box["height"] > 0


class TestTransferBridgePlacement:
    def test_transfer_lands_between_endpoints(self):
        """A bridge transition gets placed midpoint between its src and tgt."""
        b = PetriNetBuilder()
        gen = b.add_generator("Gen", interval=10.0)
        m = b.add_machine("M", processing_time=20.0)
        b.connect(gen.interface.output_place_id, m.interface.input_place_id)
        b.auto_layout(direction="LR")

        # Find the Transfer transition
        transfers = [t for t in b.net.transitions if t.name.startswith("Transfer_")]
        assert transfers, "connect() should have created a Transfer transition"
        for tr in transfers:
            in_arcs = [a for a in b.net.arcs if a.target_id == tr.id]
            out_arcs = [a for a in b.net.arcs if a.source_id == tr.id]
            if len(in_arcs) != 1 or len(out_arcs) != 1:
                continue
            src = b.net.get_place(in_arcs[0].source_id)
            tgt = b.net.get_place(out_arcs[0].target_id)
            assert src is not None and tgt is not None
            lo, hi = sorted([src.graphics.x, tgt.graphics.x])
            assert lo - 5 <= tr.graphics.x <= hi + PLACE_W + 5, (
                f"Transfer x={tr.graphics.x} not between src={src.graphics.x} "
                f"and tgt={tgt.graphics.x}"
            )


class TestDeterminism:
    def test_repeated_layout_is_bit_identical(self):
        """auto_layout() must be deterministic — same input → same output."""
        b = PetriNetBuilder()
        b.add_generator("G", interval=10.0)
        b.add_machine("M1", processing_time=20.0)
        b.add_machine("M2", processing_time=30.0)
        first = {(p.id, p.graphics.x, p.graphics.y) for p in b.net.places}
        first |= {(t.id, t.graphics.x, t.graphics.y) for t in b.net.transitions}
        b.auto_layout()
        b.auto_layout()
        b.auto_layout()
        second = {(p.id, p.graphics.x, p.graphics.y) for p in b.net.places}
        second |= {(t.id, t.graphics.x, t.graphics.y) for t in b.net.transitions}
        assert first == second, "Layout is not deterministic across re-runs"


class TestRegressionV2Topology:
    """Reproduces the topology in PetriNet_v2_f77067a6.pnml (Sonnet's output for
    the conveyor-routing task) and asserts the layout invariants that the
    prior flat-Sugiyama violated."""

    def _build_net(self) -> PetriNetBuilder:
        b = PetriNetBuilder()
        gen = b.add_generator("Arrivals", interval=30.0)
        router = b.add_router(
            "Router",
            routes=[
                {"name": "M1", "prob": 0.333},
                {"name": "M2", "prob": 0.333},
                {"name": "M3", "prob": 0.334},
            ],
        )
        m1 = b.add_machine("M1Mach", processing_time=40.0)
        m2 = b.add_machine("M2Mach", processing_time=40.0)
        bq = b.add_bounded_queue("M3Queue", capacity=5)
        m3 = b.add_machine("M3Mach", processing_time=60.0)
        merge = b.add_merge("Done", inputs=["A", "B", "C"])
        term_ok = b.add_terminator("Processed")
        term_bad = b.add_terminator("Rejected")

        # Wire arrivals → router input
        b.connect(gen.interface.output_place_id, router.interface.input_place_id)
        # Route outputs into the three machines
        b.connect(router.place_ids[1], m1.interface.input_place_id)  # Route M1
        b.connect(router.place_ids[2], m2.interface.input_place_id)  # Route M2
        b.connect(router.place_ids[3], bq.interface.input_place_id)  # Route M3 → BQ
        b.connect(bq.interface.output_place_id, m3.interface.input_place_id)
        b.connect_bounded_consumer(bq, m3)
        # Machines done → merge
        b.connect(m1.interface.output_place_id, merge.metadata["input_place_ids"]["A"])
        b.connect(m2.interface.output_place_id, merge.metadata["input_place_ids"]["B"])
        b.connect(m3.interface.output_place_id, merge.metadata["input_place_ids"]["C"])
        # Merge → success terminator; reject → bad terminator
        b.connect(merge.interface.output_place_id, term_ok.interface.input_place_id)
        b.connect(bq.metadata["reject_output_id"], term_bad.interface.input_place_id)
        b.auto_layout(direction="LR")
        return b

    def test_rejected_terminator_follows_its_producer(self):
        """Rejected lands to the right of its BoundedQueue producer.

        Terminators are drawn in a trailing column of their own
        (_align_terminators_last), so Rejected ends up well right of
        Arrivals and of the reject port that feeds it — alongside
        Processed rather than ranked against it.
        """
        b = self._build_net()
        rejected_counter = next(
            p for p in b.net.places if p.name == "Rejected_Counter"
        )
        arrivals_ready = next(
            p for p in b.net.places if p.name == "Arrivals_Ready"
        )
        bq_reject = next(p for p in b.net.places if p.name == "M3Queue_Overflow")
        assert rejected_counter.graphics.x > arrivals_ready.graphics.x + LAYER_GUTTER
        assert rejected_counter.graphics.x > bq_reject.graphics.x

    def test_machine_bboxes_do_not_overlap(self):
        b = self._build_net()
        names = ["M1Mach", "M2Mach", "M3Mach"]
        bboxes = {}
        for n in names:
            inst = b._pattern_instances[n]
            bboxes[n] = _bbox_for_pattern(b.net, inst["place_ids"], inst["transition_ids"])
        assert not _bboxes_overlap(bboxes["M1Mach"], bboxes["M2Mach"])
        assert not _bboxes_overlap(bboxes["M1Mach"], bboxes["M3Mach"])
        assert not _bboxes_overlap(bboxes["M2Mach"], bboxes["M3Mach"])

    def test_merge_routing_transitions_share_a_layer(self):
        """All Done_Route_* transitions should be approximately co-linear in x."""
        b = self._build_net()
        routes = [t for t in b.net.transitions if t.name.startswith("Done_Route_")]
        assert len(routes) == 3
        xs = [t.graphics.x for t in routes]
        spread = max(xs) - min(xs)
        # Merge places its N routing transitions in a small horizontal band
        assert spread <= TRANS_W + 5, (
            f"Merge routing transitions are scattered: x={xs}, spread={spread}"
        )

    def test_bounded_queue_capacity_within_pattern_bbox(self):
        b = self._build_net()
        inst = b._pattern_instances["M3Queue"]
        bbox = _bbox_for_pattern(b.net, inst["place_ids"], inst["transition_ids"])
        cap_pid = next(p for p in b.net.places if p.name == "M3Queue_Capacity").id
        cap = b.net.get_place(cap_pid)
        assert bbox[0] - 1 <= cap.graphics.x <= bbox[2] + 1
        assert bbox[1] - 1 <= cap.graphics.y <= bbox[3] + 1


class TestParallelTerminators:
    """When a flow branches into N parallel terminators, each one still
    continues forward (right in LR / down in TB) past its own producer."""

    def _branched_net(self) -> PetriNetBuilder:
        b = PetriNetBuilder()
        gen = b.add_generator("Gen", interval=10.0)
        router = b.add_router(
            "R",
            routes=[
                {"name": "A", "prob": 0.5},
                {"name": "B", "prob": 0.5},
            ],
        )
        ma = b.add_machine("MA", processing_time=20.0)
        mb = b.add_machine("MB", processing_time=20.0)
        ta = b.add_terminator("DoneA")
        tb = b.add_terminator("DoneB")
        b.connect(gen.interface.output_place_id, router.interface.input_place_id)
        b.connect(router.place_ids[1], ma.interface.input_place_id)
        b.connect(router.place_ids[2], mb.interface.input_place_id)
        b.connect(ma.interface.output_place_id, ta.interface.input_place_id)
        b.connect(mb.interface.output_place_id, tb.interface.input_place_id)
        b.auto_layout(direction="LR")
        return b

    def test_parallel_terminators_continue_right(self):
        b = self._branched_net()
        # Each terminator's counter should sit further right than its
        # corresponding machine's output (so the flow goes right, not down).
        ma_done = next(p for p in b.net.places if p.name == "MA_Done")
        mb_done = next(p for p in b.net.places if p.name == "MB_Done")
        done_a = next(p for p in b.net.places if p.name == "DoneA_Counter")
        done_b = next(p for p in b.net.places if p.name == "DoneB_Counter")
        assert done_a.graphics.x > ma_done.graphics.x
        assert done_b.graphics.x > mb_done.graphics.x

    def test_parallel_terminators_share_a_super_layer(self):
        """Equal-depth terminators get the same x band, separated by CLUSTER_GAP
        on Y — they do NOT stack into a single column above one another."""
        b = self._branched_net()
        done_a = next(p for p in b.net.places if p.name == "DoneA_Counter")
        done_b = next(p for p in b.net.places if p.name == "DoneB_Counter")
        # Same super-layer ⇒ similar x; different sub-rows ⇒ different y
        assert abs(done_a.graphics.x - done_b.graphics.x) <= LAYER_GUTTER
        assert abs(done_a.graphics.y - done_b.graphics.y) > PLACE_H


def _node_footprints(net) -> list[tuple[str, float, float, float, float]]:
    """Every node as (name, x, y, w, h), with the caption band that renders
    directly under it counted as part of its height. A caption drawn across
    the node below it is exactly as unreadable as two overlapping boxes, so
    layout has to keep both kinds of collision out."""
    boxes = [
        (p.name, p.graphics.x, p.graphics.y, PLACE_W, PLACE_H + LABEL_H)
        for p in net.places
    ]
    boxes += [
        (t.name, t.graphics.x, t.graphics.y, TRANS_W, TRANS_H + LABEL_H)
        for t in net.transitions
    ]
    return boxes


def _collisions(net) -> list[str]:
    """Every pair of nodes whose footprints intersect."""
    found = []
    boxes = _node_footprints(net)
    for i, (an, ax, ay, aw, ah) in enumerate(boxes):
        for bn, bx, by, bw, bh in boxes[i + 1:]:
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                found.append(f"{an} overlaps {bn}")
    return found


class TestNothingOverlaps:
    """The invariant behind every layout rule here: no two nodes may be
    drawn on top of each other, in any net this app can build, in either
    direction. Kept as a property over a spread of shapes rather than a
    fact about one of them, because the pass that used to break it
    (bridge placement) only broke on shapes where two bridges happened to
    share a midpoint."""

    def _linear(self) -> PetriNetBuilder:
        b = PetriNetBuilder()
        gen = b.add_generator("Gen", interval=10.0)
        mach = b.add_machine("Mach", processing_time=20.0)
        exit_ = b.add_terminator("Exit")
        b.connect(gen.interface.output_place_id, mach.interface.input_place_id)
        b.connect(mach.interface.output_place_id, exit_.interface.input_place_id)
        return b

    def _branched(self) -> PetriNetBuilder:
        b = PetriNetBuilder()
        gen = b.add_generator("Gen", interval=10.0)
        router = b.add_router("R", routes=[
            {"name": "A", "prob": 0.5}, {"name": "B", "prob": 0.5},
        ])
        m1 = b.add_machine("M1", processing_time=20.0)
        m2 = b.add_machine("M2", processing_time=30.0)
        e1 = b.add_terminator("E1")
        e2 = b.add_terminator("E2")
        b.connect(gen.interface.output_place_id, router.interface.input_place_id)
        b.connect(router.place_ids[1], m1.interface.input_place_id)
        b.connect(router.place_ids[2], m2.interface.input_place_id)
        b.connect(m1.interface.output_place_id, e1.interface.input_place_id)
        b.connect(m2.interface.output_place_id, e2.interface.input_place_id)
        return b

    def _merged(self) -> PetriNetBuilder:
        """Two producers into one merge and on to a single exit: the shape
        that puts several bridges between the SAME pair of clusters, which
        is what used to stack them."""
        b = PetriNetBuilder()
        gen = b.add_generator("Gen", interval=10.0)
        m1 = b.add_machine("M1", processing_time=20.0)
        m2 = b.add_machine("M2", processing_time=20.0)
        merge = b.add_merge("Join", inputs=["A", "B"])
        exit_ = b.add_terminator("Exit")
        b.connect(gen.interface.output_place_id, m1.interface.input_place_id)
        b.connect(gen.interface.output_place_id, m2.interface.input_place_id)
        b.connect(
            m1.interface.output_place_id, merge.metadata["input_place_ids"]["A"]
        )
        b.connect(
            m2.interface.output_place_id, merge.metadata["input_place_ids"]["B"]
        )
        b.connect(merge.interface.output_place_id, exit_.interface.input_place_id)
        return b

    def _counter_object(self) -> PetriNetBuilder:
        """The Counter object of a real generated model: a two-input merge
        whose output goes on to a grand total, while each of its two INPUT
        places also feeds a counter of its own. Three connectors leave from
        two neighbouring places, which is what used to stack one of them on
        the merge's own output."""
        b = PetriNetBuilder()
        merge = b.add_merge("ResultMerge", inputs=["From_CPU1", "From_CPU2"])
        total = b.add_terminator("TotalCounter")
        first = b.add_terminator("CPU1Counter")
        second = b.add_terminator("CPU2Counter")
        inputs = merge.metadata["input_place_ids"]
        b.connect(merge.interface.output_place_id, total.interface.input_place_id)
        b.connect(inputs["From_CPU1"], first.interface.input_place_id)
        b.connect(inputs["From_CPU2"], second.interface.input_place_id)
        return b

    @pytest.mark.parametrize("direction", ["LR", "TB"])
    @pytest.mark.parametrize(
        "shape", ["_linear", "_branched", "_merged", "_counter_object"]
    )
    def test_no_two_nodes_are_drawn_on_top_of_each_other(self, shape, direction):
        builder = getattr(self, shape)()
        builder.auto_layout(direction=direction)
        assert _collisions(builder.net) == []

    @staticmethod
    def _random_net(seed: int) -> PetriNetBuilder:
        """A net of randomly chosen, randomly wired patterns. The point is
        coverage of SHAPES, not of parameters: what used to collide was one
        connector landing where another connector, or a cluster node,
        already was, and which shapes do that is not something a handful of
        hand-written cases can be trusted to cover."""
        rnd = random.Random(seed)
        builder = PetriNetBuilder()
        generator = builder.add_generator(f"Gen{seed}", interval=rnd.uniform(5, 20))
        outputs = [generator.interface.output_place_id]
        for i in range(rnd.randint(1, 4)):
            kind = rnd.choice(["machine", "machine", "router", "merge", "buffer"])
            source = rnd.choice(outputs)
            if kind == "machine":
                made = builder.add_machine(
                    f"M{seed}_{i}", processing_time=rnd.uniform(5, 40)
                )
                builder.connect(source, made.interface.input_place_id)
                outputs.append(made.interface.output_place_id)
            elif kind == "router":
                count = rnd.randint(2, 3)
                made = builder.add_router(
                    f"RT{seed}_{i}",
                    routes=[{"name": f"R{j}", "prob": 1.0 / count} for j in range(count)],
                )
                builder.connect(source, made.interface.input_place_id)
                outputs.extend(made.place_ids[1:1 + count])
            elif kind == "merge":
                names = ["In0", "In1"]
                made = builder.add_merge(f"MG{seed}_{i}", inputs=names)
                for name in names:
                    builder.connect(
                        rnd.choice(outputs), made.metadata["input_place_ids"][name]
                    )
                outputs.append(made.interface.output_place_id)
            else:
                made = builder.add_buffer(f"BF{seed}_{i}")
                builder.connect(source, made.interface.input_place_id)
                outputs.append(made.interface.output_place_id)
        for i in range(rnd.randint(1, 3)):
            terminator = builder.add_terminator(f"T{seed}_{i}")
            builder.connect(rnd.choice(outputs), terminator.interface.input_place_id)
        return builder

    @pytest.mark.parametrize("direction", ["LR", "TB"])
    @pytest.mark.parametrize("seed", range(30))
    def test_random_nets_never_overlap(self, seed, direction):
        """The invariant as a property, over generated shapes rather than
        chosen ones. Before bridge placement learned to avoid what is
        already there, this failed on roughly two of every three shapes;
        the same generator was run to 3000 layouts on the fix with none."""
        builder = self._random_net(seed)
        builder.auto_layout(direction=direction)
        assert _collisions(builder.net) == []

    @pytest.mark.parametrize("direction", ["LR", "TB"])
    def test_several_bridges_between_one_pair_are_kept_apart(self, direction):
        """Two connectors joining the same two clusters share an ideal
        midpoint exactly, so placing each at its midpoint drew one on top
        of the other."""
        builder = self._merged()
        builder.auto_layout(direction=direction)
        bridges = [
            t for t in builder.net.transitions if t.name.startswith("Transfer")
        ]
        assert len(bridges) >= 2
        spots = {(t.graphics.x, t.graphics.y) for t in bridges}
        assert len(spots) == len(bridges)


class TestTerminatorsFormTheFinalColumn:
    """A terminator is where a flow ends, so it is drawn where an ending
    belongs: one column past the last real step, with every other
    terminator — even when the branches feeding them are different lengths,
    which is exactly when depth-based layering alone would scatter them."""

    def _uneven_branches(self, direction: str = "LR") -> PetriNetBuilder:
        """One short branch (a single machine) and one long branch (two
        machines chained), each ending in its own terminator."""
        b = PetriNetBuilder()
        gen = b.add_generator("Gen", interval=10.0)
        router = b.add_router(
            "R",
            routes=[
                {"name": "Short", "prob": 0.5},
                {"name": "Long", "prob": 0.5},
            ],
        )
        short = b.add_machine("ShortMach", processing_time=20.0)
        long_first = b.add_machine("LongMachA", processing_time=20.0)
        long_second = b.add_machine("LongMachB", processing_time=20.0)
        term_short = b.add_terminator("DoneShort")
        term_long = b.add_terminator("DoneLong")
        b.connect(gen.interface.output_place_id, router.interface.input_place_id)
        b.connect(router.place_ids[1], short.interface.input_place_id)
        b.connect(router.place_ids[2], long_first.interface.input_place_id)
        b.connect(
            long_first.interface.output_place_id,
            long_second.interface.input_place_id,
        )
        b.connect(
            short.interface.output_place_id, term_short.interface.input_place_id
        )
        b.connect(
            long_second.interface.output_place_id,
            term_long.interface.input_place_id,
        )
        b.auto_layout(direction=direction)
        return b

    def _bboxes(self, b: PetriNetBuilder) -> dict:
        return {
            name: _bbox_for_pattern(
                b.net, inst["place_ids"], inst["transition_ids"]
            )
            for name, inst in b._pattern_instances.items()
        }

    def test_uneven_branches_still_end_in_one_column(self):
        boxes = self._bboxes(self._uneven_branches())
        short_x = boxes["DoneShort"][0]
        long_x = boxes["DoneLong"][0]
        assert abs(short_x - long_x) <= 1, (
            f"terminators are in different columns: {short_x} vs {long_x}"
        )

    def test_terminators_stand_one_under_another(self):
        boxes = self._bboxes(self._uneven_branches())
        short_y = boxes["DoneShort"][1]
        long_y = boxes["DoneLong"][1]
        assert abs(short_y - long_y) > PLACE_H

    def test_nothing_else_is_drawn_past_the_terminator_column(self):
        boxes = self._bboxes(self._uneven_branches())
        column_x = min(boxes["DoneShort"][0], boxes["DoneLong"][0])
        for name, box in boxes.items():
            if name in ("DoneShort", "DoneLong"):
                continue
            assert box[2] <= column_x, f"{name} reaches past the terminators"

    def test_tb_ends_in_one_bottom_row_instead(self):
        """The same rule a quarter turn round: the trailing column becomes a
        trailing row, and the terminators stand side by side in it."""
        boxes = self._bboxes(self._uneven_branches(direction="TB"))
        short_y = boxes["DoneShort"][1]
        long_y = boxes["DoneLong"][1]
        assert abs(short_y - long_y) <= 1
        assert abs(boxes["DoneShort"][0] - boxes["DoneLong"][0]) > PLACE_W
        row_y = min(short_y, long_y)
        for name, box in boxes.items():
            if name in ("DoneShort", "DoneLong"):
                continue
            assert box[3] <= row_y, f"{name} reaches past the terminators"


class TestTBSymmetry:
    def test_tb_terminator_is_bottommost(self):
        b = PetriNetBuilder()
        gen = b.add_generator("G", interval=10.0)
        m = b.add_machine("M", processing_time=20.0)
        term = b.add_terminator("Done")
        b.connect(gen.interface.output_place_id, m.interface.input_place_id)
        b.connect(m.interface.output_place_id, term.interface.input_place_id)
        b.auto_layout(direction="TB")
        counter = b.net.get_place(term.metadata["counter_place_id"])
        max_y_other = max(
            (pl.graphics.y for pl in b.net.places if pl.id != counter.id),
            default=0.0,
        )
        assert counter.graphics.y >= max_y_other - 1

    def test_tb_clusters_do_not_overlap(self):
        b = PetriNetBuilder()
        b.add_generator("G", interval=10.0)
        b.add_machine("M1", processing_time=20.0)
        b.add_machine("M2", processing_time=20.0)
        b.auto_layout(direction="TB")
        inst1 = b._pattern_instances["M1"]
        inst2 = b._pattern_instances["M2"]
        bbox1 = _bbox_for_pattern(b.net, inst1["place_ids"], inst1["transition_ids"])
        bbox2 = _bbox_for_pattern(b.net, inst2["place_ids"], inst2["transition_ids"])
        assert not _bboxes_overlap(bbox1, bbox2)


class TestFlatFallback:
    def test_no_patterns_uses_flat_path(self):
        """A net built without patterns goes through flat Sugiyama."""
        net = _make_linear_net()
        stats = layout_stats(net, direction="LR")
        # Flat path returns empty cluster_bounds
        assert stats["cluster_bounds"] == {}
        # And still emits sensible coordinates
        assert stats["element_count"] == 3
        assert stats["layer_count"] == 3
