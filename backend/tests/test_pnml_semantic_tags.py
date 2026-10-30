"""Saving a model must preserve place roles used by simulation statistics."""

from pathlib import Path

from lxml import etree
import pytest

from src.domain.composed import ComposedModel, LinkType
from src.domain.models import PetriNet
from src.services.petri.agent_toolkit.operations import op_run_simulation
from src.services.petri.exporter import ComposedPNMLExporter, PNMLExporter
from src.services.petri.importer import parse_pnml
from src.services.petri.session import PetriNetSession


def validate_pnml(xml: str) -> None:
    schema = etree.RelaxNG(etree.parse(str(Path(__file__).parent / "schema" / "ptnet.pntd")))
    document = etree.fromstring(xml.encode())
    assert schema.validate(document), schema.error_log


@pytest.mark.parametrize("composed", [False, True])
def test_throughput_role_survives_export_import_and_simulation(composed):
    net = PetriNet(name="Finite service")
    source = net.add_place("Source", tokens=6)
    completed = net.add_place("Completed", tag="throughput")
    transition = net.add_transition("Service", distribution="det", mean_delay=1)
    net.add_arc(source.id, transition.id)
    net.add_arc(transition.id, completed.id)
    if composed:
        model = ComposedModel(name="Finite service")
        model.add_object(net, name="Service module")
        xml = ComposedPNMLExporter().export(model)
    else:
        xml = PNMLExporter().export(net)
    validate_pnml(xml)
    data, warnings = parse_pnml(xml)
    assert not warnings
    assert next(place for place in data["places"] if place["name"] == "Completed")["tag"] == "throughput"
    restored = PetriNetSession.from_net_data(data, auto_optimize=False)
    result = op_run_simulation(restored, simulation_time=10)
    assert "Completed: marking=6," in result
    assert "Completed: total_consumed=6" in result


def test_fusion_reference_preserves_its_own_semantic_role():
    first = PetriNet(name="First")
    first.add_place("First counter", tag="throughput")
    second = PetriNet(name="Second")
    second.add_place("Second counter", tag='custom & "quoted"')
    model = ComposedModel(name="Shared counter")
    model.add_object(first, name="First")
    model.add_object(second, name="Second")
    model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=0, target_object=1, target_element=0)
    xml = ComposedPNMLExporter().export(model)
    validate_pnml(xml)
    data, warnings = parse_pnml(xml)
    assert not warnings
    assert {place["name"]: place.get("tag") for place in data["places"]} == {
        "First counter": "throughput", "Second counter": 'custom & "quoted"',
    }
