"""Tests for PNML export functionality."""

from pathlib import Path

import pytest

from src.domain import DistributionType, PetriNet
from src.services.petri import PNMLExporter
from src.services.petri.exporter.toolspecific import PETRI_NET_SIM_VERSION, TOOL_PETRI_NET_SIM


class TestPNMLExporter:
    """Tests for PNMLExporter class."""

    @pytest.fixture
    def exporter(self) -> PNMLExporter:
        """Create exporter instance."""
        return PNMLExporter()

    @pytest.fixture
    def simple_net(self) -> PetriNet:
        """Create a simple test net with one place, one transition, one arc."""
        net = PetriNet(name="Simple Net")
        p1 = net.add_place(name="Input", tokens=1, x=100, y=100)
        t1 = net.add_transition(name="Process", x=200, y=100)
        net.add_arc(source_id=p1.id, target_id=t1.id)
        return net

    @pytest.fixture
    def timed_net(self) -> PetriNet:
        """Create a net with timed transitions."""
        net = PetriNet(name="Timed Net")
        p1 = net.add_place(name="Queue", tokens=5, x=100, y=200)
        p2 = net.add_place(name="Output", tokens=0, x=500, y=200)
        t1 = net.add_transition(
            name="Process",
            x=300,
            y=200,
            distribution=DistributionType.NORM,
            mean_delay=50.0,
            standard_deviation=5.0,
        )
        net.add_arc(source_id=p1.id, target_id=t1.id)
        net.add_arc(source_id=t1.id, target_id=p2.id)
        return net

    def test_export_returns_string(self, exporter: PNMLExporter, simple_net: PetriNet):
        """Test that export returns a string."""
        result = exporter.export(simple_net)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_export_valid_xml_header(self, exporter: PNMLExporter, simple_net: PetriNet):
        """Test that exported XML has correct header."""
        result = exporter.export(simple_net)

        assert result.startswith('<?xml version="1.0" encoding="UTF-8"')
        assert 'xmlns="http://www.pnml.org/version-2009/grammar/pnml"' in result

    def test_export_contains_net_name(self, exporter: PNMLExporter, simple_net: PetriNet):
        """Test that net name is included in export."""
        result = exporter.export(simple_net)

        assert "<text>Simple Net</text>" in result

    def test_export_contains_places(self, exporter: PNMLExporter, simple_net: PetriNet):
        """Test that places are exported correctly."""
        result = exporter.export(simple_net)

        assert '<place id="p1">' in result
        assert "<text>Input</text>" in result

    def test_export_contains_initial_marking(self, exporter: PNMLExporter, simple_net: PetriNet):
        """Test that initial marking is exported for places with tokens."""
        result = exporter.export(simple_net)

        assert "<initialMarking>" in result
        assert "<text>1</text>" in result.split("<initialMarking>")[1].split("</initialMarking>")[0]

    def test_export_no_initial_marking_for_zero_tokens(self, exporter: PNMLExporter):
        """Test that initialMarking is not exported for places with zero tokens."""
        net = PetriNet(name="Test")
        net.add_place(name="Empty", tokens=0)

        result = exporter.export(net)

        assert "<initialMarking>" not in result

    def test_export_contains_transitions(self, exporter: PNMLExporter, simple_net: PetriNet):
        """Test that transitions are exported correctly."""
        result = exporter.export(simple_net)

        assert '<transition id="t1">' in result
        assert "<text>Process</text>" in result

    def test_export_contains_arcs(self, exporter: PNMLExporter, simple_net: PetriNet):
        """Test that arcs are exported correctly."""
        result = exporter.export(simple_net)

        assert '<arc id="arc1" source="p1" target="t1">' in result

    def test_export_timed_transition_distribution(self, exporter: PNMLExporter, timed_net: PetriNet):
        """Test that timed transition parameters are exported."""
        result = exporter.export(timed_net)

        assert "<distribution>norm</distribution>" in result
        assert "<delayMeanValue>50.0</delayMeanValue>" in result
        assert "<standardDeviation>5.0</standardDeviation>" in result

    def test_export_immediate_transition(self, exporter: PNMLExporter, simple_net: PetriNet):
        """Test that immediate transitions use deterministic distribution."""
        result = exporter.export(simple_net)

        assert "<distribution>det</distribution>" in result
        assert "<timeDelay>0</timeDelay>" in result

    def test_export_coordinates(self, exporter: PNMLExporter, simple_net: PetriNet):
        """The wire coordinate is the node's CENTER, not its stored top-left:
        the place sits at (100, 100) but is 56x56 (PLACE_W/PLACE_H), so its
        center, and what gets written, is (128, 128)."""
        result = exporter.export(simple_net)

        assert 'x="128"' in result
        assert 'y="128"' in result

    def test_export_toolspecific_section(self, exporter: PNMLExporter, simple_net: PetriNet):
        """This application writes only its own identity, PetriNetSim; the
        desktop's own writer states only PetriObjModel in turn, and each
        reader's cross-fallback is what still opens the other's file. See
        services/petri/exporter/toolspecific.py."""
        result = exporter.export(simple_net)

        assert (
            f'<toolspecific tool="{TOOL_PETRI_NET_SIM}" version="{PETRI_NET_SIM_VERSION}">'
            in result
        )
        assert "PetriObjModel" not in result

    def test_save_creates_file(self, exporter: PNMLExporter, simple_net: PetriNet, tmp_path: Path):
        """Test that save creates a file."""
        output_path = tmp_path / "test.pnml"

        result = exporter.save(simple_net, output_path)

        assert result == output_path
        assert output_path.exists()

    def test_save_file_content(self, exporter: PNMLExporter, simple_net: PetriNet, tmp_path: Path):
        """Test that saved file has correct content."""
        output_path = tmp_path / "test.pnml"

        exporter.save(simple_net, output_path)
        content = output_path.read_text(encoding="utf-8")

        assert '<?xml version="1.0"' in content
        assert "<pnml" in content
        assert '<place id="p1">' in content

    def test_save_creates_parent_directories(
        self, exporter: PNMLExporter, simple_net: PetriNet, tmp_path: Path
    ):
        """Test that save creates parent directories if needed."""
        output_path = tmp_path / "subdir" / "nested" / "test.pnml"

        exporter.save(simple_net, output_path)

        assert output_path.exists()

    def test_save_accepts_string_path(
        self, exporter: PNMLExporter, simple_net: PetriNet, tmp_path: Path
    ):
        """Test that save accepts string path."""
        output_path = str(tmp_path / "test.pnml")

        result = exporter.save(simple_net, output_path)

        assert isinstance(result, Path)
        assert result.exists()


class TestPNMLExporterDistributions:
    """Tests for different distribution types in export."""

    @pytest.fixture
    def exporter(self) -> PNMLExporter:
        return PNMLExporter()

    def test_export_exponential_distribution(self, exporter: PNMLExporter):
        """Test exponential distribution export."""
        net = PetriNet(name="Test")
        net.add_transition(
            name="ExpTrans",
            distribution=DistributionType.EXP,
            mean_delay=10.0,
        )

        result = exporter.export(net)

        assert "<distribution>exp</distribution>" in result
        assert "<delayMeanValue>10.0</delayMeanValue>" in result
        assert "<standardDeviation>" not in result

    def test_export_uniform_distribution(self, exporter: PNMLExporter):
        """Test uniform distribution export."""
        net = PetriNet(name="Test")
        net.add_transition(
            name="UnifTrans",
            distribution=DistributionType.UNIF,
            mean_delay=20.0,
            standard_deviation=5.0,
        )

        result = exporter.export(net)

        assert "<distribution>unif</distribution>" in result
        assert "<standardDeviation>5.0</standardDeviation>" in result

    def test_export_deterministic_distribution(self, exporter: PNMLExporter):
        """Test deterministic distribution export."""
        net = PetriNet(name="Test")
        net.add_transition(
            name="DetTrans",
            distribution=DistributionType.DET,
            mean_delay=15.0,
        )

        result = exporter.export(net)

        assert "<distribution>det</distribution>" in result
        assert "<delayMeanValue>15.0</delayMeanValue>" in result


class TestPNMLExporterEdgeCases:
    """Tests for edge cases in PNML export."""

    @pytest.fixture
    def exporter(self) -> PNMLExporter:
        return PNMLExporter()

    def test_export_empty_net(self, exporter: PNMLExporter):
        """Test exporting an empty net."""
        net = PetriNet(name="Empty")

        result = exporter.export(net)

        assert '<?xml version="1.0"' in result
        assert "<pnml" in result
        assert "<place" not in result
        assert "<transition" not in result

    def test_export_net_with_special_characters_in_name(self, exporter: PNMLExporter):
        """Test that special characters are escaped in XML."""
        net = PetriNet(name="Test & <Net>")
        net.add_place(name="Place <1>", tokens=0)

        result = exporter.export(net)

        # Jinja2 with autoescape should handle this
        assert "&amp;" in result or "& " not in result
        assert "&lt;" in result or "< " not in result

    def test_export_arc_weight(self, exporter: PNMLExporter):
        """Test that arc weight is exported correctly."""
        net = PetriNet(name="Test")
        p1 = net.add_place(name="P1")
        t1 = net.add_transition(name="T1")
        net.add_arc(source_id=p1.id, target_id=t1.id, weight=3)

        result = exporter.export(net)

        # Find the inscription text for weight
        assert "<inscription>" in result
        assert "<text>3</text>" in result.split("<inscription>")[1].split("</inscription>")[0]

    def test_export_multiple_arcs(self, exporter: PNMLExporter):
        """Test exporting net with multiple arcs."""
        net = PetriNet(name="Test")
        p1 = net.add_place(name="P1", tokens=1)
        p2 = net.add_place(name="P2")
        t1 = net.add_transition(name="T1")
        net.add_arc(source_id=p1.id, target_id=t1.id)
        net.add_arc(source_id=t1.id, target_id=p2.id)

        result = exporter.export(net)

        assert result.count("<arc ") == 2
        assert 'source="p1" target="t1"' in result
        assert 'source="t1" target="p2"' in result

    def test_export_priority(self, exporter: PNMLExporter):
        """Test that transition priority is exported."""
        net = PetriNet(name="Test")
        net.add_transition(name="HighPriority", priority=5)

        result = exporter.export(net)

        assert "<priority>5</priority>" in result
