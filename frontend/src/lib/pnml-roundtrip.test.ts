import { describe, expect, it } from "vitest";
import type { PetriNetData } from "@/types/petri";
import { exportPnml } from "./pnml-export";
import { parsePnml } from "./pnml-import";

/**
 * A canvas that exercises everything the composed document has to carry at
 * once: three levels of nesting, a sibling object beside the nest, elements
 * that belong to no object, a fusion joining two different nesting levels,
 * arc-like links crossing in both directions, a read arc and a weighted arc.
 *
 * The point is the whole shape at once. Each piece has its own test elsewhere;
 * this pins that they survive together, which is where a writer and a reader
 * that disagree about one detail actually show up.
 */
function threeLevelNet(): PetriNetData {
  const place = (id: string, name: string, objectId: string | undefined, x: number, y: number, tokens = 0) => ({
    id,
    name,
    tokens,
    graphics: { x, y },
    ...(objectId ? { objectId } : {}),
  });
  const transition = (
    id: string,
    name: string,
    objectId: string | undefined,
    x: number,
    y: number,
    distribution: "exp" | "det" | "norm",
    meanDelay: number,
    standardDeviation = 0,
    priority = 1,
  ) => ({
    id,
    name,
    priority,
    distribution,
    mean_delay: meanDelay,
    standard_deviation: standardDeviation,
    probability: null,
    graphics: { x, y },
    ...(objectId ? { objectId } : {}),
  });
  const frame = (id: string, name: string, objectId: string | undefined, x: number, y: number, width: number, height: number, priority = 0) => ({
    id,
    name,
    priority,
    graphics: { x, y, width, height },
    ...(objectId ? { objectId } : {}),
  });

  return {
    name: "Three levels",
    objects: [
      frame("oL3", "Outer_3", undefined, 40, 40, 900, 520),
      frame("oL2", "Middle_2", "oL3", 80, 100, 760, 380, 2),
      frame("oL1", "Inner_1", "oL2", 120, 160, 380, 260, 1),
      frame("oSib", "Sibling", undefined, 1000, 40, 320, 260),
    ],
    places: [
      place("p_free", "Free_Start", undefined, 60, 620, 3),
      place("p_l1_in", "L1_In", "oL1", 160, 220, 2),
      place("p_l1_out", "L1_Out", "oL1", 400, 220),
      place("p_l2_buf", "L2_Buffer", "oL2", 600, 220),
      place("p_l3_sink", "L3_Sink", "oL3", 820, 220),
      place("p_sib_in", "Sib_In", "oSib", 1040, 120),
      place("p_sib_out", "Sib_Out", "oSib", 1240, 120),
    ],
    transitions: [
      transition("t_free", "Free_T", undefined, 260, 620, "det", 2),
      transition("t_l1", "L1_Step", "oL1", 280, 220, "exp", 1),
      transition("t_l2", "L2_Step", "oL2", 700, 220, "norm", 3, 0.5, 2),
      transition("t_sib", "Sib_Step", "oSib", 1140, 120, "exp", 1),
    ],
    arcs: [
      { id: "a_l1_1", source_id: "p_l1_in", target_id: "t_l1", weight: 1, arc_type: "NORMAL" },
      { id: "a_l1_2", source_id: "t_l1", target_id: "p_l1_out", weight: 2, arc_type: "NORMAL" },
      { id: "a_l2_1", source_id: "p_l2_buf", target_id: "t_l2", weight: 1, arc_type: "NORMAL" },
      { id: "a_sib_1", source_id: "p_sib_in", target_id: "t_sib", weight: 1, arc_type: "NORMAL" },
      { id: "a_sib_2", source_id: "t_sib", target_id: "p_sib_out", weight: 1, arc_type: "NORMAL" },
      { id: "a_sib_read", source_id: "p_sib_out", target_id: "t_sib", weight: 1, arc_type: "READ" },
      { id: "a_free", source_id: "p_free", target_id: "t_free", weight: 1, arc_type: "NORMAL" },
    ],
    links: [
      { id: "lk_fuse", type: "placeFusion", sourceId: "p_l1_out", targetId: "p_l2_buf", quantity: 1 },
      { id: "lk_l2_l3", type: "transitionToPlace", sourceId: "t_l2", targetId: "p_l3_sink", quantity: 2 },
      { id: "lk_sib_l1", type: "transitionToPlace", sourceId: "t_sib", targetId: "p_l1_in", quantity: 1 },
      { id: "lk_free_sib", type: "transitionToPlace", sourceId: "t_free", targetId: "p_sib_in", quantity: 1 },
    ],
  };
}

/** What the drawing says, independent of the ids either side happens to mint. */
function shape(net: PetriNetData) {
  const frameName = (id: string | undefined) =>
    (net.objects ?? []).find((o) => o.id === id)?.name ?? "top level";

  return {
    counts: {
      places: net.places.length,
      transitions: net.transitions.length,
      arcs: net.arcs.length,
      objects: (net.objects ?? []).length,
      links: (net.links ?? []).length,
    },
    nesting: (net.objects ?? []).map((o) => `${o.name} in ${frameName(o.objectId)}`).sort(),
    membership: [...net.places, ...net.transitions]
      .map((e) => `${e.name} in ${frameName(e.objectId)}`)
      .sort(),
    markings: net.places.map((p) => `${p.name}=${p.tokens}`).sort(),
    timing: net.transitions
      .map((t) => `${t.name}:${t.distribution}:${t.mean_delay}:${t.standard_deviation}:${t.priority}`)
      .sort(),
    arcs: net.arcs
      .map((a) => {
        const name = (id: string) =>
          net.places.find((p) => p.id === id)?.name ??
          net.transitions.find((t) => t.id === id)?.name ??
          id;
        return `${name(a.source_id)}->${name(a.target_id)} x${a.weight} ${a.arc_type}`;
      })
      .sort(),
    links: (net.links ?? [])
      .map((l) => {
        const name = (id: string) =>
          net.places.find((p) => p.id === id)?.name ??
          net.transitions.find((t) => t.id === id)?.name ??
          id;
        return `${l.type} ${name(l.sourceId)}->${name(l.targetId)} x${l.quantity}`;
      })
      .sort(),
  };
}

describe("a three-level composed canvas survives a round trip", () => {
  it("comes back as the same drawing", () => {
    const net = threeLevelNet();
    const { data: reopened } = parsePnml(exportPnml(net));

    expect(shape(reopened)).toEqual(shape(net));
  });

  it("stays the same drawing on a second trip, so the format has a fixed point", () => {
    const net = threeLevelNet();
    const { data: once } = parsePnml(exportPnml(net));
    const { data: twice } = parsePnml(exportPnml(once));

    expect(shape(twice)).toEqual(shape(once));
  });

  it("carries only this app's own tool identity on every page of the nest", () => {
    const xml = exportPnml(threeLevelNet());

    expect(xml).not.toContain("PetriObjModel");
    expect(xml.match(/tool="PetriNetSim"/g)?.length).toBeGreaterThan(0);
    // Four objects plus the page that holds what belongs to no object, one
    // marker each, each written once, under this app's own identity.
    expect(xml.match(/<petriObject /g) ?? []).toHaveLength(5);
  });
});

describe("an arc the other tool wrote in its own spelling", () => {
  const arcDoc = (toolspecific: string) => `<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Read arc</text></name>
    <page id="page1">
      <place id="p1"><name><text>P1</text></name></place>
      <transition id="t1"><name><text>T1</text></name></transition>
      <arc id="a1" source="p1" target="t1">
        <inscription><text>1</text></inscription>
        ${toolspecific}
      </arc>
    </page>
  </net>
</pnml>`;

  it("reads a non-consuming input arc written as informational", () => {
    // PetriObjModelPaint calls a read arc informational and writes it that way,
    // including when it re-writes a document that arrived saying arcType=read.
    // Reading only arcType turned every read arc into an ordinary one on the way
    // back from the desktop, which silently changes what the net does.
    const xml = arcDoc(
      '<toolspecific tool="PetriObjModel" version="2.2.2"><informational>true</informational></toolspecific>',
    );

    expect(parsePnml(xml).data.arcs[0].arc_type).toBe("READ");
  });

  it("still reads its own spelling", () => {
    const xml = arcDoc(
      '<toolspecific tool="PetriObjModel" version="2.2.2"><arcType>read</arcType></toolspecific>',
    );

    expect(parsePnml(xml).data.arcs[0].arc_type).toBe("READ");
  });

  it("leaves an ordinary arc ordinary", () => {
    expect(parsePnml(arcDoc("")).data.arcs[0].arc_type).toBe("NORMAL");
  });
});

describe("document order is not object index once pages nest", () => {
  /**
   * Object 1 is a second top-level object, object 2 is nested inside object 0.
   * Pre-order therefore reads 0, 2, 1, while the links address objects by the
   * index each page states. A reader that took position for index would bind
   * every link to the wrong object.
   */
  function outOfOrderNet(): PetriNetData {
    return {
      name: "Order",
      objects: [
        { id: "o0", name: "First", priority: 0, graphics: { x: 0, y: 0, width: 400, height: 300 } },
        { id: "o1", name: "Second", priority: 0, graphics: { x: 500, y: 0, width: 200, height: 160 } },
        { id: "o2", name: "Nested", priority: 0, graphics: { x: 40, y: 40, width: 200, height: 160 }, objectId: "o0" },
      ],
      places: [
        { id: "p0", name: "P0", tokens: 1, graphics: { x: 10, y: 10 }, objectId: "o0" },
        { id: "p1", name: "P1", tokens: 0, graphics: { x: 510, y: 10 }, objectId: "o1" },
        { id: "p2", name: "P2", tokens: 0, graphics: { x: 50, y: 50 }, objectId: "o2" },
      ],
      transitions: [
        {
          id: "t2",
          name: "T2",
          priority: 1,
          distribution: "exp",
          mean_delay: 1,
          standard_deviation: 0,
          probability: null,
          graphics: { x: 120, y: 50 },
          objectId: "o2",
        },
      ],
      arcs: [{ id: "a2", source_id: "p2", target_id: "t2", weight: 1, arc_type: "NORMAL" }],
      links: [
        { id: "lk", type: "transitionToPlace", sourceId: "t2", targetId: "p1", quantity: 3 },
      ],
    };
  }

  it("keeps every object and link bound to the right object", () => {
    const net = outOfOrderNet();
    const xml = exportPnml(net);

    // The nested page really is written before the second top-level one.
    expect(xml.indexOf('id="object2"')).toBeLessThan(xml.indexOf('id="object1"'));

    const { data: reopened } = parsePnml(xml);
    const frameOf = (name: string) =>
      (reopened.objects ?? []).find((o) => o.name === name)!;
    const ownerName = (elementId: string) => {
      const owner = [...reopened.places, ...reopened.transitions].find((e) => e.id === elementId)
        ?.objectId;
      return (reopened.objects ?? []).find((o) => o.id === owner)?.name;
    };

    expect(frameOf("Nested").objectId).toBe(frameOf("First").id);
    expect(frameOf("Second").objectId).toBeUndefined();
    expect(ownerName("p1")).toBe("Second");
    expect(ownerName("t2")).toBe("Nested");

    const link = (reopened.links ?? [])[0];
    expect(ownerName(link.sourceId)).toBe("Nested");
    expect(ownerName(link.targetId)).toBe("Second");
    expect(link.quantity).toBe(3);
  });

  it("refuses to guess the order when a nested document states no usable index", () => {
    const xml = exportPnml(outOfOrderNet()).replace(/ index="2"/g, ' index="9"');

    expect(() => parsePnml(xml)).toThrow(/nests its pages/);
  });
});
