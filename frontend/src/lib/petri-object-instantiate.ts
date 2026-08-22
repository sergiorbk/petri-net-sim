import type {
  ObjectFrame,
  ObjectLink,
  PetriArc,
  PetriNetData,
  PetriPlace,
  PetriTransition,
} from "@/types/petri";
import type { PetriObjectTemplate } from "@/lib/petri-objects-client";

let counter = 0;

function uid(prefix: string): string {
  counter++;
  return `${prefix}_inst_${Date.now().toString(36)}_${counter}`;
}

function nextLabel(base: string, existing: readonly { name: string }[]): string {
  const taken = new Set(existing.map((e) => e.name));
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}_${n}`)) n++;
  return `${base}_${n}`;
}

export interface InstantiatedSubnet {
  places: PetriPlace[];
  transitions: PetriTransition[];
  arcs: PetriArc[];
  /** Nested frames of the template, ids re-minted, nesting preserved. */
  objects?: ObjectFrame[];
  /** Object links wholly inside the template, ids re-minted. */
  links?: ObjectLink[];
}

export function instantiateTemplate(
  template: PetriObjectTemplate,
  dropX: number,
  dropY: number,
  existingNet: PetriNetData,
): InstantiatedSubnet {
  const oldToNew = new Map<string, string>();
  const templateFrames = template.objects ?? [];
  const templateLinks = template.links ?? [];

  let minX = Infinity;
  let minY = Infinity;
  for (const p of template.places) {
    if (p.graphics.x < minX) minX = p.graphics.x;
    if (p.graphics.y < minY) minY = p.graphics.y;
  }
  for (const t of template.transitions) {
    if (t.graphics.x < minX) minX = t.graphics.x;
    if (t.graphics.y < minY) minY = t.graphics.y;
  }
  for (const o of templateFrames) {
    if (o.graphics.x < minX) minX = o.graphics.x;
    if (o.graphics.y < minY) minY = o.graphics.y;
  }
  if (!isFinite(minX)) minX = 0;
  if (!isFinite(minY)) minY = 0;

  const offsetX = dropX - minX;
  const offsetY = dropY - minY;

  const allPlaceNames = [...existingNet.places];
  const places: PetriPlace[] = template.places.map((p) => {
    const id = uid("p");
    oldToNew.set(p.id, id);
    const name = nextLabel(p.name, allPlaceNames);
    const place: PetriPlace = {
      id,
      name,
      tokens: p.tokens,
      // Template-internal ownership survives as-is here; the frame pass
      // below re-mints frame ids and rewires this to the new one.
      ...(p.objectId ? { objectId: p.objectId } : {}),
      graphics: {
        x: p.graphics.x + offsetX,
        y: p.graphics.y + offsetY,
      },
    };
    allPlaceNames.push(place);
    return place;
  });

  const allTransNames = [...existingNet.transitions];
  const transitions: PetriTransition[] = template.transitions.map((t) => {
    const id = uid("t");
    oldToNew.set(t.id, id);
    const name = nextLabel(t.name, allTransNames);
    const transition: PetriTransition = {
      id,
      name,
      priority: t.priority,
      distribution: t.distribution,
      mean_delay: t.mean_delay,
      standard_deviation: t.standard_deviation,
      probability: t.probability,
      ...(t.objectId ? { objectId: t.objectId } : {}),
      graphics: {
        x: t.graphics.x + offsetX,
        y: t.graphics.y + offsetY,
      },
    };
    allTransNames.push(transition);
    return transition;
  });

  const arcs: PetriArc[] = template.arcs
    .filter((a) => oldToNew.has(a.source_id) && oldToNew.has(a.target_id))
    .map((a) => ({
      id: uid("a"),
      source_id: oldToNew.get(a.source_id)!,
      target_id: oldToNew.get(a.target_id)!,
      weight: a.weight,
      arc_type: a.arc_type,
    }));

  // Nested frames come back as real frames: fresh ids first, then a second
  // pass rewires the template-internal parent pointers and memberships.
  for (const o of templateFrames) oldToNew.set(o.id, uid("o"));
  const objects: ObjectFrame[] = templateFrames.map((o) => ({
    ...o,
    id: oldToNew.get(o.id)!,
    objectId: o.objectId ? oldToNew.get(o.objectId) : undefined,
    templateId: null,
    graphics: {
      ...o.graphics,
      x: o.graphics.x + offsetX,
      y: o.graphics.y + offsetY,
    },
  }));
  const withOwner = <T extends { objectId?: string }>(el: T): T =>
    el.objectId ? { ...el, objectId: oldToNew.get(el.objectId) } : el;
  const ownedPlaces = places.map(withOwner);
  const ownedTransitions = transitions.map(withOwner);

  const links: ObjectLink[] = templateLinks
    .filter((l) => oldToNew.has(l.sourceId) && oldToNew.has(l.targetId))
    .map((l) => ({
      ...l,
      id: uid("l"),
      sourceId: oldToNew.get(l.sourceId)!,
      targetId: oldToNew.get(l.targetId)!,
    }));

  return { places: ownedPlaces, transitions: ownedTransitions, arcs, objects, links };
}
