"""Python port of the frontend PNML reader (frontend/src/lib/pnml-import.ts).

Faithful in SEMANTICS, not in mechanism: the frontend walks a tree that
fast-xml-parser already turned into plain JS objects/arrays; this module
walks `xml.etree.ElementTree` elements directly, matching child elements by
LOCAL name (accepting either the PNML namespace or no namespace at all --
see `_matches`) instead of relying on a pre-parsed object's own keys, which
never carried a namespace to begin with. Every warning code, every hard
failure's exact text, every coordinate/toolspecific/arc-kind/nesting rule
mirrors pnml-import.ts function-for-function; see that file's own comments
for the reasoning behind each rule, not repeated here. One exception:
`_filter_place_fusion_links` also drops a placeFusion link that breaks one
of `ComposedModel.place_fusion_rejection`'s rules (a cycle, a place copying
two masters, a pair linked both ways) and warns about it -- the desktop
editor's own answer to the same document, not yet ported to pnml-import.ts.

Output shape: (net_data, warnings). `net_data` is the SAME frontend-shape
dict the phase 2 converter (composed_convert.py) already reads and writes:
flat `name`/`places`/`transitions`/`arcs`, plus `objects`/`links` for a
composed document (present, possibly empty, only when the document actually
took the composed path -- a flat document's net_data carries neither key,
matching `PetriNetData.objects?`/`links?` being absent for "today's flat
net"). `warnings` is a list of `{"code": ..., "message": ...}` dicts, one of
the seven codes in `WARNING_CODES`: the six pnml-import.ts uses (invalid-id,
duplicate-id, dangling-ref, cross-page-arc, bad-number, invalid-value) plus
this module's own dropped-link.

Two hard failures only, both raised as `ValueError` with the frontend's own
text: a document with no `<pnml>` root, or a `<pnml>` with no `<net>`.
Everything else this reader cannot make sense of is downgraded to a
warning and reinterpreted, remapped, or dropped -- a file always opens if
structurally possible (PNML ISO conformance contract, Part B).
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple

from src.domain.composed import ComposedModel
from src.services.petri.exporter.geometry import PLACE_H, PLACE_W, TRANS_H, TRANS_W
from src.services.petri.exporter.invariants import NCNAME_RE
from src.services.petri.exporter.toolspecific import TOOL_PETRI_NET_SIM

#: This product's own identity (imported above) is preferred; PetriObjModelPaint's
#: is the load-bearing fallback that makes a desktop-authored file open here.
#: Mirrors TOOL_PETRI_OBJ_MODEL in frontend/src/lib/pnml-export-composed.ts,
#: which the backend's own exporter never needed a reader-side name for
#: before this importer existed -- see toolspecific.py's own docstring.
TOOL_PETRI_OBJ_MODEL = "PetriObjModel"

_PNML_NS = "http://www.pnml.org/version-2009/grammar/pnml"

#: The six warning codes pnml-import.ts emits, plus "dropped-link" (backend-
#: only for now: the desktop editor's own answer to a document declaring an
#: illegal placeFusion -- see `_structural_links` -- has no frontend port
#: yet). Kept as a plain tuple (not an Enum) since every warning this module
#: produces is a plain {"code": ..., "message": ...} dict, matching the
#: frontend-shape convention the rest of this net_data dict already follows.
WARNING_CODES = (
    "invalid-id",
    "duplicate-id",
    "dangling-ref",
    "cross-page-arc",
    "bad-number",
    "invalid-value",
    "dropped-link",
)

WarnFn = Callable[[str, str], None]


# ---------------------------------------------------------------------------
# XML plumbing: local-name matching (accept the PNML namespace or none),
# text extraction, and Number()/parseInt()-equivalent numeric coercion.
# ---------------------------------------------------------------------------


def _tag_info(tag: str) -> Tuple[str, str]:
    """(namespace, local name) for an ElementTree tag string."""
    if tag.startswith("{"):
        ns, _, local = tag[1:].partition("}")
        return ns, local
    return "", tag


def _matches(el: ET.Element, name: str) -> bool:
    ns, local = _tag_info(el.tag)
    return local == name and ns in ("", _PNML_NS)


def _children(el: Optional[ET.Element], name: str) -> List[ET.Element]:
    if el is None:
        return []
    return [c for c in el if _matches(c, name)]


def _child(el: Optional[ET.Element], name: str) -> Optional[ET.Element]:
    kids = _children(el, name)
    return kids[0] if kids else None


def _attr(el: ET.Element, name: str, default: str = "") -> str:
    """Mirrors `String(el["@_name"] ?? default)`: a NULLISH fallback (only
    an absent attribute falls back), not a falsy one -- an attribute
    present but empty stays empty, exactly like JS `??` (as opposed to a
    plain `||`, which would also replace an empty string).

    Also mirrors fast-xml-parser's own `trimValues: true` default, which
    the frontend parser never overrides: every attribute value it hands
    the reader has already been `.trim()`-ed before this app's own code
    ever sees it (OrderedObjParser.buildAttributesMap). `xml.etree`
    performs no such trimming, so a raw attribute value is stripped here
    -- once, in the one place every id/name/type attribute read in this
    module funnels through -- to keep a whitespace-padded document (e.g.
    `id="  p1  "`) parsing to the same id the frontend would produce,
    instead of carrying the padding into `is_ncname`/`sanitize_ncname`
    and getting needlessly remapped. *default* is a Python literal, never
    XML text, so it is returned as-is, untouched.
    """
    value = el.get(name)
    return value.strip() if value is not None else default


def _text_of(el: Optional[ET.Element]) -> str:
    """Mirrors pnml-import.ts's `textOf`: a label's value is either a
    nested `<text>` child (name/initialMarking/inscription) or the
    element's own direct text content (every toolspecific leaf, which
    carries its value raw, with no `<text>` wrapper) -- checking for the
    child first and falling back to direct text handles both shapes with
    one function, exactly like the frontend's does with one function
    handling both of fast-xml-parser's two different parsed shapes.

    Also mirrors fast-xml-parser's own `trimValues: true` default (see
    `_attr`'s own docstring): a tag's text is trimmed by the frontend's
    parser before any of its own code runs, so `<initialMarking> 5
    </initialMarking>` there is already the string "5" by the time
    `Number.parseInt` sees it. `xml.etree` hands back the raw, unstripped
    text node, so it is stripped here to match -- otherwise a
    whitespace-padded numeric value would fail `_parse_int`/`_js_number`
    here while parsing fine on the frontend.
    """
    if el is None:
        return ""
    text_child = _child(el, "text")
    if text_child is not None:
        return (text_child.text or "").strip()
    return (el.text or "").strip()


#: Unsigned hex literal, matching JS's StringNumericLiteral grammar: a
#: `NonDecimalIntegerLiteral` never carries a sign (unlike the decimal
#: form), so `Number("-0x1A")` is NaN even though `Number("0x1A")` is 26.
_JS_HEX_RE = re.compile(r"^0[xX][0-9a-fA-F]+$")


def _js_number(text: str) -> float:
    """Mirrors JS `Number(string)`: the whole string must parse (unlike
    parseInt's leading-prefix leniency), empty/whitespace-only is 0, and
    anything else that doesn't parse is NaN (not an exception).

    Three places Python's own numeric grammar is more permissive than
    JS's, each corrected here rather than left to `float()`:

    - Underscore digit separators (`"1_000"`): legal inside a Python
      numeric literal since PEP 515, and `float()` accepts them in a
      string too -- there is no equivalent in JS's StringNumericLiteral
      grammar, so `Number("1_000")` is NaN. Checked for and rejected
      before `float()` ever sees the text.
    - Non-ASCII decimal digits (e.g. Arabic-indic `"١٢٣"`,
      Devanagari `"५५"`): valid input to `float()`, which
      converts any Unicode "Nd"-category digit; JS's grammar is ASCII
      `0`-`9` only, so `Number()` on the same text is NaN. Rejected the
      same way.
    - The `0x`/`0X` hex form: `float()` does not parse it at all (a
      hard `ValueError`, i.e. today's NaN), but `Number("0x1A")` is 26 --
      JS's grammar includes it as a `NonDecimalIntegerLiteral`. Matched
      and converted explicitly, ahead of the `float()` fallback, since
      `float()` has no path to it at all.
    """
    stripped = text.strip()
    if stripped == "":
        return 0.0
    if "_" in stripped:
        return float("nan")
    if any(ch.isdecimal() and not ch.isascii() for ch in stripped):
        return float("nan")
    if _JS_HEX_RE.match(stripped):
        return float(int(stripped, 16))
    try:
        return float(stripped)
    except ValueError:
        return float("nan")


#: ASCII digits only (`[0-9]`, not `\d`): Python's `\d` matches any
#: Unicode "Nd"-category digit by default, which `int()` then happily
#: converts -- JS's `Number.parseInt` recognizes ASCII `0`-`9` only, so a
#: non-ASCII digit run (e.g. Devanagari `"५५"`) is NaN there but
#: would otherwise parse fine here. An embedded `_` digit separator needs
#: no special handling: it is not in `[0-9]` either way, so the match
#: already stops there exactly like `Number.parseInt`'s own leading-run
#: leniency does.
_PARSE_INT_RE = re.compile(r"^\s*[+-]?[0-9]+")


def _parse_int(text: str) -> Optional[int]:
    """Mirrors JS `Number.parseInt(text, 10)`: parses a leading optional
    sign + decimal digits, ignoring any trailing non-digit content; `None`
    (JS: NaN) when the string does not even start with one."""
    m = _PARSE_INT_RE.match(text)
    if not m:
        return None
    return int(m.group(0))


def _maybe_int(n: float):
    """A whole-valued float becomes a plain int (cleaner net_data JSON,
    and what every domain Pydantic model downstream actually expects for
    tokens/weight/priority/quantity); a genuinely fractional one is left
    alone -- the frontend's own numbers have no such distinction, this is
    purely a Python-side JSON-cleanliness convenience with no behavioral
    effect on any comparison a warning or a test makes."""
    return int(n) if float(n).is_integer() else n


def _num_attr(el: Optional[ET.Element], attr: str, fallback: float) -> float:
    """Mirrors pnml-import.ts's `numAttr`: a missing attribute or one that
    does not parse to a finite number both fall back, silently."""
    if el is None:
        return fallback
    raw = el.get(attr)
    if raw is None:
        return fallback
    n = _js_number(raw)
    return n if math.isfinite(n) else fallback


def _contains_element_deep(node: ET.Element, names: Set[str]) -> bool:
    """Recursively searches `node`'s whole subtree for any of `names`, at
    any depth -- used to detect composed-model structure wherever in the
    document it lands, without a full multi-page parser."""
    for child in node:
        _, local = _tag_info(child.tag)
        if local in names:
            return True
        if _contains_element_deep(child, names):
            return True
    return False


# ---------------------------------------------------------------------------
# Toolspecific selection (PetriNetSim preferred, PetriObjModel fallback,
# version never filtered) and node geometry (wire position is the node's
# CENTER; the domain model stores top-left, see exporter/geometry.py).
# ---------------------------------------------------------------------------


def _find_toolspecific(element: ET.Element) -> Optional[ET.Element]:
    """The tool-specific block to read, out of however many `element`
    carries. A SINGLE block is used regardless of what its own `tool`
    attribute says (a foreign document's only toolspecific block is still
    the best guess this reader has); with two or more, this app's own
    identity wins, then PetriObjModelPaint's, and neither existing (both
    present but under some third name, or simply absent) returns nothing --
    mirrors pnml-import.ts's findToolspecific exactly, including that
    single-vs-multiple distinction.
    """
    blocks = _children(element, "toolspecific")
    if not blocks:
        return None
    if len(blocks) == 1:
        return blocks[0]

    def by_tool(tool: str) -> Optional[ET.Element]:
        return next((b for b in blocks if b.get("tool") == tool), None)

    preferred = by_tool(TOOL_PETRI_NET_SIM)
    return preferred if preferred is not None else by_tool(TOOL_PETRI_OBJ_MODEL)


def _toolspecific_child(element: ET.Element, key: str) -> Optional[ET.Element]:
    ts = _find_toolspecific(element)
    return _child(ts, key) if ts is not None else None


def _extract_position(element: ET.Element) -> Tuple[float, float]:
    graphics = _child(element, "graphics")
    position = _child(graphics, "position") if graphics is not None else None
    if position is not None:
        return _num_attr(position, "x", 0), _num_attr(position, "y", 0)
    ts = _find_toolspecific(element)
    coordinates = _child(ts, "coordinates") if ts is not None else None
    if coordinates is not None:
        return _num_attr(coordinates, "x", 0), _num_attr(coordinates, "y", 0)
    return 0.0, 0.0


def _extract_center_position(element: ET.Element, kind: str) -> Tuple[float, float]:
    """Converts a wire position (the node's CENTER) back to the app
    model's top-left anchor, by subtracting half the node's own footprint
    -- see exporter/geometry.py's own docstring for why this exact
    convention. A referencePlace uses place size, a referenceTransition
    uses transition size, matching how the exporter picked a size for it.
    """
    x, y = _extract_position(element)
    half_w = (PLACE_W if kind == "place" else TRANS_W) / 2
    half_h = (PLACE_H if kind == "place" else TRANS_H) / 2
    return x - half_w, y - half_h


# ---------------------------------------------------------------------------
# Composed-document detection and page collection.
# ---------------------------------------------------------------------------


def _is_composed_document(net: ET.Element) -> bool:
    """True when the document says anything a single flat page cannot."""
    top_pages = _children(net, "page")
    if len(top_pages) > 1:
        return True
    return _contains_element_deep(
        net, {"referencePlace", "referenceTransition", "petriObjectLinks", "petriObject"}
    )


def _collect_pages(
    net: ET.Element,
) -> Tuple[List[ET.Element], Dict[ET.Element, ET.Element]]:
    """Every `<page>` of the document, nested ones included, and the page
    each one sits directly inside (absent for a page under `<net>` itself).
    """
    pages: List[ET.Element] = []
    enclosing: Dict[ET.Element, ET.Element] = {}

    def walk(node: ET.Element, parent: Optional[ET.Element]) -> None:
        for page in _children(node, "page"):
            pages.append(page)
            if parent is not None:
                enclosing[page] = parent
            walk(page, page)

    walk(net, None)
    return pages, enclosing


def _petri_object_marker(page: ET.Element) -> Optional[ET.Element]:
    ts = _find_toolspecific(page)
    return _child(ts, "petriObject") if ts is not None else None


def _order_pages_by_index(pages: List[ET.Element], nested: bool) -> List[ET.Element]:
    """Pages in the order their `<petriObject index="...">` attributes
    state -- see pnml-import.ts's own docstring on why document order is
    not that order once pages nest, and why a nested document that cannot
    say a valid order has to fail rather than guess.
    """
    by_index: Dict[int, ET.Element] = {}
    for page in pages:
        index = _num_attr(_petri_object_marker(page), "index", -1)
        if (
            not math.isfinite(index)
            or not float(index).is_integer()
            or index < 0
            or index >= len(pages)
            or int(index) in by_index
        ):
            if nested:
                raise ValueError(
                    "Invalid PNML: this document nests its pages, so every page must state a "
                    "unique <petriObject index> in 0.."
                    f"{len(pages) - 1}; page order cannot be guessed from the document, and the "
                    "links address objects by that index."
                )
            return pages
        by_index[int(index)] = page
    return [by_index[i] for i in range(len(pages))]


def _is_fusion_reference(raw: ET.Element, touched_by_arcs: Set[str]) -> bool:
    """What a reference node means, which the document only sometimes says
    outright -- see pnml-import.ts's own docstring (mirrors
    ReferenceNodeIndex.isFusion)."""
    role = _text_of(_toolspecific_child(raw, "referenceRole"))
    if role:
        return role.lower() == "fusion"
    return _attr(raw, "id") not in touched_by_arcs


@dataclass
class _DocNode:
    """One place, transition or reference node of the document, with
    where it sits. Mirrors pnml-import.ts's DocumentNode interface."""

    id: str
    page: int
    place_kind: bool
    reference: bool
    fusion: bool
    ref: str
    name: str


# ---------------------------------------------------------------------------
# Id safety net (PNML ISO conformance contract, decision 2): export always
# writes NCName-safe ids; import accepts whatever a document actually says,
# remaps anything that is not a valid, unique NCName, rewrites every
# reference to it, and reports one warning per replacement.
# ---------------------------------------------------------------------------


def is_ncname(raw_id: str) -> bool:
    return bool(NCNAME_RE.fullmatch(raw_id))


_NCNAME_INVALID_CHARS_RE = re.compile(r"[^A-Za-z0-9_.\-]")
_NCNAME_START_RE = re.compile(r"^[A-Za-z_]")
_DASH_RUN_RE = re.compile(r"-+")
_LEADING_TRAILING_DASH_RE = re.compile(r"^-+|-+$")


def sanitize_ncname(raw_id: str) -> str:
    """Makes an arbitrary string safe to write as an XML id. Mirrors
    frontend/src/lib/pnml-export-composed.ts's `sanitizeNCName` exactly:
    every character outside the NCName alphabet becomes "-"; an invalid
    (or absent) first character gets an "n-" prefix; runs of "-" then
    collapse to one and leading/trailing "-" are trimmed. A result that
    sanitizes to nothing becomes "n"."""
    s = _NCNAME_INVALID_CHARS_RE.sub("-", raw_id)
    if not _NCNAME_START_RE.match(s):
        s = f"n-{s}"
    s = _DASH_RUN_RE.sub("-", s)
    s = _LEADING_TRAILING_DASH_RE.sub("", s)
    return s if len(s) > 0 else "n"


def _describe(kind: str, id_: str, name: str) -> str:
    """Names an already-resolved element in a warning message, by its
    visible name when there is one, by its id otherwise."""
    if name and name != id_:
        return f'{kind} "{name}" (id "{id_}")'
    return f'{kind} id "{id_}"'


def _label(kind: str, raw_id: str, visible_name: str) -> str:
    """Same as `_describe`, but for a not-yet-resolved raw id (used only
    inside `_IdRegistry.assign`, before the final id exists)."""
    if visible_name:
        return f'{kind} "{visible_name}" (id "{raw_id}")'
    return f'{kind} id "{raw_id}"'


class _IdRegistry:
    """One id-safety pass shared by the whole document. Mirrors
    pnml-import.ts's createParseContext: every place, transition, arc,
    reference node and object-frame page gets exactly one call to
    `assign`, in the order it is parsed ("first occurrence"); a raw id
    already a valid, unclaimed NCName keeps itself, otherwise it is
    sanitized and, on a further collision (including a genuine duplicate),
    given a "-2", "-3", ... suffix.

    `resolve` answers what an arc's source/target, a reference node's
    `ref`, or a declared link's element id should now point at: always the
    id assigned to the FIRST element that ever carried that raw id.

    Passing the element's own raw XML node as `raw_node` caches the result
    under that node's identity (Python's default object-identity hashing,
    matching JS's WeakMap<object, string>): a second call for the very
    same node returns the cached id unchanged, letting the two-pass
    composed reader register every element up front and then parse each
    one a second time without re-registering (and re-warning about) it.
    """

    def __init__(self, warn: WarnFn) -> None:
        self._warn = warn
        self._used: Set[str] = set()
        self._first_final_id_of: Dict[str, str] = {}
        self._id_by_node: Dict[int, str] = {}

    def assign(
        self, kind: str, raw_id: str, visible_name: str, raw_node: Optional[ET.Element] = None,
    ) -> str:
        if raw_node is not None:
            cached = self._id_by_node.get(id(raw_node))
            if cached is not None:
                return cached

        invalid = not is_ncname(raw_id)
        base = sanitize_ncname(raw_id) if invalid else raw_id
        target = base
        duplicate = False
        if target in self._used:
            duplicate = True
            n = 2
            candidate = f"{base}-{n}"
            while candidate in self._used:
                n += 1
                candidate = f"{base}-{n}"
            target = candidate
        self._used.add(target)
        if raw_id not in self._first_final_id_of:
            self._first_final_id_of[raw_id] = target

        if duplicate:
            self._warn(
                "duplicate-id",
                f"{_label(kind, raw_id, visible_name)} duplicates an id already used elsewhere "
                f'in the document; imported as "{target}".',
            )
        elif invalid:
            self._warn(
                "invalid-id",
                f'{_label(kind, raw_id, visible_name)} is not a valid XML id; imported as "{target}".',
            )

        if raw_node is not None:
            self._id_by_node[id(raw_node)] = target
        return target

    def resolve(self, raw_id: str) -> Optional[str]:
        return self._first_final_id_of.get(raw_id)


# ---------------------------------------------------------------------------
# Element parsing: place, transition, arc.
# ---------------------------------------------------------------------------


def _parse_place(
    raw: ET.Element, registry: _IdRegistry, warn: WarnFn, id_override: Optional[str] = None,
) -> dict:
    raw_id = _attr(raw, "id")
    visible_name = _text_of(_child(raw, "name"))
    # A fusion referencePlace hands in the id it already assigned itself,
    # as a reference node, above: the same XML element is being parsed a
    # second time as the real place it stands for, and it must keep the
    # one id it was given.
    id_ = id_override if id_override is not None else registry.assign("Place", raw_id, visible_name, raw)
    name = visible_name or id_

    marking_text = _text_of(_child(raw, "initialMarking"))
    tokens = 0
    if marking_text != "":
        parsed = _parse_int(marking_text)
        if parsed is None:
            warn(
                "bad-number",
                f'{_describe("Place", id_, name)} has a malformed initial marking '
                f'"{marking_text}"; imported with 0 tokens.',
            )
        elif parsed < 0:
            warn(
                "invalid-value",
                f'{_describe("Place", id_, name)} has initial marking {parsed}, which is not a '
                "valid marking (a ptnet initial marking must be a nonnegative integer); imported as 0.",
            )
        else:
            tokens = parsed

    x, y = _extract_center_position(raw, "place")
    place = {"id": id_, "name": name, "tokens": tokens, "graphics": {"x": x, "y": y}}
    semantic_tag = _text_of(_toolspecific_child(raw, "semanticTag"))
    if semantic_tag:
        place["tag"] = semantic_tag
    return place


def _parse_transition(raw: ET.Element, registry: _IdRegistry, warn: WarnFn) -> dict:
    raw_id = _attr(raw, "id")
    visible_name = _text_of(_child(raw, "name"))
    id_ = registry.assign("Transition", raw_id, visible_name, raw)
    name = visible_name or id_
    x, y = _extract_center_position(raw, "transition")

    ts = _find_toolspecific(raw)
    priority: object = 1
    distribution: Optional[str] = "exp"
    mean_delay: float = 1
    std_dev: float = 0
    probability: Optional[float] = None

    if ts is not None and _attr(ts, "tool") == TOOL_PETRI_OBJ_MODEL:
        # Desktop omissions mean deterministic delay and priority zero.
        distribution, mean_delay, priority = "det", 0, 0

    if ts is not None:
        priority_el = _child(ts, "priority")
        if priority_el is not None:
            priority_text = _text_of(priority_el)
            p = _js_number(priority_text)
            if math.isfinite(p):
                # A plain `Number(...) || 1` treated an explicit, legal
                # priority of 0 as if parsing had failed. Only a value
                # that genuinely fails to parse gets the fallback, and
                # only that case warns.
                priority = _maybe_int(p)
            else:
                priority = 1
                warn(
                    "bad-number",
                    f'{_describe("Transition", id_, name)} has a malformed priority '
                    f'"{priority_text}"; imported with priority 1.',
                )

        probability_el = _child(ts, "probability")
        if probability_el is not None:
            p = _js_number(_text_of(probability_el))
            if math.isfinite(p):
                probability = p
                distribution = None

        if probability is None or any(_child(ts, key) is not None for key in ("distribution", "delayMeanValue", "timeDelay")):
            dist_el = _child(ts, "distribution")
            if dist_el is not None:
                dist_raw = _text_of(dist_el)
                valid = ("exp", "norm", "unif", "det")
                distribution = dist_raw if dist_raw in valid else "exp"

            delay_mean_el = _child(ts, "delayMeanValue")
            time_delay_el = _child(ts, "timeDelay")
            if delay_mean_el is not None:
                n = _js_number(_text_of(delay_mean_el))
                mean_delay = n if math.isfinite(n) else 0
            elif time_delay_el is not None:
                n = _js_number(_text_of(time_delay_el))
                mean_delay = n if math.isfinite(n) else 0

            std_el = _child(ts, "standardDeviation")
            if std_el is not None:
                n = _js_number(_text_of(std_el))
                std_dev = n if math.isfinite(n) else 0

    return {
        "id": id_,
        "name": name,
        "priority": priority,
        "distribution": distribution,
        "mean_delay": _maybe_int(float(mean_delay)),
        "standard_deviation": _maybe_int(float(std_dev)),
        "probability": probability,
        "graphics": {"x": x, "y": y},
    }


def _parse_arc(raw: ET.Element, registry: _IdRegistry, warn: WarnFn) -> dict:
    raw_id = _attr(raw, "id")
    id_ = registry.assign("Arc", raw_id, "", raw)
    raw_source_id = _attr(raw, "source")
    raw_target_id = _attr(raw, "target")
    resolved_source = registry.resolve(raw_source_id)
    resolved_target = registry.resolve(raw_target_id)
    source_id = resolved_source if resolved_source is not None else raw_source_id
    target_id = resolved_target if resolved_target is not None else raw_target_id

    inscription_text = _text_of(_child(raw, "inscription"))
    weight = 1
    if inscription_text != "":
        parsed = _parse_int(inscription_text)
        if parsed is None:
            warn(
                "bad-number",
                f'{_describe("Arc", id_, "")} has a malformed inscription "{inscription_text}"; '
                "imported with weight 1.",
            )
        elif parsed < 1:
            warn(
                "invalid-value",
                f'{_describe("Arc", id_, "")} has inscription {parsed}, which is not a valid '
                "weight (a ptnet arc weight must be a positive integer); imported as 1.",
            )
        else:
            weight = parsed

    # Three shapes say the same thing; the desktop's PnmlParser.parseArcs
    # accepts all three, so this reader does too. The `type` attribute is
    # this app's own shorthand and wins; then the tool-specific `<arcType>`
    # both writers emit; then the informational flag PetriObjModelPaint
    # uses for a non-consuming input arc it calls "informational" rather
    # than "read"; then the standard PNML `<type value="inhibitorArc"/>`
    # child a foreign tool would write.
    arc_type = "NORMAL"
    type_attr = raw.get("type")
    if type_attr is not None:
        upper = type_attr.upper()
        if upper == "INHIBITOR":
            arc_type = "INHIBITOR"
        elif upper == "READ":
            arc_type = "READ"
    if arc_type == "NORMAL":
        tool_arc_type = _text_of(_toolspecific_child(raw, "arcType")).lower()
        if tool_arc_type == "inhibitor":
            arc_type = "INHIBITOR"
        elif tool_arc_type == "read":
            arc_type = "READ"
    if arc_type == "NORMAL":
        if _text_of(_toolspecific_child(raw, "informational")) == "true":
            arc_type = "READ"
    if arc_type == "NORMAL":
        for type_el in _children(raw, "type"):
            value = (type_el.get("value") or "").lower()
            if "inhibitor" in value:
                arc_type = "INHIBITOR"
                break

    return {"id": id_, "source_id": source_id, "target_id": target_id, "weight": weight, "arc_type": arc_type}


# ---------------------------------------------------------------------------
# Composed-document links: structural (reference nodes) and declared
# (net-level <petriObjectLinks>), merged per PnmlModelParser.mergeDeclaredLinks.
# ---------------------------------------------------------------------------


def _endpoint_kind(link_type: str, side: str) -> str:
    if link_type == "placeFusion":
        return "place"
    if link_type == "transitionToPlace":
        return "transition" if side == "source" else "place"
    return "place" if side == "source" else "transition"  # placeToTransition


def _endpoint_key(link: dict) -> str:
    return f'{link["type"]}:{link["sourceId"]}:{link["targetId"]}'


def _structural_links(
    pages: List[ET.Element],
    reference_nodes_by_page: List[List[_DocNode]],
    arcs_by_page: List[List[dict]],
    arc_raw_by_page: List[List[ET.Element]],
    nodes: Dict[str, _DocNode],
    registry: _IdRegistry,
    warn: WarnFn,
) -> Tuple[List[dict], Set[str]]:
    """The links the document's structure states -- see pnml-import.ts's
    own docstring (mirrors ReferenceNodeIndex).

    Every placeFusion link this produces is well-formed by construction and
    never needs `ComposedModel.place_fusion_rejection`'s rules checked
    against it here: `resolve()` below always walks a reference chain
    through to a genuinely real (non-reference) node, so a structural
    fusion's target is always a real `<place>`, never another copy -- rules
    3/4 (a copy of two masters, a cycle of copies) need a "master" that is
    ITSELF also a copy, which this resolution can never produce, and rule 2
    (the same pair linked twice) needs the same SOURCE id to recur, which
    can't happen either, since each `<referencePlace>` element is exactly
    one source. A document that violates one of these rules can only do so
    with the OLDER, position-addressed `<petriObjectLinks>` declarations
    that bypass reference nodes entirely -- see `_filter_place_fusion_links`,
    which both paths' output passes through before this function's caller
    returns it.
    """

    def resolve(start: _DocNode) -> Optional[_DocNode]:
        current: Optional[_DocNode] = start
        visited: Set[str] = set()
        while current is not None and current.reference:
            if current.id in visited:
                return None
            visited.add(current.id)
            resolved = registry.resolve(current.ref)
            target_id = resolved if resolved is not None else current.ref
            current = nodes.get(target_id)
        return current

    links: List[dict] = []
    linked_arc_ids: Set[str] = set()

    for index, _page in enumerate(pages):
        page_arcs_raw = arc_raw_by_page[index]
        page_arcs_parsed = arcs_by_page[index]
        claimed: Set[str] = set()

        for node in reference_nodes_by_page[index]:
            target = resolve(node)
            if target is None:
                warn(
                    "dangling-ref",
                    f'Reference node "{node.name}" points to missing id "{node.ref}"; the link '
                    "it stands for was skipped.",
                )
                continue

            if node.fusion:
                # A fusion says this object's slot *is* the other object's place.
                if not target.place_kind:
                    continue
                links.append({"type": "placeFusion", "sourceId": node.id, "targetId": target.id, "quantity": 1})
                continue

            # A representative carries its links on its arcs: every arc of
            # the page that touches it crosses an object boundary.
            for j, raw in enumerate(page_arcs_raw):
                arc = page_arcs_parsed[j]
                outgoing = arc["source_id"] == node.id
                if not outgoing and arc["target_id"] != node.id:
                    continue
                if arc["id"] in claimed:
                    continue
                claimed.add(arc["id"])

                other_id = arc["target_id"] if outgoing else arc["source_id"]
                other = nodes.get(other_id)
                other_is_slot = other is not None and (not other.reference or other.fusion)
                if other is None or not other_is_slot or other.page != index or other.place_kind == node.place_kind:
                    continue

                quantity = max(1, arc["weight"])
                informational = _text_of(_toolspecific_child(raw, "informational")) == "true"
                linked_arc_ids.add(arc["id"])

                if node.place_kind:
                    if outgoing:
                        links.append({
                            "type": "placeToTransition", "sourceId": target.id, "targetId": other.id,
                            "quantity": quantity, "informational": informational,
                        })
                    else:
                        links.append({
                            "type": "transitionToPlace", "sourceId": other.id, "targetId": target.id,
                            "quantity": quantity, "informational": informational,
                        })
                else:
                    if outgoing:
                        links.append({
                            "type": "transitionToPlace", "sourceId": target.id, "targetId": other.id,
                            "quantity": quantity, "informational": informational,
                        })
                    else:
                        links.append({
                            "type": "placeToTransition", "sourceId": other.id, "targetId": target.id,
                            "quantity": quantity, "informational": informational,
                        })

    return links, linked_arc_ids


def _safe_index(rows: List[List[str]], obj_idx: Optional[int], el_idx: Optional[int]) -> Optional[str]:
    if obj_idx is None or not (0 <= obj_idx < len(rows)):
        return None
    row = rows[obj_idx]
    if el_idx is None or not (0 <= el_idx < len(row)):
        return None
    return row[el_idx]


def _int_attr_or(el: ET.Element, attr: str, default: int) -> Optional[int]:
    """Mirrors `Number(el["@_attr"] ?? default)` used as an array index:
    an absent attribute falls back to `default`; a present-but-unparseable
    or non-integer one becomes an invalid index (JS: NaN, which indexes an
    array to `undefined`) -- represented here as `None`, which
    `_safe_index` then treats as a lookup miss, exactly like JS."""
    raw = el.get(attr)
    if raw is None:
        return default
    n = _js_number(raw)
    if not math.isfinite(n) or not float(n).is_integer():
        return None
    return int(n)


def _declared_links(
    net: ET.Element,
    place_ids_by_page: List[List[str]],
    transition_ids_by_page: List[List[str]],
    registry: _IdRegistry,
    warn: WarnFn,
) -> List[dict]:
    """The net-level `<petriObjectLinks>` declaration, resolved to element ids."""
    places = {pid for row in place_ids_by_page for pid in row}
    transitions = {tid for row in transition_ids_by_page for tid in row}

    def kind_of(elid: str) -> Optional[str]:
        if elid in places:
            return "place"
        if elid in transitions:
            return "transition"
        return None

    ts = _find_toolspecific(net)
    links_container = _child(ts, "petriObjectLinks") if ts is not None else None
    raws = _children(links_container, "link") if links_container is not None else []

    links: List[dict] = []
    for raw in raws:
        link_type = _attr(raw, "type")
        source_object = _int_attr_or(raw, "sourceObject", -1)
        target_object = _int_attr_or(raw, "targetObject", -1)
        source_element = _int_attr_or(raw, "sourceElement", -1)
        target_element = _int_attr_or(raw, "targetElement", -1)

        has_source_id = raw.get("sourceElementId") is not None
        has_target_id = raw.get("targetElementId") is not None

        # The id-valued attributes are authoritative when present: they
        # survive a page whose slot order this reader and the writer might
        # count differently.
        if has_source_id:
            raw_source_id: Optional[str] = raw.get("sourceElementId")
        else:
            rows = transition_ids_by_page if link_type == "transitionToPlace" else place_ids_by_page
            raw_source_id = _safe_index(rows, source_object, source_element)
        if has_target_id:
            raw_target_id: Optional[str] = raw.get("targetElementId")
        else:
            rows = transition_ids_by_page if link_type == "placeToTransition" else place_ids_by_page
            raw_target_id = _safe_index(rows, target_object, target_element)

        if not raw_source_id or not raw_target_id:
            continue

        if has_source_id:
            resolved = registry.resolve(raw_source_id)
            source_id = resolved if resolved is not None else raw_source_id
        else:
            source_id = raw_source_id
        if has_target_id:
            resolved = registry.resolve(raw_target_id)
            target_id = resolved if resolved is not None else raw_target_id
        else:
            target_id = raw_target_id

        # A declaration whose endpoint is not the kind its type requires
        # does not describe a link this model can hold -- see
        # pnml-import.ts's own comment on why this is dropped rather than
        # kept broken.
        if kind_of(source_id) != _endpoint_kind(link_type, "source") or (
            kind_of(target_id) != _endpoint_kind(link_type, "target")
        ):
            continue

        quantity_raw = raw.get("quantity")
        quantity = _js_number(quantity_raw) if quantity_raw is not None else 1.0
        if not math.isfinite(quantity):
            quantity = 1.0
        elif quantity < 1:
            # Mirrors _parse_arc's inscription-weight clamp: a declared
            # quantity ComposedLink cannot hold (its own field is ge=1) is
            # still a legal-looking document value, not a parse failure,
            # so it gets an invalid-value warning naming the link rather
            # than exploding as a raw pydantic ValidationError deep inside
            # PetriNetSession.from_net_data.
            warn(
                "invalid-value",
                f'Declared link ("{link_type}" from "{source_id}" to "{target_id}") has quantity '
                f"{_maybe_int(quantity)}, which is not a valid quantity (a link quantity must be "
                "a positive integer); imported as 1.",
            )
            quantity = 1.0

        links.append({
            "type": link_type,
            "sourceId": source_id,
            "targetId": target_id,
            "quantity": _maybe_int(quantity),
            "informational": _attr(raw, "informational", "false") == "true",
        })
    return links


def _filter_place_fusion_links(
    links: List[dict],
    place_ids_by_page: List[List[str]],
    places: List[dict],
    warn: WarnFn,
) -> List[dict]:
    """Drop any placeFusion link -- structural or legacy-declared -- that
    breaks one of `ComposedModel.place_fusion_rejection`'s rules (desktop
    #62/port-spec section 2): the document still opens, but a link that
    fails is DROPPED and the reason reported alongside this module's other
    warnings, exactly like the desktop editor's own answer to a document
    it did not write.

    Runs over `links` already in DOCUMENT ORDER (structural links precede
    whatever `_merge_links` layers from the declaration, and within either
    source the order is the order each was read off the page/toolspecific
    block), so `accepted` at the point any one fusion link is checked is
    exactly "every fusion link stated earlier in the document" -- of a
    contradictory set, the first one stated is the one that stands, the
    same reading `ComposedModel.validate()` gives an already-built model.

    Both kinds of placeFusion link pass through here, but they can not
    actually break the same rules: a STRUCTURAL fusion (one `_structural_
    links` read off a `<referencePlace>`) can only ever break rule 5 (same
    object) -- see that function's own docstring for why its `resolve()`
    step, which always walks a reference chain through to a genuinely real
    place, leaves no way to construct the "copy of two masters" or "cycle
    of copies" shapes rules 2-4 refuse. A document's OLDER, position-
    addressed `<petriObjectLinks>` declarations have no such resolution
    step, so a hand-authored or foreign-tool document using them (no
    `<referencePlace>` anywhere -- see `_merge_links`'s `conformant` gate)
    can state any of the five violations directly; this is the one place
    either kind is caught, since both arrive here through the same list.
    """
    page_of: Dict[str, int] = {
        elid: page for page, ids in enumerate(place_ids_by_page) for elid in ids
    }
    name_of: Dict[str, str] = {p["id"]: p["name"] for p in places}

    def slot(elid: str) -> Tuple[int, str]:
        # -1 for an id this document never placed on any page (should not
        # happen: _declared_links already checked kind_of == "place" for
        # both sides of a placeFusion before it ever reaches here) --
        # never equal to a real page index, so it only ever prevents a
        # false "same object" match, never causes one.
        return page_of.get(elid, -1), elid

    accepted: List[Tuple[Tuple[int, str], Tuple[int, str]]] = []
    kept: List[dict] = []
    for link in links:
        if link["type"] != "placeFusion":
            kept.append(link)
            continue
        source_slot = slot(link["sourceId"])
        target_slot = slot(link["targetId"])
        reason = ComposedModel.place_fusion_rejection(accepted, source_slot, target_slot)
        if reason is not None:
            warn(
                "dropped-link",
                f"Dropped the link "
                f"{_describe('Place', link['targetId'], name_of.get(link['targetId'], ''))} = "
                f"{_describe('Place', link['sourceId'], name_of.get(link['sourceId'], ''))}: {reason}",
            )
            continue
        accepted.append((source_slot, target_slot))
        kept.append(link)
    return kept


def _merge_links(structural: List[dict], declared: List[dict], conformant: bool) -> List[dict]:
    """Settles what the model's links are when both sources speak,
    following PnmlModelParser.mergeDeclaredLinks -- see pnml-import.ts's
    own docstring for the fusion/arc-like distinction."""
    if not conformant:
        return declared

    merged = list(structural)
    seen = {_endpoint_key(link) for link in structural}
    for link in declared:
        if link["type"] == "placeFusion":
            continue
        key = _endpoint_key(link)
        if key in seen:
            continue
        seen.add(key)
        merged.append(link)
    return merged


# ---------------------------------------------------------------------------
# Composed-document nesting.
# ---------------------------------------------------------------------------


def _restore_nesting(
    objects: List[dict], frame_by_page: List[Optional[dict]], parent_index_by_page: List[Optional[int]],
) -> None:
    """Restores the nest the page structure states -- see pnml-import.ts's
    own docstring: a value that names no frame, or the frame itself,
    leaves the frame top-level; so does a chain that loops."""
    for index, frame in enumerate(frame_by_page):
        parent_index = parent_index_by_page[index]
        if frame is None or parent_index is None:
            continue
        parent = frame_by_page[parent_index]
        if parent is None or parent is frame:
            continue
        frame["objectId"] = parent["id"]

    by_id = {o["id"]: o for o in objects}
    for frame in objects:
        current = by_id.get(frame.get("objectId", ""))
        depth = 0
        while current is not None and depth <= len(objects):
            if current["id"] == frame["id"]:
                frame.pop("objectId", None)
                break
            current = by_id.get(current.get("objectId", ""))
            depth += 1


# ---------------------------------------------------------------------------
# Composed-document parsing: two passes across every page (id registration,
# then real parsing), mirroring pnml-import.ts's parseComposedPnml exactly.
# ---------------------------------------------------------------------------


def _parse_composed_pnml(net: ET.Element, name: str, registry: _IdRegistry, warn: WarnFn) -> dict:
    all_pages, enclosing = _collect_pages(net)
    # Which object is inside which is the page structure, and only that;
    # the older tool-specific parentObject attribute is neither written
    # nor read any more.
    pages = _order_pages_by_index(all_pages, nested=len(enclosing) > 0)
    conformant = _contains_element_deep(net, {"referencePlace", "referenceTransition"})

    objects: List[dict] = []
    places: List[dict] = []
    transitions: List[dict] = []

    place_ids_by_page: List[List[str]] = []
    transition_ids_by_page: List[List[str]] = []
    frame_by_page: List[Optional[dict]] = []
    parent_index_by_page: List[Optional[int]] = []
    representatives: Set[str] = set()
    nodes: Dict[str, _DocNode] = {}
    reference_nodes_by_page: List[List[_DocNode]] = []
    arcs_by_page: List[List[dict]] = []
    arc_raw_by_page: List[List[ET.Element]] = []

    # Pass 1: register every id-bearing element of every page, across the
    # whole document, before parsing touches any of them -- an arc's
    # source/target has to resolve against the COMPLETED registry, since it
    # can sit on an earlier page than the element it names.
    for index, page in enumerate(pages):
        marker = _petri_object_marker(page)
        gx = _num_attr(marker, "x", 0)
        gy = _num_attr(marker, "y", 0)
        gw = _num_attr(marker, "width", 0)
        gh = _num_attr(marker, "height", 0)
        free = gx == 0 and gy == 0 and gw == 0 and gh == 0
        if not free:
            raw_frame_id = _attr(page, "id", f"object{index}")
            marker_name = _attr(marker, "name") if marker is not None else ""
            visible_name = marker_name or _text_of(_child(page, "name"))
            registry.assign("Page", raw_frame_id, visible_name, page)
        for raw in _children(page, "place"):
            registry.assign("Place", _attr(raw, "id"), _text_of(_child(raw, "name")), raw)
        for raw in _children(page, "referencePlace"):
            registry.assign("Reference place", _attr(raw, "id"), _text_of(_child(raw, "name")), raw)
        for raw in _children(page, "referenceTransition"):
            registry.assign("Reference transition", _attr(raw, "id"), _text_of(_child(raw, "name")), raw)
        for raw in _children(page, "transition"):
            registry.assign("Transition", _attr(raw, "id"), _text_of(_child(raw, "name")), raw)
        for raw in _children(page, "arc"):
            registry.assign("Arc", _attr(raw, "id"), "", raw)

    # Pass 2: parse every page for real. Every registry.assign call below
    # passes the same raw node pass 1 already registered it under, so each
    # one is a cache hit rather than a second registration.
    for index, page in enumerate(pages):
        marker = _petri_object_marker(page)
        gx = _num_attr(marker, "x", 0)
        gy = _num_attr(marker, "y", 0)
        gw = _num_attr(marker, "width", 0)
        gh = _num_attr(marker, "height", 0)
        free = gx == 0 and gy == 0 and gw == 0 and gh == 0

        frame: Optional[dict] = None
        if not free:
            raw_frame_id = _attr(page, "id", f"object{index}")
            marker_name = _attr(marker, "name") if marker is not None else ""
            visible_name = marker_name or _text_of(_child(page, "name"))
            frame_id = registry.assign("Page", raw_frame_id, visible_name, page)
            frame = {
                "id": frame_id,
                "name": visible_name or f"Object {index + 1}",
                "priority": _maybe_int(_num_attr(marker, "priority", 0)),
                "graphics": {"x": gx, "y": gy, "width": gw, "height": gh},
            }
            if marker is not None and _attr(marker, "collapsed") == "true":
                frame["collapsed"] = True
            # Written only by this app; the desktop ignores the attribute silently.
            if marker is not None and _attr(marker, "autoFit") == "false":
                frame["autoFit"] = False
            objects.append(frame)
        frame_by_page.append(frame)

        enclosing_page = enclosing.get(page)
        nested_index = (
            _num_attr(_petri_object_marker(enclosing_page), "index", -1)
            if enclosing_page is not None else -1
        )
        parent_index_by_page.append(int(nested_index) if nested_index >= 0 else None)

        touched_by_arcs: Set[str] = set()
        for raw in _children(page, "arc"):
            touched_by_arcs.add(_attr(raw, "source"))
            touched_by_arcs.add(_attr(raw, "target"))

        page_reference_nodes: List[_DocNode] = []

        def register(node: _DocNode) -> None:
            if node.id not in nodes:
                nodes[node.id] = node

        page_place_ids: List[str] = []
        for raw in _children(page, "place"):
            place = _parse_place(raw, registry, warn)
            if frame is not None:
                place["objectId"] = frame["id"]
            places.append(place)
            page_place_ids.append(place["id"])
            register(_DocNode(
                id=place["id"], page=index, place_kind=True, reference=False, fusion=False,
                ref="", name=place["name"],
            ))

        for raw in _children(page, "referencePlace"):
            raw_id = _attr(raw, "id")
            visible_name = _text_of(_child(raw, "name"))
            node_id = registry.assign("Reference place", raw_id, visible_name, raw)
            node = _DocNode(
                id=node_id, page=index, place_kind=True, reference=True,
                fusion=_is_fusion_reference(raw, touched_by_arcs),
                ref=_attr(raw, "ref"), name=visible_name or node_id,
            )
            register(node)
            page_reference_nodes.append(node)
            if not node.fusion:
                representatives.add(node_id)
                continue
            # The same XML element is both the reference node above and,
            # here, the real place it stands in for; it gets one id,
            # assigned once, above.
            restored = _parse_place(raw, registry, warn, id_override=node_id)
            if frame is not None:
                restored["objectId"] = frame["id"]
            fused_marking_text = _text_of(_toolspecific_child(raw, "fusedInitialMarking"))
            if fused_marking_text != "":
                fused_tokens_n = _js_number(fused_marking_text)
                if math.isfinite(fused_tokens_n):
                    restored["tokens"] = _maybe_int(fused_tokens_n)
                else:
                    # Malformed, not merely absent: keep the marking
                    # _parse_place already validated rather than letting a
                    # NaN through silently.
                    warn(
                        "bad-number",
                        f'{_describe("Place", restored["id"], restored["name"])} has a malformed '
                        f'fused initial marking "{fused_marking_text}"; imported with '
                        f'{restored["tokens"]} tokens.',
                    )
            places.append(restored)
            page_place_ids.append(restored["id"])

        # There is no transition-fusion link, so a reference transition
        # can only ever be a stand-in.
        for raw in _children(page, "referenceTransition"):
            raw_id = _attr(raw, "id")
            visible_name = _text_of(_child(raw, "name"))
            node_id = registry.assign("Reference transition", raw_id, visible_name, raw)
            node = _DocNode(
                id=node_id, page=index, place_kind=False, reference=True, fusion=False,
                ref=_attr(raw, "ref"), name=visible_name or node_id,
            )
            register(node)
            page_reference_nodes.append(node)
            representatives.add(node_id)

        page_transition_ids: List[str] = []
        for raw in _children(page, "transition"):
            transition = _parse_transition(raw, registry, warn)
            if frame is not None:
                transition["objectId"] = frame["id"]
            transitions.append(transition)
            page_transition_ids.append(transition["id"])
            register(_DocNode(
                id=transition["id"], page=index, place_kind=False, reference=False, fusion=False,
                ref="", name=transition["name"],
            ))

        # Parsed once, up front: whether an arc ends up a model arc, a
        # link's own realisation, or a warning-and-drop is decided below,
        # once every page's nodes and reference chains are known.
        raw_arcs = _children(page, "arc")
        parsed_arcs = [_parse_arc(raw, registry, warn) for raw in raw_arcs]
        arcs_by_page.append(parsed_arcs)
        arc_raw_by_page.append(raw_arcs)

        place_ids_by_page.append(page_place_ids)
        transition_ids_by_page.append(page_transition_ids)
        reference_nodes_by_page.append(page_reference_nodes)

    _restore_nesting(objects, frame_by_page, parent_index_by_page)

    if conformant:
        structural_links, linked_arc_ids = _structural_links(
            pages, reference_nodes_by_page, arcs_by_page, arc_raw_by_page, nodes, registry, warn,
        )
    else:
        structural_links, linked_arc_ids = [], set()

    # Every arc is already parsed above; this decides its fate now that
    # linked_arc_ids (the arcs a structural link actually realises) is
    # known: an arc that realises a link vanishes on purpose; one that
    # touches a representative whose reference chain never resolved
    # vanishes too, but with a warning naming it; anything else is a model
    # arc, possibly one that quietly crosses a page boundary no reference
    # node accounts for, which is also worth a warning.
    arcs: List[dict] = []
    for index, _page in enumerate(pages):
        for arc in arcs_by_page[index]:
            if arc["id"] in linked_arc_ids:
                continue
            if arc["source_id"] in representatives or arc["target_id"] in representatives:
                warn(
                    "dangling-ref",
                    f'{_describe("Arc", arc["id"], "")} touches an unresolved reference node and '
                    "was skipped.",
                )
                continue
            source_node = nodes.get(arc["source_id"])
            target_node = nodes.get(arc["target_id"])
            if source_node is not None and target_node is not None and source_node.page != target_node.page:
                warn(
                    "cross-page-arc",
                    f'{_describe("Arc", arc["id"], "")} connects elements on different pages, '
                    "which the PNML same-page rule for arcs forbids; imported anyway.",
                )
            arcs.append(arc)

    declared = _declared_links(net, place_ids_by_page, transition_ids_by_page, registry, warn)
    merged = _merge_links(structural_links, declared, conformant)
    merged = _filter_place_fusion_links(merged, place_ids_by_page, places, warn)
    links = [{"id": f"link_{i}", **draft} for i, draft in enumerate(merged)]

    return {
        "name": name,
        "places": places,
        "transitions": transitions,
        "arcs": arcs,
        "objects": objects,
        "links": links,
    }


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


def _is_falsy_pnml_root(root: ET.Element) -> bool:
    """Whether *root* is the degenerate `<pnml/>` shape the frontend's own
    `if (!pnml) throw ...` treats as NO root at all, even though this
    reader's own tag match already accepted it.

    fast-xml-parser hands the frontend `doc.pnml`, and for a `<pnml>`
    element with no attribute, no child element and no (non-whitespace)
    text between its tags, that value is the empty string "" -- falsy --
    rather than the object every other shape produces (and every object
    is truthy in JS, even `{}`). `xml.etree` has no such notion; this is
    the same test run by hand against the one thing that makes the two
    parsers agree here: whether there is anything at all on or under this
    element.

    A namespace on the tag itself (`root.tag`'s `{...}` prefix) stands in
    for an `xmlns` attribute the source document declared: fast-xml-parser
    (`ignoreAttributes: false`) reads that as a real `@_xmlns` attribute
    and a truthy object, while `xml.etree` consumes it into the tag's own
    namespace and never lists it in `.attrib` at all -- checking the tag's
    namespace here is what keeps a namespaced-but-otherwise-empty
    `<pnml xmlns="...">` (this reader's own existing "missing <net>" test)
    from being misread as this bare case instead.
    """
    ns, _ = _tag_info(root.tag)
    if ns:
        return False
    if root.attrib:
        return False
    if list(root):
        return False
    return not (root.text or "").strip()


def parse_pnml(xml_text: str) -> Tuple[dict, List[dict]]:
    """Parses a PNML document into a (net_data, warnings) pair.

    `net_data` is the frontend-shape dict `composed_convert.py` already
    reads and writes; `warnings` is a list of `{"code": ..., "message":
    ...}` dicts. Raises `ValueError`, with the frontend reader's own exact
    text, for the two structural failures a document cannot be soft-fixed
    out of: no `<pnml>` root, or a `<pnml>` with no `<net>`.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid PNML: not well-formed XML ({exc})") from exc

    if not _matches(root, "pnml") or _is_falsy_pnml_root(root):
        raise ValueError("Invalid PNML: missing <pnml> root element")

    net_nodes = _children(root, "net")
    if not net_nodes:
        raise ValueError("Invalid PNML: missing <net> element")
    net = net_nodes[0]

    name = _text_of(_child(net, "name")) or "Imported net"

    warnings: List[dict] = []

    def warn(code: str, message: str) -> None:
        warnings.append({"code": code, "message": message})

    registry = _IdRegistry(warn)

    # The net's own id is never stored anywhere in the model, so an
    # invalid one only gets a warning: there is no wire reference to it
    # that would need remapping.
    raw_net_id = net.get("id")
    if raw_net_id and not is_ncname(raw_net_id):
        warn(
            "invalid-id",
            f'The net\'s own id "{raw_net_id}" is not a valid XML id. It is not stored in the '
            "model, so nothing was renamed.",
        )

    if _is_composed_document(net):
        data = _parse_composed_pnml(net, name, registry, warn)
        return data, warnings

    # Support both flat <net> and page-wrapped <net><page> layouts.
    page_nodes = _children(net, "page")
    container = page_nodes[0] if page_nodes else net

    places = [_parse_place(p, registry, warn) for p in _children(container, "place")]
    transitions = [_parse_transition(t, registry, warn) for t in _children(container, "transition")]
    arcs = [_parse_arc(a, registry, warn) for a in _children(container, "arc")]

    return {"name": name, "places": places, "transitions": transitions, "arcs": arcs}, warnings
