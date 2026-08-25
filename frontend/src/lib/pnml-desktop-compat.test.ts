import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { parsePnml } from "./pnml-import";
import { exportPnml } from "./pnml-export";
import { getLinks } from "./petri-object-model";
import type { ObjectLink } from "@/types/petri";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadFixture(name: string): string {
  return readFileSync(path.join(__dirname, "__fixtures__", name), "utf-8");
}

/**
 * The fixture is not hand-written. It is the document PetriObjModelPaint 2.3.0
 * writes from its own release demo model (ReleaseDemoModelTest), copied here
 * unchanged, so this suite tests the two tools against each other rather than
 * this app against its own idea of the format.
 *
 * What that model holds: a dispatcher whose two places are each repeated by
 * four servers, which is the one-to-many shape this release added, arranged so
 * that every dispatcher-server pair shares two places rather than one. It also
 * carries a group of objects, a construct this app deliberately does not
 * implement, which is the interesting part of the compatibility claim: a group
 * is editing-time information, so a reader that skips it has to end up with
 * exactly the same model.
 */
const DESKTOP_DEMO = "desktop_2_3_0_fan_and_connectors.pnml";

function fusionLinks(links: ObjectLink[]): ObjectLink[] {
  return links.filter((l) => l.type === "placeFusion");
}

describe("a document written by PetriObjModelPaint 2.3.0", () => {
  it("opens without complaint", () => {
    const { warnings } = parsePnml(loadFixture(DESKTOP_DEMO));
    expect(warnings).toEqual([]);
  });

  it("keeps every object the document declares", () => {
    const { data } = parsePnml(loadFixture(DESKTOP_DEMO));
    expect(data.objects?.map((o) => o.name)).toEqual([
      "Dispatcher",
      "Server 1",
      "Server 2",
      "Server 3",
      "Server 4",
    ]);
  });

  it("reads both fans, four copies of each dispatcher place", () => {
    const { data } = parsePnml(loadFixture(DESKTOP_DEMO));
    const byMaster = new Map<string, string[]>();
    for (const link of fusionLinks(getLinks(data))) {
      byMaster.set(link.targetId, [...(byMaster.get(link.targetId) ?? []), link.sourceId]);
    }
    // Two masters, four copies each, and no copy repeated twice: exactly the
    // arrangement the old strictly one-to-one rule could not have produced.
    expect([...byMaster.values()].map((copies) => copies.length)).toEqual([4, 4]);
    const copies = fusionLinks(getLinks(data)).map((l) => l.sourceId);
    expect(new Set(copies).size).toBe(copies.length);
  });

  it("ignores the group block rather than choking on it", () => {
    const xml = loadFixture(DESKTOP_DEMO);
    // The document really does carry the construct this app does not implement,
    // otherwise the assertion below would prove nothing.
    expect(xml).toContain("petriObjectGroups");
    const { data, warnings } = parsePnml(xml);
    expect(warnings).toEqual([]);
    expect(data.places.length).toBeGreaterThan(0);
  });

  it("writes the fans back as one reference place per copy, all naming the master", () => {
    const { data } = parsePnml(loadFixture(DESKTOP_DEMO));
    const written = exportPnml(data);
    const refs = [...written.matchAll(/<referencePlace[^>]*\sref="([^"]+)"/g)].map((m) => m[1]);
    expect(refs).toHaveLength(8);
    const perMaster = new Map<string, number>();
    for (const ref of refs) perMaster.set(ref, (perMaster.get(ref) ?? 0) + 1);
    expect([...perMaster.values()].sort()).toEqual([4, 4]);
  });

  it("survives a round trip with the same links", () => {
    const first = parsePnml(loadFixture(DESKTOP_DEMO)).data;
    const second = parsePnml(exportPnml(first)).data;
    const before = fusionLinks(getLinks(first)).length;
    const after = fusionLinks(getLinks(second)).length;
    expect(after).toBe(before);
    expect(after).toBe(8);
  });
});
