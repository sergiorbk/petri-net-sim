"""Real RELAX NG validation of every PNML document this backend writes.

The hand-rolled invariant checks in `services/petri/exporter/invariants.py`
catch what matters at export time (cheaply, with no extra dependency); this
module is the other half the contract calls for: validate actual exporter
output against the real ISO/IEC 15909-2 grammar (`tests/schema/ptnet.pntd`,
which pulls in `pnmlcoremodel.rng`, `conventions.rng` and `anyElement.rng` via
relative `<include>`), using `lxml.etree.RelaxNG`. A schema can only state
what a single element's content model allows; it cannot state document-wide
rules like "every id is unique" or "an arc's endpoints are both on its own
page", so `_assert_semantic_rules` below covers exactly the rules the schema
cannot, for every document this module validates.

Covers, per the contract: (a) PNMLExporter on a rich flat net, (b)
ComposedPNMLExporter on a rich composed model, (c) the backend's own golden
fixture, (d) the frontend's copy of the same golden fixture (skipped, not
failed, if the frontend checkout is not present next to this one).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from src.domain.composed import ComposedModel, LinkType
from src.domain.models import PetriNet
from src.services.petri.exporter import ComposedPNMLExporter, PNMLExporter

_PNML_NS = "{http://www.pnml.org/version-2009/grammar/pnml}"
_SCHEMA_PATH = Path(__file__).parent / "schema" / "ptnet.pntd"
_BACKEND_FIXTURE = Path(__file__).parent / "fixtures" / "composed_conformant_v21.pnml"
# tests/ -> backend/ -> repo root, the same climb test_composed_pnml_exporter.py's
# version-sync test uses to reach frontend/package.json.
_REPO_ROOT = Path(__file__).parent.parent.parent
_FRONTEND_FIXTURE = (
    _REPO_ROOT / "frontend" / "src" / "lib" / "__fixtures__" / "composed_conformant_v21.pnml"
)

_REFERENCE_TAGS = ("referencePlace", "referenceTransition")
_NODE_TAGS = ("place", "transition", *_REFERENCE_TAGS)


@pytest.fixture(scope="module")
def relaxng() -> etree.RelaxNG:
    """The ptnet grammar, parsed once and reused by every test below."""
    return etree.RelaxNG(etree.parse(str(_SCHEMA_PATH)))


def _assert_rng_valid(xml_text: str, relaxng_schema: etree.RelaxNG, *, label: str) -> etree._Element:
    """Validate `xml_text` against the ptnet grammar; return the parsed root
    on success so callers can run the semantic checks against the same tree."""
    root = etree.fromstring(xml_text.encode("utf-8"))
    if not relaxng_schema.validate(root):
        pytest.fail(f"{label} is not RELAX NG conformant:\n{relaxng_schema.error_log}")
    return root


def _all_pages(scope: etree._Element) -> list[etree._Element]:
    """Every `<page>` under `scope`, recursively: a nested object's page sits
    inside its parent's, the way ISO/IEC 15909-2 states a page hierarchy."""
    found: list[etree._Element] = []
    for page in scope.findall(f"{_PNML_NS}page"):
        found.append(page)
        found.extend(_all_pages(page))
    return found


def _assert_semantic_rules(root: etree._Element, *, label: str) -> None:
    """The rules a RELAX NG grammar cannot express, checked against the
    already-parsed document a schema-validity check just accepted:

    - every id in the document (place/transition/referencePlace/
      referenceTransition AND arc) is unique across the whole document, not
      merely within one page, and not merely within its own element kind;
    - every reference node resolves, acyclically, to a real (non-reference)
      node of the SAME kind it claims to stand for;
    - every arc's source and target both exist on the arc's OWN page;
    - the document stays bipartite (place <-> transition only, never
      place-place or transition-transition) once a reference node is
      resolved to the kind it stands for.
    """
    net = root.find(f"{_PNML_NS}net")
    assert net is not None, f"{label}: no <net> element"
    pages = _all_pages(net)
    assert pages, f"{label}: document has no <page>"

    kind_of: dict[str, str] = {}
    ref_of: dict[str, str] = {}
    ids: list[str] = []
    node_page: dict[str, etree._Element] = {}

    for page in pages:
        for tag in _NODE_TAGS:
            for el in page.findall(f"{_PNML_NS}{tag}"):
                eid = el.get("id")
                ids.append(eid)
                node_page[eid] = page
                kind_of[eid] = "place" if tag in ("place", "referencePlace") else "transition"
                if tag in _REFERENCE_TAGS:
                    ref_of[eid] = el.get("ref")
        # Arc ids share the same id space as node ids in PNML: a duplicated
        # arc id, or an arc id colliding with a node id, is exactly as broken
        # a document as a duplicated node id, so it belongs in the same
        # uniqueness check rather than a separate one only nodes go through.
        for arc in page.findall(f"{_PNML_NS}arc"):
            ids.append(arc.get("id"))

    assert len(ids) == len(set(ids)), f"{label}: duplicate id among {ids}"

    for eid, ref in ref_of.items():
        seen = {eid}
        current = ref
        while current in ref_of:
            assert current not in seen, f"{label}: reference cycle starting at '{eid}'"
            seen.add(current)
            current = ref_of[current]
        assert current in kind_of, f"{label}: reference '{eid}' points at missing id '{current}'"
        assert kind_of[current] == kind_of[eid], (
            f"{label}: reference '{eid}' ({kind_of[eid]}) resolves to '{current}' "
            f"({kind_of[current]}), a kind mismatch"
        )

    for page in pages:
        page_node_ids = {eid for eid, p in node_page.items() if p is page}
        for arc in page.findall(f"{_PNML_NS}arc"):
            aid = arc.get("id")
            src, tgt = arc.get("source"), arc.get("target")
            assert src in page_node_ids, f"{label}: arc '{aid}' source '{src}' not on its own page"
            assert tgt in page_node_ids, f"{label}: arc '{aid}' target '{tgt}' not on its own page"
            assert kind_of[src] != kind_of[tgt], (
                f"{label}: arc '{aid}' connects two {kind_of[src]}s ({src} -> {tgt}), not bipartite"
            )


def _rich_flat_net() -> PetriNet:
    """One of everything the flat exporter can write: fractional coordinates,
    det/exp/norm distributions, priorities, a read arc, an inhibitor arc, and
    a non-zero initial marking.

    Used to leave the inhibitor arc out: `net.pnml.j2` used to also write a
    standard-namespace `<type value="inhibitorArc"/>` sibling on one, which is
    not a legal `<arc>` child anywhere in the ptnet grammar (`arc.labels`
    allows only an optional `PTArcAnnotation`, i.e. `<inscription>`, confirmed
    against `tests/schema/ptnet.pntd`). Now that the template only carries the
    toolspecific `<arcType>` (which the composed exporter already did, see its
    own arc macro), an inhibitor arc belongs in this fixture like every other
    arc kind.
    """
    net = PetriNet(name="RichFlatNet")
    p_in = net.add_place("Input", tokens=3, x=10.4, y=20.6)
    p_out = net.add_place("Output", tokens=0, x=250.7, y=40.3)
    p_guard = net.add_place("Guard", tokens=0, x=70.2, y=80.8)

    t_det = net.add_transition("Det", mean_delay=1.5, distribution="det", priority=2, x=130.5, y=30.1)
    t_exp = net.add_transition("Exp", mean_delay=2.5, distribution="exp", priority=1, x=180.9, y=15.0)
    t_norm = net.add_transition(
        "Norm", mean_delay=3.0, distribution="norm", standard_deviation=0.5, priority=3, x=220.1, y=60.4
    )

    net.add_arc(p_in.id, t_det.id, weight=2)
    net.add_arc(p_in.id, t_exp.id, arc_type="read")
    net.add_arc(p_guard.id, t_det.id, arc_type="inhibitor")
    net.add_arc(t_det.id, p_out.id, weight=3)
    net.add_arc(t_exp.id, p_out.id)
    net.add_arc(p_in.id, t_norm.id)
    net.add_arc(t_norm.id, p_out.id)
    return net


def _rich_composed_model() -> ComposedModel:
    """One of everything the composed exporter can write: three objects,
    one nested inside another (`Inner` inside `Outer`) and one sitting at
    the top level (`Leaf`); a placeFusion link (projects as a
    `<referencePlace>`); a transitionToPlace link with quantity > 1
    (projects as a representative `<referencePlace>` standing for the target
    place, plus a link arc); and fractional coordinates throughout.

    No placeToTransition link: PetriObjModelPaint retired that link type, and
    the exporter now refuses a model that has one (see
    test_composed_pnml_exporter.py's test_place_to_transition_link_raises).
    """
    model = ComposedModel(name="RichComposed")

    outer = PetriNet(name="Outer")
    outer.add_place("P1", tokens=2, x=10.3, y=20.7, place_id="o_p1")
    outer.add_transition(
        "T1", mean_delay=1.0, distribution="det", priority=1, x=60.6, y=20.2, transition_id="o_t1"
    )
    outer.add_arc("o_p1", "o_t1", arc_id="o_a1")

    inner = PetriNet(name="Inner")
    inner.add_place("P1", tokens=0, x=10.1, y=10.9, place_id="i_p1")
    inner.add_transition(
        "T1", mean_delay=2.0, distribution="exp", priority=1, x=50.4, y=10.1, transition_id="i_t1"
    )
    inner.add_arc("i_p1", "i_t1", arc_id="i_a1")

    leaf = PetriNet(name="Leaf")
    leaf.add_place("P1", tokens=1, x=5.5, y=5.5, place_id="l_p1")
    leaf.add_transition(
        "T1", mean_delay=3.0, distribution="norm", standard_deviation=0.2, priority=1,
        x=40.2, y=5.1, transition_id="l_t1",
    )
    leaf.add_arc("l_p1", "l_t1", arc_id="l_a1")

    model.add_object(outer, name="Outer", priority=0, x=10.2, y=20.8, width=180.3, height=120.6)
    model.add_object(inner, name="Inner", priority=0, x=15.5, y=25.1, parent=0)
    model.add_object(leaf, name="Leaf", priority=0, x=300.7, y=40.4)

    model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=0, target_object=1, target_element=0)
    model.add_link(
        LinkType.TRANSITION_TO_PLACE, source_object=1, source_element=0, target_object=2, target_element=0,
        quantity=4,
    )
    return model


class TestFlatExporterRngConformance:
    """(a): PNMLExporter output for a rich flat net, inhibitor arc included."""

    def test_rich_flat_net_is_rng_conformant(self, relaxng):
        xml = PNMLExporter().export(_rich_flat_net())
        root = _assert_rng_valid(xml, relaxng, label="rich flat net")
        _assert_semantic_rules(root, label="rich flat net")


class TestComposedExporterRngConformance:
    """(b): ComposedPNMLExporter output for a rich composed model."""

    def test_rich_composed_model_is_rng_conformant(self, relaxng):
        xml = ComposedPNMLExporter().export(_rich_composed_model())
        root = _assert_rng_valid(xml, relaxng, label="rich composed model")
        _assert_semantic_rules(root, label="rich composed model")


class TestGoldenFixturesRngConformance:
    """(c)/(d): the golden fixture both tools' exporters are pinned against,
    backend copy and frontend copy, must each independently be conformant
    (they are compared for semantic equality elsewhere, not here)."""

    def test_backend_fixture_is_rng_conformant(self, relaxng):
        xml = _BACKEND_FIXTURE.read_text(encoding="utf-8")
        root = _assert_rng_valid(xml, relaxng, label="backend composed_conformant_v21.pnml")
        _assert_semantic_rules(root, label="backend composed_conformant_v21.pnml")

    def test_frontend_fixture_is_rng_conformant(self, relaxng):
        if not _FRONTEND_FIXTURE.exists():
            pytest.skip(
                f"frontend fixture not found at {_FRONTEND_FIXTURE} "
                "(frontend checkout not present next to this backend checkout)"
            )
        xml = _FRONTEND_FIXTURE.read_text(encoding="utf-8")
        root = _assert_rng_valid(xml, relaxng, label="frontend composed_conformant_v21.pnml")
        _assert_semantic_rules(root, label="frontend composed_conformant_v21.pnml")


class TestSemanticRulesArcIdUniqueness:
    """`_assert_semantic_rules`'s uniqueness check spans arc ids too, not
    merely node ids: a duplicated arc id, or an arc id colliding with a node
    id, is exactly as broken a document as two places sharing an id, and used
    to slip past this check entirely because only `_NODE_TAGS` were collected
    into `ids`."""

    _DOC = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <page id="page1">
      <place id="p1"><name><text>P1</text></name></place>
      <transition id="t1"><name><text>T1</text></name></transition>
      <arc id="{arc1}" source="p1" target="t1">
        <inscription><text>1</text></inscription>
      </arc>
      <arc id="{arc2}" source="p1" target="t1">
        <inscription><text>1</text></inscription>
      </arc>
    </page>
  </net>
</pnml>"""

    def test_duplicated_arc_id_is_rejected(self):
        root = etree.fromstring(self._DOC.format(arc1="a1", arc2="a1").encode("utf-8"))
        with pytest.raises(AssertionError, match="duplicate id"):
            _assert_semantic_rules(root, label="duplicate arc id fixture")

    def test_arc_id_colliding_with_node_id_is_rejected(self):
        root = etree.fromstring(self._DOC.format(arc1="p1", arc2="a2").encode("utf-8"))
        with pytest.raises(AssertionError, match="duplicate id"):
            _assert_semantic_rules(root, label="arc/node id collision fixture")
