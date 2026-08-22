import type { ComposedLinkSpec, ComposedObjectSpec, ComposedSimulateBody } from "@/lib/composed-simulation-client";
import type { ArcType, PetriTransition } from "@/types/petri";
import { version as appVersion } from "../../package.json";
import { FRAME_MIN_H, FRAME_MIN_W, PLACE_H, PLACE_W, TRANS_H, TRANS_W } from "@/lib/petri-geometry";

/**
 * Serialises a composed (Petri-object) model to ISO/IEC 15909-2 conformant
 * PNML: one `<page>` per object plus standard `<referencePlace>` /
 * `<referenceTransition>` nodes for cross-object structure, instead of
 * hiding that structure entirely inside `<toolspecific>` the way the wire
 * format historically did. See the composed-PNML conformance spec for the
 * full contract this file implements; every §-reference in a comment below
 * points at that document.
 *
 * Hand-written string serialisation rather than a generic XML builder: a
 * fusion `<referencePlace>` has to interleave with `<place>` elements at
 * exactly the position of the place it replaces (§3), and object-keyed
 * builders group same-named children together, which cannot express that.
 */

/** Escapes text content and attribute values for inclusion in the XML output. */
export function escapeXml(value: string | number): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function round(n: number): number {
  return Math.round(n);
}

/**
 * A place's/transition's wire position is the CENTER of its node shape; the
 * app model (`graphics.x/y`) keeps React Flow's top-left anchor. Converting
 * here, once, at the export boundary, is what keeps every reader (this app's
 * own importer, the desktop's) landing a node exactly where the user drew it.
 * Sizes come from petri-geometry.ts, the same numbers the canvas itself draws
 * with; a reference node uses the size of whichever kind it stands for.
 */
function placeCenter(x: number, y: number): { x: number; y: number } {
  return { x: round(x + PLACE_W / 2), y: round(y + PLACE_H / 2) };
}
function transitionCenter(x: number, y: number): { x: number; y: number } {
  return { x: round(x + TRANS_W / 2), y: round(y + TRANS_H / 2) };
}

/**
 * A deliberate ASCII under-approximation of the XML NCName grammar: every id
 * this pair of exporters ever writes is ASCII, and a real NCName also allows
 * a wider set of Unicode letters/combining marks neither writer produces.
 * Matches the backend's own `_NCNAME_RE` (composed_pnml_exporter.py) so both
 * writers agree on what counts as valid.
 */
const NCNAME_RE = /^[A-Za-z_][A-Za-z0-9_.\-]*$/;

export function isNCName(id: string): boolean {
  return NCNAME_RE.test(id);
}

/**
 * Makes an arbitrary string safe to write as an XML id: every character
 * outside the NCName alphabet becomes "-"; an invalid (or absent) first
 * character gets an "n-" prefix; runs of "-" then collapse to one and
 * leading/trailing "-" are trimmed, with the "n-" prefix immune to that trim
 * since it starts with a letter, not a dash. A result that sanitizes to
 * nothing becomes "n".
 *
 * This is the safety net for hand-assembled or externally-loaded data (a
 * composed-simulate request body built by hand, a canvas element cloned from
 * a foreign import); the canvas's own id minting (petri-ids.ts) is already
 * NCName-safe by construction. Export never throws over an id shape; it
 * remaps silently so the file it produces is always valid.
 */
export function sanitizeNCName(id: string): string {
  let s = id.replace(/[^A-Za-z0-9_.\-]/g, "-");
  if (!/^[A-Za-z_]/.test(s)) s = `n-${s}`;
  s = s.replace(/-+/g, "-").replace(/^-+|-+$/g, "");
  return s.length > 0 ? s : "n";
}

/** What `buildIdRemap` hands back: one final id per input, plus how a reference to a raw id resolves. */
export interface IdAssignment {
  /** The final id written for the n-th entry of `rawIds`, in the same order. */
  ids: string[];
  /**
   * What a REFERENCE to a raw id (an arc's source/target, a representative
   * node's target) should resolve to: the final id of the FIRST element that
   * ever carried that raw id, matching the importer's first-wins semantics
   * for a document (or, here, a hand-assembled request) with a genuine
   * duplicate. Falls back to the raw id itself if it was never assigned one,
   * which is the caller's own signal that nothing in `rawIds` claims it.
   */
  resolve(rawId: string): string;
}

/**
 * Assigns a final, document-unique, NCName-safe id to every entry of
 * `rawIds`, in order: a raw id that is already a valid NCName and not yet
 * claimed keeps itself; otherwise (including a second element carrying a raw
 * id an earlier one already used: `buildIdRemap` cannot tell "the same id
 * string, reused" from "the same id, referenced again" except by this order,
 * so the first occurrence always keeps the spelling and the assignment can
 * never be keyed by the raw string alone) it is sanitized and, on a
 * collision, de-duplicated with a "-2", "-3", ... suffix.
 *
 * `reserved` pre-claims ids nothing in `rawIds` is allowed to take: a
 * generated id this exporter writes verbatim elsewhere in the document (a
 * page id, a link-arc id, a representative node's id, see
 * `exportComposedPnml`), so that a user id which happens to collide with one
 * of them is what moves, not the generated one.
 */
export function buildIdRemap(rawIds: string[], reserved: readonly string[] = []): IdAssignment {
  const used = new Set<string>(reserved);
  const firstFinalIdOf = new Map<string, string>();

  const ids = rawIds.map((id) => {
    const base = isNCName(id) ? id : sanitizeNCName(id);
    let target = base;
    if (used.has(target)) {
      let n = 2;
      let candidate = `${base}-${n}`;
      while (used.has(candidate)) {
        n += 1;
        candidate = `${base}-${n}`;
      }
      target = candidate;
    }
    used.add(target);
    if (!firstFinalIdOf.has(id)) firstFinalIdOf.set(id, target);
    return target;
  });

  return { ids, resolve: (rawId: string) => firstFinalIdOf.get(rawId) ?? rawId };
}

/** Strips a previously-applied `o<digits>_` namespace prefix, so re-export is idempotent (§2). */
function stripNamespacePrefix(id: string): string {
  return id.replace(/^o\d+_/, "");
}

/**
 * Whole-document, all-or-nothing namespacing (§2): if any element id occurs
 * in more than one object, every element id in the document is emitted as
 * `o{objectIndex}_{id}`. Canvas-built models never collide, so this is a
 * safety net for hand-assembled or externally-loaded objects sharing ids.
 *
 * A duplicate id *within* one object is a broken input and fails the export.
 */
function computeNamespacing(objects: ComposedObjectSpec[]): boolean {
  const owners = new Map<string, Set<number>>();

  objects.forEach((obj, index) => {
    const seenInObject = new Set<string>();
    const record = (id: string) => {
      if (seenInObject.has(id)) {
        throw new Error(
          `Cannot export composed PNML: object ${index} ("${obj.name}") has more than one element with id "${id}".`,
        );
      }
      seenInObject.add(id);
      let owner = owners.get(id);
      if (!owner) {
        owner = new Set<number>();
        owners.set(id, owner);
      }
      owner.add(index);
    };
    for (const p of obj.net_data.places) record(p.id);
    for (const t of obj.net_data.transitions) record(t.id);
    for (const a of obj.net_data.arcs) record(a.id);
  });

  for (const owner of owners.values()) {
    if (owner.size > 1) return true;
  }
  return false;
}

/**
 * The id actually written for one element: `rawId`, namespaced with its
 * object index when `computeNamespacing` found a cross-object collision,
 * then run through the document's id-safety remap (built from
 * `composedPreIds`, see there for why looking it up here is enough to
 * cover arc source/target, `ref` attributes and declared-link ids too).
 */
function emitId(remap: IdAssignment, namespaced: boolean, objectIndex: number, rawId: string): string {
  const preId = namespaced ? `o${objectIndex}_${stripNamespacePrefix(rawId)}` : rawId;
  return remap.resolve(preId);
}

/**
 * Every place, transition and arc id of a whole composed document, in one
 * document-order list (after namespacing, so it is exactly the strings
 * `emitId` will otherwise write), which is what `buildIdRemap` needs to
 * build the document's id-safety remap.
 *
 * A single list here is what lets `emitId` stay a plain lookup everywhere
 * else it is called: an arc's source/target reference an existing place's or
 * transition's id, so remapping the place/transition once and resolving that
 * same remap for the arc's endpoints keeps the two attributes consistent by
 * construction, without a separate pass over arcs. A representative node's
 * own id (`ref_object{n}_{targetId}`) and a declared link's
 * `sourceElementId`/`targetElementId` are built by concatenating an already
 * NCName-safe target id with literal, always-safe text, so they inherit
 * safety from this same remap instead of needing one of their own; a page id
 * (`object{n}`) never depends on user data at all, though a user id can
 * still collide with one of those generated strings, which is what the
 * `reserved` ids passed to `buildIdRemap` in `exportComposedPnml` are for.
 */
function composedPreIds(objects: ComposedObjectSpec[], namespaced: boolean): string[] {
  const preIds: string[] = [];
  objects.forEach((obj, i) => {
    const preId = (rawId: string) => (namespaced ? `o${i}_${stripNamespacePrefix(rawId)}` : rawId);
    for (const p of obj.net_data.places) preIds.push(preId(p.id));
    for (const t of obj.net_data.transitions) preIds.push(preId(t.id));
    for (const a of obj.net_data.arcs) preIds.push(preId(a.id));
  });
  return preIds;
}

function pageId(objectIndex: number): string {
  return `object${objectIndex}`;
}

/** Which kind of node a link endpoint addresses, per the §4 projection table. */
function endpointKind(type: ComposedLinkSpec["type"], side: "source" | "target"): "place" | "transition" {
  if (type === "placeFusion") return "place";
  if (type === "transitionToPlace") return side === "source" ? "transition" : "place";
  // placeToTransition
  return side === "source" ? "place" : "transition";
}

function resolveRawElementId(
  objects: ComposedObjectSpec[],
  objectIndex: number,
  elementIndex: number,
  kind: "place" | "transition",
): string {
  const obj = objects[objectIndex];
  if (!obj) {
    throw new Error(`Cannot export composed PNML: link references unknown object ${objectIndex}.`);
  }
  const el = kind === "place" ? obj.net_data.places[elementIndex] : obj.net_data.transitions[elementIndex];
  if (!el) {
    throw new Error(
      `Cannot export composed PNML: link references missing ${kind} ${elementIndex} on object ${objectIndex}.`,
    );
  }
  return el.id;
}

function assertWeight(weight: number, describe: string): number {
  if (weight < 1) {
    throw new Error(`Cannot export composed PNML: ${describe} has weight ${weight}, must be >= 1.`);
  }
  return weight;
}

/** Pads every non-blank line with `pad`, keeping blank lines blank. Returns lines, not a joined string. */
function indent(lines: string[], pad: string): string[] {
  return lines.map((l) => (l.length > 0 ? pad + l : l));
}

function nameBlock(name: string): string[] {
  return ["<name>", `  <text>${escapeXml(name)}</text>`, "</name>"];
}

/**
 * The desktop tool's identity, and the one this app writes for itself.
 *
 * Every reader in this family selects a tool-specific block by its `tool`
 * attribute alone: neither this app's importer nor PetriObjModelPaint's parser
 * ever looks at `version`, which is a statement about the document rather than
 * a filter. That is what makes the readers' CROSS-fallback safe: petri-server's
 * parser prefers its own PetriObjModel block and falls back to PetriNetSim,
 * this app's importer (`pnml-import.ts`) prefers PetriNetSim and falls back to
 * PetriObjModel, and neither filters on version, so a document written by only
 * one tool still opens fully in the other. `TOOL_PETRI_OBJ_MODEL` stays exported
 * here for that reader-side fallback lookup even though this file's own writer
 * no longer emits a block under it.
 */
export const TOOL_PETRI_OBJ_MODEL = "PetriObjModel";
export const TOOL_PETRI_NET_SIM = "PetriNetSim";

/** This app's release, read from its package.json so the two cannot drift. */
export const PETRI_NET_SIM_VERSION = appVersion;

/**
 * One payload, written under this app's own tool identity only. Mirroring
 * PetriObjModelPaint's block here (as this file used to) duplicated a payload
 * the reader-side fallback above already makes unnecessary, and it meant a
 * document said the desktop's release number without the desktop ever having
 * produced it. PetriObjModelPaint's own writer mirrors this: it states only
 * PetriObjModel, from its own pom.xml, and no longer knows this app's version.
 */
function toolspecificBlocks(payload: string[]): string[] {
  return [
    `<toolspecific tool="${TOOL_PETRI_NET_SIM}" version="${PETRI_NET_SIM_VERSION}">`,
    ...indent(payload, "  "),
    "</toolspecific>",
  ];
}

function graphicsBlock(x: number, y: number): string[] {
  return ["<graphics>", `  <position x="${round(x)}" y="${round(y)}"/>`, "</graphics>"];
}

function placeXml(id: string, name: string, tokens: number, x: number, y: number): string {
  const center = placeCenter(x, y);
  const lines: string[] = [`<place id="${escapeXml(id)}">`];
  lines.push(...indent(nameBlock(name), "  "));
  if (tokens > 0) {
    lines.push("  <initialMarking>", `    <text>${tokens}</text>`, "  </initialMarking>");
  }
  // A plain place has nothing left to say in toolspecific once <coordinates>
  // is gone (PNML ISO conformance contract, decision 1): no block at all,
  // the same precedent an INHIBITOR/READ-free arc already sets.
  lines.push(...indent(graphicsBlock(center.x, center.y), "  "));
  lines.push("</place>");
  return lines.join("\n");
}

function transitionXml(id: string, name: string, t: Pick<PetriTransition, "priority" | "distribution" | "mean_delay" | "standard_deviation" | "probability" | "graphics">): string {
  const center = transitionCenter(t.graphics.x, t.graphics.y);
  const lines: string[] = [`<transition id="${escapeXml(id)}">`];
  lines.push(...indent(nameBlock(name), "  "));

  const ts: string[] = [];
  if (t.probability !== null) {
    ts.push(`<probability>${t.probability}</probability>`);
  } else if (t.distribution) {
    ts.push(`<timeDelay>${t.mean_delay}</timeDelay>`);
    ts.push(`<delayMeanValue>${t.mean_delay}</delayMeanValue>`);
    ts.push(`<distribution>${t.distribution}</distribution>`);
    if (t.distribution === "norm" || t.distribution === "unif") {
      ts.push(`<standardDeviation>${t.standard_deviation}</standardDeviation>`);
    }
    ts.push(`<priority>${t.priority}</priority>`);
  } else {
    ts.push("<timeDelay>0</timeDelay>", "<delayMeanValue>0</delayMeanValue>", "<distribution>det</distribution>");
    ts.push(`<priority>${t.priority}</priority>`);
  }
  lines.push(...indent(toolspecificBlocks(ts), "  "));
  lines.push(...indent(graphicsBlock(center.x, center.y), "  "));
  lines.push("</transition>");
  return lines.join("\n");
}

/** An object's own internal arc (§3 "own arcs"); carries `<arcType>` for INHIBITOR/READ, never `<type value="inhibitorArc"/>` (§8.7). */
function ownArcXml(id: string, source: string, target: string, weight: number, arcType: ArcType): string {
  assertWeight(weight, `arc "${id}"`);
  const lines: string[] = [
    `<arc id="${escapeXml(id)}" source="${escapeXml(source)}" target="${escapeXml(target)}">`,
    "  <graphics/>",
    "  <inscription>",
    `    <text>${weight}</text>`,
    "  </inscription>",
  ];
  if (arcType !== "NORMAL") {
    lines.push(
      ...indent(toolspecificBlocks([`<arcType>${arcType.toLowerCase()}</arcType>`]), "  "),
    );
  }
  lines.push("</arc>");
  return lines.join("\n");
}

/**
 * The arc realising a transitionToPlace link (§4), from the source's own
 * transition to the representative node standing for the target place.
 *
 * `informational` is always false here: it is only meaningful for
 * placeToTransition (see `ObjectLinkType`'s own doc comment), and that link
 * type never reaches this function, `exportComposedPnml` refuses a model
 * that has one before any link is resolved. The parameter stays so a caller
 * need not special-case a shape this exporter no longer produces.
 */
function linkArcXml(id: string, source: string, target: string, weight: number, informational: boolean): string {
  assertWeight(weight, `link arc "${id}"`);
  const lines: string[] = [
    `<arc id="${escapeXml(id)}" source="${escapeXml(source)}" target="${escapeXml(target)}">`,
    "  <graphics/>",
    "  <inscription>",
    `    <text>${weight}</text>`,
    "  </inscription>",
  ];
  if (informational) {
    lines.push(...indent(toolspecificBlocks(["<informational>true</informational>"]), "  "));
  }
  lines.push("</arc>");
  return lines.join("\n");
}

/** A `<referencePlace>`/`<referenceTransition>` node (§4, §7): never carries `<initialMarking>` (§8.3). */
function referenceNodeXml(
  tag: "referencePlace" | "referenceTransition",
  id: string,
  ref: string,
  name: string,
  x: number,
  y: number,
  role: "fusion" | "representative",
  fusedMarking: number | undefined,
  /**
   * Why this node is here, said in an XML comment. Not in `<name>`: that name
   * is the user's, and folding provenance into it would rename their element
   * the moment the file is saved and reopened.
   */
  provenance: string,
): string {
  // A reference node's wire position uses the size of the node kind it
  // stands for: a referencePlace is drawn as a place, a referenceTransition
  // as a transition, whatever the represented element's own kind is.
  const center = tag === "referencePlace" ? placeCenter(x, y) : transitionCenter(x, y);
  const lines: string[] = [];
  if (provenance) lines.push(`<!-- ${provenance} -->`);
  lines.push(`<${tag} id="${escapeXml(id)}" ref="${escapeXml(ref)}">`);
  lines.push(...indent(nameBlock(name), "  "));

  const ts: string[] = [`<referenceRole>${role}</referenceRole>`];
  if (fusedMarking != null && fusedMarking > 0) {
    ts.push(`<fusedInitialMarking>${fusedMarking}</fusedInitialMarking>`);
  }
  lines.push(...indent(toolspecificBlocks(ts), "  "));
  lines.push(...indent(graphicsBlock(center.x, center.y), "  "));
  lines.push(`</${tag}>`);
  return lines.join("\n");
}

interface RepresentativeEntry {
  /** This reference node's own id, e.g. `ref_object0_t_end`. */
  id: string;
  targetKind: "place" | "transition";
  targetEmittedId: string;
  name: string;
  x: number;
  y: number;
  /** What this node stands for, for the XML comment above it. */
  standsFor: string;
}

/** Everything needed to render one `<page>`, resolved up front so the template loop below never computes an ordinal. */
interface PageModel {
  index: number;
  spec: ComposedObjectSpec;
  /** `<place>` and fusion `<referencePlace>`, in the object's own place order (§3). */
  placeSlots: string[];
  transitions: string[];
  /** `<referencePlace>`/`<referenceTransition>` for arc-like links, in link order, deduped per target. */
  representatives: string[];
  ownArcs: string[];
  linkArcs: string[];
}

/**
 * Reduce the placeFusion links to one shared place per fusion group.
 *
 * A fusion is an identity: the places of a group are one place, so one member
 * is emitted as a real `<place>` and every other points straight at it. Doing
 * it per group rather than per link is what keeps the document free of chains
 * and cycles by construction, since projecting each link on its own turns
 * `A.p -> B.q, B.q -> C.r` into a reference that points at a reference, and
 * `A.p -> B.q, B.q -> A.p` into a cycle.
 *
 * Which member survives is not a free choice: each link makes its target the
 * survivor, which is what PetriObjModel.wire() does when it assigns
 * `sourcePlaces[source] = <the target's place>`. Mirroring it here keeps the
 * document and the engine agreed on whose initial marking the shared place has.
 *
 * Must stay identical to the backend's `_elect_shared_places`: both writers
 * emit the same document, and a golden fixture in each repo pins that.
 */
function electSharedPlaces(links: ComposedLinkSpec[]): Map<string, [number, number]> {
  const parent = new Map<string, [number, number]>();
  const members: [number, number][] = [];
  const key = (slot: [number, number]) => `${slot[0]}:${slot[1]}`;

  const seen = (slot: [number, number]) => {
    if (parent.has(key(slot))) return;
    parent.set(key(slot), slot);
    members.push(slot);
  };

  const find = (slot: [number, number]): [number, number] => {
    let current = slot;
    for (;;) {
      const next = parent.get(key(current));
      if (!next || key(next) === key(current)) return current;
      current = next;
    }
  };

  for (const link of links) {
    if (link.type !== "placeFusion") continue;
    const source: [number, number] = [link.source_object, link.source_element];
    const target: [number, number] = [link.target_object, link.target_element];
    seen(source);
    seen(target);
    const sourceRoot = find(source);
    const targetRoot = find(target);
    if (key(sourceRoot) !== key(targetRoot)) parent.set(key(sourceRoot), targetRoot);
  }

  const shared = new Map<string, [number, number]>();
  for (const slot of members) {
    const survivor = find(slot);
    if (key(survivor) !== key(slot)) shared.set(key(slot), survivor);
  }
  return shared;
}

/**
 * Resolves a link's target to its final document id, fusion applied. Shared
 * between `buildPages` (the real build) and `reservedGeneratedIds` (which
 * needs the same string before the final remap exists, see
 * `exportComposedPnml`) so the two can never compute a different
 * representative-node id for the same link: computing it in two places is
 * exactly the bug `targetEmittedIdOf`'s own docstring below describes.
 */
function createLinkTargetResolver(
  objects: ComposedObjectSpec[],
  links: ComposedLinkSpec[],
  namespaced: boolean,
  remap: IdAssignment,
) {
  const shared = electSharedPlaces(links);

  /** The document id of the place occupying a given (object, place index). */
  const slotId = (slot: [number, number]) =>
    emitId(remap, namespaced, slot[0], resolveRawElementId(objects, slot[0], slot[1], "place"));

  /**
   * Where a link's target really lives once fusion has been applied: pointing
   * at a place that has itself been fused away would make one reference node
   * refer to another.
   */
  const linkTargetSlot = (link: ComposedLinkSpec): [number, number] | null => {
    if (endpointKind(link.type, "target") !== "place") return null;
    const own: [number, number] = [link.target_object, link.target_element];
    return shared.get(`${own[0]}:${own[1]}`) ?? own;
  };

  /**
   * The document id a link's arc has to end at, fusion applied. Both the
   * representative nodes and the arcs that use them are keyed by it, and they
   * have to agree: computing it in two places let them disagree exactly when
   * the target place had been fused away, since one side followed the fusion
   * and the other did not. The arc then looked for a representative filed
   * under the surviving place's id and found nothing.
   */
  const targetEmittedIdOf = (link: ComposedLinkSpec): string => {
    const survivor = linkTargetSlot(link);
    if (survivor) return slotId(survivor);
    return emitId(
      remap,
      namespaced,
      link.target_object,
      resolveRawElementId(
        objects,
        link.target_object,
        link.target_element,
        endpointKind(link.type, "target"),
      ),
    );
  };

  return { shared, slotId, linkTargetSlot, targetEmittedIdOf };
}

/**
 * Every id `buildPages`/`pageXml`/`linksBlockXml` write that is not taken
 * from the user's own data: one page id per object, one link-arc id per
 * non-fusion link, and one representative-node id per non-fusion link's
 * target (deduping is not needed here, a `Set` built from the returned list
 * absorbs a repeat for free). None of these is ever sanitized, so on their
 * own they would never collide with each other, but a user element can
 * legitimately be named the same as one of them (a place called "object0"),
 * which is otherwise indistinguishable from the generated page id "object0"
 * once both are written. Reserving them in the document's uniqueness domain
 * before the final remap is built (`exportComposedPnml`) is what makes a
 * colliding user id the one that moves instead.
 *
 * `userRemap` is the remap built from user data alone (`composedPreIds`,
 * with nothing reserved yet): a representative's id is built from its
 * target's *own* emitted id, which the reservation pass needs before the
 * final, reservation-aware remap can exist in the first place.
 */
function reservedGeneratedIds(
  objects: ComposedObjectSpec[],
  links: ComposedLinkSpec[],
  namespaced: boolean,
  userRemap: IdAssignment,
): string[] {
  const pageIds = objects.map((_, i) => pageId(i));
  const larcIds = links.map((_, i) => `larc_${i}`);
  const { targetEmittedIdOf } = createLinkTargetResolver(objects, links, namespaced, userRemap);
  const refIds = links
    .filter((link) => link.type !== "placeFusion")
    .map((link) => `ref_${pageId(link.source_object)}_${targetEmittedIdOf(link)}`);
  return [...pageIds, ...larcIds, ...refIds];
}

function buildPages(body: ComposedSimulateBody, namespaced: boolean, remap: IdAssignment): PageModel[] {
  const { objects, links } = body;
  const { shared, slotId, linkTargetSlot, targetEmittedIdOf } = createLinkTargetResolver(
    objects,
    links,
    namespaced,
    remap,
  );

  return objects.map((obj, i) => {
    const placeSlots = obj.net_data.places.map((place, placeIndex) => {
      const survivor = shared.get(`${i}:${placeIndex}`);
      const ownId = emitId(remap, namespaced, i, place.id);
      if (!survivor) {
        return placeXml(ownId, place.name, place.tokens, place.graphics.x, place.graphics.y);
      }
      const survivorId = slotId(survivor);
      return referenceNodeXml(
        "referencePlace",
        ownId,
        survivorId,
        place.name,
        place.graphics.x,
        place.graphics.y,
        "fusion",
        place.tokens > 0 ? place.tokens : undefined,
        `This place is shared with "${survivorId}", which holds the marking for both.`,
      );
    });

    const transitions = obj.net_data.transitions.map((t) =>
      transitionXml(emitId(remap, namespaced, i, t.id), t.name, t),
    );

    // Arc-like (transitionToPlace) links sourced from this object gain a
    // representative reference node standing for the target element (§4), deduped per target
    // so several links to the same remote element share one node.
    const representatives: string[] = [];
    const repByTarget = new Map<string, RepresentativeEntry>();

    links.forEach((link) => {
      if (link.type === "placeFusion" || link.source_object !== i) return;
      const targetKind = endpointKind(link.type, "target");
      const survivor = linkTargetSlot(link);
      const targetEmittedId = targetEmittedIdOf(link);
      const dedupeKey = `${targetKind}:${targetEmittedId}`;
      if (repByTarget.has(dedupeKey)) return;

      const targetObj = objects[survivor ? survivor[0] : link.target_object];
      const targetElement =
        targetKind === "place"
          ? targetObj.net_data.places[survivor ? survivor[1] : link.target_element]
          : targetObj.net_data.transitions[link.target_element];
      const repId = `ref_${pageId(i)}_${targetEmittedId}`;
      const entry: RepresentativeEntry = {
        id: repId,
        targetKind,
        targetEmittedId,
        name: targetElement.name,
        standsFor: `${targetElement.name} in ${targetObj.name}`,
        x: targetElement.graphics.x,
        y: targetElement.graphics.y,
      };
      repByTarget.set(dedupeKey, entry);
      representatives.push(
        referenceNodeXml(
          targetKind === "place" ? "referencePlace" : "referenceTransition",
          entry.id,
          entry.targetEmittedId,
          entry.name,
          entry.x,
          entry.y,
          "representative",
          undefined,
          `Stands for "${entry.standsFor}", so this page can draw an arc to it.`,
        ),
      );
    });

    const ownArcs = obj.net_data.arcs.map((a) =>
      ownArcXml(
        emitId(remap, namespaced, i, a.id),
        emitId(remap, namespaced, i, a.source_id),
        emitId(remap, namespaced, i, a.target_id),
        a.weight,
        a.arc_type,
      ),
    );

    const linkArcs: string[] = [];
    links.forEach((link, linkIndex) => {
      if (link.type === "placeFusion" || link.source_object !== i) return;
      const sourceKind = endpointKind(link.type, "source");
      const sourceRawId = resolveRawElementId(objects, i, link.source_element, sourceKind);
      const sourceEmittedId = emitId(remap, namespaced, i, sourceRawId);

      const targetKind = endpointKind(link.type, "target");
      const targetEmittedId = targetEmittedIdOf(link);
      const representative = repByTarget.get(`${targetKind}:${targetEmittedId}`);
      if (!representative) {
        throw new Error(
          `Cannot export composed PNML: link ${linkIndex} has no representative node for ` +
            `${targetKind} ${targetEmittedId} on object ${i}.`,
        );
      }
      const repId = representative.id;

      linkArcs.push(
        linkArcXml(
          `larc_${linkIndex}`,
          sourceEmittedId,
          repId,
          link.quantity,
          // Always false: informational is only meaningful for placeToTransition,
          // which exportComposedPnml refuses before this loop ever runs.
          false,
        ),
      );
    });

    return { index: i, spec: obj, placeSlots, transitions, representatives, ownArcs, linkArcs };
  });
}

/**
 * The `<petriObject>` marker, following PnmlModelGenerator.createPage exactly:
 * index/name/priority/x/y and a size always; collapsed only when it says
 * something. Anything else the desktop would read as geometry it did not
 * write, and a file saved here has to reopen there unchanged.
 *
 * It does not state a parent. Nesting is what the document's own page
 * structure says, so repeating it here could only be a second answer to a
 * question already answered, and a file must carry nothing about pages that a
 * conformant reader cannot act on.
 *
 * `autoFit="false"` is this app's own extension, on top of that contract: the
 * desktop has no auto-fitting frame and its parser ignores attributes it does
 * not know, so carrying it costs a foreign reader nothing and saves this app a
 * frame the user sized by hand being silently re-fitted on reload.
 *
 * The free-elements bucket is the one page that is not a Petri-object, and the
 * convention that says so is an all-default marker — no geometry at all. The
 * reader (here and in GraphCanvasModel.fromObjModel) recognises it by exactly
 * that, so nothing optional may leak onto it.
 */
function petriObjectXml(page: PageModel): string {
  const spec = page.spec;
  const attrs = [
    `index="${page.index}"`,
    `name="${escapeXml(spec.name)}"`,
    `priority="${spec.priority}"`,
  ];
  if (spec.free) {
    attrs.push('x="0"', 'y="0"');
    return `<petriObject ${attrs.join(" ")}/>`;
  }

  attrs.push(`x="${round(spec.x)}"`, `y="${round(spec.y)}"`);
  // A real object always states a size, even when the canvas has not given it
  // one yet. Without that, a frame sitting at the origin with no size wrote the
  // very marker that means "the free-elements bucket", and reopening the file
  // read the object as that bucket: the frame, and every membership in it, was
  // silently gone. The minimum is the smallest box the canvas will draw, so a
  // frame written this way reopens at the size it would have been given anyway.
  attrs.push(
    `width="${round(Math.max(spec.width ?? 0, FRAME_MIN_W))}"`,
    `height="${round(Math.max(spec.height ?? 0, FRAME_MIN_H))}"`,
  );
  if (spec.collapsed) attrs.push('collapsed="true"');
  if (spec.auto_fit === false) attrs.push('autoFit="false"');
  return `<petriObject ${attrs.join(" ")}/>`;
}

/**
 * One `<page>`, with the pages of the objects nested inside this one written
 * inside it. ISO/IEC 15909-2 expresses a page hierarchy by nesting pages, and
 * that is the only form of it a reader outside this family can see. Children
 * come after the page's own content, in object index order, which is the one
 * position both writers in this family agree on.
 */
function pageXml(page: PageModel, childrenOf: (index: number) => PageModel[]): string {
  const lines: string[] = [`<page id="${pageId(page.index)}">`];
  lines.push(...indent(nameBlock(page.spec.name), "  "));
  lines.push(...indent(toolspecificBlocks([petriObjectXml(page)]), "  "));
  for (const slot of page.placeSlots) lines.push(...indent(slot.split("\n"), "  "));
  for (const t of page.transitions) lines.push(...indent(t.split("\n"), "  "));
  for (const r of page.representatives) lines.push(...indent(r.split("\n"), "  "));
  for (const a of page.ownArcs) lines.push(...indent(a.split("\n"), "  "));
  for (const a of page.linkArcs) lines.push(...indent(a.split("\n"), "  "));
  for (const child of childrenOf(page.index)) {
    lines.push(...indent(pageXml(child, childrenOf).split("\n"), "  "));
  }
  lines.push("</page>");
  return lines.join("\n");
}

/**
 * `<petriObjectLinks>` (§6): still emitted at version 2.1, now with
 * id-valued `sourceElementId`/`targetElementId` alongside the positional
 * indices. Redundant with the structural reference nodes above, kept for
 * a reader that doesn't implement them yet (an un-rebuilt petri-server, a
 * saved-file reader) and as the user's declared intent, addressed by id.
 */
function linksBlockXml(body: ComposedSimulateBody, namespaced: boolean, remap: IdAssignment): string {
  const lines: string[] = ["<petriObjectLinks>"];
  const shared = electSharedPlaces(body.links);

  body.links.forEach((link) => {
    const sourceKind = endpointKind(link.type, "source");
    const targetKind = endpointKind(link.type, "target");
    const sourceId = emitId(
      remap,
      namespaced,
      link.source_object,
      resolveRawElementId(body.objects, link.source_object, link.source_element, sourceKind),
    );

    // The declaration names the target the document's structure names, which
    // is not always the one the link was written with: a target place that has
    // been fused away is declared as the place that survived instead. Declare
    // the original and a reader sees two links where there is one, and delivers
    // its tokens twice.
    const survivor =
      targetKind === "place"
        ? shared.get(`${link.target_object}:${link.target_element}`)
        : undefined;
    const [targetObject, targetElement] = survivor ?? [link.target_object, link.target_element];
    const targetId = emitId(
      remap,
      namespaced,
      targetObject,
      resolveRawElementId(body.objects, targetObject, targetElement, targetKind),
    );

    const attrs = [
      `type="${link.type}"`,
      `sourceObject="${link.source_object}"`,
      `sourceElement="${link.source_element}"`,
      `sourceElementId="${escapeXml(sourceId)}"`,
      `targetObject="${targetObject}"`,
      `targetElement="${targetElement}"`,
      `targetElementId="${escapeXml(targetId)}"`,
    ];
    if (link.type !== "placeFusion") {
      assertWeight(link.quantity, `link ${link.type} (${link.source_object}.${link.source_element} -> ${link.target_object}.${link.target_element})`);
      attrs.push(`quantity="${link.quantity}"`);
    }
    // No `informational` attribute: it is only meaningful for placeToTransition,
    // which exportComposedPnml refuses before this function ever runs.
    lines.push(`  <link ${attrs.join(" ")}/>`);
  });

  lines.push("</petriObjectLinks>");
  return toolspecificBlocks(lines).join("\n");
}

/**
 * Exports a composed model to ISO/IEC 15909-2 conformant, multi-page PNML
 * with standard `<referencePlace>`/`<referenceTransition>` structure (see
 * module docstring). `body` is exactly the request `buildComposedRequest`
 * sends to `/api/v1/simulate/composed`, this function does not re-derive
 * the object/link partition, only serialises it.
 */
export function exportComposedPnml(body: ComposedSimulateBody): string {
  if (body.objects.length === 0) {
    throw new Error("Cannot export composed PNML: model has no objects.");
  }
  body.links.forEach((link, index) => {
    if (link.type === "placeToTransition") {
      // PetriObjModelPaint retired this link type (ComposedModel.validate()
      // on the backend already refuses one for any request that goes through
      // it). This is the exporter's own backstop for a body that reached here
      // some other way: the projection this function used to write for it (a
      // representative reference node plus an informational link arc) is
      // gone, so there is nothing left here that could express one.
      throw new Error(
        `Cannot export composed PNML: link ${index} is a placeToTransition link, which ` +
          "PetriObjModelPaint retired: express the connection as a place fusion with a " +
          "local read arc instead.",
      );
    }
    if (link.source_object === link.target_object) {
      throw new Error(
        `Cannot export composed PNML: link ${index} (${link.type}) connects object ${link.source_object} to itself, which composed PNML cannot express.`,
      );
    }
  });

  const namespaced = computeNamespacing(body.objects);
  const preIds = composedPreIds(body.objects, namespaced);
  // The final remap has to reserve every id this exporter generates itself
  // (page ids, link-arc ids, representative-node ids) so that a colliding
  // user id is the one that gets bumped. But a representative's generated
  // id is itself built from its target's *emitted* id, which only exists
  // once a remap has run over the user's own data. So: remap the user's data
  // once to compute what to reserve, then remap it again, this time with
  // those reservations in place, and use that second remap for the actual
  // document (`reservedGeneratedIds`, `buildIdRemap`).
  const userRemap = buildIdRemap(preIds);
  const reserved = reservedGeneratedIds(body.objects, body.links, namespaced, userRemap);
  const remap = buildIdRemap(preIds, reserved);
  const pages = buildPages(body, namespaced, remap);

  const doc: string[] = [
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
    '<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">',
    '  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">',
    "    <name>",
    `      <text>${escapeXml(body.name)}</text>`,
    "    </name>",
  ];

  // Only the top level goes under <net>; a nested object's page is written
  // inside its parent's. An object whose stated parent is not in this document
  // has nothing to hang from, so it is written at the top level rather than
  // dropped, the same rule the reader applies to a frame with a missing owner.
  const byParent = new Map<number, PageModel[]>();
  for (const page of pages) {
    const parent = page.spec.parent;
    const key = parent != null && parent >= 0 && parent < pages.length ? parent : -1;
    const siblings = byParent.get(key);
    if (siblings) siblings.push(page);
    else byParent.set(key, [page]);
  }
  const childrenOf = (index: number) => byParent.get(index) ?? [];

  for (const page of childrenOf(-1)) {
    doc.push(...indent(pageXml(page, childrenOf).split("\n"), "    "));
  }

  if (body.links.length > 0) {
    doc.push(...indent(linksBlockXml(body, namespaced, remap).split("\n"), "    "));
  }

  doc.push("  </net>", "</pnml>");
  return doc.join("\n");
}
