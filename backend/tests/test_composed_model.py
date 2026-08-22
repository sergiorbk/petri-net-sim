"""Tests for the ComposedModel domain aggregate."""

from __future__ import annotations

from src.domain.composed import ComposedModel, ComposedLink, LinkType
from src.domain.models import PetriNet


def _generator_net() -> PetriNet:
    """P1 --> T1 --> P1 (a self-looping generator, no output place needed)."""
    net = PetriNet(name="Generator")
    p1 = net.add_place("P1", tokens=1)
    t1 = net.add_transition("T1", mean_delay=2.0, distribution="exp")
    net.add_arc(p1.id, t1.id)
    net.add_arc(t1.id, p1.id)
    return net


def _sink_net_no_local_output() -> PetriNet:
    """A place feeding a transition that has no local output at all —
    the object relies entirely on a transitionToPlace link to deliver
    its tokens elsewhere."""
    net = PetriNet(name="Sink")
    p1 = net.add_place("In", tokens=0)
    t1 = net.add_transition("Deliver", mean_delay=1.0, distribution="exp")
    net.add_arc(p1.id, t1.id)
    return net


class TestAddObjectAndAddLink:
    def test_add_object_indexes_sequentially(self):
        model = ComposedModel(name="M")
        obj0 = model.add_object(_generator_net(), name="Gen")
        obj1 = model.add_object(_generator_net(), name="Gen2")
        assert obj0.index == 0
        assert obj1.index == 1
        assert len(model.objects) == 2

    def test_add_object_defaults_name_from_net(self):
        model = ComposedModel()
        obj = model.add_object(_generator_net())
        assert obj.name == "Generator"

    def test_add_link_appends(self):
        model = ComposedModel()
        model.add_object(_generator_net(), name="A")
        model.add_object(_generator_net(), name="B")
        link = model.add_link(LinkType.PLACE_FUSION, 0, 0, 1, 0)
        assert link in model.links
        assert link.type == LinkType.PLACE_FUSION

    def test_from_nets_convenience_constructor(self):
        model = ComposedModel.from_nets(
            [("A", _generator_net()), ("B", _generator_net())], name="Combined"
        )
        assert model.name == "Combined"
        assert [o.name for o in model.objects] == ["A", "B"]
        assert model.links == []


class TestComposedLinkInformationalScope:
    def test_informational_allowed_on_place_to_transition(self):
        link = ComposedLink(
            type=LinkType.PLACE_TO_TRANSITION,
            source_object=0, source_element=0,
            target_object=1, target_element=0,
            informational=True,
        )
        assert link.informational is True

    def test_informational_rejected_on_place_fusion(self):
        import pytest

        with pytest.raises(ValueError, match="informational"):
            ComposedLink(
                type=LinkType.PLACE_FUSION,
                source_object=0, source_element=0,
                target_object=1, target_element=0,
                informational=True,
            )

    def test_informational_rejected_on_transition_to_place(self):
        import pytest

        with pytest.raises(ValueError, match="informational"):
            ComposedLink(
                type=LinkType.TRANSITION_TO_PLACE,
                source_object=0, source_element=0,
                target_object=1, target_element=0,
                informational=True,
            )


class TestValidate:
    def test_valid_model_has_no_errors(self):
        model = ComposedModel.from_nets([("A", _generator_net()), ("B", _generator_net())])
        model.add_link(LinkType.PLACE_FUSION, 0, 0, 1, 0)
        assert model.validate() == []

    def test_empty_model_is_invalid(self):
        model = ComposedModel()
        errors = model.validate()
        assert any("no objects" in e for e in errors)

    def test_transition_with_no_input_at_all_is_invalid(self):
        net = PetriNet(name="Orphan")
        net.add_transition("Floating", mean_delay=1.0)
        model = ComposedModel.from_nets([("Orphan", net)])
        errors = model.validate()
        assert any("no consuming input" in e for e in errors)

    def test_place_to_transition_link_is_rejected(self):
        """PetriObjModelPaint retired this link type entirely, and validate()
        now matches: it is flagged outright, with no exemption left for the
        transition it would have fed — that transition is reported as
        having no consuming input too, since nothing feeds it any more."""
        fed = PetriNet(name="Fed")
        fed.add_transition("Work", mean_delay=1.0)
        source = _generator_net()
        model = ComposedModel.from_nets([("Fed", fed), ("Source", source)])
        model.add_link(
            LinkType.PLACE_TO_TRANSITION,
            source_object=1, source_element=0,
            target_object=0, target_element=0,
        )
        errors = model.validate()
        assert any("placeToTransition" in e for e in errors)
        assert any("no consuming input" in e for e in errors)

    def test_informational_place_to_transition_link_is_also_rejected(self):
        model = ComposedModel.from_nets([("A", _generator_net()), ("B", _generator_net())])
        model.add_link(
            LinkType.PLACE_TO_TRANSITION,
            source_object=1, source_element=0,
            target_object=0, target_element=0,
            informational=True,
        )
        errors = model.validate()
        assert any("placeToTransition" in e for e in errors)

    def test_transition_with_no_local_output_but_a_transition_to_place_link_is_valid(self):
        """The regression test for the validate_topology() divergence: a
        transition whose only output is a cross-object link must NOT be
        flagged, unlike PetriNet.validate_topology()'s stricter rule."""
        sink = _sink_net_no_local_output()
        target = _generator_net()
        model = ComposedModel.from_nets([("Sink", sink), ("Target", target)])
        deliver_transition = sink.transitions[0]
        assert deliver_transition.name == "Deliver"
        model.add_link(
            LinkType.TRANSITION_TO_PLACE,
            source_object=0, source_element=0,
            target_object=1, target_element=0,
        )
        errors = model.validate()
        assert errors == []

    def test_link_out_of_range_object_is_invalid(self):
        model = ComposedModel.from_nets([("A", _generator_net())])
        model.add_link(LinkType.PLACE_FUSION, 0, 0, 5, 0)
        errors = model.validate()
        assert any("source_object" not in e and "target_object 5" in e for e in errors) or \
            any("target_object 5" in e for e in errors)

    def test_link_out_of_range_element_is_invalid(self):
        model = ComposedModel.from_nets([("A", _generator_net()), ("B", _generator_net())])
        model.add_link(LinkType.PLACE_FUSION, 0, 99, 1, 0)
        errors = model.validate()
        assert any("source_element 99" in e for e in errors)

    def test_place_to_transition_link_is_rejected_even_with_out_of_range_indices(self):
        """The link-type rejection fires before endpoint indices are even
        looked at — a placeToTransition link is invalid regardless of
        whether its indices would otherwise resolve."""
        model = ComposedModel.from_nets([("A", _generator_net()), ("B", _generator_net())])
        model.add_link(LinkType.PLACE_TO_TRANSITION, 0, 1, 1, 0)
        errors = model.validate()
        assert any("placeToTransition" in e for e in errors)
        assert not any("source_element" in e for e in errors)

    def test_id_ending_in_newline_is_not_a_valid_ncname(self):
        """`_NCNAME_RE` used to be checked with `.match`, and `$` matches
        right before a final newline rather than only at the true end of
        string, so an id like "p1\\n" used to clear this pre-flight gate and
        only fail once export actually ran."""
        net = PetriNet(name="BadId")
        net.add_place("P1", tokens=0, place_id="p1\n")
        model = ComposedModel.from_nets([("BadId", net)])
        errors = model.validate()
        assert any("p1\n" in e and "not a valid XML NCName" in e for e in errors)


class TestResolveElementId:
    def test_resolves_place_and_transition_ids(self):
        model = ComposedModel.from_nets([("A", _generator_net())])
        obj = model.get_object(0)
        assert model.resolve_element_id(0, 0, "place") == obj.net.places[0].id
        assert model.resolve_element_id(0, 0, "transition") == obj.net.transitions[0].id

    def test_out_of_range_raises(self):
        import pytest

        model = ComposedModel.from_nets([("A", _generator_net())])
        with pytest.raises(ValueError, match="no place at index"):
            model.resolve_element_id(0, 99, "place")
