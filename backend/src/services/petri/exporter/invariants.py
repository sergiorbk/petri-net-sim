"""Post-render invariant checks shared by PNMLExporter and ComposedPNMLExporter.

Both writers re-parse their own freshly rendered XML string and check it
against the same handful of things a template regression (a macro emitting
the wrong variable, a stray `{% for %}` reordering a page) could silently
violate, even though the Python-side view model the template walked was
correct: every element id is a valid XML NCName, no two elements share an id,
every page the document claims to have is actually present, every arc's
inscription is a positive integer, and (the one rule that spans more than
one element) an arc's source and target both live on the SAME page as the
arc itself.

Extracted into one function used by both exporters instead of living twice:
before this, only the composed exporter ran any of this at all, and the flat
exporter shipped whatever the template produced with no invariant checking
whatsoever.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

_PNML_NS = "{http://www.pnml.org/version-2009/grammar/pnml}"

#: Deliberate ASCII under-approximation of the XML NCName grammar: every id
#: either exporter emits is ASCII (raw domain ids, the composed exporter's
#: "o{n}_"/"ref_"/"larc_" prefixes), so the wider set of Unicode letters and
#: combining marks a real NCName also allows never actually matters here.
NCNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")

_REFERENCE_TAGS = ("referencePlace", "referenceTransition")
_NODE_TAGS = ("place", "transition", *_REFERENCE_TAGS)


def assert_invariants(xml_text: str, *, exporter_name: str) -> None:
    """Re-parse `xml_text` and raise `ValueError` on the first violation found.

    `exporter_name` only flavors the exception text (e.g. "PNML" vs "Composed
    PNML"); the rule set is identical for a single-page flat-net document and
    a multi-page composed one (a page hierarchy is just more pages to walk,
    it does not change what conformant output has to look like at each one).
    """
    root = ET.fromstring(xml_text)
    net = root.find(f"{_PNML_NS}net")
    if net is None:
        raise ValueError(f"{exporter_name} export invariant violated: no <net> element")

    # Pages nest (composed export): every check below is about a page's OWN
    # direct children, so a node on a nested page is not a node of the page
    # enclosing it, and an arc still may not leave the page it is drawn on.
    pages = _all_pages(net)
    if not pages:
        raise ValueError(f"{exporter_name} export invariant violated: document has no <page>")

    seen_ids: set[str] = set()
    node_page: dict[str, ET.Element] = {}

    for page in pages:
        for tag in (*_NODE_TAGS, "arc"):
            for el in page.findall(f"{_PNML_NS}{tag}"):
                eid = el.get("id")
                if not eid or not NCNAME_RE.fullmatch(eid):
                    raise ValueError(
                        f"{exporter_name} export invariant violated: "
                        f"'{eid}' is not a valid XML NCName"
                    )
                if eid in seen_ids:
                    raise ValueError(
                        f"{exporter_name} export invariant violated: duplicate id '{eid}'"
                    )
                seen_ids.add(eid)
                if tag != "arc":
                    node_page[eid] = page
                if tag in _REFERENCE_TAGS and el.find(f"{_PNML_NS}initialMarking") is not None:
                    raise ValueError(
                        f"{exporter_name} export invariant violated: "
                        f"<{tag} id='{eid}'> carries <initialMarking>"
                    )

    for page in pages:
        for arc in page.findall(f"{_PNML_NS}arc"):
            aid = arc.get("id")
            src, tgt = arc.get("source"), arc.get("target")
            # A missing endpoint is a different, more specific failure than a
            # same-page violation: it means the id is not a node anywhere in
            # the document at all, not merely on a different page than the
            # arc, so it gets its own message instead of the same-page one.
            for endpoint in (src, tgt):
                if endpoint not in node_page:
                    raise ValueError(
                        f"{exporter_name} export invariant violated: "
                        f"arc '{aid}' references missing node '{endpoint}'"
                    )
            if node_page[src] is not page or node_page[tgt] is not page:
                raise ValueError(
                    f"{exporter_name} export invariant violated: arc '{aid}' "
                    f"endpoints ({src} -> {tgt}) are not both on page '{page.get('id')}'"
                )
            _assert_positive_inscription(arc, exporter_name)


def _assert_positive_inscription(arc: ET.Element, exporter_name: str) -> None:
    """`<inscription>` is `ptnet:PTArcAnnotation`, which the ptnet PNTD (the
    place/transition net type definition that ISO/IEC 15909-2 defines)
    requires to be a positive integer. Both exporters already guarantee this by
    construction (`Arc.weight`/`ComposedLink.quantity` are `ge=1` at the
    Pydantic level, and the composed builder re-checks it defensively before
    ever rendering), so this is cheap insurance against a future template
    regression, not the primary enforcement point.
    """
    text_el = arc.find(f"{_PNML_NS}inscription/{_PNML_NS}text")
    if text_el is None:
        return
    try:
        weight = int((text_el.text or "").strip())
    except ValueError:
        weight = None
    if weight is None or weight < 1:
        raise ValueError(
            f"{exporter_name} export invariant violated: arc '{arc.get('id')}' has "
            f"inscription '{text_el.text}', must be a positive integer"
        )


def _all_pages(scope: ET.Element) -> list[ET.Element]:
    found: list[ET.Element] = []
    for page in scope.findall(f"{_PNML_NS}page"):
        found.append(page)
        found.extend(_all_pages(page))
    return found
