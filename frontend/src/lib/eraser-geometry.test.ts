import { describe, expect, it } from "vitest";
import type { ObjectFrame, PetriArc, PetriNetData, PetriPlace, PetriTransition } from "@/types/petri";
import {
  ERASER_REACH_PIXELS,
  ERASER_SWEEP_MIN_PIXELS,
  eraserHitAt,
  eraserPick,
  eraserProbePoints,
  eraserReachUnits,
  isEraserSweep,
  resolveEraserBand,
} from "./eraser-geometry";

function place(id: string, x: number, y: number, objectId?: string): PetriPlace {
  return { id, name: id, tokens: 0, graphics: { x, y }, objectId };
}

function transition(id: string, x: number, y: number, objectId?: string): PetriTransition {
  return {
    id,
    name: id,
    priority: 1,
    distribution: "exp",
    mean_delay: 1,
    standard_deviation: 0,
    probability: null,
    graphics: { x, y },
    objectId,
  };
}

function arc(id: string, source_id: string, target_id: string): PetriArc {
  return { id, source_id, target_id, weight: 1, arc_type: "NORMAL" };
}

function frame(
  id: string,
  x: number,
  y: number,
  width: number,
  height: number,
  opts?: { objectId?: string; collapsed?: boolean },
): ObjectFrame {
  return { id, name: id, priority: 0, graphics: { x, y, width, height }, ...opts };
}

function net(partial: Partial<PetriNetData>): PetriNetData {
  return { name: "n", places: [], transitions: [], arcs: [], ...partial };
}

describe("eraserReachUnits", () => {
  it("reaches ERASER_REACH_PIXELS screen pixels at zoom 1", () => {
    expect(eraserReachUnits(1)).toBe(ERASER_REACH_PIXELS);
  });

  it("reaches further in canvas units when zoomed out, so the screen distance stays fixed", () => {
    expect(eraserReachUnits(0.5)).toBe(12);
  });

  it("reaches less in canvas units when zoomed in, so the screen distance stays fixed", () => {
    expect(eraserReachUnits(2)).toBe(3);
  });

  it("never drops to zero canvas units, however far zoomed in", () => {
    expect(eraserReachUnits(100)).toBeGreaterThanOrEqual(1);
  });
});

describe("eraserProbePoints", () => {
  it("puts the exact centre first", () => {
    const points = eraserProbePoints({ x: 10, y: 20 }, 6);
    expect(points[0]).toEqual({ x: 10, y: 20 });
  });

  it("orders every later probe strictly farther from centre than the one before its ring", () => {
    const center = { x: 0, y: 0 };
    const points = eraserProbePoints(center, 6);
    const distances = points.map((p) => Math.hypot(p.x - center.x, p.y - center.y));
    // Exact point (0), then eight points at the near ring, then eight at the
    // far ring: distances are non-decreasing across that grouping, and the
    // near ring is strictly closer than the far ring (two passes, not one
    // widened pass; see the module doc comment on why that matters).
    expect(distances[0]).toBe(0);
    const nearRing = distances.slice(1, 9);
    const farRing = distances.slice(9, 17);
    for (const d of nearRing) expect(d).toBeCloseTo(3, 5);
    for (const d of farRing) expect(d).toBeCloseTo(6, 5);
  });

  it("probes eight directions per ring", () => {
    const points = eraserProbePoints({ x: 0, y: 0 }, 6);
    expect(points).toHaveLength(1 + 8 + 8);
  });

  it("keeps the near ring radius at least 1 even when reach is 1", () => {
    const points = eraserProbePoints({ x: 0, y: 0 }, 1);
    const nearRing = points.slice(1, 9);
    for (const p of nearRing) expect(Math.hypot(p.x, p.y)).toBeCloseTo(1, 5);
  });
});

describe("isEraserSweep", () => {
  it("is not a sweep when nothing moved", () => {
    expect(isEraserSweep({ x: 0, y: 0 }, { x: 0, y: 0 }, 1)).toBe(false);
  });

  it("is a sweep once the screen distance reaches the threshold, at zoom 1", () => {
    expect(isEraserSweep({ x: 0, y: 0 }, { x: ERASER_SWEEP_MIN_PIXELS, y: 0 }, 1)).toBe(true);
    expect(isEraserSweep({ x: 0, y: 0 }, { x: ERASER_SWEEP_MIN_PIXELS - 1, y: 0 }, 1)).toBe(false);
  });

  it("judges the same screen distance the same way at any zoom", () => {
    // At zoom 0.5 a canvas-unit move of 12 is only 6 screen pixels, exactly
    // the threshold; at zoom 2 the same screen distance is a 3-unit move.
    // The threshold is defined in screen pixels, so it must not drift.
    expect(isEraserSweep({ x: 0, y: 0 }, { x: 12, y: 0 }, 0.5)).toBe(true);
    expect(isEraserSweep({ x: 0, y: 0 }, { x: 11, y: 0 }, 0.5)).toBe(false);
    expect(isEraserSweep({ x: 0, y: 0 }, { x: 3, y: 0 }, 2)).toBe(true);
    expect(isEraserSweep({ x: 0, y: 0 }, { x: 2.9, y: 0 }, 2)).toBe(false);
  });
});

describe("resolveEraserBand", () => {
  it("catches a place by its centre, not one whose centre falls outside", () => {
    const n = net({ places: [place("p1", 0, 0), place("p2", 1000, 1000)] });
    // p1's box is [0,56]x[0,56], centre (28,28); band covers it. p2's centre
    // (1028,1028) is nowhere near.
    const { placeIds } = resolveEraserBand(n, { minX: 0, minY: 0, maxX: 100, maxY: 100 });
    expect(placeIds).toEqual(["p1"]);
  });

  it("catches a transition by its centre the same way", () => {
    const n = net({ transitions: [transition("t1", 0, 0), transition("t2", 1000, 1000)] });
    const { transitionIds } = resolveEraserBand(n, { minX: 0, minY: 0, maxX: 100, maxY: 100 });
    expect(transitionIds).toEqual(["t1"]);
  });

  it("catches an arc that crosses the band even though both endpoints are outside it", () => {
    // p1 far left, t1 far right, graphics.y offset so both centres land on
    // y=0: a flat line straight through the band, with neither endpoint's
    // own centre anywhere near it.
    const n = net({
      places: [place("p1", -500, -28)],
      transitions: [transition("t1", 500, -32)],
      arcs: [arc("a1", "p1", "t1")],
    });
    const { arcIds } = resolveEraserBand(n, { minX: -10, minY: -10, maxX: 10, maxY: 10 });
    expect(arcIds).toEqual(["a1"]);
  });

  it("does not catch an arc that passes nowhere near the band", () => {
    const n = net({
      places: [place("p1", -500, 500)],
      transitions: [transition("t1", 500, 500)],
      arcs: [arc("a1", "p1", "t1")],
    });
    const { arcIds } = resolveEraserBand(n, { minX: -10, minY: -10, maxX: 10, maxY: 10 });
    expect(arcIds).toEqual([]);
  });

  it("catches an object frame only when the band swallows it whole", () => {
    const n = net({ objects: [frame("o1", 100, 100, 200, 200)] });
    const swallowed = resolveEraserBand(n, { minX: 50, minY: 50, maxX: 400, maxY: 400 });
    expect(swallowed.objectIds).toEqual(["o1"]);

    // A band only partly overlapping the frame does not take it.
    const partial = resolveEraserBand(n, { minX: 150, minY: 150, maxX: 400, maxY: 400 });
    expect(partial.objectIds).toEqual([]);
  });

  it("does not let a frame's own members ride along uncaptured when only the frame is swallowed", () => {
    const n = net({
      objects: [frame("o1", 100, 100, 200, 200)],
      places: [place("p1", 150, 150, "o1")],
    });
    const { objectIds, placeIds } = resolveEraserBand(n, { minX: 50, minY: 50, maxX: 400, maxY: 400 });
    expect(objectIds).toEqual(["o1"]);
    // p1's centre also falls in the band, so it's separately caught too;
    // catching both is fine, deleteSelection's own object cascade (not this
    // function) is what makes deleting the frame take p1 with it regardless.
    expect(placeIds).toContain("p1");
  });
});

describe("eraserHitAt", () => {
  it("hits a place whose box contains the point", () => {
    const n = net({ places: [place("p1", 0, 0)] });
    expect(eraserHitAt(n, { x: 28, y: 28 })).toEqual({ id: "p1", kind: "place" });
  });

  it("misses when the point is nowhere near anything", () => {
    const n = net({ places: [place("p1", 0, 0)] });
    expect(eraserHitAt(n, { x: 5000, y: 5000 })).toBeNull();
  });

  it("hits an arc when the point lands on its line, away from either endpoint", () => {
    // Both ends are places (unrealistic for a real net, but the geometry
    // doesn't care) with the same graphics.y offset so their centres share a
    // y-coordinate: the arc between them is a flat line straight through the
    // origin, well clear of either endpoint's own 56x56 box.
    const n = net({
      places: [place("p1", -300, -28), place("p2", 300, -28)],
      arcs: [arc("a1", "p1", "p2")],
    });
    expect(eraserHitAt(n, { x: 0, y: 0 })).toEqual({ id: "a1", kind: "arc" });
  });

  it("prefers a place over a frame that contains it", () => {
    const n = net({
      objects: [frame("o1", 0, 0, 300, 300)],
      places: [place("p1", 100, 100, "o1")],
    });
    expect(eraserHitAt(n, { x: 128, y: 128 })).toEqual({ id: "p1", kind: "place" });
  });

  it("hits the frame itself away from any member", () => {
    const n = net({
      objects: [frame("o1", 0, 0, 300, 300)],
      places: [place("p1", 100, 100, "o1")],
    });
    expect(eraserHitAt(n, { x: 10, y: 10 })).toEqual({ id: "o1", kind: "object" });
  });

  it("does not hit a member hidden behind a collapsed frame; the frame itself stands in for it", () => {
    const n = net({
      objects: [frame("o1", 0, 0, 300, 300, { collapsed: true })],
      places: [place("p1", 100, 100, "o1")],
    });
    // Point lands squarely inside p1's own (hidden) box, but nothing is
    // rendered there while o1 is collapsed; only the frame is clickable.
    expect(eraserHitAt(n, { x: 128, y: 128 })).toEqual({ id: "o1", kind: "object" });
  });
});

describe("eraserPick", () => {
  it("finds the exact hit before falling back to a ring probe", () => {
    const n = net({ places: [place("p1", 0, 0)] });
    expect(eraserPick(n, { x: 28, y: 28 }, 6)).toEqual({ id: "p1", kind: "place" });
  });

  it("reaches a thin arc that the exact point misses but a ring probe catches", () => {
    // Both endpoints are placed so the arc's line sits exactly at y=-5:
    // 5 canvas units from the click, past the arc's own hit corridor (4) at
    // the exact point, but within the near ring at reach/2 (3): the ring
    // point straight up from the click (0,-3) is only 2 units from the line.
    const n = net({
      places: [place("p1", -300, -33)],
      transitions: [transition("t1", 300, -37)],
      arcs: [arc("a1", "p1", "t1")],
    });
    expect(eraserPick(n, { x: 0, y: 0 }, 6)?.id).toBe("a1");
  });

  it("skips an ineligible hit and keeps probing for one the caller accepts", () => {
    // The click lands just inside p1's right edge (its box ends at x=56).
    // The exact point hits p1, which the caller rejects (standing in for a
    // foreign object's member the eraser isn't allowed to reach); a probe
    // just 3 units further east clears p1's edge while staying well inside
    // the frame around it, so the frame is what the eraser actually erases.
    const n = net({
      objects: [frame("o1", 0, 0, 300, 300)],
      places: [place("p1", 0, 0)],
    });
    const hit = eraserPick(n, { x: 55, y: 28 }, 6, (h) => h.kind === "object");
    expect(hit).toEqual({ id: "o1", kind: "object" });
  });

  it("finds nothing when reach is exhausted and nothing is close enough", () => {
    const n = net({ places: [place("p1", 5000, 5000)] });
    expect(eraserPick(n, { x: 0, y: 0 }, 6)).toBeNull();
  });
});
