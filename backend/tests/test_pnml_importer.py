"""Unit tests for the Python PNML importer (services/petri/importer), ported
from the frontend's own test suite (frontend/src/lib/pnml-import.test.ts),
which is the normative reference for every scenario below. Each test class
mirrors one `describe` block there; see that file for the reasoning behind
each rule -- not repeated here, only the assertions that pin the behavior
down.

Fixture round trips (composed_conformant_v21.pnml, the desktop exports) live
in test_pnml_importer_fixtures.py, not here.
"""

from __future__ import annotations

import pytest

from src.services.petri.importer import parse_pnml
from src.services.petri.session import PetriNetSession

SAMPLE_PNML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name>
      <text>Test Net</text>
    </name>
    <place id="p1">
      <name><text>Input</text></name>
      <initialMarking><text>3</text></initialMarking>
      <toolspecific tool="PetriObjModel" version="1.0">
        <coordinates x="100" y="200"/>
      </toolspecific>
      <graphics><position x="100" y="200"/></graphics>
    </place>
    <place id="p2">
      <name><text>Output</text></name>
      <graphics><position x="300" y="200"/></graphics>
    </place>
    <transition id="t1">
      <name><text>Process</text></name>
      <toolspecific tool="PetriObjModel" version="1.0">
        <coordinates x="200" y="200"/>
        <timeDelay>5</timeDelay>
        <delayMeanValue>5</delayMeanValue>
        <distribution>exp</distribution>
        <priority>2</priority>
      </toolspecific>
      <graphics><position x="200" y="200"/></graphics>
    </transition>
    <arc id="a1" source="p1" target="t1">
      <graphics/>
      <inscription><text>1</text></inscription>
    </arc>
    <arc id="a2" source="t1" target="p2">
      <graphics/>
      <inscription><text>2</text></inscription>
    </arc>
  </net>
</pnml>"""


def _by_id(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


class TestParsePnml:
    """Mirrors describe("parsePnml", ...)."""

    def test_parses_places_with_names_tokens_and_positions(self):
        data, _ = parse_pnml(SAMPLE_PNML)
        assert data["name"] == "Test Net"
        assert len(data["places"]) == 2

        p1 = _by_id(data["places"])["p1"]
        assert p1["name"] == "Input"
        assert p1["tokens"] == 3
        # Wire position is the place's CENTER (100, 200); the app model
        # keeps a top-left anchor, half the place's own size (56x56) back.
        assert p1["graphics"] == {"x": 72, "y": 172}

        p2 = _by_id(data["places"])["p2"]
        assert p2["name"] == "Output"
        assert p2["tokens"] == 0

    def test_parses_transitions_with_toolspecific_parameters(self):
        data, _ = parse_pnml(SAMPLE_PNML)
        assert len(data["transitions"]) == 1

        t1 = data["transitions"][0]
        assert t1["id"] == "t1"
        assert t1["name"] == "Process"
        assert t1["mean_delay"] == 5
        assert t1["distribution"] == "exp"
        assert t1["priority"] == 2
        # Same center-anchor conversion, using the transition's own size (28x64).
        assert t1["graphics"] == {"x": 186, "y": 168}

    def test_falls_back_to_toolspecific_coordinates_when_graphics_is_absent(self):
        # _extract_position's second branch: neither node carries a
        # <graphics><position>, only the toolspecific <coordinates> --
        # exercised by SAMPLE_PNML's own p1/t1 only as a tiebreak (both
        # are present there, and <graphics> wins), never on its own. The
        # center-to-top-left conversion still applies, using each kind's
        # own footprint (place 56x56, transition 28x64), so the two land
        # on different top-left offsets from the same (100, 100) wire
        # coordinate.
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Coordinates only</text></name>
    <place id="p1">
      <name><text>P1</text></name>
      <toolspecific tool="PetriObjModel" version="1.0">
        <coordinates x="100" y="100"/>
      </toolspecific>
    </place>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="PetriObjModel" version="1.0">
        <coordinates x="100" y="100"/>
      </toolspecific>
    </transition>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert data["places"][0]["graphics"] == {"x": 72, "y": 72}
        assert data["transitions"][0]["graphics"] == {"x": 86, "y": 68}

    def test_parses_arcs_with_weight(self):
        data, _ = parse_pnml(SAMPLE_PNML)
        assert len(data["arcs"]) == 2

        a1 = _by_id(data["arcs"])["a1"]
        assert a1["source_id"] == "p1"
        assert a1["target_id"] == "t1"
        assert a1["weight"] == 1

        a2 = _by_id(data["arcs"])["a2"]
        assert a2["source_id"] == "t1"
        assert a2["target_id"] == "p2"
        assert a2["weight"] == 2

    def test_throws_on_missing_pnml_root(self):
        with pytest.raises(ValueError, match="missing <pnml>"):
            parse_pnml("<notpnml/>")

    def test_throws_on_missing_net(self):
        with pytest.raises(ValueError, match="missing <net>"):
            parse_pnml(
                '<?xml version="1.0"?>'
                '<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml"></pnml>'
            )

    def test_degenerate_pnml_root_throws_missing_root_not_missing_net(self):
        # fast-xml-parser hands the frontend `doc.pnml`, and for a <pnml>
        # with no attribute, no child and no text at all -- exactly
        # "<pnml/>" -- that value is the empty string "", which the
        # frontend's own `if (!pnml) throw ...` treats as no root at all.
        # `xml.etree` DOES find a <pnml> element here (this reader's tag
        # match alone would proceed to look for <net> and report THAT
        # missing instead), so this is a deliberate divergence this
        # reader corrects for rather than one xml.etree forces on it. The
        # sibling test above (a <pnml> that carries a real xmlns
        # attribute but still no <net>) must keep reporting "missing
        # <net>": an xmlns declaration is a real, truthy `@_xmlns`
        # attribute to the frontend's parser too.
        with pytest.raises(ValueError, match="missing <pnml>"):
            parse_pnml("<pnml/>")

    def test_handles_probability_based_transitions(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Prob Net</text></name>
    <transition id="t1">
      <name><text>Branch</text></name>
      <toolspecific tool="PetriObjModel" version="1.0">
        <coordinates x="50" y="50"/>
        <probability>0.7</probability>
      </toolspecific>
      <graphics><position x="50" y="50"/></graphics>
    </transition>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        t = data["transitions"][0]
        assert t["probability"] == 0.7
        assert t["distribution"] is None


class TestParsePnmlComposedDocuments:
    """Mirrors describe("parsePnml, composed documents", ...)."""

    def test_reads_every_page_as_an_object_not_just_the_first(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Composed Net</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="First" priority="3" x="5" y="6"/>
      </toolspecific>
      <place id="p1"><name><text>P1</text></name><graphics><position x="0" y="0"/></graphics></place>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="Second" priority="0" x="7" y="8"/>
      </toolspecific>
      <place id="p2"><name><text>P2</text></name><graphics><position x="0" y="0"/></graphics></place>
    </page>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert [o["name"] for o in data["objects"]] == ["First", "Second"]
        assert data["objects"][0]["priority"] == 3
        assert [p["id"] for p in data["places"]] == ["p1", "p2"]
        assert data["places"][1]["objectId"] == "object1"

    def test_restores_a_fused_away_place_from_its_reference_node(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Composed Net</text></name>
    <page id="object0">
      <place id="p1"><name><text>P1</text></name><graphics><position x="0" y="0"/></graphics></place>
    </page>
    <page id="object1">
      <referencePlace id="p2" ref="p1">
        <name><text>P2</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>fusion</referenceRole>
          <fusedInitialMarking>4</fusedInitialMarking>
        </toolspecific>
      </referencePlace>
    </page>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        # The canvas draws both members of a fusion; the document draws one.
        assert [p["id"] for p in data["places"]] == ["p1", "p2"]
        assert data["places"][1]["tokens"] == 4

    def test_still_parses_every_existing_single_page_case(self):
        data, _ = parse_pnml(SAMPLE_PNML)
        assert len(data["places"]) == 2
        assert len(data["transitions"]) == 1
        assert len(data["arcs"]) == 2
        assert "objects" not in data
        assert "links" not in data


# ---------------------------------------------------------------------------
# Arc kinds: an inhibitor or read arc has no P/T-net form, so it only
# survives a save in a tool-specific block -- and three different blocks say
# it, because the desktop's PnmlParser.parseArcs accepts three.
# ---------------------------------------------------------------------------


class TestArcTypeRoundTrip:
    def test_reads_the_arc_kind_from_a_foreign_documents_shapes(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Foreign</text></name>
    <place id="p1"><name><text>P1</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="byAttribute" source="p1" target="t1" type="read">
      <inscription><text>1</text></inscription>
    </arc>
    <arc id="byToolspecific" source="p1" target="t1">
      <inscription><text>1</text></inscription>
      <toolspecific tool="PetriObjModel" version="1.0">
        <arcType>Inhibitor</arcType>
      </toolspecific>
    </arc>
    <arc id="byStandardType" source="p1" target="t1">
      <inscription><text>1</text></inscription>
      <type value="inhibitorArc"/>
    </arc>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        arcs = _by_id(data["arcs"])
        assert arcs["byAttribute"]["arc_type"] == "READ"
        # Case-insensitive, like PnmlParser.parseArcs.
        assert arcs["byToolspecific"]["arc_type"] == "INHIBITOR"
        assert arcs["byStandardType"]["arc_type"] == "INHIBITOR"

    def test_informational_flag_alone_reads_as_read_when_arctype_is_absent(self):
        # The fourth shape in the precedence chain: PetriObjModelPaint calls
        # a non-consuming input arc "informational" and writes it that way
        # even with no <arcType> at all. Reading only <arcType> would turn
        # every such arc into an ordinary one.
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Informational only</text></name>
    <place id="p1"><name><text>P1</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="a1" source="p1" target="t1">
      <inscription><text>1</text></inscription>
      <toolspecific tool="PetriObjModel" version="2.2.2">
        <informational>true</informational>
      </toolspecific>
    </arc>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert data["arcs"][0]["arc_type"] == "READ"

    def test_type_attribute_wins_over_a_disagreeing_toolspecific_arctype(self):
        # Precedence, highest first: the `type` attribute, then toolspecific
        # <arcType>, then <informational>, then the standard <type value=.../>.
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Disagreement</text></name>
    <place id="p1"><name><text>P1</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="a1" source="p1" target="t1" type="read">
      <inscription><text>1</text></inscription>
      <toolspecific tool="PetriObjModel" version="2.2.2">
        <arcType>inhibitor</arcType>
      </toolspecific>
    </arc>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert data["arcs"][0]["arc_type"] == "READ"

    def test_preserves_inhibitor_and_read_through_a_flat_export_and_reimport(self):
        net_data = {
            "name": "Kinds",
            "places": [
                {"id": "p1", "name": "P1", "tokens": 1, "graphics": {"x": 0, "y": 0}},
                {"id": "p2", "name": "P2", "tokens": 0, "graphics": {"x": 0, "y": 60}},
            ],
            "transitions": [{
                "id": "t1", "name": "T1", "priority": 1, "distribution": "exp", "mean_delay": 1,
                "standard_deviation": 0, "probability": None, "graphics": {"x": 60, "y": 0},
            }],
            "arcs": [
                {"id": "a1", "source_id": "p1", "target_id": "t1", "weight": 1, "arc_type": "INHIBITOR"},
                {"id": "a2", "source_id": "p2", "target_id": "t1", "weight": 2, "arc_type": "READ"},
                {"id": "a3", "source_id": "t1", "target_id": "p2", "weight": 1, "arc_type": "NORMAL"},
            ],
        }
        session = PetriNetSession.from_net_data(net_data)
        back, _ = parse_pnml(session.export_pnml())
        arcs = _by_id(back["arcs"])
        assert arcs["a1"]["arc_type"] == "INHIBITOR"
        assert arcs["a2"]["arc_type"] == "READ"
        assert arcs["a2"]["weight"] == 2
        assert arcs["a3"]["arc_type"] == "NORMAL"


# ---------------------------------------------------------------------------
# Toolspecific selection: PetriNetSim preferred, PetriObjModel the
# load-bearing fallback, and the `version` attribute never filters.
# ---------------------------------------------------------------------------


class TestToolspecificSelection:
    def test_falls_back_to_petriobjmodel_when_that_is_the_only_block(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Desktop only</text></name>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="PetriObjModel" version="2.2.2">
        <coordinates x="100" y="100"/>
        <priority>4</priority>
      </toolspecific>
    </transition>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert data["transitions"][0]["priority"] == 4

    def test_prefers_petrinetsim_when_both_blocks_disagree(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Disagreement</text></name>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="PetriObjModel" version="2.2.2">
        <priority>4</priority>
      </toolspecific>
      <toolspecific tool="PetriNetSim" version="1.0.0">
        <priority>9</priority>
      </toolspecific>
    </transition>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        # This app's own block wins even though it comes second in the file.
        assert data["transitions"][0]["priority"] == 9

    def test_ignores_a_third_toolspecific_block_named_neither_tool(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Foreign tool</text></name>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="SomeOtherTool" version="1.0">
        <priority>9</priority>
      </toolspecific>
      <toolspecific tool="PetriNetSim" version="1.0.0">
        <priority>3</priority>
      </toolspecific>
    </transition>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert data["transitions"][0]["priority"] == 3

    def test_delay_mean_value_wins_over_time_delay_when_both_are_present(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Delay precedence</text></name>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="PetriNetSim" version="1.0.0">
        <timeDelay>99</timeDelay>
        <delayMeanValue>7</delayMeanValue>
        <distribution>det</distribution>
        <priority>1</priority>
      </toolspecific>
    </transition>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert data["transitions"][0]["mean_delay"] == 7

    def test_falls_back_to_time_delay_when_delay_mean_value_is_absent(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Delay fallback</text></name>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="PetriNetSim" version="1.0.0">
        <timeDelay>6</timeDelay>
        <distribution>det</distribution>
        <priority>1</priority>
      </toolspecific>
    </transition>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert data["transitions"][0]["mean_delay"] == 6

    def test_never_filters_on_the_version_attribute(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Old version</text></name>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="PetriNetSim" version="99.9.9-future">
        <priority>7</priority>
      </toolspecific>
    </transition>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert data["transitions"][0]["priority"] == 7


# ---------------------------------------------------------------------------
# fast-xml-parser trimming parity: `trimValues: true` is the frontend
# parser's own default, never overridden, so every tag value and attribute
# it hands the frontend reader has already been trimmed. `_text_of`/`_attr`
# mirror that so a whitespace-padded document parses identically here.
# ---------------------------------------------------------------------------


class TestFrontendTrimmingParity:
    def test_padded_id_attribute_parses_as_the_trimmed_id_not_a_sanitized_one(self):
        # Before mirroring trimValues, "  p1  " (spaces are not legal
        # NCName characters) got sanitized into a different id and an
        # invalid-id warning the frontend -- which sees the already-
        # trimmed "p1", a perfectly valid id -- never produces.
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Padded id</text></name>
    <place id="  p1  "><name><text>P1</text></name></place>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert data["places"][0]["id"] == "p1"
        assert warnings == []

    def test_whitespace_only_initial_marking_is_absent_not_malformed(self):
        # fast-xml-parser trims a leaf's text before the frontend's own
        # textOf ever sees it; a marking of only whitespace arrives there
        # as the empty string, which parsePlace treats as "no marking
        # stated" (tokens=0, no warning), the same as omitting
        # <initialMarking> entirely. Before mirroring that trim, this
        # reader saw the raw, non-empty "   " and reported a spurious
        # bad-number warning for a value that names nothing.
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Padded marking</text></name>
    <place id="p1"><name><text>P1</text></name><initialMarking><text>   </text></initialMarking></place>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert data["places"][0]["tokens"] == 0
        assert warnings == []


# ---------------------------------------------------------------------------
# Numeric coercion parity with JS Number()/Number.parseInt(text, 10):
# Python's float()/int() accept underscore digit separators and non-ASCII
# decimal digits that JS's numeric grammar does not, and JS's Number()
# accepts a "0x..." hex literal that float() cannot parse at all. Each
# case is pinned through a field this reader already routes through
# _js_number (transition priority) or _parse_int (place initialMarking).
# ---------------------------------------------------------------------------


class TestNumericCoercionParity:
    @staticmethod
    def _priority_doc(priority_text: str) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Priorities</text></name>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="PetriObjModel" version="1.0">
        <priority>{priority_text}</priority>
      </toolspecific>
    </transition>
  </net>
</pnml>"""

    @staticmethod
    def _marking_doc(marking_text: str) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Marking digits</text></name>
    <place id="p1"><name><text>P1</text></name><initialMarking><text>{marking_text}</text></initialMarking></place>
  </net>
</pnml>"""

    def test_underscore_digit_separator_is_malformed_not_a_number(self):
        # Python's float("1_000") is 1000.0 (PEP 515); JS's Number("1_000")
        # is NaN -- there is no digit-separator syntax in its grammar.
        data, warnings = parse_pnml(self._priority_doc("1_000"))
        assert data["transitions"][0]["priority"] == 1
        assert [w["code"] for w in warnings] == ["bad-number"]

    def test_non_ascii_decimal_digit_is_malformed_not_a_number_js_number(self):
        # Devanagari "55": Python's float() converts any Unicode
        # "Nd"-category digit; JS's Number() recognizes ASCII 0-9 only.
        data, warnings = parse_pnml(self._priority_doc("५५"))
        assert data["transitions"][0]["priority"] == 1
        assert [w["code"] for w in warnings] == ["bad-number"]

    def test_non_ascii_decimal_digit_is_malformed_not_a_number_parse_int(self):
        # Same rule, the _parse_int (Number.parseInt) side: Arabic-indic
        # "123" as a place's initial marking.
        data, warnings = parse_pnml(self._marking_doc("١٢٣"))
        assert data["places"][0]["tokens"] == 0
        assert [w["code"] for w in warnings] == ["bad-number"]

    def test_hex_form_is_accepted_the_way_js_number_accepts_it(self):
        # JS's Number("0x1A") is 26 (a NonDecimalIntegerLiteral); Python's
        # float("0x1A") raises ValueError outright. No warning either way
        # for a value the frontend would read as a legal number.
        data, warnings = parse_pnml(self._priority_doc("0x1A"))
        assert data["transitions"][0]["priority"] == 26
        assert warnings == []


# ---------------------------------------------------------------------------
# The v2.2 <petriObject> marker: nesting, free-elements bucket, ordering.
# ---------------------------------------------------------------------------


class TestPetriObjectAttributes:
    def test_orders_pages_by_petriobject_index_not_document_order(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Shuffled</text></name>
    <page id="second">
      <toolspecific tool="PetriObjModel" version="2.0">
        <petriObject index="1" name="Second" priority="0" x="300" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="q0"><name><text>Q0</text></name></place>
      <transition id="u0"><name><text>U0</text></name></transition>
    </page>
    <page id="first">
      <toolspecific tool="PetriObjModel" version="2.0">
        <petriObject index="0" name="First" priority="0" x="0" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
      <transition id="t0"><name><text>T0</text></name></transition>
    </page>
    <toolspecific tool="PetriObjModel" version="2.0">
      <petriObjectLinks>
        <link type="transitionToPlace" sourceObject="0" sourceElement="0" targetObject="1" targetElement="0" quantity="1"/>
      </petriObjectLinks>
    </toolspecific>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert [o["name"] for o in data["objects"]] == ["First", "Second"]
        # The positional declaration counts in that same index, so object
        # 0's transition 0 is T0 -- reading the pages as written would
        # make it U0.
        assert data["links"][0]["sourceId"] == "t0"
        assert data["links"][0]["targetId"] == "q0"

    def test_throws_for_a_nested_document_with_unusable_indices(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Broken nest</text></name>
    <page id="outer">
      <toolspecific tool="PetriObjModel" version="2.2">
        <petriObject name="Outer" priority="0" x="0" y="0" width="100" height="100"/>
      </toolspecific>
      <page id="inner">
        <toolspecific tool="PetriObjModel" version="2.2">
          <petriObject index="0" name="Inner" priority="0" x="0" y="0" width="80" height="80"/>
        </toolspecific>
      </page>
    </page>
  </net>
</pnml>"""
        with pytest.raises(ValueError, match="nests its pages"):
            parse_pnml(xml)

    def test_leaves_a_frame_top_level_when_a_page_encloses_nothing(self):
        # A page that sits directly under the net has no enclosing object,
        # so its frame is top-level. The parentObject values here say
        # otherwise and are not read: the hierarchy is the page structure
        # or it is nothing.
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Broken nest</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="Self" priority="0" x="10" y="10" width="80" height="80" parentObject="0"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="Stray" priority="0" x="10" y="10" width="80" height="80" parentObject="7"/>
      </toolspecific>
      <place id="p1"><name><text>P1</text></name></place>
    </page>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert [o.get("objectId") for o in data["objects"]] == [None, None]

    def test_reads_the_nest_from_the_page_structure(self):
        xml = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Nested</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.2.2">
        <petriObject index="0" name="Outer" priority="0" x="0" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p0"><name><text>p0</text></name></place>
      <page id="object1">
        <toolspecific tool="PetriObjModel" version="2.2.2">
          <petriObject index="1" name="Middle" priority="0" x="0" y="0" width="200" height="160"/>
        </toolspecific>
        <place id="p1"><name><text>p1</text></name></place>
        <page id="object2">
          <toolspecific tool="PetriObjModel" version="2.2.2">
            <petriObject index="2" name="Inner" priority="0" x="0" y="0" width="200" height="160"/>
          </toolspecific>
          <place id="p2"><name><text>p2</text></name></place>
        </page>
      </page>
    </page>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert len(data["objects"]) == 3
        by_name = {o["name"]: o for o in data["objects"]}
        assert by_name["Outer"].get("objectId") is None
        assert by_name["Middle"]["objectId"] == by_name["Outer"]["id"]
        assert by_name["Inner"]["objectId"] == by_name["Middle"]["id"]
        assert sorted(p["id"] for p in data["places"]) == ["p0", "p1", "p2"]

    def test_is_not_swayed_by_the_attribute_where_a_document_nests_as_well(self):
        # Mirrors pnml-import.test.ts's "is not swayed by the attribute
        # where a document nests as well" (line 999): the document nests
        # its pages for real (Inner inside Middle inside Outer, exactly
        # like test_reads_the_nest_from_the_page_structure above), and the
        # Inner page's own <petriObject> ALSO states a parentObject="0"
        # (Outer) that contradicts where it actually sits. The page
        # structure alone still wins; the attribute changes nothing.
        xml = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Nested</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.2.2">
        <petriObject index="0" name="Outer" priority="0" x="0" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p0"><name><text>p0</text></name></place>
      <page id="object1">
        <toolspecific tool="PetriObjModel" version="2.2.2">
          <petriObject index="1" name="Middle" priority="0" x="0" y="0" width="200" height="160"/>
        </toolspecific>
        <place id="p1"><name><text>p1</text></name></place>
        <page id="object2">
          <toolspecific tool="PetriObjModel" version="2.2.2">
            <petriObject index="2" name="Inner" priority="0" x="0" y="0" width="200" height="160" parentObject="0"/>
          </toolspecific>
          <place id="p2"><name><text>p2</text></name></place>
        </page>
      </page>
    </page>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert len(data["objects"]) == 3
        by_name = {o["name"]: o for o in data["objects"]}
        assert by_name["Outer"].get("objectId") is None
        assert by_name["Middle"]["objectId"] == by_name["Outer"]["id"]
        assert by_name["Inner"]["objectId"] == by_name["Middle"]["id"]
        assert sorted(p["id"] for p in data["places"]) == ["p0", "p1", "p2"]

    def test_gives_a_document_no_hierarchy_just_because_it_states_parentobject(self):
        # Neither written nor read any more: a document states its
        # hierarchy the way the standard states one, or it states none.
        # Flat pages are three top-level objects, which is what this
        # document literally says once the attribute means nothing.
        xml = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Flat</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.2.2">
        <petriObject index="0" name="Outer" priority="0" x="0" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p0"><name><text>p0</text></name></place>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.2.2">
        <petriObject index="1" name="Middle" priority="0" x="0" y="0" width="200" height="160" parentObject="0"/>
      </toolspecific>
      <place id="p1"><name><text>p1</text></name></place>
    </page>
    <page id="object2">
      <toolspecific tool="PetriObjModel" version="2.2.2">
        <petriObject index="2" name="Inner" priority="0" x="0" y="0" width="200" height="160" parentObject="1"/>
      </toolspecific>
      <place id="p2"><name><text>p2</text></name></place>
    </page>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert len(data["objects"]) == 3
        assert all(o.get("objectId") is None for o in data["objects"])
        assert sorted(p["id"] for p in data["places"]) == ["p0", "p1", "p2"]

    def test_reads_collapsed_true_and_leaves_it_off_when_absent(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Collapsed</text></name>
    <page id="objectA">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="150" collapsed="true"/>
      </toolspecific>
      <place id="pA"><name><text>PA</text></name></place>
    </page>
    <page id="objectB">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="B" priority="0" x="300" y="0" width="200" height="150"/>
      </toolspecific>
      <place id="pB"><name><text>PB</text></name></place>
    </page>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        by_name = {o["name"]: o for o in data["objects"]}
        assert by_name["A"].get("collapsed") is True
        assert "collapsed" not in by_name["B"]

    def test_reads_autofit_false_and_leaves_it_off_when_absent(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>AutoFit</text></name>
    <page id="objectA">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="150" autoFit="false"/>
      </toolspecific>
      <place id="pA"><name><text>PA</text></name></place>
    </page>
    <page id="objectB">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="B" priority="0" x="300" y="0" width="200" height="150"/>
      </toolspecific>
      <place id="pB"><name><text>PB</text></name></place>
    </page>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        by_name = {o["name"]: o for o in data["objects"]}
        assert by_name["A"].get("autoFit") is False
        assert "autoFit" not in by_name["B"]

    def test_keeps_free_elements_free_instead_of_growing_a_frame_for_them(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Free bucket</text></name>
    <page id="objectA">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="10" y="10" width="200" height="150"/>
      </toolspecific>
      <place id="pA"><name><text>PA</text></name></place>
    </page>
    <page id="free">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="Free elements" priority="0" x="0" y="0"/>
      </toolspecific>
      <place id="pFree"><name><text>PFree</text></name></place>
      <transition id="tFree"><name><text>TFree</text></name></transition>
      <arc id="aFree" source="pFree" target="tFree"><inscription><text>1</text></inscription></arc>
    </page>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        assert [o["name"] for o in data["objects"]] == ["A"]
        free_place = _by_id(data["places"])["pFree"]
        assert "objectId" not in free_place
        free_trans = _by_id(data["transitions"])["tFree"]
        assert "objectId" not in free_trans
        assert [a["id"] for a in data["arcs"]] == ["aFree"]


# ---------------------------------------------------------------------------
# Where the links come from: structure (reference nodes) first, the
# net-level declaration filling in only what the structure cannot state.
# ---------------------------------------------------------------------------


class TestStructureFirstLinkParsing:
    @staticmethod
    def _conformant_doc(declared: str = "") -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Structured</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="150"/>
      </toolspecific>
      <place id="pA0"><name><text>PA0</text></name><initialMarking><text>3</text></initialMarking></place>
      <place id="pA1"><name><text>PA1</text></name></place>
      <transition id="tA0"><name><text>TA0</text></name></transition>
      <referencePlace id="refPB0" ref="pB0">
        <name><text>PB0</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>representative</referenceRole>
        </toolspecific>
      </referencePlace>
      <referenceTransition id="refTB0" ref="tB0">
        <name><text>TB0</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>representative</referenceRole>
        </toolspecific>
      </referenceTransition>
      <arc id="aA0" source="pA0" target="tA0"><inscription><text>1</text></inscription></arc>
      <arc id="lA0" source="tA0" target="refPB0"><inscription><text>3</text></inscription></arc>
      <arc id="lA1" source="pA0" target="refTB0">
        <inscription><text>2</text></inscription>
        <toolspecific tool="PetriObjModel" version="2.1">
          <informational>true</informational>
        </toolspecific>
      </arc>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="B" priority="0" x="300" y="0" width="200" height="150"/>
      </toolspecific>
      <place id="pB0"><name><text>PB0</text></name></place>
      <referencePlace id="pB1" ref="pA1">
        <name><text>PB1</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>fusion</referenceRole>
          <fusedInitialMarking>2</fusedInitialMarking>
        </toolspecific>
      </referencePlace>
      <transition id="tB0"><name><text>TB0</text></name></transition>
      <arc id="aB0" source="pB0" target="tB0"><inscription><text>1</text></inscription></arc>
    </page>
{declared}
  </net>
</pnml>"""

    _STRUCTURAL_MEANING = [
        {"type": "transitionToPlace", "sourceId": "tA0", "targetId": "pB0", "quantity": 3, "informational": False},
        {"type": "placeToTransition", "sourceId": "pA0", "targetId": "tB0", "quantity": 2, "informational": True},
        {"type": "placeFusion", "sourceId": "pB1", "targetId": "pA1", "quantity": 1, "informational": False},
    ]

    @staticmethod
    def _meaning(data: dict) -> list[dict]:
        return [
            {
                "type": link["type"], "sourceId": link["sourceId"], "targetId": link["targetId"],
                "quantity": link["quantity"], "informational": link.get("informational", False),
            }
            for link in data.get("links", [])
        ]

    def test_reads_every_link_from_reference_nodes_alone(self):
        data, _ = parse_pnml(self._conformant_doc())
        assert self._meaning(data) == self._STRUCTURAL_MEANING
        # The arcs that realise a link are the link, not arcs of anyone's net.
        assert [a["id"] for a in data["arcs"]] == ["aA0", "aB0"]
        assert _by_id(data["places"])["pB1"]["tokens"] == 2

    def test_structure_wins_over_a_declaration_that_disagrees_on_quantity(self):
        declared = """    <toolspecific tool="PetriObjModel" version="2.1">
      <petriObjectLinks>
        <link type="transitionToPlace" sourceObject="0" sourceElement="0" sourceElementId="tA0"
              targetObject="1" targetElement="0" targetElementId="pB0" quantity="99"/>
      </petriObjectLinks>
    </toolspecific>"""
        data, _ = parse_pnml(self._conformant_doc(declared))
        assert self._meaning(data) == self._STRUCTURAL_MEANING

    def test_keeps_a_declared_link_the_structure_does_not_state(self):
        declared = """    <toolspecific tool="PetriObjModel" version="2.1">
      <petriObjectLinks>
        <link type="placeToTransition" sourceObject="1" sourceElement="0" sourceElementId="pB0"
              targetObject="0" targetElement="0" targetElementId="tA0" quantity="5" informational="false"/>
      </petriObjectLinks>
    </toolspecific>"""
        data, _ = parse_pnml(self._conformant_doc(declared))
        assert self._meaning(data) == self._STRUCTURAL_MEANING + [
            {"type": "placeToTransition", "sourceId": "pB0", "targetId": "tA0", "quantity": 5, "informational": False},
        ]

    def test_drops_a_declared_fusion_the_structure_does_not_state(self):
        declared = """    <toolspecific tool="PetriObjModel" version="2.1">
      <petriObjectLinks>
        <link type="placeFusion" sourceObject="0" sourceElement="0" sourceElementId="pA0"
              targetObject="1" targetElement="0" targetElementId="pB0"/>
      </petriObjectLinks>
    </toolspecific>"""
        data, _ = parse_pnml(self._conformant_doc(declared))
        assert self._meaning(data) == self._STRUCTURAL_MEANING

    def test_infers_a_role_for_reference_nodes_that_carry_none(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Foreign structure</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="150"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
      <transition id="t0"><name><text>T0</text></name></transition>
      <referenceTransition id="rt" ref="u0"><name><text>U0</text></name></referenceTransition>
      <arc id="a0" source="p0" target="t0"><inscription><text>1</text></inscription></arc>
      <arc id="l0" source="p0" target="rt"><inscription><text>4</text></inscription></arc>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="B" priority="0" x="300" y="0" width="200" height="150"/>
      </toolspecific>
      <place id="q0"><name><text>Q0</text></name></place>
      <referencePlace id="q1" ref="p0"><name><text>Q1</text></name></referencePlace>
      <transition id="u0"><name><text>U0</text></name></transition>
    </page>
  </net>
</pnml>"""
        data, _ = parse_pnml(xml)
        # An arc touches the reference transition, so it is a stand-in; no
        # arc touches the reference place, so it is only there to be shared.
        assert self._meaning(data) == [
            {"type": "placeToTransition", "sourceId": "p0", "targetId": "u0", "quantity": 4, "informational": False},
            {"type": "placeFusion", "sourceId": "q1", "targetId": "p0", "quantity": 1, "informational": False},
        ]
        assert [p["id"] for p in data["places"]] == ["p0", "q0", "q1"]
        assert [a["id"] for a in data["arcs"]] == ["a0"]

    @staticmethod
    def _legacy_doc() -> str:
        return """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Legacy</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.0">
        <petriObject index="0" name="First" priority="0" x="0" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
      <place id="p1"><name><text>P1</text></name></place>
      <transition id="t0"><name><text>T0</text></name></transition>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.0">
        <petriObject index="1" name="Second" priority="0" x="300" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="q0"><name><text>Q0</text></name></place>
      <transition id="u0"><name><text>U0</text></name></transition>
    </page>
    <toolspecific tool="PetriObjModel" version="2.0">
      <petriObjectLinks>
        <link type="placeFusion" sourceObject="0" sourceElement="1" targetObject="1" targetElement="0"/>
        <link type="transitionToPlace" sourceObject="0" sourceElement="0" targetObject="1" targetElement="0" quantity="4"/>
        <link type="placeToTransition" sourceObject="1" sourceElement="0" targetObject="0" targetElement="0" quantity="lots" informational="true"/>
      </petriObjectLinks>
    </toolspecific>
  </net>
</pnml>"""

    def test_reads_a_legacy_v20_document_from_its_positional_declaration(self):
        """Legacy parentObject-era documents (no reference nodes at all)
        get their links entirely from the positional declaration -- nothing
        is dropped, fusions included, since there is no structure to be
        the authority instead."""
        data, _ = parse_pnml(self._legacy_doc())
        assert self._meaning(data)[:2] == [
            {"type": "placeFusion", "sourceId": "p1", "targetId": "q0", "quantity": 1, "informational": False},
            {"type": "transitionToPlace", "sourceId": "t0", "targetId": "q0", "quantity": 4, "informational": False},
        ]

    def test_falls_back_to_quantity_1_for_a_declaration_that_does_not_parse(self):
        data, _ = parse_pnml(self._legacy_doc())
        assert self._meaning(data)[2] == {
            "type": "placeToTransition", "sourceId": "q0", "targetId": "t0", "quantity": 1, "informational": True,
        }


class TestDeclaredLinksWrongEndpointKind:
    @staticmethod
    def _doc(link: str) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Legacy</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p1"><name><text>P1</text></name></place>
      <transition id="t1"><name><text>T1</text></name></transition>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="B" priority="0" x="400" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p2"><name><text>P2</text></name></place>
      <transition id="t2"><name><text>T2</text></name></transition>
    </page>
    <toolspecific tool="PetriObjModel" version="2.1">
      <petriObjectLinks>
        {link}
      </petriObjectLinks>
    </toolspecific>
  </net>
</pnml>"""

    def test_keeps_a_declaration_whose_endpoints_match_its_type(self):
        data, _ = parse_pnml(self._doc(
            '<link type="transitionToPlace" sourceObject="0" sourceElement="0" sourceElementId="t1" '
            'targetObject="1" targetElement="0" targetElementId="p2" quantity="1"/>'
        ))
        assert len(data["links"]) == 1
        assert data["links"][0]["type"] == "transitionToPlace"
        assert data["links"][0]["sourceId"] == "t1"
        assert data["links"][0]["targetId"] == "p2"

    def test_drops_one_naming_a_transition_where_the_type_requires_a_place(self):
        data, _ = parse_pnml(self._doc(
            '<link type="transitionToPlace" sourceObject="0" sourceElement="0" sourceElementId="t1" '
            'targetObject="1" targetElement="0" targetElementId="t2" quantity="1"/>'
        ))
        assert data.get("links", []) == []
        assert [p["id"] for p in data["places"]] == ["p1", "p2"]
        assert len(data["objects"]) == 2

    def test_drops_a_fusion_that_names_a_transition(self):
        data, _ = parse_pnml(self._doc(
            '<link type="placeFusion" sourceObject="0" sourceElement="0" sourceElementId="p1" '
            'targetObject="1" targetElement="0" targetElementId="t2"/>'
        ))
        assert data.get("links", []) == []


class TestPlaceFusionRulesOnImport:
    """desktop #62/port-spec section 2: an imported document is held to the
    same five placeFusion rules `ComposedModel.place_fusion_rejection`
    enforces when a link is created in the editor (test_composed_model.py::
    TestPlaceFusionRules). A link that breaks one is DROPPED, not a parse
    failure -- the document still opens -- and the drop is reported
    alongside this module's other warnings, in document order, so of a
    contradictory set the FIRST one stated is the one that stands.
    """

    @staticmethod
    def _page(index: int, name: str, place_id: str) -> str:
        return f"""    <page id="object{index}">
      <toolspecific tool="PetriObjModel" version="2.0">
        <petriObject index="{index}" name="{name}" priority="0" x="{index * 200}" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="{place_id}"><name><text>{place_id}</text></name></place>
      <transition id="t{index}"><name><text>T{index}</text></name></transition>
    </page>"""

    @staticmethod
    def _fusion_link(source: str, target: str) -> str:
        # id-valued attributes alone are enough: _declared_links prefers
        # them over sourceObject/sourceElement when both are given (see
        # its own comment), so the position attributes are not needed here.
        return f'<link type="placeFusion" sourceElementId="{source}" targetElementId="{target}"/>'

    @classmethod
    def _legacy_doc(cls, pages: list[str], links: list[str]) -> str:
        """A pre-referencePlace (v2.0) document: `<petriObjectLinks>` is the
        ONLY source of links, position/id-addressed directly, with none of
        `_structural_links`'s resolve()-through-a-reference-chain collapsing
        -- see `_filter_place_fusion_links`'s own docstring for why this is
        the shape that can actually state a cycle or a dual-master copy;
        a real (`<referencePlace>`-based) document's reference chain always
        resolves straight through to a real place, which never leaves that
        shape standing (test_a_well_formed_fan_of_three_copies below uses
        that real shape instead, for the case it CAN produce)."""
        body = "\n".join(pages)
        links_body = "\n".join(links)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Legacy</text></name>
{body}
    <toolspecific tool="PetriObjModel" version="2.0">
      <petriObjectLinks>
{links_body}
      </petriObjectLinks>
    </toolspecific>
  </net>
</pnml>"""

    @staticmethod
    def _fusions(data: dict) -> list[tuple[str, str]]:
        return [(l["sourceId"], l["targetId"]) for l in data.get("links", []) if l["type"] == "placeFusion"]

    def test_a_link_that_would_close_a_loop_is_dropped_and_the_rest_kept(self):
        """B copies A, C copies B, and A copies C would close the loop --
        the third link, stated last, is the one dropped."""
        doc = self._legacy_doc(
            pages=[self._page(0, "A", "pA"), self._page(1, "B", "pB"), self._page(2, "C", "pC")],
            links=[
                self._fusion_link("pB", "pA"),
                self._fusion_link("pC", "pB"),
                self._fusion_link("pA", "pC"),
            ],
        )
        data, warnings = parse_pnml(doc)
        assert self._fusions(data) == [("pB", "pA"), ("pC", "pB")]

        dropped = [w for w in warnings if w["code"] == "dropped-link"]
        assert len(dropped) == 1
        assert "loop" in dropped[0]["message"]
        assert "pA" in dropped[0]["message"]
        assert "pC" in dropped[0]["message"]

    def test_a_place_that_already_copies_one_master_cannot_copy_a_second(self):
        """Two reference places naming the same copy: pA is declared as the
        source of two separate fusions; the first (into pB) stands, the
        second (into pC) is dropped."""
        doc = self._legacy_doc(
            pages=[self._page(0, "A", "pA"), self._page(1, "B", "pB"), self._page(2, "C", "pC")],
            links=[
                self._fusion_link("pA", "pB"),
                self._fusion_link("pA", "pC"),
            ],
        )
        data, warnings = parse_pnml(doc)
        assert self._fusions(data) == [("pA", "pB")]

        dropped = [w for w in warnings if w["code"] == "dropped-link"]
        assert len(dropped) == 1
        assert "already copies another one" in dropped[0]["message"]

    def test_a_well_formed_fan_of_three_copies_imports_with_no_warnings(self):
        """The positive case: ANY number of copies may point at the SAME
        master. Read from real `<referencePlace>` structure, the shape an
        actual export writes -- unlike the two tests above, which need the
        legacy declared form to reach a rule the flattened reference chain
        otherwise makes unreachable (see `_structural_links`'s own
        docstring)."""
        def reference_place(copy_id: str, master_id: str) -> str:
            return f"""      <referencePlace id="{copy_id}" ref="{master_id}">
        <name><text>{copy_id}</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>fusion</referenceRole>
        </toolspecific>
      </referencePlace>"""

        master_page = """    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="Master" priority="0" x="0" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="pMaster"><name><text>Master</text></name><initialMarking><text>5</text></initialMarking></place>
      <transition id="tMaster"><name><text>TMaster</text></name></transition>
    </page>"""
        copy_pages = "\n".join(
            f"""    <page id="object{i}">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="{i}" name="Copy{i}" priority="0" x="{i * 200}" y="0" width="100" height="100"/>
      </toolspecific>
{reference_place(f"pCopy{i}", "pMaster")}
      <transition id="t{i}"><name><text>T{i}</text></name></transition>
    </page>"""
            for i in (1, 2, 3)
        )
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Fan</text></name>
{master_page}
{copy_pages}
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert self._fusions(data) == [("pCopy1", "pMaster"), ("pCopy2", "pMaster"), ("pCopy3", "pMaster")]
        assert warnings == []


# ---------------------------------------------------------------------------
# Soft validation: a file always opens if structurally possible, and every
# place this reader had to reinterpret, remap or drop something instead of
# failing gets exactly one warning. One test per code.
# ---------------------------------------------------------------------------


class TestImportWarnings:
    @staticmethod
    def _codes(warnings: list[dict]) -> list[str]:
        return [w["code"] for w in warnings]

    def test_no_warnings_for_a_well_formed_document(self):
        _, warnings = parse_pnml(SAMPLE_PNML)
        assert warnings == []

    def test_invalid_id_sanitizes_and_rewrites_every_reference(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Bad ids</text></name>
    <place id="my place"><name><text>My Place</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="a1" source="my place" target="t1"><inscription><text>1</text></inscription></arc>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert data["places"][0]["id"] == "my-place"
        assert data["arcs"][0]["source_id"] == "my-place"
        assert "invalid-id" in self._codes(warnings)
        msg = next(w["message"] for w in warnings if w["code"] == "invalid-id")
        assert "my-place" in msg

    def test_duplicate_id_keeps_first_and_suffixes_later_ones(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Duplicated</text></name>
    <place id="p1"><name><text>First</text></name></place>
    <place id="p1"><name><text>Second</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="a1" source="p1" target="t1"><inscription><text>1</text></inscription></arc>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert [p["id"] for p in data["places"]] == ["p1", "p1-2"]
        assert data["places"][0]["name"] == "First"
        assert data["places"][1]["name"] == "Second"
        assert data["arcs"][0]["source_id"] == "p1"
        assert "duplicate-id" in self._codes(warnings)

    def test_dangling_ref_reference_node_ref_points_nowhere(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Dangling</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
      <referencePlace id="refX" ref="doesNotExist">
        <name><text>RefX</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>representative</referenceRole>
        </toolspecific>
      </referencePlace>
    </page>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert data.get("links", []) == []
        assert "dangling-ref" in self._codes(warnings)
        message = next(w["message"] for w in warnings if w["code"] == "dangling-ref")
        assert "RefX" in message
        assert "doesNotExist" in message

    def test_dangling_ref_arc_touching_unresolved_representative_is_dropped(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Dangling arc</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
      <transition id="t0"><name><text>T0</text></name></transition>
      <referencePlace id="refX" ref="doesNotExist">
        <name><text>RefX</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>representative</referenceRole>
        </toolspecific>
      </referencePlace>
      <arc id="a0" source="p0" target="t0"><inscription><text>1</text></inscription></arc>
      <arc id="lost" source="t0" target="refX"><inscription><text>1</text></inscription></arc>
    </page>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert [a["id"] for a in data["arcs"]] == ["a0"]
        dangling = [w for w in warnings if w["code"] == "dangling-ref"]
        assert len(dangling) >= 2
        assert any("lost" in w["message"] for w in dangling)

    def test_cross_page_arc_own_arc_spanning_two_pages_kept_and_flagged(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Crossing</text></name>
    <page id="page0">
      <place id="p0"><name><text>P0</text></name></place>
    </page>
    <page id="page1">
      <transition id="t1"><name><text>T1</text></name></transition>
      <arc id="a1" source="p0" target="t1"><inscription><text>1</text></inscription></arc>
    </page>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert [a["id"] for a in data["arcs"]] == ["a1"]
        assert "cross-page-arc" in self._codes(warnings)

    def test_cross_page_arc_forward_reference_still_resolves(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Forward reference</text></name>
    <page id="page0">
      <place id="p0"><name><text>P0</text></name></place>
      <arc id="a1" source="p0" target="my node"><inscription><text>1</text></inscription></arc>
    </page>
    <page id="page1">
      <transition id="my node"><name><text>My Node</text></name></transition>
    </page>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert data["transitions"][0]["id"] == "my-node"
        assert data["arcs"][0]["target_id"] == "my-node"
        assert "cross-page-arc" in self._codes(warnings)

    def test_bad_number_malformed_place_marking_defaults_to_0(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Bad marking</text></name>
    <place id="p1"><name><text>P1</text></name><initialMarking><text>lots</text></initialMarking></place>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert data["places"][0]["tokens"] == 0
        assert "bad-number" in self._codes(warnings)

    def test_invalid_value_negative_marking_clamps_to_0(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Negative marking</text></name>
    <place id="p1"><name><text>P1</text></name><initialMarking><text>-5</text></initialMarking></place>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert data["places"][0]["tokens"] == 0
        codes = self._codes(warnings)
        assert "invalid-value" in codes
        assert "bad-number" not in codes

    def test_bad_number_malformed_priority_falls_back_but_explicit_0_is_not_malformed(self):
        def doc(priority_text: str) -> str:
            return f"""<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Priorities</text></name>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="PetriObjModel" version="1.0">
        <priority>{priority_text}</priority>
      </toolspecific>
    </transition>
  </net>
</pnml>"""

        malformed_data, malformed_warnings = parse_pnml(doc("not-a-number"))
        assert malformed_data["transitions"][0]["priority"] == 1
        assert "bad-number" in self._codes(malformed_warnings)

        # The `|| 1` fallback this replaces treated an explicit 0 as parse
        # failure; it is a legal priority and must not warn.
        zero_data, zero_warnings = parse_pnml(doc("0"))
        assert zero_data["transitions"][0]["priority"] == 0
        assert "bad-number" not in self._codes(zero_warnings)

    def test_bad_number_vs_invalid_value_inscription(self):
        def doc(inscription_text: str) -> str:
            return f"""<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Inscriptions</text></name>
    <place id="p1"><name><text>P1</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="a1" source="p1" target="t1"><inscription><text>{inscription_text}</text></inscription></arc>
  </net>
</pnml>"""

        malformed_data, malformed_warnings = parse_pnml(doc("many"))
        assert malformed_data["arcs"][0]["weight"] == 1
        assert "bad-number" in self._codes(malformed_warnings)

        zero_data, zero_warnings = parse_pnml(doc("0"))
        assert zero_data["arcs"][0]["weight"] == 1
        codes = self._codes(zero_warnings)
        assert "invalid-value" in codes
        assert "bad-number" not in codes

    def test_invalid_value_declared_link_quantity_zero_clamps_to_1(self):
        """A declared petriObjectLinks quantity of 0 (or negative) cannot
        become a ComposedLink -- its own field is ge=1 -- so it must be
        clamped and warned about here, before it ever reaches
        PetriNetSession.from_net_data, mirroring how a sub-1 arc
        inscription weight is treated."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Declared quantity</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p1"><name><text>P1</text></name></place>
      <transition id="t1"><name><text>T1</text></name></transition>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="B" priority="0" x="400" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p2"><name><text>P2</text></name></place>
      <transition id="t2"><name><text>T2</text></name></transition>
    </page>
    <toolspecific tool="PetriObjModel" version="2.1">
      <petriObjectLinks>
        <link type="transitionToPlace" sourceObject="0" sourceElement="0" sourceElementId="t1"
              targetObject="1" targetElement="0" targetElementId="p2" quantity="0"/>
      </petriObjectLinks>
    </toolspecific>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert len(data["links"]) == 1
        assert data["links"][0]["quantity"] == 1
        codes = self._codes(warnings)
        assert "invalid-value" in codes
        msg = next(w["message"] for w in warnings if w["code"] == "invalid-value")
        assert "t1" in msg and "p2" in msg

        # Must load into a session without raising -- the whole point of
        # clamping before ComposedLink (ge=1) ever sees it.
        session = PetriNetSession.from_net_data(data)
        assert session is not None

    def test_bad_number_malformed_fused_marking_keeps_previously_validated_tokens(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Composed Net</text></name>
    <page id="object0">
      <place id="p1"><name><text>P1</text></name></place>
    </page>
    <page id="object1">
      <referencePlace id="p2" ref="p1">
        <name><text>P2</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>fusion</referenceRole>
          <fusedInitialMarking>lots</fusedInitialMarking>
        </toolspecific>
      </referencePlace>
    </page>
  </net>
</pnml>"""
        data, warnings = parse_pnml(xml)
        assert _by_id(data["places"])["p2"]["tokens"] == 0
        assert "bad-number" in self._codes(warnings)
        msg = next(w["message"] for w in warnings if w["code"] == "bad-number" and "fused" in w["message"])
        assert "p2" in msg
