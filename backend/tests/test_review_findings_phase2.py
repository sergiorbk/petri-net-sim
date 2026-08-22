"""Tests for the phase-2 review findings fixed in this change:

1. The reserved-id sentinel bug (PetriNet.reserve_ids replacing the old
   _node_index seeding) and the create_object/set_active_object
   _last_output_place_id reset that closes the auto-connect chaining half
   of it.
2. Id-addressed session links (SessionLink): a removed element's link is
   dropped and named in the result text, and optimize() on a composed
   object cannot corrupt one.
3. link_objects refusing a same-object link, and why that makes
   composed_document.py's own exporter backstop unreachable through the
   tool surface.
6. Composed round trip preserving each object's OWN builder extras
   (pattern-instance registry, layout direction/lock, cluster bounds),
   free pool included.
8. The composed wire-body object-count cap: create_object's own check
   counts what will actually be exported (named objects plus a
   non-empty free pool), and composed_convert.composed_model_to_wire_objects
   omits an empty one.
9. The placeToTransition retirement wording is genuinely single-sourced
   (PLACE_TO_TRANSITION_RETIRED_REASON), not just claimed to match.

See test_composed_convert.py for the converter-level findings (4, 5, and
11's adversarial/randomized round-trip coverage), and
test_agent_tool_node_composed.py for the tool_node serialization guard (2).
"""

from __future__ import annotations

import pytest

from src.core.security_config import security_settings
from src.domain.composed import PLACE_TO_TRANSITION_RETIRED_REASON
from src.domain.models import PetriNet
from src.services.petri.agent_toolkit import operations as ops
from src.services.petri.agent_toolkit.errors import ToolError
from src.services.petri.composed_convert import composed_model_to_wire_objects
from src.services.petri.session import PetriNetSession


def _ok(result) -> str:
    """Assert *result* is a successful (non-ToolError) op result and
    return its text."""
    assert not isinstance(result, ToolError), f"expected success, got: {result}"
    return str(result)


def _err(result) -> str:
    """Assert *result* is a ToolError and return its message text."""
    assert isinstance(result, ToolError), f"expected a ToolError, got: {result!r}"
    return result.message


def _two_object_session() -> PetriNetSession:
    """A, B: one place + one TIMED transition each (mean_delay=5.0, so
    nothing here is a zero-delay/sink-transition candidate the optimizer
    would touch on its own -- tests that need a genuine fusion build their
    own net directly instead)."""
    session = PetriNetSession()
    session.create_object("A")
    _ok(ops.op_add_place(session, name="A_In", tokens=1))
    _ok(ops.op_add_transition(session, name="A_T", distribution="exp", mean_delay=5.0))
    a_place = session.net.places[0].id
    a_trans = session.net.transitions[0].id
    _ok(ops.op_add_arc(session, source_id=a_place, target_id=a_trans))

    session.create_object("B")
    _ok(ops.op_add_place(session, name="B_In", tokens=0))
    _ok(ops.op_add_transition(session, name="B_T", distribution="exp", mean_delay=5.0))
    b_place = session.net.places[0].id
    b_trans = session.net.transitions[0].id
    _ok(ops.op_add_arc(session, source_id=b_place, target_id=b_trans))

    return session


# ---------------------------------------------------------------------------
# 1. Reserved-id sentinel bug + auto-connect chaining
# ---------------------------------------------------------------------------


class TestPetriNetReserveIds:
    """The replacement facility itself, at the domain layer."""

    def test_reserved_id_is_invisible_to_lookups_and_validation(self):
        net = PetriNet(name="N")
        net.reserve_ids({"p1", "t1", "arc1"})
        assert net.get_place("p1") is None
        assert net.get_transition("t1") is None
        assert net.get_arc("arc1") is None
        is_valid, errors = net.validate_topology()
        assert is_valid
        assert errors == []

    def test_reserved_id_steers_the_next_auto_generated_place_id(self):
        net = PetriNet(name="N")
        net.reserve_ids({"p1"})
        place = net.add_place("First")
        assert place.id == "p2"

    def test_reserved_transition_and_arc_ids_steer_minting_too(self):
        net = PetriNet(name="N")
        net.reserve_ids({"t1", "arc1"})
        p = net.add_place("P")
        t = net.add_transition("First")
        assert t.id == "t2"
        arc = net.add_arc(source_id=p.id, target_id=t.id)
        assert arc.id == "arc2"

    def test_reserved_id_does_not_defeat_add_arcs_existence_check(self):
        """The actual root-cause bug: seeding _node_index directly with a
        'reserved' sentinel made add_arc's `if not src_type: raise` check
        pass for an id that does not really exist in THIS net at all
        (truthy and != 'place'/'transition' both slip past it). reserve_ids
        never touches _node_index, so this now fails exactly like any
        other unknown id would."""
        net = PetriNet(name="N")
        net.reserve_ids({"p99"})
        with pytest.raises(ValueError, match="not found in net"):
            net.add_arc(source_id="p99", target_id="p99")


class TestNoCrossObjectIdChaining:
    """(a) from the root-cause description: auto_connect must never chain
    a pattern's output across an object boundary create_object/
    set_active_object just crossed."""

    def test_create_object_resets_last_output_place_id(self):
        session = PetriNetSession()
        _ok(ops.op_add_generator(session, name="Gen", interval=5.0))
        assert session.last_output_place_id is not None
        session.create_object("A")
        assert session.last_output_place_id is None

    def test_set_active_object_resets_last_output_place_id(self):
        session = PetriNetSession()
        session.create_object("A")
        _ok(ops.op_add_generator(session, name="Gen", interval=5.0))
        assert session.last_output_place_id is not None
        session.create_object("B")
        assert session.last_output_place_id is None
        session.set_active_object(0)  # back to A -- still no chaining
        assert session.last_output_place_id is None

    def test_auto_connect_does_not_wire_a_new_objects_pattern_to_the_free_pool(self):
        session = PetriNetSession()
        _ok(ops.op_add_generator(session, name="Gen", interval=5.0))
        session.create_object("A")
        text = _ok(ops.op_add_machine(session, name="M", processing_time=2.0))
        assert "Auto-connected" not in text
        free_place_ids = {p.id for p in session._free_builder.net.places}
        assert not any(
            a.source_id in free_place_ids or a.target_id in free_place_ids
            for a in session.net.arcs
        )


class TestForeignObjectIdRejected:
    """(b) from the root-cause description: op_add_arc/op_connect_patterns
    must cleanly refuse an id living in a DIFFERENT object, not silently
    accept it and write a dangling arc."""

    def test_op_add_arc_rejects_an_id_living_in_a_different_object(self):
        session = PetriNetSession()
        session.create_object("A")
        _ok(ops.op_add_place(session, name="PA", tokens=1))
        pa_id = session.net.places[0].id

        session.create_object("B")
        _ok(ops.op_add_transition(session, name="TB"))
        tb_id = session.net.transitions[0].id

        message = _err(ops.op_add_arc(session, source_id=pa_id, target_id=tb_id))
        assert "not found" in message
        assert session.net.arcs == []  # nothing dangling got created

    def test_op_connect_patterns_rejects_an_id_living_in_a_different_object(self):
        session = PetriNetSession()
        session.create_object("A")
        _ok(ops.op_add_place(session, name="PA", tokens=1))
        pa_id = session.net.places[0].id

        session.create_object("B")
        _ok(ops.op_add_place(session, name="PB", tokens=0))
        pb_id = session.net.places[0].id

        message = _err(ops.op_connect_patterns(session, source_output_id=pa_id, target_input_id=pb_id))
        assert "not found" in message
        assert not any(a.source_id == pa_id or a.target_id == pa_id for a in session.net.arcs)


# ---------------------------------------------------------------------------
# 2. Id-addressed session links
# ---------------------------------------------------------------------------


class TestIdAddressedLinksSurviveRemoval:
    def test_remove_place_drops_the_referencing_link_and_says_so(self):
        session = _two_object_session()
        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="A", source_element="A_In",
            target_object="B", target_element="B_In",
        ))
        assert len(session.links) == 1

        _ok(ops.op_set_active_object(session, name="A"))
        a_place = session.objects[0].net.places[0].id
        text = _ok(ops.op_remove_place(session, place_id=a_place))
        assert "Dropped 1 link" in text
        assert session.links == []

        # to_net_data round-trips cleanly with the link gone.
        data = session.to_net_data()
        assert data.get("links", []) == []
        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded.links == []

    def test_remove_transition_drops_the_referencing_link_and_says_so(self):
        session = _two_object_session()
        _ok(ops.op_link_objects(
            session, link_type="transitionToPlace",
            source_object="A", source_element="A_T",
            target_object="B", target_element="B_In",
        ))
        assert len(session.links) == 1

        _ok(ops.op_set_active_object(session, name="A"))
        a_trans = session.objects[0].net.transitions[0].id
        text = _ok(ops.op_remove_transition(session, transition_id=a_trans))
        assert "Dropped 1 link" in text
        assert session.links == []

    def test_remove_object_drops_the_link_only_touching_it(self):
        session = _two_object_session()
        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="A", source_element="A_In",
            target_object="B", target_element="B_In",
        ))
        text = _ok(ops.op_remove_object(session, name="A", keep_elements=False))
        assert "Dropped 1 link" in text
        assert session.links == []


class TestOptimizeDoesNotCorruptComposedLinks:
    def test_optimize_preserves_a_link_when_nothing_gets_fused(self):
        session = _two_object_session()
        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="A", source_element="A_In",
            target_object="B", target_element="B_In",
        ))
        _ok(ops.op_set_active_object(session, name="A"))
        stats = session.optimize()
        assert stats["fusions_performed"] == 0  # sanity: nothing to fuse here

        data = session.to_net_data()
        assert len(data.get("links", [])) == 1
        a_place = next(p for p in data["places"] if p["name"] == "A_In")
        assert data["links"][0]["sourceId"] == a_place["id"]

    def test_optimize_drops_rather_than_corrupts_a_fused_away_links_endpoint(self):
        """Build A so that optimize() genuinely fuses P1/P2 away (a
        zero-delay Transfer between them, PetriNetOptimizer's own
        Fusion-of-Series-Places rule), with the link pointing at the
        element that gets removed. A POSITION-addressed link would have
        kept pointing at whatever now sits at that old position (possibly
        an unrelated, real element) -- an id-addressed one either still
        resolves (the exact id survived) or cleanly disappears; it can
        never silently repoint at something else."""
        session = PetriNetSession()
        session.create_object("A")
        p1_id = session.builder.add_raw_place(name="P1", tokens=1, x=0, y=0)
        p2_id = session.builder.add_raw_place(name="P2", tokens=0, x=100, y=0)
        p3_id = session.builder.add_raw_place(name="P3", tokens=0, x=200, y=0)
        t_zero = session.builder.add_raw_transition(
            name="Transfer", distribution="det", mean_delay=0.0, x=50, y=0
        )
        t_process = session.builder.add_raw_transition(
            name="Process", distribution="exp", mean_delay=5.0, x=150, y=0
        )
        session.builder.add_raw_arc(source_id=p1_id, target_id=t_zero)
        session.builder.add_raw_arc(source_id=t_zero, target_id=p2_id)
        session.builder.add_raw_arc(source_id=p2_id, target_id=t_process)
        session.builder.add_raw_arc(source_id=t_process, target_id=p3_id)

        session.create_object("B")
        _ok(ops.op_add_place(session, name="B_In", tokens=0))
        session.set_active_object(0)  # back to A

        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="A", source_element="P2",
            target_object="B", target_element="B_In",
        ))
        assert len(session.links) == 1

        stats = session.optimize()
        assert stats["fusions_performed"] > 0
        surviving_ids = {p.id for p in session.objects[0].net.places}
        assert p2_id not in surviving_ids  # sanity: P2 really did get fused away

        data = session.to_net_data()  # must not raise
        assert all(
            link.get("sourceId") != p2_id and link.get("targetId") != p2_id
            for link in data.get("links", [])
        )
        # Nothing quietly took P2's place either: the link is just gone.
        assert data.get("links", []) == []


# ---------------------------------------------------------------------------
# 3. link_objects refuses a same-object link
# ---------------------------------------------------------------------------


class TestSameObjectLinkRejected:
    def test_link_objects_rejects_same_named_object_endpoints(self):
        session = PetriNetSession()
        session.create_object("A")
        _ok(ops.op_add_place(session, name="P1", tokens=1))
        _ok(ops.op_add_place(session, name="P2", tokens=0))
        message = _err(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="A", source_element="P1",
            target_object="A", target_element="P2",
        ))
        assert "same object" in message.lower()
        assert "add_arc" in message
        assert session.links == []

    def test_link_objects_rejects_same_free_pool_endpoints(self):
        session = PetriNetSession()
        _ok(ops.op_add_place(session, name="P1", tokens=1))
        _ok(ops.op_add_place(session, name="P2", tokens=0))
        message = _err(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object=None, source_element="P1",
            target_object=None, target_element="P2",
        ))
        assert "free pool" in message
        assert session.links == []

    def test_validate_then_export_never_hits_the_exporters_self_link_refusal(self):
        """Built entirely through the tool surface (never touching
        session.add_link directly): a same-object link is always refused
        at creation time, so a validate_model/export_pnml flow driven only
        by these tools can never reach composed_document.py's own
        "source_object == target_object, not expressible in PNML" backstop
        -- there is no path through the tools that produces one."""
        session = _two_object_session()
        _ok(ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="A", source_element="A_In",
            target_object="B", target_element="B_In",
        ))
        same_object_attempt = ops.op_link_objects(
            session, link_type="placeFusion",
            source_object="A", source_element="A_In",
            target_object="A", target_element="A_T",
        )
        assert isinstance(same_object_attempt, ToolError)

        validate_text = _ok(ops.op_validate_model(session))
        assert "not expressible in PNML" not in validate_text

        export_result = ops.op_export_pnml(session)
        assert not isinstance(export_result, ToolError)
        assert "not expressible in PNML" not in str(export_result)


# ---------------------------------------------------------------------------
# 6. Composed round trip preserves per-object builder extras
# ---------------------------------------------------------------------------


class TestBuilderExtrasRoundTripPerObject:
    def test_named_objects_own_builder_extras_survive(self):
        session = PetriNetSession()
        session.create_object("A")
        _ok(ops.op_add_generator(session, name="Gen", interval=5.0))
        session.builder.set_layout_direction("TB")
        assert session.objects[0].builder._pattern_instances  # non-empty

        data = session.to_net_data()
        frame = data["objects"][0]
        assert frame["_layout_direction"] == "TB"
        assert frame["_pattern_instances"]

        reloaded = PetriNetSession.from_net_data(data)
        restored = reloaded.objects[0].builder
        original = session.objects[0].builder
        assert restored._layout_direction == "TB"
        assert restored._pattern_instances == original._pattern_instances
        assert restored._custom_layout_locked == original._custom_layout_locked
        assert restored._cluster_bounds == original._cluster_bounds

    def test_two_named_objects_do_not_share_each_others_extras(self):
        """Each SessionObject has its OWN independent PetriNetBuilder --
        one root-level set of extra-state keys (the free pool's own
        convention) could only ever describe ONE of them."""
        session = PetriNetSession()
        session.create_object("A")
        session.builder.set_layout_direction("TB")
        session.create_object("B")
        session.builder.set_layout_direction("LR")

        data = session.to_net_data()
        by_name = {f["name"]: f for f in data["objects"]}
        assert by_name["A"]["_layout_direction"] == "TB"
        assert by_name["B"]["_layout_direction"] == "LR"

        reloaded = PetriNetSession.from_net_data(data)
        reloaded_by_name = {o.name: o for o in reloaded.objects}
        assert reloaded_by_name["A"].builder._layout_direction == "TB"
        assert reloaded_by_name["B"].builder._layout_direction == "LR"

    def test_free_pool_extras_survive_a_composed_round_trip(self):
        """Regression: the free pool used to be restored from a bare
        PetriNet dump (free_obj.net.model_dump()), which never carries
        these keys -- silently losing its own layout/pattern state the
        moment a session became composed, even though the FLAT path
        always preserved it."""
        session = PetriNetSession()
        _ok(ops.op_add_generator(session, name="FreeGen", interval=5.0))
        session.builder.set_layout_direction("TB")
        session.create_object("A")  # now composed

        data = session.to_net_data()
        assert data["_layout_direction"] == "TB"
        assert data["_pattern_instances"]

        reloaded = PetriNetSession.from_net_data(data)
        assert reloaded._free_builder._layout_direction == "TB"
        assert reloaded._free_builder._pattern_instances == session._free_builder._pattern_instances


# ---------------------------------------------------------------------------
# 8. Composed wire-body object-count cap alignment
# ---------------------------------------------------------------------------


class TestObjectCountCapAlignment:
    def test_cap_counts_a_nonempty_free_pool(self, monkeypatch):
        monkeypatch.setattr(security_settings, "SIMULATION_MAX_OBJECTS", 2)
        session = PetriNetSession()
        _ok(ops.op_add_place(session, name="FreePlace", tokens=1))  # non-empty free pool
        session.create_object("A")  # exportable count: free(1) + A(1) = 2 == cap
        with pytest.raises(ValueError, match="capped at 2"):
            session.create_object("B")

    def test_cap_ignores_an_empty_free_pool(self, monkeypatch):
        monkeypatch.setattr(security_settings, "SIMULATION_MAX_OBJECTS", 2)
        session = PetriNetSession()  # free pool stays empty throughout
        session.create_object("A")
        session.create_object("B")  # exportable count: A + B = 2 == cap (free pool free)
        with pytest.raises(ValueError, match="capped at 2"):
            session.create_object("C")

    def test_composed_model_to_wire_objects_omits_an_empty_free_pool(self):
        session = PetriNetSession()
        session.create_object("A")
        _ok(ops.op_add_place(session, name="PA", tokens=1))
        wire_objects = composed_model_to_wire_objects(session.build_composed_model())
        assert len(wire_objects) == 1
        assert wire_objects[0]["name"] == "A"
        assert wire_objects[0]["free"] is False

    def test_composed_model_to_wire_objects_keeps_a_nonempty_free_pool(self):
        session = PetriNetSession()
        _ok(ops.op_add_place(session, name="FreePlace", tokens=1))
        session.create_object("A")
        wire_objects = composed_model_to_wire_objects(session.build_composed_model())
        assert len(wire_objects) == 2
        assert any(o["free"] for o in wire_objects)

    def test_a_session_at_the_cap_still_fits_the_composed_wire_body(self, monkeypatch):
        """The boundary case this whole alignment exists for: a session
        create_object let through (per its OWN cap check) must actually
        fit POST /api/v1/simulate/composed's own wire-body cap
        (ComposedSimulateBody.objects: max_length=SIMULATION_MAX_OBJECTS)."""
        monkeypatch.setattr(security_settings, "SIMULATION_MAX_OBJECTS", 3)
        session = PetriNetSession()
        _ok(ops.op_add_place(session, name="FreePlace", tokens=1))  # non-empty: counts as 1
        session.create_object("A")
        _ok(ops.op_add_place(session, name="PA", tokens=1))
        session.create_object("B")  # exportable count: free(1) + A(1) + B(1) == 3 == cap
        _ok(ops.op_add_place(session, name="PB", tokens=1))
        with pytest.raises(ValueError, match="capped at 3"):
            session.create_object("C")

        wire_objects = composed_model_to_wire_objects(session.build_composed_model())
        assert len(wire_objects) == 3  # matches the cap exactly, free pool included

        from src.api.versions.v1.routers.simulate_composed import ComposedSimulateBody

        body = ComposedSimulateBody(objects=wire_objects)  # must NOT raise (max_length=3)
        assert len(body.objects) == 3


# ---------------------------------------------------------------------------
# 9. placeToTransition retirement wording, genuinely single-sourced
# ---------------------------------------------------------------------------


class TestPlaceToTransitionWordingSingleSourced:
    def test_operations_message_is_built_from_the_shared_constant(self):
        from src.services.petri.agent_toolkit.operations import _PLACE_TO_TRANSITION_RETIRED

        assert PLACE_TO_TRANSITION_RETIRED_REASON in _PLACE_TO_TRANSITION_RETIRED

    def test_exporters_backstop_message_uses_the_same_wording_verbatim(self):
        """Not just importing the same constant -- the RAISED message
        text actually contains it, proving the exporter's own backstop and
        link_objects's create-time refusal say the same thing rather than
        two independently hand-copied strings that already drifted apart
        once (the bug this constant replaces)."""
        from src.domain.composed import ComposedModel, LinkType
        from src.services.petri.exporter import get_composed_pnml_exporter

        model = ComposedModel(name="M")
        net_a = PetriNet(name="A")
        p = net_a.add_place("P")
        t = net_a.add_transition("T")
        net_a.add_arc(p.id, t.id)
        model.add_object(net_a, name="A")
        net_b = PetriNet(name="B")
        p2 = net_b.add_place("P2")
        t2 = net_b.add_transition("T2")
        net_b.add_arc(p2.id, t2.id)
        model.add_object(net_b, name="B")
        model.add_link(
            LinkType.PLACE_TO_TRANSITION, source_object=0, source_element=0,
            target_object=1, target_element=0,
        )

        exporter = get_composed_pnml_exporter()
        with pytest.raises(ValueError) as exc_info:
            exporter.export(model)

        assert PLACE_TO_TRANSITION_RETIRED_REASON in str(exc_info.value)
