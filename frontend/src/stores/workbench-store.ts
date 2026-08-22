import { create } from "zustand";
import type {
  PetriArc,
  PetriNetData,
  PetriPlace,
  PetriTransition,
  ArcType,
} from "@/types/petri";

interface WorkbenchState {
  liveDraft: PetriNetData | null;
  isNetMutating: boolean;
  appliedStepIds: Record<string, true>;

  beginLiveBuild: () => void;
  endLiveBuild: () => void;
  applyToolEvent: (
    stepId: string,
    toolName: string,
    input: Record<string, unknown>,
  ) => void;
}

function emptyNet(): PetriNetData {
  return { name: "Generating…", places: [], transitions: [], arcs: [] };
}

function isNetMutatingTool(toolName: string): boolean {
  return (
    toolName === "create_network" ||
    toolName === "optimize_network" ||
    toolName.startsWith("add_") ||
    toolName.startsWith("remove_") ||
    toolName.startsWith("modify_") ||
    toolName.startsWith("connect_")
  );
}

export const useWorkbenchStore = create<WorkbenchState>((set) => ({
  liveDraft: null,
  isNetMutating: false,
  appliedStepIds: {},

  beginLiveBuild: () => set({ liveDraft: null, isNetMutating: false, appliedStepIds: {} }),
  endLiveBuild: () => set({ liveDraft: null, isNetMutating: false, appliedStepIds: {} }),

  applyToolEvent: (stepId, toolName, input) =>
    set((state) => {
      if (state.appliedStepIds[stepId]) return state;

      // On first net-mutating tool in this turn, activate the live build overlay.
      const wasAlreadyMutating = state.isNetMutating;
      const mutating = wasAlreadyMutating || isNetMutatingTool(toolName);
      const draft = state.liveDraft ?? (mutating ? emptyNet() : null);

      if (!draft) {
        // Non-mutating tool, nothing to do yet.
        return { appliedStepIds: { ...state.appliedStepIds, [stepId]: true } };
      }

      const next = reduceToolEvent(draft, toolName, input);
      return {
        liveDraft: next,
        isNetMutating: mutating,
        appliedStepIds: { ...state.appliedStepIds, [stepId]: true },
      };
    }),
}));

/**
 * Apply one net-mutating tool call to the live draft. Unknown tool names
 * are no-ops. Tools that produce a structurally invalid update (missing IDs,
 * unknown source/target) are dropped silently — the final snapshot from the
 * backend is the source of truth, so partial frontend draft errors are not
 * worth surfacing.
 */
function reduceToolEvent(
  net: PetriNetData,
  toolName: string,
  input: Record<string, unknown>,
): PetriNetData {
  switch (toolName) {
    case "add_place": {
      const id = str(input.id) ?? str(input.place_id);
      const name = str(input.name) ?? id;
      if (!id) return net;
      if (net.places.some((p) => p.id === id)) return net;
      const place: PetriPlace = {
        id,
        name: name ?? id,
        tokens: num(input.tokens) ?? 0,
        graphics: { x: 0, y: 0 },
      };
      return { ...net, places: [...net.places, place] };
    }
    case "add_transition": {
      const id = str(input.id) ?? str(input.transition_id);
      const name = str(input.name) ?? id;
      if (!id) return net;
      if (net.transitions.some((t) => t.id === id)) return net;
      const transition: PetriTransition = {
        id,
        name: name ?? id,
        priority: num(input.priority) ?? 0,
        distribution: distType(input.distribution),
        mean_delay: num(input.mean_delay) ?? 0,
        standard_deviation: num(input.standard_deviation) ?? 0,
        probability: num(input.probability) ?? null,
        graphics: { x: 0, y: 0 },
      };
      return { ...net, transitions: [...net.transitions, transition] };
    }
    case "add_arc": {
      const id = str(input.id) ?? str(input.arc_id);
      const source_id = str(input.source_id) ?? str(input.source);
      const target_id = str(input.target_id) ?? str(input.target);
      if (!id || !source_id || !target_id) return net;
      if (net.arcs.some((a) => a.id === id)) return net;
      const arc: PetriArc = {
        id,
        source_id,
        target_id,
        weight: num(input.weight) ?? 1,
        arc_type: arcType(input.arc_type),
      };
      return { ...net, arcs: [...net.arcs, arc] };
    }
    default:
      return net;
  }
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function arcType(v: unknown): ArcType {
  if (v === "INHIBITOR" || v === "READ" || v === "NORMAL") return v;
  return "NORMAL";
}

function distType(v: unknown): PetriTransition["distribution"] {
  if (v === "exp" || v === "norm" || v === "unif" || v === "det") return v;
  return null;
}
