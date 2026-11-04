import type {
  ObjectFrame,
  ObjectLink,
  PetriArc,
  PetriPlace,
  PetriTransition,
} from "@/types/petri";
import type { PetriObjectTemplate } from "@/lib/petri-objects-client";

let counter = 0;

function uid(prefix: string): string {
  counter++;
  return `${prefix}_inst_${Date.now().toString(36)}_${counter}`;
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

  // Names are the template's own. Whether they may repeat names already on the
  // canvas is decided by whoever places the result: a palette drop warns, an
  // import keeps the file as it is (see editor-store addSubnetAsObject).
  const places: PetriPlace[] = template.places.map((p) => {
    const id = uid("p");
    oldToNew.set(p.id, id);
    const place: PetriPlace = {
      id,
      name: p.name,
      tokens: p.tokens,
      // Template-internal ownership survives as-is here; the frame pass
      // below re-mints frame ids and rewires this to the new one.
      ...(p.objectId ? { objectId: p.objectId } : {}),
      graphics: {
        x: p.graphics.x + offsetX,
        y: p.graphics.y + offsetY,
      },
    };
    return place;
  });

  const transitions: PetriTransition[] = template.transitions.map((t) => {
    const id = uid("t");
    oldToNew.set(t.id, id);
    const transition: PetriTransition = {
      id,
      name: t.name,
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
