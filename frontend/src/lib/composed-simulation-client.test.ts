import { describe, expect, it } from "vitest";
import { buildComposedRequest } from "./composed-simulation-client";
import type { ObjectFrame, PetriNetData, PetriPlace, PetriTransition } from "@/types/petri";

const place = (id: string, objectId?: string): PetriPlace => ({
  id, name: id.toUpperCase(), tokens: 0, graphics: { x: 20, y: 20 }, objectId,
});
const transition = (id: string, objectId?: string): PetriTransition => ({
  id, name: id.toUpperCase(), priority: 1, distribution: "exp" as const,
  mean_delay: 1, standard_deviation: 0, probability: null,
  graphics: { x: 80, y: 20 }, objectId,
});
const frame = (id: string, name: string, x: number): ObjectFrame => ({
  id, name, priority: 0, graphics: { x, y: 10, width: 200, height: 150 },
});

/** Two objects joined by a link, plus whatever a test adds to it. */
function linkedPair(): PetriNetData {
  return {
    name: "Framed",
    places: [place("pA", "oA"), place("pB", "oB")],
    transitions: [transition("tA", "oA")],
    arcs: [{ id: "aA", source_id: "pA", target_id: "tA", weight: 1, arc_type: "NORMAL" }],
    objects: [frame("oA", "A", 10), frame("oB", "B", 300)],
    links: [{ id: "l0", type: "transitionToPlace", sourceId: "tA", targetId: "pB", quantity: 1 }],
  };
}

describe("buildComposedRequest", () => {
  it("drops objects with no elements by default, and keeps them on request", () => {
    const net = linkedPair();
    net.objects!.push(frame("oEmpty", "Empty", 600));

    // A simulation request only carries objects the engine can run.
    expect(buildComposedRequest(net)!.objects.map((o) => o.name)).toEqual(["A", "B"]);
    // A document has to reproduce the canvas, empty frame and all.
    expect(
      buildComposedRequest(net, { includeEmptyObjects: true })!.objects.map((o) => o.name),
    ).toEqual(["A", "B", "Empty"]);
  });

  it("keeps cross-object links addressing the same elements once empty objects join", () => {
    const net = linkedPair();
    // A container frame sorts first, so every object index after it shifts.
    net.objects!.unshift(frame("oC", "Container", 500));
    net.objects![1].objectId = "oC";

    const body = buildComposedRequest(net, { includeEmptyObjects: true })!;
    expect(body.objects.map((o) => o.name)).toEqual(["Container", "A", "B"]);
    const link = body.links[0];
    // Object 1 ("A") transition 0 -> object 2 ("B") place 0, still tA -> pB.
    expect(body.objects[link.source_object].net_data.transitions[link.source_element].id).toBe("tA");
    expect(body.objects[link.target_object].net_data.places[link.target_element].id).toBe("pB");
  });

  it("records the frame's size, collapse, nest and hand-sizing", () => {
    const net = linkedPair();
    net.objects![0].collapsed = true;
    net.objects![0].autoFit = false;
    net.objects!.unshift(frame("oC", "Container", 500));
    net.objects![1].objectId = "oC";

    const body = buildComposedRequest(net, { includeEmptyObjects: true })!;
    const a = body.objects[1];
    expect(a.width).toBe(200);
    expect(a.height).toBe(150);
    expect(a.collapsed).toBe(true);
    expect(a.auto_fit).toBe(false);
    expect(a.parent).toBe(0);
    // An object that says nothing about collapse, nesting or sizing carries
    // none of those fields at all — absent is the default, not "false".
    const b = body.objects[2];
    expect(b.collapsed).toBeUndefined();
    expect(b.auto_fit).toBeUndefined();
    expect(b.parent).toBeUndefined();
    expect(b.free).toBeUndefined();
  });

  it("marks the free-elements bucket, which is not a frame and has no geometry", () => {
    const net = linkedPair();
    net.places.push(place("pFree"));

    const body = buildComposedRequest(net)!;
    const free = body.objects[2];
    expect(free.free).toBe(true);
    expect(free.width).toBeUndefined();
    expect(free.height).toBeUndefined();
    expect(free.net_data.places.map((p) => p.id)).toEqual(["pFree"]);
  });
});

describe("buildComposedRequest heals links whose endpoints share one owner", () => {
  it("projects a same-owner directional link into that object's local arcs", () => {
    const net = linkedPair();
    // Membership changed after the link was drawn: pB now lives in oA too,
    // so transitionToPlace tA->pB connects oA to itself.
    net.places = [place("pA", "oA"), place("pB", "oA")];

    const body = buildComposedRequest(net)!;
    expect(body.links).toHaveLength(0);
    const a = body.objects.find((o) => o.name === "A")!;
    const healed = a.net_data.arcs.find((arc) => arc.source_id === "tA" && arc.target_id === "pB");
    expect(healed).toBeDefined();
    expect(healed!.weight).toBe(1);
    expect(healed!.arc_type).toBe("NORMAL");
  });

  it("an informational same-owner link becomes a READ arc, a same-owner fusion is dropped", () => {
    const net = linkedPair();
    net.places = [place("pA", "oA"), place("pB", "oA")];
    net.links = [
      { id: "l0", type: "placeToTransition", sourceId: "pB", targetId: "tA", quantity: 2, informational: true },
      { id: "l1", type: "placeFusion", sourceId: "pA", targetId: "pB", quantity: 1 },
    ];

    const body = buildComposedRequest(net)!;
    expect(body.links).toHaveLength(0);
    const a = body.objects.find((o) => o.name === "A")!;
    const healed = a.net_data.arcs.find((arc) => arc.source_id === "pB" && arc.target_id === "tA");
    expect(healed).toMatchObject({ weight: 2, arc_type: "READ" });
    expect(a.net_data.arcs.filter((arc) => arc.id.startsWith("healed_"))).toHaveLength(1);
  });

  it("skips healing when the same local flow already exists as an arc", () => {
    const net = linkedPair();
    net.places = [place("pA", "oA"), place("pB", "oA")];
    net.arcs.push({ id: "aDup", source_id: "tA", target_id: "pB", weight: 3, arc_type: "NORMAL" });

    const body = buildComposedRequest(net)!;
    const a = body.objects.find((o) => o.name === "A")!;
    expect(a.net_data.arcs.filter((arc) => arc.source_id === "tA" && arc.target_id === "pB")).toHaveLength(1);
  });

  it("drops a fusion between two places belonging to no object, warning about it", () => {
    // Rule 5's free-to-free carve-out (rejectionForFusion, petri-object-model.ts)
    // lets the editor draw this link since neither end has a DEFINED owner,
    // but the free-elements bucket is one composed object here, the same as
    // the desktop's implicit "everything free is one object" folding, so the
    // link still has no structural form and the simulation payload must not
    // carry it either. This is the same drop pnml-export-composed.ts reports
    // when building the document; the two must agree.
    const net: PetriNetData = {
      name: "FreeFusion",
      places: [place("p1"), place("p2")],
      transitions: [],
      arcs: [],
      links: [{ id: "l1", type: "placeFusion", sourceId: "p2", targetId: "p1", quantity: 1 }],
    };

    const warnings: string[] = [];
    const body = buildComposedRequest(net, { onWarning: (m) => warnings.push(m) })!;

    expect(body.links).toHaveLength(0);
    expect(warnings).toEqual([
      'Dropped the link "P1" (id "p1") = "P2" (id "p2"): both places belong to the same ' +
        "Petri-object, so linking them would have it repeat itself.",
    ]);
  });
});
