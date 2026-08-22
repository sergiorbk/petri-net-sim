import { describe, expect, it } from "vitest";
import type { PetriNetData } from "@/types/petri";
import { applyObjectEdit, computeExternalConnections, extractObjectNet } from "./petri-object-editing";

function place(id: string, x = 0, y = 0, objectId?: string) {
  return { id, name: id, tokens: 0, graphics: { x, y }, ...(objectId ? { objectId } : {}) };
}

function transition(id: string, x = 0, y = 0, objectId?: string) {
  return {
    id,
    name: id,
    priority: 1,
    distribution: "exp" as const,
    mean_delay: 1,
    standard_deviation: 0,
    probability: null,
    graphics: { x, y },
    ...(objectId ? { objectId } : {}),
  };
}

function arc(id: string, source_id: string, target_id: string) {
  return { id, source_id, target_id, weight: 1, arc_type: "NORMAL" as const };
}

/** A canvas with one object (p1 → t1) and one free place wired into it. */
function netWithObject(): PetriNetData {
  return {
    name: "Net",
    places: [place("p1", 100, 100, "o1"), place("outside", 400, 100)],
    transitions: [transition("t1", 200, 100, "o1")],
    arcs: [arc("a1", "p1", "t1"), arc("a2", "t1", "outside")],
    objects: [
      { id: "o1", name: "Object", priority: 0, graphics: { x: 60, y: 40, width: 240, height: 180 } },
    ],
    links: [],
  };
}

describe("extractObjectNet", () => {
  it("returns only the object's members and their internal arcs", () => {
    const sub = extractObjectNet(netWithObject(), "o1")!;
    expect(sub.name).toBe("Object");
    expect(sub.places.map((p) => p.id)).toEqual(["p1"]);
    expect(sub.transitions.map((t) => t.id)).toEqual(["t1"]);
    // a2 leaves the object, so it is not part of its contents.
    expect(sub.arcs.map((a) => a.id)).toEqual(["a1"]);
  });

  it("strips membership so the sub-net reads as an ordinary flat net", () => {
    const sub = extractObjectNet(netWithObject(), "o1")!;
    expect(sub.places[0].objectId).toBeUndefined();
    expect(sub.transitions[0].objectId).toBeUndefined();
  });

  it("returns null for an unknown object", () => {
    expect(extractObjectNet(netWithObject(), "nope")).toBeNull();
  });
});

describe("computeExternalConnections", () => {
  it("names what a member connects to outside the object, keyed by its own id", () => {
    const result = computeExternalConnections(netWithObject(), "o1");
    // p1's own arc (a1) stays inside the object, so it has no entry at all.
    expect(result.has("p1")).toBe(false);
    expect(result.get("t1")).toEqual(["outside"]);
  });

  it("collects multiple external connections for the same member", () => {
    const net = netWithObject();
    net.places.push({ id: "outside2", name: "outside2", tokens: 0, graphics: { x: 500, y: 100 } });
    net.arcs.push(arc("a3", "outside2", "t1"));

    const result = computeExternalConnections(net, "o1");
    expect(result.get("t1")!.sort()).toEqual(["outside", "outside2"]);
  });

  it("a link crossing the boundary counts the same as an arc", () => {
    const net = netWithObject();
    net.links = [
      { id: "link1", type: "placeFusion", sourceId: "p1", targetId: "outside", quantity: 1 },
    ];
    const result = computeExternalConnections(net, "o1");
    expect(result.get("p1")).toEqual(["outside"]);
  });

  it("an arc wholly inside the object produces no entries", () => {
    const net: PetriNetData = {
      name: "n",
      places: [place("p1", 0, 0, "o1")],
      transitions: [transition("t1", 0, 0, "o1")],
      arcs: [arc("a1", "p1", "t1")],
      objects: [{ id: "o1", name: "o", priority: 0, graphics: { x: 0, y: 0, width: 100, height: 100 } }],
      links: [],
    };
    expect(computeExternalConnections(net, "o1").size).toBe(0);
  });

  it("reaches a nested child's members too, not just the object's own direct ones", () => {
    const net: PetriNetData = {
      name: "n",
      places: [place("p1", 0, 0, "inner"), place("outside", 400, 0)],
      transitions: [],
      arcs: [arc("a1", "p1", "outside")],
      objects: [
        { id: "outer", name: "Outer", priority: 0, graphics: { x: 0, y: 0, width: 300, height: 300 } },
        { id: "inner", name: "Inner", priority: 0, graphics: { x: 20, y: 20, width: 100, height: 100 }, objectId: "outer" },
      ],
      links: [],
    };
    expect(computeExternalConnections(net, "outer").get("p1")).toEqual(["outside"]);
  });
});

describe("applyObjectEdit", () => {
  it("round-trips an untouched object without changing membership", () => {
    const parent = netWithObject();
    const merged = applyObjectEdit(parent, "o1", extractObjectNet(parent, "o1")!);

    expect(merged.places.map((p) => p.id).sort()).toEqual(["outside", "p1"]);
    expect(merged.places.find((p) => p.id === "p1")!.objectId).toBe("o1");
    expect(merged.places.find((p) => p.id === "outside")!.objectId).toBeUndefined();
    expect(merged.arcs.map((a) => a.id).sort()).toEqual(["a1", "a2"]);
  });

  it("adds elements created inside the object as members", () => {
    const parent = netWithObject();
    const edited = extractObjectNet(parent, "o1")!;
    edited.places.push(place("p9", 260, 100));
    edited.arcs.push(arc("a9", "t1", "p9"));

    const merged = applyObjectEdit(parent, "o1", edited);
    expect(merged.places.find((p) => p.id === "p9")!.objectId).toBe("o1");
    expect(merged.arcs.map((a) => a.id)).toContain("a9");
  });

  it("drops outside connections left dangling by a deletion inside the object", () => {
    const parent = netWithObject();
    const edited = extractObjectNet(parent, "o1")!;
    // Delete t1, which the outside place was connected to through a2.
    edited.transitions = [];
    edited.arcs = [];

    const merged = applyObjectEdit(parent, "o1", edited);
    expect(merged.transitions).toHaveLength(0);
    expect(merged.arcs.map((a) => a.id)).toEqual([]);
    expect(merged.places.map((p) => p.id).sort()).toEqual(["outside", "p1"]);
  });

  it("drops cross-object links whose endpoint the edit removed", () => {
    const parent = netWithObject();
    parent.links = [
      { id: "link1", type: "placeToTransition", sourceId: "outside", targetId: "t1", quantity: 1 },
    ];
    const edited = extractObjectNet(parent, "o1")!;
    edited.transitions = [];
    edited.arcs = [];

    expect(applyObjectEdit(parent, "o1", edited).links).toEqual([]);
  });

  it("renames an id minted inside the object that collides with one outside it", () => {
    const parent = netWithObject();
    const edited = extractObjectNet(parent, "o1")!;
    // The object editor numbers ids against the sub-net alone, so it can mint
    // an id the parent canvas already uses for a different element.
    edited.places.push(place("outside", 260, 100));
    edited.arcs.push(arc("a9", "t1", "outside"));

    const merged = applyObjectEdit(parent, "o1", edited);
    const members = merged.places.filter((p) => p.objectId === "o1").map((p) => p.id);
    expect(members).toContain("outside_2");
    expect(members).not.toContain("outside");
    // The free place keeps its identity, and the new arc follows the rename.
    expect(merged.places.find((p) => p.id === "outside")!.objectId).toBeUndefined();
    expect(merged.arcs.find((a) => a.id === "a9")!.target_id).toBe("outside_2");
  });

  it("re-fits the frame around the edited contents", () => {
    const parent = netWithObject();
    const edited = extractObjectNet(parent, "o1")!;
    edited.places = [place("p1", 1000, 1000)];
    edited.transitions = [];
    edited.arcs = [];

    const frame = applyObjectEdit(parent, "o1", edited).objects![0];
    expect(frame.graphics.x).toBeLessThan(1000);
    expect(frame.graphics.x).toBeGreaterThan(900);
    expect(frame.graphics.y).toBeLessThan(1000);
  });

  it("adopts a rename made on the object's own canvas", () => {
    const parent = netWithObject();
    const edited = { ...extractObjectNet(parent, "o1")!, name: "Renamed" };
    expect(applyObjectEdit(parent, "o1", edited).objects![0].name).toBe("Renamed");
  });
});
