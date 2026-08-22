import { describe, expect, it } from "vitest";
import type { ObjectFrame, ObjectLink, PetriNetData, PetriTransition } from "@/types/petri";
import {
  cloneElements,
  fusionGroupsByPlace,
  isLocalToNet,
  objectAsGroup,
  reconcileArcsForNewMembership,
  reconcileLinksForNewMembership,
  resolveFusionMarking,
  resolveObjectBand,
  synthesizePlaceToTransitionFusion,
} from "./petri-object-model";

function place(id: string, objectId?: string) {
  return { id, name: id, tokens: 0, graphics: { x: 0, y: 0 }, objectId };
}

function transition(id: string, objectId?: string): PetriTransition {
  return {
    id,
    name: id,
    priority: 1,
    distribution: "exp",
    mean_delay: 1,
    standard_deviation: 0,
    probability: null,
    graphics: { x: 0, y: 0 },
    objectId,
  };
}

function frame(id: string, objectId?: string): ObjectFrame {
  return {
    id,
    name: id,
    priority: 0,
    graphics: { x: 0, y: 0, width: 200, height: 200 },
    objectId,
  };
}

function fusion(id: string, sourceId: string, targetId: string): ObjectLink {
  return { id, type: "placeFusion", sourceId, targetId, quantity: 1 };
}

function netWith(links: PetriNetData["links"]): PetriNetData {
  return {
    name: "n",
    places: ["p1", "p2", "p3", "p4", "p5"].map((id) => place(id)),
    transitions: [],
    arcs: [],
    links,
  };
}

describe("fusionGroupsByPlace", () => {
  it("has nothing to say about a net with no fusion", () => {
    expect(fusionGroupsByPlace(netWith([])).size).toBe(0);
  });

  it("groups the two places a single fusion joins", () => {
    const groups = fusionGroupsByPlace(netWith([fusion("l1", "p1", "p2")]));
    expect(groups.get("p1")!.label).toBe("A");
    expect(groups.get("p2")!.label).toBe("A");
    expect(groups.get("p1")!.members.sort()).toEqual(["p1", "p2"]);
    expect(groups.has("p3")).toBe(false);
  });

  it("follows fusion transitively — A=B and B=C makes all three one place", () => {
    const groups = fusionGroupsByPlace(
      netWith([fusion("l1", "p1", "p2"), fusion("l2", "p2", "p3")]),
    );
    expect(groups.get("p1")!.members.sort()).toEqual(["p1", "p2", "p3"]);
    expect(groups.get("p3")!.label).toBe("A");
  });

  it("names separate groups apart", () => {
    const groups = fusionGroupsByPlace(
      netWith([fusion("l1", "p1", "p2"), fusion("l2", "p4", "p5")]),
    );
    expect(groups.get("p1")!.label).toBe("A");
    expect(groups.get("p4")!.label).toBe("B");
  });

  it("ignores links that are flows rather than identities", () => {
    const groups = fusionGroupsByPlace(
      netWith([
        { id: "l1", type: "placeToTransition", sourceId: "p1", targetId: "t1", quantity: 1 },
      ]),
    );
    expect(groups.size).toBe(0);
  });
});

describe("resolveFusionMarking", () => {
  const groups = fusionGroupsByPlace(netWith([fusion("l1", "p1", "p2")]));

  it("prefers the place's own marking when the snapshot names it directly", () => {
    expect(resolveFusionMarking(groups, { p1: 3 }, "p1")).toBe(3);
  });

  it("mirrors the fusion partner's marking when this half isn't named", () => {
    // The composed engine tracks the pair as two places, not one, so a
    // firing that lands on p1 leaves p2 out of the snapshot entirely — the
    // exact "joined half shows its stale count forever" bug this mirrors.
    expect(resolveFusionMarking(groups, { p1: 4 }, "p2")).toBe(4);
  });

  it("returns undefined for an unfused place missing from the snapshot", () => {
    expect(resolveFusionMarking(groups, { p1: 4 }, "p3")).toBeUndefined();
  });

  it("returns undefined when neither half is in the snapshot at all", () => {
    expect(resolveFusionMarking(groups, {}, "p1")).toBeUndefined();
  });
});

describe("isLocalToNet", () => {
  /** o1 (top-level) holds p1 and nested child o2, which holds p2. */
  function nestedNet(): PetriNetData {
    return {
      name: "n",
      places: [place("p1", "o1"), place("p2", "o2")],
      transitions: [],
      objects: [frame("o1"), frame("o2", "o1")],
      arcs: [],
      links: [],
    };
  }

  it("a free place, and a top-level frame with no owner, are local", () => {
    const net = nestedNet();
    expect(isLocalToNet(net, "o1")).toBe(true);
  });

  it("a frame's own direct member is not local — visible here only because the frame is expanded", () => {
    const net = nestedNet();
    expect(isLocalToNet(net, "p1")).toBe(false);
  });

  it("a nested child frame is not local, even though it sits directly on screen when its parent is expanded", () => {
    const net = nestedNet();
    expect(isLocalToNet(net, "o2")).toBe(false);
  });

  it("a doubly-nested member is not local either", () => {
    const net = nestedNet();
    expect(isLocalToNet(net, "p2")).toBe(false);
  });

  it("an id that resolves to nothing is not local", () => {
    expect(isLocalToNet(nestedNet(), "nope")).toBe(false);
  });
});

describe("synthesizePlaceToTransitionFusion", () => {
  function baseNet(): PetriNetData {
    return {
      name: "n",
      places: [{ ...place("p1", "o1"), tokens: 5 }],
      transitions: [transition("t1", "o2")],
      objects: [frame("o1"), frame("o2")],
      arcs: [],
      links: [],
    };
  }

  it("creates a local proxy place inside the transition's object, a local arc to it, and a placeFusion back to the source place", () => {
    const net = baseNet();
    const result = synthesizePlaceToTransitionFusion(net, "p1", "t1");
    expect(result).not.toBeNull();
    const { net: next, linkId } = result!;

    expect(next.places).toHaveLength(2);
    const proxy = next.places.find((p) => p.id !== "p1")!;
    expect(proxy.objectId).toBe("o2");
    expect(proxy.tokens).toBe(5); // adopts the source place's marking, same as addObjectLink's own master rule

    expect(next.arcs).toHaveLength(1);
    expect(next.arcs[0].source_id).toBe(proxy.id);
    expect(next.arcs[0].target_id).toBe("t1");
    expect(next.arcs[0].arc_type).toBe("NORMAL");
    expect(next.arcs[0].weight).toBe(1);

    const link = next.links!.find((l) => l.id === linkId)!;
    expect(link.type).toBe("placeFusion");
    expect(link.sourceId).toBe("p1");
    expect(link.targetId).toBe(proxy.id);
  });

  it("honors quantity and informational options on the synthesized arc", () => {
    const net = baseNet();
    const result = synthesizePlaceToTransitionFusion(net, "p1", "t1", {
      quantity: 3,
      informational: true,
    });
    expect(result!.net.arcs[0].weight).toBe(3);
    expect(result!.net.arcs[0].arc_type).toBe("READ");
  });

  it("returns null when the source place already belongs to a fusion group", () => {
    const net = baseNet();
    net.places.push(place("p2", "o1"));
    net.links = [fusion("l1", "p1", "p2")];
    expect(synthesizePlaceToTransitionFusion(net, "p1", "t1")).toBeNull();
  });

  it("returns null when the transition is free — there is no object to synthesize a proxy place inside", () => {
    const net = baseNet();
    net.transitions[0] = transition("t1", undefined);
    expect(synthesizePlaceToTransitionFusion(net, "p1", "t1")).toBeNull();
  });

  it("returns null when the place and transition already share an owner", () => {
    const net = baseNet();
    net.transitions[0] = transition("t1", "o1");
    expect(synthesizePlaceToTransitionFusion(net, "p1", "t1")).toBeNull();
  });

  it("returns null for an id that doesn't resolve to a place or a transition", () => {
    const net = baseNet();
    expect(synthesizePlaceToTransitionFusion(net, "missing", "t1")).toBeNull();
    expect(synthesizePlaceToTransitionFusion(net, "p1", "missing")).toBeNull();
  });
});

describe("reconcileArcsForNewMembership", () => {
  it("is a no-op (same net reference) when no arc crosses a boundary", () => {
    const net: PetriNetData = {
      name: "n",
      places: [place("p1", "o1")],
      transitions: [transition("t1", "o1")],
      objects: [frame("o1")],
      arcs: [{ id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" }],
      links: [],
    };
    expect(reconcileArcsForNewMembership(net, new Set(["p1"]))).toBe(net);
  });

  it("replaces a place-sourced boundary-crossing arc with a synthesized fusion, not a raw placeToTransition link", () => {
    const net: PetriNetData = {
      name: "n",
      places: [place("p1")], // now free
      transitions: [transition("t1", "o1")],
      objects: [frame("o1")],
      arcs: [{ id: "a1", source_id: "p1", target_id: "t1", weight: 2, arc_type: "NORMAL" }],
      links: [],
    };
    const result = reconcileArcsForNewMembership(net, new Set(["p1"]));

    expect(result.arcs).toHaveLength(1);
    expect(result.arcs[0].id).not.toBe("a1"); // the old arc is gone, a new one replaces it
    expect(result.arcs[0].target_id).toBe("t1");
    expect(result.arcs[0].weight).toBe(2);
    expect(result.places).toHaveLength(2); // p1 plus the synthesized proxy

    const links = result.links!;
    expect(links).toHaveLength(1);
    expect(links[0].type).toBe("placeFusion");
    expect(links[0].sourceId).toBe("p1");
  });

  it("still converts a transition-sourced boundary-crossing arc into a transitionToPlace link, unaffected by placeToTransition's retirement", () => {
    const net: PetriNetData = {
      name: "n",
      places: [place("p1", "o1")],
      transitions: [transition("t1")], // now free
      objects: [frame("o1")],
      arcs: [{ id: "a1", source_id: "t1", target_id: "p1", weight: 1, arc_type: "NORMAL" }],
      links: [],
    };
    const result = reconcileArcsForNewMembership(net, new Set(["t1"]));

    expect(result.arcs).toHaveLength(0);
    const links = result.links!;
    expect(links).toHaveLength(1);
    expect(links[0].type).toBe("transitionToPlace");
    expect(links[0].sourceId).toBe("t1");
    expect(links[0].targetId).toBe("p1");
  });

  it("falls back to a raw placeToTransition link when the source place is already fused elsewhere", () => {
    // A genuine edge case: synthesis can't fuse p1 a second time, so the
    // connection is kept as the old (now validate()-rejected) link rather
    // than silently vanishing — the user resolves the clash by hand.
    const net: PetriNetData = {
      name: "n",
      places: [place("p1"), place("p2", "o2")],
      transitions: [transition("t1", "o1")],
      objects: [frame("o1"), frame("o2")],
      arcs: [{ id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" }],
      links: [fusion("l1", "p1", "p2")],
    };
    const result = reconcileArcsForNewMembership(net, new Set(["p1"]));

    expect(result.arcs).toHaveLength(0);
    const links = result.links!;
    expect(links).toHaveLength(2);
    const newLink = links.find((l) => l.id !== "l1")!;
    expect(newLink.type).toBe("placeToTransition");
    expect(newLink.sourceId).toBe("p1");
    expect(newLink.targetId).toBe("t1");
  });
});

describe("reconcileLinksForNewMembership", () => {
  function netFor(opts: {
    places?: ReturnType<typeof place>[];
    transitions?: PetriTransition[];
    objects?: ObjectFrame[];
    links: ObjectLink[];
  }): PetriNetData {
    return {
      name: "n",
      places: opts.places ?? [],
      transitions: opts.transitions ?? [],
      objects: opts.objects ?? [],
      arcs: [],
      links: opts.links,
    };
  }

  it("is a no-op (same net reference) when every link still connects two different owners", () => {
    const net = netFor({
      places: [place("p1", "o1"), place("p2", "o2")],
      objects: [frame("o1"), frame("o2")],
      links: [fusion("l1", "p1", "p2")],
    });
    const result = reconcileLinksForNewMembership(net);
    expect(result).toBe(net);
  });

  it("drops a placeFusion whose endpoints now share the same object", () => {
    // p1 and p2 could never have been fused while both under o1 (addObjectLink
    // rejects same-owner endpoints) — this models the state AFTER a membership
    // change merged their owners, which is exactly what must be cleaned up.
    const net = netFor({
      places: [place("p1", "o1"), place("p2", "o1")],
      objects: [frame("o1")],
      links: [fusion("l1", "p1", "p2")],
    });
    const result = reconcileLinksForNewMembership(net);
    expect(result.links).toHaveLength(0);
  });

  it("drops a placeFusion whose endpoints are now both free", () => {
    const net = netFor({
      places: [place("p1"), place("p2")],
      links: [fusion("l1", "p1", "p2")],
    });
    const result = reconcileLinksForNewMembership(net);
    expect(result.links).toHaveLength(0);
  });

  it("converts a transitionToPlace link whose endpoints now share an owner into a plain arc", () => {
    const net = netFor({
      places: [place("p1", "o1")],
      transitions: [transition("t1", "o1")],
      objects: [frame("o1")],
      links: [{ id: "l1", type: "transitionToPlace", sourceId: "t1", targetId: "p1", quantity: 2 }],
    });
    const result = reconcileLinksForNewMembership(net);
    expect(result.links).toHaveLength(0);
    expect(result.arcs).toHaveLength(1);
    expect(result.arcs[0]).toMatchObject({
      source_id: "t1",
      target_id: "p1",
      weight: 2,
      arc_type: "NORMAL",
    });
  });

  it("converts an informational placeToTransition link into a READ arc, mirroring reconcileArcsForNewMembership's inverse", () => {
    const net = netFor({
      places: [place("p1", "o1")],
      transitions: [transition("t1", "o1")],
      objects: [frame("o1")],
      links: [
        {
          id: "l1",
          type: "placeToTransition",
          sourceId: "p1",
          targetId: "t1",
          quantity: 3,
          informational: true,
        },
      ],
    });
    const result = reconcileLinksForNewMembership(net);
    expect(result.links).toHaveLength(0);
    expect(result.arcs[0]).toMatchObject({
      source_id: "p1",
      target_id: "t1",
      weight: 3,
      arc_type: "READ",
    });
  });

  it("only reconciles the links that actually became invalid, leaving the rest untouched", () => {
    const net = netFor({
      places: [place("p1", "o1"), place("p2", "o1"), place("p3", "o2")],
      objects: [frame("o1"), frame("o2")],
      links: [fusion("l1", "p1", "p2"), fusion("l2", "p1", "p3")],
    });
    const result = reconcileLinksForNewMembership(net);
    expect(result.links).toHaveLength(1);
    expect(result.links![0].id).toBe("l2");
  });
});

describe("objectAsGroup and cloneElements — nested frames and internal links", () => {
  /** Outer frame o1 directly holds p1; nested child o2 (built inside o1) holds p2; the two are fused. */
  function nestedFusedNet(): PetriNetData {
    return {
      name: "n",
      objects: [frame("o1"), frame("o2", "o1")],
      places: [place("p1", "o1"), place("p2", "o2")],
      transitions: [],
      arcs: [],
      links: [fusion("l1", "p1", "p2")],
    };
  }

  it("objectAsGroup walks the subtree: nested child frame, its members, and the internal fusion all come along", () => {
    const net = nestedFusedNet();
    const group = objectAsGroup(net, "o1")!;

    expect(group.objects.map((o) => o.id)).toEqual(["o1", "o2"]); // requested frame first, parent before child
    expect(group.places.map((p) => p.id).sort()).toEqual(["p1", "p2"]);
    expect(group.links).toHaveLength(1);
    expect(group.links[0].id).toBe("l1");
  });

  it("cloneElements re-parents the nested frame's copy to the OUTER copy, not the original", () => {
    const net = nestedFusedNet();
    const group = objectAsGroup(net, "o1")!;

    const copy = cloneElements(net, group, { x: 10, y: 10 });
    const [outerCopy, innerCopy] = copy.objects;

    expect(innerCopy.objectId).toBe(outerCopy.id);
    expect(innerCopy.objectId).not.toBe("o1");
    expect(innerCopy.id).not.toBe("o2");
  });

  it("cloneElements re-points the internal fusion at the two COPIES, not the originals", () => {
    const net = nestedFusedNet();
    const group = objectAsGroup(net, "o1")!;

    const copy = cloneElements(net, group, { x: 10, y: 10 });

    expect(copy.links).toHaveLength(1);
    const [link] = copy.links;
    const copiedPlaceIds = copy.places.map((p) => p.id);
    expect(copiedPlaceIds).toContain(link.sourceId);
    expect(copiedPlaceIds).toContain(link.targetId);
    expect(link.sourceId).not.toBe("p1");
    expect(link.targetId).not.toBe("p2");
  });

  it("cloneElements drops a link whose partner endpoint fell outside the copied group", () => {
    const net: PetriNetData = {
      name: "n",
      objects: [frame("o1"), frame("o2")],
      places: [place("p1", "o1"), place("p2", "o2")],
      transitions: [],
      arcs: [],
      links: [fusion("l1", "p1", "p2")],
    };
    // Only o1's group is copied — p2 (o2's place) is not part of it.
    const group = objectAsGroup(net, "o1")!;
    const copy = cloneElements(net, group, { x: 10, y: 10 });

    expect(copy.links).toHaveLength(0);
  });
});

describe("resolveObjectBand", () => {
  const bandNet = (objects: ObjectFrame[], places: PetriNetData["places"]): PetriNetData => ({
    name: "n",
    places,
    transitions: [],
    arcs: [],
    objects,
  });

  const box = (
    id: string,
    x: number,
    y: number,
    width: number,
    height: number,
    objectId?: string,
  ): ObjectFrame => ({
    id,
    name: id,
    priority: 0,
    graphics: { x, y, width, height },
    objectId,
  });

  const at = (id: string, x: number, y: number, objectId?: string) => ({
    ...place(id, objectId),
    graphics: { x, y },
  });

  it("a band that swallows a frame wraps it: the frame is captured, not made the parent", () => {
    const net = bandNet([box("o1", 100, 100, 200, 200)], [at("p1", 150, 150, "o1")]);
    const { parentId, capturedIds } = resolveObjectBand(net, {
      minX: 50,
      minY: 50,
      maxX: 400,
      maxY: 400,
    });
    expect(parentId).toBeUndefined();
    expect(capturedIds).toEqual(["o1"]);
  });

  it("a swallowed frame's own members are not captured alongside it", () => {
    // p1 lives in o1; the band takes o1 whole, so p1 travels with its frame
    // and must not be torn out into the new object as a loose member.
    const net = bandNet([box("o1", 100, 100, 200, 200)], [at("p1", 150, 150, "o1")]);
    const { capturedIds } = resolveObjectBand(net, { minX: 50, minY: 50, maxX: 400, maxY: 400 });
    expect(capturedIds).not.toContain("p1");
  });

  it("a band drawn INSIDE a frame still nests: the frame is the parent, its loose members are captured", () => {
    const net = bandNet([box("o1", 0, 0, 600, 600)], [at("p1", 200, 200, "o1")]);
    const { parentId, capturedIds } = resolveObjectBand(net, {
      minX: 150,
      minY: 150,
      maxX: 350,
      maxY: 350,
    });
    expect(parentId).toBe("o1");
    expect(capturedIds).toEqual(["p1"]);
  });

  it("swallowing a two-level object picks no parent at all: the deepest frame under the centre is swallowed too", () => {
    // The exact shape the third band gesture met: o2 inside o1, both under the
    // band's centre. Answering with either of them built the new frame inside
    // what it was wrapping, which closed a parent cycle.
    const net = bandNet(
      [box("o1", 100, 100, 400, 400), box("o2", 150, 150, 200, 200, "o1")],
      [at("p1", 200, 200, "o2")],
    );
    const { parentId, capturedIds } = resolveObjectBand(net, {
      minX: 0,
      minY: 0,
      maxX: 700,
      maxY: 700,
    });
    expect(parentId).toBeUndefined();
    expect(capturedIds).toEqual(["o1"]);
  });

  it("a frame only partly under the band stays the parent: it is not being wrapped", () => {
    const net = bandNet([box("o1", 0, 0, 600, 600)], []);
    // The band hangs off o1's bottom-right corner: its centre is still inside
    // o1, and o1 is not swallowed, so the band reads as drawn INSIDE o1.
    const { parentId, capturedIds } = resolveObjectBand(net, {
      minX: 300,
      minY: 300,
      maxX: 700,
      maxY: 700,
    });
    expect(parentId).toBe("o1");
    expect(capturedIds).toEqual([]);
  });

  it("free elements centred in the band are captured, members of other objects are not", () => {
    const net = bandNet(
      [box("o1", 500, 0, 200, 200)],
      [at("p1", 100, 100), at("p2", 550, 50, "o1")],
    );
    const { parentId, capturedIds } = resolveObjectBand(net, {
      minX: 0,
      minY: 0,
      maxX: 300,
      maxY: 300,
    });
    expect(parentId).toBeUndefined();
    expect(capturedIds).toEqual(["p1"]);
  });

  it("a collapsed frame never becomes the parent", () => {
    const net = bandNet(
      [{ ...box("o1", 0, 0, 600, 600), collapsed: true }],
      [],
    );
    const { parentId } = resolveObjectBand(net, {
      minX: 100,
      minY: 100,
      maxX: 300,
      maxY: 300,
    });
    expect(parentId).toBeUndefined();
  });
});
