"""Tests for ComposedPNMLExporter — multi-page PNML export for composed models."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.domain.composed import ComposedModel, LinkType
from src.domain.models import PetriNet, Place
from src.services.petri.exporter import ComposedPNMLExporter
from src.services.petri.exporter.toolspecific import PETRI_NET_SIM_VERSION, TOOL_PETRI_NET_SIM

NS = {"pnml": "http://www.pnml.org/version-2009/grammar/pnml"}


def _generator_net(name: str) -> PetriNet:
    net = PetriNet(name=name)
    p1 = net.add_place("P1", tokens=1, x=100, y=100)
    t1 = net.add_transition("T1", mean_delay=2.0, distribution="exp", x=200, y=100)
    net.add_arc(p1.id, t1.id)
    net.add_arc(t1.id, p1.id)
    return net


class TestComposedPNMLExporter:
    @pytest.fixture
    def exporter(self) -> ComposedPNMLExporter:
        return ComposedPNMLExporter()

    @pytest.fixture
    def two_object_model(self) -> ComposedModel:
        model = ComposedModel(name="QueueingSystem")
        model.add_object(_generator_net("Generator"), name="Generator", priority=0, x=40, y=60)
        model.add_object(_generator_net("Server"), name="Server", priority=1, x=300, y=60)
        model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=0,
                        target_object=1, target_element=0)
        return model

    def test_export_returns_valid_xml(self, exporter, two_object_model):
        xml = exporter.export(two_object_model)
        root = ET.fromstring(xml)  # raises if malformed
        assert root.tag.endswith("pnml")

    def test_export_contains_model_name(self, exporter, two_object_model):
        xml = exporter.export(two_object_model)
        assert "<text>QueueingSystem</text>" in xml

    def test_export_has_one_page_per_object(self, exporter, two_object_model):
        xml = exporter.export(two_object_model)
        root = ET.fromstring(xml)
        net = root.find("pnml:net", NS)
        pages = net.findall("pnml:page", NS)
        assert len(pages) == 2
        assert pages[0].get("id") == "object0"
        assert pages[1].get("id") == "object1"

    def test_petri_object_toolspecific_has_correct_attributes(self, exporter, two_object_model):
        xml = exporter.export(two_object_model)
        root = ET.fromstring(xml)
        pages = root.find("pnml:net", NS).findall("pnml:page", NS)

        page0_toolspecific = pages[0].find("pnml:toolspecific", NS)
        assert page0_toolspecific.get("tool") == TOOL_PETRI_NET_SIM
        assert page0_toolspecific.get("version") == PETRI_NET_SIM_VERSION
        petri_object = page0_toolspecific.find("pnml:petriObject", NS)
        assert petri_object.get("index") == "0"
        assert petri_object.get("name") == "Generator"
        assert petri_object.get("priority") == "0"

        page1_toolspecific = pages[1].find("pnml:toolspecific", NS)
        petri_object_1 = page1_toolspecific.find("pnml:petriObject", NS)
        assert petri_object_1.get("index") == "1"
        assert petri_object_1.get("priority") == "1"

    def test_every_element_carries_only_its_own_tool_identity(self, exporter, two_object_model):
        """This application writes only its own identity, PetriNetSim: the
        cross-tool fallback that once justified mirroring PetriObjModel here
        lives on the READER side (petri-server's parser prefers its own block
        and falls back to ours, this app's importer does the reverse), so a
        document written by only one tool still opens fully in the other."""
        xml = exporter.export(two_object_model)
        root = ET.fromstring(xml)
        page0 = root.find("pnml:net", NS).find("pnml:page", NS)

        blocks = page0.findall("pnml:toolspecific", NS)
        assert [(b.get("tool"), b.get("version")) for b in blocks] == [
            (TOOL_PETRI_NET_SIM, PETRI_NET_SIM_VERSION),
        ]
        assert blocks[0].find("pnml:petriObject", NS) is not None

        # Element level too, not only the page's own object marker.
        element_blocks = page0.find("pnml:transition", NS).findall("pnml:toolspecific", NS)
        assert [b.get("tool") for b in element_blocks] == [TOOL_PETRI_NET_SIM]

    def test_petri_net_sim_version_matches_the_web_application(self):
        """Both writers state the same release. The web application is where
        that version is written, so this reads it there rather than trusting the
        constant to have been kept in step by hand."""
        package_json = Path(__file__).parent.parent.parent / "frontend" / "package.json"
        stated = json.loads(package_json.read_text(encoding="utf-8"))["version"]
        assert stated == PETRI_NET_SIM_VERSION

    def test_each_page_contains_its_own_elements(self, exporter, two_object_model):
        """object0's only place is fused into object1, it is projected as
        a <referencePlace> occupying that slot, not a <place> (§3/§4)."""
        xml = exporter.export(two_object_model)
        root = ET.fromstring(xml)
        page0, page1 = root.find("pnml:net", NS).findall("pnml:page", NS)

        assert len(page0.findall("pnml:place", NS)) == 0
        assert len(page0.findall("pnml:referencePlace", NS)) == 1
        assert len(page0.findall("pnml:transition", NS)) == 1
        assert len(page0.findall("pnml:arc", NS)) == 2

        assert len(page1.findall("pnml:place", NS)) == 1
        assert len(page1.findall("pnml:referencePlace", NS)) == 0
        assert len(page1.findall("pnml:transition", NS)) == 1
        assert len(page1.findall("pnml:arc", NS)) == 2

    def test_fusion_reference_place_replaces_source_place_verbatim(self, exporter, two_object_model):
        """The fused-away place's own id/name/coordinates carry over onto
        the reference node (§2: the id is free because the <place> that
        used to own it is never emitted) and it points at the target."""
        xml = exporter.export(two_object_model)
        root = ET.fromstring(xml)
        page0 = root.find("pnml:net", NS).find("pnml:page", NS)
        ref = page0.find("pnml:referencePlace", NS)
        target_place = root.find("pnml:net", NS).findall("pnml:page", NS)[1].find("pnml:place", NS)
        assert ref.get("ref") == target_place.get("id")
        # The user's own name, untouched: fold the provenance into it and saving
        # then reopening the file would rename their place.
        assert ref.find("pnml:name", NS).find("pnml:text", NS).text == "P1"
        # Where the marking really lives is said in a comment instead, which no
        # parser can mistake for data.
        assert f'shared with "{target_place.get("id")}"' in xml
        # never carries an initialMarking, that's the whole point of §8.3
        assert ref.find("pnml:initialMarking", NS) is None
        role = ref.find("pnml:toolspecific", NS).find("pnml:referenceRole", NS)
        assert role.text == "fusion"

    def test_net_level_toolspecific_has_place_fusion_link(self, exporter, two_object_model):
        xml = exporter.export(two_object_model)
        root = ET.fromstring(xml)
        net = root.find("pnml:net", NS)
        # net-level toolspecific is a direct child of <net>, not inside any <page>
        toolspecifics = net.findall("pnml:toolspecific", NS)
        assert [b.get("tool") for b in toolspecifics] == [TOOL_PETRI_NET_SIM]
        links_block = toolspecifics[0].find("pnml:petriObjectLinks", NS)
        assert links_block is not None
        links = links_block.findall("pnml:link", NS)
        assert len(links) == 1
        link = links[0]
        assert link.get("type") == "placeFusion"
        assert link.get("sourceObject") == "0"
        assert link.get("sourceElement") == "0"
        assert link.get("targetObject") == "1"
        assert link.get("targetElement") == "0"
        # placeFusion never emits quantity/informational
        assert link.get("quantity") is None
        assert link.get("informational") is None

    def test_no_links_omits_the_links_toolspecific_block(self, exporter):
        model = ComposedModel(name="Solo")
        model.add_object(_generator_net("Only"))
        xml = exporter.export(model)
        assert "petriObjectLinks" not in xml

    def test_transition_to_place_link_emits_quantity_not_informational(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"))
        model.add_object(_generator_net("B"))
        model.add_link(LinkType.TRANSITION_TO_PLACE, 0, 0, 1, 0, quantity=3)
        xml = exporter.export(model)
        root = ET.fromstring(xml)
        link = root.find("pnml:net", NS).find("pnml:toolspecific", NS) \
            .find("pnml:petriObjectLinks", NS).find("pnml:link", NS)
        assert link.get("type") == "transitionToPlace"
        assert link.get("quantity") == "3"
        assert link.get("informational") is None
        # §6: id-valued attributes alongside the original index-valued ones.
        # `_generator_net`'s auto-ids ("p1"/"t1") collide across the two
        # objects, so §2 namespacing kicks in, "o{object}_{raw id}".
        assert link.get("sourceElementId") == "o0_t1"
        assert link.get("targetElementId") == "o1_p1"

    def test_place_to_transition_link_raises(self, exporter):
        """PetriObjModelPaint retired this link type. ComposedModel.validate()
        already refuses one for any request that goes through the API (see
        test_composed_model.py); this is the exporter's own backstop for a
        model that reached export some other way, so the projection this
        writer used to emit for it (a representative reference node plus an
        informational link arc) never has to be reasoned about again."""
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"))
        model.add_object(_generator_net("B"))
        model.add_link(LinkType.PLACE_TO_TRANSITION, 0, 0, 1, 0,
                        quantity=2, informational=True)
        with pytest.raises(ValueError, match="placeToTransition"):
            exporter.export(model)

    def test_transition_to_place_projects_representative_and_link_arc(self, exporter):
        """§4: the representative lives on the SOURCE page, and the arc
        realising the link runs from the source's own transition to it.

        Uses non-colliding explicit ids (unlike `_generator_net`, whose
        auto-ids collide across objects and would trigger §2 namespacing,
        that path has its own dedicated test) so the ids asserted below
        are exactly the ones the domain model was given.
        """
        model = ComposedModel(name="M")
        a = PetriNet(name="A")
        pa = a.add_place("P1", tokens=1, place_id="pA")
        ta = a.add_transition("T1", mean_delay=2.0, distribution="exp", transition_id="tA")
        a.add_arc(pa.id, ta.id, arc_id="arcA1")
        a.add_arc(ta.id, pa.id, arc_id="arcA2")
        b = PetriNet(name="B")
        pb = b.add_place("P1", tokens=1, place_id="pB")
        tb = b.add_transition("T1", mean_delay=2.0, distribution="exp", transition_id="tB")
        b.add_arc(pb.id, tb.id, arc_id="arcB1")
        b.add_arc(tb.id, pb.id, arc_id="arcB2")
        model.add_object(a)
        model.add_object(b)
        model.add_link(LinkType.TRANSITION_TO_PLACE, 0, 0, 1, 0, quantity=3)
        xml = exporter.export(model)
        root = ET.fromstring(xml)
        page0 = root.find("pnml:net", NS).findall("pnml:page", NS)[0]

        rep = page0.find("pnml:referencePlace", NS)
        assert rep is not None
        assert rep.get("ref") == "pB"
        role = rep.find("pnml:toolspecific", NS).find("pnml:referenceRole", NS)
        assert role.text == "representative"
        assert rep.find("pnml:initialMarking", NS) is None

        link_arcs = [el for el in page0.findall("pnml:arc", NS) if el.get("id", "").startswith("larc_")]
        assert len(link_arcs) == 1
        larc = link_arcs[0]
        assert larc.get("source") == "tA"
        assert larc.get("target") == rep.get("id")
        assert larc.find("pnml:inscription", NS).find("pnml:text", NS).text == "3"
        assert larc.find("pnml:toolspecific", NS) is None  # not informational

    def test_no_inhibitor_type_element_anywhere(self, exporter):
        """§8.7 / A2: <type value="inhibitorArc"/> is not a legal PNML
        label and must never be written; arcType stays toolspecific-only."""
        model = ComposedModel(name="M")
        net = PetriNet(name="A")
        p1 = net.add_place("Guard", tokens=0)
        p2 = net.add_place("In", tokens=1)
        t1 = net.add_transition("T")
        net.add_arc(p1.id, t1.id, arc_type="inhibitor")
        net.add_arc(p2.id, t1.id)
        model.add_object(net)
        xml = exporter.export(model)
        assert "inhibitorArc" not in xml
        assert "<arcType>inhibitor</arcType>" in xml


class TestPetriObjectFrameAttributes:
    """width/height/collapsed/autoFit on `<petriObject>`: the
    web editor's object-canvas frame state, following exactly the same
    presence rules as the frontend exporter (see model_object.py and
    composed_document._resolve_frame_attributes)."""

    @pytest.fixture
    def exporter(self) -> ComposedPNMLExporter:
        return ComposedPNMLExporter()

    @staticmethod
    def _petri_object_tag(xml: str, index: int) -> str:
        match = re.search(rf'<petriObject index="{index}"[^/]*/>', xml, re.DOTALL)
        assert match, f"no <petriObject index=\"{index}\" .../> in:\n{xml}"
        return re.sub(r"\s+", " ", match.group(0))

    def test_an_object_that_states_no_size_gets_the_smallest_drawable_one(self, exporter):
        """A real object always states a size. Emitting none wrote the marker
        that means "the free-elements bucket", and reopening the file read the
        object as that bucket: the frame, and every membership in it, was gone.
        The minimum is the smallest box the canvas draws, so such a frame
        reopens at the size it would have been given anyway."""
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), priority=2, x=10, y=20)
        xml = exporter.export(model)
        tag = self._petri_object_tag(xml, 0)
        assert tag == (
            '<petriObject index="0" name="A" priority="2" x="10" y="20" '
            'width="160" height="100"/>'
        )

    def test_the_free_elements_bucket_keeps_the_all_default_marker(self, exporter):
        """The one page that is not a Petri-object is recognised by carrying no
        geometry at all, so nothing optional may leak onto it."""
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), free=True)
        xml = exporter.export(model)
        tag = self._petri_object_tag(xml, 0)
        assert tag == '<petriObject index="0" name="A" priority="0" x="0" y="0"/>'

    def test_width_and_height_emitted_together_when_both_positive(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), width=200.0, height=150.0)
        xml = exporter.export(model)
        tag = self._petri_object_tag(xml, 0)
        assert 'width="200" height="150"' in tag

    def test_a_half_stated_size_is_completed_rather_than_dropped(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), width=200.0)
        xml = exporter.export(model)
        tag = self._petri_object_tag(xml, 0)
        assert 'width="200" height="100"' in tag

    def test_a_non_positive_size_is_raised_to_the_minimum(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), width=0.0, height=100.0)
        xml = exporter.export(model)
        tag = self._petri_object_tag(xml, 0)
        assert 'width="160" height="100"' in tag

    def test_collapsed_true_is_emitted(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), collapsed=True)
        xml = exporter.export(model)
        assert 'collapsed="true"' in self._petri_object_tag(xml, 0)

    def test_collapsed_false_is_never_emitted(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), collapsed=False)
        xml = exporter.export(model)
        assert "collapsed" not in self._petri_object_tag(xml, 0)

    def test_the_nest_is_the_page_structure_and_nothing_else(self, exporter):
        """`parent=0` is a legitimate nesting parent, not "unset", and index 0
        is the case a truthiness check used to get wrong. The nest is now stated
        by putting the child's page inside the parent's, which is how ISO/IEC
        15909-2 states a page hierarchy, so nothing repeats it as an attribute.
        """
        model = ComposedModel(name="M")
        model.add_object(_generator_net("Outer"))
        model.add_object(_generator_net("Inner"), parent=0)

        xml = exporter.export(model)

        assert "parentObject" not in xml
        net = ET.fromstring(xml).find("pnml:net", NS)
        pages = net.findall("pnml:page", NS)
        assert len(pages) == 1, "only the top level sits under <net>"
        nested = pages[0].findall("pnml:page", NS)
        assert len(nested) == 1
        assert nested[0].get("id") == "object1"

    def test_auto_fit_false_is_emitted(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), auto_fit=False)
        xml = exporter.export(model)
        assert 'autoFit="false"' in self._petri_object_tag(xml, 0)

    def test_auto_fit_true_or_none_is_never_emitted(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), auto_fit=True)
        model.add_object(_generator_net("B"), auto_fit=None)
        xml = exporter.export(model)
        assert "autoFit" not in self._petri_object_tag(xml, 0)
        assert "autoFit" not in self._petri_object_tag(xml, 1)

    def test_attribute_order_matches_spec(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(
            _generator_net("A"), priority=2, x=10, y=20,
            width=200.0, height=150.0, collapsed=True, parent=0, auto_fit=False,
        )
        model.add_object(_generator_net("B"))
        xml = exporter.export(model)
        tag = self._petri_object_tag(xml, 0)
        assert tag == (
            '<petriObject index="0" name="A" priority="2" x="10" y="20" '
            'width="200" height="150" collapsed="true" autoFit="false"/>'
        )

    def test_free_object_forces_zero_origin_and_drops_every_optional_attribute(self, exporter):
        """`free` overrides everything else the request also carried for
        position/frame state: an object not yet placed on the canvas gets
        the bare marker, x=0 y=0, no width/height/collapsed/autoFit
        regardless of what those fields were set to."""
        model = ComposedModel(name="M")
        model.add_object(
            _generator_net("A"), x=999, y=888,
            width=200.0, height=150.0, collapsed=True, parent=0, auto_fit=False,
            free=True,
        )
        xml = exporter.export(model)
        tag = self._petri_object_tag(xml, 0)
        assert tag == '<petriObject index="0" name="A" priority="0" x="0" y="0"/>'


class TestComposedPNMLExporterGoldenFixture:
    """Byte-for-byte (after canonicalisation) match against a worked example
    conformant with docs/petri-object-models.md in the PetriObjModelPaint
    repository, the anti-drift device shared verbatim across all three
    writer repos."""

    FIXTURE_PATH = Path(__file__).parent / "fixtures" / "composed_conformant_v21.pnml"

    @staticmethod
    def _canon(el: ET.Element):
        return (
            el.tag.split("}")[-1],
            tuple(sorted(el.attrib.items())),
            (el.text or "").strip(),
            tuple(TestComposedPNMLExporterGoldenFixture._canon(c) for c in el),
        )

    @pytest.fixture
    def pipeline_demo_model(self) -> ComposedModel:
        model = ComposedModel(name="PipelineDemo")

        generator = PetriNet(name="Generator")
        generator.add_place("Pool", tokens=5, x=60, y=80, place_id="p_pool")
        generator.add_place("Ready", tokens=0, x=200, y=80, place_id="p_ready")
        generator.add_place("Log", tokens=0, x=200, y=200, place_id="p_log")
        generator.add_transition(
            "Generate", mean_delay=1.0, distribution="det", x=130, y=80, transition_id="t_gen"
        )
        generator.add_arc("p_pool", "t_gen", arc_id="a_g1")
        generator.add_arc("t_gen", "p_ready", arc_id="a_g2")
        generator.add_arc("t_gen", "p_log", arc_id="a_g3")

        server = PetriNet(name="Server")
        server.add_place("In", tokens=0, x=60, y=80, place_id="p_in")
        server.add_place("Busy", tokens=0, x=200, y=80, place_id="p_busy")
        server.add_place("Done", tokens=0, x=340, y=80, place_id="p_done")
        server.add_transition(
            "Start", mean_delay=2.0, distribution="exp", x=130, y=80, transition_id="t_start"
        )
        server.add_transition(
            "End", mean_delay=3.0, distribution="det", x=270, y=80, transition_id="t_end"
        )
        server.add_arc("p_in", "t_start", arc_id="a_s1")
        server.add_arc("t_start", "p_busy", arc_id="a_s2")
        server.add_arc("p_busy", "t_end", arc_id="a_s3")
        server.add_arc("t_end", "p_done", arc_id="a_s4")

        model.add_object(generator, name="Generator", priority=1, x=40, y=60)
        model.add_object(server, name="Server", priority=0, x=360, y=60)

        # L0: fusion on object0's MIDDLE place slot (index 1), the off-by-one detector.
        model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=1,
                        target_object=1, target_element=0)
        model.add_link(LinkType.TRANSITION_TO_PLACE, source_object=1, source_element=0,
                        target_object=0, target_element=2, quantity=2)
        # No placeToTransition L2 here any more: PetriObjModelPaint retired
        # that link type and the exporter now refuses it (see
        # test_place_to_transition_link_raises), so the worked example this
        # golden fixture pins can no longer carry one.
        return model

    def test_export_matches_golden_fixture(self, exporter, pipeline_demo_model):
        xml = exporter.export(pipeline_demo_model)
        got = self._canon(ET.fromstring(xml))
        want = self._canon(ET.parse(self.FIXTURE_PATH).getroot())
        assert got == want

    @pytest.fixture
    def exporter(self) -> ComposedPNMLExporter:
        return ComposedPNMLExporter()


class TestComposedPNMLExporterInvariants:
    @pytest.fixture
    def exporter(self) -> ComposedPNMLExporter:
        return ComposedPNMLExporter()

    def test_reference_nodes_never_carry_initial_marking(self, exporter):
        """Even when the fused-away place HAS tokens (preserved only as
        <fusedInitialMarking>, never <initialMarking>, §8.3)."""
        model = ComposedModel(name="M")
        source = _generator_net("A")  # P1 has 1 token
        model.add_object(source)
        model.add_object(_generator_net("B"))
        model.add_link(LinkType.PLACE_FUSION, 0, 0, 1, 0)
        xml = exporter.export(model)
        root = ET.fromstring(xml)
        for page in root.find("pnml:net", NS).findall("pnml:page", NS):
            for tag in ("pnml:referencePlace", "pnml:referenceTransition"):
                for ref in page.findall(tag, NS):
                    assert ref.find("pnml:initialMarking", NS) is None
        assert "<fusedInitialMarking>1</fusedInitialMarking>" in xml

    def test_all_ids_are_unique_across_the_document(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"))
        model.add_object(_generator_net("B"))
        model.add_link(LinkType.PLACE_FUSION, 0, 0, 1, 0)
        model.add_link(LinkType.TRANSITION_TO_PLACE, 1, 0, 0, 0, quantity=1)
        xml = exporter.export(model)
        root = ET.fromstring(xml)
        ids = []
        for page in root.find("pnml:net", NS).findall("pnml:page", NS):
            for tag in ("place", "transition", "referencePlace", "referenceTransition", "arc"):
                ids.extend(el.get("id") for el in page.findall(f"pnml:{tag}", NS))
        assert len(ids) == len(set(ids))

    def test_every_arc_is_intra_page(self, exporter):
        """§8.2, an arc's source and target must resolve to nodes on the
        SAME page (the invariant RELAX NG cannot express)."""
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"))
        model.add_object(_generator_net("B"))
        model.add_link(LinkType.PLACE_FUSION, 0, 0, 1, 0)
        model.add_link(LinkType.TRANSITION_TO_PLACE, 1, 0, 0, 0, quantity=1)
        xml = exporter.export(model)
        root = ET.fromstring(xml)
        for page in root.find("pnml:net", NS).findall("pnml:page", NS):
            node_ids = set()
            for tag in ("place", "transition", "referencePlace", "referenceTransition"):
                node_ids.update(el.get("id") for el in page.findall(f"pnml:{tag}", NS))
            for arc in page.findall("pnml:arc", NS):
                assert arc.get("source") in node_ids
                assert arc.get("target") in node_ids

    def test_fusion_on_middle_slot_keeps_link_source_element_at_original_index(self, exporter):
        """§3: a representative/fusion reference never consumes an
        ordinal, sourceElement must keep meaning "the N-th place in
        document order" even when that N-th place became a reference.

        Explicit non-colliding ids on object A (`_generator_net("B")`'s
        auto-ids would otherwise collide and trigger §2 namespacing,
        which is exercised by its own dedicated test instead).
        """
        model = ComposedModel(name="M")
        a = PetriNet(name="A")
        p0 = a.add_place("P0", place_id="pA0")
        p1 = a.add_place("P1", place_id="pA1")
        p2 = a.add_place("P2", place_id="pA2")
        t = a.add_transition("T", transition_id="tA0")
        a.add_arc(p0.id, t.id, arc_id="arcA1")
        a.add_arc(t.id, p2.id, arc_id="arcA2")
        model.add_object(a)
        model.add_object(_generator_net("B"))
        link = model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=1,
                               target_object=1, target_element=0)
        xml = exporter.export(model)
        root = ET.fromstring(xml)
        page0 = root.find("pnml:net", NS).findall("pnml:page", NS)[0]
        # document order: P0 (<place>), P1 (<referencePlace>), P2 (<place>)
        children = [c for c in page0 if c.tag.endswith("}place") or c.tag.endswith("}referencePlace")]
        assert [c.tag.split("}")[-1] for c in children] == ["place", "referencePlace", "place"]
        assert children[1].get("id") == "pA1"

        link_el = root.find("pnml:net", NS).find("pnml:toolspecific", NS) \
            .find("pnml:petriObjectLinks", NS).find("pnml:link", NS)
        assert link_el.get("sourceElement") == "1"
        assert link.source_element == 1

    def test_last_fusion_wins_when_two_fusions_share_a_source_slot(self, exporter):
        """§4/§6: PetriObjModel.wire() overwrites `sourcePlaces[slot]` on
        each apply, so replaying two fusions on the same source slot keeps
        only the LAST one structurally, the earlier one stays declared in
        <petriObjectLinks> only, never doubling up the reference node.

        This model is no longer reachable through anything that enforces
        ComposedModel's own rules (desktop #61's rule 3: a place may be the
        SOURCE/copy of at most one fusion link; object0's only place is
        the source of both links below). `op_link_objects`/`session.add_link`
        refuse the second link outright, and `validate()` flags the model
        below as an assertion of that, in the same breath as building it.
        This test still builds the model by direct construction, bypassing
        both, to pin what the exporter itself does with input that reaches
        it some other way (a hand-authored net_data document, say) despite
        being invalid: union-find "last write wins" resilience, not a
        behaviour anything should still be able to trigger through the
        session or the agent tools.
        """
        model = ComposedModel(name="M")
        a = PetriNet(name="A")
        pa = a.add_place("P1", place_id="pA")
        ta = a.add_transition("T1", transition_id="tA")
        a.add_arc(pa.id, ta.id, arc_id="arcA1")
        a.add_arc(ta.id, pa.id, arc_id="arcA2")
        b = PetriNet(name="B")
        pb = b.add_place("P1", place_id="pB")
        tb = b.add_transition("T1", transition_id="tB")
        b.add_arc(pb.id, tb.id, arc_id="arcB1")
        b.add_arc(tb.id, pb.id, arc_id="arcB2")
        c = PetriNet(name="C")
        pc = c.add_place("P1", place_id="pC")
        tc = c.add_transition("T1", transition_id="tC")
        c.add_arc(pc.id, tc.id, arc_id="arcC1")
        c.add_arc(tc.id, pc.id, arc_id="arcC2")
        model.add_object(a)
        model.add_object(b)
        model.add_object(c)
        # Both fusions target object0's ONLY place slot (index 0); C is last.
        model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=0,
                        target_object=1, target_element=0)
        model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=0,
                        target_object=2, target_element=0)
        xml = exporter.export(model)
        root = ET.fromstring(xml)
        page0 = root.find("pnml:net", NS).findall("pnml:page", NS)[0]

        refs = page0.findall("pnml:referencePlace", NS)
        assert len(refs) == 1  # not two, only the last fusion is structural
        assert refs[0].get("ref") == "pC"

        links_block = root.find("pnml:net", NS).find("pnml:toolspecific", NS) \
            .find("pnml:petriObjectLinks", NS)
        assert len(links_block.findall("pnml:link", NS)) == 2  # both still declared

        errors = model.validate()
        assert any(
            "already copies another one" in e for e in errors
        ), "validate() should refuse this model under rule 3, even though export tolerates it"

    def test_a_fan_of_three_copies_exports_as_three_reference_places_at_one_master(self, exporter):
        """desktop #61: one master repeated by ANY number of copies is a
        legal fusion group as long as every copy is the source of exactly
        one link (rule 3) -- unlike the previous test, this one is a model
        `ComposedModel.validate()` accepts. Three copies, three
        <referencePlace> elements, all with ref="pMaster", and the master
        stays a real <place> carrying the marking."""
        model = ComposedModel(name="Fan")
        master = PetriNet(name="Master")
        pm = master.add_place("P1", tokens=5, place_id="pMaster")
        tm = master.add_transition("T1", transition_id="tMaster")
        master.add_arc(pm.id, tm.id, arc_id="arcM1")
        master.add_arc(tm.id, pm.id, arc_id="arcM2")
        model.add_object(master, name="Master")

        for i in range(1, 4):
            copy = PetriNet(name=f"Copy{i}")
            pc = copy.add_place("P1", tokens=0, place_id=f"pCopy{i}")
            tc = copy.add_transition("T1", transition_id=f"tCopy{i}")
            copy.add_arc(pc.id, tc.id, arc_id=f"arcC{i}1")
            copy.add_arc(tc.id, pc.id, arc_id=f"arcC{i}2")
            model.add_object(copy, name=f"Copy{i}")
            model.add_link(
                LinkType.PLACE_FUSION,
                source_object=i, source_element=0,
                target_object=0, target_element=0,
            )
        assert model.validate() == []

        xml = exporter.export(model)
        root = ET.fromstring(xml)
        pages = root.find("pnml:net", NS).findall("pnml:page", NS)

        master_page = pages[0]
        assert len(master_page.findall("pnml:place", NS)) == 1
        assert master_page.find("pnml:place", NS).get("id") == "pMaster"
        assert master_page.find("pnml:place", NS).find("pnml:initialMarking/pnml:text", NS).text == "5"
        assert len(master_page.findall("pnml:referencePlace", NS)) == 0

        for copy_page in pages[1:]:
            refs = copy_page.findall("pnml:referencePlace", NS)
            assert len(refs) == 1
            assert refs[0].get("ref") == "pMaster"
            assert len(copy_page.findall("pnml:place", NS)) == 0

    def test_two_objects_with_colliding_ids_get_namespaced(self, exporter):
        """Two objects built from the same net_data (e.g. the same session
        used twice) auto-generate identical ids ("p1", "t1", "arc1", ...), so
        renaming is what makes the document's ids document-scoped at all."""
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), name="A")
        model.add_object(_generator_net("A"), name="A-copy")
        model.add_link(LinkType.PLACE_FUSION, 0, 0, 1, 0)
        xml = exporter.export(model)
        root = ET.fromstring(xml)

        ids = []
        for page in root.find("pnml:net", NS).findall("pnml:page", NS):
            for tag in ("place", "transition", "referencePlace", "referenceTransition", "arc"):
                ids.extend(el.get("id") for el in page.findall(f"pnml:{tag}", NS))
        assert len(ids) == len(set(ids))
        assert all(i.startswith("o0_") or i.startswith("o1_") for i in ids)

    def test_ids_are_left_alone_when_nothing_collides(self, exporter):
        """The common case is byte-stable: a canvas already has unique ids, and
        they are the key a simulation's markings come back under, so nothing
        renames them."""
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"), name="A")
        model.add_object(_generator_net("B"), name="B")
        # Give the second object its own ids so nothing collides.
        for element in list(model.objects[1].net.places) + list(model.objects[1].net.transitions):
            element.id = f"b_{element.id}"
        for arc in model.objects[1].net.arcs:
            arc.id = f"b_{arc.id}"
            arc.source_id = f"b_{arc.source_id}"
            arc.target_id = f"b_{arc.target_id}"
        model.add_link(LinkType.PLACE_FUSION, 0, 0, 1, 0)
        root = ET.fromstring(exporter.export(model))

        emitted = set()
        for page in root.find("pnml:net", NS).findall("pnml:page", NS):
            for tag in ("place", "transition", "referencePlace", "arc"):
                emitted.update(el.get("id") for el in page.findall(f"pnml:{tag}", NS))

        for obj in model.objects:
            for element in list(obj.net.places) + list(obj.net.transitions):
                assert element.id in emitted, f"{element.id} was renamed or dropped"

    def test_source_object_equal_target_object_raises(self, exporter):
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"))
        model.add_link(LinkType.PLACE_FUSION, source_object=0, source_element=0,
                        target_object=0, target_element=0)
        with pytest.raises(ValueError, match="itself|source_object"):
            exporter.export(model)

    def test_empty_model_raises(self, exporter):
        model = ComposedModel(name="Empty")
        with pytest.raises(ValueError, match="no objects"):
            exporter.export(model)

    def test_link_quantity_below_one_raises(self, exporter):
        """ComposedLink.quantity already has ge=1 at construction; this
        exercises build_document_model's own defensive check for a model
        that reached the exporter via a path pydantic didn't validate
        (e.g. direct attribute mutation after construction)."""
        model = ComposedModel(name="M")
        model.add_object(_generator_net("A"))
        model.add_object(_generator_net("B"))
        link = model.add_link(LinkType.TRANSITION_TO_PLACE, 0, 0, 1, 0, quantity=1)
        link.quantity = 0
        with pytest.raises(ValueError, match="quantity"):
            exporter.export(model)

    def test_duplicate_id_within_one_object_raises(self, exporter):
        """A net built by direct construction from untrusted JSON (as
        simulate_composed.py does) bypasses PetriNet.add_place's own
        uniqueness guard, the exporter must still refuse it."""
        net = PetriNet.model_construct(
            name="Broken",
            places=[
                Place(id="p1", name="A", tokens=0),
                Place(id="p1", name="B", tokens=0),
            ],
            transitions=[],
            arcs=[],
        )
        model = ComposedModel(name="M")
        model.add_object(net)
        with pytest.raises(ValueError, match="duplicate"):
            exporter.export(model)
