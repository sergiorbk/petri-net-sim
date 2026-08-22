import { useEffect, useMemo, useRef, useState } from "react";
import { useReactFlow } from "@xyflow/react";
import { useSimulationStore } from "@/stores/simulation-store";
import { useEditorStore } from "@/stores/editor-store";
import type { PetriNetData } from "@/types/petri";

const PLACE_W = 56;
const PLACE_H = 56;
const TRANS_W = 28;
const TRANS_H = 64;
const TOKEN_R = 5;
const TOKEN_COLOR = "#10b981";

interface AnimatingToken {
  id: string;
  path: { x: number; y: number }[];
  startMs: number;
  durationMs: number;
}

function nodeCenter(
  net: PetriNetData,
  nodeId: string,
): { x: number; y: number } | null {
  const p = net.places.find((pl) => pl.id === nodeId);
  if (p)
    return {
      x: p.graphics.x + PLACE_W / 2,
      y: p.graphics.y + PLACE_H / 2,
    };
  const t = net.transitions.find((tr) => tr.id === nodeId);
  if (t)
    return {
      x: t.graphics.x + TRANS_W / 2,
      y: t.graphics.y + TRANS_H / 2,
    };
  return null;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function interpolatePath(
  path: { x: number; y: number }[],
  t: number,
): { x: number; y: number } {
  if (path.length === 0) return { x: 0, y: 0 };
  if (path.length === 1) return path[0];
  const clamped = Math.max(0, Math.min(1, t));
  const totalSegments = path.length - 1;
  const segment = clamped * totalSegments;
  const idx = Math.min(Math.floor(segment), totalSegments - 1);
  const local = segment - idx;
  return {
    x: lerp(path[idx].x, path[idx + 1].x, local),
    y: lerp(path[idx].y, path[idx + 1].y, local),
  };
}

function buildInputArcsForTransition(
  net: PetriNetData,
  transitionId: string,
): { sourceId: string; targetId: string }[] {
  return net.arcs
    .filter(
      (a) =>
        a.target_id === transitionId &&
        net.places.some((p) => p.id === a.source_id),
    )
    .map((a) => ({ sourceId: a.source_id, targetId: a.target_id }));
}

function buildOutputArcsForTransition(
  net: PetriNetData,
  transitionId: string,
): { sourceId: string; targetId: string }[] {
  return net.arcs
    .filter(
      (a) =>
        a.source_id === transitionId &&
        net.places.some((p) => p.id === a.target_id),
    )
    .map((a) => ({ sourceId: a.source_id, targetId: a.target_id }));
}

export function TokenAnimationOverlay() {
  const smoothAnimations = useSimulationStore((s) => s.smoothAnimations);
  const editorMode = useSimulationStore((s) => s.editorMode);
  const currentSnapshot = useSimulationStore((s) => s.currentSnapshot);
  const previousSnapshot = useSimulationStore((s) => s.previousSnapshot);
  const timeStep = useSimulationStore((s) => s.timeStep);
  const playbackRate = useSimulationStore((s) => s.playbackRate);
  const net = useEditorStore((s) => s.net);

  const { getViewport } = useReactFlow();

  const [tokens, setTokens] = useState<AnimatingToken[]>([]);
  const rafRef = useRef<number | null>(null);
  const [, forceRender] = useState(0);

  const durationMs = useMemo(() => {
    const raw = (timeStep / playbackRate) * 1000;
    return Math.max(60, Math.min(raw * 0.8, 800));
  }, [timeStep, playbackRate]);

  useEffect(() => {
    if (!smoothAnimations || editorMode !== "simulating") {
      setTokens([]);
      return;
    }

    if (!currentSnapshot?.fired_transitions?.length) return;
    if (
      previousSnapshot &&
      currentSnapshot.step_number === previousSnapshot.step_number &&
      currentSnapshot.active_phase === previousSnapshot.active_phase &&
      currentSnapshot.active_transition_id === previousSnapshot.active_transition_id
    )
      return;

    const activePhase = currentSnapshot.active_phase;
    const activeTId = currentSnapshot.active_transition_id;

    const now = performance.now();
    const newTokens: AnimatingToken[] = [];
    let counter = 0;

    for (const tId of currentSnapshot.fired_transitions) {
      const tCenter = nodeCenter(net, tId);
      if (!tCenter) continue;

      const showInput = !activePhase || activePhase === "before_act_in";
      const showOutput = !activePhase || activePhase === "before_act_out";

      if (activeTId && tId !== activeTId) continue;

      if (showInput) {
        const inputs = buildInputArcsForTransition(net, tId);
        for (const { sourceId } of inputs) {
          const src = nodeCenter(net, sourceId);
          if (!src) continue;
          counter++;
          newTokens.push({
            id: `in-${tId}-${sourceId}-${now}-${counter}`,
            path: [src, tCenter],
            startMs: now,
            durationMs,
          });
        }
      }

      if (showOutput) {
        const outputs = buildOutputArcsForTransition(net, tId);
        for (const { targetId } of outputs) {
          const tgt = nodeCenter(net, targetId);
          if (!tgt) continue;
          counter++;
          newTokens.push({
            id: `out-${tId}-${targetId}-${now}-${counter}`,
            path: [tCenter, tgt],
            startMs: now,
            durationMs,
          });
        }
      }
    }

    if (newTokens.length > 0) {
      setTokens((prev) => [...prev, ...newTokens]);
    }
  }, [
    currentSnapshot,
    previousSnapshot,
    net,
    durationMs,
    smoothAnimations,
    editorMode,
  ]);

  useEffect(() => {
    if (tokens.length === 0) return;

    function tick() {
      const now = performance.now();
      setTokens((prev) => {
        const alive = prev.filter(
          (t) => now < t.startMs + t.durationMs,
        );
        return alive.length === prev.length ? prev : alive;
      });
      forceRender((n) => n + 1);
      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [tokens.length > 0]);

  if (!smoothAnimations || editorMode !== "simulating" || tokens.length === 0) {
    return null;
  }

  const vp = getViewport();
  const now = performance.now();

  return (
    <svg
      className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible"
      style={{
        transform: `translate(${vp.x}px, ${vp.y}px) scale(${vp.zoom})`,
        transformOrigin: "0 0",
      }}
    >
      {tokens.map((token) => {
        const elapsed = now - token.startMs;
        if (elapsed < 0) return null;
        const t = Math.min(1, elapsed / token.durationMs);
        const eased = 1 - (1 - t) * (1 - t);
        const pos = interpolatePath(token.path, eased);
        const opacity = t > 0.8 ? 1 - (t - 0.8) / 0.2 : 1;

        return (
          <circle
            key={token.id}
            cx={pos.x}
            cy={pos.y}
            r={TOKEN_R / vp.zoom}
            fill={TOKEN_COLOR}
            opacity={opacity}
          />
        );
      })}
    </svg>
  );
}
