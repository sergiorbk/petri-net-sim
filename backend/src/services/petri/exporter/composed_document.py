"""View model for ISO/IEC 15909-2 conformant composed PNML export.

`composed.pnml.j2` used to receive a raw `ComposedModel` and lay out each page
itself. That stopped working once a page could hold reference nodes: deciding
which member of a fusion group survives, and which reference node a page
already has, needs real control flow and a debugger rather than Jinja's
`{% for %}`. Getting either wrong silently retargets a link, which is the
class of bug this whole conformance effort exists to design out.

So the resolution happens once, here, and the template only walks the ordered
tree it produces.

Two rules carry most of the weight, and both are documented at the function
that implements them:
  * a fusion is resolved per GROUP, never per link, so a reference node can
    never point at another reference node (`_elect_shared_places`);
  * element ids are written verbatim unless two objects share one, in which
    case the whole document is renamed and the run is translated back
    (`build_final_id_map`, and `_own_id_map` in remote_v2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Union

from src.domain.composed import (
    PLACE_TO_TRANSITION_RETIRED_REASON,
    ComposedLink,
    ComposedModel,
    LinkType,
)
from src.domain.composed.model_object import ModelObject
from src.domain.models import Arc, Place, Transition

#: The smallest frame the canvas will draw, mirroring FRAME_MIN_W/FRAME_MIN_H in
#: frontend/src/lib/petri-geometry.ts. A written frame is never smaller, so the
#: all-default marker can only ever mean the free-elements bucket.
FRAME_MIN_W = 160.0
FRAME_MIN_H = 100.0

_log = logging.getLogger(__name__)


@dataclass
class RealPlace:
    """A place slot occupied by an ordinary, unmodified `<place>`."""

    place: Place
    id: str
    slot_kind: str = field(default="place", init=False)


@dataclass
class FusionRef:
    """A place slot occupied by a `<referencePlace>` instead of a `<place>`.

    Every member of a fusion group except the surviving one becomes this.
    It stands at the exact ordinal the fused-away place would have had, so
    `sourceElement` indices elsewhere keep meaning "the N-th place slot in
    document order" exactly as they did before this projection existed.

    It keeps the original place's own id, name and coordinates: the `<place>`
    is never emitted, so the id is free for the reference node to take, and the
    node still draws where that place used to be.

    Where the marking really lives is said in an XML comment rather than in the
    name. It has to be said somewhere, since a page read on its own gives no
    hint, but the name belongs to the user: fold the provenance into it and
    saving then reopening the file renames their place.
    """

    id: str
    ref: str
    name: str
    x: float
    y: float
    fused_marking: int
    tag: str | None = None
    shared_with: str = ""
    slot_kind: str = field(default="fusion", init=False)


PlaceSlot = Union[RealPlace, FusionRef]


@dataclass
class TransitionSlot:
    transition: Transition
    id: str


@dataclass
class RepresentativeRef:
    """A reference node added to a page purely to hang a link arc off of,
    the transitionToPlace projection (§4). Never a slot:
    it does not replace anything the object already had, so it consumes no
    ordinal and never carries `<initialMarking>`/`<fusedInitialMarking>`.

    Name and coordinates mirror the TARGET element's own, a reasonable,
    deterministic default for a node a drawing tool has to place somewhere it
    wasn't asked to place it. Which object that element really belongs to is
    said in an XML comment, where it cannot be mistaken for the name.
    """

    id: str
    ref: str
    name: str
    x: float
    y: float
    target_kind: str  # "place" | "transition", which reference tag to emit
    stands_for: str = ""


@dataclass
class OwnArc:
    """One of the object's own arcs, both endpoints local to this page."""

    arc: Arc
    id: str
    source_id: str
    target_id: str


@dataclass
class LinkArc:
    """The arc realising a transitionToPlace link (§4), from the source's own
    transition to the representative node standing for the target place.
    `id` is `larc_{index}`, the link's own position in the model's `links`
    list, so it is stable across re-export.

    `informational` is always False here: it is only meaningful for
    placeToTransition (see ComposedLink's own docstring), and that link type
    never reaches this dataclass, `build_document_model` refuses a model
    that has one before any link is resolved. The field stays so
    `link_arc()` in _element_macros.pnml.j2 need not special-case a shape
    this exporter no longer produces."""

    id: str
    source_id: str
    target_id: str
    weight: int
    informational: bool


@dataclass
class ObjectDoc:
    index: int
    name: str
    priority: int
    x: float
    y: float
    template_method: str | None
    template_arguments: List[str]
    # Web-editor object-canvas frame state (§ new attributes on <petriObject>).
    # Already resolved to exactly what the template should write: None/False
    # means "omit the attribute", never a raw pass-through of the request
    # value, so composed.pnml.j2 only ever has to check presence (see
    # _build_object_doc for the resolution, including the `free` override).
    width: float | None = None
    height: float | None = None
    collapsed: bool = False
    parent: int | None = None
    auto_fit: bool | None = None
    place_slots: List[PlaceSlot] = field(default_factory=list)
    transitions: List[TransitionSlot] = field(default_factory=list)
    representatives: List[RepresentativeRef] = field(default_factory=list)
    own_arcs: List[OwnArc] = field(default_factory=list)
    link_arcs: List[LinkArc] = field(default_factory=list)
    #: The objects nested inside this one, in index order. The document states
    #: the nest by putting their pages inside this object's page, which is how
    #: ISO/IEC 15909-2 states a page hierarchy and the only form of it a reader
    #: outside this family can see, so `parent` is not written as an attribute.
    children: List["ObjectDoc"] = field(default_factory=list)


@dataclass
class ResolvedLink:
    """A `ComposedLink` as `<petriObjectLinks>` declares it, with id-valued
    endpoints alongside the index-valued ones.

    The target is the one the document's structure names, which is not always
    the one the link was written with: if the target place has been fused away,
    the structure names the place that survived instead. Declaring the original
    would give a reader two links where there is one, and it would deliver its
    tokens twice, since it has no way to see that the two describe the same
    flow.
    """

    link: ComposedLink
    source_element_id: str
    target_element_id: str
    target_object: int
    target_element: int


@dataclass
class ComposedDocument:
    name: str
    objects: List[ObjectDoc]
    links: List[ResolvedLink]
    #: The objects whose pages sit directly under `<net>`: the top level of the
    #: nest, plus anything whose stated parent is not in this document, which is
    #: written there rather than dropped.
    root_objects: List[ObjectDoc] = field(default_factory=list)


def build_document_model(model: ComposedModel) -> ComposedDocument:
    """Resolve a `ComposedModel` into the page-by-page tree `composed.pnml.j2`
    renders directly. Raises `ValueError` on any input the conformant
    projection cannot express (§4/§8 of the spec) rather than emit a
    document that looks fine and lies.
    """
    if not model.objects:
        raise ValueError("Composed model has no objects to export")

    for obj in model.objects:
        _check_no_duplicate_ids(obj)

    for index, link in enumerate(model.links):
        if link.type == LinkType.PLACE_TO_TRANSITION:
            # PetriObjModelPaint retired this link type (see ComposedModel.
            # validate(), which already refuses one for any request that goes
            # through it). This is a backstop for a model that reached the
            # exporter some other way: the projection this export used to
            # write for it (a representative reference node plus an
            # informational link arc) is gone from both composed.pnml.j2 and
            # the frontend's mirror exporter, so there is nothing left here
            # that could express one.
            raise ValueError(f"Link {index} is a {PLACE_TO_TRANSITION_RETIRED_REASON}")
        if link.source_object == link.target_object:
            raise ValueError(
                f"Link connects object {link.source_object} to itself "
                "(source_object == target_object), not expressible in PNML, "
                "every link must cross objects"
            )
        if link.quantity < 1:
            raise ValueError(f"Link quantity must be >= 1, got {link.quantity}")

    final_id = build_final_id_map(model)
    shared_place = _elect_shared_places(model)

    objects_doc = [
        _build_object_doc(model, obj, shared_place, final_id) for obj in model.objects
    ]
    resolved_links = [
        _resolve_link(model, link, shared_place, final_id) for link in model.links
    ]

    by_index = {obj.index: obj for obj in objects_doc}
    roots: List[ObjectDoc] = []
    for obj in objects_doc:
        parent = by_index.get(obj.parent) if obj.parent is not None else None
        if parent is None or parent is obj:
            roots.append(obj)
        else:
            parent.children.append(obj)

    return ComposedDocument(
        name=model.name,
        objects=objects_doc,
        links=resolved_links,
        root_objects=roots,
    )


def _elect_shared_places(model: ComposedModel) -> Dict[Tuple[int, int], Tuple[int, int]]:
    """Reduce the placeFusion links to one shared place per fusion group.

    A fusion is an identity, not a connection: the places of a group are one
    place, so exactly one of them is emitted as a real `<place>` and every
    other member becomes a `<referencePlace>` pointing straight at it. Doing
    this per GROUP rather than per LINK is what keeps the document acyclic and
    chain-free by construction, project each link on its own and
    `A.p -> B.q, B.q -> C.r` yields a reference that points at a reference,
    which the standard does not allow and a reader can only guess at, while
    `A.p -> B.q, B.q -> A.p` yields a cycle outright.

    Which member survives is not a free choice: it is whichever one
    `PetriObjModel.wire()` would leave standing, so the document and the engine
    agree about whose initial marking the shared place has. wire() assigns
    `sourcePlaces[source] = <the target's PetriP>`, so each link makes the
    target's side the survivor, a union-find whose union always points the
    source's root at the target's root reproduces that exactly, including for
    chains and for links that merely restate a group that already exists.

    A fan (desktop #61: one master, N copies pointing at it) is not a special
    case here, it falls out of the general rule: `ComposedModel.validate()`'s
    `place_fusion_rejection` (`domain/composed/model.py`) already guarantees,
    for any model that reaches this function, that every place is the SOURCE
    (the copy) of at most one link and that no cycle exists. That makes every
    fusion component a TREE whose edges all point one way, copy -> master, so
    each component has exactly one node with no outgoing edge (the master,
    which every union below roots at), and it is always that master the
    union-find elects, whether the group has one copy or a hundred sharing it.
    The union-find itself does not need to know any of this; it is correct by
    construction for any input, this docstring just names why the fan case in
    particular can never surprise it.

    :return: (object index, place index) -> the surviving slot, for every member
        that is NOT itself the survivor. A slot absent from the map is emitted
        as an ordinary place.
    """
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {}

    def find(slot: Tuple[int, int]) -> Tuple[int, int]:
        parent.setdefault(slot, slot)
        while parent[slot] != slot:
            parent[slot] = parent[parent[slot]]
            slot = parent[slot]
        return slot

    for link in model.links:
        if link.type != LinkType.PLACE_FUSION:
            continue
        source_root = find((link.source_object, link.source_element))
        target_root = find((link.target_object, link.target_element))
        if source_root != target_root:
            parent[source_root] = target_root

    shared: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for slot in list(parent):
        survivor = find(slot)
        if survivor != slot:
            shared[slot] = survivor
    return shared


def _check_no_duplicate_ids(obj: ModelObject) -> None:
    """A duplicate id within one object is broken input, PetriNet's own
    `add_place`/`add_transition` never produce one, but a net built by
    direct construction from untrusted JSON (as `simulate_composed.py`
    does with `PetriNet(**net_data)`) bypasses that guard."""
    seen: set[str] = set()
    all_ids = (
        [p.id for p in obj.net.places]
        + [t.id for t in obj.net.transitions]
        + [a.id for a in obj.net.arcs]
    )
    for el_id in all_ids:
        if el_id in seen:
            raise ValueError(
                f"Object {obj.index} ('{obj.name}') has a duplicate element id "
                f"'{el_id}', cannot export"
            )
        seen.add(el_id)


def build_final_id_map(model: ComposedModel) -> Dict[Tuple[int, str], str]:
    """(object index, own id) -> the id actually written to the document.

    A PNML id is document-scoped, but two objects built from the same template
    carry the same element ids: `PetriNet`'s own generator restarts at "p1",
    "t1", "arc1" in every net, so instantiating one library object twice, or
    naming the same session twice, collides by construction. That is not an
    exotic input, it is the ordinary API case, so a colliding document is
    renamed rather than refused.

    Renaming is whole-document and all-or-nothing, and only happens when some
    id really is shared: a canvas, whose ids are unique to begin with, is
    written exactly as given. That keeps the common case byte-stable and keeps
    a reader from having to work out which convention a given id follows.

    The caller must not see the renaming. A simulation reports its markings
    keyed by document ids, so `remote_v2` translates them back through the
    inverse of this map before anything downstream sees them. Note that a
    collision corrupts those markings *today*, before any of this: two places
    both called "p1" occupy one key in petri-server's map and overwrite each
    other, silently.
    """
    seen: set[str] = set()
    namespace = False
    for obj in model.objects:
        own = (
            {p.id for p in obj.net.places}
            | {t.id for t in obj.net.transitions}
            | {a.id for a in obj.net.arcs}
        )
        if seen & own:
            namespace = True
            break
        seen |= own

    final_id: Dict[Tuple[int, str], str] = {}
    for obj in model.objects:
        for element in list(obj.net.places) + list(obj.net.transitions) + list(obj.net.arcs):
            final_id[(obj.index, element.id)] = (
                f"o{obj.index}_{element.id}" if namespace else element.id
            )
    return final_id


def _resolve_frame_attributes(
    obj: ModelObject,
) -> Tuple[float, float, float | None, float | None, bool, int | None, bool | None]:
    """Resolve one object's `<petriObject>` position/frame attributes.

    Mirrors the frontend exporter's emission rules exactly, so the two
    writers produce the same optional-attribute set for the same request:
      * width/height are always written, together, and never smaller than
        the smallest box the canvas will draw. A real object that stated no
        size used to get neither, which wrote the very marker that means
        "the free-elements bucket": reopening the file read the object as
        that bucket, and the frame with every membership in it was gone.
      * collapsed="true" is written only when true, never "false".
      * the object's parent is not an attribute at all: the document states
        the hierarchy by writing a nested object's page inside its parent's,
        which is how ISO/IEC 15909-2 states a page hierarchy. `parent` is
        kept here because that is what the template builds the page tree
        from.
      * autoFit="false" is written only when the frame was hand-resized
        (`auto_fit is False`); auto_fit True/None both mean "leave it out",
        the desktop writer has no such concept and never sets True.

    `free` (an object the frontend has not placed on the canvas yet)
    overrides all of the above: the marker is still emitted, but at x=0
    y=0 with none of the optional attributes, regardless of whatever the
    request also carried for them.
    """
    if obj.free:
        return 0.0, 0.0, None, None, False, None, None

    width = max(obj.width or 0.0, FRAME_MIN_W)
    height = max(obj.height or 0.0, FRAME_MIN_H)

    return obj.x, obj.y, width, height, obj.collapsed, obj.parent, obj.auto_fit


def _build_object_doc(
    model: ComposedModel,
    obj: ModelObject,
    shared_place: Dict[Tuple[int, int], Tuple[int, int]],
    final_id: Dict[Tuple[int, str], str],
) -> ObjectDoc:
    x, y, width, height, collapsed, parent, auto_fit = _resolve_frame_attributes(obj)
    doc = ObjectDoc(
        index=obj.index,
        name=obj.name,
        priority=obj.priority,
        x=x,
        y=y,
        width=width,
        height=height,
        collapsed=collapsed,
        parent=parent,
        auto_fit=auto_fit,
        template_method=obj.template_method,
        template_arguments=list(obj.template_arguments),
    )

    for j, place in enumerate(obj.net.places):
        survivor_slot = shared_place.get((obj.index, j))
        if survivor_slot is None:
            doc.place_slots.append(RealPlace(place=place, id=final_id[(obj.index, place.id)]))
            continue
        survivor_id = _slot_id(model, survivor_slot, final_id)
        if place.tokens > 0:
            _log.warning(
                "Object %d ('%s') place '%s' has %d token(s) but is fused into '%s', "
                "whose own marking is the shared one, the tokens are dropped from the "
                "standard projection and kept as <fusedInitialMarking> for drawings",
                obj.index, obj.name, place.name, place.tokens, survivor_id,
            )
        doc.place_slots.append(FusionRef(
            id=final_id[(obj.index, place.id)],
            ref=survivor_id,
            name=place.name,
            shared_with=survivor_id,
            x=place.graphics.x,
            y=place.graphics.y,
            fused_marking=place.tokens,
            tag=place.tag,
        ))

    for t in obj.net.transitions:
        doc.transitions.append(TransitionSlot(transition=t, id=final_id[(obj.index, t.id)]))

    # Representatives: transitionToPlace links whose SOURCE is this object
    # gain a stand-in for the TARGET element, added
    # in link order and deduplicated per (this object, target element),
    # two links from the same object into the same far-end element need
    # only one node to hang arcs off of (§2's dedup rule).
    seen_targets: set[str] = set()
    for link in model.links:
        if link.source_object != obj.index or link.type == LinkType.PLACE_FUSION:
            continue
        target_raw_id, target_kind = model.resolve_link_endpoint(link, "target")
        target_id = _link_target_id(model, link, shared_place, final_id)
        if target_id in seen_targets:
            continue
        seen_targets.add(target_id)
        target_obj = model.get_object(link.target_object)
        target_el = (
            target_obj.net.get_place(target_raw_id)
            if target_kind == "place"
            else target_obj.net.get_transition(target_raw_id)
        )
        doc.representatives.append(RepresentativeRef(
            id=f"ref_object{obj.index}_{target_id}",
            ref=target_id,
            # The node is ours, not the user's, and it draws in a page whose
            # canvas has no such element, so the name says whose it really is.
            name=target_el.name,
            stands_for=f"{target_el.name} in {target_obj.name}",
            x=target_el.graphics.x,
            y=target_el.graphics.y,
            target_kind=target_kind,
        ))

    for a in obj.net.arcs:
        doc.own_arcs.append(OwnArc(
            arc=a,
            id=final_id[(obj.index, a.id)],
            source_id=final_id[(obj.index, a.source_id)],
            target_id=final_id[(obj.index, a.target_id)],
        ))

    for idx, link in enumerate(model.links):
        if link.source_object != obj.index or link.type == LinkType.PLACE_FUSION:
            continue
        source_raw_id, _kind = model.resolve_link_endpoint(link, "source")
        target_id = _link_target_id(model, link, shared_place, final_id)
        doc.link_arcs.append(LinkArc(
            id=f"larc_{idx}",
            source_id=final_id[(obj.index, source_raw_id)],
            target_id=f"ref_object{obj.index}_{target_id}",
            weight=link.quantity,
            informational=link.informational,
        ))

    return doc


def _slot_id(
    model: ComposedModel, slot: Tuple[int, int], final_id: Dict[Tuple[int, str], str]
) -> str:
    """The document id of the place occupying a given (object, place index)."""
    obj = model.get_object(slot[0])
    return final_id[(slot[0], obj.net.places[slot[1]].id)]


def _link_target_slot(
    model: ComposedModel,
    link: ComposedLink,
    shared_place: Dict[Tuple[int, int], Tuple[int, int]],
) -> Tuple[int, int] | None:
    """Where this link's target really lives once fusion has been applied.

    Not always where the link says: if the target place has been fused away, the
    place that survives is the one the document must name. Pointing a reference
    node at the fused-away place instead would make one reference refer to
    another, which the standard does not allow and which leaves a reader
    following a chain to an object the link never mentioned.

    :return: the surviving slot, or None when the target is a transition, which
        fusion never touches.
    """
    raw_id, kind = model.resolve_link_endpoint(link, "target")
    if kind != "place":
        return None
    target_obj = model.get_object(link.target_object)
    for index, place in enumerate(target_obj.net.places):
        if place.id == raw_id:
            return shared_place.get((link.target_object, index), (link.target_object, index))
    return None


def _link_target_id(
    model: ComposedModel,
    link: ComposedLink,
    shared_place: Dict[Tuple[int, int], Tuple[int, int]],
    final_id: Dict[Tuple[int, str], str],
) -> str:
    """The id a reference node standing for this link's target must point at."""
    slot = _link_target_slot(model, link, shared_place)
    if slot is not None:
        return _slot_id(model, slot, final_id)
    raw_id, _kind = model.resolve_link_endpoint(link, "target")
    return final_id[(link.target_object, raw_id)]


def _resolve_link(
    model: ComposedModel,
    link: ComposedLink,
    shared_place: Dict[Tuple[int, int], Tuple[int, int]],
    final_id: Dict[Tuple[int, str], str],
) -> ResolvedLink:
    source_raw_id, _ = model.resolve_link_endpoint(link, "source")
    slot = _link_target_slot(model, link, shared_place)
    if slot is None:
        target_raw_id, _ = model.resolve_link_endpoint(link, "target")
        slot = (link.target_object, link.target_element)
        target_id = final_id[(link.target_object, target_raw_id)]
    else:
        target_id = _slot_id(model, slot, final_id)
    return ResolvedLink(
        link=link,
        source_element_id=final_id[(link.source_object, source_raw_id)],
        target_element_id=target_id,
        target_object=slot[0],
        target_element=slot[1],
    )
