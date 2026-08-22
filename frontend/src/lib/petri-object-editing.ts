import type {
  ObjectFrame,
  PetriArc,
  PetriNetData,
  PetriPlace,
  PetriTransition,
} from "@/types/petri";
import {
  getLinks,
  getObjects,
  objectSubtreeIds,
  refitFrame,
} from "@/lib/petri-object-model";

function withoutOwner<T extends { objectId?: string }>(element: T): T {
  const { objectId: _owner, ...rest } = element;
  return rest as T;
}

function elementLabel(net: PetriNetData, id: string): string {
  return (
    net.places.find((p) => p.id === id)?.name ??
    net.transitions.find((t) => t.id === id)?.name ??
    id
  );
}

/**
 * For each element directly or nestedly inside the object, the names of
 * whatever it connects to OUTSIDE the object — an arc or link with exactly
 * one end in the subtree. extractObjectNet drops every one of these
 * connections outright (the far end isn't part of the extracted sub-net at
 * all, so there's nothing to point an edge at), which otherwise makes a
 * place or transition wired to the outside world look no different from one
 * that never was. Purely informational: computed fresh from the parent net
 * each time an object canvas opens, never itself part of the extracted net
 * or saved with it.
 */
export function computeExternalConnections(
  net: PetriNetData,
  objectId: string,
): Map<string, string[]> {
  const subtree = objectSubtreeIds(net, objectId);
  const inside = (owner?: string) => owner !== undefined && subtree.has(owner);
  const ownerById = new Map<string, string | undefined>();
  for (const el of [...net.places, ...net.transitions]) ownerById.set(el.id, el.objectId);

  const result = new Map<string, string[]>();
  const note = (localId: string, counterpartId: string) => {
    const existing = result.get(localId);
    const label = elementLabel(net, counterpartId);
    if (existing) existing.push(label);
    else result.set(localId, [label]);
  };

  const connections = [
    ...net.arcs.map((a) => ({ sourceId: a.source_id, targetId: a.target_id })),
    ...getLinks(net).map((l) => ({ sourceId: l.sourceId, targetId: l.targetId })),
  ];
  for (const { sourceId, targetId } of connections) {
    const sourceInside = inside(ownerById.get(sourceId));
    const targetInside = inside(ownerById.get(targetId));
    if (sourceInside && !targetInside) note(sourceId, targetId);
    else if (targetInside && !sourceInside) note(targetId, sourceId);
  }
  return result;
}

/**
 * The contents of one object frame as a standalone net, ready to be edited on
 * its own canvas. Everything nested inside comes along — an object built
 * within this one stays an object, one level further in — while the frame's
 * own direct contents lose their owner so the sub-net reads as an ordinary
 * net while it is open.
 */
export function extractObjectNet(net: PetriNetData, objectId: string): PetriNetData | null {
  const frame = getObjects(net).find((o) => o.id === objectId);
  if (!frame) return null;

  const subtree = objectSubtreeIds(net, objectId);
  const inside = (owner?: string) => owner !== undefined && subtree.has(owner);
  const unparentDirect = <T extends { objectId?: string }>(element: T): T =>
    element.objectId === objectId ? withoutOwner(element) : element;

  const places: PetriPlace[] = net.places.filter((p) => inside(p.objectId)).map(unparentDirect);
  const transitions: PetriTransition[] = net.transitions
    .filter((t) => inside(t.objectId))
    .map(unparentDirect);
  const objects: ObjectFrame[] = getObjects(net)
    .filter((o) => o.id !== objectId && subtree.has(o.id))
    .map(unparentDirect);

  const contained = new Set([...places.map((p) => p.id), ...transitions.map((t) => t.id)]);
  const arcs = net.arcs.filter(
    (a) => contained.has(a.source_id) && contained.has(a.target_id),
  );
  const links = getLinks(net).filter(
    (l) => contained.has(l.sourceId) && contained.has(l.targetId),
  );

  return { name: frame.name, places, transitions, arcs, objects, links };
}

function freshId(base: string, taken: Set<string>): string {
  let n = 2;
  let candidate = `${base}_${n}`;
  while (taken.has(candidate)) {
    n++;
    candidate = `${base}_${n}`;
  }
  return candidate;
}

/**
 * The object editor mints ids against the sub-net alone, so an element created
 * there can easily be born as "p1" while the parent canvas already has a "p1"
 * outside the object. Rename just those collisions before merging, rewiring
 * the sub-net's own arcs, links and frame membership to match.
 */
function resolveIdCollisions(edited: PetriNetData, forbidden: Set<string>): PetriNetData {
  const editedObjects = getObjects(edited);
  const taken = new Set([
    ...forbidden,
    ...edited.places.map((p) => p.id),
    ...edited.transitions.map((t) => t.id),
    ...editedObjects.map((o) => o.id),
  ]);
  const remap = new Map<string, string>();

  for (const node of [...edited.places, ...edited.transitions, ...editedObjects]) {
    if (!forbidden.has(node.id)) continue;
    const next = freshId(node.id, taken);
    taken.add(next);
    remap.set(node.id, next);
  }
  if (remap.size === 0) return edited;

  const to = (id: string) => remap.get(id) ?? id;
  const reowned = <T extends { id: string; objectId?: string }>(node: T): T => ({
    ...node,
    id: to(node.id),
    objectId: node.objectId ? to(node.objectId) : node.objectId,
  });

  return {
    ...edited,
    places: edited.places.map(reowned),
    transitions: edited.transitions.map(reowned),
    objects: editedObjects.map(reowned),
    arcs: edited.arcs.map((a) => ({
      ...a,
      source_id: to(a.source_id),
      target_id: to(a.target_id),
    })),
    links: getLinks(edited).map((l) => ({
      ...l,
      sourceId: to(l.sourceId),
      targetId: to(l.targetId),
    })),
  };
}

/**
 * Merge an edited sub-net back into the canvas that owns the object. The
 * object's whole subtree is replaced: its elements, its nested objects and
 * their contents. Everything outside is untouched, and any arc or link
 * pointing at something the edit removed is dropped rather than left
 * dangling. The frame re-fits around whatever the object now contains.
 */
export function applyObjectEdit(
  parentNet: PetriNetData,
  objectId: string,
  editedNet: PetriNetData,
): PetriNetData {
  const subtree = objectSubtreeIds(parentNet, objectId);
  const wasInside = (owner?: string) => owner !== undefined && subtree.has(owner);

  const survivingPlaces = parentNet.places.filter((p) => !wasInside(p.objectId));
  const survivingTransitions = parentNet.transitions.filter((t) => !wasInside(t.objectId));
  const survivingObjects = getObjects(parentNet).filter(
    (o) => o.id === objectId || !subtree.has(o.id),
  );

  const outsideIds = new Set([
    ...survivingPlaces.map((p) => p.id),
    ...survivingTransitions.map((t) => t.id),
    ...survivingObjects.filter((o) => o.id !== objectId).map((o) => o.id),
  ]);
  const edited = resolveIdCollisions(editedNet, outsideIds);

  // What the sub-net left unparented sat directly in this object.
  const adopt = <T extends { objectId?: string }>(node: T): T =>
    node.objectId ? node : { ...node, objectId };

  const places: PetriPlace[] = [...survivingPlaces, ...edited.places.map(adopt)];
  const transitions: PetriTransition[] = [
    ...survivingTransitions,
    ...edited.transitions.map(adopt),
  ];
  const objects: ObjectFrame[] = [...survivingObjects, ...getObjects(edited).map(adopt)];

  const aliveIds = new Set([
    ...places.map((p) => p.id),
    ...transitions.map((t) => t.id),
  ]);
  // An arc the sub-net owned is replaced by the edited one; an arc with only
  // one end inside survives, so a connection into the object is not lost.
  const previousOwner = new Map<string, string | undefined>();
  for (const element of [...parentNet.places, ...parentNet.transitions]) {
    previousOwner.set(element.id, element.objectId);
  }
  const wasFullyInside = (a: { source_id: string; target_id: string }) =>
    wasInside(previousOwner.get(a.source_id)) && wasInside(previousOwner.get(a.target_id));

  const arcs: PetriArc[] = [
    ...parentNet.arcs.filter((a) => !wasFullyInside(a)),
    ...edited.arcs,
  ].filter((a) => aliveIds.has(a.source_id) && aliveIds.has(a.target_id));

  const editedLinkIds = new Set(getLinks(edited).map((l) => l.id));
  const links = [
    ...getLinks(parentNet).filter((l) => !editedLinkIds.has(l.id)),
    ...getLinks(edited),
  ].filter((l) => aliveIds.has(l.sourceId) && aliveIds.has(l.targetId));

  const merged: PetriNetData = {
    ...parentNet,
    places,
    transitions,
    arcs,
    links,
    objects: objects.map((o) =>
      o.id === objectId ? { ...o, name: editedNet.name || o.name } : o,
    ),
  };

  return refitFrame(merged, objectId);
}
