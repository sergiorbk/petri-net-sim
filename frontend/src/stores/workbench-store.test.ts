import { beforeEach, describe, expect, it } from "vitest";
import { useWorkbenchStore } from "./workbench-store";

describe("workbench-store reducer", () => {
  beforeEach(() => {
    useWorkbenchStore.getState().endLiveBuild();
    useWorkbenchStore.getState().beginLiveBuild();
  });

  it("adds a place", () => {
    useWorkbenchStore.getState().applyToolEvent("s1", "add_place", {
      id: "p1",
      name: "Queue",
      tokens: 3,
    });
    const draft = useWorkbenchStore.getState().liveDraft!;
    expect(draft.places).toHaveLength(1);
    expect(draft.places[0]).toMatchObject({ id: "p1", name: "Queue", tokens: 3 });
  });

  it("adds a transition with defaults", () => {
    useWorkbenchStore.getState().applyToolEvent("s1", "add_transition", { id: "t1" });
    const draft = useWorkbenchStore.getState().liveDraft!;
    expect(draft.transitions).toHaveLength(1);
    expect(draft.transitions[0]).toMatchObject({ id: "t1", name: "t1", priority: 0 });
  });

  it("adds an arc with explicit source/target", () => {
    const s = useWorkbenchStore.getState();
    s.applyToolEvent("s1", "add_place", { id: "p1" });
    s.applyToolEvent("s2", "add_transition", { id: "t1" });
    s.applyToolEvent("s3", "add_arc", {
      id: "a1",
      source_id: "p1",
      target_id: "t1",
      weight: 2,
    });
    const draft = useWorkbenchStore.getState().liveDraft!;
    expect(draft.arcs).toHaveLength(1);
    expect(draft.arcs[0]).toMatchObject({
      id: "a1",
      source_id: "p1",
      target_id: "t1",
      weight: 2,
      arc_type: "NORMAL",
    });
  });

  it("ignores unknown tool names", () => {
    useWorkbenchStore.getState().applyToolEvent("s1", "run_simulation", { steps: 100 });
    // A non-mutating tool must not activate the live build overlay: the
    // draft only comes into existence on the first net-mutating tool.
    expect(useWorkbenchStore.getState().liveDraft).toBeNull();
    expect(useWorkbenchStore.getState().appliedStepIds).toHaveProperty("s1");
  });

  it("is idempotent across re-applied step ids", () => {
    const s = useWorkbenchStore.getState();
    s.applyToolEvent("s1", "add_place", { id: "p1" });
    s.applyToolEvent("s1", "add_place", { id: "p2" });
    expect(useWorkbenchStore.getState().liveDraft!.places).toHaveLength(1);
  });

  it("drops malformed events", () => {
    const s = useWorkbenchStore.getState();
    s.applyToolEvent("s1", "add_place", {});
    s.applyToolEvent("s2", "add_arc", { source_id: "p1" });
    const draft = useWorkbenchStore.getState().liveDraft!;
    expect(draft.places).toHaveLength(0);
    expect(draft.arcs).toHaveLength(0);
  });

  it("endLiveBuild clears draft", () => {
    useWorkbenchStore.getState().applyToolEvent("s1", "add_place", { id: "p1" });
    useWorkbenchStore.getState().endLiveBuild();
    expect(useWorkbenchStore.getState().liveDraft).toBeNull();
  });
});
