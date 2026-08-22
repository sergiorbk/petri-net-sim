"""PNML export service for composed Petri-object models, ISO/IEC 15909-2
conformant dialect (version "2.1").

Sibling to PNMLExporter (which stays untouched, still used for every
single-net export path) — one `<page>` per object inside one `<net>`, with
inter-object structure expressed the standard way: a placeFusion link
becomes a `<referencePlace>` occupying the source's own place slot, and a
transitionToPlace link becomes a `<referenceTransition>`/`<referencePlace>`
plus an ordinary intra-page `<arc>` (see composed_document.py for the
resolution and docs/petri-object-models.md in the PetriObjModelPaint
repository for the normative shape). A placeToTransition link is refused
outright: PetriObjModelPaint retired that link type, so this exporter raises
a `ValueError` rather than write the projection it used to. `<petriObjectLinks>`
is still emitted, now id-addressed, purely for a reader that does not
implement reference nodes yet, never a second source of truth for a
conformant one.

Verified against petri-server's actual PNML parser (element names
`petriObject`/`petriObjectLinks`, tool="PetriObjModel", see
petri-model/src/main/java/ua/stetsenkoinna/pnml/PnmlConstants.java in
PetriObjModelPaint), not just inferred from documentation. That parser
matches `toolspecific` blocks on `tool` alone, never on `version`
(PnmlModelParser.java:247), which is why bumping the version string to
"2.1" here does not require a lockstep petri-server deploy to stay
*readable*, it only needs one to stop being lossy on placeFusion, per the
deploy-order note in the spec.
"""

from pathlib import Path
from typing import Union

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.services.petri.exporter.geometry import PLACE_H, PLACE_W, TRANS_H, TRANS_W, round_half_up
from src.services.petri.exporter.invariants import assert_invariants
from src.services.petri.exporter.toolspecific import TOOLSPECIFIC_IDENTITIES

from src.domain.composed import ComposedModel

from .composed_document import build_document_model


class ComposedPNMLExporter:
    """
    Exports ComposedModel domain aggregates to multi-page PNML XML.

    Usage:
        exporter = ComposedPNMLExporter()
        xml_string = exporter.export(model)
        exporter.save(model, "model.pnml")
    """

    def __init__(self) -> None:
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
        self._template = self._env.get_template("composed.pnml.j2")

    def export(self, model: ComposedModel) -> str:
        """Render a ComposedModel to multi-page, conformant PNML XML string.

        The resolution (namespacing, ordinals, reference-node placement)
        happens in `build_document_model`, not in the template, see that
        module's docstring for why. `assert_invariants` then re-parses the
        rendered output and checks it against the same-page arc rule and the
        reference-node rules of ISO/IEC 15909-2: cheap insurance against a
        template regression silently reaching petri-server with e.g. a
        cross-page arc or a duplicated id. The reference-cycle rule, the
        positive-inscription rule and the ban on a standard-namespace
        inhibitor-arc marker are mostly enforced earlier, by construction, in
        `build_document_model` and the macros, respectively; `assert_invariants`
        re-checks the inscription rule too, as cheap insurance against the
        same class of template regression.
        """
        document = build_document_model(model)
        xml = self._template.render(doc=document)
        assert_invariants(xml, exporter_name="Composed PNML")
        return xml

    def save(self, model: ComposedModel, path: Union[str, Path]) -> Path:
        """Export and save a ComposedModel to file."""
        path = Path(path)
        xml_content = self.export(model)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml_content, encoding="utf-8")

        return path


# Singleton instance for convenience
_exporter: ComposedPNMLExporter | None = None


def get_composed_pnml_exporter() -> ComposedPNMLExporter:
    """Get singleton ComposedPNMLExporter instance."""
    global _exporter
    if _exporter is None:
        _exporter = ComposedPNMLExporter()
    return _exporter
