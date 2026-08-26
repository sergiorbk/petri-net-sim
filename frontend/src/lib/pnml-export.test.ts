import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { XMLParser } from "fast-xml-parser";
import pkg from "../../package.json";
import { exportPnml } from "./pnml-export";
import { parsePnml } from "./pnml-import";
import { buildIdRemap, escapeXml, exportComposedPnml, isNCName, sanitizeNCName } from "./pnml-export-composed";
import type { ComposedSimulateBody } from "./composed-simulation-client";
import type { PetriNetData } from "@/types/petri";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Canonicalisation: compares documents by (tag, sorted attrs, trimmed text,
// ordered children), the same shape as the Python canonicaliser in the spec's
// VERIFICATION section, order matters (it defines PNML element ordinals),
// whitespace and attribute order don't.
// ---------------------------------------------------------------------------

type CanonNode = readonly [string, readonly (readonly [string, string])[], readonly CanonNode[]] | readonly ["#text", string];

const orderedParser = new XMLParser({
  ignoreAttributes: false,
  attributeNamePrefix: "@_",
  preserveOrder: true,
  trimValues: true,
});

function canonList(nodes: unknown[]): CanonNode[] {
  const result: CanonNode[] = [];
  for (const node of nodes) {
    const rec = node as Record<string, unknown>;
    const keys = Object.keys(rec).filter((k) => k !== ":@");
    if (keys.length === 0) continue;
    const tag = keys[0];

    if (tag === "#text") {
      const text = String(rec["#text"]).trim();
      if (text.length > 0) result.push(["#text", text]);
      continue;
    }
    if (tag === "?xml") continue;

    const attrsObj = (rec[":@"] as Record<string, unknown>) ?? {};
    const attrs = Object.entries(attrsObj)
      .map(([k, v]) => [k.replace(/^@_/, ""), String(v)] as const)
      .sort((a, b) => a[0].localeCompare(b[0]));
    const children = canonList(rec[tag] as unknown[]);
    result.push([tag, attrs, children] as const);
  }
  return result;
}

function canonicalize(xml: string): CanonNode[] {
  return canonList(orderedParser.parse(xml) as unknown[]);
}

function loadFixture(name: string): string {
  return readFileSync(path.join(__dirname, "__fixtures__", name), "utf-8");
}

// ---------------------------------------------------------------------------
// The §7 worked example: two objects, a placeFusion and a transitionToPlace
// link (no placeToTransition: PetriObjModelPaint retired that link type).
// Element ids, names, positions and link addressing are chosen to reproduce
// composed_conformant_v21.pnml exactly (the golden fixture shared with the
// backend and Java packages) once run through exportComposedPnml.
// ---------------------------------------------------------------------------

function pipelineDemoRequest(): ComposedSimulateBody {
  return {
    name: "PipelineDemo",
    objects: [
      {
        name: "Generator",
        priority: 1,
        x: 40,
        y: 60,
        net_data: {
          name: "Generator",
          places: [
            { id: "p_pool", name: "Pool", tokens: 5, graphics: { x: 60, y: 80 } },
            { id: "p_ready", name: "Ready", tokens: 0, graphics: { x: 200, y: 80 } },
            { id: "p_log", name: "Log", tokens: 0, graphics: { x: 200, y: 200 } },
          ],
          transitions: [
            {
              id: "t_gen",
              name: "Generate",
              priority: 1,
              distribution: "det",
              mean_delay: 1.0,
              standard_deviation: 0,
              probability: null,
              graphics: { x: 130, y: 80 },
            },
          ],
          arcs: [
            { id: "a_g1", source_id: "p_pool", target_id: "t_gen", weight: 1, arc_type: "NORMAL" },
            { id: "a_g2", source_id: "t_gen", target_id: "p_ready", weight: 1, arc_type: "NORMAL" },
            { id: "a_g3", source_id: "t_gen", target_id: "p_log", weight: 1, arc_type: "NORMAL" },
          ],
        },
      },
      {
        name: "Server",
        priority: 0,
        x: 360,
        y: 60,
        net_data: {
          name: "Server",
          places: [
            { id: "p_in", name: "In", tokens: 0, graphics: { x: 60, y: 80 } },
            { id: "p_busy", name: "Busy", tokens: 0, graphics: { x: 200, y: 80 } },
            { id: "p_done", name: "Done", tokens: 0, graphics: { x: 340, y: 80 } },
          ],
          transitions: [
            {
              id: "t_start",
              name: "Start",
              priority: 1,
              distribution: "exp",
              mean_delay: 2.0,
              standard_deviation: 0,
              probability: null,
              graphics: { x: 130, y: 80 },
            },
            {
              id: "t_end",
              name: "End",
              priority: 1,
              distribution: "det",
              mean_delay: 3.0,
              standard_deviation: 0,
              probability: null,
              graphics: { x: 270, y: 80 },
            },
          ],
          arcs: [
            { id: "a_s1", source_id: "p_in", target_id: "t_start", weight: 1, arc_type: "NORMAL" },
            { id: "a_s2", source_id: "t_start", target_id: "p_busy", weight: 1, arc_type: "NORMAL" },
            { id: "a_s3", source_id: "p_busy", target_id: "t_end", weight: 1, arc_type: "NORMAL" },
            { id: "a_s4", source_id: "t_end", target_id: "p_done", weight: 1, arc_type: "NORMAL" },
          ],
        },
      },
    ],
    links: [
      // L0 placeFusion: object0 place 1 (p_ready) -> object1 place 0 (p_in)
      {
        type: "placeFusion",
        source_object: 0,
        source_element: 1,
        target_object: 1,
        target_element: 0,
        quantity: 1,
        informational: false,
      },
      // L1 transitionToPlace: object1 transition 0 (t_start) -> object0 place 2 (p_log), quantity 2
      {
        type: "transitionToPlace",
        source_object: 1,
        source_element: 0,
        target_object: 0,
        target_element: 2,
        quantity: 2,
        informational: false,
      },
      // No L2 placeToTransition any more: PetriObjModelPaint retired that
      // link type, and the exporter now refuses a request that has one (PNML
      // ISO conformance contract, decision 4).
    ],
  };
}

describe("exportComposedPnml", () => {
  it("matches the ISO/IEC 15909-2 golden fixture for the §7 worked example", () => {
    const xml = exportComposedPnml(pipelineDemoRequest());
    const fixture = loadFixture("composed_conformant_v21.pnml");
    expect(canonicalize(xml)).toEqual(canonicalize(fixture));
  });

  it("escapes special characters in names", () => {
    const body: ComposedSimulateBody = {
      name: 'A & B <model> "quoted"',
      objects: [
        {
          name: "Obj <1>",
          priority: 0,
          x: 0,
          y: 0,
          net_data: {
            name: "Obj <1>",
            places: [
              { id: "p1", name: 'Place "A" & <B>', tokens: 0, graphics: { x: 0, y: 0 } },
              { id: "p2", name: "p2", tokens: 0, graphics: { x: 0, y: 0 } },
            ],
            transitions: [
              {
                id: "t1",
                name: "T & 'quote'",
                priority: 0,
                distribution: null,
                mean_delay: 0,
                standard_deviation: 0,
                probability: null,
                graphics: { x: 0, y: 0 },
              },
            ],
            arcs: [{ id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" }],
          },
        },
        {
          name: "Obj2",
          priority: 0,
          x: 0,
          y: 0,
          net_data: {
            name: "Obj2",
            places: [{ id: "p3", name: "p3", tokens: 0, graphics: { x: 0, y: 0 } }],
            transitions: [
              {
                id: "t2",
                name: "T2",
                priority: 0,
                distribution: "det",
                mean_delay: 1,
                standard_deviation: 0,
                probability: null,
                graphics: { x: 0, y: 0 },
              },
            ],
            arcs: [],
          },
        },
      ],
      links: [
        // Not placeToTransition: PetriObjModelPaint retired that link type,
        // and the exporter now refuses a request that has one (PNML ISO
        // conformance contract, decision 4). transitionToPlace still crosses
        // objects and still exercises the escaping this test is about.
        {
          type: "transitionToPlace",
          source_object: 0,
          source_element: 0,
          target_object: 1,
          target_element: 0,
          quantity: 1,
          informational: false,
        },
      ],
    };

    const xml = exportComposedPnml(body);
    expect(xml).not.toContain('"quoted"');
    expect(xml).toContain(escapeXml('A & B <model> "quoted"'));
    expect(xml).toContain(escapeXml('Place "A" & <B>'));
    expect(xml).toContain(escapeXml("T & 'quote'"));
    // The raw, unescaped angle bracket must never leak into a <text> body.
    expect(xml).not.toContain("<model>");
    expect(xml).not.toContain("<B>");
  });

  it("drops a placeFusion link that connects an object to itself, warning instead of throwing", () => {
    // The desktop's own canvas-to-model step skips exactly this link (every
    // free element folds into one implicit object, so a fusion whose two
    // ends land in the same object has no structural form). Composed PNML
    // has no shape for "an object refers to itself" either, so this document
    // now skips the link rather than refusing to open at all.
    const body = pipelineDemoRequest();
    body.links[0].target_object = body.links[0].source_object; // object0.1 (Ready) -> object0.0 (Pool)
    const warnings: string[] = [];
    let xml = "";
    expect(() => {
      xml = exportComposedPnml(body, (message) => warnings.push(message));
    }).not.toThrow();
    // Both ends stay their own plain <place>: nothing was realised as a
    // reference for this link, it was skipped outright.
    expect(xml).toContain('<place id="p_pool">');
    expect(xml).toContain('<place id="p_ready">');
    expect(warnings).toEqual([
      'Dropped the link "Pool" (id "p_pool") = "Ready" (id "p_ready"): both places belong to the ' +
        "same Petri-object, so linking them would have it repeat itself.",
    ]);
  });

  it("still raises when a non-fusion link connects an object to itself", () => {
    // Rule 5's free-to-free carve-out only ever legalised a *fusion* between
    // two places with no defined, shared object; a directional link crossing
    // no object boundary at all remains something composed PNML cannot
    // express, so nothing here changes for it.
    const body = pipelineDemoRequest();
    body.links[1].target_object = body.links[1].source_object;
    expect(() => exportComposedPnml(body)).toThrow(/itself/);
  });

  it("raises on a model with no objects", () => {
    expect(() => exportComposedPnml({ name: "Empty", objects: [], links: [] })).toThrow(/no objects/);
  });

  it("raises on a link quantity below 1", () => {
    const body = pipelineDemoRequest();
    body.links[1].quantity = 0;
    expect(() => exportComposedPnml(body)).toThrow(/>= 1/);
  });

  it("raises on a placeToTransition link, retired by PetriObjModelPaint", () => {
    // The exporter's own backstop: ComposedModel.validate() on the backend
    // already refuses one for any request that goes through the API, this
    // covers a body that reached the exporter some other way. The projection
    // this function used to write for it (a representative reference node
    // plus an informational link arc) is gone, so there is nothing left here
    // that could express one.
    const body = pipelineDemoRequest();
    body.links.push({
      type: "placeToTransition",
      source_object: 0,
      source_element: 0,
      target_object: 1,
      target_element: 0,
      quantity: 1,
      informational: true,
    });
    expect(() => exportComposedPnml(body)).toThrow(/placeToTransition/);
  });
});

describe("exportPnml, flat vs composed dispatch", () => {
  it("exports a flat net with center-anchored wire positions, pinned byte-for-byte", () => {
    const net: PetriNetData = {
      name: "Capture Net",
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
        {
          id: "t2",
          name: "Branch",
          priority: 1,
          distribution: null,
          mean_delay: 0,
          standard_deviation: 0,
          probability: 0.42,
          graphics: { x: 150, y: 100 },
        },
      ],
      arcs: [
        { id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" },
        { id: "a2", source_id: "t1", target_id: "p2", weight: 3, arc_type: "NORMAL" },
      ],
    };

    const xml = exportPnml(net);

    // Pinned byte-for-byte. A flat net is a shipped format, so it changes only
    // deliberately: it carries a single tool-specific payload under this
    // app's own identity (PetriNetSim), and every node position is now the
    // CENTER of its shape (graphics.x/y + half the node's size), matching the
    // composed writer and the standard PNML convention, not the top-left
    // corner the app model itself keeps. p1 at (10,20) becomes (38,48): +28
    // in each axis, half of PLACE_W/PLACE_H (56). t1 at (150,20) becomes
    // (164,52): +14/+32, half of TRANS_W/TRANS_H (28/64). Neither place
    // carries a toolspecific block at all: a plain place has nothing left to
    // say there once <coordinates> is gone (decision 1).
    expect(xml).toBe(
      [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        '<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">',
        '  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">',
        "    <name>",
        "      <text>Capture Net</text>",
        "    </name>",
        '    <page id="page1">',
        '      <place id="p1">',
        "        <name>",
        "          <text>Start</text>",
        "        </name>",
        "        <graphics>",
        '          <position x="38" y="48"></position>',
        "        </graphics>",
        "        <initialMarking>",
        "          <text>5</text>",
        "        </initialMarking>",
        "      </place>",
        '      <place id="p2">',
        "        <name>",
        "          <text>End</text>",
        "        </name>",
        "        <graphics>",
        '          <position x="328" y="48"></position>',
        "        </graphics>",
        "      </place>",
        '      <transition id="t1">',
        "        <name>",
        "          <text>Go</text>",
        "        </name>",
        '        <toolspecific tool="PetriNetSim" version="1.1.0">',
        "          <timeDelay>2.5</timeDelay>",
        "          <delayMeanValue>2.5</delayMeanValue>",
        "          <distribution>norm</distribution>",
        "          <standardDeviation>0.5</standardDeviation>",
        "          <priority>3</priority>",
        "        </toolspecific>",
        "        <graphics>",
        '          <position x="164" y="52"></position>',
        "        </graphics>",
        "      </transition>",
        '      <transition id="t2">',
        "        <name>",
        "          <text>Branch</text>",
        "        </name>",
        '        <toolspecific tool="PetriNetSim" version="1.1.0">',
        "          <probability>0.42</probability>",
        "        </toolspecific>",
        "        <graphics>",
        '          <position x="164" y="132"></position>',
        "        </graphics>",
        "      </transition>",
        '      <arc id="a1" source="p1" target="t1">',
        "        <graphics></graphics>",
        "        <inscription>",
        "          <text>1</text>",
        "        </inscription>",
        "      </arc>",
        '      <arc id="a2" source="t1" target="p2">',
        "        <graphics></graphics>",
        "        <inscription>",
        "          <text>3</text>",
        "        </inscription>",
        "      </arc>",
        "    </page>",
        "  </net>",
        "</pnml>",
        "",
      ].join("\n"),
    );
  });

  it("exports composed when the canvas has one object frame and no links, so the frame survives the file", () => {
    const flatNet: PetriNetData = {
      name: "Solo",
      places: [{ id: "p1", name: "P1", tokens: 1, graphics: { x: 10, y: 20 } }],
      transitions: [{ id: "t1", name: "T1", priority: 0, distribution: "det", mean_delay: 1, standard_deviation: 0, probability: null, graphics: { x: 50, y: 0 } }],
      arcs: [{ id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" }],
    };
    const framedNet: PetriNetData = {
      ...flatNet,
      objects: [{ id: "obj1", name: "Frame", priority: 0, graphics: { x: 5, y: 8, width: 200, height: 160 } }],
      places: flatNet.places.map((p) => ({ ...p, objectId: "obj1" })),
      transitions: flatNet.transitions.map((t) => ({ ...t, objectId: "obj1" })),
    };

    // The engine may treat one frame with no links as a flat net, but the
    // file may not: written flat, the frame would simply not be in the
    // document, and the reopened canvas would have silently lost a drawing
    // the user made. So the file dispatch asks "is there structure", and a
    // lone frame is structure.
    const xml = exportPnml(framedNet);
    expect(xml).toContain('<page id="object0">');
    expect(xml).toContain('width="200" height="160"');

    const { data: reopened } = parsePnml(xml);
    expect(reopened.objects).toHaveLength(1);
    expect(reopened.objects![0].graphics).toMatchObject({ x: 5, y: 8, width: 200, height: 160 });
    expect(reopened.places[0].objectId).toBe(reopened.objects![0].id);

    // A truly frame-less net still exports the shipped flat shape.
    expect(exportPnml(flatNet)).toContain('<page id="page1">');
  });

  it("exports composed (multi-page) when the canvas has links between objects", () => {
    const net: PetriNetData = {
      name: "Two Objects",
      places: [
        { id: "p1", name: "P1", tokens: 1, graphics: { x: 0, y: 0 }, objectId: "obj1" },
        { id: "p2", name: "P2", tokens: 0, graphics: { x: 0, y: 0 }, objectId: "obj2" },
      ],
      transitions: [
        {
          id: "t1",
          name: "T1",
          priority: 0,
          distribution: "det",
          mean_delay: 1,
          standard_deviation: 0,
          probability: null,
          graphics: { x: 0, y: 0 },
          objectId: "obj1",
        },
      ],
      arcs: [{ id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" }],
      objects: [
        { id: "obj1", name: "Object A", priority: 0, graphics: { x: 0, y: 0, width: 200, height: 200 } },
        { id: "obj2", name: "Object B", priority: 0, graphics: { x: 300, y: 0, width: 200, height: 200 } },
      ],
      links: [{ id: "link1", type: "transitionToPlace", sourceId: "t1", targetId: "p2", quantity: 1 }],
    };

    const xml = exportPnml(net);
    expect(xml).toContain('<page id="object0">');
    expect(xml).toContain('<page id="object1">');
    expect(xml).toContain("<petriObjectLinks>");
  });

  it("writes an arcType toolspecific for inhibitor and read arcs, and nothing for normal ones", () => {
    const net: PetriNetData = {
      name: "Kinds",
      places: [{ id: "p1", name: "P1", tokens: 0, graphics: { x: 0, y: 0 } }],
      transitions: [
        {
          id: "t1", name: "T1", priority: 0, distribution: "det", mean_delay: 1,
          standard_deviation: 0, probability: null, graphics: { x: 50, y: 0 },
        },
      ],
      arcs: [
        { id: "a_normal", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" },
        { id: "a_inhibit", source_id: "p1", target_id: "t1", weight: 1, arc_type: "INHIBITOR" },
        { id: "a_read", source_id: "p1", target_id: "t1", weight: 1, arc_type: "READ" },
      ],
    };

    const xml = exportPnml(net);
    // Exactly the block the composed writer's ownArcXml emits, so one document
    // shape says "inhibitor" and both readers recognise it.
    expect(xml).toContain("<arcType>inhibitor</arcType>");
    expect(xml).toContain("<arcType>read</arcType>");
    // A normal arc is still the shipped format: no tool-specific block at all.
    const normalArc = xml.slice(
      xml.indexOf('<arc id="a_normal"'),
      xml.indexOf('<arc id="a_inhibit"'),
    );
    expect(normalArc).not.toContain("toolspecific");
  });
});

describe("exportPnml, nested objects and fused link targets", () => {
  const place = (id: string, objectId?: string) => ({
    id,
    name: id,
    tokens: 0,
    graphics: { x: 10, y: 10 },
    objectId,
  });
  const transition = (id: string, objectId?: string) => ({
    id,
    name: id,
    priority: 1,
    distribution: "exp" as const,
    mean_delay: 1,
    standard_deviation: 0,
    probability: null,
    graphics: { x: 60, y: 10 },
    objectId,
  });
  const frame = (id: string, objectId?: string) => ({
    id,
    name: id,
    priority: 0,
    graphics: { x: 0, y: 0, width: 200, height: 200 },
    objectId,
  });

  it("writes a three-level nest, every frame as its own page", () => {
    const net: PetriNetData = {
      name: "Nested",
      places: [place("p1", "o1")],
      transitions: [],
      arcs: [],
      objects: [frame("o1", "o2"), frame("o2", "o3"), frame("o3")],
    };

    const xml = exportPnml(net);

    // Three frames, each object marker written once, under this app's own
    // tool identity.
    expect(xml.match(/<petriObject /g) ?? []).toHaveLength(3);
    // Nesting is the document's own page structure: o1's page sits inside
    // o2's, which sits inside o3's. Nothing states it a second time.
    expect(xml).not.toContain("parentObject");

    let depth = 0;
    let deepest = 0;
    for (const tag of xml.match(/<\/?page[\s>]/g) ?? []) {
      depth += tag.startsWith("</") ? -1 : 1;
      deepest = Math.max(deepest, depth);
    }
    expect(deepest).toBe(3);
    expect(parsePnml(xml).data.objects).toHaveLength(3);
  });

  it("routes a link into a fused-away place to the place that survived the fusion", () => {
    // pA is fused into pB, so pA has no place of its own any more. An arc-like
    // link aimed at pA has to end at pB's representative node: the exporter
    // used to file that representative under pB's id and then look it up under
    // pA's, which threw "Cannot read properties of undefined (reading 'id')"
    // instead of writing the document.
    const net: PetriNetData = {
      name: "Fused",
      places: [place("pA", "o1"), place("pB", "o2")],
      transitions: [transition("tC", "o3")],
      arcs: [],
      objects: [frame("o1"), frame("o2"), frame("o3")],
      links: [
        { id: "l1", type: "placeFusion", sourceId: "pA", targetId: "pB", quantity: 1 },
        { id: "l2", type: "transitionToPlace", sourceId: "tC", targetId: "pA", quantity: 1 },
      ],
    };

    const xml = exportPnml(net);

    // One representative on tC's own page, standing for the surviving place.
    expect(xml).toContain('<referencePlace id="ref_object2_pB" ref="pB">');
    // The link arc ends at that representative, not at a node nobody wrote.
    expect(xml).toContain('<arc id="larc_1" source="tC" target="ref_object2_pB">');
    // pA keeps its own reference node, the fusion one, pointing at pB.
    expect(xml).toContain('<referencePlace id="pA" ref="pB">');
    expect(() => parsePnml(xml)).not.toThrow();
  });

  it("nesting and a fused link target together still export", () => {
    const net: PetriNetData = {
      name: "Both",
      places: [place("pA", "o1"), place("pB", "o2")],
      transitions: [transition("tC", "o2")],
      arcs: [],
      objects: [frame("o1", "o2"), frame("o2"), frame("o3", "o2")],
      links: [
        { id: "l1", type: "placeFusion", sourceId: "pA", targetId: "pB", quantity: 1 },
        { id: "l2", type: "transitionToPlace", sourceId: "tC", targetId: "pA", quantity: 1 },
      ],
    };

    expect(() => exportPnml(net)).not.toThrow();
  });
});

describe("this app's own tool identity", () => {
  const parse = (xml: string) =>
    new XMLParser({ ignoreAttributes: false, attributeNamePrefix: "@_" }).parse(xml);

  const flatNet: PetriNetData = {
    name: "Two tools",
    places: [{ id: "p1", name: "P1", tokens: 0, graphics: { x: 0, y: 0 } }],
    transitions: [
      {
        id: "t1",
        name: "T1",
        priority: 1,
        distribution: "exp",
        mean_delay: 1,
        standard_deviation: 0,
        probability: null,
        graphics: { x: 60, y: 0 },
      },
    ],
    arcs: [{ id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "READ" }],
  };

  // fast-xml-parser only returns an array for a repeated element; with a
  // single toolspecific block (this app's own, and nothing else's) it comes
  // back as one bare object, not a one-element array.
  const asArray = <T,>(v: T | T[]): T[] => (Array.isArray(v) ? v : [v]);
  const toolsOf = (element: Record<string, unknown>) =>
    asArray(element.toolspecific as Record<string, string> | Record<string, string>[]).map((b) => [
      b["@_tool"],
      b["@_version"],
    ]);

  it("writes every flat block under its own name only", () => {
    const doc = parse(exportPnml(flatNet));
    const page = doc.pnml.net.page;

    // p1 carries no toolspecific block at all: with no coordinates left to
    // write, tokens 0 and no other place-level toolspecific content, it has
    // nothing to say there (decision 1).
    expect(page.place.toolspecific).toBeUndefined();
    for (const element of [page.transition, page.arc]) {
      expect(toolsOf(element)).toEqual([["PetriNetSim", pkg.version]]);
    }
  });

  it("states its own release, since no reader filters on version", () => {
    // This app's version comes from its own package.json; a reader picks a
    // block by tool name, and the version says which release the vocabulary
    // belongs to, not which one a reader should accept.
    const doc = parse(exportPnml(flatNet));
    const block = doc.pnml.net.page.transition.toolspecific as Record<string, string>;
    expect(block["@_version"]).toBe(pkg.version);
  });

  it("composed documents carry its own identity on the net and on every page", () => {
    const doc = parse(exportComposedPnml(pipelineDemoRequest()));
    const net = doc.pnml.net;
    expect(toolsOf(net)).toEqual([["PetriNetSim", pkg.version]]);
    expect(toolsOf(net.page[0])).toEqual([["PetriNetSim", pkg.version]]);
  });

  it("reads back a document that carries only the desktop's block", () => {
    // Every file the desktop writes on its own: this app no longer produces
    // one to derive that from (it never mirrors PetriObjModel any more), so
    // this is hand-authored the way PetriObjModelPaint's own writer shapes
    // one, with position stated only as toolspecific <coordinates>. The
    // reader falls back to PetriObjModel by name (decision 2), and the
    // <coordinates> fallback for a document with no <graphics><position>
    // stays exactly as it was (decision 1).
    const xml = `<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Two tools</text></name>
    <page id="page1">
      <place id="p1">
        <name><text>P1</text></name>
        <toolspecific tool="PetriObjModel" version="2.2.2">
          <coordinates x="28" y="28"/>
        </toolspecific>
      </place>
      <transition id="t1">
        <name><text>T1</text></name>
        <toolspecific tool="PetriObjModel" version="2.2.2">
          <coordinates x="74" y="32"/>
          <timeDelay>1</timeDelay>
          <delayMeanValue>1</delayMeanValue>
          <distribution>exp</distribution>
          <priority>1</priority>
        </toolspecific>
      </transition>
      <arc id="a1" source="p1" target="t1">
        <inscription><text>1</text></inscription>
        <toolspecific tool="PetriObjModel" version="2.2.2">
          <arcType>read</arcType>
        </toolspecific>
      </arc>
    </page>
  </net>
</pnml>`;
    expect(xml).not.toContain("PetriNetSim");

    const { data: net } = parsePnml(xml);
    // Center-anchor conversion on read (PNML ISO conformance contract, Part
    // B): the wire position is the place's center, so subtracting half its
    // size lands back on the (0, 0) top-left the place was drawn at.
    expect(net.places[0].graphics).toEqual({ x: 0, y: 0 });
    expect(net.transitions[0].distribution).toBe("exp");
    expect(net.arcs[0].arc_type).toBe("READ");
  });

  it("prefers its own block when the two disagree", () => {
    // Nothing this app writes disagrees with itself; this pins which block a
    // reader picks if a foreign writer (or a hand-edited file) ever leaves
    // two that do. Priority is the probe: unlike a position, it lives nowhere
    // but in a tool-specific block, so the answer can only come from the
    // block the reader chose. Checked with each tool's block in both document
    // positions, so the answer is provably about the NAME, not position.
    const doc = (first: "PetriObjModel" | "PetriNetSim") => {
      const blocks = {
        PetriObjModel: '<toolspecific tool="PetriObjModel" version="2.2.2"><distribution>exp</distribution><priority>1</priority></toolspecific>',
        PetriNetSim: `<toolspecific tool="PetriNetSim" version="${pkg.version}"><distribution>exp</distribution><priority>7</priority></toolspecific>`,
      };
      const second = first === "PetriObjModel" ? "PetriNetSim" : "PetriObjModel";
      return `<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<pnml xmlns="http://www.pnml.org/version-2009/grammar/pnml">
  <net id="net1" type="http://www.pnml.org/version-2009/grammar/ptnet">
    <name><text>Two tools</text></name>
    <page id="page1">
      <place id="p1"><name><text>P1</text></name></place>
      <transition id="t1">
        <name><text>T1</text></name>
        ${blocks[first]}
        ${blocks[second]}
      </transition>
      <arc id="a1" source="p1" target="t1"><inscription><text>1</text></inscription></arc>
    </page>
  </net>
</pnml>`;
    };

    // PetriNetSim's own priority (7) wins regardless of which block comes first.
    expect(parsePnml(doc("PetriObjModel")).data.transitions[0].priority).toBe(7);
    expect(parsePnml(doc("PetriNetSim")).data.transitions[0].priority).toBe(7);
  });
});

describe("a frame with no size of its own", () => {
  it("still reopens as an object, not as the free-elements bucket", () => {
    // The bucket that holds unframed elements is recognised by an all-default
    // <petriObject> marker. A real frame that happened to sit at the origin
    // with no size wrote exactly that marker, so reopening the file read the
    // object as the bucket and the frame, with every membership in it, was
    // silently gone.
    const net: PetriNetData = {
      name: "Sizeless",
      places: [{ id: "p1", name: "P1", tokens: 0, graphics: { x: 0, y: 0 }, objectId: "o1" }],
      transitions: [],
      arcs: [],
      objects: [
        { id: "o1", name: "Obj", priority: 0, graphics: { x: 0, y: 0, width: 0, height: 0 } },
      ],
    };

    const { data: reopened } = parsePnml(exportPnml(net));

    expect(reopened.objects).toHaveLength(1);
    expect(reopened.objects![0].name).toBe("Obj");
    expect(reopened.places[0].objectId).toBe(reopened.objects![0].id);
  });
});

describe("sanitizeNCName", () => {
  it("leaves an already-safe id untouched", () => {
    expect(sanitizeNCName("p1")).toBe("p1");
    expect(sanitizeNCName("_underscore.dot-dash")).toBe("_underscore.dot-dash");
  });

  it("replaces illegal characters with a dash and collapses runs of them", () => {
    expect(sanitizeNCName("a b")).toBe("a-b");
    expect(sanitizeNCName("a   b")).toBe("a-b");
    expect(sanitizeNCName("a/b\\c")).toBe("a-b-c");
  });

  it("prefixes an invalid (or absent) first character with n-, surviving the later trim", () => {
    expect(sanitizeNCName("123abc")).toBe("n-123abc");
    expect(sanitizeNCName("  hello  ")).toBe("n-hello");
    expect(sanitizeNCName("-abc")).toBe("n-abc");
  });

  it("sanitizes an all-illegal string down to n", () => {
    expect(sanitizeNCName("!!!")).toBe("n");
    expect(sanitizeNCName("")).toBe("n");
  });

  it("agrees with isNCName about what already passes", () => {
    expect(isNCName("p1")).toBe(true);
    expect(isNCName("1p")).toBe(false);
    expect(isNCName("a b")).toBe(false);
  });
});

describe("buildIdRemap", () => {
  it("keeps every already-safe, non-colliding id exactly as it was", () => {
    const { ids } = buildIdRemap(["p1", "t1", "a1"]);
    expect(ids).toEqual(["p1", "t1", "a1"]);
  });

  it("de-duplicates a sanitized id that collides with an id already in the set", () => {
    // "a-b" is already valid and claims itself; "a b" sanitizes to the same
    // string, so it has to fall back to a numbered suffix instead of silently
    // colliding with the first one.
    const { ids } = buildIdRemap(["a-b", "a b"]);
    expect(ids).toEqual(["a-b", "a-b-2"]);
  });

  it("de-duplicates two ids that sanitize to the same thing, neither of which was valid on its own", () => {
    const { ids } = buildIdRemap(["a b", "a/b"]);
    expect(ids).toEqual(["a-b", "a-b-2"]);
  });

  it("gives a raw id repeated by two different elements two distinct final ids, first occurrence first", () => {
    // Two different elements can legitimately carry the same raw id (a place
    // and a transition are independent id spaces in the app model); each
    // occurrence still needs its own final id, not the one raw-string lookup
    // a plain Map could offer.
    const { ids, resolve } = buildIdRemap(["x1", "x1"]);
    expect(ids).toEqual(["x1", "x1-2"]);
    // A reference to the raw id lands on the first occurrence, matching the
    // importer's first-wins semantics for a genuine duplicate.
    expect(resolve("x1")).toBe("x1");
  });

  it("reserves ids so a colliding user id is the one that moves", () => {
    const { ids } = buildIdRemap(["object0"], ["object0"]);
    expect(ids).toEqual(["object0-2"]);
  });
});

describe("export-side id safety (flat)", () => {
  it("sanitizes an invalid place/transition/arc id and keeps arc source/target consistent", () => {
    const net: PetriNetData = {
      name: "Messy ids",
      places: [{ id: "p 1", name: "P1", tokens: 0, graphics: { x: 0, y: 0 } }],
      transitions: [
        {
          id: "1t",
          name: "T1",
          priority: 0,
          distribution: "det",
          mean_delay: 1,
          standard_deviation: 0,
          probability: null,
          graphics: { x: 60, y: 0 },
        },
      ],
      arcs: [{ id: "a 1", source_id: "p 1", target_id: "1t", weight: 1, arc_type: "NORMAL" }],
    };

    const xml = exportPnml(net);

    expect(xml).toContain('<place id="p-1">');
    expect(xml).toContain('<transition id="n-1t">');
    expect(xml).toContain('<arc id="a-1" source="p-1" target="n-1t">');
    // Never the raw, illegal id: the safety net is silent, not partial.
    expect(xml).not.toContain('id="p 1"');
    expect(xml).not.toContain('id="1t"');
    expect(xml).not.toContain('source="p 1"');
  });

  it("keeps a place and a transition that share one raw id as two distinct ids", () => {
    // Place ids and transition ids are independent id spaces in the app
    // model, so hand-assembled (or foreign-imported) data can legally hand
    // both a place and a transition the same raw id "x1". Writing them out
    // with the same final id would be a schema-invalid document (two
    // elements, one id).
    const net: PetriNetData = {
      name: "Dup ids",
      places: [{ id: "x1", name: "Place X1", tokens: 0, graphics: { x: 0, y: 0 } }],
      transitions: [
        {
          id: "x1",
          name: "Transition X1",
          priority: 0,
          distribution: "det",
          mean_delay: 1,
          standard_deviation: 0,
          probability: null,
          graphics: { x: 60, y: 0 },
        },
      ],
      arcs: [{ id: "a1", source_id: "x1", target_id: "x1", weight: 1, arc_type: "NORMAL" }],
    };

    const xml = exportPnml(net);

    expect(xml).toContain('<place id="x1">');
    expect(xml).toContain('<transition id="x1-2">');
    // No id in the whole document repeats.
    const ids = [...xml.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
    expect(new Set(ids).size).toBe(ids.length);
    // The arc resolves both ends to the FIRST occurrence of the shared raw
    // id, which is the place: the same first-wins rule the importer applies
    // to a genuine duplicate.
    expect(xml).toContain('<arc id="a1" source="x1" target="x1">');
  });
});

describe("export-side id safety (composed)", () => {
  it("sanitizes ids consistently across place, arc, referencePlace ref and petriObjectLinks", () => {
    const body: ComposedSimulateBody = {
      name: "Messy composed",
      objects: [
        {
          name: "Obj A",
          priority: 0,
          x: 0,
          y: 0,
          net_data: {
            name: "Obj A",
            places: [{ id: "p ready", name: "Ready", tokens: 0, graphics: { x: 0, y: 0 } }],
            transitions: [],
            arcs: [],
          },
        },
        {
          name: "Obj B",
          priority: 0,
          x: 0,
          y: 0,
          net_data: {
            name: "Obj B",
            places: [],
            transitions: [
              {
                id: "1start",
                name: "Start",
                priority: 0,
                distribution: "det",
                mean_delay: 1,
                standard_deviation: 0,
                probability: null,
                graphics: { x: 0, y: 0 },
              },
            ],
            arcs: [],
          },
        },
      ],
      links: [
        // Not placeToTransition: PetriObjModelPaint retired that link type,
        // and the exporter now refuses a request that has one (PNML ISO
        // conformance contract, decision 4). transitionToPlace, source and
        // target swapped from before, still exercises sanitization on both a
        // place id and a transition id.
        {
          type: "transitionToPlace",
          source_object: 1,
          source_element: 0,
          target_object: 0,
          target_element: 0,
          quantity: 1,
          informational: false,
        },
      ],
    };

    const xml = exportComposedPnml(body);

    expect(xml).toContain('<place id="p-ready">');
    expect(xml).not.toContain('id="p ready"');
    // The representative node for "p ready" stands for the sanitized place
    // id, and the link arc's own source uses the same sanitized transition
    // id the <transition> got.
    expect(xml).toContain('ref="p-ready"');
    expect(xml).toContain('source="n-1start"');
    // Declared links (petriObjectLinks) resolve through the same remap.
    expect(xml).toContain('sourceElementId="n-1start"');
    expect(xml).toContain('targetElementId="p-ready"');
    expect(xml).not.toContain('"1start"');
  });

  it("reserves its own generated ids so a colliding user id is bumped, not duplicated", () => {
    // "object0" is exactly the id `pageId` generates for object 0; a real
    // user place can legitimately be named that too, and used to come out
    // byte-for-byte identical to the page id, a schema-invalid document.
    const body: ComposedSimulateBody = {
      name: "Collides with a generated id",
      objects: [
        {
          name: "Obj A",
          priority: 0,
          x: 0,
          y: 0,
          net_data: {
            name: "Obj A",
            places: [{ id: "object0", name: "Object0Place", tokens: 0, graphics: { x: 0, y: 0 } }],
            transitions: [],
            arcs: [],
          },
        },
        {
          name: "Obj B",
          priority: 0,
          x: 0,
          y: 0,
          net_data: {
            name: "Obj B",
            places: [{ id: "p2", name: "P2", tokens: 0, graphics: { x: 0, y: 0 } }],
            transitions: [],
            arcs: [],
          },
        },
      ],
      links: [],
    };

    const xml = exportComposedPnml(body);

    // The generated page id keeps its exact spelling; the colliding user id
    // is the one that moves.
    expect(xml).toContain('<page id="object0">');
    expect(xml).toContain('<place id="object0-2">');
    expect(xml).not.toContain('<place id="object0">');

    const ids = [...xml.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
