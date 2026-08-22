"""Tests for the local (Python-native) composed-model simulation engine."""

from __future__ import annotations

import pytest

from src.domain.composed import ComposedModel, LinkType
from src.domain.models import ArcType, PetriNet
from src.services.simulation.composed_engine import (
    ComposedSimulationUnsupported,
    build_composed_sim_net,
)
from src.services.simulation.engine import PetriSimulator


def _immediate_net(name: str, place_name: str, place_tokens: int, transition_name: str) -> PetriNet:
    """One place --(consuming arc)--> one transition, no output — the
    transition's own output place, if any, is added by the caller so tests
    can tell which object actually fired."""
    net = PetriNet(name=name)
    net.add_place(place_name, tokens=place_tokens)
    net.add_transition(transition_name, mean_delay=0.0)
    net.add_arc(net.places[0].id, net.transitions[0].id)
    return net


def _net_with_output(name: str, in_place: str, transition: str, out_place: str, tokens: int = 0) -> PetriNet:
    net = PetriNet(name=name)
    p_in = net.add_place(in_place, tokens=tokens)
    t = net.add_transition(transition, mean_delay=0.0)
    p_out = net.add_place(out_place, tokens=0)
    net.add_arc(p_in.id, t.id)
    net.add_arc(t.id, p_out.id)
    return net


class TestPlaceFusion:
    def test_fused_places_share_one_global_slot(self):
        model = ComposedModel()
        model.add_object(_immediate_net("A", "PA", 1, "TA"))
        model.add_object(_immediate_net("B", "PB", 0, "TB"))
        # Target side (object 0) survives, per PetriObjModel.wire().
        model.add_link(LinkType.PLACE_FUSION, source_object=1, source_element=0, target_object=0, target_element=0)

        places, transitions = build_composed_sim_net(model)

        assert len(places) == 1, "two fused places collapse into one shared slot"
        assert places[0].mark == 1, "the surviving (target) side's own marking is what's kept"
        # Both transitions' consuming arc must point at the SAME slot.
        assert transitions[0].in_places == [0]
        assert transitions[1].in_places == [0]

    def test_fusion_survives_a_transitive_chain(self):
        model = ComposedModel()
        model.add_object(_immediate_net("A", "PA", 5, "TA"))
        model.add_object(_immediate_net("B", "PB", 0, "TB"))
        model.add_object(_immediate_net("C", "PC", 0, "TC"))
        # A=B, B=C — all three must resolve to ONE slot, not two.
        model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=0, target_object=1, target_element=0)
        model.add_link(LinkType.PLACE_FUSION, source_object=1, source_element=0, target_object=2, target_element=0)

        places, transitions = build_composed_sim_net(model)

        assert len(places) == 1
        in_place_slots = {t.in_places[0] for t in transitions}
        assert in_place_slots == {0}

    def test_a_firing_that_drains_a_fused_place_is_visible_to_the_other_object(self):
        # TA and TB are tied on (object_priority, priority), so which one
        # wins the one shared token is an unseeded 50/50 roulette pick
        # (SimTransition.probability defaults to 1.0, read by
        # _resolve_conflict as "unset" -> split evenly) -- deliberately not
        # pinned down here, since that tie-break is what TestObjectPriority
        # exercises. What this test asserts is fusion's own invariant:
        # exactly one side gets the token, never both, never neither.
        model = ComposedModel()
        model.add_object(_net_with_output("A", "Fused", "TA", "OutA", tokens=1))
        model.add_object(_net_with_output("B", "FusedB", "TB", "OutB", tokens=0))
        model.add_link(LinkType.PLACE_FUSION, source_object=1, source_element=0, target_object=0, target_element=0)

        places, transitions = build_composed_sim_net(model)
        result = PetriSimulator.from_sim_state(places, transitions).run(simulation_time=10.0)

        marking = {p.name: p.final_marking for p in result.places}
        assert (marking["OutA"], marking["OutB"]) in [(1, 0), (0, 1)]
        assert marking["Fused"] == 0  # the survivor's id is what's reported


class TestTransitionToPlace:
    def test_wires_a_cross_object_output_arc(self):
        model = ComposedModel()
        model.add_object(_immediate_net("A", "PA", 1, "TA"))
        model.add_object(_immediate_net("B", "PB", 0, "TB"))
        model.add_link(LinkType.TRANSITION_TO_PLACE, source_object=0, source_element=0, target_object=1, target_element=0, quantity=2)

        places, transitions = build_composed_sim_net(model)

        ta = transitions[0]
        assert ta.out_places == [1]  # object B's place, in the global pool
        assert ta.out_quantities == [2]

    def test_a_transition_feeds_a_foreign_place_which_then_enables_a_foreign_transition(self):
        model = ComposedModel()
        # A: PA(1) -> TA (no local output of its own).
        net_a = PetriNet(name="A")
        p_a = net_a.add_place("PA", tokens=1)
        t_a = net_a.add_transition("TA", mean_delay=0.0)
        net_a.add_arc(p_a.id, t_a.id)
        model.add_object(net_a)
        # B: PB(0) -> TB -> OutB.
        model.add_object(_net_with_output("B", "PB", "TB", "OutB"))
        model.add_link(LinkType.TRANSITION_TO_PLACE, source_object=0, source_element=0, target_object=1, target_element=0)

        places, transitions = build_composed_sim_net(model)
        result = PetriSimulator.from_sim_state(places, transitions).run(simulation_time=10.0)

        marking = {p.name: p.final_marking for p in result.places}
        assert marking["OutB"] == 1, "TA's token reached PB, which then fed TB through to OutB"


class TestObjectPriority:
    def test_object_priority_flows_into_every_one_of_that_object_own_transitions(self):
        model = ComposedModel()
        model.add_object(_immediate_net("A", "PA", 1, "TA"), priority=7)
        model.add_object(_immediate_net("B", "PB", 1, "TB"), priority=0)

        _, transitions = build_composed_sim_net(model)

        assert transitions[0].object_priority == 7
        assert transitions[1].object_priority == 0

    def test_higher_object_priority_wins_a_conflict_over_a_shared_resource(self):
        # Two objects whose OWN transitions have the identical (default)
        # transition-level priority, competing for one token in a place
        # fused between them. Only the higher-object-priority object's
        # transition may win — this is the unified (object, transition)
        # priority tie-break replacing PetriObjModelPaint's two separate,
        # narrower mechanisms.
        model = ComposedModel()
        model.add_object(_net_with_output("A", "Fused", "TA", "OutA", tokens=1), priority=10)
        model.add_object(_net_with_output("B", "FusedB", "TB", "OutB", tokens=0), priority=1)
        model.add_link(LinkType.PLACE_FUSION, source_object=1, source_element=0, target_object=0, target_element=0)

        places, transitions = build_composed_sim_net(model)
        result = PetriSimulator.from_sim_state(places, transitions).run(simulation_time=10.0)

        marking = {p.name: p.final_marking for p in result.places}
        assert marking["OutA"] == 1
        assert marking["OutB"] == 0

    def test_flipping_which_object_has_priority_flips_the_winner(self):
        model = ComposedModel()
        model.add_object(_net_with_output("A", "Fused", "TA", "OutA", tokens=1), priority=1)
        model.add_object(_net_with_output("B", "FusedB", "TB", "OutB", tokens=0), priority=10)
        model.add_link(LinkType.PLACE_FUSION, source_object=1, source_element=0, target_object=0, target_element=0)

        places, transitions = build_composed_sim_net(model)
        result = PetriSimulator.from_sim_state(places, transitions).run(simulation_time=10.0)

        marking = {p.name: p.final_marking for p in result.places}
        assert marking["OutA"] == 0
        assert marking["OutB"] == 1


class TestIdNamespacing:
    def test_ids_pass_through_unchanged_when_nothing_collides(self):
        # PetriNet auto-numbers "p1", "t1", "arc1" independently in every net,
        # so two DEFAULT nets always collide on those ids -- explicit,
        # already-distinct ids are what "nothing collides" actually looks
        # like here (see build_final_id_map's own docstring on this).
        model = ComposedModel()
        net_a = PetriNet(name="A")
        net_a.add_place("PA", tokens=1, place_id="place_a")
        model.add_object(net_a)
        net_b = PetriNet(name="B")
        net_b.add_place("PB", tokens=0, place_id="place_b")
        model.add_object(net_b)

        places, _ = build_composed_sim_net(model)

        ids = {p.id for p in places}
        assert ids == {"place_a", "place_b"}

    def test_colliding_ids_across_objects_get_namespaced(self):
        model = ComposedModel()
        net_a = PetriNet(name="A")
        net_a.add_place("P", tokens=1, place_id="shared_id")
        model.add_object(net_a)
        net_b = PetriNet(name="B")
        net_b.add_place("P2", tokens=0, place_id="shared_id")
        model.add_object(net_b)

        places, _ = build_composed_sim_net(model)

        ids = [p.id for p in places]
        assert len(ids) == len(set(ids)), "colliding ids must be namespaced apart"
        assert "shared_id" not in ids, "the whole document renames once any id collides"


class TestPlaceToTransitionRejected:
    def test_raises_a_clear_model_level_error(self):
        model = ComposedModel()
        model.add_object(_immediate_net("A", "PA", 1, "TA"))
        model.add_object(_net_with_output("B", "PB", "TB", "OutB"))
        model.add_link(LinkType.PLACE_TO_TRANSITION, source_object=0, source_element=0, target_object=1, target_element=0)

        with pytest.raises(ComposedSimulationUnsupported, match="placeToTransition"):
            build_composed_sim_net(model)


class TestArcTypesCarryThrough:
    def test_read_and_inhibitor_arcs_both_become_non_consuming_test_arcs(self):
        # Matches the local flat engine's existing (and, per the reference
        # Java engine, faithfully-ported) behavior: both types require the
        # place to hold enough tokens without consuming them. See
        # state.py's _wire_arc and PetriT.condition()/actIn() in
        # PetriObjModelPaint for why this is deliberate, not a bug to fix here.
        # A transition guarded by ONLY a non-consuming arc never disables
        # itself, so engine.py's _input_all() keeps opening new concurrent
        # channels for it within the same instant forever -- a genuine,
        # pre-existing property of the multi-channel engine, not something
        # this test means to exercise. A second, ORDINARY consuming arc
        # caps how many times it can actually fire, while the guard's own
        # final marking still proves it was never touched.
        model = ComposedModel()
        net = PetriNet(name="A")
        guard = net.add_place("Guard", tokens=1)
        limiter = net.add_place("Limiter", tokens=3)
        t = net.add_transition("T", mean_delay=0.0)
        out = net.add_place("Out", tokens=0)
        net.add_arc(guard.id, t.id, arc_type=ArcType.INHIBITOR)
        net.add_arc(limiter.id, t.id)
        net.add_arc(t.id, out.id)
        model.add_object(net)

        places, transitions = build_composed_sim_net(model)
        result = PetriSimulator.from_sim_state(places, transitions).run(simulation_time=10.0)

        marking = {pl.name: pl.final_marking for pl in result.places}
        assert marking["Guard"] == 1, "a read/test arc never consumes"
        assert marking["Limiter"] == 0
        assert marking["Out"] == 3, "fired exactly as many times as the ordinary arc allowed"
