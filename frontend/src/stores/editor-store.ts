import { create } from "zustand";
import { persist } from "zustand/middleware";
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
import type { InstantiatedSubnet } from "@/lib/petri-object-instantiate";
import {
  allNodeIds,
  cloneElements,
  frameBoundsFor,
  fusionGroupsByPlace,
  getLinks,
  getObjects,
  isLocalToNet,
  objectAsGroup,
  objectSubtreeIds,
  refitFrame,
  nextLinkId,
  ownerOf,
  reconcileArcsForNewMembership,
  reconcileLinksForNewMembership,
  rejectionForFusion,
  synthesizePlaceToTransitionFusion,
  type ElementGroup,
} from "@/lib/petri-object-model";
import { nextId, nextLabel } from "@/lib/petri-ids";
import { randomNetName } from "@/lib/random-net-name";

export type EditorTool =
  | "select"
  | "select-box"
  | "select-lasso"
  | "delete"
  | "add-place"
  | "add-transition"
  | "add-arc"
  | "add-object";

export type EdgeStyle = "curved" | "orthogonal" | "straight";

export const EDGE_STYLE_OPTIONS: { value: EdgeStyle; label: string }[] = [
  { value: "curved", label: "Curved" },
  { value: "orthogonal", label: "Orthogonal" },
  { value: "straight", label: "Straight" },
];

/** How an object frame's dashed boundary is drawn on the canvas. */
export type FrameStyle = "rect" | "wavy";

export const FRAME_STYLE_OPTIONS: { value: FrameStyle; label: string }[] = [
  { value: "rect", label: "Rectangular" },
  { value: "wavy", label: "Wavy" },
];

export type ElementKind = "place" | "transition" | "arc" | "object" | "link";

export interface ElementRef {
  id: string;
  kind: ElementKind;
}

const MAX_HISTORY = 100;
const PASTE_OFFSET = 20;

type ClipboardData = ElementGroup;

interface EditorState {
  net: PetriNetData;
  dirty: boolean;
  tool: EditorTool;
  edgeStyle: EdgeStyle;
  frameStyle: FrameStyle;

  /** Backend UUID of the saved net (null = never saved to cloud). */
  cloudNetId: string | null;

  /** Primary selection (last element the user clicked). */
  selection: ElementRef[];

  /**
   * Source node chosen for the in-progress arc when tool === "add-arc".
   * Cleared after the target is picked or the tool changes.
   */
  pendingArcSource: { id: string; kind: "place" | "transition" } | null;

  /** Undo stack — previous net snapshots. */
  past: PetriNetData[];
  /** Redo stack — undone net snapshots. */
  future: PetriNetData[];

  /** Internal clipboard for copy/cut/paste. */
  clipboard: ClipboardData | null;

  // --- global actions ---
  setTool: (tool: EditorTool) => void;
  setEdgeStyle: (style: EdgeStyle) => void;
  setFrameStyle: (style: FrameStyle) => void;
  setNet: (net: PetriNetData) => void;
  resetNet: (name?: string) => void;
  markClean: () => void;

  setSelection: (selection: ElementRef[]) => void;
  clearSelection: () => void;

  /**
   * Monotonically increasing counter. Incremented every time the inspector
   * should collapse (pane click, canvas pan). Components subscribe to detect
   * the signal even when selection is already empty.
   */
  inspectorCollapseSignal: number;
  collapseInspector: () => void;
  selectAll: () => void;

  setPendingArcSource: (
    source: { id: string; kind: "place" | "transition" } | null,
  ) => void;

  // --- undo/redo ---
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;

  // --- clipboard ---
  copySelection: () => void;
  cutSelection: () => void;
  paste: () => void;

  // --- structural mutations ---
  addPlace: (x: number, y: number, opts?: { objectId?: string }) => string;
  addTransition: (x: number, y: number, opts?: { objectId?: string }) => string;
  addArc: (
    sourceId: string,
    targetId: string,
    opts?: { weight?: number; arcType?: ArcType },
  ) => string | null;

  moveNode: (id: string, x: number, y: number) => void;
  /**
   * Commit every final position of ONE multi-selection drag as ONE undoable
   * step. An "object" move shifts its whole subtree like moveObject does;
   * an "element" target is the absolute final spot and wins over any subtree
   * shift that already carried it, so a selection holding both a frame and
   * its members commits cleanly.
   */
  moveManyTo: (
    moves: { id: string; kind: "element" | "object"; x: number; y: number }[],
  ) => void;

  updatePlace: (id: string, patch: Partial<Omit<PetriPlace, "id">>) => void;
  updateTransition: (
    id: string,
    patch: Partial<Omit<PetriTransition, "id">>,
  ) => void;
  updateArc: (id: string, patch: Partial<Omit<PetriArc, "id">>) => void;

  renameNet: (name: string) => void;

  addSubnet: (subnet: InstantiatedSubnet) => void;
  /**
   * Append an already-cloned group — frames, members, arcs and object links —
   * as one undoable step. This is what a composed PNML import merges in with:
   * unlike addSubnet it carries the object structure, and unlike paste it
   * takes the group directly instead of reading the clipboard.
   */
  addElementGroup: (group: ElementGroup) => void;
  /**
   * Drop a template onto the canvas already wrapped in its own object frame,
   * as a single undoable step (rather than add-then-group, which would leave
   * a half-formed object in the history).
   */
  addSubnetAsObject: (
    subnet: InstantiatedSubnet,
    name: string,
    opts?: { templateId?: string | null },
  ) => string;

  // --- object frames (composed models) ---
  addObjectFrame: (
    x: number,
    y: number,
    width?: number,
    height?: number,
    opts?: { parentId?: string },
  ) => string;
  renameObject: (id: string, name: string) => void;
  setObjectPriority: (id: string, priority: number) => void;
  setObjectTemplateId: (id: string, templateId: string | null) => void;
  resizeObject: (id: string, width: number, height: number) => void;
  moveObject: (id: string, x: number, y: number) => void;
  /** Re-fit a frame around its members (no-op once the user resized it by hand). */
  refitObject: (id: string) => void;
  /** Re-enable auto-fit and immediately snap the frame back around its members. */
  enableObjectAutoFit: (id: string) => void;
  toggleObjectCollapsed: (id: string) => void;
  deleteObject: (id: string, opts?: { keepContents?: boolean }) => void;
  /** Dissolve the frame, leaving its members on the canvas as plain elements. */
  ungroupObject: (id: string) => void;
  /** Copy a frame with its contents to a slight offset, and select the copy. */
  duplicateObject: (id: string) => string | null;
  groupSelectionIntoObject: (name?: string) => string | null;
  /**
   * Frame exactly these places/transitions/object frames, whatever the
   * current selection is. A frame id nests that whole existing object one
   * level deeper (its own members stay put, only the frame's own objectId
   * changes) rather than being treated as a member to steal contents from.
   * The new frame nests inside `opts.parentId` when given, else inside the
   * one frame everything given already shared (if they share one).
   */
  groupElementsIntoObject: (
    elementIds: string[],
    name?: string,
    opts?: { parentId?: string },
  ) => string | null;
  addElementToObject: (
    elementId: string,
    elementKind: "place" | "transition",
    objectId: string,
  ) => void;
  removeElementFromObject: (elementId: string) => void;

  /**
   * `sourceId`/`targetId` always mean STORAGE direction, the same as
   * `ObjectLink` itself, never "which end the gesture started from". For
   * placeFusion specifically that means sourceId is the COPY and targetId is
   * the MASTER it repeats (see rejectionForFusion), so a caller that resolves
   * a drawn connection (where the user drags FROM the place being repeated
   * TO the place that copies it) must pass (copyId, masterId), i.e. the
   * gesture's target first, not its own (source, target) order verbatim.
   */
  addObjectLink: (
    type: ObjectLinkType,
    sourceId: string,
    targetId: string,
    opts?: { quantity?: number; informational?: boolean },
  ) => string | null;
  /**
   * The editor's equivalent of drawing an arc from a place straight into a
   * foreign object's transition: there is no placeToTransition link (see
   * synthesizePlaceToTransitionFusion), so this synthesizes a local proxy
   * place inside the transition's own object, an ordinary local arc to the
   * transition, and a placeFusion back to `placeId` — one undo step.
   */
  linkPlaceToForeignTransition: (
    placeId: string,
    transitionId: string,
    opts?: { quantity?: number; informational?: boolean },
  ) => string | null;
  updateObjectLink: (id: string, patch: Partial<Omit<ObjectLink, "id" | "type">>) => void;
  deleteObjectLink: (id: string) => void;

  deleteSelection: () => void;
  deleteElement: (ref: ElementRef) => void;
}

const DEFAULT_TRANSITION: Omit<PetriTransition, "id" | "name" | "graphics"> = {
  priority: 1,
  distribution: "exp" as DistributionType,
  mean_delay: 1,
  standard_deviation: 0,
  probability: null,
};

function emptyNet(name = randomNetName()): PetriNetData {
  return { name, places: [], transitions: [], arcs: [] };
}

function pushHistory(past: PetriNetData[], net: PetriNetData): PetriNetData[] {
  const next = [...past, net];
  if (next.length > MAX_HISTORY) next.shift();
  return next;
}

export const useEditorStore = create<EditorState>()(
  persist(
    (set, get) => ({
  net: emptyNet(),
  dirty: false,
  tool: "select",
  edgeStyle: "curved",
  frameStyle: "rect",
  cloudNetId: null,
  selection: [],
  pendingArcSource: null,
  past: [],
  future: [],
  clipboard: null,
  inspectorCollapseSignal: 0,

  setTool: (tool) =>
    set((s) => ({
      tool,
      pendingArcSource: tool === "add-arc" ? s.pendingArcSource : null,
    })),

  setEdgeStyle: (edgeStyle) => set({ edgeStyle }),

  setFrameStyle: (frameStyle) => set({ frameStyle }),

  setNet: (net) =>
    set({
      net,
      dirty: false,
      cloudNetId: null,
      selection: [],
      pendingArcSource: null,
      past: [],
      future: [],
    }),

  resetNet: (name) =>
    set({
      net: emptyNet(name),
      dirty: false,
      cloudNetId: null,
      selection: [],
      pendingArcSource: null,
      past: [],
      future: [],
    }),

  markClean: () => set({ dirty: false }),

  setSelection: (selection) => {
    const current = get().selection;
    if (current.length === selection.length) {
      const currentMap = new Map(current.map((c) => [c.id, c.kind]));
      if (selection.every((s) => currentMap.get(s.id) === s.kind)) return;
    }
    set({ selection });
  },
  clearSelection: () => set({ selection: [] }),
  collapseInspector: () =>
    set((s) => ({ inspectorCollapseSignal: s.inspectorCollapseSignal + 1 })),

  selectAll: () => {
    const { net } = get();
    const refs: ElementRef[] = [
      ...getObjects(net).map((o): ElementRef => ({ id: o.id, kind: "object" })),
      ...net.places.map((p): ElementRef => ({ id: p.id, kind: "place" })),
      ...net.transitions.map(
        (t): ElementRef => ({ id: t.id, kind: "transition" }),
      ),
      ...net.arcs.map((a): ElementRef => ({ id: a.id, kind: "arc" })),
      ...getLinks(net).map((l): ElementRef => ({ id: l.id, kind: "link" })),
    ];
    set({ selection: refs });
  },

  setPendingArcSource: (source) => set({ pendingArcSource: source }),

  // --- undo/redo ---

  undo: () => {
    const { past, net, future } = get();
    if (past.length === 0) return;
    const prev = past[past.length - 1];
    set({
      net: prev,
      past: past.slice(0, -1),
      future: [net, ...future].slice(0, MAX_HISTORY),
      dirty: true,
      selection: [],
    });
  },

  redo: () => {
    const { past, net, future } = get();
    if (future.length === 0) return;
    const next = future[0];
    set({
      net: next,
      past: pushHistory(past, net),
      future: future.slice(1),
      dirty: true,
      selection: [],
    });
  },

  canUndo: () => get().past.length > 0,
  canRedo: () => get().future.length > 0,

  // --- clipboard ---

  copySelection: () => {
    const { net, selection } = get();
    if (selection.length === 0) return;

    const selIds = new Set(selection.map((s) => s.id));
    // A selected object travels with everything inside it: copying a frame
    // without its contents would paste an empty box.
    const objects = getObjects(net).filter((o) => selIds.has(o.id));
    const copiedObjectIds = new Set(objects.map((o) => o.id));
    const belongs = (elementObjectId?: string) =>
      elementObjectId !== undefined && copiedObjectIds.has(elementObjectId);

    const places = net.places.filter((p) => selIds.has(p.id) || belongs(p.objectId));
    const transitions = net.transitions.filter(
      (t) => selIds.has(t.id) || belongs(t.objectId),
    );
    const nodeIds = new Set([
      ...places.map((p) => p.id),
      ...transitions.map((t) => t.id),
    ]);
    const arcs = net.arcs.filter(
      (a) => nodeIds.has(a.source_id) && nodeIds.has(a.target_id),
    );
    // A place fusion (or crossing link) between two copied elements — e.g. two
    // selected objects sharing a place — travels with the copy just like an
    // arc between two copied nodes does; one with an endpoint outside the
    // selection is left behind rather than pointing at an uncopied element.
    const links = getLinks(net).filter(
      (l) => nodeIds.has(l.sourceId) && nodeIds.has(l.targetId),
    );
    set({ clipboard: { objects, places, transitions, arcs, links } });
  },

  cutSelection: () => {
    get().copySelection();
    get().deleteSelection();
  },

  paste: () => {
    const { clipboard, net, past } = get();
    if (!clipboard) return;
    if (
      clipboard.objects.length === 0 &&
      clipboard.places.length === 0 &&
      clipboard.transitions.length === 0
    ) {
      return;
    }

    const copy = cloneElements(net, clipboard, { x: PASTE_OFFSET, y: PASTE_OFFSET });

    // Selecting a pasted object rather than its members mirrors what the user
    // copied, and keeps the frame as the thing they can immediately move.
    const pastedMemberIds = new Set(
      [...copy.places, ...copy.transitions].filter((e) => e.objectId).map((e) => e.id),
    );
    const newSelection: ElementRef[] = [
      ...copy.objects.map((o): ElementRef => ({ id: o.id, kind: "object" })),
      ...copy.places
        .filter((p) => !pastedMemberIds.has(p.id))
        .map((p): ElementRef => ({ id: p.id, kind: "place" })),
      ...copy.transitions
        .filter((t) => !pastedMemberIds.has(t.id))
        .map((t): ElementRef => ({ id: t.id, kind: "transition" })),
    ];

    set({
      net: {
        ...net,
        objects: [...getObjects(net), ...copy.objects],
        places: [...net.places, ...copy.places],
        transitions: [...net.transitions, ...copy.transitions],
        arcs: [...net.arcs, ...copy.arcs],
        links: [...getLinks(net), ...copy.links],
      },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: newSelection,
    });
  },

  // --- structural mutations ---

  addPlace: (x, y, opts) => {
    const { net, past } = get();
    const id = nextId("p", net.places);
    const name = nextLabel("Place", net.places, 1);
    const place: PetriPlace = {
      id,
      name,
      tokens: 0,
      graphics: { x, y },
      objectId: opts?.objectId,
    };
    // Creating inside a frame is one gesture, so membership (and the frame
    // re-fitting around its new member) belongs to the same undo step.
    const withPlace = { ...net, places: [...net.places, place] };
    set({
      net: opts?.objectId ? refitFrame(withPlace, opts.objectId) : withPlace,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [{ id, kind: "place" }],
    });
    return id;
  },

  addTransition: (x, y, opts) => {
    const { net, past } = get();
    const id = nextId("t", net.transitions);
    const name = nextLabel("T", net.transitions, 1);
    const transition: PetriTransition = {
      id,
      name,
      ...DEFAULT_TRANSITION,
      graphics: { x, y },
      objectId: opts?.objectId,
    };
    const withTransition = { ...net, transitions: [...net.transitions, transition] };
    set({
      net: opts?.objectId ? refitFrame(withTransition, opts.objectId) : withTransition,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [{ id, kind: "transition" }],
    });
    return id;
  },

  addArc: (sourceId, targetId, opts) => {
    const { net, past } = get();

    if (sourceId === targetId) return null;

    const sourceIsPlace = net.places.some((p) => p.id === sourceId);
    const sourceIsTransition = net.transitions.some((t) => t.id === sourceId);
    const targetIsPlace = net.places.some((p) => p.id === targetId);
    const targetIsTransition = net.transitions.some((t) => t.id === targetId);

    if (!sourceIsPlace && !sourceIsTransition) return null;
    if (!targetIsPlace && !targetIsTransition) return null;

    if (sourceIsPlace === targetIsPlace) return null;

    // Different objects: not a plain arc — use addObjectLink instead. A no-op
    // (undefined === undefined) on any net with no frames.
    if (ownerOf(net, sourceId) !== ownerOf(net, targetId)) return null;

    if (
      net.arcs.some(
        (a) => a.source_id === sourceId && a.target_id === targetId,
      )
    ) {
      return null;
    }

    const id = nextId("a", net.arcs);
    const arc: PetriArc = {
      id,
      source_id: sourceId,
      target_id: targetId,
      weight: opts?.weight ?? 1,
      arc_type: opts?.arcType ?? "NORMAL",
    };

    set({
      net: { ...net, arcs: [...net.arcs, arc] },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [{ id, kind: "arc" }],
    });
    return id;
  },

  moveNode: (id, x, y) => {
    const { net, past } = get();
    const places = net.places.map((p) =>
      p.id === id ? { ...p, graphics: { x, y } } : p,
    );
    const transitions = net.transitions.map((t) =>
      t.id === id ? { ...t, graphics: { x, y } } : t,
    );
    const moved: PetriNetData = { ...net, places, transitions };
    // Moving a member re-pads its frame in the same history entry, so the
    // boundary keeps its offset from the outermost elements as they shift.
    const owner = ownerOf(moved, id);
    set({
      net: owner ? refitFrame(moved, owner) : moved,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  moveManyTo: (moves) => {
    const { net, past } = get();
    if (moves.length === 0) return;

    const frameById = new Map(getObjects(net).map((o) => [o.id, o]));
    const objectMoves = moves.filter((m) => m.kind === "object" && frameById.has(m.id));
    const movedFrameIds = new Set(objectMoves.map((m) => m.id));
    const explicitElementIds = new Set(
      moves.filter((m) => m.kind === "element").map((m) => m.id),
    );

    // In one gesture every dragged node shares one delta, so a frame whose
    // ancestor is also in the batch already rides that ancestor's subtree
    // shift; applying its own move too would shift it twice.
    const hasMovedAncestor = (id: string): boolean => {
      const seen = new Set<string>([id]);
      let current = frameById.get(id)?.objectId;
      while (current && !seen.has(current)) {
        if (movedFrameIds.has(current)) return true;
        seen.add(current);
        current = frameById.get(current)?.objectId;
      }
      return false;
    };

    let working = net;
    for (const m of objectMoves) {
      if (hasMovedAncestor(m.id)) continue;
      const frame = getObjects(working).find((o) => o.id === m.id);
      if (!frame) continue;
      const dx = m.x - frame.graphics.x;
      const dy = m.y - frame.graphics.y;
      if (dx === 0 && dy === 0) continue;
      const subtree = objectSubtreeIds(working, m.id);
      // Members with an explicit target of their own are left to it — the
      // caller hands FINAL positions, and shifting first would stack the
      // frame's delta on top of them.
      const owned = (el: { id: string; objectId?: string }) =>
        el.objectId !== undefined && subtree.has(el.objectId) && !explicitElementIds.has(el.id);
      working = {
        ...working,
        objects: getObjects(working).map((o) =>
          subtree.has(o.id)
            ? { ...o, graphics: { ...o.graphics, x: o.graphics.x + dx, y: o.graphics.y + dy } }
            : o,
        ),
        places: working.places.map((p) =>
          owned(p) ? { ...p, graphics: { x: p.graphics.x + dx, y: p.graphics.y + dy } } : p,
        ),
        transitions: working.transitions.map((t) =>
          owned(t) ? { ...t, graphics: { x: t.graphics.x + dx, y: t.graphics.y + dy } } : t,
        ),
      };
    }
    for (const m of moves) {
      if (m.kind !== "element") continue;
      working = {
        ...working,
        places: working.places.map((p) =>
          p.id === m.id ? { ...p, graphics: { x: m.x, y: m.y } } : p,
        ),
        transitions: working.transitions.map((t) =>
          t.id === m.id ? { ...t, graphics: { x: m.x, y: m.y } } : t,
        ),
      };
    }
    if (working === net) return;

    // Frames whose members moved while the frame itself stayed put re-pad in
    // the same entry, the multi-element counterpart of moveNode's refit. A
    // frame the user dragged (or that rode a dragged ancestor) keeps the box
    // the drag gave it.
    const movedElementOwners = new Set(
      moves
        .filter((m) => m.kind === "element")
        .map((m) => ownerOf(working, m.id))
        .filter(
          (o): o is string =>
            o !== undefined && !movedFrameIds.has(o) && !hasMovedAncestor(o),
        ),
    );
    for (const owner of movedElementOwners) working = refitFrame(working, owner);

    set({
      net: working,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  updatePlace: (id, patch) => {
    const { net, past } = get();

    // A fused place has ONE marking shared by every member of the group — an
    // edit to `tokens` here writes through to all of them in the same store
    // update, so it stays one undoable step. Every other field (name,
    // position, ...) stays per-place: fusion only unifies identity/marking.
    const group = patch.tokens !== undefined ? fusionGroupsByPlace(net).get(id) : undefined;
    const partnerIds = group ? new Set(group.members.filter((m) => m !== id)) : null;

    const places = net.places.map((p) => {
      if (p.id === id) {
        return { ...p, ...patch, graphics: patch.graphics ?? p.graphics };
      }
      if (partnerIds?.has(p.id)) {
        return { ...p, tokens: patch.tokens! };
      }
      return p;
    });
    set({
      net: { ...net, places },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  updateTransition: (id, patch) => {
    const { net, past } = get();
    const transitions = net.transitions.map((t) =>
      t.id === id
        ? {
            ...t,
            ...patch,
            graphics: patch.graphics ?? t.graphics,
          }
        : t,
    );
    set({
      net: { ...net, transitions },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  updateArc: (id, patch) => {
    const { net, past } = get();
    const arcs = net.arcs.map((a) => (a.id === id ? { ...a, ...patch } : a));
    set({
      net: { ...net, arcs },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  renameNet: (name) => {
    const { net, past } = get();
    set({
      net: { ...net, name },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  addSubnet: (subnet) => {
    const { net, past } = get();
    // Only select nodes, not arcs — passing edges with selected:true into ReactFlow's
    // controlled mode while onEdgesChange is a no-op triggers an infinite sync loop.
    const newSelection: ElementRef[] = [
      ...subnet.places.map((p): ElementRef => ({ id: p.id, kind: "place" })),
      ...subnet.transitions.map(
        (t): ElementRef => ({ id: t.id, kind: "transition" }),
      ),
    ];
    set({
      net: {
        ...net,
        places: [...net.places, ...subnet.places],
        transitions: [...net.transitions, ...subnet.transitions],
        arcs: [...net.arcs, ...subnet.arcs],
      },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: newSelection,
    });
  },

  addElementGroup: (group) => {
    const { net, past } = get();
    set({
      net: {
        ...net,
        objects: [...getObjects(net), ...group.objects],
        places: [...net.places, ...group.places],
        transitions: [...net.transitions, ...group.transitions],
        arcs: [...net.arcs, ...group.arcs],
        links: [...getLinks(net), ...group.links],
      },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [],
    });
  },

  addSubnetAsObject: (subnet, name, opts) => {
    const { net, past } = get();
    const objects = getObjects(net);
    const subnetFrames = subnet.objects ?? [];
    const subnetLinks = subnet.links ?? [];
    const id = nextId("o", [
      ...allNodeIds(net),
      ...subnet.places,
      ...subnet.transitions,
      ...subnetFrames,
    ]);

    // A nested template keeps its structure: a frame or element that already
    // has an owner inside the subnet stays with it; only the subnet's own
    // top level is adopted by the new wrapper. Flattening here is what used
    // to strip a saved object of its inner Petri-objects on every drop.
    const adopt = <T extends { objectId?: string }>(el: T): T =>
      el.objectId ? el : { ...el, objectId: id };
    const nestedFrames = subnetFrames.map(adopt);

    const memberIds = new Set([
      ...subnet.places.map((p) => p.id),
      ...subnet.transitions.map((t) => t.id),
      ...subnetFrames.map((o) => o.id),
    ]);
    const withMembers: PetriNetData = {
      ...net,
      objects: [...objects, ...nestedFrames],
      places: [...net.places, ...subnet.places.map(adopt)],
      transitions: [...net.transitions, ...subnet.transitions.map(adopt)],
      arcs: [...net.arcs, ...subnet.arcs],
      links: [...getLinks(net), ...subnetLinks],
    };

    const frame: ObjectFrame = {
      id,
      name: nextLabel(name, objects),
      priority: 0,
      graphics: frameBoundsFor(withMembers, memberIds) ?? {
        x: 0,
        y: 0,
        width: 240,
        height: 160,
      },
      templateId: opts?.templateId ?? null,
    };

    set({
      net: { ...withMembers, objects: [...withMembers.objects!, frame] },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [{ id, kind: "object" }],
    });
    return id;
  },

  // --- object frames (composed models) ---

  addObjectFrame: (x, y, width = 240, height = 160, opts) => {
    const { net, past } = get();
    const objects = getObjects(net);
    const id = nextId("o", allNodeIds(net));
    const name = nextLabel("Object", objects, 1);
    const frame: ObjectFrame = {
      id,
      name,
      priority: 0,
      graphics: { x, y, width, height },
      // Drawn inside another frame = built inside that object; the depth of
      // this chain is the object's abstraction level.
      objectId: opts?.parentId,
    };
    const withFrame = { ...net, objects: [...objects, frame] };
    set({
      net: opts?.parentId ? refitFrame(withFrame, opts.parentId) : withFrame,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [{ id, kind: "object" }],
    });
    return id;
  },

  renameObject: (id, name) => {
    const { net, past } = get();
    const objects = getObjects(net).map((o) => (o.id === id ? { ...o, name } : o));
    set({
      net: { ...net, objects },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  setObjectPriority: (id, priority) => {
    const { net, past } = get();
    const objects = getObjects(net).map((o) => (o.id === id ? { ...o, priority } : o));
    set({
      net: { ...net, objects },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  setObjectTemplateId: (id, templateId) => {
    const { net } = get();
    const objects = getObjects(net).map((o) =>
      o.id === id ? { ...o, templateId } : o,
    );
    // Bookkeeping only — no history entry, nothing about the net changed.
    set({ net: { ...net, objects } });
  },

  refitObject: (id) => {
    const { net, past } = get();
    const refitted = refitFrame(net, id);
    if (refitted === net) return;
    set({ net: refitted, past: pushHistory(past, net), future: [], dirty: true });
  },

  enableObjectAutoFit: (id) => {
    const { net, past } = get();
    const withAutoFit: PetriNetData = {
      ...net,
      objects: getObjects(net).map((o) =>
        o.id === id ? { ...o, autoFit: true } : o,
      ),
    };
    set({
      net: refitFrame(withAutoFit, id),
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  resizeObject: (id, width, height) => {
    const { net, past } = get();
    // A hand-drawn size is a deliberate choice — stop auto-fitting over it.
    const objects = getObjects(net).map((o) =>
      o.id === id
        ? { ...o, autoFit: false, graphics: { ...o.graphics, width, height } }
        : o,
    );
    set({
      net: { ...net, objects },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  moveObject: (id, x, y) => {
    const { net, past } = get();
    const frame = getObjects(net).find((o) => o.id === id);
    if (!frame) return;
    const dx = x - frame.graphics.x;
    const dy = y - frame.graphics.y;
    // The whole subtree travels. A nested object is content of its parent
    // just like a member element is; shifting only the direct members used
    // to leave child frames (and everything inside THEM) at their old
    // absolute spot — React Flow carried them along during the drag, and
    // the store snapped them back on drop.
    const subtree = objectSubtreeIds(net, id);
    const owned = (owner?: string) => owner !== undefined && subtree.has(owner);
    const objects = getObjects(net).map((o) =>
      subtree.has(o.id)
        ? { ...o, graphics: { ...o.graphics, x: o.graphics.x + dx, y: o.graphics.y + dy } }
        : o,
    );
    const places = net.places.map((p) =>
      owned(p.objectId)
        ? { ...p, graphics: { x: p.graphics.x + dx, y: p.graphics.y + dy } }
        : p,
    );
    const transitions = net.transitions.map((t) =>
      owned(t.objectId)
        ? { ...t, graphics: { x: t.graphics.x + dx, y: t.graphics.y + dy } }
        : t,
    );
    set({
      net: { ...net, objects, places, transitions },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  toggleObjectCollapsed: (id) => {
    const { net, past } = get();
    const objects = getObjects(net).map((o) =>
      o.id === id ? { ...o, collapsed: !o.collapsed } : o,
    );
    set({
      net: { ...net, objects },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  deleteObject: (id, opts) => {
    const { net, past, selection } = get();
    const keepContents = opts?.keepContents ?? true;

    if (keepContents) {
      const objects = getObjects(net).filter((o) => o.id !== id);
      const places = net.places.map((p) =>
        p.objectId === id ? { ...p, objectId: undefined } : p,
      );
      const transitions = net.transitions.map((t) =>
        t.objectId === id ? { ...t, objectId: undefined } : t,
      );
      // Freeing these elements may have just made an ObjectLink invalid (both
      // endpoints now share an owner, or both are free) — re-validate every
      // link the same way addObjectLink does at creation time.
      const reconciled = reconcileLinksForNewMembership({ ...net, objects, places, transitions });
      set({
        net: reconciled,
        past: pushHistory(past, net),
        future: [],
        dirty: true,
        selection: selection.filter((s) => s.id !== id),
      });
      return;
    }

    // A frame with a nested child object owns that child's frame too, not
    // just its own direct members — deleting must take the whole subtree, or
    // the child frame (and everything inside IT) survives as an orphan
    // pointing at a dissolved parent.
    const frameIds = objectSubtreeIds(net, id);
    const objects = getObjects(net).filter((o) => !frameIds.has(o.id));
    const memberIds = new Set([
      ...net.places.filter((p) => p.objectId !== undefined && frameIds.has(p.objectId)).map((p) => p.id),
      ...net.transitions
        .filter((t) => t.objectId !== undefined && frameIds.has(t.objectId))
        .map((t) => t.id),
    ]);
    const places = net.places.filter((p) => !memberIds.has(p.id));
    const transitions = net.transitions.filter((t) => !memberIds.has(t.id));
    const arcs = net.arcs.filter(
      (a) => !memberIds.has(a.source_id) && !memberIds.has(a.target_id),
    );
    const links = getLinks(net).filter(
      (l) => !memberIds.has(l.sourceId) && !memberIds.has(l.targetId),
    );
    const removedIds = new Set([...frameIds, ...memberIds]);
    set({
      net: { ...net, objects, places, transitions, arcs, links },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: selection.filter((s) => !removedIds.has(s.id)),
    });
  },

  ungroupObject: (id) => {
    get().deleteObject(id, { keepContents: true });
  },

  duplicateObject: (id) => {
    const { net, past } = get();
    const group = objectAsGroup(net, id);
    if (!group) return null;

    const copy = cloneElements(net, group, { x: PASTE_OFFSET, y: PASTE_OFFSET });
    const newId = copy.objects[0]?.id;
    if (!newId) return null;

    set({
      net: {
        ...net,
        objects: [...getObjects(net), ...copy.objects],
        places: [...net.places, ...copy.places],
        transitions: [...net.transitions, ...copy.transitions],
        arcs: [...net.arcs, ...copy.arcs],
        links: [...getLinks(net), ...copy.links],
      },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [{ id: newId, kind: "object" }],
    });
    return newId;
  },

  groupSelectionIntoObject: (name) => {
    const { selection } = get();
    return get().groupElementsIntoObject(
      selection
        .filter((s) => s.kind === "place" || s.kind === "transition" || s.kind === "object")
        .map((s) => s.id),
      name,
    );
  },

  groupElementsIntoObject: (elementIds, name, opts) => {
    const { net, past } = get();
    if (elementIds.length === 0) return null;

    const objects = getObjects(net);
    const objectIdSet = new Set(objects.map((o) => o.id));

    // A selected id naming an existing frame nests that whole object one
    // level deeper — only its own objectId moves, its members stay exactly
    // where they are. A place/transition already owned by one of those
    // selected frames is skipped here too: it is grouping only what it
    // still frees, at the byproduct of a marquee band that (correctly)
    // also swept up the frame's own contents. Without this split, both
    // cases fell through to the plain "reassign this id's objectId" path
    // below, which strips a selected frame's members into the new frame
    // and leaves the frame itself behind, empty.
    const selectedFrameIds = elementIds.filter((eid) => objectIdSet.has(eid));
    const selectedFrameIdSet = new Set(selectedFrameIds);
    const looseElementIds = elementIds.filter((eid) => {
      if (selectedFrameIdSet.has(eid)) return false;
      const owner = ownerOf(net, eid);
      return !owner || !selectedFrameIdSet.has(owner);
    });

    const ids = new Set([...selectedFrameIds, ...looseElementIds]);
    // Nothing resolved to a real frame or element — don't leave a stray frame at the origin.
    const bbox = frameBoundsFor(net, ids);
    if (!bbox) return null;

    const id = nextId("o", allNodeIds(net));

    // Members grouped out of one frame build the new object INSIDE it: that
    // is what drawing an object around an object's elements means, and a
    // top-level frame here would overlap the owner as a stranger — the two
    // then render interleaved and drag apart. The caller may name the parent
    // outright (the draw gesture knows which frame the band was drawn in);
    // otherwise it is inferred from the one owner everything given already
    // shared — a frame's own current parent counts here just as an element's
    // owning frame does. Different owners (or no owner at all) keep the new
    // frame top-level, as before.
    const owners = new Set<string>();
    for (const fid of selectedFrameIds) {
      const parent = objects.find((o) => o.id === fid)?.objectId;
      if (parent) owners.add(parent);
    }
    for (const eid of looseElementIds) {
      const owner = ownerOf(net, eid);
      if (owner) owners.add(owner);
    }
    const requestedParent =
      (opts?.parentId && objects.some((o) => o.id === opts.parentId)
        ? opts.parentId
        : undefined) ?? (owners.size === 1 ? [...owners][0] : undefined);

    // An object cannot be built inside something it is about to contain. Both
    // the caller's parentId and the inferred single owner can name a frame the
    // new one adopts, or one nested inside it, which is what a band drawn
    // around an already two-level object resolves to. Nesting it there anyway
    // closes a parent cycle (a frame becomes its own ancestor) and every walk
    // up the chain then spins forever, starting with the refit below: the
    // editor froze on the third round of "draw an object around the object".
    // Climb out to the nearest ancestor that stays outside what is adopted.
    const adopted = new Set(
      selectedFrameIds.flatMap((fid) => [...objectSubtreeIds(net, fid)]),
    );
    let parentId: string | undefined = requestedParent;
    const climbed = new Set<string>();
    while (parentId && adopted.has(parentId) && !climbed.has(parentId)) {
      climbed.add(parentId);
      parentId = objects.find((o) => o.id === parentId)?.objectId;
    }

    const frame: ObjectFrame = {
      id,
      name: name ?? nextLabel("Object", objects, 1),
      priority: 0,
      graphics: bbox,
      ...(parentId ? { objectId: parentId } : {}),
    };

    const looseIds = new Set(looseElementIds);
    const places = net.places.map((p) => (looseIds.has(p.id) ? { ...p, objectId: id } : p));
    const transitions = net.transitions.map((t) =>
      looseIds.has(t.id) ? { ...t, objectId: id } : t,
    );
    const reparentedObjects = [
      ...objects.map((o) => (selectedFrameIdSet.has(o.id) ? { ...o, objectId: id } : o)),
      frame,
    ];

    const withMembership: PetriNetData = {
      ...net,
      objects: reparentedObjects,
      places,
      transitions,
    };
    // Only elements that actually changed objectId (the loose ones) can have
    // put an existing arc/link out of step — a nested frame's own members
    // kept their direct owner, so their connections are untouched.
    let reconciled = reconcileLinksForNewMembership(
      reconcileArcsForNewMembership(withMembership, looseIds),
    );

    // The child frame clears its members by a padding the parent's old fit
    // did not account for: grow every auto-fitting ancestor around it. The
    // seen set is not about this action, which can no longer build a cycle:
    // a net that arrived with one (an old file, a hand-edited import) must
    // still not hang the editor on the next edit.
    const refitted = new Set<string>();
    for (
      let ancestor: string | undefined = parentId;
      ancestor && !refitted.has(ancestor);
      ancestor = getObjects(reconciled).find((o) => o.id === ancestor)?.objectId
    ) {
      refitted.add(ancestor);
      reconciled = refitFrame(reconciled, ancestor);
    }

    set({
      net: reconciled,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [{ id, kind: "object" }],
    });
    return id;
  },

  addElementToObject: (elementId, elementKind, objectId) => {
    const { net, past } = get();
    const places =
      elementKind === "place"
        ? net.places.map((p) => (p.id === elementId ? { ...p, objectId } : p))
        : net.places;
    const transitions =
      elementKind === "transition"
        ? net.transitions.map((t) => (t.id === elementId ? { ...t, objectId } : t))
        : net.transitions;
    const reconciled = reconcileArcsForNewMembership(
      { ...net, places, transitions },
      new Set([elementId]),
    );
    // Adoption can also make an ObjectLink same-owner (the element joins the
    // very object its link partner lives in) — such a link becomes a plain
    // arc, or is dropped when it was a fusion, exactly like on ungroup.
    const withLinksReconciled = reconcileLinksForNewMembership(reconciled);
    set({
      net: refitFrame(withLinksReconciled, objectId),
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  removeElementFromObject: (elementId) => {
    const { net, past } = get();
    const formerOwner = ownerOf(net, elementId);
    const places = net.places.map((p) =>
      p.id === elementId ? { ...p, objectId: undefined } : p,
    );
    const transitions = net.transitions.map((t) =>
      t.id === elementId ? { ...t, objectId: undefined } : t,
    );
    const reconciled = reconcileArcsForNewMembership(
      { ...net, places, transitions },
      new Set([elementId]),
    );
    // The element going free may also have just made an existing ObjectLink
    // invalid — e.g. a link between it and something that was already free
    // now has two same-owner (both undefined) endpoints. Re-validate every
    // link the same way addObjectLink does at creation time.
    const withLinksReconciled = reconcileLinksForNewMembership(reconciled);
    set({
      net: formerOwner ? refitFrame(withLinksReconciled, formerOwner) : withLinksReconciled,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  // --- object links (cross-object connections) ---

  addObjectLink: (type, sourceId, targetId, opts) => {
    const { net, past } = get();
    if (sourceId === targetId) return null;

    const sourceIsPlace = net.places.some((p) => p.id === sourceId);
    const sourceIsTransition = net.transitions.some((t) => t.id === sourceId);
    const targetIsPlace = net.places.some((p) => p.id === targetId);
    const targetIsTransition = net.transitions.some((t) => t.id === targetId);
    if (!sourceIsPlace && !sourceIsTransition) return null;
    if (!targetIsPlace && !targetIsTransition) return null;

    if (type === "placeFusion" && !(sourceIsPlace && targetIsPlace)) return null;
    if (type === "transitionToPlace" && !(sourceIsTransition && targetIsPlace)) return null;
    if (type === "placeToTransition" && !(sourceIsPlace && targetIsTransition)) return null;

    const links = getLinks(net);

    if (type === "placeFusion") {
      // sourceId is the copy, targetId is the master: rejectionForFusion is
      // the one authority for all five desktop rules (self-link, duplicate in
      // either direction, one master per copy, no loops, and same-object (the
      // carve-out from this app's old strict 1-to-1 rule) only refuses two
      // places that share a DEFINED owner, not two free ones).
      if (rejectionForFusion(net, sourceId, targetId) !== null) return null;
    } else {
      // The whole point of a directional link is connecting two DIFFERENT
      // objects; placeFusion earns its own same-object carve-out above.
      if (ownerOf(net, sourceId) === ownerOf(net, targetId)) return null;
      const duplicate = links.some(
        (l) => l.type === type && l.sourceId === sourceId && l.targetId === targetId,
      );
      if (duplicate) return null;
    }

    const id = nextLinkId(links);
    const link: ObjectLink = {
      id,
      type,
      sourceId,
      targetId,
      quantity: opts?.quantity ?? 1,
      informational: type === "placeToTransition" ? (opts?.informational ?? false) : undefined,
    };
    const linkedNet: PetriNetData = { ...net, links: [...links, link] };

    // Joining a fusion adopts the ROOT MASTER's count. targetId is the master
    // of the link just drawn, but that master can itself already be mid-chain
    // (a copy of something further up), so the newly merged group takes
    // whichever member fusionGroupsByPlace resolves as its root, never
    // targetId blindly, and every member, not just the two just linked, ends
    // up there. Folding this into the same set() as the link creation keeps
    // "join + adopt marking" one undoable step.
    let finalNet = linkedNet;
    if (type === "placeFusion") {
      const mergedGroup = fusionGroupsByPlace(linkedNet).get(targetId);
      const rootId = mergedGroup?.root ?? targetId;
      const rootTokens = net.places.find((p) => p.id === rootId)?.tokens ?? 0;
      const memberIds = new Set(mergedGroup?.members ?? [sourceId, targetId]);
      finalNet = {
        ...linkedNet,
        places: linkedNet.places.map((p) =>
          memberIds.has(p.id) ? { ...p, tokens: rootTokens } : p,
        ),
      };
    }

    set({
      net: finalNet,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [{ id, kind: "link" }],
    });
    return id;
  },

  linkPlaceToForeignTransition: (placeId, transitionId, opts) => {
    const { net, past } = get();
    const result = synthesizePlaceToTransitionFusion(net, placeId, transitionId, opts);
    if (!result) return null;
    set({
      net: result.net,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [{ id: result.linkId, kind: "link" }],
    });
    return result.linkId;
  },

  updateObjectLink: (id, patch) => {
    const { net, past } = get();
    const links = getLinks(net).map((l) => (l.id === id ? { ...l, ...patch } : l));
    set({
      net: { ...net, links },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
    });
  },

  deleteObjectLink: (id) => {
    const { net, past, selection } = get();
    const links = getLinks(net).filter((l) => l.id !== id);
    set({
      net: { ...net, links },
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: selection.filter((s) => s.id !== id),
    });
  },

  deleteElement: (ref) => {
    if (ref.kind === "object") {
      // Deleting an object deletes what it contains, the way deleting a place
      // takes its arcs with it. "Ungroup" is the action that keeps the members.
      get().deleteObject(ref.id, { keepContents: false });
      return;
    }
    if (ref.kind === "link") {
      get().deleteObjectLink(ref.id);
      return;
    }
    const { net, past } = get();
    let newNet: PetriNetData;
    if (ref.kind === "place") {
      newNet = {
        ...net,
        places: net.places.filter((p) => p.id !== ref.id),
        arcs: net.arcs.filter(
          (a) => a.source_id !== ref.id && a.target_id !== ref.id,
        ),
        links: getLinks(net).filter(
          (l) => l.sourceId !== ref.id && l.targetId !== ref.id,
        ),
      };
    } else if (ref.kind === "transition") {
      newNet = {
        ...net,
        transitions: net.transitions.filter((t) => t.id !== ref.id),
        arcs: net.arcs.filter(
          (a) => a.source_id !== ref.id && a.target_id !== ref.id,
        ),
        links: getLinks(net).filter(
          (l) => l.sourceId !== ref.id && l.targetId !== ref.id,
        ),
      };
    } else {
      newNet = {
        ...net,
        arcs: net.arcs.filter((a) => a.id !== ref.id),
      };
    }
    set({
      net: newNet,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: get().selection.filter((s) => s.id !== ref.id),
    });
  },

  deleteSelection: () => {
    const { net, past } = get();
    // A place/transition/object visible here only because its actual owner
    // is expanded isn't editable from here — deleting it (like moving or
    // resizing it) is confined to its own canvas. A plain arc is local only
    // when both its ends are; a link crosses object boundaries by
    // definition, so it's never "someone else's internals" and stays
    // deletable regardless. This mirrors the same rule the click/tool-driven
    // delete already enforces — the Delete key just reaches it more directly.
    const selection = get().selection.filter((ref) => {
      if (ref.kind === "arc") {
        const arc = net.arcs.find((a) => a.id === ref.id);
        return !arc || ownerOf(net, arc.source_id) === undefined;
      }
      if (ref.kind === "link") return true;
      return isLocalToNet(net, ref.id);
    });
    if (selection.length === 0) return;

    const delIds = new Set(selection.map((s) => s.id));
    // Deleting an object takes its contents with it, matching the single-element
    // delete and the frame's own context menu; "Ungroup" is what keeps them.
    // That cascade reaches the whole nested subtree, not just direct members —
    // otherwise a child frame built inside a deleted object (and everything
    // inside THAT) would survive as an orphan pointing at a dissolved parent.
    const deletedObjectIds = new Set(
      selection
        .filter((s) => s.kind === "object")
        .flatMap((s) => [...objectSubtreeIds(net, s.id)]),
    );
    const inDeletedObject = (objectId?: string) =>
      objectId !== undefined && deletedObjectIds.has(objectId);

    const nodeIds = new Set(
      [...net.places, ...net.transitions]
        .filter((e) => delIds.has(e.id) || inDeletedObject(e.objectId))
        .map((e) => e.id),
    );

    const places = net.places.filter((p) => !nodeIds.has(p.id));
    const transitions = net.transitions.filter((t) => !nodeIds.has(t.id));

    const newNet: PetriNetData = {
      ...net,
      objects: getObjects(net).filter((o) => !delIds.has(o.id) && !deletedObjectIds.has(o.id)),
      places,
      transitions,
      arcs: net.arcs.filter(
        (a) =>
          !delIds.has(a.id) &&
          !nodeIds.has(a.source_id) &&
          !nodeIds.has(a.target_id),
      ),
      links: getLinks(net).filter(
        (l) => !delIds.has(l.id) && !nodeIds.has(l.sourceId) && !nodeIds.has(l.targetId),
      ),
    };

    set({
      net: newNet,
      past: pushHistory(past, net),
      future: [],
      dirty: true,
      selection: [],
    });
  },
    }),
    {
      name: "petri-editor",
      version: 1,
      partialize: (state) => ({
        net: state.net,
        edgeStyle: state.edgeStyle,
        frameStyle: state.frameStyle,
      }),
    },
  ),
);

export function selectPrimary(state: EditorState): ElementRef | null {
  return state.selection[0] ?? null;
}
