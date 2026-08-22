import { describe, expect, it } from "vitest";
import { buildGraph } from "./EditorCanvas";
import type { PetriNetData } from "@/types/petri";

/**
 * buildGraph is the single graph-building implementation shared by the main
 * editor canvas and the read-only chat-workbench preview (ReadOnlyCanvas.tsx)
 * — a composed net's object frames used to render fine on the editor canvas
 * but silently vanish on a second, older read-only implementation that never
 * registered an "objectFrame" node type at all. This pins that a composed
 * net always produces a frame node for every object, regardless of caller.
 */
describe("buildGraph", () => {
  function composedNet(): PetriNetData {
    return {
      name: "composed",
      places: [
        { id: "p1", name: "P1", tokens: 1, graphics: { x: 0, y: 0 }, objectId: "obj1" },
        { id: "p2", name: "P2", tokens: 0, graphics: { x: 200, y: 0 }, objectId: "obj1" },
      ],
      transitions: [
        {
          id: "t1",
          name: "T1",
          priority: 0,
          distribution: null,
          mean_delay: 0,
          standard_deviation: 0,
          probability: null,
          graphics: { x: 100, y: 0 },
          objectId: "obj1",
        },
      ],
      arcs: [
        { id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" },
        { id: "a2", source_id: "t1", target_id: "p2", weight: 1, arc_type: "NORMAL" },
      ],
      objects: [
        {
          id: "obj1",
          name: "Object 1",
          priority: 0,
          graphics: { x: -30, y: -30, width: 300, height: 150 },
        },
      ],
    };
  }

  it("renders an objectFrame node for every object in a composed net", () => {
    const { nodes } = buildGraph(composedNet(), new Set(), null);
    const frameNodes = nodes.filter((n) => n.type === "objectFrame");
    expect(frameNodes.map((n) => n.id)).toEqual(["obj1"]);
  });

  it("carries the object's own graphics bounds onto the frame node, no reflow to fit a container", () => {
    const { nodes } = buildGraph(composedNet(), new Set(), null);
    const frame = nodes.find((n) => n.type === "objectFrame")!;
    expect(frame.position).toEqual({ x: -30, y: -30 });
    expect(frame.width).toBe(300);
    expect(frame.height).toBe(150);
  });

  it("nests member places/transitions under their frame via parentId", () => {
    const { nodes } = buildGraph(composedNet(), new Set(), null);
    const p1 = nodes.find((n) => n.id === "p1")!;
    const t1 = nodes.find((n) => n.id === "t1")!;
    expect(p1.parentId).toBe("obj1");
    expect(t1.parentId).toBe("obj1");
  });
});
