"""Server-side logic for every agent-facing Petri Net tool, as plain functions.

Every function here takes an already-resolved `PetriNetSession` as its
first argument and returns `str | ToolError` (see errors.py); never
raises for a recognized "bad input" or "not found" failure (the
`@tool_operation` decorator converts those), and never touches a session
store, FastMCP Context, or LangChain message. Resolving the session,
persisting it, and translating the result into a protocol-specific tool
result are all adapter concerns (backend/src/mcp/tools/*, the chat
agent's tool_node) that build on top of this module.

Extracted from the two existing implementations: backend/src/mcp/tools/
petri_tools.py's hand-written tool bodies and backend/src/services/agent/
nodes/tool_node.py's `_EXPLICIT_HANDLERS`, which had independently
drifted on several tools. Where the two disagreed, this module follows
the MCP body (per the phase-1 contract); documented exceptions:

- auto_layout: the MCP tool calls `session.builder.auto_layout(start_x=,
  center_y=, x_step=, y_step=)`, but `PetriNetBuilder.auto_layout` only
  ever accepted `direction`; that call raises TypeError and is untested
  (no test exercises the MCP auto_layout tool). tool_node's version
  (`direction` only) is the one that actually works, so op_auto_layout
  follows tool_node instead.
- set_layout_direction, arrange_patterns, list_pattern_instances,
  get_pattern_bounds: MCP never exposed these at all; they exist only in
  tool_node's `_EXPLICIT_HANDLERS`, so their op_* functions here follow
  tool_node (nothing to disagree with).
- The connect_* "convention lookup" tools (connect_workstation_bypass,
  connect_return_loop, connect_bounded_consumer, connect_blocking_consumer,
  connect_wip_return, connect_schedule_gate) used to build their own
  `"Error: ..."` string by hand on a lookup miss, without raising. They
  now `raise ValueError(...)` instead, letting `@tool_operation` produce
  the same text as a proper ToolError, the same fix in spirit as D2,
  applied here so every recognized failure in this module is uniformly
  typed rather than half string-convention, half exception.
- export_pnml / run_simulation's connectivity pre-check used to return a
  hand-built "ERROR: Cannot ...: ...\\nFix: ..." string directly. It now
  raises ValueError with the same message body, so it also comes back as
  a ToolError instead of being the one remaining unstructured failure
  shape in the module.
- auto-optimize (session._auto_optimize, gating PetriNetSession.
  optimize_if_needed): a deliberate, documented per-surface divergence, not
  a bug. Every op_* function below that calls set_last_output, connect, or
  one of the read-only status ops (get_network_status, validate_net,
  list_elements) runs through optimize_if_needed exactly the same way for
  both adapters; what differs is the session each adapter constructs.
  backend/src/mcp/tools/petri_tools.py's session store builds every
  PetriNetSession with auto_optimize defaulted True (MCP always eagerly
  fused Transfer transitions between add_* calls; unchanged by this
  module). backend/src/services/agent/nodes/tool_node.py constructs its
  session with auto_optimize=False (the pre-catalog chat dispatcher never
  auto-optimized anything; only an explicit optimize_network call ever
  touched the net, and this module restores that). optimize_network itself
  (op_optimize_network) always runs unconditionally on both surfaces, since
  it calls session.optimize() directly rather than optimize_if_needed.
"""

import inspect
from typing import Any

# Deliberately NOT using `from __future__ import annotations` here: catalog.py
# introspects these functions' real `inspect.signature` (types and defaults)
# to build each ToolSpec, and PEP 563 would turn every annotation into a bare
# string instead of a live type object. Python 3.10+'s `X | None` union
# syntax and `list[dict]` generic syntax both work as live runtime
# expressions without the future import, so nothing is lost by omitting it.

from src.domain import ArcType, DistributionType, RoutingStrategy
from src.domain.composed import PLACE_TO_TRANSITION_RETIRED_REASON, LinkType
from src.services.petri.agent_toolkit import time_units as tu
from src.services.petri.agent_toolkit.errors import tool_operation
from src.services.petri.importer import parse_pnml
from src.services.petri.session import PetriNetSession

_WARNINGS_HEADER = "\n⚠ Warnings:\n"

#: link_objects's own wording for refusing to CREATE a placeToTransition
#: link. run_simulation/export_pnml reject one loaded some other way (e.g.
#: from net_data) via ComposedModel.validate()/ComposedSimulationUnsupported
#: instead, each in ITS OWN wording -- this constant is not reused there.
#: Built from PLACE_TO_TRANSITION_RETIRED_REASON, the SAME text
#: composed_document.py's own backstop message (build_document_model)
#: formats into its sentence -- genuinely verbatim-shared now, not just a
#: comment claiming so (the two used to be independent, hand-copied
#: strings that had already drifted apart).
_PLACE_TO_TRANSITION_RETIRED = f"Cannot create a {PLACE_TO_TRANSITION_RETIRED_REASON}"


def _connectivity_warning(session: PetriNetSession) -> str:
    """Warn when the net has more than one connected component."""
    components = session.net.find_connected_components()
    if len(components) > 1:
        return (
            f"\n⚠ {len(components)} disconnected components detected, "
            "use connect_patterns to link them before simulating or exporting."
        )
    return ""


def _format_warnings(warnings: list[str]) -> str:
    if not warnings:
        return ""
    return _WARNINGS_HEADER + "\n".join(f"  - {w}" for w in warnings)


def _format_pnml_warnings(warnings: list[dict]) -> str:
    """Render parse_pnml's {"code", "message"} warnings the same way
    _format_warnings renders plain strings, for op_import_pnml's result
    text -- each line prefixed with its warning code so an agent (or a
    human reading the tool result) can tell dangling-ref apart from
    bad-number at a glance without re-reading the message."""
    if not warnings:
        return ""
    return _WARNINGS_HEADER + "\n".join(f"  - [{w['code']}] {w['message']}" for w in warnings)


def _coerce_enum_kwargs(sig: inspect.Signature, kwargs: dict) -> dict:
    """Coerce string values to DistributionType/RoutingStrategy per *sig*."""
    result = {}
    for k, v in kwargs.items():
        ann = sig.parameters[k].annotation if k in sig.parameters else None
        if ann is DistributionType and isinstance(v, str):
            result[k] = DistributionType(v)
        elif ann is RoutingStrategy and isinstance(v, str):
            result[k] = RoutingStrategy(v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Petri-object helpers: shared by every object/link op below.
# ---------------------------------------------------------------------------

def _object_label(object_name: str | None) -> str:
    """How one link/move endpoint's object names itself in a message."""
    return "the free pool" if object_name is None else f"'{object_name}'"


def _frame_label(session: PetriNetSession, frame_id: str | None) -> str:
    """Human-readable name for a link endpoint's owning object, addressed
    by `frame_id` (`None` = free pool; see SessionLink's own docstring) --
    or a fallback for a frame_id that no longer names any object (a
    dangling link, possible on data loaded from outside these tools;
    validate_model is what flags this, not this formatter, so it degrades
    gracefully instead)."""
    if frame_id is None:
        return "free pool"
    for obj in session.objects:
        if obj.frame_id == frame_id:
            return f"'{obj.name}'"
    return f"<removed object {frame_id}>"


def _element_label(session: PetriNetSession, frame_id: str | None, element_id: str, kind: str) -> str:
    """Human-readable "id ('name')" for one link endpoint, addressed by
    (`frame_id`, `element_id`) -- resolved against that object's CURRENT
    net, so it always reflects live state (id addressing has no position
    to go stale) -- or a fallback when the owning object or the element
    itself no longer exists (a dangling link)."""
    net = None
    if frame_id is None:
        net = session.net_for(None)
    else:
        for obj in session.objects:
            if obj.frame_id == frame_id:
                net = obj.net
                break
    if net is None:
        return f"<{kind} {element_id}>"
    el = net.get_place(element_id) if kind == "place" else net.get_transition(element_id)
    if el is None:
        return f"<{kind} {element_id}>"
    return f"{el.id} ('{el.name}')"


def _describe_link(session: PetriNetSession, link) -> str:
    """One-line rendering of a SessionLink for list_links/remove_link."""
    src_kind = "transition" if link.link_type == LinkType.TRANSITION_TO_PLACE else "place"
    src = _element_label(session, link.source_frame_id, link.source_element_id, src_kind)
    tgt = _element_label(session, link.target_frame_id, link.target_element_id, "place")
    src_obj = _frame_label(session, link.source_frame_id)
    tgt_obj = _frame_label(session, link.target_frame_id)
    return (
        f"{link.link_type.value}: {src_obj}.{src} -> {tgt_obj}.{tgt} "
        f"(quantity={link.quantity})"
    )


def _object_lines(session: PetriNetSession) -> list[str]:
    """One summary line per object (free pool first), for
    get_network_status/list_objects: element counts, active marker, and
    (for named objects) priority and how many links touch it."""
    active = session.active_object_index
    free_net = session.net_for(None)
    lines = [
        f"  [free pool]{' (active)' if active is None else ''}: "
        f"{len(free_net.places)} places, {len(free_net.transitions)} transitions"
    ]
    for i, obj in enumerate(session.objects):
        touching = sum(
            1 for link in session.links
            if link.source_frame_id == obj.frame_id or link.target_frame_id == obj.frame_id
        )
        lines.append(
            f"  {i}: '{obj.name}'{' (active)' if active == i else ''}: "
            f"{len(obj.net.places)} places, {len(obj.net.transitions)} transitions, "
            f"priority={obj.priority}, links={touching}"
        )
    return lines


def _local_topology_errors(net) -> list[str]:
    """The subset of PetriNet.validate_topology()'s checks that still
    apply to one object's net inside a composed model: arc endpoints
    exist and stay bipartite, and no id or name collides WITHIN this one
    net. Deliberately omits validate_topology's has_input/has_output/
    single-connectivity checks: all three are legitimately relaxed for an
    object designed to rely on cross-object links (see
    ComposedModel.validate()'s own docstring) -- ComposedModel.validate()
    supplies the correct, link-aware replacement for has_input instead of
    this function duplicating a weaker version of it that does not know
    about links at all.
    """
    errors: list[str] = []
    for arc in net.arcs:
        src_is_place = net.get_place(arc.source_id) is not None
        src_is_trans = net.get_transition(arc.source_id) is not None
        tgt_is_place = net.get_place(arc.target_id) is not None
        tgt_is_trans = net.get_transition(arc.target_id) is not None
        if not (src_is_place or src_is_trans):
            errors.append(f"Arc '{arc.id}': source '{arc.source_id}' not found")
        if not (tgt_is_place or tgt_is_trans):
            errors.append(f"Arc '{arc.id}': target '{arc.target_id}' not found")
        if (src_is_place and tgt_is_place) or (src_is_trans and tgt_is_trans):
            errors.append(f"Arc '{arc.id}': invalid connection, both endpoints are the same kind")
    seen: set[str] = set()
    for node_id in [p.id for p in net.places] + [t.id for t in net.transitions]:
        if node_id in seen:
            errors.append(f"Duplicate node ID: '{node_id}'")
        seen.add(node_id)
    place_names = {p.name for p in net.places}
    for t in net.transitions:
        if t.name in place_names:
            errors.append(f"Name conflict: transition '{t.name}' ({t.id}) shares its name with a place")
    return errors


# ---------------------------------------------------------------------------
# Network lifecycle
# ---------------------------------------------------------------------------

@tool_operation
def op_create_network(session: PetriNetSession, name: str = "PetriNet") -> str:
    """Create a new empty Petri Net, clearing any previous network.

    Use this FIRST when building a new model from scratch.

    Args:
        name: Name for the new network (default: "PetriNet")
    """
    session.create_network(name)
    return f"Created new empty network '{name}'. Ready to add patterns."


# ---------------------------------------------------------------------------
# Petri-objects: composed models (multiple named modules, each its own net,
# wired together by placeFusion/transitionToPlace links). A session no
# object tool ever touches stays flat forever -- these tools are the only
# way a session becomes composed. See session.py's PetriNetSession
# docstring for the active-object routing every existing add_*/modify_*
# operation already gets for free once one of these makes an object active.
# ---------------------------------------------------------------------------

@tool_operation
def op_create_object(
    session: PetriNetSession,
    name: str,
    priority: int = 0,
    parent: str | None = None,
) -> str:
    """Create a new Petri-object (a module with its own net) and make it
    active.

    Every add_*/modify_*/remove_* tool call after this one targets the
    new object's own net, exactly like an untouched session targets the
    free pool, until a later set_active_object call switches away. Use
    link_objects once both sides exist to wire this object's places or
    transitions to another object's (or the free pool's); use
    validate_model, not validate_net, to check the WHOLE composed model
    before running a simulation or exporting.

    Args:
        name: Display name for the new object (e.g. "Loader", "Conveyor").
        priority: Firing priority relative to OTHER objects, for when two
            transitions in different objects are both ready to fire at the
            same simulation time (higher fires first; ties are then broken
            by each transition's own priority, exactly like today).
        parent: Name of an existing object to nest this one INSIDE. An
            object can hold plain places and transitions and other objects
            at the same time, so this is how a model says "this whole
            assembly is one part of that bigger one" (e.g. a "Line" object
            holding a "Loader" and a "Press"). Omit for a top-level object.
    """
    index = session.create_object(name, priority=priority, parent=parent)
    return (
        f"Created object '{name}' (index={index}) and made it active. "
        "Every add_*/modify_*/remove_* call now targets its net. "
        "Call set_active_object() with no argument to switch back to the "
        "free pool, or set_active_object(name=...) for another object."
    )


@tool_operation
def op_set_active_object(session: PetriNetSession, name: str | None = None) -> str:
    """Switch which net add_*/modify_*/remove_* tool calls target.

    Args:
        name: The object to activate, by its exact name (see
            list_objects). Omit to switch to the free pool, the default
            every session starts in and stays in until create_object is
            first called.
    """
    if name is None:
        session.set_active_object(None)
        return "Active object: free pool. Every add_*/modify_* call now targets it."
    index = session.find_object_index(name)
    session.set_active_object(index)
    return f"Active object: '{name}' (index={index}). Every add_*/modify_* call now targets its net."


@tool_operation
def op_list_objects(session: PetriNetSession) -> str:
    """List every Petri-object in this session: index, name, element
    counts, which one is active, and how many links touch each one.
    """
    if not session.is_composed:
        return (
            "This session is flat: everything lives in the free pool, "
            "no named objects yet. Use create_object to start one."
        )
    lines = ["=== Objects ==="] + _object_lines(session)
    if session.links:
        lines.append(f"Links: {len(session.links)} total (see list_links for detail).")
    return "\n".join(lines)


@tool_operation
def op_rename_object(session: PetriNetSession, name: str, new_name: str) -> str:
    """Rename an existing object. Element ids, links, and priority are
    unaffected.

    Args:
        name: The object's current name (see list_objects).
        new_name: The new name.
    """
    session.rename_object(name, new_name)
    return f"Renamed object '{name}' to '{new_name}'."


@tool_operation
def op_remove_object(session: PetriNetSession, name: str, keep_elements: bool = True) -> str:
    """Remove an object from this session.

    Args:
        name: The object to remove (see list_objects).
        keep_elements: True (default) moves the object's places and
            transitions into the free pool instead of deleting them,
            healing any link or arc whose other endpoint also ends up in
            the free pool into an ordinary local one, exactly like
            dragging an object's members out of its frame on the canvas.
            False deletes the object's elements outright. Either way,
            every link still touching the removed object once its
            elements are gone is dropped along with it. A nested child
            object is not cascade-removed; it becomes top-level instead.
    """
    idx = session.find_object_index(name)
    place_count = len(session.objects[idx].net.places)
    transition_count = len(session.objects[idx].net.transitions)
    was_active = session.active_object_index == idx
    frame_id = session.objects[idx].frame_id
    # Captured (link, its description) BEFORE removal: a link's endpoints
    # may reference an element about to be deleted (keep_elements=False),
    # so its name can only be resolved now. Value-equality (SessionLink is
    # a plain dataclass) is what tells "no longer present" apart from "this
    # exact link survived untouched" after the removal round trip below
    # rebuilds `session._links` as an entirely new list.
    touching_before = [
        (link, _describe_link(session, link))
        for link in session.links
        if link.source_frame_id == frame_id or link.target_frame_id == frame_id
    ]

    session.remove_object(name, keep_elements=keep_elements)

    dropped = [desc for link, desc in touching_before if link not in session.links]
    link_note = ""
    if dropped:
        link_note = f" Dropped {len(dropped)} link(s) that referenced it: " + "; ".join(dropped) + "."

    action = "moved its elements to the free pool" if keep_elements else "deleted its elements"
    active_note = " Active object is now the free pool." if was_active else ""
    return (
        f"Removed object '{name}' ({place_count} place(s), {transition_count} "
        f"transition(s)); {action}.{active_note}{link_note}"
    )


@tool_operation
def op_move_elements_to_object(
    session: PetriNetSession,
    element_ids: list[str],
    object_name: str | None = None,
) -> str:
    """Re-frame elements: move places/transitions from the ACTIVE object
    (or the free pool -- see set_active_object/create_object) into a
    different object (or the free pool).

    Arcs entirely inside the moved batch travel with it. An arc whose
    OTHER endpoint stays behind is turned into the equivalent link
    automatically when the direction supports one (a transition producing
    into a moved place becomes a transitionToPlace link); refused with a
    clear error naming the arc when it does not (a place feeding a moved
    transition would need a retired placeToTransition link) -- move that
    place too, or remove the arc first, and retry.

    Args:
        element_ids: Place/transition ids to move, from the ACTIVE object
            (see list_elements or find_elements to discover them; ids,
            not names). Switch first with set_active_object to move FROM
            a different object.
        object_name: Destination object, by name (see list_objects, or
            create_object to make a new one first). Omit for the free pool.
    """
    if not element_ids:
        return "No element ids given; nothing moved."
    moved = session.move_elements_to_object(element_ids, object_name)
    return f"Moved {moved} element(s) to {_object_label(object_name)}."


@tool_operation
def op_link_objects(
    session: PetriNetSession,
    source_object: str | None,
    source_element: str,
    target_object: str | None,
    target_element: str,
    link_type: str | None = None,
    quantity: int = 1,
) -> str:
    """Wire one object's place or transition to another's (or the free
    pool's), across the object boundary an ordinary arc cannot cross.

    placeFusion (source_element and target_element are both places): the
    two places become one shared token pool -- use this for a resource or
    a queue two objects both need to see, AND as the replacement for the
    retired placeToTransition link type (fuse the place locally, then wire
    an ordinary or read/test arc from it to the consuming transition
    inside that same object). source_element is the copy, target_element
    is the master that holds the marking: ANY number of copies may point
    at one master (a fan), but a place already used as source_element in
    one placeFusion cannot be the source_element of another -- it would
    have no single answer for what its own marking is. A link that would
    close a loop of copies, or that restates a pair already linked (either
    direction), is refused too.
    transitionToPlace (source_element is a transition, target_element is
    a place): the transition also produces a token into the target place
    when it fires, without owning a local output place of its own there.

    placeToTransition is refused outright: PetriObjModelPaint retired it
    (a transition would gain a second, disconnected set of input places,
    contradicting what its own arcs already declare).

    Args:
        source_object: The source element's object, by name. Pass null
            (None) for the free pool.
        source_element: The source place or transition, by id or name.
        target_object: The target element's object, by name. Pass null
            (None) for the free pool.
        target_element: The target place or transition, by id or name.
        link_type: "placeFusion" or "transitionToPlace". OMIT THIS -- it
            is inferred automatically from what source_element and
            target_element actually turn out to be (place+place ->
            placeFusion, transition+place -> transitionToPlace), so this
            call succeeds on the first try instead of guessing wrong (a
            common mistake: reaching for transitionToPlace to join two
            places that are really the same buffer, which is placeFusion)
            and having to retry. Pass it explicitly only to assert what
            you expect the elements to be and get a clear error if they
            turn out to be a different kind.
        quantity: Tokens delivered per firing (meaningful for
            transitionToPlace; ignored by placeFusion, which shares one
            pool rather than delivering a quantity).
    """
    if link_type == "placeToTransition":
        raise ValueError(_PLACE_TO_TRANSITION_RETIRED)
    if link_type is not None:
        try:
            LinkType(link_type)
        except ValueError:
            raise ValueError(
                f"Unknown link_type '{link_type}'. Use 'placeFusion' or "
                "'transitionToPlace', or omit it to infer automatically."
            )
    if quantity < 1:
        raise ValueError(f"quantity must be >= 1, got {quantity}.")

    src_frame, src_id, src_kind = session.resolve_element_ref(
        source_object, source_element, role="source"
    )
    tgt_frame, tgt_id, tgt_kind = session.resolve_element_ref(
        target_object, target_element, role="target"
    )

    if src_frame == tgt_frame:
        # Mirrors the frontend's own addObjectLink rationale (editor-
        # store.ts): "the whole point of a link is connecting two
        # DIFFERENT objects". Reject up front rather than let it reach
        # export_pnml's own backstop (composed_document.py's "source_object
        # == target_object, not expressible in PNML") -- that message names
        # object INDICES, not what the agent actually passed, and only
        # fires once the agent already tried to export or simulate.
        raise ValueError(
            f"Cannot link '{source_element}' to '{target_element}': both resolve to "
            f"{_object_label(source_object)}, the SAME object. A link only makes sense "
            "connecting two different objects -- draw an ordinary arc (add_arc) "
            "between them instead."
        )

    if link_type is None:
        kind = _infer_link_type(src_kind, tgt_kind, source_element, target_element)
    else:
        kind = LinkType(link_type)
        expected_src = "transition" if kind == LinkType.TRANSITION_TO_PLACE else "place"
        if src_kind != expected_src:
            raise ValueError(
                f"{link_type} needs a {expected_src} as its source, but "
                f"'{source_element}' in {_object_label(source_object)} is a {src_kind}."
            )
        if tgt_kind != "place":
            raise ValueError(
                f"{link_type} needs a place as its target, but "
                f"'{target_element}' in {_object_label(target_object)} is a {tgt_kind}."
            )

    session.add_link(kind, src_frame, src_id, tgt_frame, tgt_id, quantity)
    return (
        f"Linked ({kind.value}) {_object_label(source_object)}.{source_element} -> "
        f"{_object_label(target_object)}.{target_element} (quantity={quantity})."
    )


def _infer_link_type(
    src_kind: str, tgt_kind: str, source_element: str, target_element: str,
) -> LinkType:
    """The link_type link_objects itself would have to pick, given what
    source_element/target_element actually resolved to -- see that
    function's own docstring for why omitting link_type and letting this
    infer it is the recommended path."""
    if src_kind == "place" and tgt_kind == "place":
        return LinkType.PLACE_FUSION
    if src_kind == "transition" and tgt_kind == "place":
        return LinkType.TRANSITION_TO_PLACE
    if src_kind == "place" and tgt_kind == "transition":
        raise ValueError(_PLACE_TO_TRANSITION_RETIRED)
    raise ValueError(
        f"No link type connects a transition directly to another transition "
        f"('{source_element}' and '{target_element}' are both transitions). "
        "Route through a place instead: add an ordinary arc from the source "
        "transition into a local place, then link THAT place onward."
    )


@tool_operation
def op_list_links(session: PetriNetSession) -> str:
    """List every cross-object link in this session, with readable object
    and element names, and its 1-based position for remove_link.
    """
    if not session.links:
        return "No links yet. Use link_objects to wire two objects together."
    lines = [f"=== Links ({len(session.links)}) ==="]
    for i, link in enumerate(session.links, start=1):
        lines.append(f"  {i}: {_describe_link(session, link)}")
    return "\n".join(lines)


@tool_operation
def op_remove_link(session: PetriNetSession, index: int) -> str:
    """Remove one cross-object link by its 1-based position (see
    list_links).

    Args:
        index: The link's position as shown by list_links (1 = first).
    """
    if index < 1 or index > len(session.links):
        raise ValueError(
            f"No link at index {index}. This session has {len(session.links)} "
            "link(s); use list_links to see them."
        )
    description = _describe_link(session, session.links[index - 1])
    session.remove_link(index - 1)
    return f"Removed link {index}: {description}."


@tool_operation
def op_validate_model(session: PetriNetSession) -> str:
    """Validate the current model.

    A flat session (no objects, no links) gets exactly validate_net's own
    check. A composed session additionally gets, per object: local
    topology checks (arc endpoints exist and stay bipartite, no id or
    name collides within that one object) plus ComposedModel.validate()
    across the whole model (every transition has a real local consuming
    input, no placeToTransition link, every link endpoint resolves, every
    id is a valid XML NCName). Every finding is listed; none of them stop
    at the first.
    """
    if not session.is_composed:
        net = session.net
        if not net.places:
            return "No network to validate. Use create_network first."
        is_valid, errors = net.validate_topology()
        if is_valid:
            components = net.find_connected_components()
            return (
                f"Model is valid. {len(net.places)} places, "
                f"{len(net.transitions)} transitions, {len(net.arcs)} arcs, "
                f"{len(components)} connected component(s)."
            )
        return f"Model has {len(errors)} finding(s):\n" + "\n".join(f"  - {e}" for e in errors)

    if not session.has_any_content:
        return "No network to validate. Use create_network or add elements first."

    model = session.build_composed_model()
    errors: list[str] = []
    for obj in model.objects:
        label = "free pool" if obj.free else f"object '{obj.name}'"
        errors.extend(f"{label}: {e}" for e in _local_topology_errors(obj.net))
    errors.extend(model.validate())

    if not errors:
        total_places = sum(len(o.net.places) for o in model.objects)
        total_transitions = sum(len(o.net.transitions) for o in model.objects)
        return (
            f"Composed model is valid. {len(model.objects)} object(s) "
            f"(including the free pool), {total_places} places, "
            f"{total_transitions} transitions, {len(model.links)} link(s)."
        )
    return f"Composed model has {len(errors)} finding(s):\n" + "\n".join(f"  - {e}" for e in errors)


# ---------------------------------------------------------------------------
# Hand-written pattern tools (non-standard param handling)
# ---------------------------------------------------------------------------

@tool_operation
def op_add_generator(
    session: PetriNetSession,
    name: str,
    interval: float | None = None,
    rate: float | None = None,
    distribution: str = "exp",
    standard_deviation: float = 0.0,
    batch_size: int = 1,
    time_unit: str = "s",
    deviation_unit: str | None = None,
) -> str:
    """Add a Generator (Source) pattern that creates tokens at regular intervals.

    Use this for arrival processes. Specify EITHER interval OR rate (not both):

    Using RATE (preferred for "N items per time unit"):
    - "4 parts per minute" -> rate=4, time_unit="min"
    - "10 customers per hour" -> rate=10, time_unit="h"

    Using INTERVAL (for "every N time units"):
    - "every 3 minutes" -> interval=3, time_unit="min"
    - "every 30 seconds" -> interval=30, time_unit="s"

    BATCH GENERATION (multiple items per arrival):
    - "5 items arrive every 5 minutes" -> interval=5, time_unit="min", batch_size=5

    DISTRIBUTION SELECTION:
    - "exp": For random/Poisson arrivals
    - "norm": For arrivals with deviation ("every 3±1 min" -> norm, std=1, time_unit="min")
    - "unif": For uniformly distributed arrivals
    - "det": For fixed/constant intervals

    UNITS, TWO INDEPENDENT KNOBS:
    - `time_unit` applies to `interval` / `rate`.
    - `deviation_unit` applies to `standard_deviation`. If omitted, it inherits
      from `time_unit`. Use it when the mean and the ± are in DIFFERENT units.

    Canonical translations:
      - "1 per minute ±10 sec"
          -> interval=1, time_unit="min", standard_deviation=10, deviation_unit="s"
      - "every 5 min ±30 sec"
          -> interval=5, time_unit="min", standard_deviation=30, deviation_unit="s"
      - "every 5 min ±1 min" (same units)
          -> interval=5, time_unit="min", standard_deviation=1  (deviation_unit omitted)

    Args:
        name: Name for this generator (e.g., "CustomerArrivals", "PartsInput")
        interval: Mean time BETWEEN arrivals in time_unit (use this OR rate, not both)
        rate: Number of arrivals PER time_unit (use this OR interval, not both)
        distribution: "exp", "norm", "unif", or "det"
        standard_deviation: Spread for "norm"/"unif" distributions (in deviation_unit, or time_unit if deviation_unit omitted)
        batch_size: Number of tokens per arrival (default: 1)
        time_unit: Unit for interval/rate, "s", "min", "h", "d". PASS THIS EXPLICITLY when the user describes the mean in non-second terms; the response echoes the resulting duration/rate in all four units so you can sanity-check.
        deviation_unit: Unit for standard_deviation. Pass ONLY when it differs from time_unit (e.g. mean in minutes, ± in seconds).
    """
    if rate is not None and rate > 0:
        actual_interval = tu.to_seconds(1.0 / rate, time_unit)
    elif interval is not None:
        actual_interval = tu.to_seconds(interval, time_unit)
    else:
        actual_interval = 1.0

    stdev_unit = deviation_unit or time_unit
    actual_stdev = tu.to_seconds(standard_deviation, stdev_unit)
    result = session.builder.add_generator(
        name=name,
        interval=actual_interval,
        distribution=DistributionType(distribution),
        standard_deviation=actual_stdev,
        batch_size=batch_size,
    )
    session.set_last_output(result.interface.output_place_id)

    conn_warn = _connectivity_warning(session)
    batch_msg = f", batch_size={batch_size}" if batch_size > 1 else ""
    stdev_msg = (
        f", stdev={tu.echo_duration(actual_stdev)} (unit={stdev_unit})"
        if standard_deviation > 0 else ""
    )
    return (
        f"Added generator '{name}' "
        f"(time_unit={time_unit}, interval={tu.echo_duration(actual_interval)}, "
        f"rate={tu.echo_rate(actual_interval)}{stdev_msg}, "
        f"distribution={distribution}{batch_msg}). "
        f"Output place ID: {result.interface.output_place_id}{conn_warn}"
    )


@tool_operation
def op_add_machine(
    session: PetriNetSession,
    name: str,
    processing_time: float,
    channels: int = 1,
    distribution: str = "exp",
    standard_deviation: float = 0.0,
    auto_connect: bool = True,
    time_unit: str = "s",
    deviation_unit: str | None = None,
) -> str:
    """Add a Machine (Server) pattern with multiple processing channels.

    Use this for processing stations like machines, servers, workstations.

    UNITS, TWO INDEPENDENT KNOBS:
    - `time_unit` applies to `processing_time`.
    - `deviation_unit` applies to `standard_deviation`. If omitted, inherits time_unit.

    Args:
        name: Name for this machine (e.g., "Lathe", "Checkout", "Server")
        processing_time: Mean processing time in time_unit
        channels: Number of parallel channels
        distribution: Time distribution - "exp", "norm", "unif", or "det"
        standard_deviation: Spread for "norm"/"unif" (in deviation_unit, or time_unit if omitted)
        auto_connect: If True (default), auto-connects to previous output.
                      Set to False for PARALLEL machines from same queue!
        time_unit: Unit for processing_time, "s", "min", "h", "d".
        deviation_unit: Unit for standard_deviation. Pass ONLY when it differs from time_unit.
    """
    pt_s = tu.to_seconds(processing_time, time_unit)
    stdev_unit = deviation_unit or time_unit
    actual_stdev = tu.to_seconds(standard_deviation, stdev_unit)
    result = session.builder.add_machine(
        name=name,
        processing_time=pt_s,
        distribution=DistributionType(distribution),
        standard_deviation=actual_stdev,
        channels=channels,
    )

    auto_msg = ""
    if auto_connect:
        auto_msg = session.auto_connect(result.interface.input_place_id)

    session.set_last_output(result.interface.output_place_id)

    conn_warn = _connectivity_warning(session)
    stdev_msg = (
        f", stdev={tu.echo_duration(actual_stdev)} (unit={stdev_unit})"
        if standard_deviation > 0 else ""
    )
    return (
        f"Added machine '{name}' ({channels} channels, "
        f"time_unit={time_unit}, processing_time={tu.echo_duration(pt_s)}, "
        f"throughput={tu.echo_rate(pt_s / channels)}{stdev_msg}, "
        f"distribution={distribution}). "
        f"Input: {result.interface.input_place_id}, "
        f"Output: {result.interface.output_place_id}.{auto_msg}{conn_warn}"
    )


@tool_operation
def op_add_controller(
    session: PetriNetSession,
    name: str,
    initial_signal: bool = False,
) -> str:
    """Add a Controller (Gate) pattern that allows flow only when a signal is present.

    The signal is read but NOT consumed (information link).

    Args:
        name: Name for this controller (e.g., "TrafficLight", "Permission")
        initial_signal: If True, the signal starts enabled (gate open)
    """
    result = session.builder.add_controller(
        name=name,
        initial_signal=initial_signal,
    )
    return (
        f"Added controller '{name}' (signal={'enabled' if initial_signal else 'disabled'}). "
        f"Input: {result.interface.input_place_id}, "
        f"Output: {result.interface.output_place_id}"
    )


@tool_operation
def op_add_assembly(
    session: PetriNetSession,
    name: str,
    inputs: list[str | dict],
    assembly_time: float = 1.0,
    distribution: str = "det",
    priority: int = 1,
    time_unit: str = "s",
) -> str:
    """Add an Assembly (Join) pattern that synchronizes multiple flows into one.

    Creates one new input place per slot named "{name}_In_{slot_name}" and
    a transition that fires when ALL slots have tokens. The caller must
    wire external sources to those slots via connect_patterns, the slot
    place_ids are returned in the response and in metadata.

    WEIGHTED INPUTS (for multiple tokens required):
    - Simple: inputs=["PartA", "PartB"] - requires 1 token from each
    - Weighted: inputs=[{"name": "Type1", "weight": 10}, {"name": "Type2", "weight": 10}]

    Args:
        name: Name for this assembly (e.g., "CarAssembly", "SectionFill")
        inputs: Names for the input slots created by this assembly
        assembly_time: Mean firing time in time_unit
        distribution: Time distribution
        priority: Transition priority (higher = fires first in conflict)
        time_unit: Unit for time values, "s", "min", "h", or "d" (days)
    """
    result = session.builder.add_assembly(
        name=name,
        inputs=inputs,
        assembly_time=tu.to_seconds(assembly_time, time_unit),
        distribution=DistributionType(distribution),
        priority=priority,
    )
    input_place_ids = result.metadata.get("input_place_ids", {})
    return (
        f"Added assembly '{name}' (inputs={[s if isinstance(s, str) else s.get('name') for s in inputs]}, "
        f"time={assembly_time}{time_unit}, priority={priority}). "
        f"Input slots: {input_place_ids}, "
        f"Output: {result.interface.output_place_id}"
    )


@tool_operation
def op_add_router(
    session: PetriNetSession,
    name: str,
    routes: list[dict],
    strategy: str = "probability",
) -> str:
    """Add a Router (Splitter) pattern that branches flow into multiple paths.

    Args:
        name: Name for this router (e.g., "QualityCheck", "LoadBalancer")
        routes: List of route configurations:
               For probability: [{"name": "Accept", "prob": 0.9}, {"name": "Reject", "prob": 0.1}]
               For priority: [{"name": "Primary", "priority": 2}, {"name": "Backup", "priority": 1}]
               PRIORITY RULE: higher "priority" number fires first (same as add_transition).
               The route with the highest priority number is tried first; lower numbers are fallbacks.
        strategy: "probability" for random split, "priority" for ordered selection
    """
    result = session.builder.add_router(
        name=name,
        routes=routes,
        strategy=RoutingStrategy(strategy),
    )
    auto_msg = session.auto_connect(result.interface.input_place_id)
    session.set_last_output(None)
    output_places = [pid for pid in result.place_ids if pid != result.interface.input_place_id]
    return (
        f"Added router '{name}' (strategy={strategy}, "
        f"routes={[r.get('name') for r in routes]}). "
        f"Input place ID: {result.interface.input_place_id}, "
        f"Output places: {output_places}"
        + (f". {auto_msg}" if auto_msg else "")
    )


@tool_operation
def op_add_conveyor(
    session: PetriNetSession,
    name: str,
    stations: list[dict],
    transport_time: float = 5.0,
) -> str:
    """Add a Conveyor pattern with sequential processing stations.

    Every item is processed at every station (no bypass option).
    For stations with bypass logic, use add_conveyor_line instead.

    Args:
        name: Name for this conveyor (e.g., "AssemblyLine", "Pipeline")
        stations: List of station configs:
                  [{"name": "Stage1", "time": 60.0, "distribution": "exp"}, ...]
        transport_time: Time to move between stations
    """
    result = session.builder.add_conveyor(
        name=name,
        stations=stations,
        transport_time=transport_time,
    )
    station_names = [s.get("name", f"Station{i}") for i, s in enumerate(stations)]
    return (
        f"Added conveyor '{name}' (stations={station_names}, "
        f"transport={transport_time}s). "
        f"Entry: {result.interface.input_place_id}, "
        f"Exit: {result.interface.output_place_id}"
    )


@tool_operation
def op_add_conveyor_line(
    session: PetriNetSession,
    station_count: int,
    processing_time: float = 1.0,
    distribution: str = "exp",
    transport_time: float = 1.0,
    return_delay: float = 5.0,
    channels: int = 1,
    station_prefix: str = "Device",
    time_unit: str = "s",
) -> str:
    """Add a COMPLETE conveyor line with Try-or-Bypass workstations.

    THIS IS THE PREFERRED TOOL for conveyor systems with bypass logic.
    Creates N workstations, all bypass connections, and return loop in ONE call.

    How it works:
    - Each station: if resource FREE -> process; if BUSY -> bypass to next
    - After last station: unprocessed items return to first with delay
    - Processed items exit at their processing station

    Args:
        station_count: Number of workstations
        processing_time: Mean processing time at each station in time_unit
        distribution: Processing time distribution
        transport_time: Time to move between stations in time_unit
        return_delay: Time for items to return from last to first station in time_unit
        channels: Number of parallel resources per station
        station_prefix: Name prefix for stations (default: "Device")
        time_unit: Unit for all time values, "s", "min", or "h"
    """
    dist = DistributionType(distribution)
    pt_s = tu.to_seconds(processing_time, time_unit)
    tt_s = tu.to_seconds(transport_time, time_unit)
    rd_s = tu.to_seconds(return_delay, time_unit)

    station_names = []
    station_results = []
    for i in range(station_count):
        sname = f"{station_prefix}{i + 1}"
        station_names.append(sname)
        result = session.builder.add_conveyor_workstation(
            name=sname,
            processing_time=pt_s,
            distribution=dist,
            transport_time=tt_s,
            channels=channels,
        )
        station_results.append(result)

    for i in range(station_count - 1):
        session.builder.connect_bypass(station_results[i], station_results[i + 1])

    session.builder.connect_return_loop(
        station_results[-1],
        station_results[0].interface.input_place_id,
        return_delay=rd_s,
    )

    exit_place_ids = [r.interface.output_place_id for r in station_results]
    first_input_id = station_results[0].interface.input_place_id

    auto_msg = session.auto_connect(first_input_id)
    session.set_last_output(None)

    return (
        f"Created conveyor line with {station_count} stations: {station_names}. "
        f"Processing: {pt_s}s ({distribution}), "
        f"Transport: {tt_s}s, Return: {rd_s}s, "
        f"Channels: {channels}. "
        f"First input: {first_input_id}. "
        f"Exit places: {exit_place_ids}.{auto_msg}"
    )


@tool_operation
def op_add_conveyor_workstation(
    session: PetriNetSession,
    name: str,
    processing_time: float = 1.0,
    distribution: str = "exp",
    transport_time: float = 1.0,
    channels: int = 1,
    time_unit: str = "s",
) -> str:
    """Add a SINGLE ConveyorWorkstation with Try-or-Bypass logic.

    For multiple workstations in a chain, prefer add_conveyor_line instead.

    Args:
        name: Name for this workstation (e.g., "Device1")
        processing_time: Mean processing time in time_unit
        distribution: Processing time distribution
        transport_time: Time to bypass to next station in time_unit
        channels: Number of parallel resources
        time_unit: Unit for time values, "s", "min", "h", or "d" (days)
    """
    result = session.builder.add_conveyor_workstation(
        name=name,
        processing_time=tu.to_seconds(processing_time, time_unit),
        distribution=DistributionType(distribution),
        transport_time=tu.to_seconds(transport_time, time_unit),
        channels=channels,
    )
    bypass_place_id = result.place_ids[3] if len(result.place_ids) > 3 else None
    return (
        f"Added workstation '{name}' (Try-or-Bypass). "
        f"Processing: {processing_time}s ({distribution}), "
        f"Bypass: {transport_time}s, Channels: {channels}. "
        f"Input: {result.interface.input_place_id}, "
        f"Output: {result.interface.output_place_id}, "
        f"Bypass: {bypass_place_id}"
    )


@tool_operation
def op_connect_workstation_bypass(
    session: PetriNetSession,
    source_workstation_name: str,
    target_workstation_name: str,
) -> str:
    """Connect bypass output of one workstation to input of next.

    Prefer add_conveyor_line which creates all connections automatically.

    Args:
        source_workstation_name: Source workstation name
        target_workstation_name: Target workstation name
    """
    source_result = session.get_workstation_result(source_workstation_name)
    target_result = session.get_workstation_result(target_workstation_name)

    if not source_result:
        raise ValueError(f"Workstation '{source_workstation_name}' not found.")
    if not target_result:
        raise ValueError(f"Workstation '{target_workstation_name}' not found.")

    session.builder.connect_bypass(source_result, target_result)
    return (
        f"Connected bypass: {source_workstation_name} -> {target_workstation_name}. "
        f"Items that bypass {source_workstation_name} will go to {target_workstation_name}."
    )


@tool_operation
def op_connect_return_loop(
    session: PetriNetSession,
    last_workstation_name: str,
    first_workstation_name: str,
    return_delay: float = 5.0,
    time_unit: str = "s",
) -> str:
    """Create return loop from last workstation back to first.

    Prefer add_conveyor_line which creates return loop automatically.

    Args:
        last_workstation_name: Last workstation name
        first_workstation_name: First workstation name
        return_delay: Time to return in time_unit (default: 5.0)
        time_unit: Unit for time values, "s", "min", "h", or "d" (days)
    """
    last_result = session.get_workstation_result(last_workstation_name)
    first_result = session.get_workstation_result(first_workstation_name)

    if not last_result:
        raise ValueError(f"Workstation '{last_workstation_name}' not found.")
    if not first_result:
        raise ValueError(f"Workstation '{first_workstation_name}' not found.")

    rd_s = tu.to_seconds(return_delay, time_unit)
    session.builder.connect_return_loop(
        last_result,
        first_result.interface.input_place_id,
        return_delay=rd_s,
    )
    return (
        f"Created return loop: {last_workstation_name} -> {first_workstation_name} "
        f"(delay={rd_s}s)."
    )


@tool_operation
def op_add_transport_agent(
    session: PetriNetSession,
    name: str,
    grab_time: float = 8.0,
    grab_deviation: float = 1.0,
    grab_distribution: str = "unif",
    move_time: float = 6.0,
    move_distribution: str = "det",
    release_time: float = 8.0,
    release_deviation: float = 1.0,
    release_distribution: str = "unif",
    return_time: float | None = None,
    return_distribution: str = "det",
    time_unit: str = "s",
) -> str:
    """Add a TransportAgent (cyclic resource) pattern.

    Models any resource that picks up, moves, releases, and returns:
    robots, forklifts, AGVs, cranes, couriers.

    Cycle: [Queue]+[Free] -> Grab -> Move -> Release -> Return -> [Free]

    Args:
        name: Name for this agent (e.g., "Robot1", "Forklift", "AGV")
        grab_time: Mean time to grab/pick item in time_unit
        grab_deviation: Standard deviation for grab in time_unit
        grab_distribution: Distribution for grab time
        move_time: Time to move WITH item in time_unit
        move_distribution: Distribution for move
        release_time: Mean time to release/place item in time_unit
        release_deviation: Standard deviation for release in time_unit
        release_distribution: Distribution for release
        return_time: Time to return EMPTY in time_unit (default: same as move_time)
        return_distribution: Distribution for return
        time_unit: Unit for all time values, "s", "min", or "h"
    """
    gt_s = tu.to_seconds(grab_time, time_unit)
    gd_s = tu.to_seconds(grab_deviation, time_unit)
    mt_s = tu.to_seconds(move_time, time_unit)
    rt_s = tu.to_seconds(release_time, time_unit)
    rd_s = tu.to_seconds(release_deviation, time_unit)
    rtn_s = tu.to_seconds(return_time, time_unit) if return_time is not None else None

    result = session.builder.add_transport_agent(
        name=name,
        grab_time=gt_s,
        grab_deviation=gd_s,
        grab_distribution=DistributionType(grab_distribution),
        move_time=mt_s,
        move_distribution=DistributionType(move_distribution),
        release_time=rt_s,
        release_deviation=rd_s,
        release_distribution=DistributionType(release_distribution),
        return_time=rtn_s,
        return_distribution=DistributionType(return_distribution),
    )

    auto_msg = session.auto_connect(result.interface.input_place_id)
    session.set_last_output(result.interface.output_place_id)

    return_time_used = rtn_s or mt_s
    return (
        f"Added transport agent '{name}'. "
        f"Grab: {gt_s}+-{gd_s}s ({grab_distribution}), "
        f"Move: {mt_s}s ({move_distribution}), "
        f"Release: {rt_s}+-{rd_s}s ({release_distribution}), "
        f"Return: {return_time_used}s ({return_distribution}). "
        f"Input (Queue): {result.interface.input_place_id}, "
        f"Output (Delivered): {result.interface.output_place_id}.{auto_msg}"
    )


@tool_operation
def op_add_priority_choice(
    session: PetriNetSession,
    name: str,
    resource_place_ids: list[dict] | None = None,
    primary_delay: float = 0.0,
    alternative_delay: float = 0.0,
    primary_name: str = "Success",
    alternative_name: str = "Fallback",
    time_unit: str = "s",
) -> str:
    """Add a PriorityChoice pattern for resource-dependent branching.

    Implements "do X if resources available, otherwise do Y" logic.
    Primary transition has higher priority and fires first if resources available.

    Args:
        name: Name for this choice point (e.g., "SectionFill")
        resource_place_ids: Resource requirements for primary path.
            Each dict: {"place_id": "p5", "weight": 10}
        primary_delay: Delay for primary/success transition in time_unit
        alternative_delay: Delay for alternative/fallback transition in time_unit
        primary_name: Name suffix for success output
        alternative_name: Name suffix for fallback output
        time_unit: Unit for time values, "s", "min", "h", or "d" (days)
    """
    result = session.builder.add_priority_choice(
        name=name,
        resource_place_ids=resource_place_ids,
        primary_delay=tu.to_seconds(primary_delay, time_unit),
        alternative_delay=tu.to_seconds(alternative_delay, time_unit),
        primary_name=primary_name,
        alternative_name=alternative_name,
    )

    auto_msg = session.auto_connect(result.interface.input_place_id)
    session.set_last_output(result.interface.output_place_id)

    fallback_place_id = result.place_ids[2] if len(result.place_ids) > 2 else None
    return (
        f"Added priority choice '{name}'. "
        f"Input: {result.interface.input_place_id}, "
        f"Success ({primary_name}): {result.interface.output_place_id}, "
        f"Fallback ({alternative_name}): {fallback_place_id}.{auto_msg}"
    )


@tool_operation
def op_add_merge(session: PetriNetSession, name: str, inputs: list[str]) -> str:
    """Add a Merge (OR-join / Funnel) pattern, combines multiple streams into one output.

    Fires as soon as ANY input has a token (unlike Assembly which waits for ALL).
    Creates one input place per stream named "{name}_In_{stream_name}".
    Wire each producer's output into the corresponding place via connect_patterns.

    Args:
        name: Name for this merge point (e.g., "OrderMerge")
        inputs: Stream names (e.g., ["Web", "Phone", "Fax"])
    """
    result = session.builder.add_merge(name=name, inputs=inputs)
    session.set_last_output(result.interface.output_place_id)
    input_place_ids = result.metadata.get("input_place_ids", {})
    return (
        f"Added merge '{name}' (streams={inputs}). "
        f"Input places: {input_place_ids}, "
        f"Output place ID: {result.interface.output_place_id}"
    )


@tool_operation
def op_add_duplicate(session: PetriNetSession, name: str, outputs: list[str]) -> str:
    """Add a Duplicate (Broadcast) pattern, copies one token into N independent copies.

    One arriving token produces one token in each output place simultaneously.
    Use for parallel processing of the same item by independent services.

    Args:
        name: Name for this broadcast point (e.g., "OrderBroadcast")
        outputs: Output branch names (e.g., ["Warehouse", "Accounting", "Logistics"])
    """
    result = session.builder.add_duplicate(name=name, outputs=outputs)
    auto_msg = session.auto_connect(result.interface.input_place_id)
    session.set_last_output(result.interface.output_place_id)
    output_place_ids = result.metadata.get("output_place_ids", {})
    return (
        f"Added duplicate '{name}' (branches={outputs}). "
        f"Input place ID: {result.interface.input_place_id}, "
        f"Output places: {output_place_ids}.{auto_msg}"
    )


@tool_operation
def op_add_multi_resource(
    session: PetriNetSession,
    name: str,
    resources: list[dict],
    processing_time: float,
    distribution: str = "exp",
    standard_deviation: float = 0.0,
    time_unit: str = "s",
) -> str:
    """Add a MultiResource (AND-Resource) pattern, op requiring multiple simultaneous resources.

    Seizes one token from each resource pool simultaneously and releases all upon
    completion. Unlike Machine (homogeneous channels), each pool can have a different
    name and capacity.

    Args:
        name: Instance name (e.g., "PaintBooth", "SurgeryRoom")
        resources: List of resource pool definitions.
                   Each dict: {"name": str, "pool_size": int}
        processing_time: Mean processing time in time_unit
        distribution: Time distribution, "exp", "norm", "unif", "det"
        standard_deviation: Std dev for norm/unif (in time_unit)
        time_unit: Unit for time values, "s", "min", "h", or "d"
    """
    pt_s = tu.to_seconds(processing_time, time_unit)
    result = session.builder.add_multi_resource(
        name=name,
        resources=resources,
        processing_time=pt_s,
        distribution=DistributionType(distribution),
        standard_deviation=tu.to_seconds(standard_deviation, time_unit),
    )

    auto_msg = session.auto_connect(result.interface.input_place_id)
    session.set_last_output(result.interface.output_place_id)
    res_ids = result.metadata.get("resource_place_ids", {})

    return (
        f"Added multi-resource operation '{name}' "
        f"(resources={[r['name'] for r in resources]}, "
        f"processing={tu.echo_duration(pt_s)} {distribution}). "
        f"Input: {result.interface.input_place_id}, "
        f"Output: {result.interface.output_place_id}, "
        f"Resource places: {res_ids}.{auto_msg}"
    )


@tool_operation
def op_add_nonstationary_generator(
    session: PetriNetSession,
    name: str,
    schedule: list[dict],
    batch_size: int = 1,
) -> str:
    """Add a NonStationaryGenerator, arrival rate changes over cyclic time windows.

    Each time window has its own arrival rate. The schedule repeats cyclically.
    NOTE: unlike almost every other timed tool, `schedule` entries are in raw
    SECONDS (duration, rate), there is no time_unit parameter here.

    Args:
        name: Name for this generator (e.g., "CoffeeShop", "CallCenter")
        schedule: List of time windows. Each dict:
                  {"duration": float (seconds), "rate": float (arrivals/sec)}
        batch_size: Tokens per arrival (default: 1)
    """
    result = session.builder.add_nonstationary_generator(
        name=name,
        schedule=schedule,
        batch_size=batch_size,
    )
    session.set_last_output(result.interface.output_place_id)
    slot_ids = result.metadata.get("slot_place_ids", [])
    gen_ids = result.metadata.get("generator_transition_ids", [])
    window_info = ", ".join(
        f"slot{i + 1}({s['duration']}s @ {s['rate']}/s)"
        for i, s in enumerate(schedule)
    )
    return (
        f"Added non-stationary generator '{name}' ({len(schedule)} windows: {window_info}). "
        f"Output: {result.interface.output_place_id}, "
        f"Slots: {slot_ids}, Generators: {gen_ids}"
    )


@tool_operation
def op_connect_bounded_consumer(
    session: PetriNetSession,
    queue_name: str,
    consumer_name: str,
) -> str:
    """Wire capacity recycling between a BoundedQueue and its consumer.

    Looks up the queue's capacity place by naming convention
    ('{queue_name}_Capacity') and the consumer's start transition
    ('{consumer_name}_Start' for Machine, '{consumer_name}_Do' for
    Assembly), then adds an arc consumer->capacity so each dequeue
    recycles a slot.

    Args:
        queue_name: Instance name passed to add_bounded_queue
        consumer_name: Instance name of the downstream consumer
                       (Machine or Assembly)
    """
    net = session.net

    capacity_place_id = None
    for p in net.places:
        if p.name == f"{queue_name}_Capacity":
            capacity_place_id = p.id
            break
    if not capacity_place_id:
        raise ValueError(
            f"bounded queue '{queue_name}' not found "
            f"(expected place '{queue_name}_Capacity')."
        )

    consume_transition_id = None
    for t in net.transitions:
        if t.name in (f"{consumer_name}_Start", f"{consumer_name}_Do"):
            consume_transition_id = t.id
            break
    if not consume_transition_id:
        raise ValueError(
            f"consumer '{consumer_name}' has no '{consumer_name}_Start' "
            f"or '{consumer_name}_Do' transition. "
            f"Add an arc to {capacity_place_id} manually."
        )

    net.add_arc(source_id=consume_transition_id, target_id=capacity_place_id)
    return (
        f"Wired capacity recycling: {consumer_name} -> {queue_name} capacity slot. "
        f"Each dequeue now restores one slot."
    )


@tool_operation
def op_add_fork_join(
    session: PetriNetSession,
    name: str,
    n_branches: int = 2,
    branch_times: list[float] | None = None,
    branch_distribution: str = "exp",
    time_unit: str = "s",
) -> str:
    """Add a ForkJoin (AND-split / AND-join) pattern for parallel branch execution.

    A single entity enters, splits into N independent parallel branches, and
    continues ONLY when ALL N branches have completed.

    Args:
        name: Instance name (e.g., "PatientExam", "QualityGate")
        n_branches: Number of parallel branches (default: 2)
        branch_times: Mean processing time per branch in time_unit.
                      Length must equal n_branches. Default: [30.0] * n_branches
        branch_distribution: Distribution for branches, "exp", "norm", "unif", "det"
        time_unit: Time unit for branch_times, "s", "min", "h"
    """
    if branch_times is None:
        branch_times = [30.0] * n_branches
    branch_times_s = [tu.to_seconds(t, time_unit) for t in branch_times]
    dist = DistributionType(branch_distribution)
    result = session.builder.add_fork_join(
        name=name,
        n_branches=n_branches,
        branch_times=branch_times_s,
        branch_distribution=dist,
    )
    session.set_last_output(result.interface.output_place_id)
    branch_input_ids = result.metadata.get("branch_input_ids", [])
    branch_done_ids = result.metadata.get("branch_done_ids", [])
    join_id = result.metadata.get("join_transition_id", "")
    branch_time_display = ", ".join(tu.echo_duration(t) for t in branch_times_s)
    return (
        f"Added fork_join '{name}' ({n_branches} branches, times: {branch_time_display}). "
        f"Input: {result.interface.input_place_id}, "
        f"Output: {result.interface.output_place_id}. "
        f"Branch inputs (wire external sources here): {branch_input_ids}. "
        f"Branch done places (wire external outputs here): {branch_done_ids}. "
        f"Join transition: {join_id}."
    )


@tool_operation
def op_connect_blocking_consumer(
    session: PetriNetSession,
    blocking_machine_name: str,
    downstream_name: str,
) -> str:
    """Wire capacity recycling between a BlockingMachine and its downstream consumer.

    Call this AFTER connecting BlockingMachine output to downstream input.

    Args:
        blocking_machine_name: Instance name passed to add_blocking_machine
        downstream_name: Instance name of the downstream consumer (Machine, etc.)
    """
    net = session.net

    capacity_place_id = None
    for p in net.places:
        if p.name == f"{blocking_machine_name}_Capacity":
            capacity_place_id = p.id
            break
    if not capacity_place_id:
        raise ValueError(
            f"blocking machine '{blocking_machine_name}' not found "
            f"(expected place '{blocking_machine_name}_Capacity')."
        )

    consume_transition_id = None
    for t in net.transitions:
        if t.name in (f"{downstream_name}_Start", f"{downstream_name}_Do"):
            consume_transition_id = t.id
            break
    if not consume_transition_id:
        raise ValueError(
            f"downstream '{downstream_name}' has no '{downstream_name}_Start' "
            f"or '{downstream_name}_Do' transition. "
            f"Add an arc to {capacity_place_id} manually."
        )

    net.add_arc(source_id=consume_transition_id, target_id=capacity_place_id)
    return (
        f"Wired blocking capacity recycling: {downstream_name} -> "
        f"{blocking_machine_name} capacity slot. "
        f"Each dequeue from blocking machine output restores one slot."
    )


@tool_operation
def op_add_resource_set(
    session: PetriNetSession,
    name: str,
    resources: list[dict],
    standard_deviation: float = 0.0,
    time_unit: str = "s",
) -> str:
    """Add a ResourceSet, entity seizes the first available resource from alternatives.

    Models "try resource A first; if busy, try B; if busy, try C."
    Resources are listed in preference order (index 0 = highest priority).

    Args:
        name: Instance name (e.g., "MachinePool", "NursePool")
        resources: List of resource dicts, ordered by preference. Each dict:
                   - "name": str (required)
                   - "service_time": float (default 60.0, in time_unit)
                   - "distribution": str "exp"|"norm"|"unif"|"det" (default "exp")
                   - "channels": int (default 1)
        standard_deviation: Global std dev fallback for norm/unif resources (in time_unit)
        time_unit: Time unit for service_time values, "s", "min", "h"
    """
    converted = []
    for r in resources:
        rc = dict(r)
        if "service_time" in rc:
            rc["service_time"] = tu.to_seconds(float(rc["service_time"]), time_unit)
        converted.append(rc)
    result = session.builder.add_resource_set(
        name=name,
        resources=converted,
        standard_deviation=tu.to_seconds(standard_deviation, time_unit),
    )
    auto_msg = session.auto_connect(result.interface.input_place_id)
    session.set_last_output(result.interface.output_place_id)
    res_names = [r.get("name", f"R{i}") for i, r in enumerate(resources)]
    free_ids = result.metadata.get("resource_free_place_ids", {})
    return (
        f"Added resource_set '{name}' ({len(resources)} resources: {res_names}). "
        f"Priority order: {res_names[0]} first. "
        f"Input: {result.interface.input_place_id}, "
        f"Output: {result.interface.output_place_id}. "
        f"Free places: {free_ids}.{auto_msg}"
    )


@tool_operation
def op_connect_wip_return(
    session: PetriNetSession,
    wip_controller_name: str,
    exit_place_id: str,
) -> str:
    """Wire the WIP return arc, recycle a WIP slot when an entity reaches the exit place.

    Call AFTER wiring the WIP-controlled section, so the producer
    transitions of exit_place_id exist.

    Args:
        wip_controller_name: Instance name passed to add_wip_controller
        exit_place_id: Output place ID of the last pattern in the controlled section
    """
    net = session.net

    wip_place_id = None
    for p in net.places:
        if p.name == f"{wip_controller_name}_WIPSlots":
            wip_place_id = p.id
            break
    if not wip_place_id:
        raise ValueError(
            f"WIPController '{wip_controller_name}' not found "
            f"(expected place '{wip_controller_name}_WIPSlots')."
        )

    producer_transition_ids = {
        arc.source_id
        for arc in net.arcs
        if arc.target_id == exit_place_id
        and net.get_transition(arc.source_id) is not None
    }
    if not producer_transition_ids:
        raise ValueError(
            f"no transitions produce into exit_place_id={exit_place_id!r}. "
            "Wire the WIP-controlled section before calling connect_wip_return."
        )
    for trans_id in producer_transition_ids:
        net.add_arc(source_id=trans_id, target_id=wip_place_id)

    return (
        f"Wired WIP return: added {len(producer_transition_ids)} arc(s) from "
        f"producers of {exit_place_id} to '{wip_controller_name}_WIPSlots'. "
        f"Each entity reaching the exit now restores one WIP slot."
    )


@tool_operation
def op_connect_schedule_gate(
    session: PetriNetSession,
    schedule_name: str,
    machine_name: str,
) -> str:
    """Gate a machine with a shift schedule via READ arc.

    Adds a READ arc from the schedule's Active signal place to the machine's
    Start transition. Call AFTER both add_scheduled_availability and
    add_machine / add_breakdown.

    Args:
        schedule_name: Name passed to add_scheduled_availability (e.g., "DayShift")
        machine_name: Name passed to add_machine or add_breakdown (e.g., "Press")
    """
    net = session.net

    signal_place_id = None
    for p in net.places:
        if p.name == f"{schedule_name}_Active":
            signal_place_id = p.id
            break
    if not signal_place_id:
        raise ValueError(
            f"schedule '{schedule_name}' not found "
            f"(no place '{schedule_name}_Active')."
        )

    target_transition_id = None
    for t in net.transitions:
        if t.name == f"{machine_name}_Start":
            target_transition_id = t.id
            break
    if not target_transition_id:
        raise ValueError(
            f"machine '{machine_name}' has no '{machine_name}_Start' transition. "
            f"Works with Machine and Breakdown patterns only."
        )

    net.add_arc(
        source_id=signal_place_id,
        target_id=target_transition_id,
        arc_type=ArcType.READ,
    )
    return (
        f"Gated '{machine_name}' with schedule '{schedule_name}'. "
        f"READ arc: {signal_place_id} -> {target_transition_id}. "
        f"Machine processes only during active windows."
    )


@tool_operation
def op_connect_patterns(
    session: PetriNetSession,
    source_output_id: str,
    target_input_id: str,
) -> str:
    """Connect the output of one pattern to the input of another.

    Args:
        source_output_id: Output place ID from the source pattern
        target_input_id: Input place ID of the target pattern
    """
    session.builder.connect(source_output_id, target_input_id)
    session._is_optimized = False
    session.optimize_if_needed()
    return f"Connected {source_output_id} -> {target_input_id}"


@tool_operation
def op_get_network_status(session: PetriNetSession) -> str:
    """Get current status of the Petri Net being built.

    Returns a summary of the ACTIVE net (places, transitions, arcs, and
    validation status; see set_active_object/create_object for what
    "active" means). In a composed session, also appends a per-object
    summary (element counts, which object is active, link counts) so the
    active net's own detail is never the only visibility into the model.
    """
    if not session.has_any_content:
        return "No network created yet. Use create_network first."

    opt_note = session.optimize_if_needed()
    status = session.get_status()
    net = session.net
    places_info = ", ".join(f"{p.id}:{p.name}({p.tokens})" for p in net.places)
    trans_info = ", ".join(f"{t.id}:{t.name}" for t in net.transitions)

    errors_msg = f"\n- Errors: {status['errors']}" if status["errors"] else ""
    last_out = session.last_output_place_id
    last_out_msg = f"\n- Last output place: {last_out}" if last_out else ""

    body = (
        f"{opt_note}Network '{status['name']}':\n"
        f"- Places ({status['places']}): {places_info}\n"
        f"- Transitions ({status['transitions']}): {trans_info}\n"
        f"- Arcs: {status['arcs']}\n"
        f"- Valid: {status['valid']}{last_out_msg}{errors_msg}"
    )
    if session.is_composed:
        object_summary = "\n".join(_object_lines(session))
        body += f"\n\n=== Objects ===\n{object_summary}"
        if session.links:
            body += f"\nLinks: {len(session.links)} total (see list_links for detail)."
    return body


# ---------------------------------------------------------------------------
# Low-level element ops (custom topology: the 10% escape hatch)
# ---------------------------------------------------------------------------

@tool_operation
def op_add_place(
    session: PetriNetSession,
    name: str,
    tokens: int = 0,
    tag: str | None = None,
    x: float | None = None,
    y: float | None = None,
) -> str:
    """Add a single place (position) to the Petri net.

    LOW-LEVEL TOOL, use only when no existing pattern (add_generator,
    add_machine, etc.) covers the required topology. For standard queueing
    and production constructs, prefer the high-level pattern tools.

    Layout: ALWAYS call find_free_position(near_element_id, direction) first
    to get collision-free coordinates near the element you will connect to,
    then pass the returned x and y here. Without explicit coordinates the
    auto-cursor places the element at the far right, colliding with existing
    elements on follow-up edits.

    Args:
        name: Human-readable place name
        tokens: Initial token count (marking)
        tag: Optional semantic tag (e.g. "throughput" for counter places)
        x: Canvas X coordinate, obtain from find_free_position
        y: Canvas Y coordinate, obtain from find_free_position
    """
    place_id = session.builder.add_raw_place(name=name, tokens=tokens, tag=tag, x=x, y=y)
    session.mark_custom_topology(place_id)
    return f"Added place '{name}' (id={place_id}, tokens={tokens})."


@tool_operation
def op_add_transition(
    session: PetriNetSession,
    name: str,
    distribution: str | None = None,
    mean_delay: float = 0.0,
    standard_deviation: float = 0.0,
    priority: int = 1,
    probability: float | None = None,
    time_unit: str = "s",
    x: float | None = None,
    y: float | None = None,
) -> str:
    """Add a single transition (event) to the Petri net.

    LOW-LEVEL TOOL, use only when no existing pattern covers the required
    topology. For standard constructs, prefer high-level pattern tools.

    Layout: ALWAYS call find_free_position(near_element_id, direction) first
    to get collision-free coordinates, then pass the returned x and y here.

    Args:
        name: Human-readable transition name
        distribution: Time distribution ("exp", "norm", "unif", "det"), omit for immediate
        mean_delay: Mean delay time in time_unit
        standard_deviation: For norm/unif distributions (in time_unit)
        priority: Firing priority (higher = fires first in conflict)
        probability: Firing probability for stochastic conflict resolution (0.0-1.0)
        time_unit: Unit for time values, "s", "min", "h"
        x: Canvas X coordinate (see list_elements for existing coords)
        y: Canvas Y coordinate
    """
    dist = DistributionType(distribution) if distribution else None
    delay_sec = tu.to_seconds(mean_delay, time_unit)
    std_sec = tu.to_seconds(standard_deviation, time_unit)
    transition_id = session.builder.add_raw_transition(
        name=name,
        distribution=dist,
        mean_delay=delay_sec,
        standard_deviation=std_sec,
        priority=priority,
        probability=probability,
        x=x,
        y=y,
    )
    session.mark_custom_topology(transition_id)
    delay_info = f" delay={tu.echo_duration(delay_sec)}" if dist else " immediate"
    return (
        f"Added transition '{name}' (id={transition_id},"
        f" distribution={distribution or 'immediate'},{delay_info})."
    )


@tool_operation
def op_add_arc(
    session: PetriNetSession,
    source_id: str,
    target_id: str,
    weight: int = 1,
    arc_type: str = "normal",
) -> str:
    """Add an arc connecting a place to a transition or vice versa.

    LOW-LEVEL TOOL. Arcs enforce bipartite constraint: Place<->Transition only.

    Args:
        source_id: ID of the source node (place or transition)
        target_id: ID of the target node (place or transition)
        weight: Arc weight (tokens consumed/produced per firing)
        arc_type: Arc type, "normal", "inhibitor", or "read"
    """
    arc_id = session.builder.add_raw_arc(
        source_id=source_id,
        target_id=target_id,
        weight=weight,
        arc_type=arc_type,
    )
    session.mark_custom_topology()

    reposition_msg = ""
    raw_ids = session._raw_element_ids
    net = session.net
    if source_id in raw_ids or target_id in raw_ids:
        raw_id = source_id if source_id in raw_ids else target_id
        anchor_id = target_id if source_id in raw_ids else source_id
        raw_el = net.get_place(raw_id) or net.get_transition(raw_id)
        anchor_el = net.get_place(anchor_id) or net.get_transition(anchor_id)
        if raw_el and anchor_el:
            ax, ay = anchor_el.graphics.x, anchor_el.graphics.y
            is_place_to_trans = net.get_place(raw_id) and net.get_transition(anchor_id)
            if is_place_to_trans:
                new_x, new_y = ax, ay - 90
            else:
                new_x, new_y = ax + 120, ay
            net.set_element_positions([{"id": raw_id, "x": new_x, "y": new_y}])
            reposition_msg = f" Repositioned {raw_id} to ({int(new_x)}, {int(new_y)}) near {anchor_id}."

    return (
        f"Added arc {source_id} -> {target_id} "
        f"(id={arc_id}, weight={weight}, type={arc_type}).{reposition_msg}"
    )


@tool_operation
def op_validate_net(session: PetriNetSession) -> str:
    """Validate the current Petri net topology.

    Checks bipartite constraint, dangling transitions (no input/output arcs),
    and duplicate IDs.
    """
    net = session.net
    if not net.places:
        return "No network to validate. Use create_network first."
    opt_note = session.optimize_if_needed()
    net = session.net
    is_valid, errors = net.validate_topology()
    components = net.find_connected_components()
    prefix = opt_note
    connectivity_line = (
        f"Connected components: {len(components)}"
        if len(components) <= 1
        else f"Connected components: {len(components)} ⚠ (disconnected!)"
    )
    if is_valid:
        return (
            f"{prefix}Network is valid. {len(net.places)} places, "
            f"{len(net.transitions)} transitions, {len(net.arcs)} arcs. "
            f"{connectivity_line}."
        )
    return (
        f"{prefix}Network has {len(errors)} validation error(s):\n"
        + "\n".join(f"  - {e}" for e in errors)
    )


# ---------------------------------------------------------------------------
# CRUD ops: modify, remove, list elements
# ---------------------------------------------------------------------------

@tool_operation
def op_modify_place(
    session: PetriNetSession,
    place_id: str,
    name: str | None = None,
    tokens: int | None = None,
    tag: str | None = None,
) -> str:
    """Modify an existing place in the Petri net.

    Only provided fields are updated, omitted fields stay unchanged.
    Use list_elements or get_network_status to discover place IDs first.

    Args:
        place_id: ID of the place to modify (e.g. "p1")
        name: New name (omit to keep current)
        tokens: New token count (omit to keep current)
        tag: New semantic tag (omit to keep current)
    """
    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if tokens is not None:
        kwargs["tokens"] = tokens
    if tag is not None:
        kwargs["tag"] = tag
    session.builder.modify_place(place_id, **kwargs)
    session.mark_custom_topology()
    changed = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    return f"Modified place {place_id}: {changed}."


@tool_operation
def op_modify_transition(
    session: PetriNetSession,
    transition_id: str,
    name: str | None = None,
    distribution: str | None = None,
    mean_delay: float | None = None,
    standard_deviation: float | None = None,
    priority: int | None = None,
    probability: float | None = None,
    time_unit: str = "s",
) -> str:
    """Modify an existing transition in the Petri net.

    Only provided fields are updated, omitted fields stay unchanged.
    Use list_elements or get_network_status to discover transition IDs first.

    Args:
        transition_id: ID of the transition to modify (e.g. "t3")
        name: New name (omit to keep current)
        distribution: New distribution ("exp", "norm", "unif", "det"), omit to keep current
        mean_delay: New mean delay in time_unit (omit to keep current)
        standard_deviation: New std deviation in time_unit (omit to keep current)
        priority: New firing priority, higher number fires first in conflict (omit to keep current)
        probability: New firing probability 0.0-1.0 (omit to keep current)
        time_unit: Unit for time values, "s", "min", "h"
    """
    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if distribution is not None:
        kwargs["distribution"] = DistributionType(distribution)
    if mean_delay is not None:
        kwargs["mean_delay"] = tu.to_seconds(mean_delay, time_unit)
    if standard_deviation is not None:
        kwargs["standard_deviation"] = tu.to_seconds(standard_deviation, time_unit)
    if priority is not None:
        kwargs["priority"] = priority
    if probability is not None:
        kwargs["probability"] = probability
    session.builder.modify_transition(transition_id, **kwargs)
    session.mark_custom_topology()
    display = {}
    for k, v in kwargs.items():
        if k == "distribution":
            display[k] = v.value
        elif k in ("mean_delay", "standard_deviation"):
            display[k] = tu.echo_duration(v)
        else:
            display[k] = v
    changed = ", ".join(f"{k}={v}" for k, v in display.items())
    return f"Modified transition {transition_id}: {changed}."


@tool_operation
def op_modify_arc(
    session: PetriNetSession,
    arc_id: str,
    weight: int | None = None,
    arc_type: str | None = None,
) -> str:
    """Modify an existing arc in the Petri net.

    Only provided fields are updated, omitted fields stay unchanged.
    Use list_elements to discover arc IDs first.

    Args:
        arc_id: ID of the arc to modify
        weight: New arc weight (omit to keep current)
        arc_type: New arc type, "normal", "inhibitor", or "read" (omit to keep current)
    """
    kwargs: dict[str, Any] = {}
    if weight is not None:
        kwargs["weight"] = weight
    if arc_type is not None:
        kwargs["arc_type"] = ArcType(arc_type)
    session.builder.modify_arc(arc_id, **kwargs)
    session.mark_custom_topology()
    changed = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    return f"Modified arc {arc_id}: {changed}."


def _drop_links_for_element(session: PetriNetSession, element_id: str) -> str:
    """Remove and describe every link naming *element_id* inside the
    ACTIVE object (or the free pool) -- op_remove_place/op_remove_transition's
    shared helper, called BEFORE the element itself is removed so
    _describe_link can still resolve its name for the note this returns
    (a link left referencing an already-gone element would otherwise
    dangle silently until the next to_net_data/build_composed_model quietly
    dropped it, with the agent never told). Returns "" when nothing
    touched it.
    """
    frame_id = session.active_frame_id()
    dropped = session.remove_links_referencing(frame_id, element_id)
    if not dropped:
        return ""
    described = "; ".join(_describe_link(session, link) for link in dropped)
    return f" Dropped {len(dropped)} link(s) that referenced it: {described}."


@tool_operation
def op_remove_place(session: PetriNetSession, place_id: str) -> str:
    """Remove a place and all its connected arcs from the Petri net.

    WARNING: Destructive, the place and ALL arcs connected to it are
    deleted. In a composed session, any cross-object link naming this
    place is also dropped (named in the result).
    """
    link_note = _drop_links_for_element(session, place_id)
    warnings = session.builder.remove_place(place_id)
    session.mark_custom_topology()
    return f"Removed place {place_id} and its connected arcs.{link_note}" + _format_warnings(warnings)


@tool_operation
def op_remove_transition(session: PetriNetSession, transition_id: str) -> str:
    """Remove a transition and all its connected arcs from the Petri net.

    WARNING: Destructive, the transition and ALL arcs connected to it are
    deleted. In a composed session, any cross-object link naming this
    transition is also dropped (named in the result).
    """
    link_note = _drop_links_for_element(session, transition_id)
    warnings = session.builder.remove_transition(transition_id)
    session.mark_custom_topology()
    return (
        f"Removed transition {transition_id} and its connected arcs.{link_note}"
        + _format_warnings(warnings)
    )


@tool_operation
def op_remove_arc(session: PetriNetSession, arc_id: str) -> str:
    """Remove a single arc from the Petri net."""
    warnings = session.builder.remove_arc(arc_id)
    session.mark_custom_topology()
    return f"Removed arc {arc_id}." + _format_warnings(warnings)


@tool_operation
def op_list_elements(session: PetriNetSession) -> str:
    """List all places, transitions, and arcs with their current
    parameters, for the ACTIVE object only (see set_active_object/
    create_object). Use list_objects for a whole-session, per-object view."""
    if not session.net.places:
        return "No network created yet. Use create_network first."
    opt_note = session.optimize_if_needed()
    elements = session.builder.list_elements()
    lines = [opt_note.strip()] if opt_note.strip() else []
    lines.append("=== Places ===")
    for p in elements["places"]:
        tag_info = f", tag={p['tag']}" if p.get("tag") else ""
        coord = f", x={int(p.get('x', 0))}, y={int(p.get('y', 0))}"
        lines.append(f"  {p['id']}: {p['name']} (tokens={p['tokens']}{tag_info}{coord})")
    lines.append("=== Transitions ===")
    for t in elements["transitions"]:
        dist = t.get("distribution") or "immediate"
        delay = f", delay={tu.echo_duration(t['mean_delay'])}" if t.get("mean_delay") else ""
        coord = f", x={int(t.get('x', 0))}, y={int(t.get('y', 0))}"
        lines.append(f"  {t['id']}: {t['name']} (dist={dist}{delay}, priority={t['priority']}{coord})")
    lines.append("=== Arcs ===")
    for a in elements["arcs"]:
        lines.append(f"  {a['id']}: {a['source_id']} -> {a['target_id']} (w={a['weight']}, type={a['arc_type']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Spatial / layout ops
# ---------------------------------------------------------------------------

@tool_operation
def op_set_positions(session: PetriNetSession, positions: list[dict]) -> str:
    """Set canvas coordinates for places and transitions by ID.

    Args:
        positions: List of {"id": "<place or transition id>", "x": <float>, "y": <float>}
    """
    if not session.net.places:
        return "No network created yet. Use create_network first."
    updated = session.builder.set_positions(positions)
    return f"Updated positions for {len(updated)} element(s): {updated}"


@tool_operation
def op_find_free_position(
    session: PetriNetSession,
    near_element_id: str,
    direction: str = "right",
) -> str:
    """Find canvas coordinates for a new element near an existing one, avoiding overlaps.

    Args:
        near_element_id: ID of the place or transition to position near
        direction: Where to place the new element relative to the anchor:
                   "right" (same y, larger x, default -- keeps flow horizontal)
                   | "left" | "above" (same x, lower y) | "below"
    """
    if not session.net.places:
        return "No network created yet. Use create_network first."
    x, y = session.net.find_free_position(near_element_id, direction)
    return (
        f"Free position near {near_element_id} ({direction}): "
        f"x={int(x)}, y={int(y)}. "
        f"Pass these to add_place or add_transition."
    )


@tool_operation
def op_find_elements(
    session: PetriNetSession,
    name_pattern: str = "",
    element_type: str | None = None,
) -> str:
    """Search places and transitions by name substring, within the ACTIVE
    object only (see set_active_object/create_object). Switch objects
    first to search a different one.

    Args:
        name_pattern: Case-insensitive substring (e.g. "Generator", "Queue").
                      Empty string returns all elements of the requested type.
        element_type: "place", "transition", or omit for both.
    """
    if not session.net.places:
        return "No network created yet. Use create_network first."
    results = session.builder.find_elements(
        name_pattern=name_pattern,
        element_type=element_type,
    )
    if not results:
        return (
            f"No elements found matching name_pattern={name_pattern!r}, "
            f"type={element_type or 'any'}."
        )
    lines = [f"Found {len(results)} element(s):"]
    for el in results:
        if el["type"] == "place":
            tag = f", tag={el['tag']}" if el.get("tag") else ""
            lines.append(
                f"  [place] {el['id']}: {el['name']} "
                f"(tokens={el['tokens']}{tag}, x={int(el['x'])}, y={int(el['y'])})"
            )
        else:
            dist = el.get("distribution") or "immediate"
            delay = f", delay={tu.echo_duration(el['mean_delay'])}" if el.get("mean_delay") else ""
            lines.append(
                f"  [transition] {el['id']}: {el['name']} "
                f"(dist={dist}{delay}, x={int(el['x'])}, y={int(el['y'])})"
            )
    return "\n".join(lines)


@tool_operation
def op_get_network_bounds(session: PetriNetSession) -> str:
    """Return the spatial bounding box of all elements in the net."""
    if not session.net.places:
        return "No network created yet. Use create_network first."
    b = session.builder.get_bounds()
    return (
        f"Network bounds ({b['element_count']} elements):\n"
        f"  x: [{int(b['min_x'])}, {int(b['max_x'])}]  width={int(b['width'])}\n"
        f"  y: [{int(b['min_y'])}, {int(b['max_y'])}]  height={int(b['height'])}\n"
        f"  center: ({int(b['center_x'])}, {int(b['center_y'])})"
    )


@tool_operation
def op_move_elements_by(
    session: PetriNetSession,
    element_ids: list[str],
    dx: float = 0.0,
    dy: float = 0.0,
) -> str:
    """Shift one or more elements by a relative offset.

    Args:
        element_ids: List of place/transition IDs to move
        dx: Horizontal shift in canvas units (positive = right)
        dy: Vertical shift in canvas units (positive = down)
    """
    if not session.net.places:
        return "No network created yet. Use create_network first."
    updated = session.builder.move_elements_by(element_ids=element_ids, dx=dx, dy=dy)
    return f"Moved {len(updated)} element(s) by (dx={dx}, dy={dy}): {updated}"


@tool_operation
def op_auto_layout(session: PetriNetSession, direction: str | None = None) -> str:
    """Re-layout the ACTIVE object's net using pattern-aware Sugiyama
    layering (see set_active_object/create_object for what "active"
    means) -- in a composed session this touches only that one object's
    members; the free pool and every other object are left exactly where
    they were.

    Ported from tool_node's `_handle_auto_layout`, not the MCP tool; see
    this module's docstring for why (the MCP body's start_x/center_y/
    x_step/y_step params don't match PetriNetBuilder.auto_layout's actual
    signature and would raise TypeError).

    Args:
        direction: "LR" for left-to-right flow or "TB" for top-to-bottom.
                   Omit to keep the net's current layout direction.
    """
    if not session.net.places:
        return "No network created yet. Use create_network first."
    resolved_direction = direction or session.builder._layout_direction
    stats = session.builder.auto_layout(direction=resolved_direction)
    return (
        f"Auto-layout applied ({resolved_direction}): {stats['layers']} layers, "
        f"{stats['element_count']} elements repositioned."
    )


@tool_operation
def op_set_layout_direction(session: PetriNetSession, direction: str = "LR") -> str:
    """Change the layout direction, clear the manual-layout lock, and re-layout.

    Args:
        direction: "LR" (left-to-right) or "TB" (top-to-bottom)
    """
    if not session.net.places:
        return "No network created yet. Use create_network first."
    result = session.builder.set_layout_direction(direction)
    return (
        f"Layout direction set to {result['direction']}. "
        f"Re-layout: {result.get('layers', 0)} layers, "
        f"{result.get('element_count', 0)} elements repositioned. "
        "Automatic layout resumed."
    )


@tool_operation
def op_arrange_patterns(session: PetriNetSession, placements: list[dict]) -> str:
    """Move named pattern instances to desired top-left positions.

    Args:
        placements: List of {"name": str, "x": float, "y": float}, the desired
            top-left corner of each pattern instance's bounding box.
    """
    if not session.net.places:
        return "No network created yet. Use create_network first."
    if not placements:
        return "No placements provided."
    result = session.builder.arrange_patterns(placements)
    names = result["arranged"]
    return (
        f"Arranged {len(names)} pattern(s): {names}. "
        "Automatic layout is now suspended, call auto_layout or "
        "set_layout_direction to resume."
    )


@tool_operation
def op_list_pattern_instances(session: PetriNetSession) -> str:
    """List every registered pattern instance with its type, IDs, and bounds."""
    if not session.net.places:
        return "No network created yet. Use create_network first."
    instances = session.builder.list_pattern_instances()
    if not instances:
        return "No pattern instances registered yet."
    lines = [f"Registered pattern instances ({len(instances)}):"]
    for inst in instances:
        lines.append(
            f"  {inst['name']} ({inst['type']}): "
            f"bbox=[{int(inst.get('min_x', 0))},{int(inst.get('min_y', 0))}"
            f"..{int(inst.get('max_x', 0))},{int(inst.get('max_y', 0))}], "
            f"in={inst.get('input_place_id')}, out={inst.get('output_place_id')}"
        )
    return "\n".join(lines)


@tool_operation
def op_get_pattern_bounds(session: PetriNetSession, name: str) -> str:
    """Return the bounding box of one named pattern instance.

    Args:
        name: The pattern instance name (as passed to its add_X call)
    """
    if not session.net.places:
        return "No network created yet. Use create_network first."
    b = session.builder.get_pattern_bounds(name)
    return (
        f"Pattern '{name}' bounds: "
        f"x=[{int(b['min_x'])}, {int(b['max_x'])}], "
        f"y=[{int(b['min_y'])}, {int(b['max_y'])}], "
        f"size={int(b['width'])}x{int(b['height'])}, "
        f"center=({int(b['center_x'])}, {int(b['center_y'])})"
    )


# ---------------------------------------------------------------------------
# Optimize / export / simulate
# ---------------------------------------------------------------------------

@tool_operation
def op_optimize_network(session: PetriNetSession) -> str:
    """Optimize the Petri Net by removing redundant elements.

    Call this AFTER the network is fully built, BEFORE exporting. Removes
    intermediate Transfer transitions and simplifies the topology while
    preserving semantic behavior, markings, and timing.
    """
    if not session.net.places:
        return "No network to optimize. Build a network first."
    stats = session.optimize()
    before = stats["before"]
    after = stats["after"]
    return (
        f"Network optimized!\n"
        f"Before: {before['places']} places, {before['transitions']} transitions, {before['arcs']} arcs\n"
        f"After: {after['places']} places, {after['transitions']} transitions, {after['arcs']} arcs\n"
        f"Removed: {before['places'] - after['places']} places, "
        f"{before['transitions'] - after['transitions']} transitions, "
        f"{before['arcs'] - after['arcs']} arcs\n"
        f"Fusions: {stats['fusions_performed']}"
    )


@tool_operation
def op_export_pnml(session: PetriNetSession) -> str:
    """Export the current model to PNML XML format.

    Returns the full PNML XML content as a string. Compatible with TINA,
    PetriObjModel, and CPN Tools. A composed session (any named object or
    link) exports every object as its own page via the ISO/IEC 15909-2
    dialect, free pool included as the free-elements page; a flat session
    keeps exporting the single flat dialect, exactly as before.
    """
    if session.is_composed:
        model = session.build_composed_model()
        errors = model.validate()
        if errors:
            raise ValueError(
                "Cannot export composed model:\n" + "\n".join(f"  - {e}" for e in errors)
                + "\nFix: use validate_model for the full picture, and link_objects "
                "to wire any object that still needs one."
            )
        return session.export_pnml()

    if not session.net.places:
        return "No network to export. Build a network first."

    is_valid, errors = session.net.validate_topology()
    connectivity_errors = [e for e in errors if "disconnected" in e]
    if connectivity_errors:
        raise ValueError(
            "Cannot export: " + connectivity_errors[0] + "\n"
            "Fix: use connect_patterns to link all components before exporting."
        )

    return session.export_pnml()


@tool_operation
def op_import_pnml(session: PetriNetSession, xml: str, replace: bool = True) -> str:
    """Import a PNML document into this session.

    The document may come from PetriObjModelPaint (the Java desktop tool)
    or from exporting a session in this application (export_pnml, or
    either of the GET .../pnml REST routes) -- both flat single-net
    documents and composed (multi-page, Petri-object) ones are read.
    Parsing always succeeds structurally: an issue this reader cannot
    make sense of is soft-fixed and reported as a warning in the result
    text instead of refusing the whole file (an invalid id sanitized, a
    duplicate id renamed, a dangling reference dropped, an arc crossing
    pages, a malformed number, an out-of-range value clamped). Only two
    hard failures are possible: no <pnml> root, or a <pnml> with no
    <net>.

    Args:
        xml: The full PNML XML document text.
        replace: True (default) replaces this session's ENTIRE current
            model (free pool, every object, every link) with the
            imported one. False refuses outright when this session
            already holds any content, leaving it completely untouched --
            call again with replace=True once you actually want to
            overwrite it, rather than losing unsaved work by accident.
    """
    if not replace and session.has_any_content:
        raise ValueError(
            "Cannot import: this session already has a model and replace=False. "
            "Call import_pnml again with replace=True to overwrite it, or "
            "create_network first if you want to discard the current model "
            "deliberately."
        )

    net_data, warnings = parse_pnml(xml)
    session.load_net_data(net_data)

    place_count = len(net_data.get("places") or [])
    transition_count = len(net_data.get("transitions") or [])
    arc_count = len(net_data.get("arcs") or [])
    object_count = len(net_data.get("objects") or [])
    link_count = len(net_data.get("links") or [])
    is_composed = bool(net_data.get("objects") or net_data.get("links"))

    name = net_data.get("name") or "Imported net"
    summary = (
        f"Imported '{name}': {place_count} place(s), {transition_count} "
        f"transition(s), {arc_count} arc(s)"
    )
    if is_composed:
        summary += f", {object_count} object(s), {link_count} link(s)"
    summary += "."

    return summary + _format_pnml_warnings(warnings)


@tool_operation
def op_run_simulation(
    session: PetriNetSession,
    simulation_time: float,
    time_unit: str = "s",
) -> str:
    """Run a discrete-event simulation of the current model.

    Executes the simulation for the given time and returns statistics:
    final markings, mean values, and observed min/max for all places and
    transitions, plus a Terminators (throughput) block sourced from places
    tagged "throughput". A composed session (any named object or link)
    runs across every object in ONE simulation via the composed engine
    (placeFusion places share one slot; transitionToPlace delivers across
    the object boundary); a flat session runs exactly as before.

    Args:
        simulation_time: Total simulation time in time_unit
        time_unit: "s" (seconds, default), "min", "h", or "d" (days)
    """
    from src.services.simulation import PetriSimulator

    sim_seconds = tu.to_seconds(simulation_time, time_unit)

    if session.is_composed:
        from src.services.simulation.composed_engine import (
            ComposedSimulationUnsupported,
            build_composed_sim_net,
        )

        if not session.has_any_content:
            return "No network to simulate. Build a network first."
        model = session.build_composed_model()
        errors = model.validate()
        if errors:
            raise ValueError(
                "Cannot simulate composed model:\n" + "\n".join(f"  - {e}" for e in errors)
                + "\nFix: use validate_model for the full picture, and link_objects "
                "to wire any object that still needs one."
            )
        try:
            places, transitions = build_composed_sim_net(model)
        except ComposedSimulationUnsupported as exc:
            raise ValueError(str(exc)) from exc

        simulator = PetriSimulator.from_sim_state(places, transitions)
        result = simulator.run(sim_seconds)
        session.record_simulation_result(result)
        body = _format_simulation_result(result)
        session.persist_simulation_summary(body)
        horizon = tu.echo_duration(sim_seconds)
        return (
            f"Composed simulation across {len(model.objects)} object(s) "
            f"(including the free pool). Simulation horizon: {horizon} "
            f"(received: simulation_time={simulation_time}, time_unit={time_unit})\n\n{body}"
        )

    if not session.net.places:
        return "No network to simulate. Build a network first."

    is_valid, errors = session.net.validate_topology()
    if not is_valid:
        connectivity_errors = [e for e in errors if "disconnected" in e]
        other_errors = [e for e in errors if "disconnected" not in e]
        parts = []
        if connectivity_errors:
            parts.append(
                "Cannot simulate: " + connectivity_errors[0] + "\n"
                "Fix: use connect_patterns to link all components before running simulation."
            )
        if other_errors:
            parts.append(
                "Topology errors:\n" + "\n".join(f"  - {e}" for e in other_errors)
            )
        raise ValueError("\n\n".join(parts))

    simulator = PetriSimulator(session.net)
    result = simulator.run(sim_seconds)
    session.record_simulation_result(result)

    body = _format_simulation_result(result)
    # Also persist the formatted text onto net_data (see session.py's
    # _last_simulation_result_text), not just in-memory on `session`: the
    # chat surface rehydrates a fresh PetriNetSession per tool_node batch,
    # so a get_simulation_results call in a LATER turn would otherwise find
    # last_simulation_result already gone. op_get_simulation_results falls
    # back to this text when that happens.
    session.persist_simulation_summary(body)
    horizon = tu.echo_duration(sim_seconds)
    return (
        f"Simulation horizon: {horizon} "
        f"(received: simulation_time={simulation_time}, time_unit={time_unit})\n\n{body}"
    )


@tool_operation
def op_get_simulation_results(session: PetriNetSession) -> str:
    """Get the results of the last simulation run in this session.

    Returns formatted statistics from the most recent run_simulation call.
    Real implementation (D6): the session stores its last SimulationResult
    and this op formats it on demand; it no longer just tells the caller
    to re-run run_simulation regardless of history. Falls back to the
    formatted text persisted on net_data (session.last_simulation_summary)
    when the in-memory SimulationResult is gone, which happens on the chat
    surface whenever this call lands in a later turn than run_simulation
    did, and tool_node rehydrated a fresh session from net_data in between.
    """
    result = session.last_simulation_result
    if result is not None:
        return _format_simulation_result(result)
    summary = session.last_simulation_summary
    if summary:
        return summary
    return "No simulation has been run yet in this session. Use run_simulation first."


def _format_simulation_result(result) -> str:
    """Render a SimulationResult via SimulationSession's own formatter.

    SimulationSession.format_results() doesn't touch `self` when a result
    is passed explicitly, so a bare, unbound instance is enough here, the
    same reach-into-internals the MCP run_simulation tool already used,
    kept in exactly one place instead of two.
    """
    from src.services.simulation.session import SimulationSession

    formatter = SimulationSession.__new__(SimulationSession)
    return formatter.format_results(result)


# ---------------------------------------------------------------------------
# Generic pattern-adding op: backs every registry pattern NOT covered by
# one of the hand-written ops above (see catalog.py's pattern-introspection
# function). The single replacement for MCP's per-pattern `_impl` closure
# built by `_make_mcp_tool` and the chat agent's `_make_agent_tool`.
# ---------------------------------------------------------------------------

@tool_operation
def op_add_pattern(
    session: PetriNetSession,
    pattern_name: str,
    name: str,
    time_unit: str = "s",
    deviation_unit: str | None = None,
    **kwargs,
) -> str:
    """Add any registry pattern by name via the builder's generic add_<pattern>.

    Not meant to be called with a literal `pattern_name` argument by an
    agent; catalog.py binds `pattern_name` per pattern via
    `functools.partial` when building each auto-generated ToolSpec, so
    from a caller's perspective this is just "the pattern's add_X op."
    """
    method = getattr(session.builder, f"add_{pattern_name}")
    sig = inspect.signature(method)
    # Same helper catalog.py's _pattern_tool_spec uses to build this
    # pattern's schema, so a param excluded from time-conversion there
    # (see BasePattern.tool_non_time_params, e.g. FinitePopulationQueue's
    # n_customers/channels) is excluded here too, instead of this call site
    # re-deriving time params from a different signature without ever
    # consulting the pattern's own exclusions.
    time_params = tu.pattern_time_params(pattern_name, sig)

    cleaned = _coerce_enum_kwargs(sig, kwargs)
    for pname in time_params:
        if pname in cleaned and cleaned[pname] is not None:
            unit = deviation_unit if pname == "standard_deviation" and deviation_unit else time_unit
            cleaned[pname] = tu.to_seconds(cleaned[pname], unit)

    result = method(name=name, **cleaned)
    auto_msg = session.auto_connect(result.interface.input_place_id)
    session.set_last_output(result.interface.output_place_id)

    meta = {
        k: v for k, v in result.metadata.items()
        if isinstance(v, str) and k.endswith("_id")
    }
    time_echo = ""
    for pname in time_params:
        if pname in cleaned:
            time_echo += f", {pname}={tu.echo_duration(cleaned[pname])}"
    if time_params:
        time_echo += f", time_unit={time_unit}"
    meta_str = f" {meta}" if meta else ""
    conn_warn = _connectivity_warning(session)

    return (
        f"Added {pattern_name} '{name}'"
        f"{time_echo}. "
        f"Input: {result.interface.input_place_id}, "
        f"Output: {result.interface.output_place_id}."
        f"{meta_str}{auto_msg}{conn_warn}"
    )


@tool_operation
def op_export_image(session: PetriNetSession, title: str = "") -> str:
    """Export the current model as a network-only PNG.

    Returns filename, media_type and data_base64. Decode the base64 to save
    the actual PNG; this is a model illustration, not an editor screenshot.
    """
    from src.services.training_export import render_network, encoded_download, filename
    data, _ = render_network(session.to_net_data())
    title = title or session.to_net_data().get("name") or "Petri network"
    return encoded_download(data, filename(title, ".png"), "image/png")


@tool_operation
def op_export_training_data(
    session: PetriNetSession,
    title: str = "",
    context: dict | None = None,
    conversation: list[dict] | None = None,
    tool_calls: list[dict] | None = None,
) -> str:
    """Export task-scoped training ZIP with PNML, evidence, PNG and geometry.

    Returns filename, media_type and data_base64 for a real ZIP. context may
    provide task, clarifications, assumptions, acceptance, status and explicit
    verification. Default status is unreviewed, verification unknown. Optional
    conversation contains actual user/assistant messages; tool_calls contains
    client-observed records with actual UTC timestamps. Never invent missing
    conversations, tool results, timestamps or successful verification.
    """
    from src.services.training_export import build_training_bundle, encoded_download
    observed = getattr(session, "_export_tool_trace", [])
    context = dict(context or {})
    if getattr(session, "_export_trace_truncated", False) and tool_calls is None:
        context["trace_truncated"] = True
    simulation = None
    if session.last_simulation_result is not None:
        from dataclasses import asdict
        observed_result = session.last_simulation_result
        results = asdict(observed_result)
        results["summary"] = session.last_simulation_summary or ""
        simulation = {"parameters": {"simulation_time": observed_result.simulation_time, "time_unit": "s"},
                      "results": results, "provenance": "application: last observed simulation result; may predate subsequent model edits"}
    elif session.last_simulation_summary:
        simulation = {"parameters": {}, "results": {"summary": session.last_simulation_summary}, "provenance": "application: recorded simulation summary; parameters unavailable; may predate model edits"}
    title = title or session.to_net_data().get("name") or "Petri session"
    data, name = build_training_bundle(
        session.to_net_data(), title, context=context, conversation=conversation,
        tool_calls=tool_calls if tool_calls is not None else observed,
        conversation_origin=getattr(session, "_export_conversation_origin", "client-provided") if conversation else "unavailable",
        tool_origin="client-provided" if tool_calls is not None else "application",
        simulation=simulation,
    )
    return encoded_download(data, name, "application/zip")
