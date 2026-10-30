import { describe, expect, it } from "vitest";
import { parsePnml } from "./pnml-import";
import { exportPnml } from "./pnml-export";

describe("Desktop transition parameters in portable review", () => {
  it("does not introduce an exponential delay or higher priority", () => {
    const xml = '<pnml><net id="n"><page id="page"><transition id="t"><toolspecific tool="PetriObjModel" version="2.5.0"><timeDelay>5</timeDelay></toolspecific></transition></page></net></pnml>';
    const { data, warnings } = parsePnml(xml);
    expect(warnings).toEqual([]);
    expect(data.transitions[0]).toMatchObject({ distribution: "det", mean_delay: 5, priority: 0 });
    data.transitions[0].probability = 0.5;
    const reopened = parsePnml(exportPnml(data)).data;
    expect(reopened.transitions[0]).toMatchObject({ distribution: "det", mean_delay: 5, priority: 0, probability: 0.5 });
  });
});
