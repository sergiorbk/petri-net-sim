import { describe, expect, it } from "vitest";
import { buildGraph } from "./EditorCanvas";
import { connectorOf } from "@/lib/petri-object-model";
import type { PetriNetData } from "@/types/petri";
import type { PlaceNodeData } from "@/components/simulation/PlaceNode";

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

  /**
   * Desktop 2.3.0 draws every place in a fusion group with a grey interior,
   * master and copy alike (PlaceNode's `linked` flag). buildGraph is where
   * that flag gets set, from fusionGroupsByPlace, so this is the one place
   * that would miss a place taking part in a link but not looking it.
   */
  function netWithFusion(): PetriNetData {
    return {
      name: "fusion",
      places: [
        { id: "master", name: "Master", tokens: 3, graphics: { x: 0, y: 0 } },
        { id: "copy", name: "Copy", tokens: 0, graphics: { x: 200, y: 0 } },
        { id: "loose", name: "Loose", tokens: 0, graphics: { x: 400, y: 0 } },
      ],
      transitions: [],
      arcs: [],
      links: [{ id: "l1", type: "placeFusion", sourceId: "copy", targetId: "master", quantity: 1 }],
    };
  }

  it("marks both the master and the copy of a fusion as linked", () => {
    const { nodes } = buildGraph(netWithFusion(), new Set(), null);
    const master = nodes.find((n) => n.id === "master")!;
    const copy = nodes.find((n) => n.id === "copy")!;
    expect((master.data as unknown as PlaceNodeData).linked).toBe(true);
    expect((copy.data as unknown as PlaceNodeData).linked).toBe(true);
  });

  it("leaves a place outside every fusion group unlinked", () => {
    const { nodes } = buildGraph(netWithFusion(), new Set(), null);
    const loose = nodes.find((n) => n.id === "loose")!;
    expect((loose.data as unknown as PlaceNodeData).linked).toBe(false);
  });

  /**
   * A place feeding a transition that feeds it back is the ordinary shape of a
   * resource being taken and returned, so the two arcs must not be drawn on
   * top of each other with one hiding the other. routeConnections spots the
   * pair and gives each arc its own anchor along the same side, plus opposite
   * middle lanes so the orthogonal style's bends do not converge again. None
   * of that was pinned by a test, and it is the kind of geometry that survives
   * a refactor only by accident.
   */
  function netWithArcsBothWays(): PetriNetData {
    return {
      name: "both ways",
      places: [{ id: "p1", name: "P1", tokens: 1, graphics: { x: 0, y: 0 } }],
      transitions: [
        {
          id: "t1",
          name: "T1",
          priority: 0,
          distribution: null,
          mean_delay: 0,
          standard_deviation: 0,
          probability: null,
          graphics: { x: 200, y: 0 },
        },
      ],
      arcs: [
        { id: "a1", source_id: "p1", target_id: "t1", weight: 1, arc_type: "NORMAL" },
        { id: "a2", source_id: "t1", target_id: "p1", weight: 1, arc_type: "NORMAL" },
      ],
    };
  }

  it("anchors the two arcs of a there-and-back pair at different points on the place", () => {
    const { nodes } = buildGraph(netWithArcsBothWays(), new Set(), null);
    const handles = (nodes.find((n) => n.id === "p1")!.data as unknown as PlaceNodeData).handles;
    const outgoing = handles.find((h) => h.id === "src-a1")!;
    const incoming = handles.find((h) => h.id === "tgt-a2")!;
    expect(outgoing.side).toBe(incoming.side);
    expect(outgoing.offset).not.toBe(incoming.offset);
  });

  it("puts the two arcs of a there-and-back pair in opposite middle lanes", () => {
    const { edges } = buildGraph(netWithArcsBothWays(), new Set(), null);
    const there = edges.find((e) => e.id === "a1")!.data as { midOffset: number };
    const back = edges.find((e) => e.id === "a2")!.data as { midOffset: number };
    expect(there.midOffset).not.toBe(0);
    expect(Math.sign(there.midOffset)).toBe(-Math.sign(back.midOffset));
  });

  /**
   * Selecting one strand of a connector (see connectorOf in
   * petri-object-model.ts) lights the whole pair of objects, in two colours:
   * the strand actually clicked in the accent, the rest of the connector in a
   * held-back variant, never the same colour as either the accent or a plain
   * unselected fusion tie, in either theme. A link belonging to a DIFFERENT
   * connector (a different pair of objects) gets neither.
   */
  function netWithTwoConnectors(): PetriNetData {
    return {
      name: "connectors",
      places: [
        { id: "p1", name: "P1", tokens: 0, graphics: { x: 0, y: 0 }, objectId: "oa" },
        { id: "p2", name: "P2", tokens: 0, graphics: { x: 0, y: 100 }, objectId: "oa" },
        { id: "p3", name: "P3", tokens: 0, graphics: { x: 200, y: 0 }, objectId: "ob" },
        { id: "p4", name: "P4", tokens: 0, graphics: { x: 200, y: 100 }, objectId: "ob" },
        { id: "p5", name: "P5", tokens: 0, graphics: { x: 0, y: 200 }, objectId: "oa" },
        { id: "p6", name: "P6", tokens: 0, graphics: { x: 400, y: 200 }, objectId: "oc" },
      ],
      transitions: [],
      arcs: [],
      objects: [
        { id: "oa", name: "A", priority: 0, graphics: { x: -20, y: -20, width: 300, height: 350 } },
        { id: "ob", name: "B", priority: 0, graphics: { x: 180, y: -20, width: 150, height: 150 } },
        { id: "oc", name: "C", priority: 0, graphics: { x: 380, y: 180, width: 150, height: 150 } },
      ],
      links: [
        // oa <-> ob, two shared places: one connector.
        { id: "l1", type: "placeFusion", sourceId: "p1", targetId: "p3", quantity: 1 },
        { id: "l2", type: "placeFusion", sourceId: "p2", targetId: "p4", quantity: 1 },
        // oa <-> oc: a different pair, a connector of its own.
        { id: "l3", type: "placeFusion", sourceId: "p5", targetId: "p6", quantity: 1 },
      ],
    };
  }

  it("colours the clicked strand with the accent and its connector siblings with the held-back tint", () => {
    const net = netWithTwoConnectors();
    const selectedIds = new Set(["l1"]);
    const connectorSiblingIds = new Set(
      connectorOf(net, "l1")
        .filter((l) => l.id !== "l1")
        .map((l) => l.id),
    );
    const { edges } = buildGraph(
      net,
      selectedIds,
      null,
      null,
      "curved",
      "rect",
      undefined,
      undefined,
      undefined,
      true,
      connectorSiblingIds,
    );

    const clicked = edges.find((e) => e.id === "l1")!;
    const sibling = edges.find((e) => e.id === "l2")!;
    const otherConnector = edges.find((e) => e.id === "l3")!;

    const clickedStroke = (clicked.style as { stroke: string }).stroke;
    const siblingStroke = (sibling.style as { stroke: string }).stroke;
    const otherStroke = (otherConnector.style as { stroke: string }).stroke;

    expect(clicked.selected).toBe(true);
    expect(sibling.selected).toBe(false);
    // Two distinct colours for the clicked strand and its held-back siblings…
    expect(siblingStroke).not.toBe(clickedStroke);
    // …and neither the accent nor the held-back tint is the plain, unrelated
    // fusion colour that an edge outside any connector selection keeps.
    expect(otherStroke).not.toBe(clickedStroke);
    expect(otherStroke).not.toBe(siblingStroke);
    expect(otherStroke).toBe("#a855f7");
  });

  it("leaves every fusion edge in the default colour when nothing is selected", () => {
    const net = netWithTwoConnectors();
    const { edges } = buildGraph(net, new Set(), null);
    for (const id of ["l1", "l2", "l3"]) {
      expect((edges.find((e) => e.id === id)!.style as { stroke: string }).stroke).toBe("#a855f7");
    }
  });
});
