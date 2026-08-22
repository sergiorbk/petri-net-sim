"""Export tests for contract phase 2, part B / E's export bullet:

- a composed PetriNetSession's export_pnml (and the op_export_pnml tool
  operation built on it) goes through ComposedPNMLExporter, validates
  against the vendored RELAX NG grammar, and re-parses to the expected
  element counts (reusing test_pnml_rng_conformance.py's own helpers,
  rather than re-implementing RNG validation here);
- a flat (no objects, no links) session's export_pnml stays byte-stable
  against calling PNMLExporter directly -- the exact call session.py's
  flat branch still makes, unchanged from phase 1.
"""

from __future__ import annotations

import pytest
from lxml import etree

from src.services.petri.agent_toolkit import operations as ops
from src.services.petri.agent_toolkit.errors import ToolError
from src.services.petri.exporter import PNMLExporter
from src.services.petri.session import PetriNetSession
from tests.test_pnml_rng_conformance import _SCHEMA_PATH, _assert_rng_valid, _assert_semantic_rules


def _ok(result) -> str:
    assert not isinstance(result, ToolError), f"expected success, got: {result}"
    return str(result)


def _err(result) -> str:
    assert isinstance(result, ToolError), f"expected a ToolError, got: {result!r}"
    return result.message


@pytest.fixture(scope="module")
def relaxng() -> etree.RelaxNG:
    """Same grammar test_pnml_rng_conformance.py validates against,
    reloaded here rather than imported as a fixture across modules
    (pytest fixtures are not shared by cross-module import, only the
    plain helper functions/constants are)."""
    return etree.RelaxNG(etree.parse(str(_SCHEMA_PATH)))


def _three_object_composed_session() -> PetriNetSession:
    """Loader --(transitionToPlace)--> Sink, plus a Buffer object fused to
    Loader's queue -- three named objects, two link types, mirroring the
    "rich composed model" shape test_pnml_rng_conformance.py's own fixture
    uses, but built through the real ops layer instead of ComposedModel
    directly."""
    session = PetriNetSession()

    _ok(ops.op_create_object(session, name="Loader", priority=2))
    _ok(ops.op_add_place(session, name="LoaderQueue", tokens=1))
    _ok(ops.op_add_transition(session, name="LoaderGo"))
    loader_place = session.net.places[0].id
    loader_trans = session.net.transitions[0].id
    _ok(ops.op_add_arc(session, source_id=loader_place, target_id=loader_trans))

    _ok(ops.op_create_object(session, name="Sink", priority=1))
    _ok(ops.op_add_place(session, name="SinkIn", tokens=0))
    _ok(ops.op_add_transition(session, name="SinkGo"))
    sink_place = session.net.places[0].id
    sink_trans = session.net.transitions[0].id
    _ok(ops.op_add_arc(session, source_id=sink_place, target_id=sink_trans))
    _ok(ops.op_add_place(session, name="SinkOut", tokens=0, tag="throughput"))
    sink_out = session.net.places[-1].id
    _ok(ops.op_add_arc(session, source_id=sink_trans, target_id=sink_out))

    _ok(ops.op_create_object(session, name="Buffer", priority=0))
    _ok(ops.op_add_place(session, name="BufferSlot", tokens=0))
    buffer_place = session.net.places[0].id

    _ok(ops.op_link_objects(
        session, link_type="transitionToPlace",
        source_object="Loader", source_element="LoaderGo",
        target_object="Sink", target_element="SinkIn",
    ))
    _ok(ops.op_link_objects(
        session, link_type="placeFusion",
        source_object="Loader", source_element="LoaderQueue",
        target_object="Buffer", target_element="BufferSlot",
    ))

    return session


class TestComposedSessionExportRngConformance:
    def test_composed_export_is_rng_conformant(self, relaxng):
        session = _three_object_composed_session()
        xml = _ok(ops.op_export_pnml(session))
        root = _assert_rng_valid(xml, relaxng, label="composed session export")
        _assert_semantic_rules(root, label="composed session export")

    def test_composed_export_reparses_to_the_expected_counts(self, relaxng):
        session = _three_object_composed_session()
        xml = _ok(ops.op_export_pnml(session))
        root = etree.fromstring(xml.encode("utf-8"))
        ns = "{http://www.pnml.org/version-2009/grammar/pnml}"

        # One page per object PLUS the free-elements (free pool) page,
        # exactly the way the frontend exporter treats an object never
        # placed on the canvas (ModelObject.free) -- 4 pages total here:
        # free pool, Loader, Sink, Buffer.
        pages = root.findall(f".//{ns}page")
        assert len(pages) == 4

        # Real (non-reference) nodes: every place/transition the session
        # actually built, minus the placeFusion SOURCE (LoaderQueue),
        # which becomes a <referencePlace> instead of a <place> -- the
        # link's TARGET side survives (PetriObjModel.wire() keeps the
        # target), so it is Buffer's own BufferSlot that stays real here.
        real_places = root.findall(f".//{ns}place")
        real_transitions = root.findall(f".//{ns}transition")
        assert len(real_places) == 3  # SinkIn, SinkOut, BufferSlot (fusion survivor)
        assert len(real_transitions) == 2  # LoaderGo, SinkGo

        reference_places = root.findall(f".//{ns}referencePlace")
        assert len(reference_places) == 2  # LoaderQueue's fusion reference + LoaderGo's transitionToPlace target stand-in

        # petriObjectLinks entries: one per link_objects call made while
        # building the session. Namespace-agnostic lookup ({*}link): a
        # toolspecific block's own children inherit whatever default
        # namespace is in scope at that point in the document.
        link_elements = root.findall(".//{*}link")
        assert len(link_elements) == 2

    def test_flat_session_stays_flat_when_object_tools_are_never_used(self, relaxng):
        """Sanity check alongside the composed test above: a session that
        never calls create_object exports via the FLAT exporter (single
        page, no petriObjectLinks), not the composed one -- confirmed
        directly in TestFlatSessionExportByteStable below, and re-checked
        here against the real grammar for good measure."""
        session = PetriNetSession()
        _ok(ops.op_add_place(session, name="P", tokens=1))
        _ok(ops.op_add_transition(session, name="T"))
        p_id, t_id = session.net.places[0].id, session.net.transitions[0].id
        _ok(ops.op_add_arc(session, source_id=p_id, target_id=t_id))

        xml = _ok(ops.op_export_pnml(session))
        root = _assert_rng_valid(xml, relaxng, label="flat session export")
        _assert_semantic_rules(root, label="flat session export")
        ns = "{http://www.pnml.org/version-2009/grammar/pnml}"
        assert len(root.findall(f".//{ns}page")) == 1


class TestComposedSessionExportInvariantChecked:
    """'Both stay invariant-checked' (contract B's export bullet): a
    composed session that would export something ComposedModel.validate()
    itself calls out is refused with the finding, not a raw exporter
    traceback or a silently-wrong PNML document."""

    def test_export_refuses_a_model_with_no_consuming_input(self):
        session = PetriNetSession()
        _ok(ops.op_create_object(session, name="A"))
        _ok(ops.op_add_place(session, name="Idle", tokens=1))
        _ok(ops.op_add_transition(session, name="Orphan"))

        message = _err(ops.op_export_pnml(session))
        assert "Cannot export composed model" in message
        assert "no consuming input" in message

    def test_export_refuses_a_placetotransition_link_loaded_from_data(self):
        session, *_ = (_three_object_composed_session(), None)
        from src.domain.composed import LinkType

        loader_place = session.objects[0].net.places[0].id
        sink_trans = session.objects[1].net.transitions[0].id
        session.add_link(
            LinkType.PLACE_TO_TRANSITION,
            session.objects[0].frame_id, loader_place,
            session.objects[1].frame_id, sink_trans,
        )
        message = _err(ops.op_export_pnml(session))
        assert "placeToTransition links are not supported" in message


class TestFlatSessionExportByteStable:
    """Contract E: 'flat session export byte-stable vs phase 1' -- a
    session with no named objects and no links keeps exporting through
    PNMLExporter on the active net exactly as session.py always called
    it, unchanged by Part B's composed branch in export_pnml."""

    def _built_flat_session(self) -> PetriNetSession:
        session = PetriNetSession()
        gen = session.builder.add_generator("Arrivals", interval=5.0)
        machine = session.builder.add_machine("Lathe", processing_time=10.0, channels=2)
        session.builder.connect(gen.interface.output_place_id, machine.interface.input_place_id)
        return session

    def test_session_export_pnml_matches_pnml_exporter_directly(self):
        session = self._built_flat_session()
        expected = PNMLExporter().export(session.net)
        assert session.export_pnml() == expected

    def test_op_export_pnml_matches_pnml_exporter_directly(self):
        session = self._built_flat_session()
        expected = PNMLExporter().export(session.net)
        assert _ok(ops.op_export_pnml(session)) == expected

    def test_creating_and_removing_an_object_returns_to_byte_stable_flat_export(self):
        """A session that touches object tools but ends up flat again
        (the last object removed) must not be permanently routed through
        the composed exporter -- is_composed is state, not history."""
        session = self._built_flat_session()
        _ok(ops.op_create_object(session, name="Temp"))
        _ok(ops.op_remove_object(session, name="Temp"))
        assert session.is_composed is False

        expected = PNMLExporter().export(session.net)
        assert session.export_pnml() == expected
