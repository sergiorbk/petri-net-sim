"""Tests for PetriNetSession's composed structure (contract part A): the
free pool / named objects / active-object routing / links, and the session's
own to_net_data/from_net_data round trip.

Backward compatibility (a session never touched by object tools serializes
byte-identical net_data to today's flat shape) is covered first and is the
one non-negotiable property of this whole change; everything else builds on
top of it.
"""

from __future__ import annotations

import pytest

from src.core.security_config import security_settings
from src.domain.composed import LinkType
from src.services.petri.agent_toolkit.operations import op_add_arc, op_add_place, op_add_transition
from src.services.petri.builder import PetriNetBuilder
from src.services.petri.composed_convert import net_data_to_composed_model
from src.services.petri.session import ModelSession, PetriNetSession, SessionObject


def _net_shape(net) -> tuple:
    """Everything about a net that a refused split must leave untouched."""
    return (
        tuple(sorted(p.id for p in net.places)),
        tuple(sorted(t.id for t in net.transitions)),
        tuple(sorted((a.source_id, a.target_id) for a in net.arcs)),
    )


class TestBackwardCompatibility:
    """The non-negotiable property: a session no object tool ever touches
    must serialize (and round-trip) exactly as it did before this change."""

    def test_fresh_session_has_no_objects_or_links(self):
        session = PetriNetSession()
        assert session.objects == []
        assert session.links == []
        assert session.active_object_index is None

    def test_untouched_session_to_net_data_has_no_composed_keys(self):
        session = PetriNetSession()
        session.builder.add_generator("Gen1", interval=10.0)
        data = session.to_net_data()
        assert "objects" not in data
        assert "links" not in data
        assert set(data.keys()) == {
            "name", "places", "transitions", "arcs",
            "_last_output_place_id", "_has_custom_topology", "_is_optimized",
            "_last_simulation_result_text", "_pattern_instances",
            "_layout_direction", "_custom_layout_locked", "_cluster_bounds",
        }

    def test_untouched_session_matches_a_plain_flat_reconstruction(self):
        """The exact byte-identical claim: build the same net two ways (one
        through PetriNetSession, one directly through PetriNetBuilder) and
        confirm to_net_data agrees on every key."""
        session = PetriNetSession()
        session.builder.add_generator("Gen1", interval=10.0)
        session.builder.add_machine("M1", processing_time=5.0)

        builder = PetriNetBuilder()
        builder.add_generator("Gen1", interval=10.0)
        builder.add_machine("M1", processing_time=5.0)
        expected = builder.net.model_dump()
        expected["_last_output_place_id"] = None
        expected["_has_custom_topology"] = False
        expected["_is_optimized"] = session.to_net_data()["_is_optimized"]
        expected["_last_simulation_result_text"] = None
        expected.update(builder.extra_state())

        assert session.to_net_data() == expected

    def test_flat_net_data_from_net_data_round_trip_unchanged(self):
        session = PetriNetSession()
        session.builder.add_generator("Gen1", interval=10.0)
        data = session.to_net_data()

        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded.to_net_data() == data
        assert reloaded.objects == []
        assert reloaded.active_object_index is None

    def test_from_net_data_with_empty_objects_and_links_keys_is_still_flat(self):
        """Absent/empty objects and links are equivalent (matches
        frontend/src/types/petri.ts's own PetriNetData comment)."""
        session = PetriNetSession()
        session.builder.add_generator("Gen1", interval=10.0)
        data = session.to_net_data()
        data["objects"] = []
        data["links"] = []

        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded.objects == []
        assert "objects" not in reloaded.to_net_data()

    def test_model_session_is_the_same_class(self):
        assert ModelSession is PetriNetSession


class TestActiveObjectTargeting:
    def test_new_session_active_object_is_free_pool(self):
        session = PetriNetSession()
        assert session.active_object_index is None
        assert session.builder is session._free_builder

    def test_create_object_makes_it_active(self):
        session = PetriNetSession()
        index = session.create_object("Robot")
        assert index == 0
        assert session.active_object_index == 0
        assert session.builder is session.objects[0].builder

    def test_set_active_object_none_returns_to_free_pool(self):
        session = PetriNetSession()
        session.create_object("Robot")
        session.set_active_object(None)
        assert session.active_object_index is None
        assert session.builder is session._free_builder

    def test_set_active_object_out_of_range_raises(self):
        session = PetriNetSession()
        session.create_object("Robot")
        with pytest.raises(ValueError, match="No object at index"):
            session.set_active_object(5)

    def test_create_object_cap_enforced(self, monkeypatch):
        from src.core.security_config import security_settings

        monkeypatch.setattr(security_settings, "SIMULATION_MAX_OBJECTS", 2)
        session = PetriNetSession()
        session.create_object("A")
        session.create_object("B")
        with pytest.raises(ValueError, match="capped at 2"):
            session.create_object("C")

    def test_existing_add_place_operation_targets_the_active_object(self):
        """The whole point: agent_toolkit.operations' op_add_place is
        completely unmodified by this change -- it only ever goes through
        session.builder/session.net, so routing to the active object is
        entirely this session's own doing."""
        session = PetriNetSession()
        op_add_place(session, name="FreePlace", tokens=1)
        session.create_object("Robot")
        op_add_place(session, name="RobotPlace", tokens=0)

        assert [p.name for p in session._free_builder.net.places] == ["FreePlace"]
        assert [p.name for p in session.objects[0].net.places] == ["RobotPlace"]

    def test_existing_add_transition_and_arc_operations_target_the_active_object(self):
        session = PetriNetSession()
        session.create_object("Robot")
        op_add_place(session, name="In", tokens=1)
        op_add_transition(session, name="T")
        place_id = session.objects[0].net.places[0].id
        trans_id = session.objects[0].net.transitions[0].id
        op_add_arc(session, source_id=place_id, target_id=trans_id)

        assert len(session.objects[0].net.arcs) == 1
        assert session._free_builder.net.places == []

    def test_switching_active_object_back_and_forth_preserves_each_ones_state(self):
        session = PetriNetSession()
        session.create_object("A")
        op_add_place(session, name="A_Place", tokens=1)
        session.create_object("B")
        op_add_place(session, name="B_Place", tokens=2)

        session.set_active_object(0)
        assert [p.name for p in session.net.places] == ["A_Place"]
        session.set_active_object(1)
        assert [p.name for p in session.net.places] == ["B_Place"]

    def test_create_network_resets_composed_structure(self):
        session = PetriNetSession()
        session.create_object("A")
        op_add_place(session, name="A_Place")
        session.create_network("Fresh")
        assert session.objects == []
        assert session.active_object_index is None
        assert session.net.name == "Fresh"


class TestEnsurePatternsInObjects:
    """Deterministic fallback for Object net-style mode (chat_node.py's
    DEFAULT_NET_STYLE): the agent is told to give every logical block its
    own object and a smaller/faster model still routinely builds the whole
    thing flat. The patterns it used ARE those blocks, already named and
    delimited in the builder's registry, so the frames get drawn round them
    after the fact -- one per pattern, never one round everything."""

    def _linear_flow(self) -> PetriNetSession:
        """The exact shape a "generator, processor, counter" prompt builds."""
        session = PetriNetSession()
        builder = session.builder
        gen = builder.add_generator("Arrivals", interval=10.0)
        machine = builder.add_machine("Processor", processing_time=20.0)
        exit_ = builder.add_terminator("Counter")
        builder.connect(
            gen.interface.output_place_id, machine.interface.input_place_id
        )
        builder.connect(
            machine.interface.output_place_id, exit_.interface.input_place_id
        )
        return session

    def test_each_pattern_becomes_its_own_object(self):
        session = self._linear_flow()
        assert session.ensure_patterns_in_objects() == [
            "Arrivals", "Processor", "Counter",
        ]
        assert [o.name for o in session.objects] == [
            "Arrivals", "Processor", "Counter",
        ]

    def test_nothing_is_left_loose_in_the_free_pool(self):
        """Including the Transfer transitions `connect` synthesizes, which
        belong to no pattern and would otherwise be stranded."""
        session = self._linear_flow()
        session.ensure_patterns_in_objects()
        assert session._free_builder.net.places == []
        assert session._free_builder.net.transitions == []

    def test_objects_are_wired_by_place_fusion(self):
        """`connect`'s pass-through transitions are plumbing a flat net
        needs and a composed model does not: they come out, and the two
        ports they joined are fused instead."""
        session = self._linear_flow()
        session.ensure_patterns_in_objects()
        data = session.to_net_data()
        assert [link["type"] for link in data["links"]] == [
            "placeFusion", "placeFusion",
        ]

    def test_the_connectors_themselves_are_gone(self):
        session = self._linear_flow()
        before = len(session.builder.net.transitions)
        session.ensure_patterns_in_objects()
        after = sum(len(o.net.transitions) for o in session.objects)
        assert after == before - 2
        assert not any(
            t.name.startswith("Transfer")
            for o in session.objects
            for t in o.net.transitions
        )

    def test_both_ports_of_every_hand_off_survive(self):
        """The difference from what the optimizer does to the same shape:
        it deletes one of the two places, which is the seam this pass needs
        to cut along."""
        session = self._linear_flow()
        session.ensure_patterns_in_objects()
        names = [p.name for o in session.objects for p in o.net.places]
        assert "Arrivals_Out" in names and "Processor_Queue" in names
        assert "Processor_Done" in names and "Counter_FinalBuffer" in names

    def test_the_result_is_a_valid_composed_model(self):
        session = self._linear_flow()
        session.ensure_patterns_in_objects()
        model = net_data_to_composed_model(session.to_net_data())
        assert model.validate() == []

    def test_each_object_owns_its_own_pattern_registration(self):
        """The frames are not just boxes: the object's builder has to know
        which of its elements form one machine, or every later layout and
        pattern lookup inside it sees loose places and transitions."""
        session = self._linear_flow()
        session.ensure_patterns_in_objects()
        assert [
            list(o.builder.pattern_instances) for o in session.objects
        ] == [["Arrivals"], ["Processor"], ["Counter"]]
        assert session._free_builder.pattern_instances == {}

    def test_a_net_with_no_patterns_is_left_flat(self):
        """Nothing to separate means nothing to frame. Wrapping a hand-built
        net in one object would say nothing the flat net did not."""
        session = PetriNetSession()
        op_add_place(session, name="P1", tokens=1)
        op_add_transition(session, name="T1")
        place_id = session._free_builder.net.places[0].id
        trans_id = session._free_builder.net.transitions[0].id
        op_add_arc(session, source_id=place_id, target_id=trans_id)

        assert session.ensure_patterns_in_objects() == []
        assert session.objects == []
        assert [p.name for p in session._free_builder.net.places] == ["P1"]

    def test_a_single_pattern_still_gets_its_frame(self):
        """One pattern is a complete decomposition, not a whole-net wrap."""
        session = PetriNetSession()
        session.builder.add_generator("Arrivals", interval=10.0)
        assert session.ensure_patterns_in_objects() == ["Arrivals"]

    def test_inseparable_patterns_are_left_flat_rather_than_framed_as_one(self):
        """Two patterns joined by a place -> transition arc cannot go in
        different objects. Putting them in ONE object instead would be the
        whole-net wrap this pass exists to stop doing, so the net is left
        flat and the failure stays visible."""
        session = PetriNetSession()
        builder = session.builder
        gen = builder.add_generator("Arrivals", interval=10.0)
        machine = builder.add_machine("Processor", processing_time=20.0)
        # Straight into the machine's own start transition, no Transfer.
        start_transition = builder.net.get_transition(
            builder.pattern_instances["Processor"]["transition_ids"][0]
        )
        builder.net.add_arc(
            source_id=gen.interface.output_place_id, target_id=start_transition.id
        )

        assert session.ensure_patterns_in_objects() == []
        assert session.objects == []

    def _welded(self, session: PetriNetSession, pattern: str) -> None:
        """Wire Arrivals straight into a pattern's first transition. No link
        can express a place-to-transition crossing, so the two patterns can
        no longer go in different objects."""
        builder = session.builder
        builder.net.add_arc(
            source_id=builder.pattern_instances["Arrivals"]["output_place_id"],
            target_id=builder.pattern_instances[pattern]["transition_ids"][0],
        )

    def test_patterns_that_cannot_be_split_share_one_object(self):
        """Graceful degradation: only the pair that is genuinely stuck
        together shares a frame, and it is named after both of them rather
        than after one with the other hidden inside."""
        session = self._linear_flow()
        self._welded(session, "Processor")

        assert session.ensure_patterns_in_objects() == [
            "Arrivals_Processor", "Counter",
        ]

    def test_a_connector_inside_one_object_is_kept_not_fused(self):
        """A place-fusion link between two places of the SAME object is
        healed away, so dissolving that connector would delete the hand-off
        instead of re-stating it."""
        session = self._linear_flow()
        self._welded(session, "Processor")
        session.ensure_patterns_in_objects()

        merged = next(o for o in session.objects if o.name == "Arrivals_Processor")
        assert any(t.name.startswith("Transfer") for t in merged.net.transitions)
        data = session.to_net_data()
        assert [link["type"] for link in data["links"]] == ["placeFusion"]

    def test_a_refused_split_leaves_the_connectors_in_place(self):
        """Removing a connector severs the only path between two patterns,
        and only a link between two objects puts it back. A run that
        dissolved and then declined to frame would leave the flow cut, so
        the decision is made before anything is removed."""
        session = self._linear_flow()
        self._welded(session, "Processor")
        self._welded(session, "Counter")
        before = _net_shape(session.builder.net)

        assert session.ensure_patterns_in_objects() == []

        assert session.objects == []
        assert _net_shape(session.builder.net) == before

    def test_hitting_the_object_cap_leaves_the_net_untouched(self, monkeypatch):
        """Same rule: framing some of the groups and stranding the rest
        would cut the flow between the two halves."""
        monkeypatch.setattr(security_settings, "SIMULATION_MAX_OBJECTS", 2)
        session = self._linear_flow()
        before = _net_shape(session.builder.net)

        assert session.ensure_patterns_in_objects() == []

        assert session.objects == []
        assert _net_shape(session.builder.net) == before

    def test_empty_free_pool_is_a_noop(self):
        session = PetriNetSession()
        assert session.ensure_patterns_in_objects() == []
        assert session.objects == []

    def test_never_touches_a_session_that_already_has_an_object(self):
        """Not a policy override of a deliberate structure the agent
        already built -- only the "built nothing but flat" case."""
        session = PetriNetSession()
        session.create_object("Existing")
        op_add_place(session, name="InObject")
        session.set_active_object(None)
        session.builder.add_generator("Arrivals", interval=10.0)

        assert session.ensure_patterns_in_objects() == []
        assert [o.name for o in session.objects] == ["Existing"]

    def test_active_object_ends_at_free_pool(self):
        session = self._linear_flow()
        session.ensure_patterns_in_objects()
        assert session.active_object_index is None


class TestIdCollisionMitigation:
    """Best-effort mitigation documented in session.py's _reserve_known_ids:
    place/transition auto-ids stay unique across the whole session, not
    just within whichever net happens to be active."""

    def test_place_ids_do_not_collide_across_objects(self):
        session = PetriNetSession()
        op_add_place(session, name="FreePlace")
        session.create_object("A")
        op_add_place(session, name="A_Place")
        session.create_object("B")
        op_add_place(session, name="B_Place")

        all_ids = [p.id for p in session._free_builder.net.places]
        for obj in session.objects:
            all_ids.extend(p.id for p in obj.net.places)
        assert len(all_ids) == len(set(all_ids))

    def test_transition_ids_do_not_collide_across_objects(self):
        session = PetriNetSession()
        session.create_object("A")
        op_add_transition(session, name="A_T")
        session.create_object("B")
        op_add_transition(session, name="B_T")

        all_ids = []
        for obj in session.objects:
            all_ids.extend(t.id for t in obj.net.transitions)
        assert len(all_ids) == len(set(all_ids))


class TestComposedRoundTrip:
    def _two_object_session_with_fusion(self) -> PetriNetSession:
        session = PetriNetSession()
        op_add_place(session, name="FreePlace", tokens=1)

        session.create_object("ObjA", priority=3)
        op_add_place(session, name="A_In", tokens=0)
        op_add_transition(session, name="A_T")
        a_place = session.net.places[0].id
        a_trans = session.net.transitions[0].id
        op_add_arc(session, source_id=a_place, target_id=a_trans)

        session.create_object("ObjB", priority=1)
        op_add_place(session, name="B_In", tokens=0)
        op_add_transition(session, name="B_T")
        b_place = session.net.places[0].id
        b_trans = session.net.transitions[0].id
        op_add_arc(session, source_id=b_place, target_id=b_trans)

        session.add_link(
            LinkType.PLACE_FUSION,
            session.objects[0].frame_id, a_place,
            session.objects[1].frame_id, b_place,
        )
        session.set_active_object(None)
        return session

    def test_round_trip_preserves_place_transition_arc_ids(self):
        session = self._two_object_session_with_fusion()
        data = session.to_net_data()
        reloaded = PetriNetSession.from_net_data(data)

        assert reloaded.to_net_data() == data
        place_ids = {p.id for p in reloaded._free_builder.net.places}
        for obj in reloaded.objects:
            place_ids |= {p.id for p in obj.net.places}
        original_ids = {p.id for p in session._free_builder.net.places}
        for obj in session.objects:
            original_ids |= {p.id for p in obj.net.places}
        assert place_ids == original_ids

    def test_round_trip_preserves_frame_ids_exactly(self):
        """Unlike the standalone converter (composed_convert.py), the
        session's OWN round trip does not go through ComposedModel for
        frame identity -- SessionObject keeps the original frame_id
        directly, so it survives byte-for-byte."""
        session = self._two_object_session_with_fusion()
        original_frame_ids = [o.frame_id for o in session.objects]
        data = session.to_net_data()
        reloaded = PetriNetSession.from_net_data(data)
        assert [o.frame_id for o in reloaded.objects] == original_frame_ids

    def test_round_trip_preserves_object_names_and_priorities(self):
        session = self._two_object_session_with_fusion()
        data = session.to_net_data()
        reloaded = PetriNetSession.from_net_data(data)
        assert [(o.name, o.priority) for o in reloaded.objects] == [("ObjA", 3), ("ObjB", 1)]

    def test_round_trip_preserves_links(self):
        session = self._two_object_session_with_fusion()
        data = session.to_net_data()
        reloaded = PetriNetSession.from_net_data(data)
        assert len(reloaded.links) == 1
        link = reloaded.links[0]
        assert link.link_type == LinkType.PLACE_FUSION
        obj_a = next(o for o in reloaded.objects if o.name == "ObjA")
        obj_b = next(o for o in reloaded.objects if o.name == "ObjB")
        assert (link.source_frame_id, link.source_element_id) == (obj_a.frame_id, obj_a.net.places[0].id)
        assert (link.target_frame_id, link.target_element_id) == (obj_b.frame_id, obj_b.net.places[0].id)

    def test_round_trip_preserves_free_pool_contents(self):
        session = self._two_object_session_with_fusion()
        data = session.to_net_data()
        reloaded = PetriNetSession.from_net_data(data)
        assert [p.name for p in reloaded._free_builder.net.places] == ["FreePlace"]

    def test_round_trip_preserves_template_id(self):
        session = PetriNetSession()
        session.create_object("A")
        session.objects[0].template_id = "lib-item-42"
        data = session.to_net_data()
        assert data["objects"][0]["templateId"] == "lib-item-42"

        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded.objects[0].template_id == "lib-item-42"

    def test_round_trip_preserves_nesting(self):
        session = PetriNetSession()
        session.create_object("Outer")
        outer_frame_id = session.objects[0].frame_id
        session.create_object("Inner")
        session.objects[1].parent_frame_id = outer_frame_id

        data = session.to_net_data()
        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded.objects[1].parent_frame_id == reloaded.objects[0].frame_id

    def test_a_composed_session_round_trips_a_second_time_unchanged(self):
        session = self._two_object_session_with_fusion()
        data = session.to_net_data()
        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded.to_net_data() == data


class TestActiveObjectPersistsAcrossRoundTrip:
    """Bug found while writing phase 2's chat-dispatcher end-to-end test
    (contract part E): a chat turn's PetriNetSession is rehydrated fresh
    via from_net_data on every tool_node call, so with no persisted active
    object, a SECOND turn that never repeats set_active_object always fell
    back to the free pool -- a follow-up add_place/add_arc call would
    silently target the wrong net (or, worse, crash the way this exact
    scenario did: the free-pool net had "reserved" id-collision
    placeholders left over from _reserve_ids_everywhere, and this test's
    original failure was "cannot connect reserved to reserved").
    _two_object_session_with_fusion's own fixture (see the class above)
    happens to always call set_active_object(None) right before every
    round trip it tests, which is exactly why this gap went unnoticed
    until a genuinely multi-turn scenario exercised it."""

    def test_active_named_object_survives_a_round_trip(self):
        session = PetriNetSession()
        session.create_object("A")
        session.create_object("B")
        session.set_active_object(0)  # back to A; B was left active by create_object

        data = session.to_net_data()
        assert data["_active_object_id"] == session.objects[0].frame_id

        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded.active_object_index == 0
        assert reloaded.objects[reloaded.active_object_index].name == "A"

    def test_active_free_pool_survives_a_round_trip(self):
        session = PetriNetSession()
        session.create_object("A")
        session.set_active_object(None)

        data = session.to_net_data()
        assert data["_active_object_id"] is None

        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded.active_object_index is None
        assert reloaded.builder is reloaded._free_builder

    def test_add_place_after_reload_lands_in_the_still_active_object_not_the_free_pool(self):
        """The end-to-end proof: exactly the tool_node scenario (session
        serialized after turn 1, rehydrated for turn 2, an ordinary
        add_place call with no explicit set_active_object first)."""
        session = PetriNetSession()
        session.create_object("A")
        op_add_place(session, name="PA", tokens=1)
        data = session.to_net_data()

        reloaded = PetriNetSession.from_net_data(data)
        op_add_place(reloaded, name="PA2", tokens=0)

        assert reloaded.active_object_index == 0
        assert {p.name for p in reloaded.net.places} == {"PA", "PA2"}
        assert reloaded._free_builder.net.places == []

    def test_active_object_removed_between_save_and_reload_falls_back_to_free_pool(self):
        """A defensive edge case, not reachable through the ops layer
        today (no op removes an object while leaving its frame_id
        referenced elsewhere) but cheap to guard: an _active_object_id
        that matches no restored object must not raise, and must not
        silently pick some arbitrary other object either."""
        session = PetriNetSession()
        session.create_object("A")
        data = session.to_net_data()
        data["_active_object_id"] = "not-a-real-frame-id"

        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded.active_object_index is None

    def test_backward_compat_net_data_with_no_active_object_key_falls_back_to_free_pool(self):
        """net_data saved by a session that predates this fix has no
        _active_object_id key at all -- must not raise, must default to
        the free pool exactly like every other missing bookkeeping key."""
        session = PetriNetSession()
        session.create_object("A")
        op_add_place(session, name="PA", tokens=1)
        data = session.to_net_data()
        del data["_active_object_id"]

        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded.active_object_index is None


class TestSessionObject:
    def test_net_property_delegates_to_builder(self):
        builder = PetriNetBuilder(name="X")
        obj = SessionObject(frame_id="o1", builder=builder, name="X")
        assert obj.net is builder.net


class TestPatternNameAsLinkEndpoint:
    """A caller wiring two objects reaches for the name it gave the pattern
    ("TaskQueue"), not for the name that pattern gave one of its places
    ("TaskQueue_Buffer"). That used to be an error listing every element to
    pick from, which cost a whole tool call to recover from and taught
    nothing: the pattern DOES have a well-defined place to mean here, and
    which one it is depends on which end of the link you are."""

    def _session(self) -> PetriNetSession:
        session = PetriNetSession()
        session.create_object("Generator")
        session.builder.add_generator("TaskSource", interval=10.0)
        session.create_object("Queue")
        session.builder.add_buffer("TaskQueue")
        return session

    def test_a_source_endpoint_resolves_to_the_pattern_output(self):
        session = self._session()
        instance = session.objects[0].builder.pattern_instances["TaskSource"]
        _, element_id, kind = session.resolve_element_ref(
            "Generator", "TaskSource", role="source"
        )
        assert element_id == instance["output_place_id"]
        assert kind == "place"

    def test_a_target_endpoint_resolves_to_the_pattern_input(self):
        session = self._session()
        session.create_object("Machine")
        session.builder.add_machine("CPU", processing_time=5.0)
        instance = session.objects[2].builder.pattern_instances["CPU"]
        _, element_id, _ = session.resolve_element_ref(
            "Machine", "CPU", role="target"
        )
        assert element_id == instance["input_place_id"]

    def test_an_element_of_its_own_still_wins(self):
        """The fallback only runs when nothing else matched, so a place
        actually called by that name is never shadowed."""
        session = self._session()
        _, element_id, _ = session.resolve_element_ref(
            "Queue", "TaskQueue_Buffer", role="source"
        )
        place = next(
            p for p in session.objects[1].net.places if p.name == "TaskQueue_Buffer"
        )
        assert element_id == place.id

    def test_a_sink_cannot_be_a_source_and_says_why(self):
        session = self._session()
        session.create_object("Exit")
        session.builder.add_terminator("Done")
        with pytest.raises(ValueError, match="terminator, which produces nothing"):
            session.resolve_element_ref("Exit", "Done", role="source")

    def test_a_source_cannot_be_a_target_and_says_why(self):
        session = self._session()
        with pytest.raises(ValueError, match="generator, which receives nothing"):
            session.resolve_element_ref("Generator", "TaskSource", role="target")

    def test_an_unknown_name_lists_what_is_there_and_asks_for_names(self):
        """An invented id is the common way this fails -- ids are handed
        out in creation order across the whole session, so a plausible
        guess lands on a neighbour's element or on nothing. The list is
        there to recover from without a second call, and it says to reach
        for the name in it rather than the id beside it."""
        session = self._session()
        with pytest.raises(ValueError) as raised:
            session.resolve_element_ref("Queue", "t99", role="source")
        message = str(raised.value)
        assert "by NAME rather than by id" in message
        assert "TaskQueue_Buffer" in message


class TestNestedObjects:
    """A Petri-object may hold plain places and transitions and other
    Petri-objects at the same time. The frame, the layout and the
    serializer always supported it; only the way to ask for it was
    missing."""

    def _line(self) -> PetriNetSession:
        session = PetriNetSession()
        session.create_object("Line")
        session.builder.add_buffer("LineBuffer")
        session.create_object("Loader", parent="Line")
        session.builder.add_generator("Feed", interval=5.0)
        session.create_object("Press", parent="Line")
        session.builder.add_machine("Stamp", processing_time=12.0)
        return session

    def test_a_child_records_its_parent(self):
        session = self._line()
        line, loader, press = session.objects
        assert loader.parent_frame_id == line.frame_id
        assert press.parent_frame_id == line.frame_id
        assert line.parent_frame_id is None

    def test_the_nesting_survives_serialization(self):
        data = self._line().to_net_data()
        frames = {f["name"]: f for f in data["objects"]}
        assert frames["Loader"]["objectId"] == frames["Line"]["id"]
        assert "objectId" not in frames["Line"] or frames["Line"].get("objectId") is None

    def test_a_parent_keeps_its_own_elements_alongside_its_children(self):
        data = self._line().to_net_data()
        line_id = next(f["id"] for f in data["objects"] if f["name"] == "Line")
        own = [p["name"] for p in data["places"] if p.get("objectId") == line_id]
        assert own == ["LineBuffer_Buffer"]

    def test_an_unknown_parent_says_how_to_recover(self):
        """Naming a parent that does not exist is an ordering slip, not a
        change of plan. A bare "no such object" invites dropping the
        nesting and creating the child flat, which throws away the
        structure the caller was describing -- so the message says what to
        do instead."""
        session = PetriNetSession()
        session.create_object("Intake")
        with pytest.raises(ValueError) as raised:
            session.create_object("Line1", parent="Plant")
        message = str(raised.value)
        assert "create_object('Plant')" in message
        assert "Do not drop the nesting" in message
        assert "Intake" in message  # still lists what does exist


class TestApplyLayoutDirection:
    """The build direction is the user's choice, applied to the whole
    session rather than to whichever object happened to be active -- every
    part of a composed model carries its own PetriNetBuilder, so a
    direction set on one only would leave the rest flowing the other way.
    """

    def _composed_session(self) -> PetriNetSession:
        session = PetriNetSession()
        session.builder.add_generator("FreeGen", interval=10.0)
        session.create_object("Machine")
        session.builder.add_machine("Mach", processing_time=20.0)
        session.create_object("Exit")
        session.builder.add_terminator("Done")
        return session

    def test_every_part_of_the_model_is_relaid(self):
        session = self._composed_session()
        changed = session.apply_layout_direction("TB")
        assert set(changed) == {"free pool", "Machine", "Exit"}
        assert session.objects[0].builder.layout_direction == "TB"
        assert session.objects[1].builder.layout_direction == "TB"

    def test_applying_the_current_direction_changes_nothing(self):
        """Safe to call on every turn: a builder already facing this way is
        left completely alone, so a deliberate manual arrangement survives
        every turn that does not actually change the direction."""
        session = self._composed_session()
        assert session.apply_layout_direction("LR") == []

    def test_a_manual_arrangement_survives_a_no_op_pass(self):
        session = PetriNetSession()
        session.builder.add_generator("Gen", interval=10.0)
        session.builder.add_machine("Mach", processing_time=20.0)
        session.builder.arrange_patterns([{"name": "Gen", "x": 1000.0, "y": 2000.0}])
        placed = {p.id: (p.graphics.x, p.graphics.y) for p in session.builder.net.places}

        assert session.apply_layout_direction("LR") == []

        after = {p.id: (p.graphics.x, p.graphics.y) for p in session.builder.net.places}
        assert after == placed

    def test_changing_direction_does_relay_out(self):
        """The one thing that may undo a manual arrangement is an actual
        change of direction, which is a direct instruction to re-flow."""
        session = PetriNetSession()
        session.builder.add_generator("Gen", interval=10.0)
        session.builder.add_machine("Mach", processing_time=20.0)
        before = {p.id: (p.graphics.x, p.graphics.y) for p in session.builder.net.places}

        assert session.apply_layout_direction("TB") == ["free pool"]

        after = {p.id: (p.graphics.x, p.graphics.y) for p in session.builder.net.places}
        assert after != before

    def test_rejects_a_direction_the_layout_engine_does_not_know(self):
        session = PetriNetSession()
        session.builder.add_generator("Gen", interval=10.0)
        with pytest.raises(ValueError):
            session.apply_layout_direction("sideways")
