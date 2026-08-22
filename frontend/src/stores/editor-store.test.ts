import { describe, expect, it, beforeEach } from "vitest";
import { useEditorStore } from "./editor-store";

function resetStore() {
  useEditorStore.getState().resetNet();
}

describe("editor-store undo/redo", () => {
  beforeEach(resetStore);

  it("has empty history on start", () => {
    const s = useEditorStore.getState();
    expect(s.past).toHaveLength(0);
    expect(s.future).toHaveLength(0);
  });

  it("pushes to history on addPlace", () => {
    useEditorStore.getState().addPlace(10, 20);
    const s = useEditorStore.getState();
    expect(s.past).toHaveLength(1);
    expect(s.net.places).toHaveLength(1);
  });

  it("undo restores previous state", () => {
    useEditorStore.getState().addPlace(10, 20);
    useEditorStore.getState().addTransition(30, 40);
    expect(useEditorStore.getState().net.transitions).toHaveLength(1);

    useEditorStore.getState().undo();
    expect(useEditorStore.getState().net.transitions).toHaveLength(0);
    expect(useEditorStore.getState().net.places).toHaveLength(1);
  });

  it("redo restores undone state", () => {
    useEditorStore.getState().addPlace(10, 20);
    useEditorStore.getState().addTransition(30, 40);
    useEditorStore.getState().undo();
    expect(useEditorStore.getState().net.transitions).toHaveLength(0);

    useEditorStore.getState().redo();
    expect(useEditorStore.getState().net.transitions).toHaveLength(1);
  });

  it("new mutation clears future", () => {
    useEditorStore.getState().addPlace(10, 20);
    useEditorStore.getState().addPlace(30, 40);
    useEditorStore.getState().undo();
    expect(useEditorStore.getState().future).toHaveLength(1);

    useEditorStore.getState().addTransition(50, 60);
    expect(useEditorStore.getState().future).toHaveLength(0);
  });

  it("undo is no-op when past is empty", () => {
    const before = useEditorStore.getState().net;
    useEditorStore.getState().undo();
    expect(useEditorStore.getState().net).toBe(before);
  });

  it("redo is no-op when future is empty", () => {
    useEditorStore.getState().addPlace(10, 20);
    const before = useEditorStore.getState().net;
    useEditorStore.getState().redo();
    expect(useEditorStore.getState().net).toBe(before);
  });

  it("round-trips through 20 steps of undo-all then redo-all", () => {
    for (let i = 0; i < 10; i++) {
      useEditorStore.getState().addPlace(i * 10, 0);
    }
    for (let i = 0; i < 10; i++) {
      useEditorStore.getState().addTransition(i * 10, 50);
    }
    const finalNet = useEditorStore.getState().net;
    expect(finalNet.places).toHaveLength(10);
    expect(finalNet.transitions).toHaveLength(10);

    for (let i = 0; i < 20; i++) {
      useEditorStore.getState().undo();
    }
    expect(useEditorStore.getState().net.places).toHaveLength(0);
    expect(useEditorStore.getState().net.transitions).toHaveLength(0);

    for (let i = 0; i < 20; i++) {
      useEditorStore.getState().redo();
    }
    const restored = useEditorStore.getState().net;
    expect(restored.places).toHaveLength(10);
    expect(restored.transitions).toHaveLength(10);
    expect(restored.places.map((p) => p.id)).toEqual(
      finalNet.places.map((p) => p.id),
    );
    expect(restored.transitions.map((t) => t.id)).toEqual(
      finalNet.transitions.map((t) => t.id),
    );
  });

  it("tracks undo for updatePlace", () => {
    useEditorStore.getState().addPlace(10, 20);
    const placeId = useEditorStore.getState().net.places[0].id;
    useEditorStore.getState().updatePlace(placeId, { tokens: 5 });
    expect(useEditorStore.getState().net.places[0].tokens).toBe(5);

    useEditorStore.getState().undo();
    expect(useEditorStore.getState().net.places[0].tokens).toBe(0);
  });

  it("tracks undo for deleteSelection", () => {
    useEditorStore.getState().addPlace(10, 20);
    const placeId = useEditorStore.getState().net.places[0].id;
    useEditorStore.getState().setSelection([{ id: placeId, kind: "place" }]);
    useEditorStore.getState().deleteSelection();
    expect(useEditorStore.getState().net.places).toHaveLength(0);

    useEditorStore.getState().undo();
    expect(useEditorStore.getState().net.places).toHaveLength(1);
  });

  it("tracks undo for renameNet", () => {
    const originalName = useEditorStore.getState().net.name;
    useEditorStore.getState().renameNet("New Name");
    expect(useEditorStore.getState().net.name).toBe("New Name");

    useEditorStore.getState().undo();
    expect(useEditorStore.getState().net.name).toBe(originalName);
  });
});

describe("editor-store clipboard", () => {
  beforeEach(resetStore);

  it("copySelection captures places and transitions", () => {
    useEditorStore.getState().addPlace(10, 20);
    useEditorStore.getState().addTransition(30, 40);
    useEditorStore.getState().selectAll();
    useEditorStore.getState().copySelection();

    const clip = useEditorStore.getState().clipboard;
    expect(clip).not.toBeNull();
    expect(clip!.places).toHaveLength(1);
    expect(clip!.transitions).toHaveLength(1);
  });

  it("paste creates new elements with offset", () => {
    useEditorStore.getState().addPlace(100, 200);
    const origId = useEditorStore.getState().net.places[0].id;
    useEditorStore.getState().selectAll();
    useEditorStore.getState().copySelection();
    useEditorStore.getState().paste();

    const s = useEditorStore.getState();
    expect(s.net.places).toHaveLength(2);
    const pasted = s.net.places.find((p) => p.id !== origId)!;
    expect(pasted.graphics.x).toBe(120);
    expect(pasted.graphics.y).toBe(220);
  });

  it("paste preserves arcs between copied nodes", () => {
    const pid = useEditorStore.getState().addPlace(10, 20);
    const tid = useEditorStore.getState().addTransition(30, 40);
    useEditorStore.getState().addArc(pid, tid);
    expect(useEditorStore.getState().net.arcs).toHaveLength(1);

    useEditorStore.getState().selectAll();
    useEditorStore.getState().copySelection();
    useEditorStore.getState().paste();

    expect(useEditorStore.getState().net.arcs).toHaveLength(2);
  });

  it("cutSelection removes originals", () => {
    useEditorStore.getState().addPlace(10, 20);
    useEditorStore.getState().selectAll();
    useEditorStore.getState().cutSelection();

    expect(useEditorStore.getState().net.places).toHaveLength(0);
    expect(useEditorStore.getState().clipboard).not.toBeNull();
  });

  it("paste is undoable", () => {
    useEditorStore.getState().addPlace(10, 20);
    useEditorStore.getState().selectAll();
    useEditorStore.getState().copySelection();
    useEditorStore.getState().paste();
    expect(useEditorStore.getState().net.places).toHaveLength(2);

    useEditorStore.getState().undo();
    expect(useEditorStore.getState().net.places).toHaveLength(1);
  });
});

describe("editor-store selectAll", () => {
  beforeEach(resetStore);

  it("selects all elements", () => {
    useEditorStore.getState().addPlace(10, 20);
    useEditorStore.getState().addTransition(30, 40);
    const pid = useEditorStore.getState().net.places[0].id;
    const tid = useEditorStore.getState().net.transitions[0].id;
    useEditorStore.getState().addArc(pid, tid);

    useEditorStore.getState().selectAll();
    expect(useEditorStore.getState().selection).toHaveLength(3);
  });
});
