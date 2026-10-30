import { describe, expect, it } from "vitest";
import type { PetriNetData } from "@/types/petri";
import { exportPnml } from "./pnml-export";
import { parsePnml } from "./pnml-import";

function counterNet(composed: boolean): PetriNetData {
  const objectId = composed ? "module" : undefined;
  return {
    name: "Tagged counter",
    places: [
      { id: "source", name: "Source", tokens: 6, graphics: { x: 0, y: 0 }, objectId },
      { id: "completed", name: "Completed", tokens: 0, tag: "throughput", graphics: { x: 200, y: 0 }, objectId },
    ],
    transitions: [{ id: "service", name: "Service", distribution: "det", mean_delay: 1,
      standard_deviation: 0, probability: null, priority: 1, graphics: { x: 100, y: 0 }, objectId }],
    arcs: [
      { id: "in", source_id: "source", target_id: "service", weight: 1, arc_type: "NORMAL" },
      { id: "out", source_id: "service", target_id: "completed", weight: 1, arc_type: "NORMAL" },
    ],
    ...(composed ? { objects: [{ id: "module", name: "Service module", priority: 0,
      graphics: { x: 0, y: 0, width: 300, height: 150 } }] } : {}),
  };
}

describe("PNML place role persistence", () => {
  it.each([false, true])("preserves a throughput counter through repeated round trips (composed=%s)", (composed) => {
    const first = parsePnml(exportPnml(counterNet(composed))).data;
    const reopened = parsePnml(exportPnml(first)).data;
    expect(reopened.places.find((place) => place.name === "Completed")?.tag).toBe("throughput");
    expect(reopened.places.find((place) => place.name === "Source")?.tokens).toBe(6);
  });

  it("escapes and restores arbitrary semantic tags", () => {
    const net = counterNet(false);
    net.places[1].tag = 'custom & "quoted"';
    expect(parsePnml(exportPnml(net)).data.places[1].tag).toBe('custom & "quoted"');
  });

  it("preserves the role of a place projected as a fusion reference", () => {
    const net = counterNet(true);
    net.transitions = [];
    net.arcs = [];
    net.objects!.push({ id: "other", name: "Other module", priority: 0,
      graphics: { x: 350, y: 0, width: 200, height: 150 } });
    net.places[0].tag = "throughput";
    net.places[1].tag = "shared-view";
    net.places[1].objectId = "other";
    net.links = [{ id: "fusion", type: "placeFusion", sourceId: "completed", targetId: "source", quantity: 1 }];
    const reopened = parsePnml(exportPnml(net)).data;
    expect(Object.fromEntries(reopened.places.map((place) => [place.name, place.tag])))
      .toEqual({ Source: "throughput", Completed: "shared-view" });
  });
});
