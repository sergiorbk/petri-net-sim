"""Fixture round trips for the Python PNML importer.

Reads the same fixtures test_pnml_rng_conformance.py already validates the
EXPORTER against, from the importer's side: the backend's own golden
composed_conformant_v21.pnml, the frontend's copy of it (skipped if that
checkout is not present next to this one, same convention as
test_pnml_rng_conformance.py), and the two real PetriObjModelPaint exports
under frontend/src/lib/__fixtures__ (desktop_export_new_petrinet.pnml:
three-level nest, two fusions, a Free elements page, an invalid net id;
desktop_export_flat.pnml: a plain flat document with neither <graphics> nor
toolspecific <coordinates> at all).

Each fixture is: (a) parsed and checked against the same structure/warning
expectations pnml-import.test.ts pins for it, (b) round-tripped through a
PetriNetSession (phase 2) and the resulting PNML re-validated against the
vendored RELAX NG grammar (tests/schema/ptnet.pntd). For the conformant
fixture specifically, the re-export is also checked for CANONICAL semantic
identity against the original: re-parsing both sides and comparing places/
transitions/arcs/objects/links by what they mean, not by the frame/link ids
each side happens to mint (frame ids are not preserved through a full PNML
round trip -- the composed exporter always numbers pages by the ComposedModel's
own object index, discarding whatever id the source page used, exactly as
composed_convert.py's own docstring documents for `composed_model_to_net_data`;
this is a property of the wire format itself, not something to paper over).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from src.services.petri.importer import parse_pnml
from src.services.petri.session import PetriNetSession

_BACKEND_FIXTURE = Path(__file__).parent / "fixtures" / "composed_conformant_v21.pnml"
_SCHEMA_PATH = Path(__file__).parent / "schema" / "ptnet.pntd"
# tests/ -> backend/ -> repo root, the same climb test_composed_pnml_exporter.py's
# version-sync test and test_pnml_rng_conformance.py both use.
_REPO_ROOT = Path(__file__).parent.parent.parent
_FRONTEND_DIR = _REPO_ROOT / "frontend" / "src" / "lib" / "__fixtures__"
_FRONTEND_FIXTURE = _FRONTEND_DIR / "composed_conformant_v21.pnml"
_DESKTOP_NESTED_FIXTURE = _FRONTEND_DIR / "desktop_export_new_petrinet.pnml"
_DESKTOP_FLAT_FIXTURE = _FRONTEND_DIR / "desktop_export_flat.pnml"


def _by_id(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


@pytest.fixture(scope="module")
def relaxng() -> etree.RelaxNG:
    return etree.RelaxNG(etree.parse(str(_SCHEMA_PATH)))


def _assert_reexport_is_rng_conformant(net_data: dict, relaxng_schema: etree.RelaxNG, *, label: str) -> None:
    """Rebuilds a PetriNetSession from *net_data* (the phase 2 converter),
    re-exports it to PNML, and validates that output against the vendored
    ptnet grammar -- the "re-export through the session validates against
    the vendored RNG grammar" half of the fixture-round-trip contract."""
    session = PetriNetSession.from_net_data(net_data)
    xml = session.export_pnml()
    root = etree.fromstring(xml.encode("utf-8"))
    if not relaxng_schema.validate(root):
        pytest.fail(f"{label}: session re-export is not RELAX NG conformant:\n{relaxng_schema.error_log}")


def _canonicalize(net_data: dict) -> dict:
    """A frame/link-id-independent view of one net_data document, for
    comparing two documents by what they MEAN rather than by which
    arbitrary frame/link ids each side happens to carry (see module
    docstring: frame ids are not stable across a full PNML round trip by
    design, and link ids never were -- composed_convert.py's own docstring
    documents both). Place, transition and (local) arc ids ARE preserved
    exactly by the converter, so those are compared directly.
    """
    obj_name_by_id = {o["id"]: o["name"] for o in net_data.get("objects", [])}

    def owner_by_name(el: dict) -> dict:
        el = dict(el)
        if "objectId" in el:
            el["objectId"] = obj_name_by_id.get(el["objectId"], el["objectId"])
        return el

    places = sorted((owner_by_name(p) for p in net_data.get("places", [])), key=lambda p: p["id"])
    transitions = sorted((owner_by_name(t) for t in net_data.get("transitions", [])), key=lambda t: t["id"])
    arcs = sorted(net_data.get("arcs", []), key=lambda a: a["id"])

    objects = []
    for o in net_data.get("objects", []):
        o2 = {k: v for k, v in o.items() if k != "id"}
        if "objectId" in o2:
            o2["objectId"] = obj_name_by_id.get(o2["objectId"], o2["objectId"])
        objects.append(o2)
    objects.sort(key=lambda o: o["name"])

    links = sorted(
        (
            {
                "type": link["type"], "sourceId": link["sourceId"], "targetId": link["targetId"],
                "quantity": link["quantity"], "informational": link.get("informational", False),
            }
            for link in net_data.get("links", [])
        ),
        key=lambda link: (link["type"], link["sourceId"], link["targetId"]),
    )

    return {
        "name": net_data.get("name"),
        "places": places,
        "transitions": transitions,
        "arcs": arcs,
        "objects": objects,
        "links": links,
    }


class TestConformantFixtureRoundTrip:
    """The backend's own golden composed_conformant_v21.pnml fixture."""

    def test_backend_copy_parses_with_expected_structure(self, relaxng):
        xml = _BACKEND_FIXTURE.read_text(encoding="utf-8")
        data, warnings = parse_pnml(xml)

        assert warnings == []
        assert data["name"] == "PipelineDemo"
        assert [o["name"] for o in data["objects"]] == ["Generator", "Server"]
        assert len(data["places"]) == 6
        assert len(data["transitions"]) == 3
        assert len(data["arcs"]) == 7
        assert len(data["links"]) == 2

        fusion = next(link for link in data["links"] if link["type"] == "placeFusion")
        assert fusion == {"id": fusion["id"], "type": "placeFusion", "sourceId": "p_ready", "targetId": "p_in", "quantity": 1}
        feed = next(link for link in data["links"] if link["type"] == "transitionToPlace")
        assert feed["sourceId"] == "t_start"
        assert feed["targetId"] == "p_log"
        assert feed["quantity"] == 2

        _assert_reexport_is_rng_conformant(data, relaxng, label="backend composed_conformant_v21.pnml")

    def test_backend_copy_reexport_is_canonically_identical_to_input(self):
        xml = _BACKEND_FIXTURE.read_text(encoding="utf-8")
        original, _ = parse_pnml(xml)
        session = PetriNetSession.from_net_data(original)
        reexported, _ = parse_pnml(session.export_pnml())

        assert _canonicalize(original) == _canonicalize(reexported)

    def test_frontend_copy_matches_the_backend_copy(self, relaxng):
        if not _FRONTEND_FIXTURE.exists():
            pytest.skip(
                f"frontend fixture not found at {_FRONTEND_FIXTURE} "
                "(frontend checkout not present next to this backend checkout)"
            )
        backend_data, backend_warnings = parse_pnml(_BACKEND_FIXTURE.read_text(encoding="utf-8"))
        frontend_data, frontend_warnings = parse_pnml(_FRONTEND_FIXTURE.read_text(encoding="utf-8"))

        assert frontend_warnings == []
        assert _canonicalize(backend_data) == _canonicalize(frontend_data)

        _assert_reexport_is_rng_conformant(frontend_data, relaxng, label="frontend composed_conformant_v21.pnml")

    def test_frontend_copy_reexport_is_canonically_identical_to_input(self):
        if not _FRONTEND_FIXTURE.exists():
            pytest.skip(
                f"frontend fixture not found at {_FRONTEND_FIXTURE} "
                "(frontend checkout not present next to this backend checkout)"
            )
        original, _ = parse_pnml(_FRONTEND_FIXTURE.read_text(encoding="utf-8"))
        session = PetriNetSession.from_net_data(original)
        reexported, _ = parse_pnml(session.export_pnml())

        assert _canonicalize(original) == _canonicalize(reexported)


class TestExplicitPriorityZeroRoundTrip:
    """PetriObjModelPaint writes priority="0" as its own default, and this
    reader deliberately keeps an explicit 0 rather than treating it as
    unset (see test_bad_number_malformed_priority_falls_back_but_explicit_0_is_not_malformed
    in test_pnml_importer.py). This is the other half of that contract:
    a document stating priority 0 must not merely PARSE that way, it must
    actually LOAD -- Transition.priority is ge=0, not ge=1, precisely so
    PetriNetSession.from_net_data doesn't explode on it -- and the
    resulting session must re-export a document that still says
    <priority>0</priority> and still validates against the vendored
    RELAX NG grammar."""

    _XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Priority Zero</text></name>
    <place id="p1">
      <name><text>Input</text></name>
      <initialMarking><text>1</text></initialMarking>
    </place>
    <place id="p2">
      <name><text>Output</text></name>
    </place>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="PetriObjModel" version="1.0">
        <priority>0</priority>
      </toolspecific>
    </transition>
    <arc id="a1" source="p1" target="t1"><inscription><text>1</text></inscription></arc>
    <arc id="a2" source="t1" target="p2"><inscription><text>1</text></inscription></arc>
  </net>
</pnml>"""

    def test_imports_with_no_warning_loads_and_reexports_priority_0(self, relaxng):
        data, warnings = parse_pnml(self._XML)
        assert warnings == []
        assert data["transitions"][0]["priority"] == 0

        session = PetriNetSession.from_net_data(data)
        xml = session.export_pnml()
        assert "<priority>0</priority>" in xml

        _assert_reexport_is_rng_conformant(data, relaxng, label="explicit priority-0 transition")


class TestDesktopInteropFixtures:
    """Real files PetriObjModelPaint itself wrote, not hand-authored
    approximations of its shape -- mirrors pnml-import.test.ts's
    "parsePnml, desktop interop fixtures" describe block exactly."""

    def _require(self, path: Path) -> None:
        if not path.exists():
            pytest.skip(f"fixture not found at {path} (frontend checkout not present next to this backend checkout)")

    def test_nested_export_three_level_nest_two_fusions_free_page_invalid_net_id(self, relaxng):
        self._require(_DESKTOP_NESTED_FIXTURE)
        data, warnings = parse_pnml(_DESKTOP_NESTED_FIXTURE.read_text(encoding="utf-8"))

        # The only warning is about the net's own id ("New PetriNet" has a
        # space in it); every element id in the file is already a valid
        # NCName, so nothing else is remapped or warned about.
        assert len(warnings) == 1
        assert warnings[0]["code"] == "invalid-id"
        assert "New PetriNet" in warnings[0]["message"]

        # Structure: three pages carry real petriObject geometry and
        # become frames, nested Object 1 inside Object 2 inside Object 3;
        # the fourth page ("Free elements") has an all-zero marker and
        # stays the unframed bucket rather than becoming a frame of its own.
        assert len(data["objects"]) == 3
        by_name = {o["name"]: o for o in data["objects"]}
        object1, object2, object3 = by_name["Object 1"], by_name["Object 2"], by_name["Object 3"]
        assert object1["objectId"] == object2["id"]
        assert object2["objectId"] == object3["id"]
        assert "objectId" not in object3

        # Element counts read straight off the fixture: 6 places (2 of
        # them restored fusion members), 3 transitions, 7 arcs, 2 fusion
        # links.
        assert len(data["places"]) == 6
        assert len(data["transitions"]) == 3
        assert len(data["arcs"]) == 7
        assert len(data["links"]) == 2
        assert all(link["type"] == "placeFusion" for link in data["links"])
        fusion_pairs = sorted(f'{link["sourceId"]}->{link["targetId"]}' for link in data["links"])
        assert fusion_pairs == [
            "p-p1-ec3eda7c->p-p2-6a033dc2",
            "p-p2-826b107f->p-p3-91569318",
        ]

        # A nested-page member carries the objectId of the frame it sits
        # in; a Free-elements member carries none.
        p3 = _by_id(data["places"])["p-p3-91569318"]
        assert p3["objectId"] == object1["id"]
        free_place = _by_id(data["places"])["p-p1-2b462d12"]
        assert "objectId" not in free_place

        # Center-to-top-left conversion, one place and one transition,
        # both inside the innermost nested page.
        assert p3["graphics"] == {"x": 547, "y": 186}
        t2 = _by_id(data["transitions"])["t-t2-7d188d05"]
        assert t2["graphics"] == {"x": 493, "y": 182}

        _assert_reexport_is_rng_conformant(data, relaxng, label="desktop_export_new_petrinet.pnml")

    def test_flat_export_zero_warnings_and_fallback_positions(self, relaxng):
        self._require(_DESKTOP_FLAT_FIXTURE)
        data, warnings = parse_pnml(_DESKTOP_FLAT_FIXTURE.read_text(encoding="utf-8"))

        assert warnings == []
        assert len(data["places"]) == 2
        assert len(data["transitions"]) == 1
        assert len(data["arcs"]) == 2
        # A flat, single-page document with no petriObject or reference
        # markers never enters the composed reader, so it never gets an
        # objects array.
        assert "objects" not in data

        # Neither the place nor the transition carries a <graphics>
        # element or a toolspecific <coordinates>, so the (0, 0) fallback
        # feeds the same center-to-top-left conversion as every other node.
        p1 = _by_id(data["places"])["p-testplace1-3e78ffc8"]
        assert p1["graphics"] == {"x": -28, "y": -28}
        t1 = _by_id(data["transitions"])["t-testtransition1-d4ef8c48"]
        assert t1["graphics"] == {"x": -14, "y": -32}

        _assert_reexport_is_rng_conformant(data, relaxng, label="desktop_export_flat.pnml")
