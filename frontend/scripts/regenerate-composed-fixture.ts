// Regenerates frontend/src/lib/__fixtures__/composed_conformant_v21.pnml by
// actually running exportComposedPnml, the same TypeScript exporter
// pnml-export.test.ts checks itself against. Never hand-edit that fixture:
// run this script instead, so the file always reflects what the exporter
// really emits (including the current package.json version, since
// PETRI_NET_SIM_VERSION is read from there).
//
// This is the frontend half of backend/scripts/bump_version.py's fixture
// regeneration step; that script shells out to this one with vite-node
// because the fixture is exercised by, and must match, the TypeScript
// writer, not the Python one (backend/tests/fixtures/composed_conformant_v21.pnml
// is the Python writer's own golden fixture, regenerated separately by the
// same parent script via a direct import).
//
// Run from frontend/: npx vite-node scripts/regenerate-composed-fixture.ts
//
// The request body below is the same §7 worked example
// (frontend/src/lib/pnml-export.test.ts's pipelineDemoRequest) kept in sync
// by hand: two independent hand-authored copies of one canonical worked
// example is the existing pattern this repo already uses for the fixture's
// backend twin (test_composed_pnml_exporter.py's pipeline_demo_model), not
// something this script introduces.

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { exportComposedPnml } from "../src/lib/pnml-export-composed";
import type { ComposedSimulateBody } from "../src/lib/composed-simulation-client";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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
      // link type, and the exporter now refuses a request that has one.
    ],
  };
}

const xml = exportComposedPnml(pipelineDemoRequest());
const outPath = path.join(__dirname, "..", "src", "lib", "__fixtures__", "composed_conformant_v21.pnml");
writeFileSync(outPath, xml, "utf-8");
console.log(`Wrote ${outPath}`);
