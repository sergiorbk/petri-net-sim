"""PNML export service for Petri Net domain models."""

from pathlib import Path
from typing import Union

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.services.petri.exporter.geometry import PLACE_H, PLACE_W, TRANS_H, TRANS_W, round_half_up
from src.services.petri.exporter.invariants import assert_invariants
from src.services.petri.exporter.toolspecific import TOOLSPECIFIC_IDENTITIES

from src.domain import PetriNet


class PNMLExporter:
    """
    Exports PetriNet domain models to PNML XML format.

    PNML (Petri Net Markup Language) is an XML-based interchange format
    for Petri nets, compatible with tools like PetriObjModel.

    Usage:
        exporter = PNMLExporter()
        xml_string = exporter.export(net)
        exporter.save(net, "model.pnml")
    """

    def __init__(self) -> None:
        """Initialize exporter with Jinja2 template environment."""
        template_dir = Path(__file__).parent / "templates"

        self._env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(default_for_string=True, default=True),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # Which tool identities every toolspecific block is written under; the
        # templates loop over this rather than naming one tool inline.
        self._env.globals["toolspecific_identities"] = TOOLSPECIFIC_IDENTITIES
        # Node footprints, so a template can compute a node's own center
        # (wire anchor) from its stored top-left graphics; see geometry.py.
        self._env.globals["PLACE_W"] = PLACE_W
        self._env.globals["PLACE_H"] = PLACE_H
        self._env.globals["TRANS_W"] = TRANS_W
        self._env.globals["TRANS_H"] = TRANS_H
        self._env.filters["round_half_up"] = round_half_up
        self._template = self._env.get_template("net.pnml.j2")

    def export(self, net: PetriNet) -> str:
        """
        Render PetriNet to PNML XML string.

        `assert_invariants` re-parses the rendered output the same way
        ComposedPNMLExporter.export does: cheap insurance against a template
        regression (a hand-assembled net with a space in an id, say) reaching
        petri-server with e.g. a duplicated or non-NCName id.

        Args:
            net: PetriNet domain model

        Returns:
            XML string in PNML format
        """
        xml = self._template.render(net=net)
        assert_invariants(xml, exporter_name="PNML")
        return xml

    def save(self, net: PetriNet, path: Union[str, Path]) -> Path:
        """
        Export and save PetriNet to file.

        Args:
            net: PetriNet domain model
            path: Output file path

        Returns:
            Path to saved file
        """
        path = Path(path)
        xml_content = self.export(net)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml_content, encoding="utf-8")

        return path


# Singleton instance for convenience
_exporter: PNMLExporter | None = None


def get_pnml_exporter() -> PNMLExporter:
    """Get singleton PNMLExporter instance."""
    global _exporter
    if _exporter is None:
        _exporter = PNMLExporter()
    return _exporter
