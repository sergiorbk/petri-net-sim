import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ReactFlow, Background, Controls, ConnectionMode, type ReactFlowInstance } from "@xyflow/react";
import { useSimulationStore } from "@/stores/simulation-store";
import { useWorkbenchStore } from "@/stores/workbench-store";
import { useUiStore } from "@/stores/ui-store";
import { useEditorStore } from "@/stores/editor-store";
import { buildGraph, NODE_TYPES, EDGE_TYPES } from "@/apps/simulator/EditorCanvas";
import { cn } from "@/lib/utils";
import type { PetriNetData, SimulationSnapshot } from "@/types/petri";

export function ReadOnlyCanvas() {
  const { t } = useTranslation();
  const simNet = useSimulationStore((s) => s.net);
  const snapshot = useSimulationStore((s) => s.currentSnapshot);
  const liveDraft = useWorkbenchStore((s) => s.liveDraft);
  const isNetMutating = useWorkbenchStore((s) => s.isNetMutating);

  const net = liveDraft ?? simNet;

  if (!net || net.places.length === 0) {
    if (isNetMutating) {
      return (
        <div className="flex h-full w-full items-center justify-center bg-zinc-50 dark:bg-zinc-950">
          <div className="text-center text-text-muted">
            <Spinner className="mx-auto mb-3 h-6 w-6 animate-spin" />
            <p className="text-sm">{t("workbench.generating")}</p>
          </div>
        </div>
      );
    }
    return (
      <div className="flex h-full w-full items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        <div className="text-center text-text-muted">
          <PetriIcon className="mx-auto mb-3 h-10 w-10 opacity-40" />
          <p className="text-sm">{t("workbench.empty.title")}</p>
          <p className="mt-1 text-xs">{t("workbench.empty.hint")}</p>
        </div>
      </div>
    );
  }

  return <ReadOnlyPetriFlow net={net} snapshot={liveDraft ? null : snapshot} />;
}

interface ReadOnlyPetriFlowProps {
  net: PetriNetData;
  snapshot: SimulationSnapshot | null;
}

/**
 * The actual canvas, once there's a net to show. Nodes/edges come straight
 * from EditorCanvas's own `buildGraph` — same places, transitions, object
 * frames (with their border ports and auto-fit sizing/margins), arcs, links
 * and firing pulse, so a generated net reads exactly like it would on the
 * main editor canvas instead of a second, thinner rendering of it. Nothing
 * here is draggable, selectable, or editable; `nodesDraggable={false}` and
 * empty selection/handlers are all it takes since buildGraph itself already
 * treats those as "off".
 */
function ReadOnlyPetriFlow({ net, snapshot }: ReadOnlyPetriFlowProps) {
  const resolvedTheme = useUiStore((s) => s.resolvedTheme);
  const edgeStyle = useEditorStore((s) => s.edgeStyle);
  const frameStyle = useEditorStore((s) => s.frameStyle);

  const emptySelection = useMemo(() => new Set<string>(), []);
  const { nodes, edges } = useMemo(
    () => buildGraph(net, emptySelection, null, snapshot, edgeStyle, frameStyle, undefined, undefined, undefined, false),
    [net, emptySelection, snapshot, edgeStyle, frameStyle],
  );

  const proOptions = useMemo(() => ({ hideAttribution: true }), []);

  // Fitting is done entirely by hand (onInit below, plus this effect), NOT
  // via React Flow's own `fitView` boolean prop: that prop only ever
  // auto-fits ONCE, on mount, and never again -- but this net streams in
  // across several tool-call batches while the agent builds it (and can
  // jump entirely on a version switch), so the mount-time fit is for
  // whatever partial/different net happened to exist at that moment;
  // everything added or changed afterward renders at the SAME stale pan/
  // zoom, with no relationship to where it actually landed. That reads as
  // a jumbled mess even though the underlying coordinates (buildGraph, same
  // as the main editor) are perfectly laid out -- confirmed by the fact
  // that opening the exact same net in the main editor, a fresh ReactFlow
  // mount with its own fresh fit, renders it correctly every time.
  // Re-fitting explicitly whenever the node set changes keeps the viewport
  // honest without the underlying net data or layout needing to know
  // anything about window/panel size.
  const rfInstance = useRef<ReactFlowInstance | null>(null);
  const nodeSignature = nodes.map((n) => n.id).join(",");
  useEffect(() => {
    // Debounced: a burst of streaming tool-call batches changes
    // nodeSignature several times within a few hundred ms, and React Flow
    // measures each newly-added node's real size via ResizeObserver
    // asynchronously — calling fitView immediately, on every one of those
    // changes, computes bounds from whatever is measured SO FAR (often
    // wrong) and each call cancels the previous one's in-flight animation
    // before it settles. Waiting for a quiet moment after the last change
    // both coalesces the burst into one fit and gives the new nodes time
    // to be measured first.
    const timer = setTimeout(() => {
      rfInstance.current?.fitView({ padding: 0.2, duration: 200 });
    }, 150);
    return () => clearTimeout(timer);
  }, [nodeSignature]);

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        elevateNodesOnSelect={false}
        onInit={(instance) => {
          rfInstance.current = instance;
          instance.fitView({ padding: 0.2 });
        }}
        proOptions={proOptions}
        connectionMode={ConnectionMode.Loose}
        nodesDraggable={false}
        nodesConnectable={false}
        // Lower than the main editor's own 0.25: composed nets with several
        // objects side by side routinely need a smaller zoom to fit at all
        // in this panel, which is far narrower than the main editor ever is.
        minZoom={0.1}
        maxZoom={4}
        colorMode={resolvedTheme}
        className="bg-zinc-50 dark:bg-zinc-950"
      >
        <Background color={resolvedTheme === "dark" ? "#52525b" : "#d4d4d8"} gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
      <StatsOverlay net={net} snapshot={snapshot} />
    </div>
  );
}

interface StatsOverlayProps {
  net: PetriNetData;
  snapshot: SimulationSnapshot | null;
}

function StatsOverlay({ net, snapshot }: StatsOverlayProps) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);

  const hasActiveTransitions = net.transitions.some(
    (t) => (snapshot?.buffers[t.id] ?? 0) > 0,
  );

  return (
    <div className="absolute bottom-2 right-2 z-10 w-52 rounded-lg border border-zinc-200 bg-white/95 text-xs shadow backdrop-blur-sm dark:border-zinc-700 dark:bg-zinc-900/95">
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center justify-between px-2.5 py-2 text-left"
      >
        <span className="font-semibold text-zinc-500 dark:text-zinc-400">
          {t("workbench.canvas.tokenCounts")}
        </span>
        <svg
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform dark:text-zinc-500",
            collapsed && "rotate-180",
          )}
          viewBox="0 0 16 16"
          fill="currentColor"
        >
          <path d="M3.5 5.5 8 10l4.5-4.5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {!collapsed && (
        <div className="max-h-48 overflow-y-auto px-2.5 pb-2.5">
          <div className="space-y-0.5">
            {net.places.map((p) => {
              const count = snapshot ? (snapshot.markings[p.id] ?? 0) : p.tokens;
              return (
                <div key={p.id} className="flex items-center justify-between gap-2">
                  <span className="truncate text-zinc-600 dark:text-zinc-400">
                    {p.name}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 tabular-nums",
                      count > 0
                        ? "font-bold text-emerald-600 dark:text-emerald-400"
                        : "text-zinc-300 dark:text-zinc-600",
                    )}
                  >
                    {count}
                  </span>
                </div>
              );
            })}
          </div>

          {hasActiveTransitions && (
            <>
              <p className="mb-1 mt-2 font-semibold text-zinc-500 dark:text-zinc-400">
                {t("workbench.canvas.activeBuffers")}
              </p>
              <div className="space-y-0.5">
                {net.transitions
                  .filter((t) => (snapshot?.buffers[t.id] ?? 0) > 0)
                  .map((t) => (
                    <div
                      key={t.id}
                      className="flex items-center justify-between gap-2"
                    >
                      <span className="truncate text-zinc-600 dark:text-zinc-400">
                        {t.name}
                      </span>
                      <span className="shrink-0 font-bold tabular-nums text-amber-500 dark:text-amber-400">
                        {snapshot?.buffers[t.id] ?? 0}
                      </span>
                    </div>
                  ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Spinner({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M12 3a9 9 0 1 0 9 9" strokeLinecap="round" />
    </svg>
  );
}

function PetriIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="6" r="3" />
      <circle cx="18" cy="18" r="3" />
      <rect x="10" y="9" width="4" height="6" rx="1" />
      <line x1="9" y1="12" x2="10" y2="12" />
      <line x1="14" y1="10" x2="15" y2="8" />
      <line x1="14" y1="14" x2="15" y2="16" />
    </svg>
  );
}
