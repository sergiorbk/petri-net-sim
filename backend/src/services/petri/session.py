"""PetriNet session - manages builder state for tool execution contexts."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.core.logger import get_logger
from src.core.security_config import security_settings
from src.domain import PetriNet, PatternInterface, PatternResult
from src.domain.composed import ComposedLink, ComposedModel, LinkType
from src.services.petri.builder import PetriNetBuilder
from src.services.petri.composed_convert import (
    FREE_POOL_INDEX,
    composed_model_to_net_data,
    net_data_to_composed_model,
)
from src.services.petri.exporter import get_composed_pnml_exporter, get_pnml_exporter
from src.services.petri.optimizer import is_transfer_transition, optimize_petri_net

if TYPE_CHECKING:
    from src.services.simulation.engine import SimulationResult


@dataclass
class SessionObject:
    """One named Petri-object living inside a composed `PetriNetSession`.

    Mirrors one `ComposedModel.objects` entry (name/priority/x/y/width/
    height/collapsed/auto_fit), plus what `ModelObject` itself cannot carry:
    a persistent `PetriNetBuilder` (so add_*/modify_* tool calls that target
    this object keep the SAME cursor/pattern-instance state across turns,
    exactly like the free pool's builder always has) and a stable string
    `frame_id` (`ModelObject` only has an int `index` -- see
    composed_convert.py's module docstring on why that is not enough to
    round-trip a hand-authored frame id).

    `width`/`height` are `None` until first given an explicit value or
    serialized (`PetriNetSession.to_net_data` auto-derives them from member
    bounds on the way out, mirroring the frontend's own auto-fit frame,
    never mutating this stored `None` back -- see composed_convert.py's
    `_resolve_object_bounds`). `parent_frame_id` is another object's
    `frame_id`, or `None` for a top-level object.
    """

    frame_id: str
    builder: PetriNetBuilder
    name: str
    priority: int = 0
    x: float = 0.0
    y: float = 0.0
    width: Optional[float] = None
    height: Optional[float] = None
    collapsed: bool = False
    parent_frame_id: Optional[str] = None
    auto_fit: Optional[bool] = None
    template_id: Optional[str] = None

    @property
    def net(self) -> PetriNet:
        return self.builder.net


#: The PetriNetBuilder fields PetriNetBuilder.extra_state()/_restore_builder
#: round-trip (pattern-instance registry, layout direction/lock, cluster
#: bounds). Named here, once, so BOTH to_net_data (which serializes them:
#: the free pool at net_data's own root, same as always, and now every
#: named object's OWN builder under that object's own frame dict -- see
#: to_net_data's docstring) and from_net_data (which reads them back from
#: those exact two places) agree on the key set without repeating it.
_BUILDER_EXTRA_STATE_KEYS = (
    "_pattern_instances",
    "_layout_direction",
    "_custom_layout_locked",
    "_cluster_bounds",
)


def _restore_builder(net_data: dict) -> PetriNetBuilder:
    """Reconstruct a PetriNetBuilder from serialized net_data.

    Shared by PetriNetSession.from_net_data and tool_node._get_builder_from_state
    so both paths use identical reconstruction logic. *net_data* is expected
    to carry _BUILDER_EXTRA_STATE_KEYS alongside places/transitions/arcs
    (merged in by the caller when those extras live somewhere else, e.g. a
    per-object frame dict rather than net_data's own root -- see
    from_net_data's composed branch).
    """
    net = PetriNet(**net_data)
    builder = PetriNetBuilder.__new__(PetriNetBuilder)
    builder._net = net
    all_x = (
        [p.graphics.x for p in net.places] +
        [t.graphics.x for t in net.transitions]
    )
    builder._x_cursor = (max(all_x) + 300.0) if all_x else 100.0
    builder._y_cursor = 200.0
    builder._x_step = 500.0
    builder._y_step = 150.0
    builder._pattern_instances = net_data.get("_pattern_instances") or {}
    builder._layout_direction = net_data.get("_layout_direction") or "LR"
    builder._custom_layout_locked = bool(net_data.get("_custom_layout_locked", False))
    builder._cluster_bounds = net_data.get("_cluster_bounds") or {}
    builder._populate_patterns()
    builder._install_builder_methods()
    return builder


def _dedupe_source_ids(source_net: PetriNet, moving_ids: set[str], dest_ids: set[str]) -> dict[str, str]:
    """Rename any id in *moving_ids* (elements about to leave *source_net*
    for a destination whose current ids are *dest_ids*) that would
    collide there, directly on *source_net* itself: its own places,
    transitions, arcs, and private `_node_index`. Returns {old_id:
    new_id} for whatever was actually renamed (possibly empty).

    Deliberately done here, on ONE well-scoped PetriNet whose own ids ARE
    guaranteed locally unique, rather than on the flattened net_data a
    composed session serializes to: a composed model does NOT guarantee
    ids are unique ACROSS objects (domain/composed/model.py), so two
    different objects can easily both have a place "p1" -- renaming by a
    bare id string against net_data's one flat places[] array cannot tell
    apart which occurrence a rename should touch, and mutates every
    matching id it finds regardless of which object it belongs to. Fixed
    on ONE net first, so by the time this session gets to net_data (and
    to net_data_to_composed_model's owner-by-id bucket lookup) the two
    nets actually involved in this move no longer collide with each
    other (a THIRD, unrelated object could still coincidentally share an
    id with one of them -- a pre-existing gap this move does not
    introduce and is not responsible for closing, see
    `_reserve_known_ids`'s own docstring).

    Needed because `move_elements_to_object`/`remove_object` perform a REAL
    merge of two independent PetriNets (unlike `_reserve_known_ids`, which
    only reserves ids in advance so FUTURE auto-generated ones avoid a
    collision): two objects built independently can easily both hold a
    place called "p1", and the merge this function protects is exactly
    the moment such a pre-existing collision would otherwise silently
    produce one PetriNet with two same-id places, invisible until export.

    Scoped to place/transition ids only, matching `_reserve_known_ids`'s
    own documented scope -- arc-id collisions across a merge remain an
    unaddressed, pre-existing gap (see that function's docstring: "not
    arc ids... flagged as a known follow-up"), out of scope here for the
    same reason.
    """
    all_ids = {p.id for p in source_net.places} | {t.id for t in source_net.transitions}
    rename: dict[str, str] = {}
    for old_id in moving_ids:
        if old_id not in dest_ids:
            continue
        is_place = source_net.get_place(old_id) is not None
        prefix = "p" if is_place else "t"
        n = 1
        candidate = f"{prefix}{n}"
        occupied = all_ids | set(rename.values())
        while candidate in occupied:
            n += 1
            candidate = f"{prefix}{n}"
        rename[old_id] = candidate
        all_ids.add(candidate)

    if not rename:
        return rename

    for p in source_net.places:
        if p.id in rename:
            p.id = rename[p.id]
    for t in source_net.transitions:
        if t.id in rename:
            t.id = rename[t.id]
    for a in source_net.arcs:
        a.source_id = rename.get(a.source_id, a.source_id)
        a.target_id = rename.get(a.target_id, a.target_id)
    source_net._rebuild_index()
    return rename


def _is_composed_shape(net_data: dict) -> bool:
    """Whether net_data carries Petri-object structure at all: a non-empty
    `objects` or `links` array, or any place/transition tagged with
    `objectId`. Mirrors frontend/src/types/petri.ts's own PetriNetData
    comment verbatim ("Absent/empty = today's flat net, unchanged behavior
    everywhere") -- an empty `objects: []`/`links: []` is NOT composed, the
    same as their being absent entirely, so a session round-tripped through
    a layer that always emits these keys (even empty) still takes the flat
    path and stays byte-identical.
    """
    if net_data.get("objects") or net_data.get("links"):
        return True
    if any(p.get("objectId") for p in net_data.get("places", [])):
        return True
    if any(t.get("objectId") for t in net_data.get("transitions", [])):
        return True
    return False


#: Public alias for cross-module use by code that works with a raw net_data
#: dict directly and never constructs a PetriNetSession -- e.g. the
#: sessions.py REST simulate endpoints, which must refuse composed net_data
#: with a clear error instead of routing it through the flat-net-only
#: engine. Same function as _is_composed_shape, exported under a name
#: without a leading underscore since it is a legitimate cross-module
#: dependency, not an internal helper reaching outside this module.
is_composed_net_data = _is_composed_shape


@dataclass
class SessionLink:
    """One cross-object link, addressed by ELEMENT ID within its owning
    object's own frame_id (`None` for the free pool) -- NOT by the domain
    `ComposedLink`'s (object index, element index) position.

    This is deliberate and replaces an earlier position-addressed `_links`
    (a plain `list[ComposedLink]`, copied straight from whatever
    `net_data_to_composed_model` last computed): a place/transition's
    position in its object's own `places[]`/`transitions[]` array shifts
    every time an EARLIER element in that same list is removed, so a link
    recorded by position went silently stale -- still structurally valid
    (in range), just pointing at the WRONG element -- the moment a remove_*
    op ran on anything before it. An id, once minted, never moves.

    Resolved to a position-addressed `ComposedLink` ONLY at the boundary
    that actually needs one: `PetriNetSession._build_composed_model`
    (i.e. every consumer of `to_net_data`/`build_composed_model`/
    `export_pnml`/`run_simulation`/`validate_model`), by looking up each
    element id's CURRENT position in its owning net at build time -- so a
    link this class carries is always resolved fresh, never stale.

    `source_frame_id`/`target_frame_id` name a `SessionObject.frame_id`, or
    `None` for the free pool -- the same convention `resolve_element_ref`'s
    object_name parameter and `net_for` use, NOT the free-pool-is-index-0
    convention `ComposedLink`/`_build_composed_model` still use internally
    (ids don't need a fixed reserved slot the way positions did).
    """

    link_type: LinkType
    source_frame_id: Optional[str]
    source_element_id: str
    target_frame_id: Optional[str]
    target_element_id: str
    quantity: int = 1
    informational: bool = False


def _session_link_from_composed(
    model: ComposedModel, link: ComposedLink, frame_id_by_bucket: dict[int, str | None],
) -> SessionLink:
    """One position-addressed `ComposedLink` (as `net_data_to_composed_model`
    just produced it) translated into an id-addressed `SessionLink`, via
    `ComposedModel.resolve_link_endpoint` (the same lookup
    `composed_model_to_net_data` itself uses to write net_data's own
    id-addressed `links[].sourceId`/`targetId`) and *frame_id_by_bucket*
    (bucket index -> that object's real frame_id; see from_net_data's
    composed branch, the only caller). Called only at LOAD time, while the
    positions `link` carries are still guaranteed fresh -- never later, see
    SessionLink's own docstring on why a position goes stale.
    """
    source_id, _ = model.resolve_link_endpoint(link, "source")
    target_id, _ = model.resolve_link_endpoint(link, "target")
    return SessionLink(
        link_type=link.type,
        source_frame_id=frame_id_by_bucket.get(link.source_object),
        source_element_id=source_id,
        target_frame_id=frame_id_by_bucket.get(link.target_object),
        target_element_id=target_id,
        quantity=link.quantity,
        informational=link.informational,
    )


logger = get_logger()


def _find_pattern_connectors(
    net: PetriNet, instances: dict[str, dict]
) -> list[tuple[str, str, str]]:
    """Find the pass-through transitions that join two patterns, and the
    pairs of ports each of them joins.

    `PetriNetBuilder.connect` cannot draw a place straight to a place, so
    it inserts a zero-delay transition between them. That transition is
    pure plumbing: it belongs to no pattern, carries no delay, priority or
    weight of its own, and exists only because a flat net has no other way
    to say "this hands off to that". A composed model does have a way --
    fusing the two places -- so the plumbing comes out and the meaning
    stays, with both patterns still whole.

    Only connectors whose two sides belong to two DIFFERENT patterns are
    touched. Anything else, including a pass-through the agent built on
    purpose in the middle of its own net, is left exactly where it is.

    Pure: reports what could be dissolved without touching `net`, so the
    caller can decide whether the split is going ahead at all before
    anything is removed. Removing a connector severs the only path between
    two patterns, and only a place-fusion link between two OBJECTS puts it
    back -- so a run that dissolves and then declines to frame would leave
    the flow cut. See `_remove_connectors`.

    Returns `(transition_id, source_place_id, target_place_id)` per
    dissolvable connector, in net order.
    """
    owner: dict[str, str] = {}
    for name, instance in instances.items():
        for element in (*instance["place_ids"], *instance["transition_ids"]):
            owner[element] = name

    found: list[tuple[str, str, str]] = []
    for transition in list(net.transitions):
        if transition.id in owner or not is_transfer_transition(net, transition):
            continue
        incoming = net.get_arcs_to(transition.id)[0]
        outgoing = net.get_arcs_from(transition.id)[0]
        source_owner = owner.get(incoming.source_id)
        target_owner = owner.get(outgoing.target_id)
        if source_owner is None or target_owner is None or source_owner == target_owner:
            continue
        found.append((transition.id, incoming.source_id, outgoing.target_id))
    return found


def _remove_connectors(net: PetriNet, connectors: list[tuple[str, str, str]]) -> None:
    """Delete the connector transitions found by `_find_pattern_connectors`,
    with the two arcs each of them owns. Only called once the split is
    certain to happen, so the place-fusion links that take their place are
    certain to be created."""
    for transition_id, _, _ in connectors:
        for arc in [*net.get_arcs_to(transition_id), *net.get_arcs_from(transition_id)]:
            net.remove_arc(arc.id)
        net.remove_transition(transition_id)


def _group_by_object_boundary(
    net: PetriNet,
    instances: dict[str, dict],
    without: frozenset[str] = frozenset(),
) -> list[tuple[str, list[str], list[str]]]:
    """Partition a flat net into the largest set of parts that can each be
    their own Petri-object, keeping only the parts that contain a pattern.

    Two elements have to share an object when an arc runs from a place to a
    transition across them: a composed model cannot express that crossing,
    because placeToTransition links are retired, whereas the opposite
    direction is an ordinary transitionToPlace link. A pattern's own members
    are held together too -- a machine is one block whether or not its
    internal wiring happens to force it.

    `without` names elements that are about to be removed (the connectors
    from `_find_pattern_connectors`): they are left out of the partition
    and so are their arcs, so the grouping describes the net as it will be
    rather than as it still is.

    Returns `(object_name, member_ids, pattern_names)` per part, ordered by
    the creation order of the first pattern in each, so the result is stable
    across runs. A part holding several patterns is named after all of them:
    it exists because they could not be separated, and saying so beats
    picking one of their names and hiding the rest.
    """
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    place_ids = {p.id for p in net.places} - without
    transition_ids = {t.id for t in net.transitions} - without
    for element in (*place_ids, *transition_ids):
        find(element)
    for instance in instances.values():
        members = [
            element
            for element in (*instance["place_ids"], *instance["transition_ids"])
            if element in parent
        ]
        for member in members[1:]:
            union(members[0], member)
    for arc in net.arcs:
        if arc.source_id in without or arc.target_id in without:
            continue
        if arc.source_id in place_ids and arc.target_id in transition_ids:
            union(arc.source_id, arc.target_id)

    members_by_root: dict[str, list[str]] = {}
    for element in parent:
        members_by_root.setdefault(find(element), []).append(element)

    order = {name: i for i, name in enumerate(instances)}
    parts: list[tuple[str, list[str], list[str]]] = []
    for members in members_by_root.values():
        member_set = set(members)
        names = [
            name
            for name, instance in instances.items()
            if set(instance["place_ids"]) | set(instance["transition_ids"]) <= member_set
        ]
        if not names:
            continue  # loose elements belonging to no pattern stay free
        parts.append(("_".join(names), sorted(members), names))
    parts.sort(key=lambda part: order[part[2][0]])
    return parts


class PetriNetSession:
    """
    Manages a PetriNetBuilder instance with session-aware state.

    Encapsulates builder lifecycle, auto-connection tracking, and
    serialization. Used by both MCP server and LangGraph tool node.

    Composed structure (Petri-objects): a session holds an implicit FREE
    pool (`_free_builder` -- exactly today's one-and-only net, untouched by
    every session that never uses object tools) plus zero or more named
    `SessionObject`s (`_objects`) and cross-object `SessionLink`s
    (`_links`, id-addressed -- see that class's own docstring for why).
    `_active_object` is `None` for the free pool (the default, and the
    only state a session that never touched object tools is ever in) or an
    index into `_objects`; `builder`/`net` below always resolve to
    whichever one is active, which is what lets every existing
    add_*/modify_* operation in agent_toolkit/operations.py target the
    active object's net with NO changes of its own -- they already only
    ever go through `session.builder`/`session.net`.
    """

    def __init__(self, auto_optimize: bool = True) -> None:
        self._free_builder = PetriNetBuilder()
        self._objects: list[SessionObject] = []
        self._links: list[SessionLink] = []
        self._active_object: int | None = None
        self._last_output_place_id: str | None = None
        self._has_custom_topology: bool = False
        self._raw_element_ids: set[str] = set()
        self._is_optimized: bool = True  # fresh empty network needs no optimization
        # Session-level switch (see operations.py's documented-divergence
        # list): when False, optimize_if_needed() never runs on its own --
        # only an explicit optimize_network call touches the net. The MCP
        # adapter leaves this at its default (True); the chat tool_node
        # constructs every session with it False, restoring the pre-catalog
        # chat behavior where nothing but optimize_network ever fused
        # Transfer transitions.
        self._auto_optimize: bool = auto_optimize
        # Set for a turn that is building a composed (Petri-object) model:
        # it makes `optimize` leave every pattern's own elements alone, so
        # the hand-off place between two patterns survives as the seam each
        # of them can still be framed along. Not part of net_data -- it
        # describes THIS turn's intent, not the net. See `optimize`.
        self.protect_pattern_ports: bool = False
        # Last run_simulation result, kept in memory only (not part of
        # to_net_data/from_net_data, a SimulationResult is not net state,
        # and the session object itself is the unit of persistence for
        # whichever adapter holds it across calls). See
        # agent_toolkit.operations.op_get_simulation_results.
        self._last_simulation_result: Optional["SimulationResult"] = None
        # Formatted text of the last simulation result, IS part of
        # to_net_data/from_net_data (see _last_simulation_result_text
        # below) so a chat session rehydrated fresh from net_data in a
        # later turn can still answer get_simulation_results without the
        # in-memory SimulationResult, which does not survive that
        # rehydration. See agent_toolkit.operations.op_get_simulation_results.
        self._last_simulation_summary: str | None = None

    @classmethod
    def from_net_data(cls, net_data: dict, auto_optimize: bool = True) -> "PetriNetSession":
        """Reconstruct session from serialized net_data dict.

        Accepts both the legacy flat shape (places/transitions/arcs only)
        and the composed shape (places/transitions optionally carrying
        `objectId`, plus optional `objects`/`links`) -- see class
        docstring and composed_convert.py. A net_data dict with no
        objectId anywhere and no (non-empty) objects/links key is treated
        as flat, byte-identically to how this method always worked, so a
        session that was never touched by object tools round-trips exactly
        as before.
        """
        session = cls.__new__(cls)
        session._auto_optimize = auto_optimize
        session._objects = []
        session._links = []
        session._active_object = None

        if not net_data or (not net_data.get("places") and not _is_composed_shape(net_data)):
            session._free_builder = PetriNetBuilder()
            session._last_output_place_id = None
            session._has_custom_topology = False
            session._raw_element_ids = set()
            session._is_optimized = True
            session._last_simulation_result = None
            session._last_simulation_summary = None
            return session

        if not _is_composed_shape(net_data):
            session._free_builder = _restore_builder(net_data)
            session._last_output_place_id = net_data.get("_last_output_place_id")
            session._has_custom_topology = net_data.get("_has_custom_topology", False)
            session._raw_element_ids = set()
            session._is_optimized = net_data.get("_is_optimized", False)
            session._last_simulation_result = None
            session._last_simulation_summary = net_data.get("_last_simulation_result_text")
            return session

        model = net_data_to_composed_model(net_data)
        free_obj = model.objects[FREE_POOL_INDEX]
        # The free pool's OWN builder extras (_pattern_instances etc.) live
        # at net_data's root, same as the flat path above -- NOT on
        # free_obj.net.model_dump(), which is a bare PetriNet dump with no
        # extra keys at all. Merging them in here is what makes the free
        # pool's layout/pattern state survive a COMPOSED round trip exactly
        # like it always has for a flat one (previously silently lost).
        free_data = free_obj.net.model_dump()
        free_data.update({k: net_data[k] for k in _BUILDER_EXTRA_STATE_KEYS if k in net_data})
        session._free_builder = _restore_builder(free_data)

        # net_data_to_composed_model builds model.objects[1:] in exactly the
        # same order as net_data["objects"] (see its docstring), so the two
        # zip up positionally -- this is how the ORIGINAL frame id and
        # templateId (neither of which ComposedModel/ModelObject has a
        # field for) survive the round trip despite going through it.
        raw_frames = net_data.get("objects") or []
        # bucket index (free pool=0, named object i -> i+1, matching
        # net_data_to_composed_model's own fixed convention) -> that
        # object's own frame_id (None for the free pool) -- used right
        # below to translate model.links' position addressing into this
        # session's id-addressed SessionLinks, once, while the bucket
        # layout net_data_to_composed_model just computed is still known.
        frame_id_by_bucket: dict[int, str | None] = {FREE_POOL_INDEX: None}
        for i, (m_obj, raw_frame) in enumerate(zip(model.objects[1:], raw_frames)):
            frame_id_by_bucket[i + 1] = raw_frame["id"]
            # Same reasoning as the free pool above: this object's own
            # builder extras live on ITS raw frame dict (see to_net_data),
            # not on m_obj.net.model_dump().
            obj_data = m_obj.net.model_dump()
            obj_data.update({k: raw_frame[k] for k in _BUILDER_EXTRA_STATE_KEYS if k in raw_frame})
            session._objects.append(
                SessionObject(
                    frame_id=raw_frame["id"],
                    builder=_restore_builder(obj_data),
                    name=m_obj.name,
                    priority=m_obj.priority,
                    x=m_obj.x,
                    y=m_obj.y,
                    width=m_obj.width,
                    height=m_obj.height,
                    collapsed=m_obj.collapsed,
                    parent_frame_id=raw_frame.get("objectId"),
                    auto_fit=m_obj.auto_fit,
                    template_id=raw_frame.get("templateId"),
                )
            )
        # model.links is position-addressed (see SessionLink's docstring on
        # why this class does not keep it that way): translate each one to
        # an id-addressed SessionLink while positions are still known to be
        # accurate (nothing has moved yet -- this IS the load that just
        # produced them).
        session._links = [
            _session_link_from_composed(model, link, frame_id_by_bucket)
            for link in model.links
        ]
        session._reserve_ids_everywhere()

        # Restore which object was active (see to_net_data's matching
        # comment). session._active_object already defaults to None (free
        # pool) from this method's top, so a session serialized before this
        # key existed, or one whose active frame_id no longer matches any
        # restored object (e.g. that object was since removed by whatever
        # produced this net_data), correctly falls back to the free pool
        # rather than raising.
        active_frame_id = net_data.get("_active_object_id")
        if active_frame_id is not None:
            for i, restored_obj in enumerate(session._objects):
                if restored_obj.frame_id == active_frame_id:
                    session._active_object = i
                    break

        session._last_output_place_id = net_data.get("_last_output_place_id")
        session._has_custom_topology = net_data.get("_has_custom_topology", False)
        session._raw_element_ids = set()
        session._is_optimized = net_data.get("_is_optimized", False)
        session._last_simulation_result = None
        session._last_simulation_summary = net_data.get("_last_simulation_result_text")
        return session

    @property
    def builder(self) -> PetriNetBuilder:
        """The active builder: the free pool's, or the active object's."""
        if self._active_object is None:
            return self._free_builder
        return self._objects[self._active_object].builder

    def apply_layout_direction(self, direction: str) -> list[str]:
        """Lay every part of this session out in `direction` ("LR"/"TB").

        The free pool and each named object carry their OWN PetriNetBuilder,
        so a direction applied to the active one only would leave the rest
        of a composed model flowing the other way. Returns the names of the
        parts that actually changed ("free pool" for the pool itself), empty
        when everything already flowed that way.

        A builder ALREADY facing `direction` is left completely alone rather
        than re-laid-out. That is what keeps this safe to call on every turn:
        re-running the layout would also clear `_custom_layout_locked` and
        discard a deliberate `arrange_patterns` placement, so the only thing
        that may undo a manual arrangement is an actual change of direction,
        which is a direct instruction to re-flow the net.
        """
        changed: list[str] = []
        parts = [("free pool", self._free_builder)]
        parts += [(obj.name, obj.builder) for obj in self._objects]
        for name, builder in parts:
            if builder.layout_direction == direction:
                continue
            builder.set_layout_direction(direction)
            changed.append(name)
        return changed

    @property
    def net(self) -> PetriNet:
        """Access the current (active) PetriNet."""
        return self.builder.net

    @property
    def active_object_index(self) -> int | None:
        """`None` (free pool) or an index into `objects`."""
        return self._active_object

    @property
    def objects(self) -> list[SessionObject]:
        """Named objects in this session, in creation order. Read-only view."""
        return list(self._objects)

    @property
    def links(self) -> list[SessionLink]:
        """Cross-object links, id-addressed. See SessionLink's own docstring."""
        return list(self._links)

    def _exportable_object_count(self) -> int:
        """How many object specs this session would actually produce for
        the composed wire body (POST /api/v1/simulate/composed): every
        named object, unconditionally, plus the free pool ONLY when it
        holds at least one place or transition -- mirroring the frontend's
        buildComposedRequest (composed-simulation-client.ts's
        partitionIntoObjects, includeEmptyObjects=false) and
        composed_convert.composed_model_to_wire_objects, which both drop an
        empty free pool rather than spend one of the wire body's
        SIMULATION_MAX_OBJECTS slots on nothing. Used by create_object's
        own cap check so a session it lets through still fits that wire
        body, not just this session's own in-process ComposedModel (which
        always carries the free pool regardless of emptiness -- see
        _build_composed_model -- so counting THAT would undercount by one
        exactly when the free pool is non-empty).
        """
        free_net = self._free_builder.net
        free_counts = bool(free_net.places or free_net.transitions)
        return len(self._objects) + (1 if free_counts else 0)

    def _session_max_x(self) -> float:
        """Rightmost extent of every element already in the session (free
        pool plus every existing object's own net), so a freshly created
        object's builder can start clear of them.

        Each object's `PetriNetBuilder` starts its OWN cursor at the same
        fixed (100, 200) default (see `PetriNetBuilder.__init__`) with no
        knowledge of any other object's net -- without this, a second and
        third `create_object` call would place their elements right on top
        of the first object's, and the whole composed model would render as
        one tiny overlapping clump instead of spreading left to right.
        """
        all_x = [
            x
            for net in (self._free_builder.net, *(o.net for o in self._objects))
            for x in (
                [p.graphics.x for p in net.places] + [t.graphics.x for t in net.transitions]
            )
        ]
        return max(all_x) if all_x else 100.0

    def create_object(
        self, name: str, priority: int = 0, parent: str | None = None,
    ) -> int:
        """Create a new, empty named object and make it active.

        *parent* is another object's name, making the new one a module
        INSIDE it: a Petri-object may hold plain places and transitions and
        other Petri-objects at the same time, and nesting is how a model
        says "this whole assembly is one part of that bigger one". The
        frame, the layout and the serializer have always supported it (see
        `SessionObject.parent_frame_id`); only the way to ask for it was
        missing.

        Returns its index (0-based, among named objects only -- see class
        docstring on why this differs from a `_links` entry's object
        index). The response text a tool call builds around this ("created
        and active; use set_active_object() with no argument to switch back
        to the free pool") is agent_toolkit's job (catalog part B), not
        this session-level primitive's.

        Also resets `_last_output_place_id`: auto_connect's "wire the new
        pattern's input to the last pattern's output" convenience must
        never silently reach across the object boundary this call just
        created (it would draw an arc between two elements in different
        nets, which PetriNet.add_arc doesn't have any legitimate way to
        represent) -- the new object starts with no "last output" to chain
        from, exactly like a brand-new session does.
        """
        if self._exportable_object_count() >= security_settings.SIMULATION_MAX_OBJECTS:
            raise ValueError(
                "Cannot create object: composed models are capped at "
                f"{security_settings.SIMULATION_MAX_OBJECTS} objects."
            )
        parent_frame_id: str | None = None
        if parent is not None:
            try:
                parent_frame_id = self._objects[self.find_object_index(parent)].frame_id
            except ValueError as exc:
                # Naming a parent that does not exist is an ORDERING slip,
                # not a change of plan: the caller has a hierarchy in mind
                # and reached for the outer part before building it. Saying
                # only "no such object" invites giving the nesting up and
                # creating this one flat, which loses the structure the
                # caller was describing. Say what to do instead.
                raise ValueError(
                    f"{exc} Create the parent first -- "
                    f"create_object('{parent}') -- then create '{name}' with "
                    f"parent='{parent}' again. Do not drop the nesting: the "
                    "outer object is part of the structure."
                ) from exc
        frame_id = self._next_frame_id()
        new_builder = PetriNetBuilder(name=name)
        # Start past everything already in the session -- see _session_max_x.
        new_builder._x_cursor = self._session_max_x() + 300.0
        self._objects.append(
            SessionObject(
                frame_id=frame_id,
                builder=new_builder,
                name=name,
                priority=priority,
                parent_frame_id=parent_frame_id,
            )
        )
        self._reserve_ids_everywhere()
        index = len(self._objects) - 1
        self._active_object = index
        self._last_output_place_id = None
        return index

    def ensure_patterns_in_objects(self) -> list[str]:
        """Give each pattern built in the free pool its own Petri-object.

        Deterministic fallback for the chat workbench's Object net-style
        mode (chat_node.py's DEFAULT_NET_STYLE): the agent is told to call
        create_object per logical block, and a smaller/faster model still
        routinely builds the whole thing flat instead. The patterns it used
        ARE the logical blocks, already recorded by name and membership in
        the builder's own registry, so the frames can simply be drawn round
        them after the fact.

        What it deliberately does NOT do is wrap the whole net in a single
        object. One frame around everything says nothing a plain flat net
        did not already say, and it is not what a composed model is for.
        So: no patterns, no frames; and if every pattern turns out to be
        inseparable from the others (below), that is a failure to decompose
        and is left visible rather than papered over with one big frame.

        Connectors go first. `PetriNetBuilder.connect` wires two patterns
        by inserting a pass-through transition between their two ports;
        that transition carries no behaviour and belongs to neither
        pattern, so it is dissolved and the two ports are fused with a
        link instead. The composed model then says exactly what the flat
        net meant -- one pattern hands off to the next -- with nothing
        synthetic left standing between them, and with BOTH ports intact.
        (Fusing the two places into one, which is what the topology
        optimizer does to the same shape, would delete one of those ports
        and with it the seam this pass needs. Hence
        `protect_pattern_ports`.)

        Grouping rule for whatever connectors remain: the ONLY thing that
        forces two elements into the same object is an arc from a place to
        a transition, because a composed model has no way to express that
        crossing -- placeToTransition links are retired -- while the
        opposite direction is an ordinary transitionToPlace link. A
        connector that was not dissolved (one whose sides are not two
        different patterns' ports) is therefore pulled into the object of
        the place feeding it, with no special case needed.

        A no-op when this session already has an object: this is a safety
        net for the "built nothing but flat" case, not a policy override of
        a structure the agent deliberately built.

        Returns the names of the objects created, in creation order.
        """
        if self._objects:
            return []
        builder = self._free_builder
        instances = builder.pattern_instances
        if not instances:
            return []

        # Everything below decides BEFORE it changes anything. Removing a
        # connector severs the only path between two patterns, and only a
        # link between two OBJECTS puts it back, so a run that gave up
        # halfway would leave the flow cut. Either the whole split happens
        # or the net is left exactly as it was.
        candidates = _find_pattern_connectors(builder.net, instances)
        # Which connectors are worth dissolving depends on where the split
        # actually falls, so the partition is computed first with all of
        # them out of the way. A connector whose two ports land in the SAME
        # object after that (its patterns are held together by some other
        # path) must be KEPT: a place-fusion link inside one object is not
        # a link at all, it is healed away, and the hand-off it replaced
        # would simply be gone. Re-including those cannot merge two objects
        # that were separate -- each one joins a pair already together --
        # so the partition only has to be recomputed once.
        groups = _group_by_object_boundary(
            builder.net, instances, frozenset(c[0] for c in candidates)
        )
        group_of = {
            member: index
            for index, (_, members, _) in enumerate(groups)
            for member in members
        }
        connectors = [
            connector
            for connector in candidates
            if group_of.get(connector[1], -1) != group_of.get(connector[2], -2)
        ]
        if len(connectors) != len(candidates):
            groups = _group_by_object_boundary(
                builder.net, instances, frozenset(c[0] for c in connectors)
            )
        if len(groups) == 1 and len(instances) > 1:
            logger.info(
                "Object mode: %d patterns are wired place-to-transition into one "
                "inseparable block; leaving the net flat rather than framing all "
                "of it as a single object.",
                len(instances),
            )
            return []
        # +1: the free pool counts towards the cap too while it still holds
        # anything, and it does until the last group has moved out.
        if len(groups) + 1 > security_settings.SIMULATION_MAX_OBJECTS:
            logger.warning(
                "Object mode: %d pattern groups would exceed the %d-object cap; "
                "leaving the net flat.",
                len(groups), security_settings.SIMULATION_MAX_OBJECTS,
            )
            return []

        _remove_connectors(builder.net, connectors)
        fusions = [(source, target) for _, source, target in connectors]
        element_count = len(builder.net.places) + len(builder.net.transitions)

        created: list[tuple[str, list[str]]] = []
        for name, members, pattern_names in groups:
            self.set_active_object(None)
            self.create_object(name)
            self.set_active_object(None)
            self.move_elements_to_object(members, name)
            created.append((name, pattern_names))
            self._free_builder.drop_pattern_instances(pattern_names)

        # Handing the registrations over is a SECOND pass on purpose. Each
        # move above is a full round trip that re-fits and re-spreads every
        # frame, and adopting mid-loop would lay one object out at the
        # origin only for the next move to shove it aside again, compounding
        # an offset per object. Doing it once at the end leaves every object
        # laid out from its own origin, and the single spread on the way out
        # separates them from there.
        for name, pattern_names in created:
            index = self.find_object_index(name)
            self._objects[index].builder.adopt_pattern_instances(
                {n: instances[n] for n in pattern_names}
            )
        created = [name for name, _ in created]
        self.set_active_object(None)
        self._relink_dissolved_connectors(fusions)
        if created:
            logger.debug(
                "Object mode: framed %d pattern group(s) out of %d free-pool "
                "elements: %s",
                len(created), element_count, ", ".join(created),
            )
        return created

    def _relink_dissolved_connectors(self, fusions: list[tuple[str, str]]) -> None:
        """Re-state each dissolved connector as a place-fusion link between
        the two ports it used to join, now that they live in objects."""
        frame_of: dict[str, str] = {}
        for obj in self._objects:
            for place in obj.net.places:
                frame_of[place.id] = obj.frame_id
        for source_id, target_id in fusions:
            source_frame = frame_of.get(source_id)
            target_frame = frame_of.get(target_id)
            if source_frame is None or target_frame is None:
                # Unreachable: a connector is only removed once every group
                # is known to be framable, and its two ports are by
                # definition members of two patterns. Guarded anyway --
                # the alternative to a link here is a severed flow.
                logger.error(
                    "Object mode: no frame for the fused pair %s/%s; the "
                    "hand-off between them is now unwired.",
                    source_id, target_id,
                )
                continue
            self.add_link(
                LinkType.PLACE_FUSION, source_frame, source_id, target_frame, target_id
            )

    def _reserve_ids_everywhere(self) -> None:
        """Best-effort id-collision mitigation: register every net in this
        session (free pool + every object) with every OTHER net's current
        place/transition/arc ids as RESERVED (PetriNet.reserve_ids -- an
        id-minting hint only, never visible to a lookup; see that method's
        own docstring for why this replaced seeding `_node_index` directly,
        which used to defeat `add_arc`'s existence check for a foreign id).
        Covers arc ids too (the prior mitigation's documented gap: two
        objects independently auto-numbering their first arc "arc1" could
        not previously be steered apart). Called whenever a net could newly
        need to know about ids it did not before: `create_object` (the new,
        still-empty object learns everyone else's ids) and `from_net_data`'s
        composed branch (every restored object learns about every OTHER
        restored object's ids, a snapshot as of load time).
        """
        all_nets = [self._free_builder.net, *(o.net for o in self._objects)]
        all_ids: set[str] = set()
        for net in all_nets:
            all_ids.update(p.id for p in net.places)
            all_ids.update(t.id for t in net.transitions)
            all_ids.update(a.id for a in net.arcs)
        for net in all_nets:
            own_ids = (
                {p.id for p in net.places}
                | {t.id for t in net.transitions}
                | {a.id for a in net.arcs}
            )
            net.reserve_ids(all_ids - own_ids)

    def set_active_object(self, index: int | None = None) -> None:
        """Switch which net add_*/modify_* operations target.

        `None` (the default) selects the free pool; an int selects
        `objects[index]`, and must be in range.

        Also resets `_last_output_place_id` -- see create_object's own
        docstring for why: switching objects must never leave a stale
        "last output" pointing into the net just switched AWAY from, which
        the next auto_connect call would otherwise try to wire across the
        object boundary this call just crossed.
        """
        if index is not None and not (0 <= index < len(self._objects)):
            raise ValueError(
                f"No object at index {index}. This session has {len(self._objects)} object(s)."
            )
        self._active_object = index
        self._last_output_place_id = None

    @property
    def is_composed(self) -> bool:
        """Whether this session has any named object or link -- i.e.
        whether it needs the composed code paths (ComposedPNMLExporter,
        the composed local simulation engine, ComposedModel.validate())
        rather than the flat ones. A session no object tool ever touched
        is never composed, matching to_net_data's own flat/composed split.
        """
        return bool(self._objects or self._links)

    @property
    def has_any_content(self) -> bool:
        """Whether this session holds anything a destructive operation
        (op_import_pnml's replace=False guard, chiefly) should refuse to
        silently overwrite: a place, transition or arc anywhere (the free
        pool, or any named object's own net -- unlike checking `self.net`
        alone, which only ever sees the ACTIVE net and would otherwise
        misreport "empty" for a composed session whose active object, or
        the free pool, simply happens to be the empty one right now), any
        named object itself (creating one is deliberate structure even
        before it holds an element), or any cross-object link.

        Checking places alone (as this used to) let replace=False sail
        straight through a transitions-only net (a transition with no
        place yet, e.g. mid-build), an arcs-bearing net whose places had
        already been optimized away, or a composed session whose only
        content so far is the object/link scaffolding itself -- wiping
        all of it with no error.
        """
        def _net_has_content(net: PetriNet) -> bool:
            return bool(net.places or net.transitions or net.arcs)

        if _net_has_content(self._free_builder.net):
            return True
        if any(_net_has_content(o.net) for o in self._objects):
            return True
        return bool(self._objects or self._links)

    def net_for(self, object_index: int | None) -> PetriNet:
        """The PetriNet for the free pool (`None`) or `objects[object_index]`
        -- `object_index` uses THIS property's own 0-based, named-objects-
        only convention (matching `active_object_index`/`create_object`),
        not the free-pool-is-index-0 convention `_build_composed_model`
        uses internally when it resolves a `SessionLink` to a
        position-addressed `ComposedLink` (see that class's own docstring).
        """
        if object_index is None:
            return self._free_builder.net
        return self._objects[object_index].net

    def build_composed_model(self) -> ComposedModel:
        """Public entry point for a Part B operation (validate_model,
        run_simulation, export_pnml) that needs this session's full
        ComposedModel regardless of which object is currently active. A
        thin, stable wrapper around `_build_composed_model` so callers
        outside this module are not reaching past a leading underscore.
        """
        return self._build_composed_model()

    def find_object_index(self, name: str) -> int:
        """Resolve an object name to its 0-based index into `objects`
        (the SAME convention `active_object_index`/`create_object`/
        `set_active_object` use). Raises ValueError, naming every object
        currently in this session, when *name* matches none of them or
        more than one of them -- object tools address an object by name
        only, so an ambiguous name cannot be disambiguated any other way
        here; give the objects distinct names first.
        """
        matches = [i for i, o in enumerate(self._objects) if o.name == name]
        if not matches:
            available = ", ".join(o.name for o in self._objects) or "(none)"
            raise ValueError(f"No object named '{name}'. Objects in this session: {available}.")
        if len(matches) > 1:
            raise ValueError(
                f"Object name '{name}' is ambiguous: {len(matches)} objects share it, "
                "and object tools address by name. Give them distinct names "
                "(e.g. by editing net_data directly) before targeting one here."
            )
        return matches[0]

    def resolve_element_ref(
        self, object_name: str | None, element_ref: str, role: str = "source",
    ) -> tuple[str | None, str, str]:
        """(owning frame_id, element id, kind) for one link/move endpoint,
        addressed by *object_name* (`None` = free pool) and *element_ref*
        (an id or a name, id tried first since ids are unambiguous by
        construction) within that one object's own net. `kind` is "place"
        or "transition". Raises ValueError, naming the object and the
        element, when *element_ref* matches nothing or more than one
        element there.

        A PATTERN INSTANCE name resolves to that pattern's own port, which
        is what *role* selects: "source" gives the output place (what the
        pattern hands on), "target" the input place (what it receives).
        That is the same pairing `connect` makes, and it is what a caller
        means by "link the Queue to Processor1" -- the alternative was
        having to remember that the queue built as "TaskQueue" holds a
        place called "TaskQueue_Buffer". An element's own name or id always
        wins; the pattern name is only tried when nothing else matched.

        Returns the element's own id (not merely echoing *element_ref*,
        which may have been a NAME) and the owning object's `frame_id`
        (`None` for the free pool) -- the addressing SessionLink/add_link
        use, immune to the element's position shifting later; see
        SessionLink's own docstring.
        """
        if object_name is None:
            frame_id = None
            builder = self._free_builder
            where = "the free pool"
        else:
            obj_idx = self.find_object_index(object_name)
            frame_id = self._objects[obj_idx].frame_id
            builder = self._objects[obj_idx].builder
            where = f"object '{object_name}'"
        net = builder.net

        place = net.get_place(element_ref)
        if place is not None:
            return frame_id, place.id, "place"
        trans = net.get_transition(element_ref)
        if trans is not None:
            return frame_id, trans.id, "transition"

        place_matches = [p for p in net.places if p.name == element_ref]
        trans_matches = [t for t in net.transitions if t.name == element_ref]
        total = len(place_matches) + len(trans_matches)
        if total == 0:
            instance = builder.pattern_instances.get(element_ref)
            if instance is not None:
                port_key = "output_place_id" if role == "source" else "input_place_id"
                port = instance.get(port_key)
                if port is None:
                    end = "produces nothing" if role == "source" else "receives nothing"
                    raise ValueError(
                        f"'{element_ref}' in {where} is a {instance['type']}, which "
                        f"{end}, so it cannot be the {role} of a link. Name one of "
                        "its own places instead (see list_elements)."
                    )
                port_place = net.get_place(port)
                if port_place is not None:
                    return frame_id, port_place.id, "place"
            # Not an id, not an element name, and not a pattern instance
            # here either. List what actually exists so the very next call
            # can use the right one directly, instead of spending a
            # separate list_elements round trip on it.
            available = ", ".join(
                f"{p.id} ({p.name})" for p in net.places
            ) or "(no places)"
            available += "; " + (
                ", ".join(f"{t.id} ({t.name})" for t in net.transitions)
                or "(no transitions)"
            )
            raise ValueError(
                f"No place or transition named or id '{element_ref}' in {where}. "
                f"Use one of these, by NAME rather than by id -- a name is "
                f"echoed by the tool that created it and cannot be confused "
                f"with a neighbour's: {available}."
            )
        if total > 1:
            raise ValueError(
                f"'{element_ref}' is ambiguous in {where}: matches {total} elements. "
                "Use its id instead (see list_elements)."
            )
        if place_matches:
            return frame_id, place_matches[0].id, "place"
        return frame_id, trans_matches[0].id, "transition"

    def add_link(
        self,
        link_type: LinkType,
        source_frame_id: str | None,
        source_element_id: str,
        target_frame_id: str | None,
        target_element_id: str,
        quantity: int = 1,
        informational: bool = False,
    ) -> SessionLink:
        """Create a cross-object link, id-addressed (see SessionLink's own
        docstring), append it, and return it. Endpoint existence is NOT
        checked here, only when a `SessionLink` is next resolved to a
        position-addressed `ComposedLink` (`_build_composed_model`, which
        silently drops one whose frame_id/element_id no longer resolves --
        the id-addressed equivalent of the old "out-of-range endpoint,
        caught later by ComposedModel.validate" contract, still exercised
        by validate_model/export_pnml/run_simulation the same way a
        hand-authored net_data document's own dangling link is).
        """
        link = SessionLink(
            link_type=link_type,
            source_frame_id=source_frame_id,
            source_element_id=source_element_id,
            target_frame_id=target_frame_id,
            target_element_id=target_element_id,
            quantity=quantity,
            informational=informational,
        )
        self._links.append(link)
        return link

    def remove_link(self, position: int) -> SessionLink:
        """Remove and return the link at *position* (0-based into `_links`,
        the same list `links` exposes)."""
        return self._links.pop(position)

    def remove_links_referencing(self, frame_id: str | None, element_id: str) -> list[SessionLink]:
        """Remove and return every link (in `_links` order) with an
        endpoint at (*frame_id*, *element_id*) -- called by
        op_remove_place/op_remove_transition right after the element
        itself is gone, so a link that named it does not linger, silently
        dangling, until the next `_build_composed_model` quietly drops it
        with no one told. *frame_id* is `None` for the free pool, the same
        convention `resolve_element_ref`/`add_link` use.
        """
        kept: list[SessionLink] = []
        removed: list[SessionLink] = []
        for link in self._links:
            touches = (
                (link.source_frame_id == frame_id and link.source_element_id == element_id)
                or (link.target_frame_id == frame_id and link.target_element_id == element_id)
            )
            (removed if touches else kept).append(link)
        self._links = kept
        return removed

    def active_frame_id(self) -> str | None:
        """The active object's `frame_id`, or `None` for the free pool --
        the SessionLink-addressing counterpart to `active_object_index`
        (which uses the `objects`-list convention instead). Used wherever
        an op needs to name the CURRENTLY active object as a link
        endpoint (e.g. remove_links_referencing after a remove_place/
        remove_transition, which always act on the active net).
        """
        if self._active_object is None:
            return None
        return self._objects[self._active_object].frame_id

    def rename_object(self, name: str, new_name: str) -> None:
        """Rename an existing object. Element ids, links, geometry and
        priority are unaffected."""
        idx = self.find_object_index(name)
        self._objects[idx].name = new_name

    def move_elements_to_object(self, element_ids: list[str], object_name: str | None) -> int:
        """Re-frame a batch of elements FROM THE ACTIVE OBJECT (or the free
        pool) into a different one (or the free pool), by id.

        Scoped to the active net as the source, not "wherever in the
        session an id happens to match": a composed model does not
        guarantee element ids are unique ACROSS objects (only within
        each one, by design -- see domain/composed/model.py), so two
        different objects can easily both have a place "p1"; searching
        the whole session for a bare id would be ambiguous (silently
        pick the wrong element) the moment that happens. Addressing
        element_ids against whichever net is ACTIVE matches every other
        element-addressing tool here (modify_place, remove_place,
        list_elements, ...): switch first with set_active_object to move
        FROM a different object.

        See `_reframe_elements` for the mechanism (a net_data round trip
        that heals links/arcs at the new boundary) and its own return
        value (the count moved).
        """
        return self._reframe_elements(self._active_object, element_ids, object_name)

    def _reframe_elements(
        self, source_object_index: int | None, element_ids: list[str], object_name: str | None,
    ) -> int:
        """Shared implementation behind move_elements_to_object (source =
        whichever object is active) and remove_object's own keep_elements
        merge step (source = the object being removed, known explicitly,
        not "whichever is active" -- the object being removed need not be
        the active one). *source_object_index* uses the `objects`-list
        convention (`None` = free pool), same as `net_for`.

        Implemented as a full net_data round trip through
        net_data_to_composed_model/composed_model_to_net_data
        (composed_convert.py): reassigning each element's objectId and
        re-partitioning is exactly the healing pass that already turns an
        arc newly crossing the new boundary into a synthesized link (and a
        link whose endpoints newly share an owner back into a local arc),
        the same mechanism the frontend's own drag-between-frames uses
        (see composed_convert.py's module docstring). `_dedupe_moving_ids`
        renames an id ahead of the move if it would otherwise collide with
        one already at the destination (two independently-built objects
        can easily both have a "p1" -- see that function's docstring).

        Preserves every object's own frame id, name, priority, geometry,
        nesting and templateId exactly like to_net_data/from_net_data
        always have; `_objects`' own order and length are unchanged by
        this call (only membership changes), so `_active_object` and every
        `_links` entry addressed against the object's position stay valid
        with no renumbering needed.

        Raises ValueError, naming the specific arc, if healing would need
        a placeToTransition link -- retired, see link_objects/link_type's
        own docs -- rather than silently produce one no other tool here
        can create. Returns the number of elements moved.
        """
        dest_object_index: int | None = None
        dest_frame_id: str | None = None
        if object_name is not None:
            dest_object_index = self.find_object_index(object_name)
            dest_frame_id = self._objects[dest_object_index].frame_id
        source_frame_id: str | None = (
            None if source_object_index is None else self._objects[source_object_index].frame_id
        )

        source_net = self.net_for(source_object_index)
        dest_net = self.net_for(dest_object_index)

        ids = set(element_ids)
        known = {p.id for p in source_net.places} | {t.id for t in source_net.transitions}
        missing = ids - known
        if missing:
            raise ValueError(f"Unknown element id(s): {', '.join(sorted(missing))}.")

        dest_ids = {p.id for p in dest_net.places} | {t.id for t in dest_net.transitions}
        rename = _dedupe_source_ids(source_net, ids, dest_ids)
        if rename:
            ids = {rename.get(old, old) for old in ids}
            if self._last_output_place_id in rename:
                self._last_output_place_id = rename[self._last_output_place_id]

        net_data = self.to_net_data()
        all_elements = [*net_data.get("places", []), *net_data.get("transitions", [])]
        # Matched by BOTH id and current owner: an id in `ids` could also
        # exist, unrelated, in a DIFFERENT object (see this method's own
        # docstring on why ids are not session-wide unique) -- the owner
        # check is what keeps this from grabbing that other element instead.
        moving = [
            el for el in all_elements
            if el["id"] in ids and el.get("objectId") == source_frame_id
        ]

        for element in moving:
            if dest_frame_id is None:
                element.pop("objectId", None)
            else:
                element["objectId"] = dest_frame_id

        model = net_data_to_composed_model(net_data)
        for link in model.links:
            if link.type == LinkType.PLACE_TO_TRANSITION:
                src_id, _ = model.resolve_link_endpoint(link, "source")
                tgt_id, _ = model.resolve_link_endpoint(link, "target")
                raise ValueError(
                    f"Cannot move: the arc {src_id} -> {tgt_id} would have to cross "
                    "objects as a placeToTransition link, which PetriObjModelPaint "
                    "retired. Move the other endpoint into the same object too, or "
                    "remove that arc first."
                )

        rebuilt = PetriNetSession.from_net_data(net_data, auto_optimize=self._auto_optimize)
        self._objects = rebuilt._objects
        self._links = rebuilt._links
        self._free_builder = rebuilt._free_builder
        self._last_output_place_id = rebuilt._last_output_place_id
        self._has_custom_topology = rebuilt._has_custom_topology
        self._raw_element_ids = rebuilt._raw_element_ids
        self._is_optimized = rebuilt._is_optimized
        self._last_simulation_summary = rebuilt._last_simulation_summary
        return len(moving)

    def remove_object(self, name: str, keep_elements: bool = True) -> None:
        """Remove a named object from this session.

        keep_elements=True (default) first re-frames every place/
        transition the object owns into the free pool (via
        `_reframe_elements`, using this object's own known index as the
        source regardless of which object happens to be active -- unlike
        the public move_elements_to_object, which only ever moves FROM
        the active one; also heals any link/arc that newly shares an
        owner once the elements land in the free pool) before dropping
        the now-empty object; keep_elements=False drops the object's own elements
        along with it. Either way, once the object's frame is gone, any
        link that still names it as an endpoint is dropped too --
        net_data_to_composed_model already skips a link whose endpoint
        owner it cannot resolve (see its own "dangling endpoint" comment),
        so nothing extra has to be done for that here.

        A nested child object (one whose own parent_frame_id pointed at
        this one) is NOT cascade-removed; it becomes a top-level object
        instead, the same fallback net_data_to_composed_model already
        applies to any dangling parent reference.

        If the removed object was active, the session falls back to the
        free pool, matching set_active_object's own default.
        """
        idx = self.find_object_index(name)
        obj = self._objects[idx]
        member_ids = [p.id for p in obj.net.places] + [t.id for t in obj.net.transitions]

        if keep_elements and member_ids:
            self._reframe_elements(idx, member_ids, None)
            obj = self._objects[idx]  # now empty; _objects' order/length unchanged

        net_data = self.to_net_data()
        frame_id = obj.frame_id
        if net_data.get("objects"):
            net_data["objects"] = [f for f in net_data["objects"] if f["id"] != frame_id]
        if not keep_elements:
            net_data["places"] = [
                p for p in net_data.get("places", []) if p.get("objectId") != frame_id
            ]
            net_data["transitions"] = [
                t for t in net_data.get("transitions", []) if t.get("objectId") != frame_id
            ]

        rebuilt = PetriNetSession.from_net_data(net_data, auto_optimize=self._auto_optimize)
        old_active = self._active_object

        self._objects = rebuilt._objects
        self._links = rebuilt._links
        self._free_builder = rebuilt._free_builder
        self._last_output_place_id = rebuilt._last_output_place_id
        self._has_custom_topology = rebuilt._has_custom_topology
        self._raw_element_ids = rebuilt._raw_element_ids
        self._is_optimized = rebuilt._is_optimized
        self._last_simulation_summary = rebuilt._last_simulation_summary

        if old_active is None or old_active == idx:
            self._active_object = None
        elif old_active > idx:
            self._active_object = old_active - 1
        else:
            self._active_object = old_active

    def _next_frame_id(self) -> str:
        existing = {o.frame_id for o in self._objects}
        n = len(self._objects) + 1
        while f"o{n}" in existing:
            n += 1
        return f"o{n}"

    def _parent_index(self, obj: SessionObject) -> int | None:
        """`obj`'s parent frame's position in the FULL composed model (free
        pool=0, named=i+1) -- resolves `parent_frame_id` the same way
        `net_data_to_composed_model` resolves an ObjectFrame's own
        `objectId`. A dangling reference (the named parent no longer
        exists) resolves to no parent, same fallback the frontend's own
        `objectsParentFirst` uses, rather than raising."""
        if obj.parent_frame_id is None:
            return None
        for i, other in enumerate(self._objects):
            if other.frame_id == obj.parent_frame_id:
                return i + 1
        return None

    def _link_endpoint_position(self, frame_id: str | None, element_id: str) -> tuple[int, int] | None:
        """(`_links`-convention object index, position) for one SessionLink
        endpoint, resolved fresh against the CURRENT state of the net
        *frame_id* names -- `None` when that object no longer exists (a
        removed object a link was never explicitly dropped for) or the
        element itself no longer exists there (removed by something other
        than op_remove_place/op_remove_transition's own
        remove_links_referencing call, e.g. a whole object's worth of
        elements dropped by remove_object(keep_elements=False)). The one
        place a SessionLink's id addressing turns into the domain
        ComposedLink's position addressing -- see SessionLink's own
        docstring and _build_composed_model, its only caller.
        """
        if frame_id is None:
            net = self._free_builder.net
            obj_idx = FREE_POOL_INDEX
        else:
            net = None
            obj_idx = None
            for i, obj in enumerate(self._objects):
                if obj.frame_id == frame_id:
                    net = obj.net
                    obj_idx = i + 1
                    break
            if net is None:
                return None
        place = net.get_place(element_id)
        if place is not None:
            return obj_idx, net.places.index(place)
        trans = net.get_transition(element_id)
        if trans is not None:
            return obj_idx, net.transitions.index(trans)
        return None

    def _build_composed_model(self) -> ComposedModel:
        """The full ComposedModel this session's current state describes:
        free pool at FREE_POOL_INDEX (0), named objects at i+1, `_links`
        (id-addressed) resolved fresh against each net's CURRENT positions
        via `_link_endpoint_position` -- the only place a SessionLink
        becomes a domain ComposedLink; see that class's own docstring on
        why resolving late, at build time, rather than once at creation and
        then carrying the position forward, is the whole point. A link
        whose frame_id/element_id no longer resolves (the object or the
        specific element was removed some other way than
        remove_links_referencing already covers) is silently dropped here,
        matching net_data_to_composed_model's own "dangling endpoint: skip
        rather than fail the whole model" convention for the exact same
        situation reached through net_data instead.
        """
        model = ComposedModel(name=self._free_builder.net.name)
        model.add_object(self._free_builder.net, name="Free", free=True)
        for obj in self._objects:
            model.add_object(
                obj.net,
                name=obj.name,
                priority=obj.priority,
                x=obj.x,
                y=obj.y,
                width=obj.width,
                height=obj.height,
                collapsed=obj.collapsed,
                parent=self._parent_index(obj),
                auto_fit=obj.auto_fit,
                free=False,
            )
        for link in self._links:
            source = self._link_endpoint_position(link.source_frame_id, link.source_element_id)
            target = self._link_endpoint_position(link.target_frame_id, link.target_element_id)
            if source is None or target is None:
                continue
            model.add_link(
                link.link_type,
                source_object=source[0],
                source_element=source[1],
                target_object=target[0],
                target_element=target[1],
                quantity=link.quantity,
                informational=link.informational,
            )
        return model

    def _restore_frame_ids(self, data: dict) -> None:
        """Swap composed_model_to_net_data's minted `obj{index}` frame ids
        (see composed_convert.py's module docstring: ModelObject has no
        field to carry a real frame id through) back for each object's own
        `frame_id`, in place, everywhere one could appear: an object's own
        `id`, another object's `objectId` (nesting), and an element's
        `objectId`. Each minted id only ever appears as a WHOLE field
        value (never embedded in a larger string), so a plain dict lookup
        per field is exact regardless of any coincidental overlap between
        a real frame_id and another position's minted pattern.
        """
        rename = {f"obj{i + 1}": obj.frame_id for i, obj in enumerate(self._objects)}
        if not rename:
            return
        for frame in data.get("objects", []):
            frame["id"] = rename.get(frame["id"], frame["id"])
            if "objectId" in frame:
                frame["objectId"] = rename.get(frame["objectId"], frame["objectId"])
        for element in [*data.get("places", []), *data.get("transitions", [])]:
            if "objectId" in element:
                element["objectId"] = rename.get(element["objectId"], element["objectId"])

    @property
    def last_output_place_id(self) -> str | None:
        """Get the last output place ID for auto-connection."""
        return self._last_output_place_id

    @property
    def has_custom_topology(self) -> bool:
        """Whether low-level tools were used in this session."""
        return self._has_custom_topology

    def mark_custom_topology(self, element_id: str | None = None) -> None:
        """Flag that low-level element tools were used, optionally tracking element ID."""
        self._has_custom_topology = True
        self._is_optimized = False
        if element_id:
            self._raw_element_ids.add(element_id)

    def to_net_data(self) -> dict:
        """Serialize current state to dict.

        A session with no named objects and no links serializes EXACTLY as
        it always has: the flat `PetriNet.model_dump()` plus the same
        underscore-prefixed bookkeeping keys, byte-identical to a session
        that predates Petri-objects entirely (non-negotiable backward
        compatibility, see class docstring). Otherwise, goes through
        `_build_composed_model` + `composed_model_to_net_data` (the
        frontend shape: flat places/transitions/arcs plus objects/links),
        then re-attaches `templateId` positionally (composed_convert.py's
        converter has no field to carry it through ComposedModel).
        """
        if not self._objects and not self._links:
            data = self._free_builder.net.model_dump()
            data["_last_output_place_id"] = self._last_output_place_id
            data["_has_custom_topology"] = self._has_custom_topology
            data["_is_optimized"] = self._is_optimized
            data["_last_simulation_result_text"] = self._last_simulation_summary
            data.update(self._free_builder.extra_state())
            return data

        model = self._build_composed_model()
        # The object frames are arranged the same way their contents are:
        # the free pool's builder carries the session-wide choice, which
        # apply_layout_direction keeps every object in step with.
        data = composed_model_to_net_data(
            model, self._free_builder.layout_direction
        )
        self._restore_frame_ids(data)
        if data.get("objects"):
            for frame_dict, obj in zip(data["objects"], self._objects):
                if obj.template_id is not None:
                    frame_dict["templateId"] = obj.template_id
                # This object's OWN builder extras (pattern-instance
                # registry, layout direction/lock, cluster bounds), nested
                # under its own frame dict rather than net_data's shared
                # root -- each named object has its own independent
                # PetriNetBuilder (SessionObject.builder), so a single
                # root-level set of these keys (as the flat path below
                # uses) could only ever describe ONE object. Restored by
                # the matching merge in from_net_data's composed branch.
                # Internal (underscore-prefixed) keys on an ObjectFrame
                # dict, same convention as net_data's own root-level ones;
                # composed_model_to_net_data never writes these itself, so
                # there is nothing here to collide with.
                frame_dict.update(obj.builder.extra_state())
        data["_last_output_place_id"] = self._last_output_place_id
        data["_has_custom_topology"] = self._has_custom_topology
        data["_is_optimized"] = self._is_optimized
        data["_last_simulation_result_text"] = self._last_simulation_summary
        # Which object add_*/modify_* calls were targeting when this was
        # serialized, by frame_id (stable across a round trip, unlike the
        # plain int index -- see class docstring) rather than the 0-based
        # `_objects` index directly. Without this, a session rehydrated by
        # tool_node/MCP for the NEXT turn always restarts at the free pool
        # regardless of which object was active when the previous turn
        # ended (from_net_data's own session._active_object = None default
        # otherwise has nothing to override it with) -- silently sending a
        # follow-up add_place/add_transition call to the wrong net with no
        # error at all. Composed-only key, so a flat session's net_data
        # (this method's other branch) is untouched by this addition.
        data["_active_object_id"] = (
            self._objects[self._active_object].frame_id
            if self._active_object is not None
            else None
        )
        data.update(self._free_builder.extra_state())
        return data

    def create_network(self, name: str = "PetriNet") -> None:
        """Reset with a new empty network, clearing any composed structure."""
        self._free_builder = PetriNetBuilder(name=name)
        self._objects = []
        self._links = []
        self._active_object = None
        self._last_output_place_id = None
        self._has_custom_topology = False
        self._raw_element_ids = set()
        self._is_optimized = True
        self._last_simulation_result = None
        self._last_simulation_summary = None

    def load_net_data(self, net_data: dict) -> None:
        """Replace this session's ENTIRE state (free pool, every named
        object, every link, active-object selection, bookkeeping) with
        what *net_data* describes, in place -- the same "replace
        everything, mutate this instance" contract create_network already
        has, just loading a real model instead of an empty one.

        Used by op_import_pnml (agent_toolkit): a PNML import must behave
        like every other session-replacing tool call, where the SAME
        PetriNetSession object the caller already holds (and will persist
        under its existing key) keeps describing the model, rather than a
        caller having to notice a brand-new instance came back and swap
        its own reference to it.

        Implemented as from_net_data + a field-by-field copy -- the same
        mechanism _reframe_elements/remove_object already use to "become"
        a freshly rebuilt session -- rather than duplicating
        from_net_data's flat/composed branch selection and builder-
        reconstruction here.
        """
        rebuilt = PetriNetSession.from_net_data(net_data, auto_optimize=self._auto_optimize)
        self._objects = rebuilt._objects
        self._links = rebuilt._links
        self._active_object = rebuilt._active_object
        self._free_builder = rebuilt._free_builder
        self._last_output_place_id = rebuilt._last_output_place_id
        self._has_custom_topology = rebuilt._has_custom_topology
        self._raw_element_ids = rebuilt._raw_element_ids
        self._is_optimized = rebuilt._is_optimized
        # A freshly imported model invalidates any in-memory simulation
        # result from before the import (it described the OLD model), same
        # as create_network's own reset -- but the persisted summary text
        # from_net_data restores is legitimately empty here too, since a
        # PNML document (unlike net_data) never carries one.
        self._last_simulation_result = None
        self._last_simulation_summary = rebuilt._last_simulation_summary

    def auto_connect(self, new_input_place_id: str) -> str:
        """Auto-connect last output to new input if available. Returns message."""
        if self._last_output_place_id and new_input_place_id:
            src_id = self._last_output_place_id
            src_place = self.builder.net.get_place(src_id)
            tgt_place = self.builder.net.get_place(new_input_place_id)
            src_name = src_place.name if src_place else src_id
            tgt_name = tgt_place.name if tgt_place else new_input_place_id
            self.builder.connect(src_id, new_input_place_id)
            self._is_optimized = False
            return f" Auto-connected {src_name} → {tgt_name}."
        return ""

    def set_last_output(self, place_id: str | None) -> None:
        """Track the last output place ID and trigger optimization after pattern addition."""
        self._last_output_place_id = place_id
        if self.builder.net.places:
            self._is_optimized = False
            self.optimize_if_needed()

    def optimize_if_needed(self) -> str:
        """Optimize if network was modified since last optimization. Returns note or ''.

        A no-op whenever this session was constructed with auto_optimize
        disabled, regardless of which caller reaches it (set_last_output,
        the read-only status/list/validate ops, or connect_patterns) --
        gating it here, in the one place every one of those call sites
        already funnels through, is what makes the auto-optimize switch a
        session-level property instead of something every call site has to
        remember to check for itself.

        Also a no-op for a composed session (Part B bug found during
        development): `optimize_petri_net` sees only the ACTIVE object's
        own net and prunes an immediate transition with no LOCAL output
        arc as a dead-end "sink transition" -- exactly the shape of a
        transitionToPlace link's source, which delivers its only output
        across the object boundary, invisible to the optimizer. Since
        `set_last_output` calls this after nearly every pattern-adding
        tool call, an object built with auto_optimize on (MCP's default)
        could silently lose a transition a link still names the moment
        this ran, corrupting that link's addressing with no error at all.
        A composed session skips optimization entirely rather than risk
        that; optimize_network (which calls session.optimize() directly)
        still runs on request, on the active object only, same as always
        -- this only gates the AUTOMATIC path.
        """
        if not self._auto_optimize or self._is_optimized or not self.builder.net.places:
            return ""
        if self.is_composed:
            return ""
        stats = self.optimize()
        before, after = stats["before"], stats["after"]
        removed_p = before["places"] - after["places"]
        removed_t = before["transitions"] - after["transitions"]
        if removed_p or removed_t:
            return (
                f"[Auto-optimized: removed {removed_p} place(s), "
                f"{removed_t} transition(s)]\n"
            )
        return ""

    def get_workstation_result(self, workstation_name: str) -> PatternResult | None:
        """Reconstruct PatternResult for a workstation from current net state."""
        net_data = self.builder.net.model_dump()
        places = net_data.get("places", [])

        approach_id = None
        resource_id = None
        exit_id = None
        to_next_id = None

        for p in places:
            name = p.get("name", "")
            pid = p.get("id", "")
            if name == f"{workstation_name}_Approach":
                approach_id = pid
            elif name == f"Resource_{workstation_name}":
                resource_id = pid
            elif name == f"Exit_{workstation_name}":
                exit_id = pid
            elif name == f"{workstation_name}_ToNext":
                to_next_id = pid

        if not all([approach_id, resource_id, exit_id, to_next_id]):
            return None

        return PatternResult(
            interface=PatternInterface(
                input_place_id=approach_id,
                output_place_id=exit_id,
            ),
            place_ids=[approach_id, resource_id, exit_id, to_next_id],
            transition_ids=[],
        )

    def get_status(self) -> dict:
        """Get network status summary including connectivity (active net only)."""
        net = self.builder.net
        is_valid, errors = net.validate_topology()
        components = net.find_connected_components()
        islands: list[list[str]] = []
        if len(components) > 1:
            for comp in components:
                names: list[str] = []
                for nid in comp:
                    place = net.get_place(nid)
                    if place:
                        names.append(place.name)
                        continue
                    trans = net.get_transition(nid)
                    if trans:
                        names.append(trans.name)
                islands.append(sorted(names))
        return {
            "name": net.name,
            "places": len(net.places),
            "transitions": len(net.transitions),
            "arcs": len(net.arcs),
            "valid": is_valid,
            "errors": errors,
            "connected_components": len(components),
            "islands": islands,
        }

    @property
    def last_simulation_result(self) -> Optional["SimulationResult"]:
        """The most recent run_simulation result, or None if none has run yet."""
        return self._last_simulation_result

    def record_simulation_result(self, result: "SimulationResult") -> None:
        """Store *result* as the session's last simulation result.

        Called by agent_toolkit.operations.op_run_simulation so a later
        op_get_simulation_results call in the same session can report it
        without re-running the simulation.
        """
        self._last_simulation_result = result

    @property
    def last_simulation_summary(self) -> str | None:
        """The formatted text of the last simulation result, or None.

        Unlike last_simulation_result, this survives to_net_data/from_net_data
        (see _last_simulation_result_text): it is what op_get_simulation_results
        falls back to when a fresh session was rehydrated for a later chat
        turn and the in-memory SimulationResult is gone.
        """
        return self._last_simulation_summary

    def persist_simulation_summary(self, text: str) -> None:
        """Store the formatted text of the last simulation result.

        Called by agent_toolkit.operations.op_run_simulation right after
        formatting the result, so a get_simulation_results call in a LATER
        chat turn (a fresh PetriNetSession rehydrated from net_data, with
        no in-memory SimulationResult) can still answer with the real
        numbers instead of "no simulation has been run yet".
        """
        self._last_simulation_summary = text

    def export_pnml(self) -> str:
        """Export this session's model to PNML XML string.

        A composed session (any named object or link, see `is_composed`)
        exports via ComposedPNMLExporter -- one page per object, the free
        pool included as the free-elements page exactly the way
        ComposedModel/composed_document.py already treats an object never
        placed on the canvas (see `ModelObject.free`/`_build_composed_model`,
        which always marks the free pool this way). A flat session keeps
        exporting via the flat PNMLExporter on whichever net is active,
        byte-identical to how this method always worked (Part B, contract
        E's export bullet: this is the case the "flat session export
        byte-stable" test pins down).
        """
        if self.is_composed:
            model = self.build_composed_model()
            exporter = get_composed_pnml_exporter()
            return exporter.export(model)
        exporter = get_pnml_exporter()
        return exporter.export(self.builder.net)

    def optimize(self) -> dict:
        """Optimize the active network, return before/after stats.

        With `protect_pattern_ports` set, the elements of every registered
        pattern survive untouched. What the optimizer would otherwise fuse
        first is the place where one pattern hands off to the next, and
        that place is the seam a composed model gets cut along: once two
        patterns share a single place, there is no longer any way to give
        each of them its own Petri-object. See
        `ensure_patterns_in_objects`, which does the same "drop the
        redundant connector" cleanup at the object level instead, by
        fusing the two ports with a link rather than deleting one of them.
        """
        net = self.builder.net
        places_before = len(net.places)
        transitions_before = len(net.transitions)
        arcs_before = len(net.arcs)

        protected: frozenset[str] = frozenset()
        if self.protect_pattern_ports:
            protected = frozenset(
                element
                for instance in self.builder.pattern_instances.values()
                for element in (*instance["place_ids"], *instance["transition_ids"])
            )
        optimized_net, stats = optimize_petri_net(net, protected)

        self.builder._net = optimized_net
        self._is_optimized = True

        if self._last_output_place_id:
            surviving_ids = {p.id for p in optimized_net.places}
            if self._last_output_place_id not in surviving_ids:
                self._last_output_place_id = None

        return {
            "before": {
                "places": places_before,
                "transitions": transitions_before,
                "arcs": arcs_before,
            },
            "after": {
                "places": len(optimized_net.places),
                "transitions": len(optimized_net.transitions),
                "arcs": len(optimized_net.arcs),
            },
            "fusions_performed": stats.fusions_performed,
        }


#: Same class, offered under the name the composed-session contract
#: suggested ("rename to ModelSession if that reads better"). Kept as an
#: alias rather than a rename so every existing `from
#: src.services.petri.session import PetriNetSession` (agent_toolkit/
#: operations.py chief among them, out of this change's scope) keeps
#: working unmodified; new code -- and Part B's catalog operations, if its
#: author prefers -- may import either name.
ModelSession = PetriNetSession
