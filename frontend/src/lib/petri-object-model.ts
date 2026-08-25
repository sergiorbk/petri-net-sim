import type {
  ObjectFrame,
  ObjectLink,
  ObjectLinkType,
  PetriArc,
  PetriNetData,
  PetriPlace,
  PetriTransition,
} from "@/types/petri";
import { nextId, nextLabel } from "@/lib/petri-ids";
import {
  boxOfElement,
  FRAME_HEADER_H,
  FRAME_MIN_H,
  FRAME_MIN_W,
  FRAME_PADDING,
  NODE_LABEL_H,
  PLACE_H,
  PLACE_W,
  TRANS_H,
  TRANS_W,
} from "@/lib/petri-geometry";

/** The object a place or transition belongs to, or undefined if it's free. */
export function ownerOf(net: PetriNetData, elementId: string): string | undefined {
  const place = net.places.find((p) => p.id === elementId);
  if (place) return place.objectId;
  const transition = net.transitions.find((t) => t.id === elementId);
  if (transition) return transition.objectId;
  return undefined;
}

/**
 * Whether an id is directly local to the current net's own top level — a
 * free place/transition, or an object frame with no owner of its own —
 * rather than something only visible here because the object that actually
 * owns it happens to be expanded. A Petri-object is managed as a unit
 * (moved, deleted, resized, renamed) from wherever it's directly local, the
 * same as any free element; what's INSIDE it is not editable from there —
 * only from that object's own canvas (its own tab, where extractObjectNet
 * strips its direct members' objectId, making THEM locally editable there
 * in turn). A frame's own objectId decides its case; ownerOf decides an
 * element's, and both are "local" under the identical rule: no owner here.
 */
export function isLocalToNet(net: PetriNetData, id: string): boolean {
  const frame = getObjects(net).find((o) => o.id === id);
  if (frame) return frame.objectId === undefined;
  const place = net.places.find((p) => p.id === id);
  if (place) return place.objectId === undefined;
  const transition = net.transitions.find((t) => t.id === id);
  if (transition) return transition.objectId === undefined;
  // An id that resolves to nothing at all is never treated as editable —
  // this gate should fail closed, not silently pass an id it can't place.
  return false;
}

export function getObjects(net: PetriNetData) {
  return net.objects ?? [];
}

export function getLinks(net: PetriNetData) {
  return net.links ?? [];
}

export interface SelectionAsTemplate {
  places: PetriPlace[];
  transitions: PetriTransition[];
  arcs: PetriArc[];
  interface: { input_place_id: string | null; output_place_id: string | null };
  /**
   * Frames nested inside the captured object, internal nesting intact; a
   * direct child of the captured object floats to the template's top level
   * (its objectId is cleared). Absent for flat captures.
   */
  objects?: ObjectFrame[];
  /** Object links wholly inside the capture (fusions, crossing flows). */
  links?: ObjectLink[];
}

/**
 * Shapes a place/transition selection into the payload the petri-objects API
 * expects for a new custom object (`PetriObjectCreateRequest.template_data`
 * minus `name`, which the caller supplies). Shared by the "Save Selection as
 * Object" menu action and the canvas's right-click "Create Petri-object".
 */
export function extractSelectionAsTemplate(
  net: PetriNetData,
  ids: Set<string>,
): SelectionAsTemplate | null {
  const places = net.places.filter((p) => ids.has(p.id));
  const transitions = net.transitions.filter((t) => ids.has(t.id));
  if (places.length === 0 && transitions.length === 0) return null;

  const nodeIds = new Set([...places.map((p) => p.id), ...transitions.map((t) => t.id)]);
  const arcs = net.arcs.filter((a) => nodeIds.has(a.source_id) && nodeIds.has(a.target_id));

  return {
    places,
    transitions,
    arcs,
    interface: {
      input_place_id: places.length > 0 ? places[0].id : null,
      output_place_id: places.length > 1 ? places[places.length - 1].id : null,
    },
  };
}

/**
 * Everything one object IS, shaped for the petri-objects library: the whole
 * nested subtree — child frames with their nesting, members at every depth,
 * arcs and object links wholly inside — not just the direct members, which
 * used to be all the library kept, silently flattening a nested object and
 * dropping its links on the way through a save. The captured object's own
 * frame is not part of the payload (dropping the template mints a fresh
 * wrapper); its direct contents float to the template's top level.
 */
export function extractObjectAsTemplate(
  net: PetriNetData,
  objectId: string,
): SelectionAsTemplate | null {
  const subtree = objectSubtreeIds(net, objectId);
  const unparentDirect = <T extends { objectId?: string }>(el: T): T =>
    el.objectId === objectId ? { ...el, objectId: undefined } : el;

  const places = net.places
    .filter((p) => p.objectId !== undefined && subtree.has(p.objectId))
    .map(unparentDirect);
  const transitions = net.transitions
    .filter((t) => t.objectId !== undefined && subtree.has(t.objectId))
    .map(unparentDirect);
  if (places.length === 0 && transitions.length === 0) return null;

  const nodeIds = new Set([...places.map((p) => p.id), ...transitions.map((t) => t.id)]);
  const arcs = net.arcs.filter((a) => nodeIds.has(a.source_id) && nodeIds.has(a.target_id));
  const links = getLinks(net).filter(
    (l) => nodeIds.has(l.sourceId) && nodeIds.has(l.targetId),
  );
  const objects = getObjects(net)
    .filter((o) => o.id !== objectId && subtree.has(o.id))
    .map(unparentDirect);

  return {
    places,
    transitions,
    arcs,
    interface: {
      input_place_id: places.length > 0 ? places[0].id : null,
      output_place_id: places.length > 1 ? places[places.length - 1].id : null,
    },
    ...(objects.length > 0 ? { objects } : {}),
    ...(links.length > 0 ? { links } : {}),
  };
}

/**
 * Every node id in the net (object frames + places + transitions) — the
 * namespace a freshly-minted frame id must avoid colliding with. Places and
 * transitions aren't guaranteed to follow this app's own p#/t# convention
 * (e.g. a net loaded from an external source), so a new frame id can't be
 * checked for uniqueness against net.objects alone.
 */
export function allNodeIds(net: PetriNetData): { id: string }[] {
  return [...getObjects(net), ...net.places, ...net.transitions];
}

/** The places and transitions belonging directly to one object frame. */
export function membersOf(net: PetriNetData, objectId: string): { id: string }[] {
  return [
    ...net.places.filter((p) => p.objectId === objectId),
    ...net.transitions.filter((t) => t.objectId === objectId),
  ];
}

/** Object frames built directly inside another frame. */
export function childObjectsOf(net: PetriNetData, objectId: string): ObjectFrame[] {
  return getObjects(net).filter((o) => o.objectId === objectId);
}

/** Everything a frame contains directly: its elements and its child frames. */
export function directContentsOf(net: PetriNetData, objectId: string): { id: string }[] {
  return [...membersOf(net, objectId), ...childObjectsOf(net, objectId)];
}

/**
 * A frame and every frame nested inside it, at any depth. Deleting, extracting
 * or collapsing an object all act on the whole subtree, not just one level.
 */
export function objectSubtreeIds(net: PetriNetData, objectId: string): Set<string> {
  const ids = new Set<string>([objectId]);
  const queue = [objectId];
  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const child of childObjectsOf(net, current)) {
      if (ids.has(child.id)) continue;
      ids.add(child.id);
      queue.push(child.id);
    }
  }
  return ids;
}

/**
 * Abstraction level of a frame: 1 for an object sitting on the net, 2 for one
 * built inside it, and so on. The net itself is level 0.
 */
export function objectLevel(net: PetriNetData, objectId: string): number {
  const byId = new Map(getObjects(net).map((o) => [o.id, o]));
  let level = 1;
  let current = byId.get(objectId)?.objectId;
  const seen = new Set<string>([objectId]);
  while (current && !seen.has(current)) {
    seen.add(current);
    level++;
    current = byId.get(current)?.objectId;
  }
  return level;
}

/**
 * Frames ordered so that every parent precedes its children — React Flow
 * requires a node's parent to already exist earlier in the node array.
 */
export function objectsParentFirst(net: PetriNetData): ObjectFrame[] {
  const frames = getObjects(net);
  const byParent = new Map<string | undefined, ObjectFrame[]>();
  for (const frame of frames) {
    const key = frame.objectId;
    const siblings = byParent.get(key);
    if (siblings) siblings.push(frame);
    else byParent.set(key, [frame]);
  }

  const ordered: ObjectFrame[] = [];
  const visit = (parentId: string | undefined) => {
    for (const frame of byParent.get(parentId) ?? []) {
      ordered.push(frame);
      visit(frame.id);
    }
  };
  visit(undefined);

  // A frame whose parent is missing (or part of a cycle) would otherwise be
  // dropped from the canvas entirely; surface it at the top level instead.
  if (ordered.length < frames.length) {
    const placed = new Set(ordered.map((o) => o.id));
    for (const frame of frames) if (!placed.has(frame.id)) ordered.push(frame);
  }
  return ordered;
}

/**
 * Frame bounds that clear a set of places/transitions: their true boxes (not
 * just their top-left corners) plus a uniform padding, extra room at the top
 * for the frame's header chrome and at the bottom for the node captions that
 * render below each box. Returns null when no id resolves to an element.
 */
export function frameBoundsFor(
  net: PetriNetData,
  ids: Set<string>,
): { x: number; y: number; width: number; height: number } | null {
  const boxes = [...ids]
    .map((id) => boxOfElement(net, id))
    .filter((b): b is NonNullable<typeof b> => b !== null);
  if (boxes.length === 0) return null;

  const minX = Math.min(...boxes.map((b) => b.x)) - FRAME_PADDING;
  const minY =
    Math.min(...boxes.map((b) => b.y)) - FRAME_PADDING - FRAME_HEADER_H;
  const maxX = Math.max(...boxes.map((b) => b.x + b.w)) + FRAME_PADDING;
  const maxY =
    Math.max(...boxes.map((b) => b.y + b.h)) + FRAME_PADDING + NODE_LABEL_H;

  return {
    x: minX,
    y: minY,
    width: Math.max(FRAME_MIN_W, maxX - minX),
    height: Math.max(FRAME_MIN_H, maxY - minY),
  };
}

/**
 * Re-fit one frame around its current members. A no-op for a frame the user
 * has sized by hand (autoFit === false), for an unknown id, and for an empty
 * frame — an object that lost its last member keeps its box so it stays
 * visible and droppable rather than collapsing to nothing.
 *
 * Members carry absolute coordinates, so moving the frame alone leaves them
 * exactly where they were on the canvas.
 */
export function refitFrame(net: PetriNetData, objectId: string): PetriNetData {
  const frame = getObjects(net).find((o) => o.id === objectId);
  if (!frame || frame.autoFit === false) return net;

  // Child frames are enclosed just like elements are, so the fit covers both.
  const memberIds = new Set(directContentsOf(net, objectId).map((m) => m.id));
  if (memberIds.size === 0) return net;

  const bounds = frameBoundsFor(net, memberIds);
  if (!bounds) return net;

  const g = frame.graphics;
  if (
    g.x === bounds.x &&
    g.y === bounds.y &&
    g.width === bounds.width &&
    g.height === bounds.height
  ) {
    return net;
  }

  return {
    ...net,
    objects: getObjects(net).map((o) =>
      o.id === objectId ? { ...o, graphics: bounds } : o,
    ),
  };
}

/** Re-fit every auto-fitting frame — used after bulk edits touching many objects. */
export function refitAllFrames(net: PetriNetData): PetriNetData {
  return getObjects(net).reduce((acc, o) => refitFrame(acc, o.id), net);
}

/** A self-contained group of elements, as copied, pasted or duplicated. */
export interface ElementGroup {
  objects: ObjectFrame[];
  places: PetriPlace[];
  transitions: PetriTransition[];
  arcs: PetriArc[];
  /**
   * Object links whose both endpoints are inside the group — a place fusion
   * between two of the group's own members (e.g. the outer frame's place
   * fused with one inside a nested child) or a crossing arc-as-link. Without
   * this, copying or duplicating an object silently drops its internal shared
   * places, the same bug class the desktop app fixed.
   */
  links: ObjectLink[];
}

/**
 * Fresh copies of a group of elements, ready to be appended to `net`: new ids
 * that collide with nothing already there, de-duplicated names, positions
 * shifted by `offset`, and internal wiring re-pointed at the copies.
 *
 * Membership only survives when the owning frame is part of the group — a
 * member copied without its object comes out free rather than silently
 * joining the original's frame, which would put it somewhere it isn't.
 */
export function cloneElements(
  net: PetriNetData,
  group: ElementGroup,
  offset: { x: number; y: number },
): ElementGroup {
  const idMap = new Map<string, string>();

  const existingObjects = [...getObjects(net)];
  const objects = group.objects.map((frame) => {
    const id = nextId("o", [...allNodeIds(net), ...existingObjects]);
    idMap.set(frame.id, id);
    const clone: ObjectFrame = {
      ...frame,
      id,
      name: nextLabel(frame.name, existingObjects),
      // A nested frame's parent pointer follows its own parent's clone, the
      // same way a member's objectId is remapped below — otherwise a copied
      // child frame would stay attached to the ORIGINAL outer frame instead
      // of the copy. group.objects is parent-first (objectAsGroup puts the
      // requested frame at index 0), so the parent's id is already in idMap
      // by the time a child is processed. A parent that isn't part of the
      // group comes out top-level, mirroring how a stray member comes out free.
      objectId: frame.objectId ? idMap.get(frame.objectId) : undefined,
      graphics: {
        ...frame.graphics,
        x: frame.graphics.x + offset.x,
        y: frame.graphics.y + offset.y,
      },
    };
    existingObjects.push(clone);
    return clone;
  });

  const existingPlaces = [...net.places];
  const places = group.places.map((place) => {
    const id = nextId("p", [...existingPlaces, ...net.transitions, ...existingObjects]);
    idMap.set(place.id, id);
    const clone: PetriPlace = {
      ...place,
      id,
      name: nextLabel(place.name, existingPlaces),
      objectId: place.objectId ? idMap.get(place.objectId) : undefined,
      graphics: { x: place.graphics.x + offset.x, y: place.graphics.y + offset.y },
    };
    existingPlaces.push(clone);
    return clone;
  });

  const existingTransitions = [...net.transitions];
  const transitions = group.transitions.map((transition) => {
    const id = nextId("t", [...existingTransitions, ...existingPlaces, ...existingObjects]);
    idMap.set(transition.id, id);
    const clone: PetriTransition = {
      ...transition,
      id,
      name: nextLabel(transition.name, existingTransitions),
      objectId: transition.objectId ? idMap.get(transition.objectId) : undefined,
      graphics: {
        x: transition.graphics.x + offset.x,
        y: transition.graphics.y + offset.y,
      },
    };
    existingTransitions.push(clone);
    return clone;
  });

  const existingArcs = [...net.arcs];
  const arcs = group.arcs
    .filter((a) => idMap.has(a.source_id) && idMap.has(a.target_id))
    .map((arc) => {
      const clone: PetriArc = {
        ...arc,
        id: nextId("a", existingArcs),
        source_id: idMap.get(arc.source_id)!,
        target_id: idMap.get(arc.target_id)!,
      };
      existingArcs.push(clone);
      return clone;
    });

  // Only a link whose BOTH endpoints were copied re-points at the copies — one
  // dangling off the edge of the group (e.g. a fusion with a place outside a
  // partial selection) is left behind rather than pointing back at a place
  // that wasn't cloned.
  const existingLinks = [...getLinks(net)];
  const links = group.links
    .filter((l) => idMap.has(l.sourceId) && idMap.has(l.targetId))
    .map((link) => {
      const clone: ObjectLink = {
        ...link,
        id: nextLinkId(existingLinks),
        sourceId: idMap.get(link.sourceId)!,
        targetId: idMap.get(link.targetId)!,
      };
      existingLinks.push(clone);
      return clone;
    });

  return { objects, places, transitions, arcs, links };
}

/**
 * One object frame with everything inside it — the unit that copy, paste and
 * duplicate operate on when an object is selected.
 */
export function objectAsGroup(net: PetriNetData, objectId: string): ElementGroup | null {
  const frame = getObjects(net).find((o) => o.id === objectId);
  if (!frame) return null;

  // A frame built inside this one is part of the unit being copied too.
  // objectSubtreeIds discovers ids breadth-first starting at objectId, so
  // iterating the Set in insertion order — rather than net.objects' own
  // order, which objectsParentFirst exists precisely because it ISN'T
  // guaranteed to follow — puts the requested frame at index 0 (what
  // duplicateObject reads back as "the copy of what was asked for") and every
  // parent ahead of its children, which cloneElements' objectId remap relies on.
  const frameIds = objectSubtreeIds(net, objectId);
  const objectsById = new Map(getObjects(net).map((o) => [o.id, o]));
  const objects = [...frameIds]
    .map((frameId) => objectsById.get(frameId))
    .filter((o): o is ObjectFrame => o !== undefined);

  const places = net.places.filter((p) => p.objectId !== undefined && frameIds.has(p.objectId));
  const transitions = net.transitions.filter(
    (t) => t.objectId !== undefined && frameIds.has(t.objectId),
  );
  const memberIds = new Set([...places.map((p) => p.id), ...transitions.map((t) => t.id)]);
  const arcs = net.arcs.filter(
    (a) => memberIds.has(a.source_id) && memberIds.has(a.target_id),
  );
  // An internal shared place — one member fused with another member elsewhere
  // in the subtree (e.g. the outer frame's place fused with one inside a
  // nested child) — travels with the copy too, not just plain arcs.
  const links = getLinks(net).filter(
    (l) => memberIds.has(l.sourceId) && memberIds.has(l.targetId),
  );

  return { objects, places, transitions, arcs, links };
}

/** Spreadsheet-style group name: A, B, … Z, AA, AB, … */
function fusionGroupLabel(index: number): string {
  let n = index;
  let label = "";
  do {
    label = String.fromCharCode(65 + (n % 26)) + label;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return label;
}

export interface FusionGroup {
  /** Short name shown on every place in the group. */
  label: string;
  /** Every place id in the group, including the one this entry is keyed by. */
  members: string[];
  /**
   * The member every other one in the group ultimately repeats: the single
   * member that is never a placeFusion link's sourceId. rejectionForFusion's
   * rules 3 and 4 (one master per copy, no loops) guarantee a well-formed
   * group has exactly one such member; a group loaded from somewhere that
   * doesn't hold that invariant falls back to the group's first member so a
   * corrupt input still resolves to *something* rather than throwing.
   */
  root: string;
}

/**
 * Fusion is transitive — fusing A with B and B with C makes all three one
 * place — so the groups are the connected components of the place-fusion
 * relation, not the individual links. Each participating place is mapped to
 * its group, which is what lets a fused place be marked as such on its own,
 * even when its partners are off-screen or on another canvas.
 *
 * Labels follow link order so they stay stable as the net grows.
 */
export function fusionGroupsByPlace(net: PetriNetData): Map<string, FusionGroup> {
  const neighbours = new Map<string, string[]>();
  const order: string[] = [];
  const note = (id: string, other: string) => {
    const existing = neighbours.get(id);
    if (existing) existing.push(other);
    else {
      neighbours.set(id, [other]);
      order.push(id);
    }
  };

  // A place that is a source of some link repeats another one, so it can
  // never be the group's root: that's the sole member the walk below
  // doesn't rule out.
  const sourceIds = new Set<string>();
  for (const link of getLinks(net)) {
    if (link.type !== "placeFusion") continue;
    note(link.sourceId, link.targetId);
    note(link.targetId, link.sourceId);
    sourceIds.add(link.sourceId);
  }

  const result = new Map<string, FusionGroup>();
  let groupIndex = 0;

  for (const start of order) {
    if (result.has(start)) continue;

    const members: string[] = [];
    const queue = [start];
    const seen = new Set([start]);
    while (queue.length > 0) {
      const id = queue.shift()!;
      members.push(id);
      for (const next of neighbours.get(id) ?? []) {
        if (seen.has(next)) continue;
        seen.add(next);
        queue.push(next);
      }
    }

    const root = members.find((id) => !sourceIds.has(id)) ?? members[0];
    const group: FusionGroup = { label: fusionGroupLabel(groupIndex), members, root };
    for (const id of members) result.set(id, group);
    groupIndex++;
  }

  return result;
}

export type FusionRejectionReason =
  | "selfLink"
  | "alreadyLinked"
  | "copyAlreadyLinked"
  | "wouldCreateLoop"
  | "sameObject";

/**
 * Wording for each FusionRejectionReason, phrased to slot after a colon in a
 * sentence ("Dropped the link X = Y: <reason>."), the shape a document- or
 * export-time report needs. The editor's own toast (canvas.fusion.rejection.*
 * in the locale files) says the identical thing as a full sentence, so a user
 * sees the same explanation whether the rejection happened at their cursor,
 * on opening a file, or on saving one.
 */
export const FUSION_REJECTION_REASON_TEXT: Record<FusionRejectionReason, string> = {
  selfLink: "a place cannot be linked to itself",
  alreadyLinked:
    "these two places are already linked; a link in the opposite direction is not allowed either",
  copyAlreadyLinked:
    "that place already copies another one; a place can repeat a single source, otherwise there is no saying which marking it holds",
  wouldCreateLoop: "that would make a loop of links, where each place copies the next",
  sameObject: "both places belong to the same Petri-object, so linking them would have it repeat itself",
};

/**
 * The single authority for whether a placeFusion link from `copyId` to
 * `masterId` is allowed, in the order desktop PetriObjModelPaint's
 * GraphCanvasModel.rejectionFor checks them. Both the editor gesture and a
 * document being opened (pnml-import) consult this, so there is only ever
 * one place that can disagree with itself about a link.
 *
 * A shared place is a directed reference, not an undirected merge: `copyId`
 * is the place that repeats another, `masterId` is the one repeated, and it
 * holds the marking (see addObjectLink). One master may be repeated by any
 * number of copies (that fan is the desktop's headline change from this
 * app's old strict 1-to-1 rule), but a copy may repeat only one master
 * (rule 3), and chains of copies are fine as long as they never close a
 * loop (rule 4).
 */
export function rejectionForFusion(
  net: PetriNetData,
  copyId: string,
  masterId: string,
): FusionRejectionReason | null {
  if (copyId === masterId) return "selfLink";

  const fusionLinks = getLinks(net).filter((l) => l.type === "placeFusion");

  const alreadyLinked = fusionLinks.some(
    (l) =>
      (l.sourceId === copyId && l.targetId === masterId) ||
      (l.sourceId === masterId && l.targetId === copyId),
  );
  if (alreadyLinked) return "alreadyLinked";

  // A place can repeat a single source; otherwise there is no saying which
  // marking it holds. This is what makes the fan legal in one direction
  // only: masterId may already be plenty of OTHER links' target, that's
  // the fan, but copyId itself may not already be repeating someone else.
  if (fusionLinks.some((l) => l.sourceId === copyId)) return "copyAlreadyLinked";

  // Walk up from masterId along each place's own source link (the link
  // where it is the copy): if copyId turns up on that chain, this link
  // would close a loop of "each place copies the next". Bounded by the
  // link count so a corrupt document already on disk can't hang the walk.
  const masterOfCopy = new Map(fusionLinks.map((l) => [l.sourceId, l.targetId]));
  let current: string | undefined = masterOfCopy.get(masterId);
  for (let steps = 0; current !== undefined && steps < fusionLinks.length; steps++) {
    if (current === copyId) return "wouldCreateLoop";
    current = masterOfCopy.get(current);
  }

  // Two places with no object at all are not "the same object": only a
  // shared, DEFINED owner rules the link out.
  const copyOwner = ownerOf(net, copyId);
  if (copyOwner !== undefined && copyOwner === ownerOf(net, masterId)) return "sameObject";

  return null;
}

/**
 * A shared place is one marking wearing two faces, but a running simulation
 * only ever reports whichever half it happens to know by id — the composed
 * engine still tracks the pair as two separate places, not a merged one.
 * Without mirroring, the half the engine didn't name keeps showing its stale
 * pre-run count forever and never joins the animation, exactly the "joined
 * half" bug PetriObjModelPaint had to fix for the same reason. Returns
 * undefined only when neither this place nor any fusion partner has an
 * entry — not currently simulating, or genuinely not fused.
 */
export function resolveFusionMarking(
  fusionGroups: Map<string, FusionGroup>,
  markings: Record<string, number>,
  placeId: string,
): number | undefined {
  const group = fusionGroups.get(placeId);
  // One place, one marking, and it's the ROOT master's, not whichever
  // member the snapshot happens to name, and not this place's own entry
  // just because it's the one asked about.
  const rootMarking = group ? markings[group.root] : undefined;
  if (rootMarking !== undefined) return rootMarking;
  const direct = markings[placeId];
  if (direct !== undefined) return direct;
  if (!group) return undefined;
  for (const memberId of group.members) {
    const m = markings[memberId];
    if (m !== undefined) return m;
  }
  return undefined;
}

export function nextLinkId(existing: readonly { id: string }[]): string {
  let n = existing.length + 1;
  const taken = new Set(existing.map((e) => e.id));
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const id = `link${n}`;
    if (!taken.has(id)) return id;
    n++;
  }
}

/**
 * Cross-object "place feeds a foreign transition" is expressed the way
 * PetriObjModelPaint expresses it, and the way the Python composed engine's
 * ComposedSimulationUnsupported error asks for it: never a direct
 * placeToTransition link, only placeFusion. A local place is synthesized
 * inside the transition's own object, wired to it with an ordinary local
 * arc, and fused back to `placeId`, so the transition ends up with exactly
 * one input list, all of it local, and nothing left for a second
 * cross-object mechanism to duplicate.
 *
 * The proxy REPEATS placeId: placeId is the master (it holds the real,
 * user-visible marking; the proxy is a purely technical stand-in that lets a
 * local arc reach a foreign transition), so the link is stored copy -> master
 * the same way any other placeFusion is: sourceId is the fresh proxy,
 * targetId is placeId (see rejectionForFusion's docstring for why the
 * direction isn't a free choice: the PNML exporter's electSharedPlaces
 * makes the target the survivor, and placeId must stay the real `<place>`).
 *
 * No call to rejectionForFusion is needed here: the proxy is always a
 * brand-new place that has never been anyone's copy or master before, its
 * object already differs from placeId's own by construction (the check just
 * above), and it therefore cannot fail any of the five rules. Unlike the
 * old strict 1-to-1 rule this replaced, placeId already belonging to a
 * fusion group of its own is no longer a reason to refuse.
 *
 * Returns null only when either id doesn't resolve to what it should: a
 * place, a transition owned by some OTHER object than the place (a free
 * transition has no object to synthesize a proxy place inside).
 */
export function synthesizePlaceToTransitionFusion(
  net: PetriNetData,
  placeId: string,
  transitionId: string,
  opts?: { quantity?: number; informational?: boolean },
): { net: PetriNetData; linkId: string } | null {
  const place = net.places.find((p) => p.id === placeId);
  const transition = net.transitions.find((t) => t.id === transitionId);
  if (!place || !transition) return null;
  if (transition.objectId === undefined || transition.objectId === place.objectId) return null;

  const proxyPlace: PetriPlace = {
    id: nextId("p", net.places),
    name: nextLabel("Place", net.places, 1),
    tokens: place.tokens,
    graphics: { x: transition.graphics.x - 80, y: transition.graphics.y },
    objectId: transition.objectId,
  };

  const arc: PetriArc = {
    id: nextId("a", net.arcs),
    source_id: proxyPlace.id,
    target_id: transitionId,
    weight: opts?.quantity ?? 1,
    arc_type: opts?.informational ? "READ" : "NORMAL",
  };

  const links = getLinks(net);
  const linkId = nextLinkId(links);
  const link: ObjectLink = {
    id: linkId,
    type: "placeFusion",
    sourceId: proxyPlace.id,
    targetId: placeId,
    quantity: 1,
    informational: undefined,
  };

  return {
    net: {
      ...net,
      places: [...net.places, proxyPlace],
      arcs: [...net.arcs, arc],
      links: [...links, link],
    },
    linkId,
  };
}

/**
 * After changing which object some elements belong to, any existing arc
 * whose two endpoints now have different owners can no longer be a normal
 * arc. A place-sourced one is rebuilt as a synthesized fusion, exactly like
 * a freshly drawn one (synthesizePlaceToTransitionFusion) rather than being
 * silently dropped (the class of bug present in this app's existing "save
 * selection as template" flow, which just discards a boundary-crossing arc
 * outright); a transition-sourced one still becomes a transitionToPlace
 * link, which is unaffected by placeToTransition's retirement.
 */
export function reconcileArcsForNewMembership(
  net: PetriNetData,
  changedIds: Set<string>,
): PetriNetData {
  const originalArcs = net.arcs;
  let workingNet = net;
  const toRemove = new Set<string>();

  for (const arc of originalArcs) {
    const touchesChanged = changedIds.has(arc.source_id) || changedIds.has(arc.target_id);
    const sourceOwner = ownerOf(workingNet, arc.source_id);
    const targetOwner = ownerOf(workingNet, arc.target_id);

    if (!touchesChanged || sourceOwner === targetOwner) continue;

    toRemove.add(arc.id);
    const sourceIsPlace = workingNet.places.some((p) => p.id === arc.source_id);

    if (sourceIsPlace) {
      const synthesized = synthesizePlaceToTransitionFusion(workingNet, arc.source_id, arc.target_id, {
        quantity: arc.weight,
      });
      if (synthesized) {
        workingNet = synthesized.net;
        continue;
      }
      // synthesizePlaceToTransitionFusion only refuses when the transition
      // itself is free (no object to build a local proxy place inside): a
      // fusion already touching the source place is no longer a reason to
      // refuse, now that one master may be repeated by any number of copies.
      // Fall back to the old raw link rather than lose the connection
      // outright. Invalid per the backend's validate(), same as any other
      // unresolved boundary clash; the user resolves it by hand from the
      // property inspector.
    }

    const type: ObjectLinkType = sourceIsPlace ? "placeToTransition" : "transitionToPlace";
    const id = nextLinkId(getLinks(workingNet));
    workingNet = {
      ...workingNet,
      links: [
        ...getLinks(workingNet),
        {
          id,
          type,
          sourceId: arc.source_id,
          targetId: arc.target_id,
          quantity: arc.weight,
          informational: type === "placeToTransition" ? false : undefined,
        },
      ],
    };
  }

  if (toRemove.size === 0) return net;

  return { ...workingNet, arcs: workingNet.arcs.filter((a) => !toRemove.has(a.id)) };
}

/**
 * The mirror image of {@link reconcileArcsForNewMembership}: after a
 * membership change frees an element or merges two frames' contents, any
 * existing ObjectLink whose two endpoints now share ONE owner (both free
 * counts as sharing "no owner") fails the same invariant addObjectLink
 * enforces at creation time — "the whole point of a link is connecting two
 * DIFFERENT objects". Rather than leaving that link dangling in place:
 *  - a placeFusion is dropped. The two places are siblings again (or both
 *    free); FIX 1/2's marking adoption already happened when they were
 *    joined, and un-doing that merge is not this function's job — it only
 *    removes the now-meaningless identity link.
 *  - a directional link (transitionToPlace/placeToTransition) becomes an
 *    ordinary arc instead, so the flow it represented isn't silently lost —
 *    the inverse of what reconcileArcsForNewMembership does for an arc that
 *    starts crossing a boundary.
 *
 * Called after ungrouping a frame and after removing a single element from
 * one, wherever a link's endpoints could have just lost their difference.
 */
export function reconcileLinksForNewMembership(net: PetriNetData): PetriNetData {
  const links = getLinks(net);
  if (links.length === 0) return net;

  const keptLinks: ObjectLink[] = [];
  const newArcs: PetriArc[] = [];
  const existingArcs = net.arcs;

  for (const link of links) {
    const sourceOwner = ownerOf(net, link.sourceId);
    const targetOwner = ownerOf(net, link.targetId);
    if (sourceOwner !== targetOwner) {
      keptLinks.push(link);
      continue;
    }

    if (link.type === "placeFusion") continue; // no longer two different places' identities

    newArcs.push({
      id: nextId("a", [...existingArcs, ...newArcs]),
      source_id: link.sourceId,
      target_id: link.targetId,
      weight: link.quantity,
      arc_type: link.informational ? "READ" : "NORMAL",
    });
  }

  if (keptLinks.length === links.length) return net;

  return {
    ...net,
    links: keptLinks,
    arcs: newArcs.length > 0 ? [...net.arcs, ...newArcs] : net.arcs,
  };
}

/**
 * The frame whose bounds contain a point, or undefined. With frames nested
 * inside each other the INNERMOST containing frame wins: the first-in-array
 * frame used to, which silently handed a drop aimed at a child object to its
 * enclosing parent. A collapsed frame never matches: its interior is closed,
 * and a drop swallowed into content the user cannot see is exactly the bug
 * class the desktop app had to fix.
 *
 * `skip` rules a frame out as an answer while leaving it in the array the
 * nesting depth is measured against: the object band needs "the innermost
 * frame here that the band does not itself swallow", and a skipped frame's
 * children must still report their true depth.
 */
export function frameAtPoint(
  frames: readonly ObjectFrame[],
  point: { x: number; y: number },
  opts?: { skip?: (frame: ObjectFrame) => boolean },
): ObjectFrame | undefined {
  const containing = frames.filter(
    (f) =>
      !f.collapsed &&
      !opts?.skip?.(f) &&
      point.x >= f.graphics.x &&
      point.x <= f.graphics.x + f.graphics.width &&
      point.y >= f.graphics.y &&
      point.y <= f.graphics.y + f.graphics.height,
  );
  if (containing.length <= 1) return containing[0];

  const byId = new Map(frames.map((f) => [f.id, f]));
  const depthOf = (frame: ObjectFrame): number => {
    let depth = 0;
    const seen = new Set<string>([frame.id]);
    let parent = frame.objectId ? byId.get(frame.objectId) : undefined;
    while (parent && !seen.has(parent.id)) {
      seen.add(parent.id);
      depth++;
      parent = parent.objectId ? byId.get(parent.objectId) : undefined;
    }
    return depth;
  };
  return containing.reduce((deepest, f) => (depthOf(f) > depthOf(deepest) ? f : deepest));
}

/** The rectangle a Petri-object band was dragged out, in flow coordinates. */
export interface ObjectBand {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export interface ObjectBandCapture {
  /** The frame the band was drawn INSIDE: the new object's parent, if any. */
  parentId?: string;
  /** What the new object takes as its own direct contents. */
  capturedIds: string[];
}

/**
 * What a Petri-object band gesture means: which frame the new object is built
 * inside, and what it swallows.
 *
 * A band that SWALLOWS a frame wraps it: the new object goes around it, one
 * level shallower. Only a frame the band sits inside can be its parent, so a
 * swallowed frame is ruled out as a candidate however deep the band's centre
 * lands in it. Reading the centre alone (the frame is under it either way)
 * meant a band drawn around an object built the new frame INSIDE that object
 * instead of around it: the user saw the two names trade places, and a third
 * band closed a parent cycle that hung the editor.
 *
 * A frame joins the capture only when swallowed whole: its centre being in
 * range is not enough for a large frame under a small band, the same rule the
 * select-box marquee uses. Elements go by centre, as they always have. Only
 * what is loose at the band's own level (free, or a direct member of the
 * parent frame) is capturable; a swallowed frame's own contents travel with
 * their frame, and members of OTHER objects stay where they are.
 */
export function resolveObjectBand(net: PetriNetData, band: ObjectBand): ObjectBandCapture {
  const frames = getObjects(net);
  const swallows = (g: ObjectFrame["graphics"]) =>
    g.x >= band.minX &&
    g.y >= band.minY &&
    g.x + g.width <= band.maxX &&
    g.y + g.height <= band.maxY;

  const parent = frameAtPoint(
    frames,
    { x: (band.minX + band.maxX) / 2, y: (band.minY + band.maxY) / 2 },
    { skip: (f) => swallows(f.graphics) },
  );

  const capturable = (owner?: string) => owner === undefined || owner === parent?.id;
  const centred = (g: { x: number; y: number }, w: number, h: number) => {
    const cx = g.x + w / 2;
    const cy = g.y + h / 2;
    return cx >= band.minX && cx <= band.maxX && cy >= band.minY && cy <= band.maxY;
  };

  return {
    parentId: parent?.id,
    capturedIds: [
      ...frames
        .filter((f) => f.id !== parent?.id && capturable(f.objectId) && swallows(f.graphics))
        .map((f) => f.id),
      ...net.places
        .filter((p) => capturable(p.objectId) && centred(p.graphics, PLACE_W, PLACE_H))
        .map((p) => p.id),
      ...net.transitions
        .filter((t) => capturable(t.objectId) && centred(t.graphics, TRANS_W, TRANS_H))
        .map((t) => t.id),
    ],
  };
}
