import { describe, expect, it } from "vitest";
import type { ObjectFrame, ObjectLink, PetriNetData, PetriPlace, PetriTransition } from "@/types/petri";
import {
  allNames,
  findGroupConflicts,
  nextFreeName,
  renameConflict,
  renameInGroup,
  suggestedRenames,
} from "./petri-names";

const place = (id: string, name = id): PetriPlace => ({
  id,
  name,
  tokens: 0,
  graphics: { x: 0, y: 0 },
});

const transition = (id: string, name = id): PetriTransition => ({
  id,
  name,
  priority: 1,
  distribution: "exp",
  mean_delay: 1,
  standard_deviation: 0,
  probability: null,
  graphics: { x: 0, y: 0 },
});

const frame = (id: string, name = id): ObjectFrame => ({
  id,
  name,
  priority: 0,
  graphics: { x: 0, y: 0, width: 100, height: 100 },
});

const fusion = (id: string, sourceId: string, targetId: string): ObjectLink => ({
  id,
  type: "placeFusion",
  sourceId,
  targetId,
  quantity: 1,
});

const net = (parts: Partial<PetriNetData>): PetriNetData => ({
  name: "n",
  places: [],
  transitions: [],
  arcs: [],
  ...parts,
});

describe("nextFreeName", () => {
  it("returns the name itself when it is free", () => {
    expect(nextFreeName("Queue", new Set(["Other"]))).toBe("Queue");
  });

  it("appends _2 first, then counts up", () => {
    expect(nextFreeName("Queue", new Set(["Queue"]))).toBe("Queue_2");
    expect(nextFreeName("Queue", new Set(["Queue", "Queue_2", "Queue_3"]))).toBe("Queue_4");
  });

  it("continues an existing numeric suffix instead of stacking another", () => {
    expect(nextFreeName("Queue_2", new Set(["Queue_2"]))).toBe("Queue_3");
    expect(nextFreeName("Place_1", new Set(["Place_1"]))).toBe("Place_2");
  });

  it("skips numbers that are taken after the starting one", () => {
    expect(nextFreeName("Queue_2", new Set(["Queue_2", "Queue_3"]))).toBe("Queue_4");
  });
});

describe("allNames", () => {
  it("covers places, transitions and object frames in one namespace", () => {
    const names = allNames(
      net({ places: [place("p1", "A")], transitions: [transition("t1", "B")], objects: [frame("o1", "C")] }),
    );
    expect([...names].sort()).toEqual(["A", "B", "C"]);
  });
});

describe("findGroupConflicts", () => {
  it("reports nothing when no name is taken", () => {
    const existing = net({ places: [place("p1", "A")] });
    const group = net({ places: [place("p9", "B")] });
    expect(findGroupConflicts(existing, group)).toEqual([]);
  });

  it("catches a place colliding with a transition, which the per-kind check missed", () => {
    const existing = net({ transitions: [transition("t1", "Work")] });
    const group = net({ places: [place("p9", "Work")] });
    const [conflict] = findGroupConflicts(existing, group);
    expect(conflict).toMatchObject({ ids: ["p9"], kind: "place", name: "Work", suggestion: "Work_2" });
  });

  it("catches an object frame colliding with an element", () => {
    const existing = net({ places: [place("p1", "Line")] });
    const group = net({ places: [], objects: [frame("o9", "Line")] });
    expect(findGroupConflicts(existing, group)[0]).toMatchObject({ kind: "object", suggestion: "Line_2" });
  });

  it("hands out distinct suggestions when two elements want the same name", () => {
    const existing = net({ places: [place("p1", "Q")] });
    const group = net({ places: [place("p8", "Q"), place("p9", "Q")] });
    const suggestions = findGroupConflicts(existing, group).map((c) => c.suggestion);
    expect(suggestions).toEqual(["Q_2", "Q_3"]);
  });

  it("does not hand out a name the group already uses for something else", () => {
    const existing = net({ places: [place("p1", "Q")] });
    const group = net({ places: [place("p8", "Q"), place("p9", "Q_2")] });
    const [conflict] = findGroupConflicts(existing, group);
    expect(conflict.suggestion).toBe("Q_3");
  });

  it("treats fused places in the group as ONE place with ONE new name", () => {
    const existing = net({ places: [place("p1", "Out"), place("p2", "Out")] });
    const group = net({
      places: [place("c1", "Out"), place("c2", "Out")],
      links: [fusion("l1", "c1", "c2")],
    });
    const conflicts = findGroupConflicts(existing, group);
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].ids.sort()).toEqual(["c1", "c2"]);
    const renamed = renameInGroup(group, suggestedRenames(conflicts));
    expect(renamed.places.map((p) => p.name)).toEqual(["Out_2", "Out_2"]);
  });

  it("does not merge two places that merely share a name", () => {
    const existing = net({ places: [place("p1", "Out")] });
    const group = net({ places: [place("c1", "Out"), place("c2", "Out")] });
    expect(findGroupConflicts(existing, group)).toHaveLength(2);
  });

  it("ignores a fusion whose partner was left outside the group", () => {
    const existing = net({ places: [place("p1", "Out")] });
    const group = net({
      places: [place("c1", "Out")],
      links: [fusion("l1", "c1", "p1")],
    });
    expect(findGroupConflicts(existing, group)).toHaveLength(1);
  });
});

describe("renameInGroup", () => {
  it("renames only the named elements and leaves the rest as they were", () => {
    const group = net({ places: [place("p1", "A"), place("p2", "B")], transitions: [transition("t1", "C")] });
    const renamed = renameInGroup(group, new Map([["p2", "B_2"]]));
    expect(renamed.places.map((p) => p.name)).toEqual(["A", "B_2"]);
    expect(renamed.transitions[0]).toBe(group.transitions[0]);
  });

  it("returns the very same group when there is nothing to rename", () => {
    const group = net({ places: [place("p1")] });
    expect(renameInGroup(group, new Map())).toBe(group);
  });
});

describe("renameConflict", () => {
  const base = net({
    places: [place("p1", "A"), place("p2", "B")],
    transitions: [transition("t1", "T")],
    objects: [frame("o1", "Obj")],
  });

  it("is null for a name nobody uses", () => {
    expect(renameConflict(base, "p1", "Fresh")).toBeNull();
  });

  it("is null when the element keeps its own name", () => {
    expect(renameConflict(base, "p1", "A")).toBeNull();
  });

  it("flags a name used by another element, whatever its kind", () => {
    const result = renameConflict(base, "p1", "T");
    expect(result?.conflict).toMatchObject({ ids: ["p1"], name: "T", suggestion: "T_2" });
    expect(result?.taken.has("T")).toBe(true);
  });

  it("flags a name used by an object frame", () => {
    expect(renameConflict(base, "t1", "Obj")?.conflict.suggestion).toBe("Obj_2");
  });

  it("lets a fused place take the name of the place it is fused with", () => {
    const fused = net({
      places: [place("p1", "Out"), place("p2", "In")],
      links: [fusion("l1", "p2", "p1")],
    });
    expect(renameConflict(fused, "p2", "Out")).toBeNull();
  });

  it("still flags a fused place that takes some OTHER element's name", () => {
    const fused = net({
      places: [place("p1", "Out"), place("p2", "In"), place("p3", "Other")],
      links: [fusion("l1", "p2", "p1")],
    });
    expect(renameConflict(fused, "p2", "Other")).not.toBeNull();
  });

  it("the exception covers fusion partners only, not an unrelated place with the same name", () => {
    const fused = net({
      places: [place("p1", "Out"), place("p2", "In"), place("p3", "Out")],
      links: [fusion("l1", "p2", "p1")],
    });
    // p3 is called Out and is NOT fused with p2, so Out is still taken.
    expect(renameConflict(fused, "p2", "Out")).not.toBeNull();
  });
});
