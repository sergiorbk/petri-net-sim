import { describe, expect, it, beforeEach } from "vitest";
import { useEditorStore } from "./editor-store";
import { canvasLevel, MAIN_TAB_ID, useCanvasTabsStore } from "./canvas-tabs-store";

function reset() {
  useCanvasTabsStore.setState({
    tabs: [{ id: MAIN_TAB_ID, path: [MAIN_TAB_ID], title: "" }],
    activeId: MAIN_TAB_ID,
    stash: {},
  });
  useEditorStore.getState().resetNet();
}

/** A canvas holding one object built from a single place. */
function canvasWithObject(): { objectId: string; placeId: string } {
  const placeId = useEditorStore.getState().addPlace(100, 100);
  useEditorStore.getState().setSelection([{ id: placeId, kind: "place" }]);
  const objectId = useEditorStore.getState().groupSelectionIntoObject("Widget")!;
  return { objectId, placeId };
}

describe("canvas-tabs-store", () => {
  beforeEach(reset);

  it("opens an object on its own canvas showing only that object's contents", () => {
    const { objectId, placeId } = canvasWithObject();

    const tabId = useCanvasTabsStore.getState().openObjectTab(objectId);

    expect(tabId).toBeTruthy();
    expect(useCanvasTabsStore.getState().activeId).toBe(tabId);
    const net = useEditorStore.getState().net;
    expect(net.name).toBe("Widget");
    expect(net.places.map((p) => p.id)).toEqual([placeId]);
    expect(net.places[0].objectId).toBeUndefined();
    expect(net.objects ?? []).toHaveLength(0);
  });

  it("keeps the parent canvas intact while its object is open", () => {
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);

    const stashed = useCanvasTabsStore.getState().stash[MAIN_TAB_ID];
    expect(stashed.net.objects).toHaveLength(1);
    expect(stashed.net.places[0].objectId).toBe(objectId);
  });

  it("focuses the existing canvas instead of opening a second one", () => {
    const { objectId } = canvasWithObject();
    const first = useCanvasTabsStore.getState().openObjectTab(objectId);
    useCanvasTabsStore.getState().activateTab(MAIN_TAB_ID);
    const second = useCanvasTabsStore.getState().openObjectTab(objectId);

    expect(second).toBe(first);
    expect(useCanvasTabsStore.getState().tabs).toHaveLength(2);
  });

  it("refuses to open an object that is not on the canvas", () => {
    canvasWithObject();
    expect(useCanvasTabsStore.getState().openObjectTab("nope")).toBeNull();
    expect(useCanvasTabsStore.getState().tabs).toHaveLength(1);
  });

  it("writes edits back into the frame on the parent canvas", () => {
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);

    useEditorStore.getState().addTransition(200, 100);
    expect(useCanvasTabsStore.getState().saveActiveObjectTab()).toBe(true);

    useCanvasTabsStore.getState().activateTab(MAIN_TAB_ID);
    const net = useEditorStore.getState().net;
    expect(net.transitions).toHaveLength(1);
    expect(net.transitions[0].objectId).toBe(objectId);
    expect(net.places[0].objectId).toBe(objectId);
    expect(net.objects).toHaveLength(1);
  });

  it("makes the write-back one undoable step on the parent canvas", () => {
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);
    useEditorStore.getState().addTransition(200, 100);
    useCanvasTabsStore.getState().saveActiveObjectTab();
    useCanvasTabsStore.getState().activateTab(MAIN_TAB_ID);

    expect(useEditorStore.getState().canUndo()).toBe(true);
    useEditorStore.getState().undo();
    expect(useEditorStore.getState().net.transitions).toHaveLength(0);
  });

  it("clears the object canvas's dirty flag once written back", () => {
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);
    useEditorStore.getState().addTransition(200, 100);
    expect(useEditorStore.getState().dirty).toBe(true);

    useCanvasTabsStore.getState().saveActiveObjectTab();
    expect(useEditorStore.getState().dirty).toBe(false);
  });

  it("refuses to write back an object the parent canvas no longer has", () => {
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);

    // Simulate the frame being ungrouped on the parent while its canvas is open.
    const stash = useCanvasTabsStore.getState().stash;
    useCanvasTabsStore.setState({
      stash: {
        ...stash,
        [MAIN_TAB_ID]: { ...stash[MAIN_TAB_ID], net: { ...stash[MAIN_TAB_ID].net, objects: [] } },
      },
    });

    expect(useCanvasTabsStore.getState().saveActiveObjectTab()).toBe(false);
  });

  it("returns to the parent canvas when an object canvas is closed", () => {
    const { objectId, placeId } = canvasWithObject();
    const tabId = useCanvasTabsStore.getState().openObjectTab(objectId)!;

    useCanvasTabsStore.getState().closeTab(tabId);

    expect(useCanvasTabsStore.getState().activeId).toBe(MAIN_TAB_ID);
    expect(useCanvasTabsStore.getState().tabs).toHaveLength(1);
    const net = useEditorStore.getState().net;
    expect(net.objects).toHaveLength(1);
    expect(net.places.find((p) => p.id === placeId)!.objectId).toBe(objectId);
  });

  it("never closes the canvas of the net itself", () => {
    useCanvasTabsStore.getState().closeTab(MAIN_TAB_ID);
    expect(useCanvasTabsStore.getState().tabs).toHaveLength(1);
    expect(useCanvasTabsStore.getState().activeId).toBe(MAIN_TAB_ID);
  });

  it("resetToRoot drops every open canvas and stashed snapshot", () => {
    // A new document entering the editor makes the open tabs views into
    // content that no longer exists; carrying them over is how a Ctrl+S on a
    // phantom object tab merges the new net into a stale parent snapshot.
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);
    expect(useCanvasTabsStore.getState().tabs.length).toBeGreaterThan(1);

    useCanvasTabsStore.getState().resetToRoot();

    const state = useCanvasTabsStore.getState();
    expect(state.tabs).toHaveLength(1);
    expect(state.activeId).toBe(MAIN_TAB_ID);
    expect(state.stash).toEqual({});
  });

  it("discards an object canvas's unsaved edits when it is closed", () => {
    const { objectId } = canvasWithObject();
    const tabId = useCanvasTabsStore.getState().openObjectTab(objectId)!;
    useEditorStore.getState().addTransition(200, 100);

    useCanvasTabsStore.getState().closeTab(tabId);

    expect(useEditorStore.getState().net.transitions).toHaveLength(0);
  });
});

describe("canvas-tabs-store nesting", () => {
  beforeEach(reset);

  it("opens an object built inside another object, one level deeper", () => {
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);

    // Build a second object on the object's own canvas.
    const inner = useEditorStore.getState().addPlace(400, 100);
    useEditorStore.getState().setSelection([{ id: inner, kind: "place" }]);
    const innerId = useEditorStore.getState().groupSelectionIntoObject("Inner")!;

    const innerTab = useCanvasTabsStore.getState().openObjectTab(innerId);

    expect(innerTab).toBeTruthy();
    const tab = useCanvasTabsStore.getState().tabs.find((t) => t.id === innerTab)!;
    expect(canvasLevel(tab)).toBe(2);
    expect(useEditorStore.getState().net.name).toBe("Inner");
  });

  it("carries a nested object all the way back to the net", () => {
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);
    const inner = useEditorStore.getState().addPlace(400, 100);
    useEditorStore.getState().setSelection([{ id: inner, kind: "place" }]);
    const innerId = useEditorStore.getState().groupSelectionIntoObject("Inner")!;

    expect(useCanvasTabsStore.getState().saveActiveObjectTab()).toBe(true);
    useCanvasTabsStore.getState().activateTab(MAIN_TAB_ID);

    const net = useEditorStore.getState().net;
    const nested = net.objects!.find((o) => o.id === innerId)!;
    expect(nested).toBeDefined();
    expect(nested.objectId).toBe(objectId); // level 2: inside the outer object
    expect(net.objects).toHaveLength(2);
  });

  it("saving a level-2 canvas reaches the net through its parent", () => {
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);
    const inner = useEditorStore.getState().addPlace(400, 100);
    useEditorStore.getState().setSelection([{ id: inner, kind: "place" }]);
    const innerId = useEditorStore.getState().groupSelectionIntoObject("Inner")!;
    useCanvasTabsStore.getState().saveActiveObjectTab();
    useCanvasTabsStore.getState().openObjectTab(innerId);

    // A transition added two levels down must land in the net itself.
    const deep = useEditorStore.getState().addTransition(420, 160);
    expect(useCanvasTabsStore.getState().saveActiveObjectTab()).toBe(true);
    useCanvasTabsStore.getState().activateTab(MAIN_TAB_ID);

    const net = useEditorStore.getState().net;
    expect(net.transitions.find((t) => t.id === deep)!.objectId).toBe(innerId);
  });

  it("opens a doubly-nested object directly from the net, synthesizing the skipped intermediate canvas", () => {
    // The inner object is visible directly on "main" once its own parent is
    // expanded there, and opening it must not require visiting the parent's
    // own canvas first, and the level shown must still reflect its true
    // depth (2), not just one more than whatever canvas it was opened from.
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);
    const inner = useEditorStore.getState().addPlace(400, 100);
    useEditorStore.getState().setSelection([{ id: inner, kind: "place" }]);
    const innerId = useEditorStore.getState().groupSelectionIntoObject("Inner")!;
    useCanvasTabsStore.getState().saveActiveObjectTab();
    useCanvasTabsStore.getState().activateTab(MAIN_TAB_ID);

    const innerTab = useCanvasTabsStore.getState().openObjectTab(innerId);

    expect(innerTab).toBeTruthy();
    const tabs = useCanvasTabsStore.getState().tabs;
    const tab = tabs.find((t) => t.id === innerTab)!;
    expect(canvasLevel(tab)).toBe(2);
    expect(useEditorStore.getState().net.name).toBe("Inner");

    // The skipped level-1 canvas (the outer object's own) exists too, as a
    // real tab with its own stash, not just implied by the path string.
    const intermediate = tabs.find((t) => canvasLevel(t) === 1);
    expect(intermediate).toBeDefined();
    expect(intermediate!.path).toEqual([MAIN_TAB_ID, objectId]);
    expect(useCanvasTabsStore.getState().stash[intermediate!.id]).toBeDefined();
    expect(tabs).toHaveLength(3);
  });

  it("writes back from a directly-opened doubly-nested canvas through the synthesized intermediate tab", () => {
    const { objectId } = canvasWithObject();
    useCanvasTabsStore.getState().openObjectTab(objectId);
    const inner = useEditorStore.getState().addPlace(400, 100);
    useEditorStore.getState().setSelection([{ id: inner, kind: "place" }]);
    const innerId = useEditorStore.getState().groupSelectionIntoObject("Inner")!;
    useCanvasTabsStore.getState().saveActiveObjectTab();
    useCanvasTabsStore.getState().activateTab(MAIN_TAB_ID);
    useCanvasTabsStore.getState().openObjectTab(innerId);

    const deep = useEditorStore.getState().addTransition(420, 160);
    expect(useCanvasTabsStore.getState().saveActiveObjectTab()).toBe(true);
    useCanvasTabsStore.getState().activateTab(MAIN_TAB_ID);

    const net = useEditorStore.getState().net;
    expect(net.transitions.find((t) => t.id === deep)!.objectId).toBe(innerId);
  });

  it("closing a canvas closes the canvases opened from inside it", () => {
    const { objectId } = canvasWithObject();
    const outerTab = useCanvasTabsStore.getState().openObjectTab(objectId)!;
    const inner = useEditorStore.getState().addPlace(400, 100);
    useEditorStore.getState().setSelection([{ id: inner, kind: "place" }]);
    const innerId = useEditorStore.getState().groupSelectionIntoObject("Inner")!;
    useCanvasTabsStore.getState().saveActiveObjectTab();
    useCanvasTabsStore.getState().openObjectTab(innerId);

    useCanvasTabsStore.getState().closeTab(outerTab);

    expect(useCanvasTabsStore.getState().tabs).toHaveLength(1);
    expect(useCanvasTabsStore.getState().activeId).toBe(MAIN_TAB_ID);
  });
});
