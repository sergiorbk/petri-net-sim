"""Tests for the Petri-object operations added to agent_toolkit (contract
phase 2, part B): create_object/set_active_object/list_objects/
rename_object/remove_object, move_elements_to_object, link_objects/
list_links/remove_link, validate_model, and the composed-aware
run_simulation/export_pnml/get_network_status paths.

Everything here goes through the real op_* functions in operations.py --
the same functions both the MCP and chat adapters call via the catalog --
so a test failure here is a failure either agent surface would actually
hit. See test_petri_session_composed.py for the session-level (Part A)
counterpart these build on.
"""

from __future__ import annotations

import pytest

from src.domain.models import PetriNet
from src.services.petri.agent_toolkit import operations as ops
from src.services.petri.agent_toolkit.catalog import build_catalog
from src.services.petri.agent_toolkit.errors import ToolError
from src.services.petri.session import PetriNetSession


def _ok(result) -> str:
    """Assert *result* is a successful (non-ToolError) op result and
    return its text, so a broken op fails the test at the exact call
    site instead of surfacing as a confusing string-vs-ToolError diff
    later in the test."""
    assert not isinstance(result, ToolError), f"expected success, got: {result}"
    return str(result)


def _err(result) -> str:
    """Assert *result* is a ToolError and return its message text."""
    assert isinstance(result, ToolError), f"expected a ToolError, got: {result!r}"
    return result.message


# ---------------------------------------------------------------------------
# Catalog wiring: the new tools are real catalog entries with the expected
# schema narrowing (E's "no changes to either adapter" claim rests on this).
# ---------------------------------------------------------------------------

class TestCatalogWiring:
    _NEW_TOOL_NAMES = (
        "create_object", "set_active_object", "list_objects", "rename_object",
        "remove_object", "move_elements_to_object", "link_objects",
        "list_links", "remove_link", "validate_model",
    )

    @pytest.mark.parametrize("name", _NEW_TOOL_NAMES)
    def test_every_new_tool_is_in_the_catalog(self, name):
        catalog = build_catalog()
        assert name in catalog
        assert catalog[name].description.strip()

    def test_link_type_choices_exclude_the_retired_link_type(self):
        spec = build_catalog()["link_objects"]
        by_name = {p.name: p for p in spec.params}
        assert by_name["link_type"].choices == ("placeFusion", "transitionToPlace")

    def test_no_em_dash_in_new_tool_descriptions(self):
        catalog = build_catalog()
        for name in self._NEW_TOOL_NAMES:
            assert chr(0x2014) not in catalog[name].description, f"{name}: description has an em dash"


# ---------------------------------------------------------------------------
# Object lifecycle
# ---------------------------------------------------------------------------

class TestObjectLifecycle:
    def test_create_object_reports_index_and_how_to_switch_back(self):
        session = PetriNetSession()
        text = _ok(ops.op_create_object(session, name="Loader"))
        assert "'Loader'" in text
        assert "index=0" in text
        assert "set_active_object" in text
        assert session.active_object_index == 0

    def test_create_object_respects_the_cap_with_a_clear_error(self, monkeypatch):
        from src.core.security_config import security_settings

        monkeypatch.setattr(security_settings, "SIMULATION_MAX_OBJECTS", 1)
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        message = _err(ops.op_create_object(session, name="B"))
        assert "capped at 1" in message

    def test_list_objects_on_a_flat_session_says_so(self):
        session = PetriNetSession()
        text = _ok(ops.op_list_objects(session))
        assert "flat" in text.lower()
        assert "create_object" in text

    def test_list_objects_reports_counts_and_active_marker(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="Loader"))
        _ok(ops.op_add_place(session, name="Q", tokens=1))
        _ok(ops.op_create_object(session, name="Sink"))
        text = _ok(ops.op_list_objects(session))
        assert "'Loader'" in text and "1 places" in text
        assert "'Sink' (active)" in text
        assert "[free pool]" in text

    def test_set_active_object_by_name_switches_target(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_create_object(session, name="B"))
        _ok(ops.op_set_active_object(session, name="A"))
        assert session.active_object_index == 0
        _ok(ops.op_add_place(session, name="A_Place"))
        assert [p.name for p in session.objects[0].net.places] == ["A_Place"]
        assert session.objects[1].net.places == []

    def test_set_active_object_none_returns_to_free_pool(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        text = _ok(ops.op_set_active_object(session, name=None))
        assert "free pool" in text
        assert session.active_object_index is None

    def test_set_active_object_unknown_name_names_available_objects(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        message = _err(ops.op_set_active_object(session, name="Ghost"))
        assert "No object named 'Ghost'" in message
        assert "A" in message

    def test_rename_object(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        text = _ok(ops.op_rename_object(session, name="A", new_name="Robot"))
        assert "'A'" in text and "'Robot'" in text
        assert session.objects[0].name == "Robot"

    def test_rename_object_unknown_name_errors(self):
        session = PetriNetSession()
        message = _err(ops.op_rename_object(session, name="Ghost", new_name="X"))
        assert "No object named 'Ghost'" in message

    def test_remove_object_keep_elements_moves_to_free_pool(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_add_place(session, name="P", tokens=2))
        text = _ok(ops.op_remove_object(session, name="A", keep_elements=True))
        assert "moved its elements to the free pool" in text
        assert session.objects == []
        assert [p.name for p in session._free_builder.net.places] == ["P"]

    def test_remove_object_without_keep_elements_deletes_them(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_add_place(session, name="P", tokens=2))
        text = _ok(ops.op_remove_object(session, name="A", keep_elements=False))
        assert "deleted its elements" in text
        assert session.objects == []
        assert session._free_builder.net.places == []

    def test_remove_object_falls_back_to_free_pool_when_it_was_active(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        assert session.active_object_index == 0
        text = _ok(ops.op_remove_object(session, name="A"))
        assert "Active object is now the free pool" in text
        assert session.active_object_index is None

    def test_remove_object_unknown_name_errors(self):
        session = PetriNetSession()
        message = _err(ops.op_remove_object(session, name="Ghost"))
        assert "No object named 'Ghost'" in message


# ---------------------------------------------------------------------------
# Active-object targeting via the ops layer specifically (Part A already
# covers direct session.create_object/set_active_object; this exercises the
# same routing through op_create_object/op_set_active_object).
# ---------------------------------------------------------------------------

class TestActiveObjectTargetingThroughOps:
    def test_add_place_after_op_create_object_targets_the_new_object(self):
        session = PetriNetSession()
        _ok(ops.op_add_place(session, name="FreePlace"))
        _ok(ops.op_create_object(session, name="Robot"))
        _ok(ops.op_add_place(session, name="RobotPlace"))

        assert [p.name for p in session._free_builder.net.places] == ["FreePlace"]
        assert [p.name for p in session.objects[0].net.places] == ["RobotPlace"]

    def test_switching_back_and_forth_via_ops_preserves_each_objects_state(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_add_place(session, name="A_Place"))
        _ok(ops.op_create_object(session, name="B"))
        _ok(ops.op_add_place(session, name="B_Place"))

        _ok(ops.op_set_active_object(session, name="A"))
        assert [p.name for p in session.net.places] == ["A_Place"]
        _ok(ops.op_set_active_object(session, name="B"))
        assert [p.name for p in session.net.places] == ["B_Place"]


# ---------------------------------------------------------------------------
# link_objects / list_links / remove_link
# ---------------------------------------------------------------------------

def _two_linkable_objects() -> tuple[PetriNetSession, str, str, str, str]:
    """Loader (place->transition) and Sink (place->transition->throughput
    place), both active-targeted via ops, wired for a transitionToPlace
    smoke test. Returns (session, loader_place_id, loader_trans_id,
    sink_place_id, sink_trans_id)."""
    session = PetriNetSession()
    _ok(ops.op_create_object(session, name="Loader"))
    _ok(ops.op_add_place(session, name="LoaderQueue", tokens=1))
    _ok(ops.op_add_transition(session, name="LoaderGo"))
    loader_place = session.net.places[0].id
    loader_trans = session.net.transitions[0].id
    _ok(ops.op_add_arc(session, source_id=loader_place, target_id=loader_trans))

    _ok(ops.op_create_object(session, name="Sink"))
    _ok(ops.op_add_place(session, name="SinkIn", tokens=0))
    _ok(ops.op_add_transition(session, name="SinkGo"))
    sink_place = session.net.places[0].id
    sink_trans = session.net.transitions[0].id
    _ok(ops.op_add_arc(session, source_id=sink_place, target_id=sink_trans))

    return session, loader_place, loader_trans, sink_place, sink_trans


class TestLinkObjectsHappyPath:
    def test_transition_to_place_link(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        text = _ok(ops.op_link_objects(
            session, link_type="transitionToPlace",
            source_object="Loader", source_element="LoaderGo",
            target_object="Sink", target_element="SinkIn",
            quantity=3,
        ))
        assert "transitionToPlace" in text
        assert "quantity=3" in text
        assert len(session.links) == 1
        link = session.links[0]
        assert link.quantity == 3

    def test_place_fusion_link(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        text = _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="Loader", source_element="LoaderQueue",
            target_object="Sink", target_element="SinkIn",
        ))
        assert "placeFusion" in text
        assert len(session.links) == 1

    def test_elements_addressable_by_id_too(self):
        session, loader_place, _lt, _sp, sink_trans = _two_linkable_objects()
        # A placeFusion needs two places; address both ends by id here
        # instead of by name, to prove id-based resolution also works.
        text = _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="Loader", source_element=loader_place,
            target_object="Sink", target_element=session.objects[1].net.places[0].id,
        ))
        assert "placeFusion" in text

    def test_free_pool_endpoint(self):
        session = PetriNetSession()
        _ok(ops.op_add_place(session, name="FreeQueue", tokens=1))
        free_place = session.net.places[0].id
        _ok(ops.op_create_object(session, name="Sink"))
        _ok(ops.op_add_place(session, name="SinkIn"))
        sink_place = session.net.places[0].id
        text = _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object=None, source_element=free_place,
            target_object="Sink", target_element=sink_place,
        ))
        assert "the free pool" in text
        assert session.links[0].source_frame_id is None  # the free pool


class TestLinkObjectsInfersLinkType:
    """Omitting link_type is the recommended path (see op_link_objects's
    own docstring): the common real mistake is reaching for
    transitionToPlace to join two places that are really the same buffer
    (that's placeFusion) -- inferring from what the elements actually are
    removes the guess entirely instead of erroring and making the caller
    retry."""

    def test_place_and_place_infers_place_fusion(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        text = _ok(ops.op_link_objects(
            session,
            source_object="Loader", source_element="LoaderQueue",
            target_object="Sink", target_element="SinkIn",
        ))
        assert "placeFusion" in text
        assert session.links[0].link_type.value == "placeFusion"

    def test_transition_and_place_infers_transition_to_place(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        text = _ok(ops.op_link_objects(
            session,
            source_object="Loader", source_element="LoaderGo",
            target_object="Sink", target_element="SinkIn",
        ))
        assert "transitionToPlace" in text
        assert session.links[0].link_type.value == "transitionToPlace"

    def test_place_and_transition_gives_the_retirement_message_not_a_generic_one(self):
        """The exact failure this is meant to prevent: an agent reaching for
        what would have been placeToTransition without saying so."""
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session,
            source_object="Loader", source_element="LoaderQueue",
            target_object="Sink", target_element="SinkGo",
        ))
        assert "retired" in message.lower()

    def test_transition_and_transition_explains_routing_through_a_place(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session,
            source_object="Loader", source_element="LoaderGo",
            target_object="Sink", target_element="SinkGo",
        ))
        assert "transition" in message.lower()
        assert "place" in message.lower()

    def test_explicit_link_type_still_validates_against_the_actual_kinds(self):
        """Omitting link_type infers it; passing one explicitly still
        asserts it and errors if the elements are a different kind --
        unchanged from before this call was made optional."""
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session, link_type="transitionToPlace",
            source_object="Loader", source_element="LoaderQueue",  # place, not transition
            target_object="Sink", target_element="SinkIn",
        ))
        assert "needs a transition as its source" in message


class TestLinkObjectsErrorPaths:
    def test_place_to_transition_is_refused_with_the_retirement_message(self):
        session, _lp, _lt, sp, st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session, link_type="placeToTransition",
            source_object="Loader", source_element="LoaderQueue",
            target_object="Sink", target_element="SinkGo",
        ))
        assert "retired" in message
        assert "place fusion" in message
        assert session.links == []

    def test_unknown_link_type_errors(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session, link_type="bogusType",
            source_object="Loader", source_element="LoaderQueue",
            target_object="Sink", target_element="SinkIn",
        ))
        assert "Unknown link_type 'bogusType'" in message

    def test_quantity_below_one_errors(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session, link_type="transitionToPlace",
            source_object="Loader", source_element="LoaderGo",
            target_object="Sink", target_element="SinkIn",
            quantity=0,
        ))
        assert "quantity must be >= 1" in message

    def test_unknown_source_object_names_it(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="Ghost", source_element="X",
            target_object="Sink", target_element="SinkIn",
        ))
        assert "No object named 'Ghost'" in message

    def test_unknown_element_names_the_object_and_element(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="Loader", source_element="Nope",
            target_object="Sink", target_element="SinkIn",
        ))
        assert "'Nope'" in message
        assert "'Loader'" in message
        # Lists what actually exists there -- a caller reaching for the
        # PATTERN INSTANCE name it just gave add_generator/add_machine/etc.
        # (which is never itself an element id/name) can retry immediately
        # with the right one, instead of a separate list_elements call.
        assert "LoaderQueue" in message
        assert "LoaderGo" in message

    def test_ambiguous_element_name_lists_the_count_and_suggests_id(self):
        p1 = PetriNet(name="Dup")
        p1.add_place("Dup", tokens=0)
        first = p1.model_dump()
        p2 = PetriNet(name="Dup2")
        p2.add_place("Dup", tokens=0)
        second = p2.model_dump()
        second["places"][0]["id"] = "p2"
        net_data = {
            "name": "Dup",
            "places": first["places"] + second["places"],
            "transitions": [], "arcs": [],
        }
        session = PetriNetSession.from_net_data(net_data)
        message = _err(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object=None, source_element="Dup",
            target_object=None, target_element="p1",
        ))
        assert "ambiguous" in message
        assert "matches 2 elements" in message

    def test_source_kind_mismatch_for_place_fusion(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="Loader", source_element="LoaderGo",  # transition, not place
            target_object="Sink", target_element="SinkIn",
        ))
        assert "placeFusion needs a place as its source" in message
        assert "'LoaderGo'" in message
        assert "transition" in message

    def test_source_kind_mismatch_for_transition_to_place(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session, link_type="transitionToPlace",
            source_object="Loader", source_element="LoaderQueue",  # place, not transition
            target_object="Sink", target_element="SinkIn",
        ))
        assert "transitionToPlace needs a transition as its source" in message

    def test_target_kind_mismatch(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        message = _err(ops.op_link_objects(
            session, link_type="transitionToPlace",
            source_object="Loader", source_element="LoaderGo",
            target_object="Sink", target_element="SinkGo",  # transition, not place
        ))
        assert "needs a place as its target" in message


class TestLinkObjectsFusionRules:
    """desktop #61: op_link_objects must refuse a placeFusion link that
    breaks one of ComposedModel.place_fusion_rejection's five rules, not
    just accept it and leave the mistake to surface later at export or
    simulation time. Each of these is a broken fan (or worse) built with
    two or three ordinary tool calls -- exactly the failure mode that used
    to sail through with no error at any layer."""

    @staticmethod
    def _three_linkable_objects() -> tuple[PetriNetSession, str, str, str]:
        session = PetriNetSession()
        places = []
        for name in ("A", "B", "C"):
            _ok(ops.op_create_object(session, name=name))
            _ok(ops.op_add_place(session, name=f"{name}Place", tokens=1 if name == "A" else 0))
            _ok(ops.op_add_transition(session, name=f"{name}Go"))
            places.append(session.net.places[0].id)
            _ok(ops.op_add_arc(session, source_id=places[-1], target_id=session.net.transitions[0].id))
        return session, *places

    def test_a_place_cannot_copy_two_masters(self):
        session, a_place, _b_place, _c_place = self._three_linkable_objects()
        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="A", source_element=a_place,
            target_object="B", target_element="BPlace",
        ))
        message = _err(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="A", source_element=a_place,
            target_object="C", target_element="CPlace",
        ))
        assert "already copies another one" in message
        assert len(session.links) == 1  # the second call left no trace

    def test_reverse_direction_of_an_existing_link_is_refused(self):
        session, a_place, _b_place, _c_place = self._three_linkable_objects()
        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="A", source_element=a_place,
            target_object="B", target_element="BPlace",
        ))
        message = _err(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="B", source_element="BPlace",
            target_object="A", target_element=a_place,
        ))
        assert "opposite direction" in message

    def test_a_fan_of_two_copies_at_one_master_is_accepted(self):
        """The positive case, built the same way an agent would: B and C
        both copy A, one tool call each -- legal because A is never the
        SOURCE of either link."""
        session, a_place, _b_place, _c_place = self._three_linkable_objects()
        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="B", source_element="BPlace",
            target_object="A", target_element=a_place,
        ))
        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="C", source_element="CPlace",
            target_object="A", target_element=a_place,
        ))
        assert len(session.links) == 2
        errors = session.build_composed_model().validate()
        assert errors == []


class TestListAndRemoveLinks:
    def test_list_links_empty(self):
        session = PetriNetSession()
        text = _ok(ops.op_list_links(session))
        assert "No links yet" in text

    def test_list_links_shows_readable_names_and_position(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        _ok(ops.op_link_objects(
            session, link_type="transitionToPlace",
            source_object="Loader", source_element="LoaderGo",
            target_object="Sink", target_element="SinkIn",
        ))
        text = _ok(ops.op_list_links(session))
        assert "1:" in text
        assert "'Loader'" in text and "'Sink'" in text
        assert "LoaderGo" in text and "SinkIn" in text

    def test_remove_link_by_position(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        _ok(ops.op_link_objects(
            session, link_type="transitionToPlace",
            source_object="Loader", source_element="LoaderGo",
            target_object="Sink", target_element="SinkIn",
        ))
        text = _ok(ops.op_remove_link(session, index=1))
        assert "Removed link 1" in text
        assert session.links == []

    def test_remove_link_out_of_range_errors(self):
        session = PetriNetSession()
        message = _err(ops.op_remove_link(session, index=1))
        assert "No link at index 1" in message
        assert "0 link(s)" in message


# ---------------------------------------------------------------------------
# move_elements_to_object
# ---------------------------------------------------------------------------

class TestMoveElementsToObject:
    def test_no_ids_given_is_a_no_op(self):
        session = PetriNetSession()
        text = _ok(ops.op_move_elements_to_object(session, element_ids=[]))
        assert "nothing moved" in text

    def test_moves_from_active_object_to_named_destination(self):
        session = PetriNetSession()
        _ok(ops.op_add_place(session, name="FreeP", tokens=1))
        free_id = session.net.places[0].id
        _ok(ops.op_create_object(session, name="Dest"))
        _ok(ops.op_set_active_object(session, name=None))  # move FROM free pool

        text = _ok(ops.op_move_elements_to_object(session, element_ids=[free_id], object_name="Dest"))
        assert "Moved 1 element(s) to 'Dest'" in text
        assert session._free_builder.net.places == []
        assert [p.name for p in session.objects[0].net.places] == ["FreeP"]

    def test_unknown_element_id_in_active_object_errors(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="Dest"))
        message = _err(ops.op_move_elements_to_object(session, element_ids=["p99"], object_name=None))
        assert "Unknown element id(s): p99" in message

    def test_cross_object_arc_heals_into_a_link_after_the_move(self):
        """The same scenario link_objects would create by hand: moving a
        place away from the transition that feeds it turns their local
        arc into a transitionToPlace link automatically."""
        session, _lp, _lt, sink_place, sink_trans = _two_linkable_objects()
        _ok(ops.op_add_place(session, name="SinkOut", tokens=0, tag="throughput"))
        sink_out_id = session.net.places[-1].id
        _ok(ops.op_add_arc(session, source_id=sink_trans, target_id=sink_out_id))

        _ok(ops.op_set_active_object(session, name="Sink"))
        text = _ok(ops.op_move_elements_to_object(session, element_ids=[sink_out_id], object_name="Loader"))
        assert "Moved 1 element(s) to 'Loader'" in text

        assert len(session.links) == 1
        link = session.links[0]
        from src.domain.composed import LinkType
        assert link.link_type == LinkType.TRANSITION_TO_PLACE
        assert [p.name for p in session.objects[0].net.places] == ["LoaderQueue", "SinkOut"]
        assert [p.name for p in session.objects[1].net.places] == ["SinkIn"]  # unaffected

    def test_would_be_place_to_transition_link_is_refused(self):
        """Moving the TRANSITION away from a place that feeds it (rather
        than the place away from the transition) would need the retired
        placeToTransition direction -- refused, nothing changes."""
        session, loader_place, loader_trans, _sp, _st = _two_linkable_objects()
        _ok(ops.op_set_active_object(session, name="Loader"))
        message = _err(
            ops.op_move_elements_to_object(session, element_ids=[loader_trans], object_name="Sink")
        )
        assert "placeToTransition" in message
        assert "retired" in message
        # Nothing was moved: Loader still has both its original elements.
        assert len(session.objects[0].net.places) == 1
        assert len(session.objects[0].net.transitions) == 1

    def test_id_collision_at_destination_is_renamed_not_silently_merged(self):
        """Two independently-built objects can both auto-number their
        first place 'p1' (see session.py's _reserve_known_ids docstring on
        why the existing mitigation alone does not prevent this). Moving
        one into the other must rename it, not silently produce two
        places sharing one id."""
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_create_object(session, name="B"))
        _ok(ops.op_set_active_object(session, name="A"))
        _ok(ops.op_add_place(session, name="APlace"))
        _ok(ops.op_set_active_object(session, name="B"))
        _ok(ops.op_add_place(session, name="BPlace"))
        assert session.objects[0].net.places[0].id == "p1"
        assert session.objects[1].net.places[0].id == "p1"  # genuine collision

        _ok(ops.op_move_elements_to_object(session, element_ids=["p1"], object_name="A"))

        dest_ids = [p.id for p in session.objects[0].net.places]
        assert len(dest_ids) == len(set(dest_ids)), f"colliding ids merged: {dest_ids}"
        names_by_id = {p.id: p.name for p in session.objects[0].net.places}
        assert names_by_id == {"p1": "APlace", "p2": "BPlace"}
        assert session.objects[1].net.places == []
        errors = ops.op_validate_model(session)
        assert not isinstance(errors, ToolError)
        assert "valid" in errors.lower()


# ---------------------------------------------------------------------------
# validate_model
# ---------------------------------------------------------------------------

class TestValidateModelFlat:
    def test_no_network_message(self):
        session = PetriNetSession()
        text = _ok(ops.op_validate_model(session))
        assert "No network to validate" in text

    def test_valid_flat_network(self):
        session = PetriNetSession()
        _ok(ops.op_add_place(session, name="In", tokens=1))
        _ok(ops.op_add_transition(session, name="T"))
        _ok(ops.op_add_place(session, name="Out", tokens=0))
        in_id, out_id = session.net.places[0].id, session.net.places[1].id
        t_id = session.net.transitions[0].id
        _ok(ops.op_add_arc(session, source_id=in_id, target_id=t_id))
        _ok(ops.op_add_arc(session, source_id=t_id, target_id=out_id))
        text = _ok(ops.op_validate_model(session))
        assert "Model is valid" in text

    def test_invalid_flat_network_lists_findings(self):
        session = PetriNetSession()
        _ok(ops.op_add_place(session, name="Island1"))
        _ok(ops.op_add_place(session, name="Island2"))
        text = _ok(ops.op_validate_model(session))
        assert "finding(s)" in text


class TestValidateModelComposed:
    def test_valid_composed_model(self):
        session, _lp, _lt, sp, st = _two_linkable_objects()
        _ok(ops.op_link_objects(
            session, link_type="transitionToPlace",
            source_object="Loader", source_element="LoaderGo",
            target_object="Sink", target_element="SinkIn",
        ))
        text = _ok(ops.op_validate_model(session))
        assert "Composed model is valid" in text
        assert "1 link(s)" in text

    def test_transition_with_no_consuming_input_is_flagged(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_add_place(session, name="Idle", tokens=1))
        _ok(ops.op_add_transition(session, name="Orphan"))
        text = _ok(ops.op_validate_model(session))
        assert "no consuming input" in text
        assert "'Orphan'" in text

    def test_place_to_transition_link_loaded_from_data_is_flagged(self):
        """link_objects itself refuses to create one; validate_model must
        still flag one that arrived some other way (e.g. imported data)."""
        session, loader_place, _lt, _sp, sink_trans = _two_linkable_objects()
        from src.domain.composed import LinkType

        session.add_link(
            LinkType.PLACE_TO_TRANSITION,
            session.objects[0].frame_id, loader_place,
            session.objects[1].frame_id, sink_trans,
        )
        text = _ok(ops.op_validate_model(session))
        assert "placeToTransition links are not supported" in text

    def test_duplicate_id_within_one_object_is_flagged(self):
        """Bypasses add_place's own uniqueness guard the way imported/
        hand-edited net_data can: two places sharing an id inside ONE
        object, only reachable in a composed model since a flat
        PetriNet's own validate_topology already covers this case."""
        # add_place itself refuses a duplicate id (net.py's own guard); the
        # only way to reach this state is raw dict construction, exactly
        # how imported/hand-edited net_data bypasses it too.
        places = [
            {"id": "p1", "name": "First", "tokens": 0, "tag": None,
             "graphics": {"x": 0.0, "y": 0.0}, "objectId": "o1"},
            {"id": "p1", "name": "Second", "tokens": 0, "tag": None,
             "graphics": {"x": 10.0, "y": 10.0}, "objectId": "o1"},
        ]

        net_data = {
            "name": "Root",
            "places": places,
            "transitions": [],
            "arcs": [],
            "objects": [{"id": "o1", "name": "Broken", "priority": 0,
                          "graphics": {"x": 0, "y": 0, "width": 160, "height": 100}}],
        }
        session = PetriNetSession.from_net_data(net_data)
        text = _ok(ops.op_validate_model(session))
        assert "Duplicate node ID: 'p1'" in text


# ---------------------------------------------------------------------------
# Composed-aware run_simulation / get_simulation_results: the fusion
# scenario from test_composed_engine.py, reused through the ops layer.
# ---------------------------------------------------------------------------

class TestComposedRunSimulationSmoke:
    def test_fused_token_is_consumed_by_exactly_one_side(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_add_place(session, name="PA", tokens=1))
        _ok(ops.op_add_transition(session, name="TA"))
        a_place = session.net.places[0].id
        a_trans = session.net.transitions[0].id
        _ok(ops.op_add_arc(session, source_id=a_place, target_id=a_trans))

        _ok(ops.op_create_object(session, name="B"))
        _ok(ops.op_add_place(session, name="PB", tokens=0))
        _ok(ops.op_add_transition(session, name="TB"))
        b_place = session.net.places[0].id
        b_trans = session.net.transitions[0].id
        _ok(ops.op_add_arc(session, source_id=b_place, target_id=b_trans))

        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="B", source_element="PB",
            target_object="A", target_element="PA",
        ))

        text = _ok(ops.op_run_simulation(session, simulation_time=10.0))
        assert "Composed simulation across 3 object(s)" in text

        result = session.last_simulation_result
        assert result is not None
        marking = {p.name: p.final_marking for p in result.places}
        assert marking["PA"] == 0  # the surviving (target) side's id is what's reported
        assert "PB" not in marking  # fused away, PA is its one shared slot

        # get_simulation_results reports whichever ran last, unmodified.
        again = _ok(ops.op_get_simulation_results(session))
        assert again == "\n".join(text.split("\n\n", 1)[1:])

    def test_placetotransition_link_refuses_to_simulate(self):
        session, loader_place, _lt, _sp, sink_trans = _two_linkable_objects()
        from src.domain.composed import LinkType

        session.add_link(
            LinkType.PLACE_TO_TRANSITION,
            session.objects[0].frame_id, loader_place,
            session.objects[1].frame_id, sink_trans,
        )
        message = _err(ops.op_run_simulation(session, simulation_time=10.0))
        assert "Cannot simulate composed model" in message
        assert "placeToTransition" in message


# ---------------------------------------------------------------------------
# Composed-aware get_network_status
# ---------------------------------------------------------------------------

class TestGetNetworkStatusComposed:
    def test_reports_per_object_counts_and_active_marker(self):
        session, _lp, _lt, _sp, _st = _two_linkable_objects()
        text = _ok(ops.op_get_network_status(session))
        assert "=== Objects ===" in text
        assert "'Loader'" in text and "'Sink' (active)" in text

    def test_reports_content_even_when_active_object_is_empty(self):
        """The active net (free pool by default) having zero places used
        to be misread as 'no network at all', even when a named object
        held real content."""
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_add_place(session, name="P"))
        _ok(ops.op_set_active_object(session, name=None))
        text = _ok(ops.op_get_network_status(session))
        assert "No network created yet" not in text
        assert "'A'" in text and "1 places" in text


# ---------------------------------------------------------------------------
# import_pnml replace=False: session.has_any_content must see everything a
# reimport would silently wipe, not just places (it used to check places
# alone, so a transitions-only net, or a composed session whose only
# content so far was the object/link scaffolding itself, sailed straight
# through replace=False and got overwritten with no error at all).
# ---------------------------------------------------------------------------

class TestImportPnmlReplaceFalseGuard:
    def test_refuses_on_a_transitions_only_session(self):
        from tests.test_pnml_importer import SAMPLE_PNML

        session = PetriNetSession()
        _ok(ops.op_add_transition(session, name="Lonely"))
        assert session.net.places == []  # the exact gap has_any_content missed

        message = _err(ops.op_import_pnml(session, xml=SAMPLE_PNML, replace=False))
        assert "replace" in message.lower()
        # Untouched: the transition from before the refused import survives.
        assert len(session.net.transitions) == 1
        assert session.net.transitions[0].name == "Lonely"

    def test_refuses_on_an_empty_net_but_objects_session(self):
        from tests.test_pnml_importer import SAMPLE_PNML

        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        assert session.net.places == []
        assert session.net.transitions == []

        message = _err(ops.op_import_pnml(session, xml=SAMPLE_PNML, replace=False))
        assert "replace" in message.lower()
        # Untouched: the empty object created before the refused import survives.
        assert [o.name for o in session.objects] == ["A"]

    def test_replace_true_still_overwrites_either_session(self):
        from tests.test_pnml_importer import SAMPLE_PNML

        session = PetriNetSession()
        _ok(ops.op_add_transition(session, name="Lonely"))

        text = _ok(ops.op_import_pnml(session, xml=SAMPLE_PNML))
        assert "Imported 'Test Net'" in text
        assert [t.name for t in session.net.transitions] == ["Process"]
