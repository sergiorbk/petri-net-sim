import { XMLBuilder } from "fast-xml-parser";
import type { PetriNetData } from "@/types/petri";
import { buildComposedRequest } from "@/lib/composed-simulation-client";
import { isComposedNet } from "@/lib/petri-composed";
import { PLACE_H, PLACE_W, TRANS_H, TRANS_W } from "@/lib/petri-geometry";
import { PETRI_NET_SIM_VERSION, TOOL_PETRI_NET_SIM, buildIdRemap } from "@/lib/pnml-export-composed";
import { exportComposedPnml } from "@/lib/pnml-export-composed";

function randomHex8(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(4)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function buildExportFilename(
  name: string,
  ext: string,
  options?: { version?: number; id?: string },
): string {
  const safeName = name.replace(/[^a-zA-Z0-9_-]/g, "_");
  const tail = (options?.id ?? randomHex8()).slice(0, 8);
  const version = options?.version != null ? `_v${options.version}` : "";
  return `${safeName}${version}_${tail}.${ext}`;
}

const builder = new XMLBuilder({
  ignoreAttributes: false,
  attributeNamePrefix: "@_",
  format: true,
  indentBy: "  ",
  suppressEmptyNode: false,
});

function resolveExportNames(net: PetriNetData): {
  placeNames: Map<string, string>;
  transitionNames: Map<string, string>;
} {
  const placeNameSet = new Set(net.places.map((p) => p.name));
  const conflicting = new Set(
    net.transitions.filter((t) => placeNameSet.has(t.name)).map((t) => t.name),
  );

  const placeNames = new Map(net.places.map((p) => [p.id, p.name]));
  const transitionNames = new Map(
    net.transitions.map((t) => [
      t.id,
      conflicting.has(t.name) ? `${t.name}_${t.id.slice(0, 8)}` : t.name,
    ]),
  );

  return { placeNames, transitionNames };
}

/**
 * Exports a canvas to PNML. A truly flat net keeps exporting exactly what it
 * exports today: that is a shipped format with users' files in it. Any canvas
 * that says something a flat net cannot — a frame, a link — gets the
 * ISO/IEC 15909-2 conformant multi-page shape.
 *
 * The file dispatch is deliberately wider than the engine dispatch
 * (`needsObjectEngine`): one frame with no links simulates fine as a flat
 * projection, but writing it flat would drop the frame from the reopened
 * canvas. A file has to come back as the same drawing, so the question here
 * is "does the canvas carry structure", not "which engine runs it".
 */
export function exportPnml(net: PetriNetData): string {
  if (!isComposedNet(net)) return exportFlatPnml(net);
  // A file is not a simulation request either: an object the engine would
  // have nothing to run — a frame that only holds other frames, a frame the
  // user emptied — is still written.
  return exportComposedPnml(buildComposedRequest(net, { includeEmptyObjects: true })!);
}

/**
 * One tool-specific payload under this app's own tool identity, the
 * object-tree form of the composed writer's toolspecificBlocks. Still an
 * array of one so the builder's repeat-element machinery stays the same
 * shape regardless of how many identities a payload is written under.
 */
function toolspecificBlocks(payload: Record<string, unknown>): Record<string, unknown>[] {
  return [{ "@_tool": TOOL_PETRI_NET_SIM, "@_version": PETRI_NET_SIM_VERSION, ...payload }];
}

function exportFlatPnml(net: PetriNetData): string {
  const { placeNames, transitionNames } = resolveExportNames(net);

  // Safety net for hand-assembled data: canvas-minted ids (petri-ids.ts) are
  // always NCName-safe, so this only ever moves an id a foreign import or a
  // hand-built request carried in with an illegal character. It also covers
  // a place and a transition sharing one raw id (independent id spaces in
  // the app model, so nothing stops that in hand-assembled data), giving the
  // two distinct final ids instead of writing the same id twice. Each
  // `emitOwn*Id` looks its element up by position in the very list
  // `buildIdRemap` assigned from, so which occurrence is which is never in
  // question; an arc's source/target instead `resolve` the raw id they
  // reference, which lands on the FIRST element that ever carried it.
  const placeCount = net.places.length;
  const transitionCount = net.transitions.length;
  const { ids: finalIds, resolve } = buildIdRemap([
    ...net.places.map((p) => p.id),
    ...net.transitions.map((t) => t.id),
    ...net.arcs.map((a) => a.id),
  ]);
  const emitOwnPlaceId = (index: number) => finalIds[index];
  const emitOwnTransitionId = (index: number) => finalIds[placeCount + index];
  const emitOwnArcId = (index: number) => finalIds[placeCount + transitionCount + index];

  const places = net.places.map((p, i) => {
    // Wire position is the CENTER of the place shape; the app model keeps
    // React Flow's top-left anchor (graphics.x/y).
    const x = Math.round(p.graphics.x + PLACE_W / 2);
    const y = Math.round(p.graphics.y + PLACE_H / 2);
    // A plain place has nothing left to say in toolspecific once <coordinates>
    // is gone (PNML ISO conformance contract, decision 1): no block at all,
    // the same precedent a NORMAL arc's own toolspecific-free case sets below.
    const place: Record<string, unknown> = {
      "@_id": emitOwnPlaceId(i),
      name: { text: placeNames.get(p.id) ?? p.name },
      graphics: {
        position: { "@_x": x, "@_y": y },
      },
    };
    if (p.tokens > 0) {
      place.initialMarking = { text: p.tokens };
    }
    return place;
  });

  const transitions = net.transitions.map((t, i) => {
    const x = Math.round(t.graphics.x + TRANS_W / 2);
    const y = Math.round(t.graphics.y + TRANS_H / 2);
    const ts: Record<string, unknown> = {};

    if (t.probability !== null) {
      ts.probability = t.probability;
    } else if (t.distribution) {
      ts.timeDelay = t.mean_delay;
      ts.delayMeanValue = t.mean_delay;
      ts.distribution = t.distribution;
      if (t.distribution === "norm" || t.distribution === "unif") {
        ts.standardDeviation = t.standard_deviation;
      }
      ts.priority = t.priority;
    } else {
      ts.timeDelay = 0;
      ts.delayMeanValue = 0;
      ts.distribution = "det";
      ts.priority = t.priority;
    }

    return {
      "@_id": emitOwnTransitionId(i),
      name: { text: transitionNames.get(t.id) ?? t.name },
      toolspecific: toolspecificBlocks(ts),
      graphics: {
        position: { "@_x": x, "@_y": y },
      },
    };
  });

  const arcs = net.arcs.map((a, i) => {
    const arc: Record<string, unknown> = {
      "@_id": emitOwnArcId(i),
      "@_source": resolve(a.source_id),
      "@_target": resolve(a.target_id),
      graphics: "",
      inscription: { text: a.weight },
    };
    // An inhibitor/read arc has no P/T-net form, so the kind can only survive
    // in a tool-specific block. Written exactly as the composed writer's
    // ownArcXml writes it, so one document shape says it and both readers
    // (this app's and the desktop's PnmlParser.parseArcs) recognise it. A
    // NORMAL arc keeps emitting no tool-specific block of its own.
    if (a.arc_type !== "NORMAL") {
      arc.toolspecific = toolspecificBlocks({ arcType: a.arc_type.toLowerCase() });
    }
    return arc;
  });

  const doc = {
    "?xml": { "@_version": "1.0", "@_encoding": "UTF-8", "@_standalone": "no" },
    pnml: {
      "@_xmlns": "http://www.pnml.org/version-2009/grammar/pnml",
      net: {
        "@_id": "net1",
        "@_type": "http://www.pnml.org/version-2009/grammar/ptnet",
        name: { text: net.name },
        page: {
          "@_id": "page1",
          place: places,
          transition: transitions,
          arc: arcs,
        },
      },
    },
  };

  return builder.build(doc) as string;
}
