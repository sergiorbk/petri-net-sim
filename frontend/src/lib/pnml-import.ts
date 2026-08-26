import { XMLParser } from "fast-xml-parser";
import type {
  ArcType,
  DistributionType,
  ObjectFrame,
  ObjectLink,
  ObjectLinkType,
  PetriArc,
  PetriNetData,
  PetriPlace,
  PetriTransition,
} from "@/types/petri";
import { PLACE_H, PLACE_W, TRANS_H, TRANS_W } from "@/lib/petri-geometry";
import {
  TOOL_PETRI_NET_SIM,
  TOOL_PETRI_OBJ_MODEL,
  isNCName,
  sanitizeNCName,
} from "@/lib/pnml-export-composed";
import { FUSION_REJECTION_REASON_TEXT, rejectionForFusion } from "@/lib/petri-object-model";

const parser = new XMLParser({
  ignoreAttributes: false,
  attributeNamePrefix: "@_",
  isArray: (name, jpath) => {
    if (jpath === "pnml.net.toolspecific.petriObjectLinks.link") return true;
    // Everything a net or a page can hold more than one of. The path is matched
    // by its tail rather than in full because pages nest: the standard states a
    // page hierarchy by putting a <page> inside a <page>, so the same child can
    // arrive at pnml.net.page.place or pnml.net.page.page.page.place, and a
    // fixed list of paths would silently hand the deeper ones back as a single
    // object. A lone reference node has to arrive as a list to be walked too.
    const repeatable = [
      "place",
      "transition",
      "arc",
      "page",
      "referencePlace",
      "referenceTransition",
    ];
    if (!repeatable.includes(name)) return false;
    const parent = jpath.slice(0, jpath.length - name.length - 1);
    return parent === "pnml.net" || parent === "pnml.net.page" || parent.startsWith("pnml.net.page.");
  },
});

// ---------------------------------------------------------------------------
// Import warnings: everything this reader is willing to tolerate rather than
// throw over gets a warning instead of vanishing without a trace. Soft
// validation means a file always opens if structurally possible; these are
// the record of what had to be reinterpreted, remapped or dropped to do that.
// ---------------------------------------------------------------------------

export type ImportWarningCode =
  | "invalid-id"
  | "duplicate-id"
  | "dangling-ref"
  | "cross-page-arc"
  | "bad-number"
  | "invalid-value"
  | "rejected-fusion";

export interface ImportWarning {
  code: ImportWarningCode;
  message: string;
}

export interface PnmlImportResult {
  data: PetriNetData;
  warnings: ImportWarning[];
}

/** How many warning messages a summary toast shows before it just counts the rest. */
const SUMMARY_MESSAGE_LIMIT = 3;

/**
 * Formats the toast text for a completed import: a header naming how many
 * warnings there were, the first few messages, and a count of any remainder.
 * Kept here, next to the codes that feed it, so every call site (file picker,
 * drag-and-drop, gallery import) renders the same summary instead of each
 * re-deriving its own truncation rule. Callers are still expected to
 * console.warn the full `warnings` array, since the toast only samples it.
 */
export function summarizeImportWarnings(warnings: ImportWarning[]): string {
  const shown = warnings.slice(0, SUMMARY_MESSAGE_LIMIT).map((w) => w.message);
  const remaining = warnings.length - shown.length;
  const lines = [`PNML imported with ${warnings.length} warnings`, ...shown];
  if (remaining > 0) lines.push(`... and ${remaining} more`);
  return lines.join("\n");
}

function textOf(node: unknown): string {
  if (node == null) return "";
  if (typeof node === "string") return node;
  // The parser types tag values, so <informational>true</informational> arrives
  // as a boolean and a plain string comparison would silently never match.
  if (typeof node === "number" || typeof node === "boolean") return String(node);
  if (typeof node === "object" && "text" in (node as Record<string, unknown>)) {
    return textOf((node as Record<string, unknown>).text);
  }
  if (typeof node === "object" && "#text" in (node as Record<string, unknown>)) {
    return String((node as Record<string, unknown>)["#text"]);
  }
  return "";
}

function numAttr(obj: unknown, attr: string, fallback: number): number {
  if (obj == null || typeof obj !== "object") return fallback;
  const raw = (obj as Record<string, unknown>)[`@_${attr}`];
  if (raw == null) return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

function extractPosition(element: Record<string, unknown>): {
  x: number;
  y: number;
} {
  const graphics = element.graphics as Record<string, unknown> | undefined;
  if (graphics?.position) {
    return {
      x: numAttr(graphics.position, "x", 0),
      y: numAttr(graphics.position, "y", 0),
    };
  }
  const toolspecific = findToolspecific(element);
  if (toolspecific?.coordinates) {
    return {
      x: numAttr(toolspecific.coordinates, "x", 0),
      y: numAttr(toolspecific.coordinates, "y", 0),
    };
  }
  return { x: 0, y: 0 };
}

/**
 * Converts a wire position back to the app model's top-left anchor
 * (graphics.x/y), by subtracting half the node's own size. On the wire (in
 * the PNML file) a node coordinate is the CENTER of the node shape, matching
 * what the exporter now writes into `<graphics><position>`, the only position
 * statement on the wire (PNML ISO conformance contract, decision 1).
 * A referencePlace uses place size, a referenceTransition uses transition
 * size, matching how the exporter picked a size for it.
 *
 * A file this app wrote before it also used center anchoring (version 1.0.0)
 * wrote the position as top-left. Reopening such a file now lands every node
 * half a node's size off from where it was drawn. That is an accepted,
 * one-time visual shift, not a bug: nothing in a 1.0.0 file states which
 * anchor it used, so there is nothing here to detect and special-case.
 */
function extractCenterPosition(
  element: Record<string, unknown>,
  kind: "place" | "transition",
): { x: number; y: number } {
  const wire = extractPosition(element);
  const halfW = (kind === "place" ? PLACE_W : TRANS_W) / 2;
  const halfH = (kind === "place" ? PLACE_H : TRANS_H) / 2;
  return { x: wire.x - halfW, y: wire.y - halfH };
}

/**
 * Recursively searches a parsed PNML fragment for any of the given element
 * names, at any depth. Used to detect composed-model structure, reference
 * nodes and the net-level links block, wherever in the document they land,
 * without building a full multi-page parser (see guardAgainstComposedPnml).
 */
function containsElementDeep(node: unknown, names: readonly string[]): boolean {
  if (node == null || typeof node !== "object") return false;
  if (Array.isArray(node)) return node.some((n) => containsElementDeep(n, names));
  const obj = node as Record<string, unknown>;
  if (names.some((n) => n in obj)) return true;
  return Object.values(obj).some((v) => containsElementDeep(v, names));
}

/** True when the document says anything a single flat page cannot. */
function isComposedDocument(net: Record<string, unknown>): boolean {
  const pages = net.page == null ? [] : Array.isArray(net.page) ? net.page : [net.page];
  return (
    pages.length > 1
    // A petriObject marker is composed structure even alone on a single
    // page: it is exactly how a one-object canvas is written, and the
    // desktop parser likewise reads the marker wherever it appears.
    || containsElementDeep(net, [
      "referencePlace",
      "referenceTransition",
      "petriObjectLinks",
      "petriObject",
    ])
  );
}

function asArray(value: unknown): Record<string, unknown>[] {
  if (value == null) return [];
  return (Array.isArray(value) ? value : [value]) as Record<string, unknown>[];
}

function toolspecificValue(
  element: Record<string, unknown>,
  key: string,
): unknown {
  const ts = findToolspecific(element);
  return ts ? ts[key] : undefined;
}

/** The `<petriObject>` marker of a page, or an empty record when the page carries none. */
function petriObjectMarker(page: Record<string, unknown>): Record<string, unknown> {
  return (findToolspecific(page)?.petriObject ?? {}) as Record<string, unknown>;
}

/**
 * Every page of the document, nested ones included, and the page each one sits
 * in.
 *
 * ISO/IEC 15909-2 states a page hierarchy by putting a `<page>` inside a
 * `<page>`, which is how both tools in this family now write the nest between
 * Petri-objects. Taking only the direct children of `<net>` would read such a
 * document as a single top-level object and lose everything under it.
 */
function collectPages(net: Record<string, unknown>): {
  pages: Record<string, unknown>[];
  enclosing: Map<Record<string, unknown>, Record<string, unknown>>;
} {
  const pages: Record<string, unknown>[] = [];
  const enclosing = new Map<Record<string, unknown>, Record<string, unknown>>();

  const walk = (node: Record<string, unknown>, parent: Record<string, unknown> | null) => {
    for (const page of asArray(node.page)) {
      pages.push(page);
      if (parent) enclosing.set(page, parent);
      walk(page, page);
    }
  };
  walk(net, null);

  return { pages, enclosing };
}

/**
 * Pages in the order their `<petriObject index="...">` attributes state.
 *
 * Document order is not that order once pages nest: a child of object 0 is
 * written before a second top-level object, so pre-order reads 0, 2, 1. Links
 * address objects by the stated index, so falling back to document order would
 * quietly re-bind every one of them to a different object. A flat document
 * predates all of that and keeps the old, harmless fallback.
 */
function orderPagesByIndex(
  pages: Record<string, unknown>[],
  nested: boolean,
): Record<string, unknown>[] {
  const byIndex = new Map<number, Record<string, unknown>>();
  for (const page of pages) {
    const index = numAttr(petriObjectMarker(page), "index", -1);
    if (!Number.isInteger(index) || index < 0 || index >= pages.length || byIndex.has(index)) {
      if (nested) {
        throw new Error(
          "Invalid PNML: this document nests its pages, so every page must state a unique " +
            "<petriObject index> in 0.." + (pages.length - 1) + "; page order cannot be guessed " +
            "from the document, and the links address objects by that index.",
        );
      }
      return pages;
    }
    byIndex.set(index, page);
  }
  return pages.map((_, i) => byIndex.get(i)!);
}

/**
 * What a reference node means, which the document only sometimes says outright.
 *
 * A document this app or the desktop wrote states the role. A foreign one does
 * not, and then the arcs give it away: a reference node its own page never
 * draws an arc to is there only to be shared with the page that owns it, which
 * is a fusion; one an arc touches is a stand-in for that arc's far endpoint.
 * Mirrors ReferenceNodeIndex.isFusion. Raw-to-raw on purpose: this only
 * classifies the node, which never becomes part of the model, so it never
 * needs to agree with the id-safety remap below.
 */
function isFusionReference(
  raw: Record<string, unknown>,
  touchedByArcs: Set<string>,
): boolean {
  const role = textOf(toolspecificValue(raw, "referenceRole"));
  if (role) return role.toLowerCase() === "fusion";
  return !touchedByArcs.has(String(raw["@_id"] ?? ""));
}

/** One place, transition or reference node of the document, with where it sits. */
interface DocumentNode {
  id: string;
  page: number;
  placeKind: boolean;
  reference: boolean;
  fusion: boolean;
  /** What a reference node points at (the document's raw `ref` string); empty for a real element. */
  ref: string;
  /** The element's own visible name, or its id when it has none. */
  name: string;
}

/** A link before it has been given an id, which only the merged list can hand out. */
type DraftLink = Omit<ObjectLink, "id">;

/** What makes two links the same link, ignoring their annotations. */
function endpointKey(link: DraftLink): string {
  return `${link.type}:${link.sourceId}:${link.targetId}`;
}

// ---------------------------------------------------------------------------
// Id safety net (PNML ISO conformance contract, decision 2): export always
// writes NCName-safe ids; import accepts whatever a document actually says,
// remaps anything that is not a valid, unique NCName, rewrites every
// reference to it, and reports one warning per replacement. A file always
// opens if structurally possible.
// ---------------------------------------------------------------------------

/** Names an already-resolved element in a warning message, by its visible name when there is one, by its id otherwise. */
function describe(kind: string, id: string, name: string): string {
  return name && name !== id ? `${kind} "${name}" (id "${id}")` : `${kind} id "${id}"`;
}

interface ParseCtx {
  registry: {
    /**
     * Assigns the final, NCName-safe, document-unique id for one element
     * occurrence, in registration order. Passing the element's own raw XML
     * node as `raw` caches the result under that node's identity: a second
     * call for the very same node (same object reference) returns the cached
     * id unchanged instead of registering a second occurrence. That is what
     * lets a two-pass reader register every element up front, in one pass,
     * and then parse each element in a second pass using the ordinary
     * parse-time call, without assigning (or warning about) the same element
     * twice.
     */
    assign(kind: string, rawId: string, visibleName: string, raw?: object): string;
    /** The id an arc source/target, a `ref` attribute or a declared link should use for a raw id, if that raw id was ever assigned one. */
    resolve(rawId: string): string | undefined;
  };
  warn(code: ImportWarningCode, message: string): void;
}

/**
 * One id-safety pass shared by the whole document: every place, transition,
 * arc, reference node and object-frame page gets exactly one call to
 * `assign`, in the order it is parsed, which is what "first occurrence"
 * means here. A raw id that is already a valid, unclaimed NCName keeps
 * itself; otherwise it is sanitised (sanitizeNCName, shared with the
 * exporter in pnml-export-composed.ts) and, if that still collides with
 * something already claimed (including a genuine duplicate, the same raw id
 * used by two different elements) given a "-2", "-3", ... suffix.
 *
 * `resolve` answers what an arc's source/target, a reference node's `ref`,
 * or a declared link's sourceElementId/targetElementId should now point at:
 * always the id assigned to the FIRST element that ever carried that raw id,
 * so every reference to a duplicated id keeps landing on the one element the
 * document meant (the same behaviour this reader already had for duplicates,
 * now explicit and no longer silently duplicating the element itself too).
 */
function createParseContext(): { ctx: ParseCtx; warnings: ImportWarning[] } {
  const warnings: ImportWarning[] = [];
  const warn = (code: ImportWarningCode, message: string) => warnings.push({ code, message });

  const used = new Set<string>();
  const firstFinalIdOf = new Map<string, string>();
  // Keyed by the raw XML node's own object identity, not by its id text: two
  // different elements can carry the same raw id (that is exactly what
  // "duplicate-id" means), so only the node itself, not its id, can say
  // whether this is a repeat call for an element already registered.
  const idByNode = new WeakMap<object, string>();

  const label = (kind: string, rawId: string, visibleName: string): string =>
    visibleName ? `${kind} "${visibleName}" (id "${rawId}")` : `${kind} id "${rawId}"`;

  const assign = (kind: string, rawId: string, visibleName: string, raw?: object): string => {
    if (raw) {
      const cached = idByNode.get(raw);
      if (cached != null) return cached;
    }

    const invalid = !isNCName(rawId);
    const base = invalid ? sanitizeNCName(rawId) : rawId;
    let target = base;
    let duplicate = false;
    if (used.has(target)) {
      duplicate = true;
      let n = 2;
      let candidate = `${base}-${n}`;
      while (used.has(candidate)) {
        n += 1;
        candidate = `${base}-${n}`;
      }
      target = candidate;
    }
    used.add(target);
    if (!firstFinalIdOf.has(rawId)) firstFinalIdOf.set(rawId, target);

    if (duplicate) {
      warn(
        "duplicate-id",
        `${label(kind, rawId, visibleName)} duplicates an id already used elsewhere in the document; imported as "${target}".`,
      );
    } else if (invalid) {
      warn("invalid-id", `${label(kind, rawId, visibleName)} is not a valid XML id; imported as "${target}".`);
    }
    if (raw) idByNode.set(raw, target);
    return target;
  };

  const resolve = (rawId: string): string | undefined => firstFinalIdOf.get(rawId);

  return { ctx: { registry: { assign, resolve }, warn }, warnings };
}

/**
 * Reads a composed (Petri-object) document back into the canvas shape.
 *
 * The document and the canvas hold the same model in different terms, so this
 * undoes exactly what the exporter did. One page becomes one object frame,
 * unless its `<petriObject>` marker records no geometry at all — that is the
 * bucket of elements belonging to no object, and drawing a frame around it
 * would invent a Petri-object the document does not contain (the same
 * all-zero heuristic as GraphCanvasModel.fromObjModel). A `<referencePlace>`
 * standing in for a fused-away place becomes that place again, with the
 * marking the exporter parked in `<fusedInitialMarking>`, because the canvas
 * draws both members of a fusion and the document only draws one.
 *
 * Where the links come from is decided by structure, never by a version
 * attribute a writer may stamp for any reason (PnmlModelParser):
 *
 * - **Conformant**, at least one reference node. The reference nodes are the
 *   authority, because they are the only part of the composition a reader that
 *   is not this tool can see. The declared `<petriObjectLinks>` block is still
 *   read, but only for what the structure cannot state.
 * - **Legacy**, no reference nodes. The declaration is the only source, exactly
 *   as it always was — a reader that only understood the new shape would be a
 *   data-loss bug for every file saved so far.
 */
function parseComposedPnml(
  net: Record<string, unknown>,
  name: string,
  ctx: ParseCtx,
): PetriNetData {
  const { pages: allPages, enclosing } = collectPages(net);
  // Which object is inside which is the page structure, and only that. The
  // older tool-specific parentObject attribute is neither written nor read any
  // more: a document states its hierarchy the way ISO/IEC 15909-2 states one or
  // it states none. A file exported before that carries the attribute alone, so
  // it opens with its objects at the top level, which is what it now literally
  // says.
  const pages = orderPagesByIndex(allPages, enclosing.size > 0);
  const conformant = containsElementDeep(net, ["referencePlace", "referenceTransition"]);

  const objects: ObjectFrame[] = [];
  const places: PetriPlace[] = [];
  const transitions: PetriTransition[] = [];

  /** Per page, the ids of its place slots and transitions, in document order. */
  const placeIdsByPage: string[][] = [];
  const transitionIdsByPage: string[][] = [];
  /** Per page, the frame it produced, or null for the free-elements bucket. */
  const frameByPage: (ObjectFrame | null)[] = [];
  /** Per page, the page index its marker named as its parent, when it named one. */
  const parentIndexByPage: (number | null)[] = [];
  /** Reference nodes that only carry a link arc; those arcs are links, not arcs. */
  const representatives = new Set<string>();
  /** Every place, transition and reference node of the document, by its final id. */
  const nodes = new Map<string, DocumentNode>();
  /** Per page, its reference nodes in document order, for the structural pass. */
  const referenceNodesByPage: DocumentNode[][] = [];
  /** Per page, its own arcs, parsed exactly once so a later pass never re-parses (and re-warns about) the same arc. */
  const arcsByPage: PetriArc[][] = [];

  // Pass 1: register every id-bearing element of every page, across the whole
  // document, before parsing touches any of them. An arc's source/target has
  // to resolve against the *completed* registry: it can sit on an earlier
  // page than the element it names (the standard's same-page rule is a rule a
  // document can violate, not a guarantee this reader gets to lean on), and
  // until every page has registered its ids, that reference cannot yet know
  // the id its target will end up with. Registering page by page, interleaved
  // with resolving that same page's arcs (as a single combined pass would),
  // is exactly what left a forward reference unresolved.
  pages.forEach((page, index) => {
    const marker = petriObjectMarker(page);
    const geometry = {
      x: numAttr(marker, "x", 0),
      y: numAttr(marker, "y", 0),
      width: numAttr(marker, "width", 0),
      height: numAttr(marker, "height", 0),
    };
    const free =
      geometry.x === 0 && geometry.y === 0 && geometry.width === 0 && geometry.height === 0;
    if (!free) {
      const rawFrameId = String(page["@_id"] ?? `object${index}`);
      const markerName = String(marker["@_name"] ?? "");
      const visibleName = markerName || textOf(page.name);
      ctx.registry.assign("Page", rawFrameId, visibleName, page);
    }
    for (const raw of asArray(page.place)) {
      ctx.registry.assign("Place", String(raw["@_id"] ?? ""), textOf(raw.name), raw);
    }
    for (const raw of asArray(page.referencePlace)) {
      ctx.registry.assign("Reference place", String(raw["@_id"] ?? ""), textOf(raw.name), raw);
    }
    for (const raw of asArray(page.referenceTransition)) {
      ctx.registry.assign("Reference transition", String(raw["@_id"] ?? ""), textOf(raw.name), raw);
    }
    for (const raw of asArray(page.transition)) {
      ctx.registry.assign("Transition", String(raw["@_id"] ?? ""), textOf(raw.name), raw);
    }
    for (const raw of asArray(page.arc)) {
      ctx.registry.assign("Arc", String(raw["@_id"] ?? ""), "", raw);
    }
  });

  // Pass 2: parse every page for real. Every `ctx.registry.assign` call below
  // passes the same raw node pass 1 already registered it under, so each one
  // is a cache hit that returns the id already assigned rather than
  // registering (and re-warning about) the element a second time; `resolve`
  // now always sees the whole document, forward references included.
  pages.forEach((page, index) => {
    const marker = petriObjectMarker(page);
    const geometry = {
      x: numAttr(marker, "x", 0),
      y: numAttr(marker, "y", 0),
      width: numAttr(marker, "width", 0),
      height: numAttr(marker, "height", 0),
    };
    // A real frame always has a size, so its geometry is never all-zero; a page
    // that records none is either this app's free-elements bucket or a document
    // that never described objects in the first place.
    const free =
      geometry.x === 0 && geometry.y === 0 && geometry.width === 0 && geometry.height === 0;

    let frame: ObjectFrame | null = null;
    if (!free) {
      const rawFrameId = String(page["@_id"] ?? `object${index}`);
      const markerName = String(marker["@_name"] ?? "");
      const visibleName = markerName || textOf(page.name);
      const frameId = ctx.registry.assign("Page", rawFrameId, visibleName, page);
      frame = {
        id: frameId,
        name: visibleName || `Object ${index + 1}`,
        priority: numAttr(marker, "priority", 0),
        graphics: geometry,
      };
      if (String(marker["@_collapsed"] ?? "") === "true") frame.collapsed = true;
      // Written only by this app; the desktop ignores the attribute silently.
      if (String(marker["@_autoFit"] ?? "") === "false") frame.autoFit = false;
      objects.push(frame);
    }
    frameByPage.push(frame);
    const enclosingPage = enclosing.get(page);
    const nested = enclosingPage
      ? numAttr(petriObjectMarker(enclosingPage), "index", -1)
      : -1;
    parentIndexByPage.push(nested >= 0 ? nested : null);

    const touchedByArcs = new Set<string>();
    for (const raw of asArray(page.arc)) {
      touchedByArcs.add(String(raw["@_source"] ?? ""));
      touchedByArcs.add(String(raw["@_target"] ?? ""));
    }

    const pageReferenceNodes: DocumentNode[] = [];
    const register = (node: DocumentNode) => {
      if (!nodes.has(node.id)) nodes.set(node.id, node);
    };

    const pagePlaceIds: string[] = [];
    for (const raw of asArray(page.place)) {
      const place = parsePlace(raw, ctx);
      if (frame) place.objectId = frame.id;
      places.push(place);
      pagePlaceIds.push(place.id);
      register({ id: place.id, page: index, placeKind: true, reference: false, fusion: false, ref: "", name: place.name });
    }
    for (const raw of asArray(page.referencePlace)) {
      const rawId = String(raw["@_id"] ?? "");
      const visibleName = textOf(raw.name);
      const id = ctx.registry.assign("Reference place", rawId, visibleName, raw);
      const node: DocumentNode = {
        id,
        page: index,
        placeKind: true,
        reference: true,
        fusion: isFusionReference(raw, touchedByArcs),
        ref: String(raw["@_ref"] ?? ""),
        name: visibleName || id,
      };
      register(node);
      pageReferenceNodes.push(node);
      if (!node.fusion) {
        representatives.add(id);
        continue;
      }
      // The same XML element is both the reference node above and, here, the
      // real place it stands in for; it gets one id, assigned once, above.
      const restored = parsePlace(raw, ctx, id);
      if (frame) restored.objectId = frame.id;
      const fusedMarkingText = textOf(toolspecificValue(raw, "fusedInitialMarking"));
      if (fusedMarkingText !== "") {
        const fusedTokens = Number(fusedMarkingText);
        if (Number.isFinite(fusedTokens)) {
          restored.tokens = fusedTokens;
        } else {
          // Malformed, not merely absent: keep the marking parsePlace already
          // validated (its own <initialMarking>, or the 0 default) rather
          // than letting a NaN through silently.
          ctx.warn(
            "bad-number",
            `${describe("Place", restored.id, restored.name)} has a malformed fused initial marking ` +
              `"${fusedMarkingText}"; imported with ${restored.tokens} tokens.`,
          );
        }
      }
      places.push(restored);
      pagePlaceIds.push(restored.id);
    }
    // There is no transition-fusion link, so a reference transition can only
    // ever be a stand-in; inferring a role for it would produce a nonsense link.
    for (const raw of asArray(page.referenceTransition)) {
      const rawId = String(raw["@_id"] ?? "");
      const visibleName = textOf(raw.name);
      const id = ctx.registry.assign("Reference transition", rawId, visibleName, raw);
      const node: DocumentNode = {
        id,
        page: index,
        placeKind: false,
        reference: true,
        fusion: false,
        ref: String(raw["@_ref"] ?? ""),
        name: visibleName || id,
      };
      register(node);
      pageReferenceNodes.push(node);
      representatives.add(id);
    }

    const pageTransitionIds: string[] = [];
    for (const raw of asArray(page.transition)) {
      const transition = parseTransition(raw, ctx);
      if (frame) transition.objectId = frame.id;
      transitions.push(transition);
      pageTransitionIds.push(transition.id);
      register({ id: transition.id, page: index, placeKind: false, reference: false, fusion: false, ref: "", name: transition.name });
    }

    // Parsed once, up front: whether an arc ends up a model arc, a link's own
    // realisation, or a warning-and-drop is decided below, once every page's
    // nodes and reference chains are known; re-parsing it there would also
    // re-run (and re-warn about) its inscription.
    arcsByPage.push(asArray(page.arc).map((raw) => parseArc(raw, ctx)));

    placeIdsByPage.push(pagePlaceIds);
    transitionIdsByPage.push(pageTransitionIds);
    referenceNodesByPage.push(pageReferenceNodes);
  });

  restoreNesting(objects, frameByPage, parentIndexByPage);

  const structural = conformant
    ? structuralLinks(pages, referenceNodesByPage, arcsByPage, nodes, ctx)
    : { links: [] as DraftLink[], linkedArcIds: new Set<string>() };

  // Every arc is already parsed above; this decides its fate now that
  // linkedArcIds (the arcs a structural link actually realises) is known: an
  // arc that realises a link vanishes on purpose; one that touches a
  // representative whose reference chain never resolved vanishes too, but
  // with a warning naming it (today it vanished silently); anything else is a
  // model arc, possibly one that quietly crosses a page boundary no
  // reference node accounts for, which is also worth a warning rather than
  // silent acceptance.
  const arcs: PetriArc[] = [];
  pages.forEach((_page, index) => {
    for (const arc of arcsByPage[index]) {
      if (structural.linkedArcIds.has(arc.id)) continue;
      if (representatives.has(arc.source_id) || representatives.has(arc.target_id)) {
        ctx.warn(
          "dangling-ref",
          `${describe("Arc", arc.id, "")} touches an unresolved reference node and was skipped.`,
        );
        continue;
      }
      const sourcePage = nodes.get(arc.source_id)?.page;
      const targetPage = nodes.get(arc.target_id)?.page;
      if (sourcePage != null && targetPage != null && sourcePage !== targetPage) {
        ctx.warn(
          "cross-page-arc",
          `${describe("Arc", arc.id, "")} connects elements on different pages, which the ` +
            "PNML same-page rule for arcs forbids; imported anyway.",
        );
      }
      arcs.push(arc);
    }
  });

  const declared = declaredLinks(net, placeIdsByPage, transitionIdsByPage, ctx);

  const merged = mergeLinks(structural.links, declared, conformant);
  const validated = dropInvalidFusions(merged, places, transitions, objects, nodes, ctx);
  const links: ObjectLink[] = validated.map((draft, index) => ({ id: `link_${index}`, ...draft }));

  return { name, places, transitions, arcs, objects, links };
}

/**
 * Restores the nest the page structure states, once every page has had its
 * chance to produce a frame: a page may enclose one whose frame is built later.
 *
 * A value that names no frame (out of range, or a free-elements page), or the
 * frame itself, leaves the frame top-level rather than failing the import. So
 * does a chain that loops: a cycle is not a tree, and the canvas draws trees.
 */
function restoreNesting(
  objects: ObjectFrame[],
  frameByPage: (ObjectFrame | null)[],
  parentIndexByPage: (number | null)[],
): void {
  frameByPage.forEach((frame, index) => {
    const parentIndex = parentIndexByPage[index];
    if (!frame || parentIndex == null) return;
    const parent = frameByPage[parentIndex];
    if (!parent || parent === frame) return;
    frame.objectId = parent.id;
  });

  const byId = new Map(objects.map((o) => [o.id, o]));
  for (const frame of objects) {
    let current = byId.get(frame.objectId ?? "");
    for (let depth = 0; current && depth <= objects.length; depth++) {
      if (current.id === frame.id) {
        delete frame.objectId;
        break;
      }
      current = byId.get(current.objectId ?? "");
    }
  }
}

/**
 * The links the document's structure states — the complete set of them, since
 * a reader that does not know this tool sees exactly these and nothing else.
 * Mirrors ReferenceNodeIndex, addressing endpoints by id rather than by the
 * (page, ordinal) pair the Java model counts in.
 *
 * Also reports which of the page's own arcs realise a link (`linkedArcIds`):
 * the caller uses that to tell "this arc is the link's own wire, and vanishes
 * on purpose" apart from "this arc touches a representative that never
 * resolved, and vanishes as data loss that deserves a warning".
 */
function structuralLinks(
  pages: Record<string, unknown>[],
  referenceNodesByPage: DocumentNode[][],
  arcsByPage: PetriArc[][],
  nodes: Map<string, DocumentNode>,
  ctx: ParseCtx,
): { links: DraftLink[]; linkedArcIds: Set<string> } {
  /** Follows a ref through however many reference nodes stand in the way. */
  const resolve = (start: DocumentNode): DocumentNode | null => {
    let current: DocumentNode | undefined = start;
    const visited = new Set<string>();
    while (current?.reference) {
      if (visited.has(current.id)) return null;
      visited.add(current.id);
      const targetId = ctx.registry.resolve(current.ref) ?? current.ref;
      current = nodes.get(targetId);
    }
    return current ?? null;
  };

  const links: DraftLink[] = [];
  const linkedArcIds = new Set<string>();

  pages.forEach((page, index) => {
    const pageArcsRaw = asArray(page.arc);
    const pageArcsParsed = arcsByPage[index];
    /** Arcs already read as a link, so an arc between two representatives is read once. */
    const claimed = new Set<string>();

    for (const node of referenceNodesByPage[index]) {
      const target = resolve(node);
      if (!target) {
        ctx.warn(
          "dangling-ref",
          `Reference node "${node.name}" points to missing id "${node.ref}"; the link it stands for was skipped.`,
        );
        continue;
      }

      if (node.fusion) {
        // A fusion says this object's slot *is* the other object's place.
        if (!target.placeKind) continue;
        links.push({ type: "placeFusion", sourceId: node.id, targetId: target.id, quantity: 1 });
        continue;
      }

      // A representative carries its links on its arcs: every arc of the page
      // that touches it crosses an object boundary.
      for (let j = 0; j < pageArcsRaw.length; j++) {
        const raw = pageArcsRaw[j];
        const arc = pageArcsParsed[j];
        const outgoing = arc.source_id === node.id;
        if (!outgoing && arc.target_id !== node.id) continue;
        // Already accounted for: an arc between two representatives has no
        // endpoint in this object at all and cannot say which objects it links.
        if (claimed.has(arc.id)) continue;
        claimed.add(arc.id);

        const other = nodes.get(outgoing ? arc.target_id : arc.source_id);
        const otherIsSlot = other != null && (!other.reference || other.fusion);
        if (!other || !otherIsSlot || other.page !== index || other.placeKind === node.placeKind) {
          continue;
        }

        // The standard lets a document omit the inscription even though both
        // writers always emit it.
        const quantity = Math.max(1, arc.weight);
        // An arc that tests a marking without consuming it has no P/T-net form
        // at all, so the flag only exists in the arc's tool-specific block.
        const informational = textOf(toolspecificValue(raw, "informational")) === "true";
        linkedArcIds.add(arc.id);

        if (node.placeKind) {
          // The stand-in is a place of another object.
          links.push(
            outgoing
              ? { type: "placeToTransition", sourceId: target.id, targetId: other.id, quantity, informational }
              : { type: "transitionToPlace", sourceId: other.id, targetId: target.id, quantity, informational },
          );
        } else {
          // The stand-in is a transition of another object.
          links.push(
            outgoing
              ? { type: "transitionToPlace", sourceId: target.id, targetId: other.id, quantity, informational }
              : { type: "placeToTransition", sourceId: other.id, targetId: target.id, quantity, informational },
          );
        }
      }
    }
  });

  return { links, linkedArcIds };
}

/** The net-level `<petriObjectLinks>` declaration, resolved to element ids. */
/** Which endpoint kind a link type requires on each side. */
function endpointKind(type: ObjectLinkType, side: "source" | "target"): "place" | "transition" {
  if (type === "placeFusion") return "place";
  if (type === "transitionToPlace") return side === "source" ? "transition" : "place";
  return side === "source" ? "place" : "transition"; // placeToTransition
}

function declaredLinks(
  net: Record<string, unknown>,
  placeIdsByPage: string[][],
  transitionIdsByPage: string[][],
  ctx: ParseCtx,
): DraftLink[] {
  const places = new Set(placeIdsByPage.flat());
  const transitions = new Set(transitionIdsByPage.flat());
  const kindOf = (id: string): "place" | "transition" | null =>
    places.has(id) ? "place" : transitions.has(id) ? "transition" : null;

  const raws = asArray(
    (findToolspecific(net)?.petriObjectLinks as Record<string, unknown> | undefined)?.link,
  );

  const links: DraftLink[] = [];
  for (const raw of raws) {
    const type = String(raw["@_type"] ?? "") as ObjectLinkType;
    const sourceObject = Number(raw["@_sourceObject"] ?? -1);
    const targetObject = Number(raw["@_targetObject"] ?? -1);
    const sourceElement = Number(raw["@_sourceElement"] ?? -1);
    const targetElement = Number(raw["@_targetElement"] ?? -1);

    // The id-valued attributes are authoritative when present: they survive a
    // page whose slot order this reader and the writer might count differently.
    const hasSourceId = raw["@_sourceElementId"] != null;
    const hasTargetId = raw["@_targetElementId"] != null;
    const rawSourceId = hasSourceId
      ? String(raw["@_sourceElementId"])
      : (type === "transitionToPlace" ? transitionIdsByPage : placeIdsByPage)
        [sourceObject]?.[sourceElement];
    const rawTargetId = hasTargetId
      ? String(raw["@_targetElementId"])
      : (type === "placeToTransition" ? transitionIdsByPage : placeIdsByPage)
        [targetObject]?.[targetElement];
    if (!rawSourceId || !rawTargetId) continue;

    // The id-valued attributes carry the document's original spelling and
    // need the same remap every other reference goes through; the positional
    // fallback already names an id assigned above, so it needs none.
    const sourceId = hasSourceId ? (ctx.registry.resolve(rawSourceId) ?? rawSourceId) : rawSourceId;
    const targetId = hasTargetId ? (ctx.registry.resolve(rawTargetId) ?? rawTargetId) : rawTargetId;

    // A declaration whose endpoint is not the kind its type requires does not
    // describe a link this model can hold: placeFusion joins two places,
    // transitionToPlace runs from a transition to a place. Keeping it produced
    // a link that indexed one object's places with a position taken from its
    // transitions, which the writer then could not resolve at all. The rest of
    // the document still opens, and the structural reference nodes, which are
    // the authoritative source, usually state the same link correctly.
    if (
      kindOf(sourceId) !== endpointKind(type, "source") ||
      kindOf(targetId) !== endpointKind(type, "target")
    ) {
      continue;
    }

    const quantity = Number(raw["@_quantity"] ?? 1);
    links.push({
      type,
      sourceId,
      targetId,
      quantity: Number.isFinite(quantity) ? quantity : 1,
      informational: String(raw["@_informational"] ?? "false") === "true",
    });
  }
  return links;
}

/**
 * Settles what the model's links are when both sources speak, following
 * PnmlModelParser.mergeDeclaredLinks:
 *
 * - **Fusions**: the reference nodes are the complete set and every declared
 *   fusion is dropped. Fusion is destructive and not idempotent — replaying a
 *   declaration over an already-fused model chains it further rather than
 *   reproducing it — so it gets exactly one source of truth.
 * - **Arc-like links**: the union, keyed on endpoints. Where the two disagree
 *   on multiplicity or on the informational flag the structure wins, because
 *   that is what every other reader of the document sees. A declaration the
 *   structure does not state is kept: that is how a legacy-style declaration
 *   inside a conformant document survives.
 */
function mergeLinks(
  structural: DraftLink[],
  declared: DraftLink[],
  conformant: boolean,
): DraftLink[] {
  if (!conformant) return declared;

  const merged = [...structural];
  const seen = new Set(structural.map(endpointKey));
  for (const link of declared) {
    if (link.type === "placeFusion") continue;
    const key = endpointKey(link);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(link);
  }
  return merged;
}

/**
 * A document is held to the same five rules the editor gesture is
 * (rejectionForFusion, petri-object-model.ts): a fusion link a hand-written
 * or foreign-tool file declares can carry a cycle, a copy repeating two
 * masters, or a pair linked both ways round, none of which the canvas could
 * ever have produced itself. Checked in document order, accumulating the
 * accepted links as it goes, so of a contradictory set the first one stated
 * is the one that stands, the one that would already have taken effect by
 * the time a later, conflicting one was declared. Non-fusion links pass
 * through untouched: only placeFusion has rules to fail.
 */
function dropInvalidFusions(
  draftLinks: DraftLink[],
  places: PetriPlace[],
  transitions: PetriTransition[],
  objects: ObjectFrame[],
  nodes: Map<string, DocumentNode>,
  ctx: ParseCtx,
): DraftLink[] {
  const accepted: DraftLink[] = [];
  for (const link of draftLinks) {
    if (link.type !== "placeFusion") {
      accepted.push(link);
      continue;
    }
    // rejectionForFusion never looks at a link's id, only its type/endpoints;
    // these placeholders exist purely to satisfy PetriNetData's shape.
    const netSoFar: PetriNetData = {
      name: "",
      places,
      transitions,
      arcs: [],
      objects,
      links: accepted.map((l, i) => ({ id: `v${i}`, ...l })),
    };
    const reason = rejectionForFusion(netSoFar, link.sourceId, link.targetId);
    if (reason) {
      const master = nodes.get(link.targetId);
      const joined = nodes.get(link.sourceId);
      ctx.warn(
        "rejected-fusion",
        `Dropped the link ${describe("Place", link.targetId, master?.name ?? link.targetId)} = ` +
          `${describe("Place", link.sourceId, joined?.name ?? link.sourceId)}: ${FUSION_REJECTION_REASON_TEXT[reason]}.`,
      );
      continue;
    }
    accepted.push(link);
  }
  return accepted;
}

/**
 * The tool-specific block to read, out of however many an element carries.
 *
 * Each tool in this family writes only its own block: this app writes
 * PetriNetSim, PetriObjModelPaint writes PetriObjModel. This app's block is
 * preferred and PetriObjModel is the load-bearing fallback that makes a
 * desktop-authored file open here. Documents from the brief era when both
 * tools mirrored every payload under both names still read fine, the
 * preference just picks one of the two identical blocks.
 *
 * The `version` attribute is deliberately not consulted. It names the release
 * whose vocabulary the block is written in, so filtering on it would drop the
 * data of every document written by a build newer than this reader.
 */
function findToolspecific(
  element: Record<string, unknown>,
): Record<string, unknown> | null {
  const ts = element.toolspecific;
  if (!ts) return null;
  if (Array.isArray(ts)) {
    const blocks = ts.filter(
      (t): t is Record<string, unknown> => typeof t === "object" && t != null,
    );
    const byTool = (tool: string) => blocks.find((t) => t["@_tool"] === tool);
    return byTool(TOOL_PETRI_NET_SIM) ?? byTool(TOOL_PETRI_OBJ_MODEL) ?? null;
  }
  if (typeof ts === "object") return ts as Record<string, unknown>;
  return null;
}

function parsePlace(raw: Record<string, unknown>, ctx: ParseCtx, idOverride?: string): PetriPlace {
  const rawId = String(raw["@_id"] ?? "");
  const visibleName = textOf(raw.name);
  // A fusion referencePlace hands in the id it already assigned itself, as a
  // reference node, above: the same XML element is being parsed a second time
  // as the real place it stands for, and it must keep the one id it was given.
  const id = idOverride ?? ctx.registry.assign("Place", rawId, visibleName, raw);
  const name = visibleName || id;

  const markingText = textOf(raw.initialMarking);
  let tokens = 0;
  if (markingText !== "") {
    const parsed = Number.parseInt(markingText, 10);
    if (!Number.isFinite(parsed)) {
      ctx.warn(
        "bad-number",
        `${describe("Place", id, name)} has a malformed initial marking "${markingText}"; imported with 0 tokens.`,
      );
    } else if (parsed < 0) {
      // ptnet initialMarking is a nonNegativeInteger: a negative value parses
      // fine as a number but is not a legal marking, which is a different
      // problem from failing to parse at all.
      ctx.warn(
        "invalid-value",
        `${describe("Place", id, name)} has initial marking ${parsed}, which is not a valid marking ` +
          "(a ptnet initial marking must be a nonnegative integer); imported as 0.",
      );
    } else {
      tokens = parsed;
    }
  }
  const graphics = extractCenterPosition(raw, "place");
  return { id, name, tokens, graphics };
}

function parseTransition(raw: Record<string, unknown>, ctx: ParseCtx): PetriTransition {
  const rawId = String(raw["@_id"] ?? "");
  const visibleName = textOf(raw.name);
  const id = ctx.registry.assign("Transition", rawId, visibleName, raw);
  const name = visibleName || id;
  const pos = extractCenterPosition(raw, "transition");

  const ts = findToolspecific(raw);
  let priority = 1;
  let distribution: DistributionType | null = "exp";
  let meanDelay = 1;
  let stdDev = 0;
  let probability: number | null = null;

  if (ts) {
    if (ts.priority != null) {
      // A plain `Number(...) || 1` treated an explicit, legal priority of 0
      // as if parsing had failed, silently turning it into 1. Only a value
      // that genuinely fails to parse gets that fallback now, and it warns.
      const p = Number(ts.priority);
      if (Number.isFinite(p)) {
        priority = p;
      } else {
        ctx.warn(
          "bad-number",
          `${describe("Transition", id, name)} has a malformed priority "${String(ts.priority)}"; imported with priority 1.`,
        );
      }
    }
    if (ts.probability != null) {
      const p = Number(ts.probability);
      if (Number.isFinite(p)) {
        probability = p;
        distribution = null;
      }
    }
    if (probability === null) {
      const distRaw = ts.distribution;
      if (typeof distRaw === "string") {
        const valid: DistributionType[] = ["exp", "norm", "unif", "det"];
        distribution = valid.includes(distRaw as DistributionType)
          ? (distRaw as DistributionType)
          : "exp";
      }
      if (ts.delayMeanValue != null) {
        meanDelay = Number(ts.delayMeanValue) || 0;
      } else if (ts.timeDelay != null) {
        meanDelay = Number(ts.timeDelay) || 0;
      }
      if (ts.standardDeviation != null) {
        stdDev = Number(ts.standardDeviation) || 0;
      }
    }
  }

  return {
    id,
    name,
    priority,
    distribution,
    mean_delay: meanDelay,
    standard_deviation: stdDev,
    probability,
    graphics: pos,
  };
}

function parseArc(raw: Record<string, unknown>, ctx: ParseCtx): PetriArc {
  const rawId = String(raw["@_id"] ?? "");
  const id = ctx.registry.assign("Arc", rawId, "", raw);
  const rawSourceId = String(raw["@_source"] ?? "");
  const rawTargetId = String(raw["@_target"] ?? "");
  const sourceId = ctx.registry.resolve(rawSourceId) ?? rawSourceId;
  const targetId = ctx.registry.resolve(rawTargetId) ?? rawTargetId;

  // An inscription of exactly 0 parses as a number fine, but is not a legal
  // ptnet arc weight (positiveInteger); unparseable text is not a number at
  // all. The two are different problems and get different warning codes.
  const inscriptionText = textOf(raw.inscription);
  let weight = 1;
  if (inscriptionText !== "") {
    const parsed = Number.parseInt(inscriptionText, 10);
    if (!Number.isFinite(parsed)) {
      ctx.warn(
        "bad-number",
        `${describe("Arc", id, "")} has a malformed inscription "${inscriptionText}"; imported with weight 1.`,
      );
    } else if (parsed < 1) {
      ctx.warn(
        "invalid-value",
        `${describe("Arc", id, "")} has inscription ${parsed}, which is not a valid weight ` +
          "(a ptnet arc weight must be a positive integer); imported as 1.",
      );
    } else {
      weight = parsed;
    }
  }

  // Three shapes say the same thing, and the desktop's PnmlParser.parseArcs
  // accepts all three, so this reader does too or a file that opens there
  // silently loses its arc kinds here. The `type` attribute is this app's own
  // shorthand and wins; then the tool-specific `<arcType>` both writers emit;
  // then the standard PNML `<type value="inhibitorArc"/>` child a foreign tool
  // would write.
  let arcType: ArcType = "NORMAL";
  const typeRaw = raw["@_type"];
  if (typeof typeRaw === "string") {
    const upper = typeRaw.toUpperCase();
    if (upper === "INHIBITOR") arcType = "INHIBITOR";
    else if (upper === "READ") arcType = "READ";
  }
  if (arcType === "NORMAL") {
    const toolArcType = textOf(toolspecificValue(raw, "arcType")).toLowerCase();
    if (toolArcType === "inhibitor") arcType = "INHIBITOR";
    else if (toolArcType === "read") arcType = "READ";
  }
  if (arcType === "NORMAL") {
    // The same fact in the other tool's spelling. PetriObjModelPaint calls a
    // non-consuming input arc informational and writes it that way, including
    // when it is re-writing a document that arrived here saying arcType=read.
    // Reading only arcType turned every read arc into an ordinary one on the
    // way back from the desktop, which silently changes what the net does.
    if (textOf(toolspecificValue(raw, "informational")) === "true") arcType = "READ";
  }
  if (arcType === "NORMAL") {
    for (const typeElement of asArray(raw.type)) {
      const value = String(typeElement["@_value"] ?? "").toLowerCase();
      if (value.includes("inhibitor")) {
        arcType = "INHIBITOR";
        break;
      }
    }
  }

  return {
    id,
    source_id: sourceId,
    target_id: targetId,
    weight,
    arc_type: arcType,
  };
}

export function parsePnml(xml: string): PnmlImportResult {
  const doc = parser.parse(xml);
  const pnml = doc.pnml;
  if (!pnml) throw new Error("Invalid PNML: missing <pnml> root element");

  const netNode = pnml.net;
  if (!netNode) throw new Error("Invalid PNML: missing <net> element");

  const net = Array.isArray(netNode) ? netNode[0] : netNode;
  const name = textOf(net.name) || "Imported net";

  const { ctx, warnings } = createParseContext();

  // The net's own id is never stored anywhere in the model (nothing in this
  // app ever addresses a net by id), so an invalid one only gets a warning:
  // there is no wire reference to it that would need remapping.
  const rawNetId = (net as Record<string, unknown>)["@_id"];
  if (rawNetId != null && String(rawNetId) !== "" && !isNCName(String(rawNetId))) {
    ctx.warn(
      "invalid-id",
      `The net's own id "${String(rawNetId)}" is not a valid XML id. It is not stored in the model, so nothing was renamed.`,
    );
  }

  if (isComposedDocument(net as Record<string, unknown>)) {
    const data = parseComposedPnml(net as Record<string, unknown>, name, ctx);
    return { data, warnings };
  }

  // Support both flat <net> and page-wrapped <net><page> layouts
  const pageNode = net.page
    ? (Array.isArray(net.page) ? net.page[0] : net.page)
    : null;
  const container = (pageNode ?? net) as Record<string, unknown>;

  const rawPlaces: unknown[] = (container.place as unknown[]) ?? [];
  const rawTransitions: unknown[] = (container.transition as unknown[]) ?? [];
  const rawArcs: unknown[] = (container.arc as unknown[]) ?? [];

  const places = rawPlaces.map((p) => parsePlace(p as Record<string, unknown>, ctx));
  const transitions = rawTransitions.map((t) =>
    parseTransition(t as Record<string, unknown>, ctx),
  );
  const arcs = rawArcs.map((a) => parseArc(a as Record<string, unknown>, ctx));

  return { data: { name, places, transitions, arcs }, warnings };
}
