import { describe, expect, it } from "vitest";
import type { ObjectLink, PetriNetData, SimulationSnapshot } from "@/types/petri";
import { isComposedNet, projectForSimulation } from "./petri-composed";

function place(id: string, tokens = 0, objectId?: string) {
  return { id, name: id, tokens, graphics: { x: 0, y: 0 }, ...(objectId ? { objectId } : {}) };
}

function transition(id: string, objectId?: string) {
  return {
    id,
    name: id,
    priority: 1,
    distribution: "exp" as const,
    mean_delay: 1,
    standard_deviation: 0,
    probability: null,
    graphics: { x: 0, y: 0 },
    ...(objectId ? { objectId } : {}),
  };
}

function arc(id: string, source_id: string, target_id: string, weight = 1) {
  return { id, source_id, target_id, weight, arc_type: "NORMAL" as const };
}

function snapshot(markings: Record<string, number>): SimulationSnapshot {
  return { current_time: 0, step_number: 0, markings, buffers: {}, progress: 0 };
}

/** Two objects: A is p1 → t1 → p2, B is p3 → t2. */
function twoObjects(links: ObjectLink[]): PetriNetData {
  return {
    name: "net",
    places: [place("p1", 1, "oA"), place("p2", 0, "oA"), place("p3", 0, "oB")],
    transitions: [transition("t1", "oA"), transition("t2", "oB")],
    arcs: [arc("a1", "p1", "t1"), arc("a2", "t1", "p2"), arc("a3", "p3", "t2")],
    objects: [
      { id: "oA", name: "A", priority: 0, graphics: { x: 0, y: 0, width: 10, height: 10 } },
      { id: "oB", name: "B", priority: 0, graphics: { x: 0, y: 0, width: 10, height: 10 } },
    ],
    links,
  };
}

describe("isComposedNet", () => {
  it("is false for a plain net", () => {
    expect(isComposedNet({ name: "n", places: [place("p1")], transitions: [], arcs: [] })).toBe(false);
  });

  it("is true once the net has objects or links", () => {
    expect(isComposedNet(twoObjects([]))).toBe(true);
  });
});

describe("projectForSimulation", () => {
  it("leaves a plain net exactly as it is", () => {
    const net: PetriNetData = { name: "n", places: [place("p1")], transitions: [], arcs: [] };
    const projection = projectForSimulation(net);
    expect(projection.composed).toBe(false);
    expect(projection.net).toBe(net);
  });

  it("drops the object frames, which carry no behaviour", () => {
    const projection = projectForSimulation(twoObjects([]));
    expect(projection.net.objects).toBeUndefined();
    expect(projection.net.links).toBeUndefined();
    expect(projection.net.places.every((p) => p.objectId === undefined)).toBe(true);
  });

  it("turns a directional link into an ordinary arc", () => {
    const projection = projectForSimulation(
      twoObjects([
        { id: "link1", type: "transitionToPlace", sourceId: "t1", targetId: "p3", quantity: 2 },
      ]),
    );
    const generated = projection.net.arcs.find((a) => a.source_id === "t1" && a.target_id === "p3");
    expect(generated).toBeDefined();
    expect(generated!.weight).toBe(2);
    expect(generated!.arc_type).toBe("NORMAL");
  });

  it("turns an informational link into a READ arc, which tests without consuming", () => {
    const projection = projectForSimulation(
      twoObjects([
        {
          id: "link1",
          type: "placeToTransition",
          sourceId: "p2",
          targetId: "t2",
          quantity: 1,
          informational: true,
        },
      ]),
    );
    const generated = projection.net.arcs.find((a) => a.source_id === "p2" && a.target_id === "t2");
    expect(generated!.arc_type).toBe("READ");
  });

  it("collapses a fusion group to one place and rewires everything onto it", () => {
    const projection = projectForSimulation(
      twoObjects([{ id: "link1", type: "placeFusion", sourceId: "p2", targetId: "p3", quantity: 1 }]),
    );

    // p2 and p3 are one place, so only one of them survives.
    const ids = projection.net.places.map((p) => p.id);
    expect(ids).toContain("p2");
    expect(ids).not.toContain("p3");
    // p3's arc to t2 now leaves the surviving place.
    expect(projection.net.arcs.find((a) => a.id === "a3")!.source_id).toBe("p2");
    // The fusion itself is not an arc.
    expect(projection.net.arcs.some((a) => a.id === "link1")).toBe(false);
  });

  it("follows fusion transitively", () => {
    const net = twoObjects([
      { id: "link1", type: "placeFusion", sourceId: "p1", targetId: "p2", quantity: 1 },
      { id: "link2", type: "placeFusion", sourceId: "p2", targetId: "p3", quantity: 1 },
    ]);
    const projection = projectForSimulation(net);
    expect(projection.net.places).toHaveLength(1);
  });

  it("keeps the largest initial marking in a group rather than discarding tokens", () => {
    const net = twoObjects([
      { id: "link1", type: "placeFusion", sourceId: "p2", targetId: "p3", quantity: 1 },
    ]);
    net.places = [place("p1", 1, "oA"), place("p2", 0, "oA"), place("p3", 5, "oB")];
    const projection = projectForSimulation(net);
    expect(projection.net.places.find((p) => p.id === "p2")!.tokens).toBe(5);
  });

  it("merges arcs that become duplicates once a group is collapsed", () => {
    const net = twoObjects([
      { id: "link1", type: "placeFusion", sourceId: "p2", targetId: "p3", quantity: 1 },
    ]);
    // Both fused places feed t2 — one place feeding it twice is one arc of weight 2.
    net.arcs = [arc("a1", "p2", "t2"), arc("a2", "p3", "t2")];
    const projection = projectForSimulation(net);
    const feeding = projection.net.arcs.filter((a) => a.target_id === "t2");
    expect(feeding).toHaveLength(1);
    expect(feeding[0].weight).toBe(2);
  });

  it("reports the group's marking on every place of the group", () => {
    const projection = projectForSimulation(
      twoObjects([{ id: "link1", type: "placeFusion", sourceId: "p2", targetId: "p3", quantity: 1 }]),
    );
    const expanded = projection.expandSnapshot(snapshot({ p1: 0, p2: 4 }));
    expect(expanded.markings.p2).toBe(4);
    expect(expanded.markings.p3).toBe(4);
    expect(expanded.markings.p1).toBe(0);
  });

  it("leaves a snapshot untouched when nothing was fused", () => {
    const projection = projectForSimulation(twoObjects([]));
    const input = snapshot({ p1: 1 });
    expect(projection.expandSnapshot(input).markings).toEqual({ p1: 1 });
  });
});
