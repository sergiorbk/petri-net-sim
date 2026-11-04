import type {
  ObjectFrame,
  ObjectLink,
  PetriPlace,
  PetriTransition,
} from "@/types/petri";

/**
 * One namespace for the whole canvas: places, transitions AND object frames
 * share it, so a subnet cannot borrow the name of an element inside another
 * one. The backend already insists on this for places and transitions (PNML
 * tools such as TINA key on the name), and the editor used to check each kind
 * only against itself, which is how "Queue" could exist twice.
 *
 * The one exception is a shared place. Places joined by a placeFusion link are
 * ONE place drawn in several objects, and a reader recognises it by its name,
 * so the members of a fusion group may carry the same name. Any other pair
 * may not.
 *
 * Kept free of petri-object-model on purpose: that module calls into this
 * one, and the fusion walk needed here is a dozen lines.
 */

export type NamedKind = "place" | "transition" | "object";

/** Whatever carries names: a net, or a group about to be added to one. */
interface Nameable {
  objects?: ObjectFrame[];
  places: PetriPlace[];
  transitions: PetriTransition[];
  links?: ObjectLink[];
}

/** One name that is already taken, and every element in the group that wants it. */
export interface NameConflict {
  /** More than one id only for places that are fused with each other. */
  ids: string[];
  kind: NamedKind;
  name: string;
  /** The first free `name_N`, chosen so the whole batch stays unique. */
  suggestion: string;
}

function everyNamed(source: Nameable): { id: string; name: string; kind: NamedKind }[] {
  return [
    ...(source.objects ?? []).map((o) => ({ id: o.id, name: o.name, kind: "object" as const })),
    ...source.places.map((p) => ({ id: p.id, name: p.name, kind: "place" as const })),
    ...source.transitions.map((t) => ({ id: t.id, name: t.name, kind: "transition" as const })),
  ];
}

/** Every name in use, across all three kinds. */
export function allNames(source: Nameable): Set<string> {
  return new Set(everyNamed(source).map((e) => e.name));
}

/** The same elements as `{ name }` records, for helpers that take a list. */
export function namedElements(source: Nameable): { name: string }[] {
  return everyNamed(source);
}

/**
 * `base` if it is free, otherwise the first free `base_N`.
 *
 * Numbers rather than words: they are short whatever the length of the name,
 * predictable, and sort the way people expect. A name that already ends in
 * `_N` continues that count (`Queue_2` -> `Queue_3`) instead of stacking a
 * second suffix (`Queue_2_2`).
 */
export function nextFreeName(base: string, taken: ReadonlySet<string>): string {
  if (!taken.has(base)) return base;
  const match = /^(.*)_(\d+)$/.exec(base);
  const stem = match ? match[1] : base;
  let n = match ? Number(match[2]) + 1 : 2;
  while (taken.has(`${stem}_${n}`)) n++;
  return `${stem}_${n}`;
}

/**
 * Which fusion set each place belongs to, keyed by place id. Only links with
 * both ends in `within` count, so a copy whose partner was left behind is not
 * treated as fused with it.
 */
function fusionClasses(
  links: readonly ObjectLink[] | undefined,
  within: ReadonlySet<string>,
): Map<string, string> {
  const parent = new Map<string, string>();
  const find = (id: string): string => {
    let root = parent.get(id) ?? id;
    while ((parent.get(root) ?? root) !== root) root = parent.get(root)!;
    parent.set(id, root);
    return root;
  };
  const linked = new Set<string>();
  for (const link of links ?? []) {
    if (link.type !== "placeFusion") continue;
    if (!within.has(link.sourceId) || !within.has(link.targetId)) continue;
    linked.add(link.sourceId);
    linked.add(link.targetId);
    const a = find(link.sourceId);
    const b = find(link.targetId);
    if (a !== b) parent.set(a, b);
  }
  // Every linked place, root included: a root is never a child in `parent`,
  // so walking its keys would leave the master out of its own group.
  const classes = new Map<string, string>();
  for (const id of linked) classes.set(id, find(id));
  return classes;
}

/**
 * The names a group asks for that the net already uses.
 *
 * Fused places inside the group count once: they are one place, so they get
 * one row and one new name, and stay equal to each other afterwards.
 * Duplicates the group already contains among itself are not reported here,
 * only collisions with `net`.
 */
export function findGroupConflicts(net: Nameable, group: Nameable): NameConflict[] {
  const inNet = allNames(net);
  const entries = everyNamed(group);
  const placeIds = new Set(group.places.map((p) => p.id));
  const classes = fusionClasses(group.links, placeIds);

  const rows = new Map<string, { ids: string[]; kind: NamedKind; name: string }>();
  for (const entry of entries) {
    if (!inNet.has(entry.name)) continue;
    const cls = entry.kind === "place" ? classes.get(entry.id) : undefined;
    const key = `${cls ?? entry.id}\u0000${entry.name}`;
    const row = rows.get(key);
    if (row) row.ids.push(entry.id);
    else rows.set(key, { ids: [entry.id], kind: entry.kind, name: entry.name });
  }

  // A suggestion must dodge the net, the group's own names (including the
  // ones that are not being renamed) and the suggestions already handed out.
  const taken = new Set([...inNet, ...entries.map((e) => e.name)]);
  return [...rows.values()].map((row) => {
    const suggestion = nextFreeName(row.name, taken);
    taken.add(suggestion);
    return { ...row, suggestion };
  });
}

/** `id -> new name` from each conflict's own suggestion. */
export function suggestedRenames(conflicts: readonly NameConflict[]): Map<string, string> {
  const renames = new Map<string, string>();
  for (const conflict of conflicts) {
    for (const id of conflict.ids) renames.set(id, conflict.suggestion);
  }
  return renames;
}

/** A copy of `group` with the given elements renamed; everything else shared. */
export function renameInGroup<G extends Nameable>(
  group: G,
  renames: ReadonlyMap<string, string>,
): G {
  if (renames.size === 0) return group;
  const rename = <T extends { id: string; name: string }>(el: T): T =>
    renames.has(el.id) ? { ...el, name: renames.get(el.id)! } : el;
  return {
    ...group,
    ...(group.objects ? { objects: group.objects.map(rename) } : {}),
    places: group.places.map(rename),
    transitions: group.transitions.map(rename),
  };
}

/**
 * The conflict created by giving element `id` the name `name`, or null when
 * the name is free. A place may keep the name of the places it is fused with.
 */
export function renameConflict(
  net: Nameable,
  id: string,
  name: string,
): { conflict: NameConflict; taken: Set<string> } | null {
  const self = everyNamed(net).find((e) => e.id === id);
  if (!self) return null;

  const placeIds = new Set(net.places.map((p) => p.id));
  const classes = fusionClasses(net.links, placeIds);
  const myClass = self.kind === "place" ? classes.get(id) : undefined;
  const isMate = (otherId: string) =>
    myClass !== undefined && otherId !== id && classes.get(otherId) === myClass;

  const others = everyNamed(net).filter((e) => e.id !== id);
  // What the new name must avoid: everyone except me and my fused partners.
  const blocking = new Set(others.filter((e) => !isMate(e.id)).map((e) => e.name));
  if (!blocking.has(name)) return null;

  const suggestion = nextFreeName(name, new Set(others.map((e) => e.name)));
  return {
    conflict: { ids: [id], kind: self.kind, name, suggestion },
    taken: blocking,
  };
}
