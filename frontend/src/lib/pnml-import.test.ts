import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { parsePnml } from "./pnml-import";
import { exportPnml } from "./pnml-export";
import type { ObjectFrame, PetriNetData, PetriPlace, PetriTransition } from "@/types/petri";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadFixture(name: string): string {
  return readFileSync(path.join(__dirname, "__fixtures__", name), "utf-8");
}

const SAMPLE_PNML = `<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name>
      <text>Test Net</text>
    </name>
    <place id="p1">
      <name><text>Input</text></name>
      <initialMarking><text>3</text></initialMarking>
      <toolspecific tool="PetriObjModel" version="1.0">
        <coordinates x="100" y="200"/>
      </toolspecific>
      <graphics><position x="100" y="200"/></graphics>
    </place>
    <place id="p2">
      <name><text>Output</text></name>
      <graphics><position x="300" y="200"/></graphics>
    </place>
    <transition id="t1">
      <name><text>Process</text></name>
      <toolspecific tool="PetriObjModel" version="1.0">
        <coordinates x="200" y="200"/>
        <timeDelay>5</timeDelay>
        <delayMeanValue>5</delayMeanValue>
        <distribution>exp</distribution>
        <priority>2</priority>
      </toolspecific>
      <graphics><position x="200" y="200"/></graphics>
    </transition>
    <arc id="a1" source="p1" target="t1">
      <graphics/>
      <inscription><text>1</text></inscription>
    </arc>
    <arc id="a2" source="t1" target="p2">
      <graphics/>
      <inscription><text>2</text></inscription>
    </arc>
  </net>
</pnml>`;

describe("parsePnml", () => {
  it("parses places with names, tokens, and positions", () => {
    const { data: net } = parsePnml(SAMPLE_PNML);
    expect(net.name).toBe("Test Net");
    expect(net.places).toHaveLength(2);

    const p1 = net.places.find((p) => p.id === "p1")!;
    expect(p1.name).toBe("Input");
    expect(p1.tokens).toBe(3);
    // The wire position is the place's CENTER (100, 200); the app model keeps
    // React Flow's top-left anchor, half the place's own size (56x56) back.
    expect(p1.graphics).toEqual({ x: 72, y: 172 });

    const p2 = net.places.find((p) => p.id === "p2")!;
    expect(p2.name).toBe("Output");
    expect(p2.tokens).toBe(0);
  });

  it("parses transitions with toolspecific parameters", () => {
    const { data: net } = parsePnml(SAMPLE_PNML);
    expect(net.transitions).toHaveLength(1);

    const t1 = net.transitions[0];
    expect(t1.id).toBe("t1");
    expect(t1.name).toBe("Process");
    expect(t1.mean_delay).toBe(5);
    expect(t1.distribution).toBe("exp");
    expect(t1.priority).toBe(2);
    // Same center-anchor conversion, using the transition's own size (28x64).
    expect(t1.graphics).toEqual({ x: 186, y: 168 });
  });

  it("parses arcs with weight", () => {
    const { data: net } = parsePnml(SAMPLE_PNML);
    expect(net.arcs).toHaveLength(2);

    const a1 = net.arcs.find((a) => a.id === "a1")!;
    expect(a1.source_id).toBe("p1");
    expect(a1.target_id).toBe("t1");
    expect(a1.weight).toBe(1);

    const a2 = net.arcs.find((a) => a.id === "a2")!;
    expect(a2.source_id).toBe("t1");
    expect(a2.target_id).toBe("p2");
    expect(a2.weight).toBe(2);
  });

  it("throws on invalid PNML (missing root)", () => {
    expect(() => parsePnml("<notpnml/>")).toThrow("missing <pnml>");
  });

  it("handles probability-based transitions", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Prob Net</text></name>
    <transition id="t1">
      <name><text>Branch</text></name>
      <toolspecific tool="PetriObjModel" version="1.0">
        <coordinates x="50" y="50"/>
        <probability>0.7</probability>
      </toolspecific>
      <graphics><position x="50" y="50"/></graphics>
    </transition>
  </net>
</pnml>`;
    const { data: net } = parsePnml(xml);
    const t = net.transitions[0];
    expect(t.probability).toBe(0.7);
    expect(t.distribution).toBeNull();
  });
});

describe("exportPnml", () => {
  it("produces valid XML that can be re-parsed", () => {
    const { data: net } = parsePnml(SAMPLE_PNML);
    const xml = exportPnml(net);
    const { data: reparsed } = parsePnml(xml);
    expect(reparsed.name).toBe(net.name);
    expect(reparsed.places).toHaveLength(net.places.length);
    expect(reparsed.transitions).toHaveLength(net.transitions.length);
    expect(reparsed.arcs).toHaveLength(net.arcs.length);
  });

  it("round-trips place data", () => {
    const { data: net } = parsePnml(SAMPLE_PNML);
    const xml = exportPnml(net);
    const { data: reparsed } = parsePnml(xml);

    for (const orig of net.places) {
      const rt = reparsed.places.find((p) => p.id === orig.id)!;
      expect(rt.name).toBe(orig.name);
      expect(rt.tokens).toBe(orig.tokens);
      expect(rt.graphics.x).toBe(orig.graphics.x);
      expect(rt.graphics.y).toBe(orig.graphics.y);
    }
  });

  it("round-trips transition parameters", () => {
    const { data: net } = parsePnml(SAMPLE_PNML);
    const xml = exportPnml(net);
    const { data: reparsed } = parsePnml(xml);

    for (const orig of net.transitions) {
      const rt = reparsed.transitions.find((t) => t.id === orig.id)!;
      expect(rt.name).toBe(orig.name);
      expect(rt.distribution).toBe(orig.distribution);
      expect(rt.mean_delay).toBe(orig.mean_delay);
      expect(rt.priority).toBe(orig.priority);
    }
  });

  it("round-trips arc data", () => {
    const { data: net } = parsePnml(SAMPLE_PNML);
    const xml = exportPnml(net);
    const { data: reparsed } = parsePnml(xml);

    for (const orig of net.arcs) {
      const rt = reparsed.arcs.find((a) => a.id === orig.id)!;
      expect(rt.source_id).toBe(orig.source_id);
      expect(rt.target_id).toBe(orig.target_id);
      expect(rt.weight).toBe(orig.weight);
    }
  });
});

describe("parsePnml, composed documents", () => {
  it("reads every page as an object, not just the first", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Composed Net</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="First" priority="3" x="5" y="6"/>
      </toolspecific>
      <place id="p1"><name><text>P1</text></name><graphics><position x="0" y="0"/></graphics></place>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="Second" priority="0" x="7" y="8"/>
      </toolspecific>
      <place id="p2"><name><text>P2</text></name><graphics><position x="0" y="0"/></graphics></place>
    </page>
  </net>
</pnml>`;
    const { data: net } = parsePnml(xml);
    expect(net.objects?.map((o) => o.name)).toEqual(["First", "Second"]);
    expect(net.objects?.[0].priority).toBe(3);
    expect(net.places.map((p) => p.id)).toEqual(["p1", "p2"]);
    expect(net.places[1].objectId).toBe("object1");
  });

  it("restores a fused-away place from the reference node standing in for it", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Composed Net</text></name>
    <page id="object0">
      <place id="p1"><name><text>P1</text></name><graphics><position x="0" y="0"/></graphics></place>
    </page>
    <page id="object1">
      <referencePlace id="p2" ref="p1">
        <name><text>P2</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>fusion</referenceRole>
          <fusedInitialMarking>4</fusedInitialMarking>
        </toolspecific>
      </referencePlace>
    </page>
  </net>
</pnml>`;
    const { data: net } = parsePnml(xml);
    // The canvas draws both members of a fusion; the document draws one.
    expect(net.places.map((p) => p.id)).toEqual(["p1", "p2"]);
    expect(net.places[1].tokens).toBe(4);
  });

  it("still parses every existing single-page case", () => {
    expect(() => parsePnml(SAMPLE_PNML)).not.toThrow();
    const { data: net } = parsePnml(SAMPLE_PNML);
    expect(net.places).toHaveLength(2);
    expect(net.transitions).toHaveLength(1);
    expect(net.arcs).toHaveLength(2);
  });
});

describe("round-trip from scratch", () => {
  it("preserves a programmatically built net through export and re-import", () => {
    const net: PetriNetData = {
      name: "Scratch Net",
      places: [
        { id: "p1", name: "Start", tokens: 5, graphics: { x: 10, y: 20 } },
        { id: "p2", name: "End", tokens: 0, graphics: { x: 300, y: 20 } },
      ],
      transitions: [
        {
          id: "t1",
          name: "Go",
          priority: 3,
          distribution: "norm",
          mean_delay: 2.5,
          standard_deviation: 0.5,
          probability: null,
          graphics: { x: 150, y: 20 },
        },
      ],
      arcs: [
        { id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" },
        { id: "a2", source_id: "t1", target_id: "p2", weight: 3, arc_type: "NORMAL" },
      ],
    };

    const xml = exportPnml(net);
    const { data: reparsed } = parsePnml(xml);

    expect(reparsed.name).toBe("Scratch Net");
    expect(reparsed.places[0].tokens).toBe(5);
    expect(reparsed.transitions[0].distribution).toBe("norm");
    expect(reparsed.transitions[0].mean_delay).toBe(2.5);
    expect(reparsed.transitions[0].standard_deviation).toBe(0.5);
    expect(reparsed.arcs[1].weight).toBe(3);
  });
});

describe("composed PNML round trip", () => {
  /** Two objects sharing a place, plus one cross-object arc of each direction. */
  function composedNet(): PetriNetData {
    const place = (id: string, tokens: number, objectId: string) => ({
      id, name: id.toUpperCase(), tokens, graphics: { x: 10, y: 20 }, objectId,
    });
    const transition = (id: string, objectId: string) => ({
      id, name: id.toUpperCase(), priority: 1, distribution: "exp" as const,
      mean_delay: 1, standard_deviation: 0, probability: null,
      graphics: { x: 30, y: 40 }, objectId,
    });
    return {
      name: "Composed",
      places: [
        place("a_p0", 2, "oA"), place("a_p1", 0, "oA"),
        place("b_p0", 0, "oB"), place("b_p1", 0, "oB"),
      ],
      transitions: [transition("a_t0", "oA"), transition("b_t0", "oB")],
      arcs: [
        { id: "a_arc0", source_id: "a_p0", target_id: "a_t0", weight: 1, arc_type: "NORMAL" },
        { id: "a_arc1", source_id: "a_t0", target_id: "a_p1", weight: 1, arc_type: "NORMAL" },
        { id: "b_arc0", source_id: "b_p0", target_id: "b_t0", weight: 1, arc_type: "NORMAL" },
        { id: "b_arc1", source_id: "b_t0", target_id: "b_p1", weight: 1, arc_type: "NORMAL" },
      ],
      objects: [
        { id: "oA", name: "A", priority: 2, graphics: { x: 0, y: 0, width: 100, height: 80 } },
        { id: "oB", name: "B", priority: 5, graphics: { x: 200, y: 0, width: 100, height: 80 } },
      ],
      links: [
        { id: "l0", type: "placeFusion", sourceId: "b_p0", targetId: "a_p1", quantity: 1 },
        // Not placeToTransition: PetriObjModelPaint retired that link type, and
        // the exporter now refuses a request that has one (PNML ISO
        // conformance contract, decision 4). transitionToPlace exercises the
        // same arc-like (representative node + link arc) projection.
        { id: "l1", type: "transitionToPlace", sourceId: "a_t0", targetId: "b_p1", quantity: 2 },
      ],
    };
  }

  it("survives export and re-import with its objects, links and markings intact", () => {
    const { data: back } = parsePnml(exportPnml(composedNet()));

    expect(back.name).toBe("Composed");
    expect(back.objects?.map((o) => o.name)).toEqual(["A", "B"]);
    expect(back.objects?.map((o) => o.priority)).toEqual([2, 5]);

    // Both members of the fusion come back, though the document only draws one.
    const ids = back.places.map((p) => p.id).sort();
    expect(ids).toEqual(["a_p0", "a_p1", "b_p0", "b_p1"]);
    expect(back.places.find((p) => p.id === "a_p0")?.tokens).toBe(2);

    // Every element still knows which object it belongs to.
    expect(back.places.find((p) => p.id === "b_p1")?.objectId).toBeTruthy();

    // The links are read once, from the declaration, never doubled by the arcs
    // that realise them.
    expect(back.links?.length).toBe(2);
    const fusion = back.links?.find((l) => l.type === "placeFusion");
    expect(fusion?.targetId).toBe("a_p1");
    const feed = back.links?.find((l) => l.type === "transitionToPlace");
    expect(feed?.quantity).toBe(2);

    // Only each object's own arcs; the link arc is not one of them.
    expect(back.arcs.length).toBe(4);
  });

  it("leaves a flat net on the flat path, unchanged", () => {
    const flat: PetriNetData = {
      name: "Flat",
      places: [{ id: "p1", name: "P1", tokens: 1, graphics: { x: 0, y: 0 } }],
      transitions: [{
        id: "t1", name: "T1", priority: 1, distribution: "exp", mean_delay: 1,
        standard_deviation: 0, probability: null, graphics: { x: 10, y: 0 },
      }],
      arcs: [{ id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" }],
    };
    const { data: back } = parsePnml(exportPnml(flat));
    expect(back.objects).toBeUndefined();
    expect(back.links).toBeUndefined();
    expect(back.places.length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Arc kinds. An inhibitor or read arc has no P/T-net form, so it only survives
// a save in a tool-specific block — and three different blocks say it, because
// the desktop's PnmlParser.parseArcs accepts three.
// ---------------------------------------------------------------------------

describe("arc type round trip", () => {
  function kindsNet(): PetriNetData {
    return {
      name: "Kinds",
      places: [
        { id: "p1", name: "P1", tokens: 1, graphics: { x: 0, y: 0 } },
        { id: "p2", name: "P2", tokens: 0, graphics: { x: 0, y: 60 } },
      ],
      transitions: [{
        id: "t1", name: "T1", priority: 1, distribution: "exp", mean_delay: 1,
        standard_deviation: 0, probability: null, graphics: { x: 60, y: 0 },
      }],
      arcs: [
        { id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "INHIBITOR" },
        { id: "a2", source_id: "p2", target_id: "t1", weight: 2, arc_type: "READ" },
        { id: "a3", source_id: "t1", target_id: "p2", weight: 1, arc_type: "NORMAL" },
      ],
    };
  }

  it("preserves INHIBITOR and READ through a flat export and re-import", () => {
    const { data: back } = parsePnml(exportPnml(kindsNet()));
    expect(back.arcs.find((a) => a.id === "a1")?.arc_type).toBe("INHIBITOR");
    expect(back.arcs.find((a) => a.id === "a2")?.arc_type).toBe("READ");
    expect(back.arcs.find((a) => a.id === "a2")?.weight).toBe(2);
    expect(back.arcs.find((a) => a.id === "a3")?.arc_type).toBe("NORMAL");
  });

  it("preserves INHIBITOR and READ on an object's own arcs through a composed round trip", () => {
    const flat = kindsNet();
    const net: PetriNetData = {
      ...flat,
      places: [
        ...flat.places.map((p) => ({ ...p, objectId: "oA" })),
        { id: "q1", name: "Q1", tokens: 0, graphics: { x: 400, y: 0 }, objectId: "oB" },
      ],
      transitions: flat.transitions.map((t) => ({ ...t, objectId: "oA" })),
      objects: [
        { id: "oA", name: "A", priority: 0, graphics: { x: 0, y: 0, width: 200, height: 200 } },
        { id: "oB", name: "B", priority: 0, graphics: { x: 300, y: 0, width: 200, height: 200 } },
      ],
      links: [{ id: "l0", type: "transitionToPlace", sourceId: "t1", targetId: "q1", quantity: 1 }],
    };

    const { data: back } = parsePnml(exportPnml(net));
    expect(back.arcs.find((a) => a.id === "a1")?.arc_type).toBe("INHIBITOR");
    expect(back.arcs.find((a) => a.id === "a2")?.arc_type).toBe("READ");
    expect(back.arcs.find((a) => a.id === "a3")?.arc_type).toBe("NORMAL");
  });

  it("reads the arc kind from a foreign document's shapes", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Foreign</text></name>
    <place id="p1"><name><text>P1</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="byAttribute" source="p1" target="t1" type="read">
      <inscription><text>1</text></inscription>
    </arc>
    <arc id="byToolspecific" source="p1" target="t1">
      <inscription><text>1</text></inscription>
      <toolspecific tool="PetriObjModel" version="1.0">
        <arcType>Inhibitor</arcType>
      </toolspecific>
    </arc>
    <arc id="byStandardType" source="p1" target="t1">
      <inscription><text>1</text></inscription>
      <type value="inhibitorArc"/>
    </arc>
  </net>
</pnml>`;
    const { data: net } = parsePnml(xml);
    expect(net.arcs.find((a) => a.id === "byAttribute")?.arc_type).toBe("READ");
    // Case-insensitive, like PnmlParser.parseArcs.
    expect(net.arcs.find((a) => a.id === "byToolspecific")?.arc_type).toBe("INHIBITOR");
    expect(net.arcs.find((a) => a.id === "byStandardType")?.arc_type).toBe("INHIBITOR");
  });
});

// ---------------------------------------------------------------------------
// The v2.2 <petriObject> marker: the frame's own shape, its collapse, its nest
// and the free-elements bucket. None of it changes what the model computes, so
// the simulator never looks at it — but a save that dropped it would come back
// as a differently-shaped canvas, which to the user is the same kind of loss
// as a missing arc.
// ---------------------------------------------------------------------------

describe("petriObject v2.2 attributes", () => {
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

  /**
   * Two objects joined by a link — the smallest canvas that takes the composed
   * export path at all, so a test can add whatever third frame it is about.
   */
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

  it("round-trips a parent/child/grandchild nest", () => {
    const net: PetriNetData = {
      name: "Nested",
      places: [place("pOuter", "oOuter"), place("pMiddle", "oMiddle"), place("pInner", "oInner")],
      transitions: [transition("tOuter", "oOuter")],
      arcs: [],
      objects: [
        frame("oOuter", "Outer", 0),
        { ...frame("oMiddle", "Middle", 20), objectId: "oOuter" },
        { ...frame("oInner", "Inner", 40), objectId: "oMiddle" },
      ],
      links: [
        { id: "l0", type: "transitionToPlace", sourceId: "tOuter", targetId: "pMiddle", quantity: 1 },
      ],
    };

    const { data: back } = parsePnml(exportPnml(net));
    const byName = new Map(back.objects!.map((o) => [o.name, o]));
    expect([...byName.keys()]).toEqual(["Outer", "Middle", "Inner"]);
    expect(byName.get("Outer")!.objectId).toBeUndefined();
    expect(byName.get("Middle")!.objectId).toBe(byName.get("Outer")!.id);
    expect(byName.get("Inner")!.objectId).toBe(byName.get("Middle")!.id);
  });

  it("round-trips a collapsed frame with the bounds it reopens into", () => {
    const net = linkedPair();
    net.objects![0].collapsed = true;

    const { data: back } = parsePnml(exportPnml(net));
    expect(back.objects![0].collapsed).toBe(true);
    // Collapse only flips a boolean on the canvas, so what is written is the
    // expanded box, not whatever the collapsed frame happens to be drawn at.
    expect(back.objects![0].graphics).toEqual({ x: 10, y: 10, width: 200, height: 150 });
    expect(back.objects![1].collapsed).toBeUndefined();
  });

  it("round-trips a hand-resized frame as autoFit false, an auto-fitting one as absent", () => {
    const net = linkedPair();
    net.objects![0].autoFit = false;

    const { data: back } = parsePnml(exportPnml(net));
    expect(back.objects![0].autoFit).toBe(false);
    // Absent means "re-fit me", which is the default and says nothing.
    expect(back.objects![1].autoFit).toBeUndefined();
  });

  it("keeps free elements free instead of growing a frame for them", () => {
    const net = linkedPair();
    net.places.push(place("pFree"));
    net.transitions.push(transition("tFree"));
    net.arcs.push({ id: "aFree", source_id: "pFree", target_id: "tFree", weight: 1, arc_type: "NORMAL" });

    const { data: back } = parsePnml(exportPnml(net));
    expect(back.objects!.map((o) => o.name)).toEqual(["A", "B"]);
    expect(back.places.find((p) => p.id === "pFree")?.objectId).toBeUndefined();
    expect(back.transitions.find((t) => t.id === "tFree")?.objectId).toBeUndefined();
    expect(back.arcs.map((a) => a.id).sort()).toEqual(["aA", "aFree"]);
  });

  it("keeps a container frame that holds only child frames", () => {
    const net = linkedPair();
    net.objects!.unshift(frame("oC", "Container", 500));
    net.objects![1].objectId = "oC";

    const { data: back } = parsePnml(exportPnml(net));
    const byName = new Map(back.objects!.map((o) => [o.name, o]));
    expect([...byName.keys()]).toEqual(["Container", "A", "B"]);
    expect(byName.get("A")!.objectId).toBe(byName.get("Container")!.id);
  });

  it("keeps a deliberately empty frame", () => {
    const net = linkedPair();
    net.objects!.push(frame("oEmpty", "Empty", 600));

    const { data: back } = parsePnml(exportPnml(net));
    expect(back.objects!.map((o) => o.name)).toEqual(["A", "B", "Empty"]);
    expect(back.objects![2].graphics).toEqual({ x: 600, y: 10, width: 200, height: 150 });
  });

  it("leaves a frame top-level when a page encloses nothing", () => {
    // A page that sits directly under the net has no enclosing object, so its
    // frame is top-level. The parentObject values here say otherwise and are
    // not read: the hierarchy is the page structure or it is nothing.
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Broken nest</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="Self" priority="0" x="10" y="10" width="80" height="80" parentObject="0"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="Stray" priority="0" x="10" y="10" width="80" height="80" parentObject="7"/>
      </toolspecific>
      <place id="p1"><name><text>P1</text></name></place>
    </page>
  </net>
</pnml>`;
    const { data: net } = parsePnml(xml);
    expect(net.objects!.map((o) => o.objectId)).toEqual([undefined, undefined]);
  });

  it("orders pages by their petriObject index, not by where they sit in the file", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Shuffled</text></name>
    <page id="second">
      <toolspecific tool="PetriObjModel" version="2.0">
        <petriObject index="1" name="Second" priority="0" x="300" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="q0"><name><text>Q0</text></name></place>
      <transition id="u0"><name><text>U0</text></name></transition>
    </page>
    <page id="first">
      <toolspecific tool="PetriObjModel" version="2.0">
        <petriObject index="0" name="First" priority="0" x="0" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
      <transition id="t0"><name><text>T0</text></name></transition>
    </page>
    <toolspecific tool="PetriObjModel" version="2.0">
      <petriObjectLinks>
        <link type="transitionToPlace" sourceObject="0" sourceElement="0" targetObject="1" targetElement="0" quantity="1"/>
      </petriObjectLinks>
    </toolspecific>
  </net>
</pnml>`;
    const { data: net } = parsePnml(xml);
    expect(net.objects!.map((o) => o.name)).toEqual(["First", "Second"]);
    // The positional declaration counts in that same index, so object 0's
    // transition 0 is T0 — reading the pages as written would make it U0.
    expect(net.links![0].sourceId).toBe("t0");
    expect(net.links![0].targetId).toBe("q0");
  });
});

// ---------------------------------------------------------------------------
// Where the links come from. A document carrying reference nodes states its
// composition in the standard's own terms, which is the only part of it a
// reader that is not this tool can see — so that is the authority, and the
// tool-specific declaration is left to say what the structure cannot.
// ---------------------------------------------------------------------------

describe("structure-first link parsing", () => {
  /** Compares links by what they mean, not by the ids the reader hands out. */
  const meaning = (net: PetriNetData) =>
    (net.links ?? []).map((l) => ({
      type: l.type,
      sourceId: l.sourceId,
      targetId: l.targetId,
      quantity: l.quantity,
      informational: l.informational ?? false,
    }));

  /**
   * A conformant document stating one link of every kind purely structurally:
   * object A feeds B's place, tests B's transition without consuming, and B's
   * first place *is* A's second one. What the net-level block declares on top
   * of that is up to each test.
   */
  function conformantDoc(declared = ""): string {
    return `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Structured</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="150"/>
      </toolspecific>
      <place id="pA0"><name><text>PA0</text></name><initialMarking><text>3</text></initialMarking></place>
      <place id="pA1"><name><text>PA1</text></name></place>
      <transition id="tA0"><name><text>TA0</text></name></transition>
      <referencePlace id="refPB0" ref="pB0">
        <name><text>PB0</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>representative</referenceRole>
        </toolspecific>
      </referencePlace>
      <referenceTransition id="refTB0" ref="tB0">
        <name><text>TB0</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>representative</referenceRole>
        </toolspecific>
      </referenceTransition>
      <arc id="aA0" source="pA0" target="tA0"><inscription><text>1</text></inscription></arc>
      <arc id="lA0" source="tA0" target="refPB0"><inscription><text>3</text></inscription></arc>
      <arc id="lA1" source="pA0" target="refTB0">
        <inscription><text>2</text></inscription>
        <toolspecific tool="PetriObjModel" version="2.1">
          <informational>true</informational>
        </toolspecific>
      </arc>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="B" priority="0" x="300" y="0" width="200" height="150"/>
      </toolspecific>
      <place id="pB0"><name><text>PB0</text></name></place>
      <referencePlace id="pB1" ref="pA1">
        <name><text>PB1</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>fusion</referenceRole>
          <fusedInitialMarking>2</fusedInitialMarking>
        </toolspecific>
      </referencePlace>
      <transition id="tB0"><name><text>TB0</text></name></transition>
      <arc id="aB0" source="pB0" target="tB0"><inscription><text>1</text></inscription></arc>
    </page>
${declared}
  </net>
</pnml>`;
  }

  const structuralMeaning = [
    { type: "transitionToPlace", sourceId: "tA0", targetId: "pB0", quantity: 3, informational: false },
    { type: "placeToTransition", sourceId: "pA0", targetId: "tB0", quantity: 2, informational: true },
    { type: "placeFusion", sourceId: "pB1", targetId: "pA1", quantity: 1, informational: false },
  ];

  it("reads every link from the reference nodes alone, with no declared block", () => {
    const { data: net } = parsePnml(conformantDoc());
    expect(meaning(net)).toEqual(structuralMeaning);
    // The arcs that realise a link are the link, not arcs of anyone's net.
    expect(net.arcs.map((a) => a.id)).toEqual(["aA0", "aB0"]);
    // The fused-away place comes back with the marking parked on its stand-in.
    expect(net.places.find((p) => p.id === "pB1")?.tokens).toBe(2);
  });

  it("lets the structure win over a declaration that disagrees on quantity", () => {
    const { data: net } = parsePnml(conformantDoc(`    <toolspecific tool="PetriObjModel" version="2.1">
      <petriObjectLinks>
        <link type="transitionToPlace" sourceObject="0" sourceElement="0" sourceElementId="tA0"
              targetObject="1" targetElement="0" targetElementId="pB0" quantity="99"/>
      </petriObjectLinks>
    </toolspecific>`));
    // Structure is what every other reader of this document sees.
    expect(meaning(net)).toEqual(structuralMeaning);
  });

  it("keeps a declared directional link the structure does not state", () => {
    const { data: net } = parsePnml(conformantDoc(`    <toolspecific tool="PetriObjModel" version="2.1">
      <petriObjectLinks>
        <link type="placeToTransition" sourceObject="1" sourceElement="0" sourceElementId="pB0"
              targetObject="0" targetElement="0" targetElementId="tA0" quantity="5" informational="false"/>
      </petriObjectLinks>
    </toolspecific>`));
    expect(meaning(net)).toEqual([
      ...structuralMeaning,
      { type: "placeToTransition", sourceId: "pB0", targetId: "tA0", quantity: 5, informational: false },
    ]);
  });

  it("drops a declared fusion the structure does not state", () => {
    const { data: net } = parsePnml(conformantDoc(`    <toolspecific tool="PetriObjModel" version="2.1">
      <petriObjectLinks>
        <link type="placeFusion" sourceObject="0" sourceElement="0" sourceElementId="pA0"
              targetObject="1" targetElement="0" targetElementId="pB0"/>
      </petriObjectLinks>
    </toolspecific>`));
    // Fusion is destructive and not idempotent, so it gets one source of truth.
    expect(meaning(net)).toEqual(structuralMeaning);
  });

  it("infers a role for reference nodes that carry none", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Foreign structure</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="150"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
      <transition id="t0"><name><text>T0</text></name></transition>
      <referenceTransition id="rt" ref="u0"><name><text>U0</text></name></referenceTransition>
      <arc id="a0" source="p0" target="t0"><inscription><text>1</text></inscription></arc>
      <arc id="l0" source="p0" target="rt"><inscription><text>4</text></inscription></arc>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="B" priority="0" x="300" y="0" width="200" height="150"/>
      </toolspecific>
      <place id="q0"><name><text>Q0</text></name></place>
      <referencePlace id="q1" ref="p0"><name><text>Q1</text></name></referencePlace>
      <transition id="u0"><name><text>U0</text></name></transition>
    </page>
  </net>
</pnml>`;
    const { data: net } = parsePnml(xml);
    // An arc touches the reference transition, so it is a stand-in; no arc
    // touches the reference place, so it is only there to be shared.
    expect(meaning(net)).toEqual([
      { type: "placeToTransition", sourceId: "p0", targetId: "u0", quantity: 4, informational: false },
      { type: "placeFusion", sourceId: "q1", targetId: "p0", quantity: 1, informational: false },
    ]);
    expect(net.places.map((p) => p.id)).toEqual(["p0", "q0", "q1"]);
    expect(net.arcs.map((a) => a.id)).toEqual(["a0"]);
  });

  /** A pre-conformance document: no reference nodes, links declared positionally. */
  function legacyDoc(): string {
    return `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Legacy</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.0">
        <petriObject index="0" name="First" priority="0" x="0" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
      <place id="p1"><name><text>P1</text></name></place>
      <transition id="t0"><name><text>T0</text></name></transition>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.0">
        <petriObject index="1" name="Second" priority="0" x="300" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="q0"><name><text>Q0</text></name></place>
      <transition id="u0"><name><text>U0</text></name></transition>
    </page>
    <toolspecific tool="PetriObjModel" version="2.0">
      <petriObjectLinks>
        <link type="placeFusion" sourceObject="0" sourceElement="1" targetObject="1" targetElement="0"/>
        <link type="transitionToPlace" sourceObject="0" sourceElement="0" targetObject="1" targetElement="0" quantity="4"/>
        <link type="placeToTransition" sourceObject="1" sourceElement="0" targetObject="0" targetElement="0" quantity="lots" informational="true"/>
      </petriObjectLinks>
    </toolspecific>
  </net>
</pnml>`;
  }

  it("still reads a legacy v2.0 document from its positional declaration", () => {
    const { data: net } = parsePnml(legacyDoc());
    // Nothing is dropped here: with no structure to be the authority, the
    // declaration is the only thing the document says, fusions included.
    expect(meaning(net).slice(0, 2)).toEqual([
      { type: "placeFusion", sourceId: "p1", targetId: "q0", quantity: 1, informational: false },
      { type: "transitionToPlace", sourceId: "t0", targetId: "q0", quantity: 4, informational: false },
    ]);
  });

  it("falls back to quantity 1 for a declaration that does not parse as a number", () => {
    const { data: net } = parsePnml(legacyDoc());
    expect(meaning(net)[2]).toEqual({
      type: "placeToTransition", sourceId: "q0", targetId: "t0", quantity: 1, informational: true,
    });
  });

  it("reproduces fusions and crossing links through its own export and re-import", () => {
    const place = (id: string, tokens: number, objectId: string): PetriPlace => ({
      id, name: id.toUpperCase(), tokens, graphics: { x: 10, y: 20 }, objectId,
    });
    const transition = (id: string, objectId: string): PetriTransition => ({
      id, name: id.toUpperCase(), priority: 1, distribution: "exp" as const,
      mean_delay: 1, standard_deviation: 0, probability: null,
      graphics: { x: 30, y: 40 }, objectId,
    });
    const frame = (id: string, name: string, x: number): ObjectFrame => ({
      id, name, priority: 0, graphics: { x, y: 0, width: 150, height: 120 },
    });

    const net: PetriNetData = {
      name: "Crossing",
      places: [
        place("a_p0", 2, "oA"), place("a_p1", 0, "oA"),
        place("b_p0", 0, "oB"), place("b_p1", 0, "oB"),
        place("c_p0", 1, "oC"),
      ],
      transitions: [transition("a_t0", "oA"), transition("b_t0", "oB"), transition("c_t0", "oC")],
      arcs: [
        { id: "a_arc0", source_id: "a_p0", target_id: "a_t0", weight: 1, arc_type: "NORMAL" },
        { id: "b_arc0", source_id: "b_p0", target_id: "b_t0", weight: 1, arc_type: "NORMAL" },
        { id: "c_arc0", source_id: "c_p0", target_id: "c_t0", weight: 1, arc_type: "NORMAL" },
      ],
      objects: [frame("oA", "A", 0), frame("oB", "B", 200), frame("oC", "C", 400)],
      links: [
        { id: "l0", type: "placeFusion", sourceId: "b_p0", targetId: "a_p1", quantity: 1 },
        // Not placeToTransition: PetriObjModelPaint retired that link type,
        // and the exporter now refuses a request that has one (PNML ISO
        // conformance contract, decision 4). A second transitionToPlace link
        // still exercises "more than one crossing link" just as well.
        { id: "l1", type: "transitionToPlace", sourceId: "a_t0", targetId: "c_p0", quantity: 2 },
        { id: "l2", type: "transitionToPlace", sourceId: "c_t0", targetId: "b_p1", quantity: 3 },
      ],
    };

    const { data: back } = parsePnml(exportPnml(net));
    // Link ids are the reader's own; what has to survive is what they mean.
    const sort = (rows: ReturnType<typeof meaning>) =>
      [...rows].sort((x, y) => `${x.type}${x.sourceId}${x.targetId}`.localeCompare(`${y.type}${y.sourceId}${y.targetId}`));
    expect(sort(meaning(back))).toEqual(sort(meaning(net)));
    expect(back.arcs.map((a) => a.id).sort()).toEqual(["a_arc0", "b_arc0", "c_arc0"]);
  });
});

describe("declared links whose endpoints are not the kind the type requires", () => {
  const doc = (link: string) => `<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Legacy</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p1"><name><text>P1</text></name></place>
      <transition id="t1"><name><text>T1</text></name></transition>
    </page>
    <page id="object1">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="B" priority="0" x="400" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p2"><name><text>P2</text></name></place>
      <transition id="t2"><name><text>T2</text></name></transition>
    </page>
    <toolspecific tool="PetriObjModel" version="2.1">
      <petriObjectLinks>
        ${link}
      </petriObjectLinks>
    </toolspecific>
  </net>
</pnml>`;

  it("keeps a declaration whose endpoints match its type", () => {
    const { data: net } = parsePnml(
      doc('<link type="transitionToPlace" sourceObject="0" sourceElement="0" sourceElementId="t1" targetObject="1" targetElement="0" targetElementId="p2" quantity="1"/>'),
    );
    expect(net.links).toHaveLength(1);
    expect(net.links![0]).toMatchObject({ type: "transitionToPlace", sourceId: "t1", targetId: "p2" });
  });

  it("drops one that names a transition where the type requires a place", () => {
    // The rest of the document still opens. Kept, this produced a link that
    // indexed an object's places with a position taken from its transitions,
    // and exporting it threw rather than writing a file.
    const { data: net } = parsePnml(
      doc('<link type="transitionToPlace" sourceObject="0" sourceElement="0" sourceElementId="t1" targetObject="1" targetElement="0" targetElementId="t2" quantity="1"/>'),
    );
    expect(net.links ?? []).toHaveLength(0);
    expect(net.places.map((p) => p.id)).toEqual(["p1", "p2"]);
    expect(net.objects).toHaveLength(2);
  });

  it("drops a fusion that names a transition", () => {
    const { data: net } = parsePnml(
      doc('<link type="placeFusion" sourceObject="0" sourceElement="0" sourceElementId="p1" targetObject="1" targetElement="0" targetElementId="t2"/>'),
    );
    expect(net.links ?? []).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// A document is held to the same five rules the editor gesture is
// (rejectionForFusion, petri-object-model.ts). A hand-written or foreign-tool
// file has no gesture stopping it from declaring a fusion the canvas itself
// could never draw; these fixtures use the legacy, position/id-addressed
// <petriObjectLinks> declaration (declaredLinks), which is exactly the shape
// such a file states a link in: unlike a <referencePlace>'s own ref chain,
// it carries no built-in cycle or duplicate-master detection at all.
// ---------------------------------------------------------------------------

describe("documents are held to the same fusion rules as the editor", () => {
  /** Three objects, each with one place, and a declared petriObjectLinks block. */
  function threeObjectDoc(links: string): string {
    const object = (index: number, name: string, placeId: string) => `
    <page id="${placeId}_page">
      <toolspecific tool="PetriObjModel" version="2.0">
        <petriObject index="${index}" name="${name}" priority="0" x="${index * 200}" y="0" width="100" height="100"/>
      </toolspecific>
      <place id="${placeId}"><name><text>${placeId.toUpperCase()}</text></name></place>
    </page>`;
    return `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Legacy fusions</text></name>
    ${object(0, "A", "p1")}${object(1, "B", "p2")}${object(2, "C", "p3")}
    <toolspecific tool="PetriObjModel" version="2.0">
      <petriObjectLinks>
        ${links}
      </petriObjectLinks>
    </toolspecific>
  </net>
</pnml>`;
  }

  const fusionLink = (sourceId: string, targetId: string) =>
    `<link type="placeFusion" sourceElementId="${sourceId}" targetElementId="${targetId}"/>`;

  it("drops the link that closes a cycle, keeping every link stated before it", () => {
    // p1 copies p2, p2 copies p3: legal so far. p3 copying p1 back closes the
    // loop, and is the third and last of the three to be declared.
    const xml = threeObjectDoc(
      [fusionLink("p1", "p2"), fusionLink("p2", "p3"), fusionLink("p3", "p1")].join("\n        "),
    );
    const { data: net, warnings } = parsePnml(xml);

    expect(net.links?.map((l) => `${l.sourceId}->${l.targetId}`)).toEqual(["p1->p2", "p2->p3"]);

    const fusionWarnings = warnings.filter((w) => w.code === "rejected-fusion");
    expect(fusionWarnings).toHaveLength(1);
    // Both endpoints, and the reason, in the message.
    expect(fusionWarnings[0].message).toContain('"P1" (id "p1")');
    expect(fusionWarnings[0].message).toContain('"P3" (id "p3")');
    expect(fusionWarnings[0].message).toContain("that would make a loop of links, where each place copies the next");
  });

  it("keeps the first master a copy claims and drops a second, contradictory one", () => {
    // p1 copying p2 is declared first; p1 copying p3 as well is declared
    // second and contradicts it: a place can repeat only a single source.
    const xml = threeObjectDoc([fusionLink("p1", "p2"), fusionLink("p1", "p3")].join("\n        "));
    const { data: net, warnings } = parsePnml(xml);

    expect(net.links?.map((l) => `${l.sourceId}->${l.targetId}`)).toEqual(["p1->p2"]);

    const fusionWarnings = warnings.filter((w) => w.code === "rejected-fusion");
    expect(fusionWarnings).toHaveLength(1);
    expect(fusionWarnings[0].message).toContain('"P1" (id "p1")');
    expect(fusionWarnings[0].message).toContain('"P3" (id "p3")');
    expect(fusionWarnings[0].message).toContain(
      "that place already copies another one; a place can repeat a single source",
    );
  });

  it("imports a well-formed fan of three copies with all links kept and no warnings", () => {
    // One master on the free-elements page, repeated by a copy in each of
    // three separate objects: legal in every direction, so nothing is dropped
    // and nothing warns. This is the case that must not regress.
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Fan</text></name>
    <page id="free">
      <place id="m"><name><text>M</text></name><initialMarking><text>3</text></initialMarking></place>
    </page>
    <page id="objectA">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="100" height="100"/>
      </toolspecific>
      <referencePlace id="c1" ref="m">
        <name><text>C1</text></name>
        <toolspecific tool="PetriObjModel" version="2.1"><referenceRole>fusion</referenceRole></toolspecific>
      </referencePlace>
    </page>
    <page id="objectB">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="1" name="B" priority="0" x="200" y="0" width="100" height="100"/>
      </toolspecific>
      <referencePlace id="c2" ref="m">
        <name><text>C2</text></name>
        <toolspecific tool="PetriObjModel" version="2.1"><referenceRole>fusion</referenceRole></toolspecific>
      </referencePlace>
    </page>
    <page id="objectC">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="2" name="C" priority="0" x="400" y="0" width="100" height="100"/>
      </toolspecific>
      <referencePlace id="c3" ref="m">
        <name><text>C3</text></name>
        <toolspecific tool="PetriObjModel" version="2.1"><referenceRole>fusion</referenceRole></toolspecific>
      </referencePlace>
    </page>
  </net>
</pnml>`;
    const { data: net, warnings } = parsePnml(xml);

    expect(net.links?.map((l) => `${l.sourceId}->${l.targetId}`).sort()).toEqual([
      "c1->m",
      "c2->m",
      "c3->m",
    ]);
    expect(warnings).toHaveLength(0);
  });
});

describe("where a document says one object is inside another", () => {
  const pageMarker = (index: number, name: string, parent?: number) =>
    `<toolspecific tool="PetriObjModel" version="2.2.2">
        <petriObject index="${index}" name="${name}" priority="0" x="0" y="0" width="200" height="160"${
          parent == null ? "" : ` parentObject="${parent}"`
        }/>
      </toolspecific>`;

  const place = (id: string) => `<place id="${id}"><name><text>${id}</text></name></place>`;

  /** The hierarchy said the way ISO/IEC 15909-2 says one. */
  const nested = `<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Nested</text></name>
    <page id="object0">${pageMarker(0, "Outer")}${place("p0")}
      <page id="object1">${pageMarker(1, "Middle")}${place("p1")}
        <page id="object2">${pageMarker(2, "Inner")}${place("p2")}</page>
      </page>
    </page>
  </net>
</pnml>`;

  /** The shape written before the pages nested: flat, with the old attribute. */
  const flatWithAttribute = `<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Flat</text></name>
    <page id="object0">${pageMarker(0, "Outer")}${place("p0")}</page>
    <page id="object1">${pageMarker(1, "Middle", 0)}${place("p1")}</page>
    <page id="object2">${pageMarker(2, "Inner", 1)}${place("p2")}</page>
  </net>
</pnml>`;

  const nest = (net: PetriNetData) =>
    (net.objects ?? [])
      .map((o) => `${o.name} in ${(net.objects ?? []).find((p) => p.id === o.objectId)?.name ?? "top"}`)
      .sort();

  it("reads the nest from the page structure", () => {
    const { data: net } = parsePnml(nested);
    expect(net.objects).toHaveLength(3);
    expect(nest(net)).toEqual(["Inner in Middle", "Middle in Outer", "Outer in top"]);
    expect(net.places.map((p) => p.id).sort()).toEqual(["p0", "p1", "p2"]);
  });

  it("gives a document no hierarchy just because it states parentObject", () => {
    // The attribute is neither written nor read any more: a document states its
    // hierarchy the way the standard states one, or it states none. Flat pages
    // are three top-level objects, which is what this document literally says
    // once the attribute means nothing. Pinned so the support cannot come back
    // by accident, and so the flattening reads as a decision rather than a bug.
    const { data: net } = parsePnml(flatWithAttribute);

    expect(net.objects).toHaveLength(3);
    expect(nest(net)).toEqual(["Inner in top", "Middle in top", "Outer in top"]);
    // Everything else about such a document still arrives.
    expect(net.places.map((p) => p.id).sort()).toEqual(["p0", "p1", "p2"]);
  });

  it("is not swayed by the attribute where a document nests as well", () => {
    const both = nested.replace(
      '<petriObject index="2" name="Inner" priority="0" x="0" y="0" width="200" height="160"/>',
      '<petriObject index="2" name="Inner" priority="0" x="0" y="0" width="200" height="160" parentObject="0"/>',
    );

    expect(nest(parsePnml(both).data)).toEqual(["Inner in Middle", "Middle in Outer", "Outer in top"]);
  });
});

// ---------------------------------------------------------------------------
// Soft validation (PNML ISO conformance contract, Part B): a file always
// opens if structurally possible, and every place where this reader had to
// reinterpret, remap or drop something instead of failing gets exactly one
// warning, naming the element and saying what was done. One test per code.
// ---------------------------------------------------------------------------

describe("import warnings", () => {
  const codesOf = (warnings: { code: string }[]) => warnings.map((w) => w.code);

  it("produces no warnings for a well-formed document", () => {
    const { warnings } = parsePnml(SAMPLE_PNML);
    expect(warnings).toEqual([]);
  });

  it("invalid-id: sanitizes an illegal id and rewrites every reference to it", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Bad ids</text></name>
    <place id="my place"><name><text>My Place</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="a1" source="my place" target="t1"><inscription><text>1</text></inscription></arc>
  </net>
</pnml>`;
    const { data: net, warnings } = parsePnml(xml);

    expect(net.places[0].id).toBe("my-place");
    // The remap is one shared pass: the arc's source resolves to the exact
    // same sanitized id the place itself was given.
    expect(net.arcs[0].source_id).toBe("my-place");
    expect(codesOf(warnings)).toContain("invalid-id");
    expect(warnings.find((w) => w.code === "invalid-id")?.message).toContain("my-place");
  });

  it("duplicate-id: keeps the first occurrence and suffixes every later one", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Duplicated</text></name>
    <place id="p1"><name><text>First</text></name></place>
    <place id="p1"><name><text>Second</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="a1" source="p1" target="t1"><inscription><text>1</text></inscription></arc>
  </net>
</pnml>`;
    const { data: net, warnings } = parsePnml(xml);

    expect(net.places.map((p) => p.id)).toEqual(["p1", "p1-2"]);
    expect(net.places[0].name).toBe("First");
    expect(net.places[1].name).toBe("Second");
    // A reference to the duplicated raw id keeps resolving to the first
    // occurrence, exactly as it already did before either place got an id of
    // its own.
    expect(net.arcs[0].source_id).toBe("p1");
    expect(codesOf(warnings)).toContain("duplicate-id");
  });

  it("dangling-ref: a reference node whose ref points nowhere warns and drops no link", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Dangling</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
      <referencePlace id="refX" ref="doesNotExist">
        <name><text>RefX</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>representative</referenceRole>
        </toolspecific>
      </referencePlace>
    </page>
  </net>
</pnml>`;
    const { data: net, warnings } = parsePnml(xml);

    expect(net.links ?? []).toHaveLength(0);
    expect(codesOf(warnings)).toContain("dangling-ref");
    const message = warnings.find((w) => w.code === "dangling-ref")?.message ?? "";
    expect(message).toContain("RefX");
    expect(message).toContain("doesNotExist");
  });

  it("dangling-ref: an arc touching an unresolved representative is dropped, not silently lost", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Dangling arc</text></name>
    <page id="object0">
      <toolspecific tool="PetriObjModel" version="2.1">
        <petriObject index="0" name="A" priority="0" x="0" y="0" width="200" height="160"/>
      </toolspecific>
      <place id="p0"><name><text>P0</text></name></place>
      <transition id="t0"><name><text>T0</text></name></transition>
      <referencePlace id="refX" ref="doesNotExist">
        <name><text>RefX</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>representative</referenceRole>
        </toolspecific>
      </referencePlace>
      <arc id="a0" source="p0" target="t0"><inscription><text>1</text></inscription></arc>
      <arc id="lost" source="t0" target="refX"><inscription><text>1</text></inscription></arc>
    </page>
  </net>
</pnml>`;
    const { data: net, warnings } = parsePnml(xml);

    // The ordinary arc survives; the one that only exists to reach the
    // unresolved representative is gone, but named in a warning rather than
    // vanishing without a trace.
    expect(net.arcs.map((a) => a.id)).toEqual(["a0"]);
    const dangling = warnings.filter((w) => w.code === "dangling-ref");
    expect(dangling.length).toBeGreaterThanOrEqual(2);
    expect(dangling.some((w) => w.message.includes("lost"))).toBe(true);
  });

  it("cross-page-arc: an own arc spanning two pages with no reference node is kept and flagged", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Crossing</text></name>
    <page id="page0">
      <place id="p0"><name><text>P0</text></name></place>
    </page>
    <page id="page1">
      <transition id="t1"><name><text>T1</text></name></transition>
      <arc id="a1" source="p0" target="t1"><inscription><text>1</text></inscription></arc>
    </page>
  </net>
</pnml>`;
    const { data: net, warnings } = parsePnml(xml);

    // Not dropped: the rule is violated, not the document's structure.
    expect(net.arcs.map((a) => a.id)).toEqual(["a1"]);
    expect(codesOf(warnings)).toContain("cross-page-arc");
  });

  it("cross-page-arc: an arc naming an element that only appears on a later page still resolves", () => {
    // page0's arc names "my node" before page1 ever declares it. A reader
    // that registered ids one page at a time, resolving each page's own arcs
    // before moving on, would still have nothing to resolve "my node"
    // against here, and would silently keep the raw, dangling string instead
    // of the id the transition ends up with, which also hides the
    // same-page-rule violation, since a dangling target has no page to
    // compare the source's page against.
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Forward reference</text></name>
    <page id="page0">
      <place id="p0"><name><text>P0</text></name></place>
      <arc id="a1" source="p0" target="my node"><inscription><text>1</text></inscription></arc>
    </page>
    <page id="page1">
      <transition id="my node"><name><text>My Node</text></name></transition>
    </page>
  </net>
</pnml>`;
    const { data: net, warnings } = parsePnml(xml);

    expect(net.transitions[0].id).toBe("my-node");
    // The arc's target is the very id the transition was given, not the raw,
    // dangling string a page-at-a-time reader would have kept.
    expect(net.arcs[0].target_id).toBe("my-node");
    expect(codesOf(warnings)).toContain("cross-page-arc");
  });

  it("bad-number: a malformed place marking defaults to 0 tokens", () => {
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Bad marking</text></name>
    <place id="p1"><name><text>P1</text></name><initialMarking><text>lots</text></initialMarking></place>
  </net>
</pnml>`;
    const { data: net, warnings } = parsePnml(xml);

    expect(net.places[0].tokens).toBe(0);
    expect(codesOf(warnings)).toContain("bad-number");
  });

  it("invalid-value: a negative initial marking clamps to 0 instead of going negative silently", () => {
    // ptnet initialMarking is a nonNegativeInteger. -5 parses as a number
    // fine, so this is a different problem from "lots" above, and gets a
    // different warning code, mirroring the arc-inscription-below-1 case.
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Negative marking</text></name>
    <place id="p1"><name><text>P1</text></name><initialMarking><text>-5</text></initialMarking></place>
  </net>
</pnml>`;
    const { data: net, warnings } = parsePnml(xml);

    expect(net.places[0].tokens).toBe(0);
    expect(codesOf(warnings)).toContain("invalid-value");
    expect(codesOf(warnings)).not.toContain("bad-number");
  });

  it("bad-number: a malformed transition priority falls back to 1, but an explicit 0 is not malformed", () => {
    const xml = (priorityText: string) => `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Priorities</text></name>
    <transition id="t1">
      <name><text>T1</text></name>
      <toolspecific tool="PetriObjModel" version="1.0">
        <priority>${priorityText}</priority>
      </toolspecific>
    </transition>
  </net>
</pnml>`;

    const malformed = parsePnml(xml("not-a-number"));
    expect(malformed.data.transitions[0].priority).toBe(1);
    expect(codesOf(malformed.warnings)).toContain("bad-number");

    // The || fallback this replaces treated an explicit 0 as parse failure;
    // it is a legal priority and must not warn.
    const explicitZero = parsePnml(xml("0"));
    expect(explicitZero.data.transitions[0].priority).toBe(0);
    expect(codesOf(explicitZero.warnings)).not.toContain("bad-number");
  });

  it("bad-number vs invalid-value: a malformed inscription and an explicit 0 both coerce to weight 1, differently", () => {
    const xml = (inscriptionText: string) => `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Inscriptions</text></name>
    <place id="p1"><name><text>P1</text></name></place>
    <transition id="t1"><name><text>T1</text></name></transition>
    <arc id="a1" source="p1" target="t1"><inscription><text>${inscriptionText}</text></inscription></arc>
  </net>
</pnml>`;

    const malformed = parsePnml(xml("many"));
    expect(malformed.data.arcs[0].weight).toBe(1);
    expect(codesOf(malformed.warnings)).toContain("bad-number");

    // A ptnet inscription is a positiveInteger: an explicit 0 parses fine as
    // a number but is not a legal weight, which is a different problem.
    const explicitZero = parsePnml(xml("0"));
    expect(explicitZero.data.arcs[0].weight).toBe(1);
    expect(codesOf(explicitZero.warnings)).toContain("invalid-value");
    expect(codesOf(explicitZero.warnings)).not.toContain("bad-number");
  });

  it("bad-number: a malformed fusedInitialMarking keeps the previously validated tokens", () => {
    // fusedInitialMarking lives in a fusion referencePlace's tool-specific
    // block, parked there by the exporter because the canvas draws both
    // fusion members but the document only draws one (the survivor).
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Composed Net</text></name>
    <page id="object0">
      <place id="p1"><name><text>P1</text></name></place>
    </page>
    <page id="object1">
      <referencePlace id="p2" ref="p1">
        <name><text>P2</text></name>
        <toolspecific tool="PetriObjModel" version="2.1">
          <referenceRole>fusion</referenceRole>
          <fusedInitialMarking>lots</fusedInitialMarking>
        </toolspecific>
      </referencePlace>
    </page>
  </net>
</pnml>`;
    const { data: net, warnings } = parsePnml(xml);

    // parsePlace already validated this place's own (absent) <initialMarking>
    // to 0; a malformed fusedInitialMarking must not clobber that with NaN.
    expect(net.places.find((p) => p.id === "p2")?.tokens).toBe(0);
    expect(codesOf(warnings)).toContain("bad-number");
    expect(
      warnings.find((w) => w.code === "bad-number" && w.message.includes("fused"))?.message,
    ).toContain("p2");
  });
});

// ---------------------------------------------------------------------------
// Cross-tool regression fixtures (PNML interop contract): real files the
// desktop tool itself wrote, not hand-authored approximations of its shape.
// A hand-written fixture can silently drift from what the desktop actually
// emits; these two exercise the importer against the genuine article.
// ---------------------------------------------------------------------------

describe("parsePnml, desktop interop fixtures", () => {
  it("reads a genuine PetriObjModelPaint 2.2.2 export: three-level nest, two fusions, a Free elements page, an invalid net id", () => {
    const { data: net, warnings } = parsePnml(loadFixture("desktop_export_new_petrinet.pnml"));

    // The only warning is about the net's own id ("New PetriNet" has a
    // space in it); every element id in the file is already a valid NCName,
    // so nothing else is remapped or warned about.
    expect(warnings).toHaveLength(1);
    expect(warnings[0].code).toBe("invalid-id");
    expect(warnings[0].message).toContain("New PetriNet");

    // Structure: three pages carry real petriObject geometry and become
    // frames, nested Object 1 inside Object 2 inside Object 3; the fourth
    // page ("Free elements") has an all-zero marker and stays the unframed
    // bucket rather than becoming a frame of its own.
    expect(net.objects).toHaveLength(3);
    const byName = (name: string) => net.objects!.find((o) => o.name === name)!;
    const object1 = byName("Object 1");
    const object2 = byName("Object 2");
    const object3 = byName("Object 3");
    expect(object1.objectId).toBe(object2.id);
    expect(object2.objectId).toBe(object3.id);
    expect(object3.objectId).toBeUndefined();

    // Element counts read straight off the fixture: 6 places (2 of them
    // restored fusion members), 3 transitions, 7 arcs, 2 fusion links.
    expect(net.places).toHaveLength(6);
    expect(net.transitions).toHaveLength(3);
    expect(net.arcs).toHaveLength(7);
    expect(net.links).toHaveLength(2);
    expect(net.links!.every((l) => l.type === "placeFusion")).toBe(true);
    const fusionPairs = net.links!.map((l) => `${l.sourceId}->${l.targetId}`).sort();
    expect(fusionPairs).toEqual([
      "p-p1-ec3eda7c->p-p2-6a033dc2",
      "p-p2-826b107f->p-p3-91569318",
    ]);

    // A nested-page member carries the objectId of the frame it sits in; a
    // Free-elements member carries none.
    const p3 = net.places.find((p) => p.id === "p-p3-91569318")!;
    expect(p3.objectId).toBe(object1.id);
    const freePlace = net.places.find((p) => p.id === "p-p1-2b462d12")!;
    expect(freePlace.objectId).toBeUndefined();

    // Center-to-top-left conversion, one place and one transition, both
    // inside the innermost nested page: wire (575,214) minus half the
    // place's own size (56x56) is (547,186); wire (507,214) minus half the
    // transition's own size (28x64) is (493,182).
    expect(p3.graphics).toEqual({ x: 547, y: 186 });
    const t2 = net.transitions.find((t) => t.id === "t-t2-7d188d05")!;
    expect(t2.graphics).toEqual({ x: 493, y: 182 });
  });

  it("reads a regenerated flat-dialect desktop export with zero warnings and the importer's fallback positions", () => {
    const { data: net, warnings } = parsePnml(loadFixture("desktop_export_flat.pnml"));

    expect(warnings).toHaveLength(0);
    expect(net.places).toHaveLength(2);
    expect(net.transitions).toHaveLength(1);
    expect(net.arcs).toHaveLength(2);
    // A flat, single-page document with no petriObject or reference markers
    // never enters the composed reader, so it never gets an objects array.
    expect(net.objects).toBeUndefined();

    // Neither place nor the transition carries a <graphics> element or a
    // toolspecific <coordinates>, so extractPosition's (0,0) fallback feeds
    // the same center-to-top-left conversion as every other node: half the
    // shape's own size, negative.
    const p1 = net.places.find((p) => p.id === "p-testplace1-3e78ffc8")!;
    expect(p1.graphics).toEqual({ x: -28, y: -28 });
    const t1 = net.transitions.find((t) => t.id === "t-testtransition1-d4ef8c48")!;
    expect(t1.graphics).toEqual({ x: -14, y: -32 });
  });
});
