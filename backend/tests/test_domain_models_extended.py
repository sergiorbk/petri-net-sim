"""Tests for domain model methods not yet covered — Place, PetriNet helpers."""

from __future__ import annotations

import pytest

from src.domain.models.place import Place
from src.domain.models.net import PetriNet


# ---------------------------------------------------------------------------
# Place — token manipulation
# ---------------------------------------------------------------------------


class TestPlaceAddTokens:
    def test_adds_tokens(self):
        p = Place(name="P1", tokens=0)
        p.add_tokens(3)
        assert p.tokens == 3

    def test_adds_to_existing(self):
        p = Place(name="P1", tokens=5)
        p.add_tokens(2)
        assert p.tokens == 7

    def test_add_zero_ok(self):
        p = Place(name="P1", tokens=2)
        p.add_tokens(0)
        assert p.tokens == 2

    def test_add_negative_raises(self):
        p = Place(name="P1", tokens=5)
        with pytest.raises(ValueError, match="negative"):
            p.add_tokens(-1)


class TestPlaceRemoveTokens:
    def test_removes_tokens(self):
        p = Place(name="P1", tokens=5)
        p.remove_tokens(3)
        assert p.tokens == 2

    def test_remove_all_ok(self):
        p = Place(name="P1", tokens=3)
        p.remove_tokens(3)
        assert p.tokens == 0

    def test_remove_negative_raises(self):
        p = Place(name="P1", tokens=5)
        with pytest.raises(ValueError, match="negative"):
            p.remove_tokens(-1)

    def test_remove_more_than_available_raises(self):
        p = Place(name="P1", tokens=2)
        with pytest.raises(ValueError, match="Insufficient"):
            p.remove_tokens(5)


class TestPlaceHasTokens:
    def test_true_when_enough(self):
        p = Place(name="P1", tokens=3)
        assert p.has_tokens(2) is True

    def test_true_when_exact(self):
        p = Place(name="P1", tokens=2)
        assert p.has_tokens(2) is True

    def test_false_when_not_enough(self):
        p = Place(name="P1", tokens=1)
        assert p.has_tokens(3) is False

    def test_default_count_is_one(self):
        p = Place(name="P1", tokens=1)
        assert p.has_tokens() is True
        p2 = Place(name="P2", tokens=0)
        assert p2.has_tokens() is False


# ---------------------------------------------------------------------------
# PetriNet — edge-case model methods
# ---------------------------------------------------------------------------


class TestPetriNetGetMethods:
    def test_get_place_returns_none_for_missing(self):
        net = PetriNet(name="N")
        assert net.get_place("nonexistent") is None

    def test_get_transition_returns_none_for_missing(self):
        net = PetriNet(name="N")
        assert net.get_transition("nonexistent") is None

    def test_get_arc_returns_none_for_missing(self):
        net = PetriNet(name="N")
        assert net.get_arc("nonexistent") is None

    def test_get_place_by_name_finds_existing(self):
        net = PetriNet(name="N")
        p = net.add_place("MyPlace")
        found = net.get_place_by_name("MyPlace")
        assert found is not None
        assert found.id == p.id

    def test_get_place_by_name_returns_none_for_missing(self):
        net = PetriNet(name="N")
        assert net.get_place_by_name("Nope") is None


class TestPetriNetUpdateMethods:
    def test_update_place_name(self):
        net = PetriNet(name="N")
        p = net.add_place("Old")
        net.update_place(p.id, name="New")
        assert net.get_place(p.id).name == "New"

    def test_update_place_nonexistent_raises(self):
        net = PetriNet(name="N")
        with pytest.raises(ValueError, match="not found"):
            net.update_place("bad_id", name="X")

    def test_update_place_negative_tokens_raises(self):
        net = PetriNet(name="N")
        p = net.add_place("P1")
        with pytest.raises(ValueError, match="negative"):
            net.update_place(p.id, tokens=-1)

    def test_update_transition_nonexistent_raises(self):
        net = PetriNet(name="N")
        with pytest.raises(ValueError, match="not found"):
            net.update_transition("bad_id", name="X")

    def test_update_arc_nonexistent_raises(self):
        net = PetriNet(name="N")
        with pytest.raises(ValueError, match="not found"):
            net.update_arc("bad_id", weight=2)

    def test_remove_place_nonexistent_raises(self):
        net = PetriNet(name="N")
        with pytest.raises(ValueError, match="not found"):
            net.remove_place("bad_id")

    def test_remove_transition_nonexistent_raises(self):
        net = PetriNet(name="N")
        with pytest.raises(ValueError, match="not found"):
            net.remove_transition("bad_id")

    def test_remove_arc_nonexistent_raises(self):
        net = PetriNet(name="N")
        with pytest.raises(ValueError, match="not found"):
            net.remove_arc("bad_id")


class TestPetriNetArcValidation:
    def test_bipartite_place_place_raises(self):
        net = PetriNet(name="N")
        p1 = net.add_place("P1")
        p2 = net.add_place("P2")
        with pytest.raises(ValueError, match="cannot connect"):
            net.add_arc(p1.id, p2.id)

    def test_bipartite_transition_transition_raises(self):
        net = PetriNet(name="N")
        t1 = net.add_transition("T1")
        t2 = net.add_transition("T2")
        with pytest.raises(ValueError, match="cannot connect"):
            net.add_arc(t1.id, t2.id)

    def test_arc_source_not_found_raises(self):
        net = PetriNet(name="N")
        t = net.add_transition("T1")
        with pytest.raises(ValueError, match="not found"):
            net.add_arc("nonexistent", t.id)


class TestPetriNetCustomIds:
    def test_add_place_with_custom_id(self):
        net = PetriNet(name="N")
        p = net.add_place("P", place_id="custom_p1")
        assert p.id == "custom_p1"

    def test_add_place_duplicate_custom_id_raises(self):
        net = PetriNet(name="N")
        net.add_place("P1", place_id="custom_p1")
        with pytest.raises(ValueError, match="already exists"):
            net.add_place("P2", place_id="custom_p1")

    def test_add_transition_with_custom_id(self):
        net = PetriNet(name="N")
        t = net.add_transition("T", transition_id="custom_t1")
        assert t.id == "custom_t1"

    def test_add_transition_duplicate_custom_id_raises(self):
        net = PetriNet(name="N")
        net.add_transition("T1", transition_id="custom_t1")
        with pytest.raises(ValueError, match="already exists"):
            net.add_transition("T2", transition_id="custom_t1")

    def test_get_transition_by_name_returns_none(self):
        net = PetriNet(name="N")
        assert net.get_transition_by_name("Nonexistent") is None

    def test_total_tokens_sums_all_places(self):
        net = PetriNet(name="N")
        net.add_place("P1", tokens=3)
        net.add_place("P2", tokens=5)
        assert net.total_tokens == 8


class TestPetriNetValidation:
    def test_validates_valid_net(self):
        net = PetriNet(name="N")
        p1 = net.add_place("P1")
        t = net.add_transition("T")
        p2 = net.add_place("P2")
        net.add_arc(p1.id, t.id)
        net.add_arc(t.id, p2.id)
        valid, errors = net.validate_topology()
        assert valid is True
        assert errors == []

    def test_removes_place_id_not_a_place_raises(self):
        net = PetriNet(name="N")
        # Try to remove a transition via remove_place — should fail
        t = net.add_transition("T")
        with pytest.raises(ValueError, match="is not a place"):
            net.remove_place(t.id)

    def test_removes_transition_id_not_a_transition_raises(self):
        net = PetriNet(name="N")
        # Try to remove a place via remove_transition — should fail
        p = net.add_place("P")
        with pytest.raises(ValueError, match="is not a transition"):
            net.remove_transition(p.id)

    def test_update_place_unknown_attr_raises(self):
        net = PetriNet(name="N")
        p = net.add_place("P")
        with pytest.raises(ValueError, match="Unknown place attribute"):
            net.update_place(p.id, nonexistent_attr="x")

    def test_update_transition_unknown_attr_raises(self):
        net = PetriNet(name="N")
        t = net.add_transition("T")
        with pytest.raises(ValueError, match="Unknown transition attribute"):
            net.update_transition(t.id, nonexistent_attr="x")

    def test_update_arc_unknown_attr_raises(self):
        net = PetriNet(name="N")
        p = net.add_place("P")
        t = net.add_transition("T")
        arc = net.add_arc(p.id, t.id)
        with pytest.raises(ValueError, match="Unknown arc attribute"):
            net.update_arc(arc.id, nonexistent_attr="x")
