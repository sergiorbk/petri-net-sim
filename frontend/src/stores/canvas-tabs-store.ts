import { create } from "zustand";
import type { PetriNetData } from "@/types/petri";
import { useEditorStore, type ElementRef } from "@/stores/editor-store";
import { applyObjectEdit, computeExternalConnections, extractObjectNet } from "@/lib/petri-object-editing";
import { getObjects } from "@/lib/petri-object-model";

export const MAIN_TAB_ID = "main";

/** How many parent-net revisions a write-back may push onto the undo stack. */
const MAX_HISTORY = 100;

/**
 * One open canvas. The path is what gives it an identity and a level: the net
 * itself is `["main"]` at level 0, an object opened from it is
 * `["main", objectId]` at level 1, an object opened from *that* canvas is
 * `["main", outerId, innerId]` at level 2, and so on.
 */
export interface CanvasTab {
  id: string;
  path: string[];
  title: string;
  /**
   * Names of what each of this object's own elements connects to outside
   * it, keyed by element id — purely a display aid for the ports drawn on
   * this canvas (see PlaceNodeData/TransitionNodeData's externalConnections
   * field), computed once from the parent net at open time. Absent for the
   * root net tab, which has no "outside" to speak of.
   */
  externalConnections?: Record<string, string[]>;
}

export function canvasLevel(tab: CanvasTab): number {
  return tab.path.length - 1;
}

export function objectIdOf(tab: CanvasTab): string | null {
  return tab.path.length > 1 ? tab.path[tab.path.length - 1] : null;
}

function parentIdOf(tab: CanvasTab): string | null {
  return tab.path.length > 1 ? tab.path.slice(0, -1).join("/") : null;
}

function pathId(path: string[]): string {
  return path.join("/");
}

/**
 * Everything a background canvas has to remember. The editor store stays a
 * single-document store — canvases simply swap its contents in and out — so
 * every existing action, shortcut and panel keeps working untouched.
 */
interface EditorSnapshot {
  net: PetriNetData;
  selection: ElementRef[];
  past: PetriNetData[];
  future: PetriNetData[];
  dirty: boolean;
  cloudNetId: string | null;
}

function captureEditor(): EditorSnapshot {
  const s = useEditorStore.getState();
  return {
    net: s.net,
    selection: s.selection,
    past: s.past,
    future: s.future,
    dirty: s.dirty,
    cloudNetId: s.cloudNetId,
  };
}

function restoreEditor(snapshot: EditorSnapshot): void {
  useEditorStore.setState({ ...snapshot, pendingArcSource: null, tool: "select" });
}

interface CanvasTabsState {
  tabs: CanvasTab[];
  activeId: string;
  /** Editor state of every canvas that is not currently active. */
  stash: Record<string, EditorSnapshot>;

  activateTab: (id: string) => void;
  /**
   * Open (or focus) the canvas of one object of the *active* canvas, so an
   * object built inside another object can be opened in turn.
   */
  openObjectTab: (objectId: string) => string | null;
  closeTab: (id: string) => void;
  /**
   * Write the active object canvas back through every canvas above it, up to
   * the net itself, as one undoable step on each. Returns false when there is
   * nothing to write back — the active canvas is the net, or its object is
   * gone from the canvas that owned it.
   */
  saveActiveObjectTab: () => boolean;
  /** Keep a canvas's label in step with the net name shown on it. */
  setTabTitle: (id: string, title: string) => void;
  /**
   * Back to the net alone. Object canvases are views into the loaded
   * document, so whenever a different document lands in the editor (route
   * load, file drop, New) the open tabs and their stashed snapshots describe
   * content that no longer exists and must go with it.
   */
  resetToRoot: () => void;
}

const MAIN_TAB: CanvasTab = { id: MAIN_TAB_ID, path: [MAIN_TAB_ID], title: "" };

// Deliberately NOT persisted. The editor store never survives a reload — the
// net is fetched fresh from the server — so a rehydrated activeId would point
// into canvases whose content no longer exists: the editor would show the
// root net on a tab labeled as an object's, and a Ctrl+S there would merge
// the whole net into a stale parent snapshot.
export const useCanvasTabsStore = create<CanvasTabsState>()(
    (set, get) => ({
      tabs: [MAIN_TAB],
      activeId: MAIN_TAB_ID,
      stash: {},

      activateTab: (id) => {
        const { activeId, stash, tabs } = get();
        if (id === activeId) return;
        const target = tabs.find((t) => t.id === id);
        const snapshot = stash[id];
        if (!target || !snapshot) return;

        const { [id]: _entering, ...rest } = stash;
        set({ stash: { ...rest, [activeId]: captureEditor() }, activeId: id });
        restoreEditor(snapshot);
      },

      openObjectTab: (objectId) => {
        const { activeId, tabs, stash } = get();
        const parent = tabs.find((t) => t.id === activeId);
        if (!parent) return null;

        const parentNet = useEditorStore.getState().net;
        const objects = getObjects(parentNet);
        if (!objects.some((o) => o.id === objectId)) return null;

        // The clicked object may be visible here only because its OWN
        // parent frame is itself nested inside this canvas's net (that
        // ancestor is expanded, so the object reads as directly clickable
        // even though it isn't one of this canvas's top-level members).
        // Every intervening ancestor needs its own tab in the chain, or the
        // level shown here is short by however many were skipped, and
        // saveActiveObjectTab's own walk back up has nowhere to merge an
        // intermediate ancestor's edit into.
        const chain: string[] = [];
        const seen = new Set<string>();
        for (let step: string | undefined = objectId; step !== undefined; ) {
          if (seen.has(step)) break; // a net that arrived with a parent cycle must not hang the walk
          seen.add(step);
          chain.unshift(step);
          step = objects.find((o) => o.id === step)?.objectId;
        }

        let parentTabId = activeId;
        let netForThisLevel = parentNet;
        let nextTabs = tabs;
        let nextStash = stash;
        let capturedActive = false;
        let finalId = activeId;

        for (const step of chain) {
          const stepParent = nextTabs.find((t) => t.id === parentTabId)!;
          const path = [...stepParent.path, step];
          const id = pathId(path);
          finalId = id;

          if (nextTabs.some((t) => t.id === id)) {
            // Already open from an earlier visit: descend from its own
            // current content (stashed, unless it happens to be the live
            // active tab) so the next step in the chain, if any, extracts
            // from the right document.
            netForThisLevel =
              id === activeId ? useEditorStore.getState().net : (nextStash[id]?.net ?? netForThisLevel);
            parentTabId = id;
            continue;
          }

          const objectNet = extractObjectNet(netForThisLevel, step);
          if (!objectNet) return null;
          const externalConnections = Object.fromEntries(
            computeExternalConnections(netForThisLevel, step),
          );

          if (!capturedActive) {
            // The real active tab's live editor state is captured exactly
            // once, same as a single-level open always did.
            nextStash = { ...nextStash, [activeId]: captureEditor() };
            capturedActive = true;
          }
          nextStash = {
            ...nextStash,
            [id]: { net: objectNet, selection: [], past: [], future: [], dirty: false, cloudNetId: null },
          };
          nextTabs = [...nextTabs, { id, path, title: objectNet.name, externalConnections }];

          netForThisLevel = objectNet;
          parentTabId = id;
        }

        set({ tabs: nextTabs, stash: nextStash, activeId: finalId });
        restoreEditor(nextStash[finalId]!);
        return finalId;
      },

      closeTab: (id) => {
        const { tabs, stash, activeId } = get();
        const tab = tabs.find((t) => t.id === id);
        if (!tab || tab.path.length === 1) return;

        // Closing a canvas closes everything opened from inside it.
        const closing = new Set(
          tabs.filter((t) => t.id === id || t.id.startsWith(`${id}/`)).map((t) => t.id),
        );
        const remaining = tabs.filter((t) => !closing.has(t.id));
        const restStash = Object.fromEntries(
          Object.entries(stash).filter(([key]) => !closing.has(key)),
        );

        if (!closing.has(activeId)) {
          set({ tabs: remaining, stash: restStash });
          return;
        }

        const fallbackId = parentIdOf(tab) ?? MAIN_TAB_ID;
        const fallback = restStash[fallbackId];
        if (!fallback) return;
        const { [fallbackId]: _restored, ...stashWithoutFallback } = restStash;
        set({ tabs: remaining, stash: stashWithoutFallback, activeId: fallbackId });
        restoreEditor(fallback);
      },

      saveActiveObjectTab: () => {
        const { tabs, activeId } = get();
        const active = tabs.find((t) => t.id === activeId);
        if (!active || active.path.length === 1) return false;

        // Walk up the chain: an object canvas is a view into its parent, so a
        // save only means something once it has reached the net itself.
        let net = useEditorStore.getState().net;
        let tab = active;
        const stash = { ...get().stash };

        while (tab.path.length > 1) {
          const objectId = objectIdOf(tab)!;
          const parentId = parentIdOf(tab)!;
          const parentSnapshot = stash[parentId];
          if (!parentSnapshot) return false;
          if (!getObjects(parentSnapshot.net).some((o) => o.id === objectId)) return false;

          const merged = applyObjectEdit(parentSnapshot.net, objectId, net);
          stash[parentId] = {
            ...parentSnapshot,
            net: merged,
            past: [...parentSnapshot.past, parentSnapshot.net].slice(-MAX_HISTORY),
            future: [],
            dirty: true,
            selection: [],
          };

          net = merged;
          const parentTab = tabs.find((t) => t.id === parentId);
          if (!parentTab) return false;
          tab = parentTab;
        }

        set({
          stash,
          tabs: tabs.map((t) =>
            t.id === activeId ? { ...t, title: useEditorStore.getState().net.name } : t,
          ),
        });
        useEditorStore.setState({ dirty: false });
        return true;
      },

      setTabTitle: (id, title) =>
        set((s) =>
          s.tabs.some((t) => t.id === id && t.title !== title)
            ? { tabs: s.tabs.map((t) => (t.id === id ? { ...t, title } : t)) }
            : s,
        ),

      resetToRoot: () => set({ tabs: [MAIN_TAB], activeId: MAIN_TAB_ID, stash: {} }),
    }),
);

// The store used to persist under this key; the stale entry would otherwise
// sit in localStorage forever.
try {
  localStorage.removeItem("petri-canvas-tabs");
} catch {
  // Storage may be unavailable (SSR, privacy mode); nothing to clean then.
}
