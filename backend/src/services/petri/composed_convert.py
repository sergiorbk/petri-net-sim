"""Converter pair: frontend-shape net_data dict <-> domain ComposedModel.

The frontend shape (types mirrored from frontend/src/types/petri.ts) is one
flat document: `places`/`transitions`/`arcs` arrays plus optional `objects`
(ObjectFrame[]) and `links` (ObjectLink[]). A place/transition carries an
`objectId` string when it is framed inside an object; an ObjectLink addresses
its two endpoints by element id (`sourceId`/`targetId`), because ids are
unique across the WHOLE document regardless of framing (the frontend's own
`nextId` scans the flat arrays, never resets per object).

`ComposedModel` (src/domain/composed) is the opposite shape: several
independent `PetriNet`s (`ModelObject.net`), each with its OWN id namespace,
wired together by `ComposedLink`s that address an endpoint by POSITION
(object index, then the element's position in that object's own
places[]/transitions[] array) rather than by id. This is deliberate on the
domain side (see model.py's docstring) but means this converter has to
resolve every id-addressed frontend link into a position-addressed one, and
back.

This module mirrors the PARTITIONING semantics of
`frontend/src/lib/composed-simulation-client.ts`'s `partitionIntoObjects` /
`buildComposedRequest`: an element belongs to the object named by its
`objectId`, or to the implicit free pool when `objectId` is absent. It
deliberately does NOT mirror that file's exact object ORDERING or its
"drop empty objects" default: `buildComposedRequest` optimizes for a
throwaway simulation request, this module optimizes for a stable,
information-preserving round trip (see `net_data_to_composed_model`'s
docstring for the concrete ordering contract).

What DOES and does NOT survive a round trip THROUGH a ComposedModel (i.e.
net_data -> net_data_to_composed_model -> composed_model_to_net_data),
explained fully where each matters below:
  - Place, transition, and LOCAL arc ids: preserved exactly -- ComposedModel
    carries each object's own PetriNet, ids and all, completely unmodified.
  - Frame ids: NOT preserved. `ModelObject` has no field for a frame's own
    string id (only an int `index` and a `name`) -- `composed_model_to_net_data`
    always mints a fresh, deterministic `obj{index}` id, discarding whatever
    hand-authored one the input had. `PetriNetSession`'s own
    to_net_data/from_net_data does not suffer this (it keeps each object's
    original frame id directly, restoring it after this converter's own
    round trip -- see session.py's `SessionObject`/`_restore_frame_ids`).
  - Link ids: NOT preserved either, for the same structural reason as frame
    ids -- `ComposedLink` (src/domain/composed/link.py) has no id field at
    all, so there is nowhere for one to survive the trip through it.
    `composed_model_to_net_data` always mints `link{position}` ids by
    ARRAY POSITION in `model.links`, which also means removing one link and
    keeping others renumbers every link after it on the very next
    serialization -- callers must not treat a link id as stable across two
    calls to this converter (or across two `PetriNetSession.to_net_data()`
    calls on a composed session, which goes through this same converter).
  - A cross-object arc, or a same-owner link, HEALED into a synthesized
    local arc (`_heal_same_owner_arcs_and_links`/`_distribute_arcs`) is a
    genuinely NEW arc, not a preserved one: it never existed as an arc in
    the input, so there is no original id to preserve.
  - `templateId` (frontend-only: this app's Petri-object template library)
    has no ComposedModel counterpart and is dropped by this converter.
    ModelObject.template_method/template_arguments is a different, desktop
    (PetriObjModelPaint)-specific field this converter does not populate.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from src.domain.composed import ComposedModel, LinkType, ModelObject
from src.domain.layout.sugiyama import CLUSTER_GAP
from src.domain.models import PetriNet
from src.services.petri.exporter.geometry import (
    FRAME_HEADER_H,
    FRAME_MIN_H,
    FRAME_MIN_W,
    FRAME_PADDING,
    NODE_LABEL_H,
    PLACE_H,
    PLACE_W,
    TRANS_H,
    TRANS_W,
)

#: Object index reserved for the free pool in every ComposedModel this
#: module builds or reads: always added first (so it always lands at index
#: 0), always present even when it holds no elements. Fixing this instead
#: of mirroring the frontend's "free bucket last, omitted when empty"
#: convention keeps index assignment stable across calls regardless of
#: which objects currently happen to be empty -- see module docstring.
FREE_POOL_INDEX = 0


@dataclass
class Box:
    """An axis-aligned box in canvas coordinates, top-left + size."""

    x: float
    y: float
    w: float
    h: float


def frame_bounds_for_members(boxes: list[Box]) -> Box:
    """Frame bounds that clear a set of member boxes, mirroring the
    frontend's `frameBoundsFor` (frontend/src/lib/petri-object-model.ts):
    true member boxes (not just their top-left corners) plus uniform
    padding, extra room at the top for the frame's header chrome and at the
    bottom for each member's caption.

    With no members at all (a freshly created, still-empty object with no
    explicit geometry either) there is nothing to clear: falls back to the
    origin at the minimum frame size, a reasonable default an empty object
    can be dragged from later.
    """
    if not boxes:
        return Box(0.0, 0.0, FRAME_MIN_W, FRAME_MIN_H)

    min_x = min(b.x for b in boxes) - FRAME_PADDING
    min_y = min(b.y for b in boxes) - FRAME_PADDING - FRAME_HEADER_H
    max_x = max(b.x + b.w for b in boxes) + FRAME_PADDING
    max_y = max(b.y + b.h for b in boxes) + FRAME_PADDING + NODE_LABEL_H

    return Box(
        x=min_x,
        y=min_y,
        w=max(FRAME_MIN_W, max_x - min_x),
        h=max(FRAME_MIN_H, max_y - min_y),
    )


# ---------------------------------------------------------------------------
# net_data -> ComposedModel
# ---------------------------------------------------------------------------


@dataclass
class _Bucket:
    """One object's worth of raw (still-dict) places/transitions/arcs,
    gathered while partitioning a net_data document."""

    frame_id: Optional[str]  # None for the free pool bucket
    frame: Optional[dict] = None  # the raw ObjectFrame dict, if any
    places: list[dict] = field(default_factory=list)
    transitions: list[dict] = field(default_factory=list)
    arcs: list[dict] = field(default_factory=list)


def _partition_buckets(net_data: dict) -> tuple[list[_Bucket], dict[str, int]]:
    """Group places/transitions by `objectId` into fixed-order buckets.

    Bucket 0 is always the free pool (FREE_POOL_INDEX), present even when
    empty. Buckets 1..N are one per entry of net_data["objects"], in that
    array's own order, ALSO present even when currently empty -- an object
    with no direct members is still a real, drawn object (see the frontend's
    own comment on why a saved document keeps it), and dropping it here
    would silently lose it on the very next reload.
    """
    frames = net_data.get("objects") or []
    buckets = [_Bucket(frame_id=None)]
    index_by_frame_id: dict[str, int] = {}
    for raw_frame in frames:
        index_by_frame_id[raw_frame["id"]] = len(buckets)
        buckets.append(_Bucket(frame_id=raw_frame["id"], frame=raw_frame))

    for place in net_data.get("places", []):
        owner = place.get("objectId")
        idx = index_by_frame_id.get(owner, FREE_POOL_INDEX) if owner else FREE_POOL_INDEX
        buckets[idx].places.append(place)
    for trans in net_data.get("transitions", []):
        owner = trans.get("objectId")
        idx = index_by_frame_id.get(owner, FREE_POOL_INDEX) if owner else FREE_POOL_INDEX
        buckets[idx].transitions.append(trans)

    return buckets, index_by_frame_id


def _member_bucket_map(buckets: list[_Bucket]) -> dict[str, int]:
    """element id -> owning bucket index, across every bucket."""
    owner: dict[str, int] = {}
    for bi, bucket in enumerate(buckets):
        for p in bucket.places:
            owner[p["id"]] = bi
        for t in bucket.transitions:
            owner[t["id"]] = bi
    return owner


def _bucket_position(buckets: list[_Bucket], bucket_index: int, element_id: str) -> Optional[tuple[int, str]]:
    """(position, "place"|"transition") of one element within one bucket."""
    bucket = buckets[bucket_index]
    for i, p in enumerate(bucket.places):
        if p["id"] == element_id:
            return i, "place"
    for i, t in enumerate(bucket.transitions):
        if t["id"] == element_id:
            return i, "transition"
    return None


def _endpoint_kind(link_type: LinkType, side: str) -> str:
    """Whether one side of a link addresses a place or a transition.

    Mirrors (does not import, this runs before any ComposedModel exists to
    call the instance method on) ComposedModel._endpoint_kind.
    """
    if link_type == LinkType.PLACE_FUSION:
        return "place"
    if link_type == LinkType.TRANSITION_TO_PLACE:
        return "transition" if side == "source" else "place"
    return "place" if side == "source" else "transition"  # PLACE_TO_TRANSITION


def _heal_same_owner_arcs_and_links(
    net_data: dict, buckets: list[_Bucket], owner: dict[str, int]
) -> list[dict]:
    """Cross-object ObjectLinks whose endpoints share one owner, and
    same-object PetriArcs healed from a same-owner link, both folded into
    the arc lists they belong in. Mirrors buildComposedRequest's own
    healing pass (composed-simulation-client.ts): membership can change
    after a link was drawn (grouping, drag-adoption), and a link between two
    elements that now share an owner is not a cross-object link anymore.

    Returns the ids of ObjectLinks that were healed this way, so the caller
    excludes them from ordinary link resolution.
    """
    healed_ids: list[dict] = []
    for link in net_data.get("links", []):
        src_bucket = owner.get(link["sourceId"])
        tgt_bucket = owner.get(link["targetId"])
        if src_bucket is None or tgt_bucket is None or src_bucket != tgt_bucket:
            continue
        healed_ids.append(link["id"])
        if link["type"] == "placeFusion":
            continue  # the two places are one identity now; nothing to draw
        # Checked against the FULL document's arcs (net_data["arcs"]), not
        # buckets[src_bucket].arcs: at this point in net_data_to_composed_model
        # (called BEFORE _distribute_arcs below fills buckets[*].arcs with
        # anything at all -- local arcs included), the latter is always
        # empty, silently defeating this duplicate check and letting a
        # healed arc double up with the identical local arc the document
        # already carries. Mirrors the frontend's own healing pass
        # (composed-simulation-client.ts's buildComposedRequest, lines
        # ~142-145), which checks net.arcs -- the whole document -- for
        # exactly this reason.
        existing_arc = any(
            a["source_id"] == link["sourceId"] and a["target_id"] == link["targetId"]
            for a in net_data.get("arcs", [])
        )
        if existing_arc:
            continue
        buckets[src_bucket].arcs.append({
            "id": f"healed_{link['id']}",
            "source_id": link["sourceId"],
            "target_id": link["targetId"],
            "weight": link.get("quantity", 1),
            "arc_type": "READ" if link.get("informational") else "NORMAL",
        })
    return healed_ids


def _validate_crossing_arc_directions(
    net_data: dict, buckets: list[_Bucket], owner: dict[str, int],
) -> None:
    """Reject a READ arc crossing a boundary in the transitionToPlace
    direction (source is a TRANSITION) with a clean, actionable ValueError
    -- before `_heal_same_owner_arcs_and_links`/`_distribute_arcs` mutate
    `buckets` at all, and therefore before `net_data_to_composed_model`
    builds any PetriNet or ComposedModel from it.

    `informational` (what a READ arc becomes on the synthesized link) is
    only meaningful for a placeToTransition link -- domain/composed/
    link.py's `ComposedLink._check_informational_scope` raises for any
    other type -- and a transition cannot "read" an output place without
    consuming it, so a transitionToPlace-direction READ arc has no link
    shape it could legitimately become. Left unchecked, `_distribute_arcs`
    would still synthesize a `type: "transitionToPlace", informational:
    true` spec for it, and the informational-scope violation would only
    surface much later as an opaque pydantic ValidationError out of
    `ComposedModel.add_link`, deep inside this function's own final loop,
    AFTER buckets/model construction was already well underway.

    A place-to-transition crossing (source is a place) with the same READ
    arc_type is NOT rejected here: it legitimately becomes an informational
    placeToTransition link spec. Whether that link TYPE is itself usable at
    all once synthesized is the retirement backstop's job
    (ComposedModel.validate/composed_document.py: placeToTransition is
    retired regardless of informational), not this function's -- this only
    guards the one direction ComposedLink's own model would otherwise
    refuse to construct at all.
    """
    for arc in net_data.get("arcs", []):
        if (arc.get("arc_type") or "").upper() != "READ":
            continue
        src_bucket = owner.get(arc["source_id"])
        tgt_bucket = owner.get(arc["target_id"])
        if src_bucket is None or tgt_bucket is None or src_bucket == tgt_bucket:
            continue
        source_pos = _bucket_position(buckets, src_bucket, arc["source_id"])
        source_is_place = source_pos is not None and source_pos[1] == "place"
        if source_is_place:
            continue
        raise ValueError(
            f"Arc '{arc['id']}' ({arc['source_id']} -> {arc['target_id']}) is a READ "
            "arc sourced from a transition, crossing an object boundary. A READ arc "
            "only makes sense reading FROM a place INTO a consuming transition, so "
            "there is no cross-object link this direction can become. Fix the arc's "
            "direction, or change it to a normal (non-READ) arc."
        )


def _distribute_arcs(net_data: dict, buckets: list[_Bucket], owner: dict[str, int]) -> list[dict]:
    """Local arcs go to their shared bucket. A cross-bucket arc cannot be
    represented as a PetriArc in a ComposedModel (each object's net is
    independent) -- it is a cross-object flow and is synthesized into a
    link instead, mirroring buildComposedRequest's identical handling of
    a boundary-crossing PetriArc.

    Returns the list of synthesized link specs (frontend ObjectLink shape)
    for such arcs, to be resolved alongside the document's own links.
    """
    synthesized: list[dict] = []
    for arc in net_data.get("arcs", []):
        src_bucket = owner.get(arc["source_id"])
        tgt_bucket = owner.get(arc["target_id"])
        if src_bucket is None or tgt_bucket is None:
            continue  # dangling endpoint: not this converter's problem
        if src_bucket == tgt_bucket:
            buckets[src_bucket].arcs.append(arc)
            continue
        source_is_place = _bucket_position(buckets, src_bucket, arc["source_id"])
        is_place = source_is_place is not None and source_is_place[1] == "place"
        synthesized.append({
            "id": arc["id"],
            "type": "placeToTransition" if is_place else "transitionToPlace",
            "sourceId": arc["source_id"],
            "targetId": arc["target_id"],
            "quantity": arc.get("weight", 1),
            "informational": (arc.get("arc_type") or "").upper() == "READ",
        })
    return synthesized


def net_data_to_composed_model(net_data: dict) -> ComposedModel:
    """Partition a frontend-shape net_data dict into a ComposedModel.

    Object 0 is always the free pool (`ModelObject.free=True`), present
    even when it holds no elements; objects 1..N mirror net_data["objects"]
    in array order, also present even when currently empty. See
    FREE_POOL_INDEX and `_partition_buckets` for why this differs from
    buildComposedRequest's throwaway-request ordering.
    """
    buckets, index_by_frame_id = _partition_buckets(net_data)
    owner = _member_bucket_map(buckets)

    # Validate BEFORE any mutation: _partition_buckets above only reads
    # net_data (places/transitions land in buckets, but buckets[*].arcs is
    # still empty), so failing here leaves both net_data and buckets
    # exactly as a caller handed them in -- no partially-built model, no
    # partially-healed arcs to unwind.
    _validate_crossing_arc_directions(net_data, buckets, owner)

    healed_link_ids = set(_heal_same_owner_arcs_and_links(net_data, buckets, owner))
    synthesized_links = _distribute_arcs(net_data, buckets, owner)

    model = ComposedModel(name=net_data.get("name", "ComposedModel"))

    free_bucket = buckets[FREE_POOL_INDEX]
    free_net = PetriNet(
        name=net_data.get("name", "PetriNet"),
        places=free_bucket.places,
        transitions=free_bucket.transitions,
        arcs=free_bucket.arcs,
    )
    model.add_object(free_net, name="Free", free=True)

    for bucket in buckets[1:]:
        raw_frame = bucket.frame or {}
        graphics = raw_frame.get("graphics") or {}
        parent_frame_id = raw_frame.get("objectId")
        parent_index = index_by_frame_id.get(parent_frame_id) if parent_frame_id else None
        obj_net = PetriNet(
            name=raw_frame.get("name", bucket.frame_id),
            places=bucket.places,
            transitions=bucket.transitions,
            arcs=bucket.arcs,
        )
        model.add_object(
            obj_net,
            name=raw_frame.get("name", bucket.frame_id),
            priority=raw_frame.get("priority", 0),
            x=graphics.get("x", 0.0),
            y=graphics.get("y", 0.0),
            width=graphics.get("width"),
            height=graphics.get("height"),
            collapsed=bool(raw_frame.get("collapsed", False)),
            parent=parent_index,
            auto_fit=raw_frame.get("autoFit"),
            free=False,
        )

    all_links = [
        link for link in net_data.get("links", []) if link["id"] not in healed_link_ids
    ] + synthesized_links

    for link_spec in all_links:
        source_bucket = owner.get(link_spec["sourceId"])
        target_bucket = owner.get(link_spec["targetId"])
        if source_bucket is None or target_bucket is None:
            continue  # dangling endpoint: skip rather than fail the whole model
        link_type = LinkType(link_spec["type"])
        source_pos = _bucket_position(buckets, source_bucket, link_spec["sourceId"])
        target_pos = _bucket_position(buckets, target_bucket, link_spec["targetId"])
        if source_pos is None or target_pos is None:
            continue
        model.add_link(
            link_type,
            source_object=source_bucket,
            source_element=source_pos[0],
            target_object=target_bucket,
            target_element=target_pos[0],
            quantity=link_spec.get("quantity", 1),
            informational=bool(link_spec.get("informational", False)),
        )

    return model


# ---------------------------------------------------------------------------
# ComposedModel -> net_data
# ---------------------------------------------------------------------------


def _resolve_object_bounds(model: ComposedModel, obj: ModelObject, resolved: dict[int, Box]) -> Box:
    """x/y/width/height for one object, auto-derived from its member
    places/transitions (and any already-resolved child frames) unless
    `auto_fit` was explicitly turned off.

    Mirrors the frontend's own `refitFrame`/`autoFit` contract exactly
    (frontend/src/stores/editor-store.ts's resizeObject/resetAutoFit): a
    hand-drawn resize sets `auto_fit=False` and is the only thing that
    freezes a stored width/height going forward. Everything else --
    `auto_fit` left at its default `None` (every agent-created object,
    which never touches it) or explicitly `True` -- keeps re-deriving the
    box from current members on every export.

    That distinction matters because `width`/`height` do NOT stay unset
    once a fit has run once: `net_data_to_composed_model` (the wire ->
    domain direction) reads them straight back off `graphics.width/height`,
    so the padded box THIS function computed on a previous turn comes back
    as an explicit value on the next one. Keying off "is width/height set"
    instead of `auto_fit` would freeze every agent-built object at
    whatever size it happened to be when its second element was added,
    leaving it visibly too tight for everything added afterward -- which
    is exactly the bug this docstring update fixed.

    The WHOLE box (position included) is derived from where the members
    currently sit when auto-fitting: a box explicitly sized but positioned
    wherever its members happen to be would not actually enclose them.
    Memoized in `resolved` so a parent that needs a child's freshly-derived
    box never recomputes it, and a parent/child cycle (which should not
    occur, but ComposedModel does not forbid it) cannot recurse forever --
    a cycle member falls back to its own elements only.
    """
    if obj.index in resolved:
        return resolved[obj.index]
    if obj.auto_fit is False and obj.width is not None and obj.height is not None:
        box = Box(obj.x, obj.y, obj.width, obj.height)
        resolved[obj.index] = box
        return box

    resolved[obj.index] = Box(obj.x, obj.y, FRAME_MIN_W, FRAME_MIN_H)  # cycle guard placeholder

    boxes = [Box(p.graphics.x, p.graphics.y, PLACE_W, PLACE_H) for p in obj.net.places]
    boxes += [Box(t.graphics.x, t.graphics.y, TRANS_W, TRANS_H) for t in obj.net.transitions]
    for child in model.objects:
        if child.parent == obj.index and child.index != obj.index:
            child_box = _resolve_object_bounds(model, child, resolved)
            boxes.append(child_box)

    box = frame_bounds_for_members(boxes)
    resolved[obj.index] = box
    return box


def _frame_id_for(obj: ModelObject) -> str:
    """Deterministic string frame id minted from an object's own index (see
    module docstring: ModelObject has no string id field of its own)."""
    return f"obj{obj.index}"


def _spread_one_sibling_group(
    siblings: list[dict],
    min_gap: float,
    translate: Callable[[dict, float], None],
    obstacles: list[dict] = (),
) -> None:
    """Push one group of sibling frames (same parent, or all top-level ones
    together) apart, left to right, until every pair clears at least
    `min_gap`. Only frames whose size was NOT explicitly locked (`auto_fit
    is not False`, matching `_resolve_object_bounds`'s own contract) are
    moved -- a deliberately hand-positioned frame keeps the exact spot it
    was put at, but an unlocked sibling is free to make room for it.

    Moving is delegated to `translate` rather than done on the frame's own
    `graphics` here, because a frame is not a box that merely sits above
    its contents: its box is DERIVED from where its members sit, and every
    member stores absolute coordinates. Sliding the box on its own would
    leave the members exactly where they were -- piled on top of whatever
    territory the frame was just pushed off, which is the very collision
    this pass exists to resolve.

    `obstacles` seeds the placed list with fixed boxes from OUTSIDE this
    group that siblings must also clear but that themselves never move --
    the free pool's own bounding box, at the top level (see
    _arrange_object_frames): its elements have no frame of their own
    to render, so nothing about a plain top-level-only pass would ever
    know it occupies real canvas territory a new object could land right
    on top of.
    """
    placed: list[dict] = list(obstacles)
    for frame in siblings:
        g = frame["graphics"]
        locked = frame.get("autoFit") is False
        if not locked:
            moved = True
            while moved:
                moved = False
                for prev in placed:
                    pg = prev["graphics"]
                    overlaps_y = (
                        g["y"] < pg["y"] + pg["height"] + min_gap
                        and pg["y"] < g["y"] + g["height"] + min_gap
                    )
                    if not overlaps_y:
                        continue
                    min_x = pg["x"] + pg["width"] + min_gap
                    if g["x"] < min_x:
                        translate(frame, min_x - g["x"])
                        moved = True
        placed.append(frame)


def _flow_between(
    link: dict, produced: set[str], consumed: set[str]
) -> tuple[str, str] | None:
    """Which way a link makes one object follow another, if it does at all.

    A place fusion is SYMMETRIC: it says two places are one place, not that
    either comes first. Its sourceId/targetId are only the order somebody
    wrote the arguments in, and taking that for a flow direction is how an
    exit object ended up drawn before the generator that feeds it -- the
    agent had simply named it first.

    The net itself knows better. A place that its own object WRITES to is
    where that object hands off; a place its own object READS from is where
    the next one picks up. So the fused pair points from the writer to the
    reader.

    None when the pair says nothing about order: two objects reading from
    the same shared place are peers drawing on one queue, not a sequence,
    and inventing an order between them would draw one of them behind the
    other for no reason.

    A transitionToPlace link is genuinely directed -- a transition delivers
    INTO a place -- so it is taken as written.
    """
    source, target = link["sourceId"], link["targetId"]
    if link.get("type") != "placeFusion":
        return (source, target)
    if source in produced and target in consumed:
        return (source, target)
    if target in produced and source in consumed:
        return (target, source)
    return None


def _object_cells(
    siblings: list[dict],
    edges: list[tuple[str, str]],
) -> dict[str, tuple[int, int]]:
    """Assign each frame in one sibling group a (column, row) cell.

    The cells are a notional table, not anything stored: column is the
    step along the flow, row is the branch across it. Two objects share a
    column exactly when neither can be said to come before the other, which
    is what "these run in parallel" means, and an object sits one column
    past everything that feeds it.

    Column comes from the longest path over the object graph, the same rule
    the element-level layout uses for its own layers (domain/layout/sugiyama
    `_assign_layers_super`). Nothing is declared: the links the model
    already has ARE the ordering, so a derived cell cannot contradict the
    topology the way a hand-numbered one could.

    An object with no links at all is a special case worth naming: the
    agent builds every object first and links them last, so mid-build the
    graph is empty and EVERY object would qualify as parallel and pile into
    one column. Unlinked objects therefore get successive columns of their
    own, in creation order, which is also what an unlinked model looked
    like before any of this existed. They snap into place the moment the
    links arrive.

    Row order within a column follows each frame's current cross-axis
    position, so an arrangement that was already reasonable is not
    reshuffled for no reason, with the frame id as a deterministic
    tie-break.
    """
    ids = [f["id"] for f in siblings]
    index_of = {fid: i for i, fid in enumerate(ids)}
    succs: dict[str, list[str]] = {fid: [] for fid in ids}
    preds: dict[str, list[str]] = {fid: [] for fid in ids}
    for source, target in edges:
        if source in succs and target in preds and source != target:
            succs[source].append(target)
            preds[target].append(source)

    linked = [fid for fid in ids if succs[fid] or preds[fid]]
    isolated = [fid for fid in ids if fid not in set(linked)]

    column: dict[str, int] = {fid: 0 for fid in linked}
    remaining = {fid: len(preds[fid]) for fid in linked}
    queue = deque(sorted(fid for fid in linked if remaining[fid] == 0))
    visited: set[str] = set()
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for nxt in sorted(succs[current]):
            column[nxt] = max(column[nxt], column[current] + 1)
            remaining[nxt] -= 1
            if remaining[nxt] <= 0 and nxt not in visited:
                queue.append(nxt)
    # A cycle member never drains its in-degree; park it past the frontier
    # rather than letting it share column 0 with the sources.
    frontier = max(column.values(), default=-1)
    for fid in linked:
        if fid not in visited:
            frontier += 1
            column[fid] = frontier
    for fid in sorted(isolated, key=lambda f: index_of[f]):
        frontier += 1
        column[fid] = frontier

    cells: dict[str, tuple[int, int]] = {}
    by_column: dict[int, list[str]] = {}
    for fid in ids:
        by_column.setdefault(column[fid], []).append(fid)
    for col, members in by_column.items():
        for row, fid in enumerate(members):
            cells[fid] = (col, row)
    return cells


def _place_group_in_grid(
    siblings: list[dict],
    edges: list[tuple[str, str]],
    direction: str,
    translate,
    gap: float,
    min_flow: float | None = None,
) -> None:
    """Lay one sibling group out on its notional grid.

    "LR" runs columns along x and stacks rows down y, so parallel branches
    sit one under another and each step moves right. "TB" is the same table
    transposed: parallel branches stand side by side and each step moves
    down. Nothing else about the two cases differs, which is why the axis
    is chosen once here rather than branched on throughout.

    Each column is centred across the widest column, so a single generator
    feeding two machines is drawn level with the pair instead of aligned to
    the top one.
    """
    horizontal = direction != "TB"
    cells = _object_cells(siblings, edges)
    by_id = {f["id"]: f for f in siblings}

    def flow_size(frame: dict) -> float:
        g = frame["graphics"]
        return g["width"] if horizontal else g["height"]

    def cross_size(frame: dict) -> float:
        g = frame["graphics"]
        return g["height"] if horizontal else g["width"]

    columns: dict[int, list[dict]] = {}
    for fid, (col, row) in sorted(cells.items(), key=lambda kv: (kv[1][0], kv[1][1])):
        columns.setdefault(col, []).append(by_id[fid])
    # Sort each column by where its frames already sit across the flow, so
    # a layout that was already sensible keeps its order.
    for members in columns.values():
        members.sort(
            key=lambda f: (
                f["graphics"]["y" if horizontal else "x"], f["id"],
            )
        )

    def column_extent(members: list[dict]) -> float:
        return sum(cross_size(f) for f in members) + gap * (len(members) - 1)

    widest = max((column_extent(m) for m in columns.values()), default=0.0)
    origin_flow = min(
        (f["graphics"]["x" if horizontal else "y"] for f in siblings), default=0.0
    )
    origin_cross = min(
        (f["graphics"]["y" if horizontal else "x"] for f in siblings), default=0.0
    )

    if min_flow is not None:
        origin_flow = max(origin_flow, min_flow)

    flow = origin_flow
    for col in sorted(columns):
        members = columns[col]
        cross = origin_cross + (widest - column_extent(members)) / 2
        for frame in members:
            g = frame["graphics"]
            target_flow, target_cross = flow, cross
            dx = (target_flow - g["x"]) if horizontal else (target_cross - g["x"])
            dy = (target_cross - g["y"]) if horizontal else (target_flow - g["y"])
            translate(frame, dx, dy)
            cross += cross_size(frame) + gap
        flow += max(flow_size(f) for f in members) + gap


def _arrange_object_frames(
    frames: list[dict],
    places: list[dict],
    transitions: list[dict],
    arcs: list[dict],
    links: list[dict],
    direction: str = "LR",
    min_gap: float = CLUSTER_GAP,
) -> None:
    """Lay every group of sibling object frames out on its own notional
    grid (top-level ones together, and independently for each parent's own
    set of nested children), so that objects which run in parallel stand
    across from each other and objects which follow one another step along
    the flow. See `_object_cells` for how a cell is derived and
    `_place_group_in_grid` for how it becomes a position.

    This replaced a pass that only pushed overlapping frames to the right
    until they cleared `min_gap`. That kept them from colliding but knew
    nothing about the model, so two machines fed by the same generator --
    the definition of parallel -- were drawn one after the other exactly
    like two stages of a pipeline. The links say which of those it is, so
    they are what decides.

    A group holding any frame whose size was explicitly locked
    (`autoFit is False`, someone resized it by hand) is left to the old
    collision-avoidance pass instead: a hand-placed frame is a decision,
    and re-flowing the group around it would move it.

    A nested group is laid out exactly like the top-level one, because a
    nested frame's `graphics` sits in the SAME absolute canvas coordinate
    space as everything else (the frontend converts to parent-relative only
    at render time, via React Flow's parentId/extent). Placement is needed
    at all because nothing else produces it: an object's box is derived
    purely from where ITS OWN members happen to sit
    (`_resolve_object_bounds`), two objects know nothing of each other's
    territory, and every builder starts new members from the same fixed
    default cursor, so without this pass they all land on top of each other.

    An object is moved WITH its contents (`translate_subtree` below): the
    box is only ever a fit around where its members sit, and members store
    absolute coordinates, so moving the box alone would strand the members
    at the piled-up spot the frame was just pushed off -- the frame lands
    somewhere clear and renders empty, while its innards stay heaped on
    top of whatever else is there.

    Processed deepest-nesting-first: after laying one parent's children
    out, that parent's own box is re-fit to enclose them again (same
    formula `_resolve_object_bounds` used the first time: the parent's own
    direct places/transitions plus every child's box) -- otherwise the
    parent would still be sized for where its children stood BEFORE they
    moved, clipping them. A locked parent (`auto_fit is False`) is never
    resized, matching every other auto-fit rule here.
    """
    by_id = {f["id"]: f for f in frames}

    def nesting_depth(frame: dict) -> int:
        d = 0
        seen = {frame["id"]}
        cur = frame
        while cur.get("objectId") in by_id:
            cur = by_id[cur["objectId"]]
            if cur["id"] in seen:  # cycle guard -- should not occur
                break
            seen.add(cur["id"])
            d += 1
        return d

    groups: dict[str | None, list[dict]] = {}
    for f in frames:
        groups.setdefault(f.get("objectId"), []).append(f)

    members_by_owner: dict[str, list[dict]] = {}
    for element in (*places, *transitions):
        owner = element.get("objectId")
        if owner is not None:
            members_by_owner.setdefault(owner, []).append(element)

    def translate_subtree(frame: dict, dx: float, dy: float = 0.0) -> None:
        """Slide a frame and everything it contains -- its own direct
        places/transitions, plus every nested child frame with ITS contents,
        recursively -- by `dx`. Nested frames move along for the same reason
        members do: their `graphics` is absolute canvas coordinates too (the
        frontend converts to parent-relative only at render time, via React
        Flow's parentId/extent), so a child left behind would escape the
        parent that owns it."""
        pending = [frame]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current["id"] in seen:  # cycle guard -- should not occur
                continue
            seen.add(current["id"])
            current["graphics"]["x"] += dx
            current["graphics"]["y"] += dy
            for element in members_by_owner.get(current["id"], ()):
                element["graphics"]["x"] += dx
                element["graphics"]["y"] += dy
            pending.extend(groups.get(current["id"], ()))

    # A group's own processing priority is its PARENT's nesting depth + 1
    # (the top-level group, keyed by None, is depth 0) -- so the deepest
    # groups of children are spread, and their parents re-fit around them,
    # before any shallower group (which may include those same parents as
    # members) is touched.
    def group_priority(parent_key: str | None) -> int:
        return 0 if parent_key is None else nesting_depth(by_id[parent_key]) + 1

    def own_elements_box(owner: str | None) -> Box | None:
        """Where an owner's OWN places and transitions sit, as one box.

        Elements have no frame to reposition, but they occupy real canvas
        territory just like any object's box does. A group of frames laid
        out without knowing that lands on top of them: at the top level
        that means a new object over the free pool, and inside a parent it
        means the parent's own places under its nested children, since a
        Petri-object may hold plain elements and other objects at once.
        Treated as a fixed obstacle, never moved or resized.
        """
        boxes = [
            Box(p["graphics"]["x"], p["graphics"]["y"], PLACE_W, PLACE_H)
            for p in places
            if p.get("objectId") == owner
        ] + [
            Box(t["graphics"]["x"], t["graphics"]["y"], TRANS_W, TRANS_H)
            for t in transitions
            if t.get("objectId") == owner
        ]
        return frame_bounds_for_members(boxes) if boxes else None

    free_pool = own_elements_box(None)
    top_level_obstacles: list[dict] = []
    if free_pool is not None:
        top_level_obstacles = [{
            "id": "__free_pool__",
            "graphics": {
                "x": free_pool.x, "y": free_pool.y,
                "width": free_pool.w, "height": free_pool.h,
            },
            "autoFit": False,
        }]

    owner_of_element: dict[str, str] = {}
    for element in (*places, *transitions):
        owner = element.get("objectId")
        if owner is not None:
            owner_of_element[element["id"]] = owner

    # Which places are written to, and which are read from, inside their own
    # object -- the two facts that tell a hand-off's direction apart from the
    # order somebody happened to write it in. See _flow_between.
    produced = {arc["target_id"] for arc in arcs}
    consumed = {arc["source_id"] for arc in arcs}

    def ancestor_in(frame_id: str | None, allowed: set[str]) -> str | None:
        """The member of `allowed` that owns `frame_id`, directly or through
        any depth of nesting. An element several objects deep still tells
        this group which of ITS frames the link touches."""
        seen: set[str] = set()
        current = frame_id
        while current is not None and current not in allowed:
            if current in seen:  # cycle guard -- should not occur
                return None
            seen.add(current)
            current = by_id[current].get("objectId") if current in by_id else None
        return current

    for parent_key in sorted(groups, key=group_priority, reverse=True):
        siblings = groups[parent_key]
        if any(frame.get("autoFit") is False for frame in siblings):
            obstacles = top_level_obstacles if parent_key is None else ()
            _spread_one_sibling_group(siblings, min_gap, translate_subtree, obstacles)
        else:
            allowed = {frame["id"] for frame in siblings}
            edges: list[tuple[str, str]] = []
            for link in links:
                pair = _flow_between(link, produced, consumed)
                if pair is None:
                    continue
                source = ancestor_in(owner_of_element.get(pair[0]), allowed)
                target = ancestor_in(owner_of_element.get(pair[1]), allowed)
                if source is not None and target is not None and source != target:
                    edges.append((source, target))
            occupied = free_pool if parent_key is None else own_elements_box(parent_key)
            min_flow = None
            if occupied is not None:
                min_flow = (
                    occupied.x + occupied.w + min_gap
                    if direction != "TB"
                    else occupied.y + occupied.h + min_gap
                )
            _place_group_in_grid(
                siblings, edges, direction, translate_subtree, min_gap, min_flow
            )

        if parent_key is None or parent_key not in by_id:
            continue
        parent = by_id[parent_key]
        if parent.get("autoFit") is False:
            continue
        boxes = [
            Box(p["graphics"]["x"], p["graphics"]["y"], PLACE_W, PLACE_H)
            for p in places
            if p.get("objectId") == parent_key
        ]
        boxes += [
            Box(t["graphics"]["x"], t["graphics"]["y"], TRANS_W, TRANS_H)
            for t in transitions
            if t.get("objectId") == parent_key
        ]
        boxes += [
            Box(s["graphics"]["x"], s["graphics"]["y"], s["graphics"]["width"], s["graphics"]["height"])
            for s in siblings
        ]
        fit = frame_bounds_for_members(boxes)
        parent["graphics"] = {"x": fit.x, "y": fit.y, "width": fit.w, "height": fit.h}


def composed_model_to_net_data(
    model: ComposedModel, layout_direction: str = "LR"
) -> dict:
    """Merge a ComposedModel back into a frontend-shape net_data dict.

    `layout_direction` ("LR"/"TB") is which way the OBJECT frames are
    arranged, matching the direction their contents were laid out in. It is
    a parameter rather than something read off the model because
    ComposedModel carries no layout state of its own; PetriNetSession,
    which does, passes its own.

    Inverse of `net_data_to_composed_model` for every field ComposedModel
    actually carries. The object marked `free=True` (if any -- a
    hand-built ComposedModel that never called add_object(..., free=True)
    legitimately has none) contributes its elements with no `objectId` and
    is not written to `objects[]`; every other object becomes one
    ObjectFrame plus `objectId`-tagged elements.
    """
    free_obj = next((o for o in model.objects if o.free), None)
    frame_id_by_index = {o.index: _frame_id_for(o) for o in model.objects if o is not free_obj}

    places: list[dict] = []
    transitions: list[dict] = []
    arcs: list[dict] = []
    objects: list[dict] = []
    resolved_bounds: dict[int, Box] = {}

    for obj in model.objects:
        dumped = obj.net.model_dump()
        frame_id = frame_id_by_index.get(obj.index)
        for p in dumped["places"]:
            if frame_id is not None:
                p["objectId"] = frame_id
            places.append(p)
        for t in dumped["transitions"]:
            if frame_id is not None:
                t["objectId"] = frame_id
            transitions.append(t)
        arcs.extend(dumped["arcs"])

        if obj is free_obj:
            continue

        bounds = _resolve_object_bounds(model, obj, resolved_bounds)
        frame: dict[str, Any] = {
            "id": frame_id,
            "name": obj.name,
            "priority": obj.priority,
            "graphics": {"x": bounds.x, "y": bounds.y, "width": bounds.w, "height": bounds.h},
        }
        if obj.collapsed:
            frame["collapsed"] = True
        if obj.parent is not None and obj.parent in frame_id_by_index:
            frame["objectId"] = frame_id_by_index[obj.parent]
        if obj.auto_fit is not None:
            frame["autoFit"] = obj.auto_fit
        objects.append(frame)

    links: list[dict] = []
    for i, link in enumerate(model.links):
        source_id, _ = model.resolve_link_endpoint(link, "source")
        target_id, _ = model.resolve_link_endpoint(link, "target")
        link_dict: dict[str, Any] = {
            "id": f"link{i + 1}",
            "type": link.type.value,
            "sourceId": source_id,
            "targetId": target_id,
            "quantity": link.quantity,
        }
        if link.informational:
            link_dict["informational"] = True
        links.append(link_dict)

    # After the links, because the links are what says which objects run in
    # parallel and which follow one another -- see _arrange_object_frames.
    _arrange_object_frames(objects, places, transitions, arcs, links, layout_direction)

    result: dict[str, Any] = {
        "name": model.name,
        "places": places,
        "transitions": transitions,
        "arcs": arcs,
    }
    if objects:
        result["objects"] = objects
    if links:
        result["links"] = links
    return result


# ---------------------------------------------------------------------------
# ComposedModel -> composed-simulate wire body (POST /api/v1/simulate/composed)
# ---------------------------------------------------------------------------


def composed_model_to_wire_objects(model: ComposedModel) -> list[dict[str, Any]]:
    """One dict per `model.objects` entry, shaped like
    `simulate_composed.ComposedObjectSpec` (name/priority/x/y/width/height/
    collapsed/parent/auto_fit/free/net_data) and ready to drop straight
    into `ComposedSimulateBody.objects` for `POST /api/v1/simulate/composed`
    -- EXCEPT the free pool (`ModelObject.free`) is omitted when it holds
    no places and no transitions, mirroring the frontend's own
    buildComposedRequest (composed-simulation-client.ts's
    partitionIntoObjects, `includeEmptyObjects=false`): that wire body caps
    `objects` at `SIMULATION_MAX_OBJECTS` entries, so spending one of them
    on an empty free pool is exactly the waste
    `PetriNetSession._exportable_object_count` (session.py, create_object's
    own cap check) budgets against -- this is the converter half of that
    same accounting, giving a session sitting right at the cap something it
    can actually round-trip through that endpoint.

    Named objects are NOT dropped when empty (unlike the frontend's default
    partitioning): every one of them is still a real object the composed
    engine/exporter has to know about (an object holding only nested child
    objects and no elements of its own is legitimate, see
    `_resolve_object_bounds`), so only the free pool -- which has no
    identity of its own beyond "wherever an element's objectId is absent"
    -- gets this special case.

    Objects only: a caller that also needs `model.links` translated into
    `ComposedLinkSpec` dicts has to remap each one's `source_object`/
    `target_object` through the SAME wire-index shift this function
    computes internally (dropping the free pool shifts every later
    object's position by one) -- not done here, since no caller of this
    function needs links yet (see this change's report for the
    feasibility note on `simulate_composed._resolve_composed_model`).
    """
    included = [
        obj for obj in model.objects
        if not (obj.free and not obj.net.places and not obj.net.transitions)
    ]
    # `obj.parent` is a DOMAIN model.objects index; omitting the free pool
    # shifts every later object's position in the WIRE list by one, so a
    # parent reference has to be remapped through this table rather than
    # carried over as-is -- otherwise every parent/child pair after the
    # dropped free pool would point at the wrong wire spec (or out of
    # range entirely).
    wire_index_by_domain_index = {obj.index: i for i, obj in enumerate(included)}
    specs: list[dict[str, Any]] = []
    for obj in included:
        specs.append({
            "name": obj.name,
            "priority": obj.priority,
            "x": obj.x,
            "y": obj.y,
            "width": obj.width,
            "height": obj.height,
            "collapsed": obj.collapsed,
            "parent": (
                wire_index_by_domain_index.get(obj.parent) if obj.parent is not None else None
            ),
            "auto_fit": obj.auto_fit,
            "free": obj.free,
            "net_data": obj.net.model_dump(),
        })
    return specs
