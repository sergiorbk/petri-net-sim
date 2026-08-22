"""Tests for src/services/petri/composed_convert.py: the converter pair
between the frontend-shape net_data dict and the domain ComposedModel.

Property focus (contract E, first bullet): flat net_data stays flat, and a
composed partition/merge round trip preserves place/transition/arc/link ids,
free-pool contents, and frame structure (name/priority/geometry/nesting) --
see composed_convert.py's module docstring for the one documented exception
(a hand-authored frame's own string id is not preserved through
ComposedModel, which has no field for it; PetriNetSession's own round trip,
tested separately, does not have this limitation).
"""

from __future__ import annotations

import copy
import random

import pytest

from src.domain.composed import ComposedModel, LinkType
from src.domain.layout.sugiyama import CLUSTER_GAP
from src.domain.models import PetriNet
from src.services.petri.exporter.geometry import PLACE_H, PLACE_W, TRANS_H, TRANS_W
from src.services.petri.composed_convert import (
    FREE_POOL_INDEX,
    Box,
    _flow_between,
    composed_model_to_net_data,
    frame_bounds_for_members,
    net_data_to_composed_model,
)


def _flat_net_data() -> dict:
    return {
        "name": "Flat",
        "places": [{"id": "p1", "name": "P1", "tokens": 1, "graphics": {"x": 0, "y": 0}}],
        "transitions": [
            {
                "id": "t1", "name": "T1", "priority": 1, "distribution": None,
                "mean_delay": 0.0, "standard_deviation": 0.0, "probability": None,
                "graphics": {"x": 100, "y": 0},
            }
        ],
        "arcs": [{"id": "arc1", "source_id": "p1", "target_id": "t1", "weight": 1, "arc_type": "NORMAL"}],
    }


def _two_object_fused_net_data() -> dict:
    """Object A's place fused with object B's place, mirroring the shape
    the frontend's own buildComposedRequest would send."""
    return {
        "name": "Demo",
        "places": [
            {"id": "p1", "name": "Free1", "tokens": 1, "graphics": {"x": 0, "y": 0}},
            {"id": "p2", "name": "A_In", "tokens": 0, "graphics": {"x": 100, "y": 0}, "objectId": "o1"},
            {"id": "p3", "name": "B_In", "tokens": 0, "graphics": {"x": 300, "y": 0}, "objectId": "o2"},
        ],
        "transitions": [
            {
                "id": "t1", "name": "A_T", "priority": 1, "distribution": None, "mean_delay": 0.0,
                "standard_deviation": 0.0, "probability": None, "graphics": {"x": 150, "y": 50}, "objectId": "o1",
            },
            {
                "id": "t2", "name": "B_T", "priority": 1, "distribution": None, "mean_delay": 0.0,
                "standard_deviation": 0.0, "probability": None, "graphics": {"x": 350, "y": 50}, "objectId": "o2",
            },
        ],
        "arcs": [
            {"id": "a1", "source_id": "p2", "target_id": "t1", "weight": 1, "arc_type": "NORMAL"},
            {"id": "a2", "source_id": "p3", "target_id": "t2", "weight": 1, "arc_type": "NORMAL"},
        ],
        "objects": [
            {"id": "o1", "name": "ObjA", "priority": 3, "graphics": {"x": 80, "y": -20, "width": 200, "height": 150}},
            {"id": "o2", "name": "ObjB", "priority": 1, "graphics": {"x": 280, "y": -20, "width": 200, "height": 150}},
        ],
        "links": [
            {"id": "link1", "type": "placeFusion", "sourceId": "p2", "targetId": "p3", "quantity": 1},
        ],
    }


class TestFrameBoundsForMembers:
    def test_empty_members_falls_back_to_minimum_box(self):
        box = frame_bounds_for_members([])
        assert box.x == 0.0 and box.y == 0.0
        assert box.w >= 160 and box.h >= 100

    def test_derives_box_that_clears_every_member(self):
        boxes = [Box(100, 200, 56, 56), Box(200, 200, 28, 64)]
        bounds = frame_bounds_for_members(boxes)
        assert bounds.x == 72.0
        assert bounds.y == 144.0
        assert bounds.w == 184.0
        assert bounds.h == 174.0


class TestNetDataToComposedModel:
    def test_free_pool_is_always_object_zero(self):
        model = net_data_to_composed_model(_flat_net_data())
        assert model.objects[FREE_POOL_INDEX].free is True
        assert len(model.objects[FREE_POOL_INDEX].net.places) == 1

    def test_flat_net_data_produces_only_the_free_pool(self):
        model = net_data_to_composed_model(_flat_net_data())
        assert len(model.objects) == 1
        assert len(model.links) == 0

    def test_partitions_elements_by_object_id(self):
        model = net_data_to_composed_model(_two_object_fused_net_data())
        assert len(model.objects) == 3  # free pool + 2 named
        free, obj_a, obj_b = model.objects
        assert [p.name for p in free.net.places] == ["Free1"]
        assert [p.name for p in obj_a.net.places] == ["A_In"]
        assert [p.name for p in obj_b.net.places] == ["B_In"]
        assert obj_a.name == "ObjA"
        assert obj_a.priority == 3
        assert obj_a.free is False

    def test_resolves_id_addressed_link_to_position_addressed(self):
        model = net_data_to_composed_model(_two_object_fused_net_data())
        assert len(model.links) == 1
        link = model.links[0]
        assert link.type == LinkType.PLACE_FUSION
        # object 1 = ObjA (first named object after the free pool), element
        # 0 = its only place (A_In); object 2 = ObjB, element 0 = B_In.
        assert (link.source_object, link.source_element) == (1, 0)
        assert (link.target_object, link.target_element) == (2, 0)

    def test_arcs_stay_local_to_their_own_object(self):
        model = net_data_to_composed_model(_two_object_fused_net_data())
        _, obj_a, obj_b = model.objects
        assert len(obj_a.net.arcs) == 1
        assert len(obj_b.net.arcs) == 1

    def test_composed_model_validates_clean(self):
        model = net_data_to_composed_model(_two_object_fused_net_data())
        assert model.validate() == []

    def test_empty_object_is_kept_not_dropped(self):
        net_data = _flat_net_data()
        net_data["objects"] = [{"id": "o1", "name": "Empty", "priority": 0, "graphics": {"x": 0, "y": 0, "width": 160, "height": 100}}]
        model = net_data_to_composed_model(net_data)
        assert len(model.objects) == 2
        assert model.objects[1].name == "Empty"
        assert len(model.objects[1].net.places) == 0

    def test_nested_object_parent_resolves_to_full_model_index(self):
        net_data = _two_object_fused_net_data()
        net_data["objects"][1]["objectId"] = "o1"  # ObjB nested inside ObjA
        model = net_data_to_composed_model(net_data)
        # ObjA is model index 1, so ObjB's parent should resolve to 1.
        assert model.objects[2].parent == 1

    def test_transition_to_place_link_resolves_correctly(self):
        net_data = _two_object_fused_net_data()
        net_data["links"] = [
            {"id": "link1", "type": "transitionToPlace", "sourceId": "t1", "targetId": "p3", "quantity": 2}
        ]
        model = net_data_to_composed_model(net_data)
        link = model.links[0]
        assert link.type == LinkType.TRANSITION_TO_PLACE
        assert (link.source_object, link.source_element) == (1, 0)  # t1 in ObjA
        assert (link.target_object, link.target_element) == (2, 0)  # p3 in ObjB
        assert link.quantity == 2

    def test_place_to_transition_link_passes_through_unrejected(self):
        """The converter itself is non-judgmental -- placeToTransition
        links are retired policy (ComposedModel.validate() flags them),
        not a partitioning failure this layer should swallow or crash on."""
        net_data = _two_object_fused_net_data()
        net_data["links"] = [
            {"id": "link1", "type": "placeToTransition", "sourceId": "p2", "targetId": "t2", "quantity": 1}
        ]
        model = net_data_to_composed_model(net_data)
        assert model.links[0].type == LinkType.PLACE_TO_TRANSITION
        errors = model.validate()
        assert any("placeToTransition" in e for e in errors)

    def test_same_owner_link_heals_into_a_local_arc(self):
        """A fusion link whose endpoints now share one owner (e.g. both
        ended up in the free pool) is not a cross-object link any more --
        mirrors buildComposedRequest's own healing pass."""
        net_data = _flat_net_data()
        net_data["places"].append({"id": "p2", "name": "P2", "tokens": 0, "graphics": {"x": 50, "y": 50}})
        net_data["links"] = [
            {"id": "link1", "type": "transitionToPlace", "sourceId": "t1", "targetId": "p2", "quantity": 1}
        ]
        model = net_data_to_composed_model(net_data)
        assert model.links == []
        healed = [a for a in model.objects[FREE_POOL_INDEX].net.arcs if a.target_id == "p2"]
        assert len(healed) == 1

    def test_cross_object_arc_synthesizes_a_link(self):
        """A PetriArc whose two endpoints belong to different objects
        cannot be represented inside either object's own PetriNet -- it
        must become a link, mirroring buildComposedRequest's identical
        handling of a boundary-crossing arc. Source is a PLACE (object A's
        p2) so the synthesized link is placeToTransition, the one type
        `informational` is actually legal for (see ComposedLink's own
        `_check_informational_scope`)."""
        net_data = _two_object_fused_net_data()
        net_data["links"] = []
        net_data["arcs"].append(
            {"id": "cross", "source_id": "p2", "target_id": "t2", "weight": 5, "arc_type": "READ"}
        )
        model = net_data_to_composed_model(net_data)
        assert len(model.links) == 1
        link = model.links[0]
        assert link.type == LinkType.PLACE_TO_TRANSITION
        assert link.quantity == 5
        assert link.informational is True

    def test_duplicate_heal_does_not_double_the_arc_when_the_document_already_has_it(self):
        """A stale same-owner link whose flow the document ALREADY carries
        as a real local arc must heal to exactly that one arc, not a
        second 'healed_' duplicate alongside it. This was dead code: the
        duplicate check inside _heal_same_owner_arcs_and_links used to
        compare against buckets[*].arcs, which _distribute_arcs (the only
        thing that ever puts a LOCAL arc into a bucket) had not run yet at
        that point in net_data_to_composed_model -- always empty, so the
        check never caught anything, and this exact document used to
        produce two arcs t1 -> p2 instead of one."""
        net_data = _flat_net_data()
        net_data["places"].append(
            {"id": "p2", "name": "P2", "tokens": 0, "graphics": {"x": 50, "y": 50}}
        )
        # The identical local arc t1 -> p2 already exists in net_data...
        net_data["arcs"].append(
            {"id": "arc2", "source_id": "t1", "target_id": "p2", "weight": 1, "arc_type": "NORMAL"}
        )
        # ...AND a stale link claims the same flow, both endpoints now
        # sharing the free pool as their owner (as if a prior drag-adoption
        # merged them without the frontend healing this link away yet).
        net_data["links"] = [
            {"id": "link1", "type": "transitionToPlace", "sourceId": "t1", "targetId": "p2", "quantity": 1},
        ]

        model = net_data_to_composed_model(net_data)

        assert model.links == []
        matching = [
            a for a in model.objects[FREE_POOL_INDEX].net.arcs
            if a.source_id == "t1" and a.target_id == "p2"
        ]
        assert len(matching) == 1

        # The round trip out the other side must also show only one arc,
        # not the input's one arc plus a synthesized "healed_link1" sibling.
        back = composed_model_to_net_data(model)
        matching_back = [
            a for a in back["arcs"] if a["source_id"] == "t1" and a["target_id"] == "p2"
        ]
        assert len(matching_back) == 1


class TestCrossingArcDirectionValidation:
    """Only a place-to-transition crossing may become an informational
    link (`informational` is only valid for a placeToTransition
    ComposedLink -- domain/composed/link.py's own
    `_check_informational_scope`); a transition-sourced READ arc crossing
    a boundary has no link shape it could become, and must fail cleanly
    BEFORE net_data_to_composed_model mutates anything.
    """

    def test_transition_sourced_read_arc_crossing_a_boundary_is_rejected_cleanly(self):
        net_data = _two_object_fused_net_data()
        net_data["links"] = []
        net_data["arcs"].append(
            {"id": "cross", "source_id": "t1", "target_id": "p3", "weight": 1, "arc_type": "READ"}
        )
        before = copy.deepcopy(net_data)

        with pytest.raises(ValueError, match="READ arc sourced from a transition"):
            net_data_to_composed_model(net_data)

        # Nothing was mutated by the failed attempt: validation runs
        # before _heal_same_owner_arcs_and_links/_distribute_arcs touch
        # anything, and this converter never mutates net_data itself.
        assert net_data == before

    def test_place_sourced_read_arc_crossing_a_boundary_becomes_an_informational_link(self):
        """The other direction: legal, and does not raise -- companion to
        the rejection test above, pinning down BOTH directions explicitly."""
        net_data = _two_object_fused_net_data()
        net_data["links"] = []
        net_data["arcs"].append(
            {"id": "cross", "source_id": "p2", "target_id": "t2", "weight": 5, "arc_type": "READ"}
        )
        before = copy.deepcopy(net_data)

        model = net_data_to_composed_model(net_data)

        assert net_data == before  # a successful call is non-mutating too
        assert len(model.links) == 1
        link = model.links[0]
        assert link.type == LinkType.PLACE_TO_TRANSITION
        assert link.informational is True


class TestComposedModelToNetData:
    def test_free_object_contributes_no_objects_entry_and_no_object_id(self):
        model = ComposedModel(name="X")
        net = PetriNet(name="Free")
        net.add_place("P1", tokens=1)
        model.add_object(net, free=True)
        data = composed_model_to_net_data(model)
        assert "objects" not in data
        assert "objectId" not in data["places"][0]

    def test_named_object_gets_a_frame_and_tagged_elements(self):
        model = ComposedModel(name="X")
        free_net = PetriNet(name="Free")
        model.add_object(free_net, free=True)
        obj_net = PetriNet(name="A")
        obj_net.add_place("P1", tokens=0, x=10, y=10)
        # auto_fit=False: an explicit box is only ever preserved verbatim
        # when auto-fit is deliberately locked (mirrors the frontend's own
        # resizeObject/refitFrame contract) -- otherwise _resolve_object_bounds
        # re-derives it from the member(s) on every export, see its docstring.
        model.add_object(
            obj_net, name="ObjA", priority=5, x=1, y=2, width=300, height=200, auto_fit=False,
        )

        data = composed_model_to_net_data(model)
        assert len(data["objects"]) == 1
        frame = data["objects"][0]
        assert frame["name"] == "ObjA"
        assert frame["priority"] == 5
        assert frame["graphics"] == {"x": 1.0, "y": 2.0, "width": 300.0, "height": 200.0}
        assert data["places"][0]["objectId"] == frame["id"]

    def test_missing_width_height_are_auto_derived(self):
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        obj_net = PetriNet(name="A")
        obj_net.add_place("P1", tokens=0, x=100, y=100)
        model.add_object(obj_net, name="ObjA")  # width/height omitted -> None

        data = composed_model_to_net_data(model)
        frame = data["objects"][0]
        assert frame["graphics"]["width"] > 0
        assert frame["graphics"]["height"] > 0

    def test_unlocked_frame_keeps_growing_across_a_wire_round_trip(self):
        """An agent builds a Petri-object incrementally across several tool
        calls/turns, each one exporting to net_data and the NEXT one
        reconstructing a ComposedModel from that exact dict (see
        PetriNetSession.to_net_data / from_net_data). Nothing on that path
        ever sets `autoFit`, so it stays None (never locked) throughout --
        the frame must keep re-fitting to whatever is added, not freeze at
        whatever size the FIRST export happened to compute (the bug: a
        naive "was width/height already set" check reads the previous
        export's own auto-derived value as if it were a deliberate lock)."""
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        obj_net = PetriNet(name="A")
        obj_net.add_place("P1", tokens=0, x=0, y=0)
        model.add_object(obj_net, name="ObjA")

        first_export = composed_model_to_net_data(model)
        small_frame = first_export["objects"][0]["graphics"]

        # A second member lands far outside the first export's box -- as
        # would happen once the agent adds more to the same object.
        grown = net_data_to_composed_model(first_export | {
            "places": first_export["places"] + [
                {"id": "p_new", "name": "P2", "tokens": 0,
                 "graphics": {"x": 1000, "y": 1000}, "objectId": first_export["objects"][0]["id"]},
            ],
        })
        second_export = composed_model_to_net_data(grown)
        grown_frame = second_export["objects"][0]["graphics"]

        assert grown_frame["width"] > small_frame["width"]
        assert grown_frame["height"] > small_frame["height"]

    def test_objects_piled_at_the_same_spot_are_spread_apart(self):
        """Every SessionObject's builder starts new members from the same
        fixed default cursor (services/petri/builder.py), so two objects
        the agent creates in the same conversation routinely end up with
        their members at (or very near) the exact same coordinates -- their
        auto-fit boxes would land stacked directly on top of each other
        with no export-time correction."""
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        for name in ("ObjA", "ObjB"):
            net = PetriNet(name=name)
            net.add_place("P1", tokens=0, x=100, y=200)
            model.add_object(net, name=name)

        data = composed_model_to_net_data(model)
        a, b = (f["graphics"] for f in data["objects"])
        gap = b["x"] - (a["x"] + a["width"])
        assert gap >= CLUSTER_GAP

    def test_object_piled_on_top_of_the_free_pool_is_pushed_clear_of_it(self):
        """The free pool has no frame of its own to render or reposition,
        but its elements occupy real canvas territory just like an
        object's members do. A named object built later in the same
        session -- whose builder, like every other, starts new members
        from the same fixed default cursor -- can land directly on top of
        the free pool's own content with nothing to push either one apart,
        unless the free pool is also treated as an obstacle."""
        model = ComposedModel(name="X")
        free_net = PetriNet(name="Free")
        free_net.add_place("FreeP1", tokens=0, x=100, y=200)
        model.add_object(free_net, free=True)

        obj_net = PetriNet(name="ObjA")
        obj_net.add_place("P1", tokens=0, x=100, y=200)  # same spot as FreeP1
        model.add_object(obj_net, name="ObjA")

        data = composed_model_to_net_data(model)
        frame = data["objects"][0]["graphics"]
        free_place = next(p for p in data["places"] if p["name"] == "FreeP1")
        fx, fy = free_place["graphics"]["x"], free_place["graphics"]["y"]

        overlaps_x = frame["x"] < fx + PLACE_W and fx < frame["x"] + frame["width"]
        overlaps_y = frame["y"] < fy + PLACE_H and fy < frame["y"] + frame["height"]
        assert not (overlaps_x and overlaps_y)

    def test_nested_children_piled_at_the_same_spot_are_spread_apart_too(self):
        """Nested object frames sit in the SAME absolute coordinate space as
        everything else (the frontend only converts to parent-relative at
        render time) -- so two children nested inside the same parent are
        just as exposed to the "every builder starts at the same default
        cursor" cause as two top-level objects are. The parent must also be
        re-fit afterward, or it stays sized for where its children stood
        BEFORE being spread apart and ends up clipping them."""
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        parent_index = model.add_object(PetriNet(name="Parent"), name="Parent").index
        for name in ("ChildA", "ChildB"):
            net = PetriNet(name=name)
            net.add_place("P1", tokens=0, x=500, y=500)
            model.add_object(net, name=name, parent=parent_index)

        data = composed_model_to_net_data(model)
        by_name = {f["name"]: f["graphics"] for f in data["objects"]}
        child_a, child_b = by_name["ChildA"], by_name["ChildB"]
        gap = child_b["x"] - (child_a["x"] + child_a["width"])
        assert gap >= CLUSTER_GAP

        parent = by_name["Parent"]
        assert parent["x"] <= min(child_a["x"], child_b["x"])
        assert parent["x"] + parent["width"] >= max(
            child_a["x"] + child_a["width"], child_b["x"] + child_b["width"],
        )

    def test_spread_carries_each_object_members_along_with_its_frame(self):
        """A frame is not a box that merely floats above its contents: its
        geometry is DERIVED from where its members sit, and every member
        stores absolute canvas coordinates. So a spread that slid the box
        alone left the members behind at their original, still-piled spot
        -- every object after the first one rendered with its innards
        heaped outside it (and on top of each other), which is what a net
        generated from chat actually looked like."""
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        for name in ("ObjA", "ObjB", "ObjC"):
            net = PetriNet(name=name)
            net.add_place("P1", tokens=0, x=100, y=200)
            net.add_transition("T1", x=200, y=200)
            model.add_object(net, name=name)

        data = composed_model_to_net_data(model)
        frames = {f["id"]: f["graphics"] for f in data["objects"]}
        assert len(frames) == 3

        for element, (w, h) in [
            *((p, (PLACE_W, PLACE_H)) for p in data["places"]),
            *((t, (TRANS_W, TRANS_H)) for t in data["transitions"]),
        ]:
            frame = frames[element["objectId"]]
            x, y = element["graphics"]["x"], element["graphics"]["y"]
            assert frame["x"] <= x and x + w <= frame["x"] + frame["width"]
            assert frame["y"] <= y and y + h <= frame["y"] + frame["height"]

        # The members moved apart with their frames, not just the frames.
        xs = sorted(p["graphics"]["x"] for p in data["places"])
        assert len(set(xs)) == 3

    def test_spread_carries_nested_children_and_their_members_along(self):
        """Moving a parent has to take its whole subtree: a nested child's
        `graphics` is absolute too, so a child (and the child's own
        members) left behind escapes the parent that owns it."""
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        for parent_name, child_name in [("ParentA", "ChildA"), ("ParentB", "ChildB")]:
            parent_net = PetriNet(name=parent_name)
            parent_net.add_place("PP", tokens=0, x=100, y=100)
            parent_index = model.add_object(parent_net, name=parent_name).index
            child_net = PetriNet(name=child_name)
            child_net.add_place("CP", tokens=0, x=300, y=100)
            model.add_object(child_net, name=child_name, parent=parent_index)

        data = composed_model_to_net_data(model)
        by_name = {f["name"]: f for f in data["objects"]}

        for parent_name, child_name in [("ParentA", "ChildA"), ("ParentB", "ChildB")]:
            parent, child = by_name[parent_name]["graphics"], by_name[child_name]["graphics"]
            assert parent["x"] <= child["x"]
            assert child["x"] + child["width"] <= parent["x"] + parent["width"]

        frames = {f["id"]: f["graphics"] for f in data["objects"]}
        for place in data["places"]:
            frame = frames[place["objectId"]]
            x, y = place["graphics"]["x"], place["graphics"]["y"]
            assert frame["x"] <= x and x + PLACE_W <= frame["x"] + frame["width"]
            assert frame["y"] <= y and y + PLACE_H <= frame["y"] + frame["height"]

    def _fan_out_model(self) -> ComposedModel:
        """Gen feeds two machines that both feed one counter -- the shape
        where "parallel" and "sequential" have to be told apart.

        Place ids are spelled out because each PetriNet numbers its own
        from p1: a hand-built ComposedModel gets none of the cross-object
        id reservation PetriNetSession does, and links address elements BY
        ID, so two objects both owning a "p1" would resolve to whichever
        was written last."""
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        # Each object WRITES to the place it hands off from and READS from
        # the one it picks up at -- that is what tells a fusion's direction
        # apart from the order its arguments were written in, so a fixture
        # of bare places would be testing nothing.
        gen = PetriNet(name="Gen")
        gen.add_place("Out", tokens=0, x=100, y=100, place_id="gen_out")
        emit = gen.add_transition("Emit")
        gen.add_arc(source_id=emit.id, target_id="gen_out")
        model.add_object(gen, name="Gen")
        for name in ("P1", "P2"):
            net = PetriNet(name=name)
            net.add_place("In", tokens=0, x=100, y=100, place_id=f"{name}_in")
            net.add_place("Out", tokens=0, x=300, y=100, place_id=f"{name}_out")
            work = net.add_transition("Work")
            net.add_arc(source_id=f"{name}_in", target_id=work.id)
            net.add_arc(source_id=work.id, target_id=f"{name}_out")
            model.add_object(net, name=name)
        counter = PetriNet(name="Counter")
        counter.add_place("In", tokens=0, x=100, y=100, place_id="counter_in")
        counter.add_place("Total", tokens=0, x=300, y=100, place_id="counter_total")
        tally = counter.add_transition("Tally")
        counter.add_arc(source_id="counter_in", target_id=tally.id)
        counter.add_arc(source_id=tally.id, target_id="counter_total")
        model.add_object(counter, name="Counter")
        model.add_link(LinkType.PLACE_FUSION, source_object=1, source_element=0,
                       target_object=2, target_element=0)
        model.add_link(LinkType.PLACE_FUSION, source_object=1, source_element=0,
                       target_object=3, target_element=0)
        model.add_link(LinkType.PLACE_FUSION, source_object=2, source_element=1,
                       target_object=4, target_element=0)
        model.add_link(LinkType.PLACE_FUSION, source_object=3, source_element=1,
                       target_object=4, target_element=0)
        return model

    def test_parallel_objects_share_a_column_and_stack(self):
        """Neither machine comes before the other, which is what parallel
        means, so they stand across from each other rather than one after
        the other."""
        data = composed_model_to_net_data(self._fan_out_model())
        frames = {f["name"]: f["graphics"] for f in data["objects"]}
        assert frames["P1"]["x"] == frames["P2"]["x"]
        assert abs(frames["P1"]["y"] - frames["P2"]["y"]) >= frames["P1"]["height"]

    def test_sequential_objects_step_along_the_flow(self):
        data = composed_model_to_net_data(self._fan_out_model())
        frames = {f["name"]: f["graphics"] for f in data["objects"]}
        assert frames["Gen"]["x"] < frames["P1"]["x"] < frames["Counter"]["x"]

    def test_tb_transposes_the_whole_table(self):
        """Same cells, other axis: parallel branches stand side by side and
        each step moves down."""
        data = composed_model_to_net_data(self._fan_out_model(), "TB")
        frames = {f["name"]: f["graphics"] for f in data["objects"]}
        assert frames["P1"]["y"] == frames["P2"]["y"]
        assert abs(frames["P1"]["x"] - frames["P2"]["x"]) >= frames["P1"]["width"]
        assert frames["Gen"]["y"] < frames["P1"]["y"] < frames["Counter"]["y"]

    def test_a_column_is_centred_across_the_widest_one(self):
        data = composed_model_to_net_data(self._fan_out_model())
        frames = {f["name"]: f["graphics"] for f in data["objects"]}
        def middle(frame):
            return frame["y"] + frame["height"] / 2
        branches = (middle(frames["P1"]) + middle(frames["P2"])) / 2
        assert abs(middle(frames["Gen"]) - branches) < 1

    def test_members_travel_with_their_frame_when_it_is_placed(self):
        data = composed_model_to_net_data(self._fan_out_model())
        frames = {f["id"]: f["graphics"] for f in data["objects"]}
        for place in data["places"]:
            frame = frames[place["objectId"]]
            x, y = place["graphics"]["x"], place["graphics"]["y"]
            assert frame["x"] <= x and x + PLACE_W <= frame["x"] + frame["width"]
            assert frame["y"] <= y and y + PLACE_H <= frame["y"] + frame["height"]

    def test_unlinked_objects_still_step_along_the_flow(self):
        """The agent builds every object first and links them last, so an
        empty graph is a half-finished model, not a claim that everything
        is parallel. Piling them into one column mid-build and unpiling
        them at the end would be a worse answer than leaving them in the
        row they were already in."""
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        for name in ("A", "B", "C"):
            net = PetriNet(name=name)
            net.add_place("P", tokens=0, x=100, y=100)
            model.add_object(net, name=name)

        frames = {
            f["name"]: f["graphics"] for f in composed_model_to_net_data(model)["objects"]
        }
        xs = [frames[name]["x"] for name in ("A", "B", "C")]
        assert xs == sorted(xs) and len(set(xs)) == 3

    def test_a_parents_own_elements_are_not_buried_under_its_children(self):
        """A Petri-object may hold plain places and other objects at once.
        The parent's own elements are laid out by the parent's own builder,
        which knows nothing of the child frames, so the children have to be
        placed clear of them -- the same rule that keeps a top-level object
        off the free pool."""
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        parent_net = PetriNet(name="Line")
        parent_net.add_place("Buffer", tokens=0, x=100, y=100, place_id="line_buf")
        parent_index = model.add_object(parent_net, name="Line").index
        for name in ("Loader", "Press"):
            net = PetriNet(name=name)
            net.add_place("P", tokens=0, x=100, y=100, place_id=f"{name}_p")
            model.add_object(net, name=name, parent=parent_index)

        data = composed_model_to_net_data(model)
        frames = {f["name"]: f["graphics"] for f in data["objects"]}
        buffer = next(p for p in data["places"] if p["id"] == "line_buf")
        bx, by = buffer["graphics"]["x"], buffer["graphics"]["y"]

        for child in ("Loader", "Press"):
            box = frames[child]
            assert not (
                bx < box["x"] + box["width"]
                and box["x"] < bx + PLACE_W
                and by < box["y"] + box["height"]
                and box["y"] < by + PLACE_H
            ), f"the parent's own place sits on top of {child}"

    def test_a_parent_still_encloses_everything_it_owns(self):
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        parent_net = PetriNet(name="Line")
        parent_net.add_place("Buffer", tokens=0, x=100, y=100, place_id="line_buf")
        parent_index = model.add_object(parent_net, name="Line").index
        child = PetriNet(name="Loader")
        child.add_place("P", tokens=0, x=100, y=100, place_id="loader_p")
        model.add_object(child, name="Loader", parent=parent_index)

        data = composed_model_to_net_data(model)
        frames = {f["name"]: f["graphics"] for f in data["objects"]}
        line, loader = frames["Line"], frames["Loader"]
        assert line["x"] <= loader["x"]
        assert loader["x"] + loader["width"] <= line["x"] + line["width"]
        assert line["y"] <= loader["y"]
        assert loader["y"] + loader["height"] <= line["y"] + line["height"]

    def test_a_fusion_written_backwards_still_flows_forwards(self):
        """A place fusion says two places are ONE place; which of them was
        named first is not a fact about the model. Reading it as one drew a
        counter object before the machine feeding it, because the agent had
        named the counter first."""
        model = self._fan_out_model()
        # Same model, every fusion stated the other way round.
        for link in model.links:
            link.source_object, link.target_object = link.target_object, link.source_object
            link.source_element, link.target_element = link.target_element, link.source_element

        frames = {
            f["name"]: f["graphics"] for f in composed_model_to_net_data(model)["objects"]
        }
        assert frames["Gen"]["x"] < frames["P1"]["x"] < frames["Counter"]["x"]

    def test_a_shared_queue_creates_no_ordering(self):
        """Both objects READ from the fused place, so neither follows the
        other: they are peers drawing on one queue. Asserted on the rule
        itself rather than on coordinates, because where two objects with
        no other relation end up is a layout choice, whereas whether one
        depends on the other is a fact about the model."""
        link = {"type": "placeFusion", "sourceId": "a_q", "targetId": "b_q"}
        produced, consumed = set(), {"a_q", "b_q"}

        assert _flow_between(link, produced, consumed) is None

    def test_a_hand_off_flows_from_the_writer_to_the_reader(self):
        link = {"type": "placeFusion", "sourceId": "out", "targetId": "in"}
        assert _flow_between(link, {"out"}, {"in"}) == ("out", "in")
        # Stated the other way round, the same hand-off still flows the
        # same way: which argument came first is not a fact about the model.
        backwards = {"type": "placeFusion", "sourceId": "in", "targetId": "out"}
        assert _flow_between(backwards, {"out"}, {"in"}) == ("out", "in")

    def test_a_transition_to_place_link_is_taken_as_written(self):
        """That one IS directed: a transition delivers INTO a place."""
        link = {"type": "transitionToPlace", "sourceId": "t1", "targetId": "p1"}
        assert _flow_between(link, set(), set()) == ("t1", "p1")

    def test_locked_frame_is_never_moved_by_the_spread_pass(self):
        """A deliberately hand-positioned (auto_fit=False) frame keeps its
        exact spot even if an unlocked sibling would otherwise overlap it;
        the unlocked one makes room instead."""
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        locked_net = PetriNet(name="Locked")
        locked_net.add_place("P1", tokens=0, x=0, y=0)
        model.add_object(locked_net, name="Locked", x=0, y=0, width=100, height=100, auto_fit=False)
        loose_net = PetriNet(name="Loose")
        loose_net.add_place("P1", tokens=0, x=10, y=10)  # overlaps Locked's box
        model.add_object(loose_net, name="Loose")

        data = composed_model_to_net_data(model)
        by_name = {f["name"]: f["graphics"] for f in data["objects"]}
        assert by_name["Locked"] == {"x": 0.0, "y": 0.0, "width": 100.0, "height": 100.0}
        assert by_name["Loose"]["x"] >= by_name["Locked"]["x"] + by_name["Locked"]["width"] + CLUSTER_GAP

    def test_link_round_trips_to_id_addressed_form(self):
        model = ComposedModel(name="X")
        model.add_object(PetriNet(name="Free"), free=True)
        net_a = PetriNet(name="A")
        p_a = net_a.add_place("PA", tokens=1)
        model.add_object(net_a, name="ObjA")
        net_b = PetriNet(name="B")
        p_b = net_b.add_place("PB", tokens=0)
        model.add_object(net_b, name="ObjB")
        model.add_link(LinkType.PLACE_FUSION, source_object=1, source_element=0, target_object=2, target_element=0)

        data = composed_model_to_net_data(model)
        assert len(data["links"]) == 1
        link = data["links"][0]
        assert link["type"] == "placeFusion"
        assert link["sourceId"] == p_a.id
        assert link["targetId"] == p_b.id


class TestRoundTrip:
    def test_flat_net_data_round_trips_without_objects_or_links_keys(self):
        net_data = _flat_net_data()
        model = net_data_to_composed_model(net_data)
        back = composed_model_to_net_data(model)
        assert "objects" not in back
        assert "links" not in back
        assert [p["id"] for p in back["places"]] == ["p1"]
        assert [t["id"] for t in back["transitions"]] == ["t1"]
        assert [a["id"] for a in back["arcs"]] == ["arc1"]

    def test_place_transition_arc_link_ids_survive_the_round_trip(self):
        net_data = _two_object_fused_net_data()
        model = net_data_to_composed_model(net_data)
        back = composed_model_to_net_data(model)

        assert {p["id"] for p in back["places"]} == {"p1", "p2", "p3"}
        assert {t["id"] for t in back["transitions"]} == {"t1", "t2"}
        assert {a["id"] for a in back["arcs"]} == {"a1", "a2"}
        assert len(back["links"]) == 1
        assert back["links"][0]["sourceId"] == "p2"
        assert back["links"][0]["targetId"] == "p3"
        assert back["links"][0]["type"] == "placeFusion"

    def test_free_pool_members_survive_with_no_object_id(self):
        net_data = _two_object_fused_net_data()
        model = net_data_to_composed_model(net_data)
        back = composed_model_to_net_data(model)
        free_place = next(p for p in back["places"] if p["id"] == "p1")
        assert "objectId" not in free_place

    def test_frame_names_priorities_and_geometry_survive(self):
        # autoFit=False: geometry only ever round-trips byte-for-byte when
        # auto-fit is locked (a deliberate resize) -- otherwise it is
        # legitimately recomputed from current members on every export, see
        # _resolve_object_bounds's docstring. Without this, a plain "does
        # geometry survive" fixture with no autoFit key would exercise the
        # unlocked (default) path and assert the WRONG contract.
        net_data = _two_object_fused_net_data()
        for frame in net_data["objects"]:
            frame["autoFit"] = False
        model = net_data_to_composed_model(net_data)
        back = composed_model_to_net_data(model)
        by_name = {f["name"]: f for f in back["objects"]}
        assert by_name["ObjA"]["priority"] == 3
        assert by_name["ObjA"]["graphics"] == {"x": 80.0, "y": -20.0, "width": 200.0, "height": 150.0}
        assert by_name["ObjB"]["priority"] == 1

    def test_a_second_pass_is_stable(self):
        """Frame ids are minted (not preserved) through this converter --
        see module docstring -- but that minting is deterministic, so a
        SECOND round trip changes nothing further: this is the property
        that actually matters (idempotent after the first normalization),
        not literal preservation of a hand-authored frame id string."""
        net_data = _two_object_fused_net_data()
        first = composed_model_to_net_data(net_data_to_composed_model(net_data))
        second = composed_model_to_net_data(net_data_to_composed_model(first))
        assert first == second

    def test_nesting_survives_the_round_trip(self):
        net_data = _two_object_fused_net_data()
        net_data["objects"][1]["objectId"] = "o1"  # ObjB nested inside ObjA
        model = net_data_to_composed_model(net_data)
        back = composed_model_to_net_data(model)
        by_name = {f["name"]: f for f in back["objects"]}
        assert by_name["ObjB"]["objectId"] == by_name["ObjA"]["id"]
        assert "objectId" not in by_name["ObjA"]

    def test_round_trip_survives_an_element_id_shaped_like_a_minted_link_id(self):
        """A hand-authored element id that happens to look exactly like an
        id this converter would ITSELF mint for something else entirely (a
        place literally id'd "link1", the same shape
        composed_model_to_net_data mints for a link's own id -- see the
        module docstring's now-corrected claim about which ids survive)
        must not corrupt anything: element ids, frame ids, and link ids
        are three separate namespaces this converter never conflates, so a
        link referencing this element must keep referencing exactly it."""
        net_data = _two_object_fused_net_data()
        for p in net_data["places"]:
            if p["id"] == "p2":
                p["id"] = "link1"
        for a in net_data["arcs"]:
            if a["source_id"] == "p2":
                a["source_id"] = "link1"
        net_data["links"][0]["sourceId"] = "link1"

        model = net_data_to_composed_model(net_data)
        back = composed_model_to_net_data(model)

        assert {p["id"] for p in back["places"]} == {"p1", "link1", "p3"}
        assert len(back["links"]) == 1
        assert back["links"][0]["sourceId"] == "link1"
        assert back["links"][0]["targetId"] == "p3"
        # The link's OWN id is independently (re-)minted, "link1" too by
        # array position -- coexisting fine with an ELEMENT that happens
        # to share the exact same string, since the two are never compared
        # against each other anywhere in this converter.
        assert back["links"][0]["id"] == "link1"


def _random_composed_net_data(rng: random.Random) -> dict:
    """One structurally-valid, randomly-shaped composed net_data document:
    0-3 named objects (some possibly nested), 1-3 places and 1-2
    transitions per object (and the free pool), a handful of bipartite
    arcs (local or boundary-crossing, NORMAL only -- the crossing READ
    direction is exercised by its own dedicated, deliberately-adversarial
    tests above, not fuzzed here), and maybe one placeFusion link (its two
    endpoints picked from ALL places regardless of owner, so this
    sometimes exercises the same-owner healing path too).
    """
    n_objects = rng.randint(0, 3)
    object_ids = [f"o{i + 1}" for i in range(n_objects)]
    objects = [
        {
            "id": oid, "name": f"Obj{i + 1}", "priority": rng.randint(0, 5),
            "graphics": {
                "x": float(rng.randint(0, 500)), "y": float(rng.randint(0, 500)),
                "width": 160.0, "height": 100.0,
            },
        }
        for i, oid in enumerate(object_ids)
    ]
    for i, obj in enumerate(objects):
        if i > 0 and rng.random() < 0.3:
            obj["objectId"] = objects[rng.randint(0, i - 1)]["id"]

    owners = [None, *object_ids]  # None = the free pool
    places: list[dict] = []
    transitions: list[dict] = []
    elements_by_owner: dict[str | None, list[tuple[str, str]]] = {owner: [] for owner in owners}
    pid = tid = 1
    for owner in owners:
        for _ in range(rng.randint(1, 3)):
            place_id = f"p{pid}"
            pid += 1
            place = {
                "id": place_id, "name": place_id, "tokens": rng.randint(0, 3),
                "graphics": {"x": float(rng.randint(0, 500)), "y": float(rng.randint(0, 500))},
            }
            if owner is not None:
                place["objectId"] = owner
            places.append(place)
            elements_by_owner[owner].append((place_id, "place"))
        for _ in range(rng.randint(1, 2)):
            trans_id = f"t{tid}"
            tid += 1
            trans = {
                "id": trans_id, "name": trans_id, "priority": 1, "distribution": None,
                "mean_delay": 0.0, "standard_deviation": 0.0, "probability": None,
                "graphics": {"x": float(rng.randint(0, 500)), "y": float(rng.randint(0, 500))},
            }
            if owner is not None:
                trans["objectId"] = owner
            transitions.append(trans)
            elements_by_owner[owner].append((trans_id, "transition"))

    all_elements = [el for owner in owners for el in elements_by_owner[owner]]
    place_ids = [eid for eid, kind in all_elements if kind == "place"]
    trans_ids = [eid for eid, kind in all_elements if kind == "transition"]

    arcs: list[dict] = []
    for i in range(rng.randint(1, 6)):
        p, t = rng.choice(place_ids), rng.choice(trans_ids)
        src, tgt = (p, t) if rng.random() < 0.5 else (t, p)
        arcs.append({"id": f"a{i + 1}", "source_id": src, "target_id": tgt, "weight": 1, "arc_type": "NORMAL"})

    links: list[dict] = []
    if len(place_ids) >= 2 and rng.random() < 0.6:
        a, b = rng.sample(place_ids, 2)
        links.append({"id": "link1", "type": "placeFusion", "sourceId": a, "targetId": b, "quantity": 1})

    return {
        "name": "Random", "places": places, "transitions": transitions,
        "arcs": arcs, "objects": objects, "links": links,
    }


class TestRandomizedRoundTrip:
    """A few dozen randomly-shaped documents (plain `random`, fixed seed --
    no hypothesis dependency), each checked for the two properties that
    actually matter for a converter with no field-level oracle to compare
    against: place/transition ids survive untouched (arc/frame/link ids do
    not, by design -- see the module docstring), and a second round trip
    changes nothing further past the first normalization pass."""

    def test_place_and_transition_ids_survive_and_a_second_pass_is_stable(self):
        rng = random.Random(42)
        for _ in range(30):
            net_data = _random_composed_net_data(rng)
            model = net_data_to_composed_model(net_data)
            back = composed_model_to_net_data(model)

            assert {p["id"] for p in back["places"]} == {p["id"] for p in net_data["places"]}
            assert {t["id"] for t in back["transitions"]} == {t["id"] for t in net_data["transitions"]}

            second = composed_model_to_net_data(net_data_to_composed_model(back))
            assert back == second
