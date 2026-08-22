import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { cn } from "@/lib/utils";
import type { ComputedHandle, HandleSide } from "./PlaceNode";

export interface TransitionNodeData {
  label: string;
  distribution: string | null;
  meanDelay: number;
  standardDeviation: number;
  priority: number;
  probability: number | null;
  buffer: number;
  handles: ComputedHandle[];
  /** Set to true for one animation frame to trigger pulse on transition fire. */
  pulsing?: boolean;
  /**
   * Names of elements outside this object this transition connects to. Only
   * set while viewing the object's own canvas — see PlaceNodeData's field of
   * the same name for why the connection itself can't be drawn here.
   */
  externalConnections?: string[];
}

interface TransitionNodeProps {
  data: TransitionNodeData;
  selected?: boolean;
}

const SIDE_TO_POSITION: Record<HandleSide, Position> = {
  left:   Position.Left,
  right:  Position.Right,
  top:    Position.Top,
  bottom: Position.Bottom,
};

function handleStyle(side: HandleSide, offset: number): React.CSSProperties {
  return side === "left" || side === "right"
    ? { top: `${offset}%` }
    : { left: `${offset}%` };
}

function fmtSecs(secs: number): string {
  if (secs === 0) return "0s";
  if (secs < 60) return `${+secs.toFixed(2)}s`;
  if (secs < 3600) return `${+(secs / 60).toFixed(2)}m`;
  return `${+(secs / 3600).toFixed(2)}h`;
}

function formatDelay(distribution: string | null, meanDelay: number, stdDev: number): string {
  if (!distribution) return "imm";
  const mean = fmtSecs(meanDelay);
  const spread = (distribution === "norm" || distribution === "unif") && stdDev > 0
    ? `±${fmtSecs(stdDev)}`
    : "";
  return `${distribution} ${mean}${spread}`;
}

export const TransitionNode = memo(({ data, selected }: TransitionNodeProps) => {
  const active = data.buffer > 0;
  const pulsing = data.pulsing ?? false;
  const showPriority = data.priority > 1;
  const showProb = data.probability !== null && data.probability !== 1;

  return (
    <div className="flex flex-col items-center">
      {/* Handles live inside the rectangle so top/left % is relative to its
          dimensions — this keeps connection points visually centred. */}
      <div
        className={cn(
          "relative flex h-16 w-7 items-center justify-center border-[3px]",
          !pulsing && "transition-colors duration-200",
          selected
            ? "border-blue-500 shadow-md shadow-blue-200/60 dark:shadow-blue-900/60"
            : active
              ? "border-amber-500 dark:border-amber-400"
              : "border-zinc-300 dark:border-zinc-200",
          active
            ? "bg-amber-50 dark:bg-amber-950/40"
            : "bg-white dark:bg-zinc-900",
          pulsing && "petri-pulse-transition",
        )}
      >
        {data.handles.map((h) => (
          <Handle
            key={h.id}
            id={h.id}
            type={h.type}
            position={SIDE_TO_POSITION[h.side]}
            style={handleStyle(h.side, h.offset)}
            className="!border-0 !bg-transparent"
          />
        ))}

        {active && (
          <span className="absolute -right-2.5 -top-2.5 flex h-5 w-5 items-center justify-center rounded-full bg-amber-500 text-[9px] font-bold text-white shadow">
            {data.buffer}
          </span>
        )}

        {showPriority && (
          <span className="absolute -left-2 -top-2 flex h-4 w-4 items-center justify-center rounded-full bg-blue-500 text-[8px] font-bold text-white">
            {data.priority}
          </span>
        )}

        {showProb && (
          <span className="absolute -bottom-2 -right-2 flex items-center justify-center rounded-full bg-violet-500 px-1 py-0.5 text-[8px] font-bold text-white leading-none whitespace-nowrap">
            {Math.round((data.probability ?? 0) * 100)}%
          </span>
        )}

        {data.externalConnections && data.externalConnections.length > 0 && (
          <span
            title={data.externalConnections.join(", ")}
            className="absolute -bottom-2 -left-2 flex h-4 w-4 items-center justify-center rounded-full border-2 border-sky-500 bg-white text-[8px] font-bold text-sky-600 dark:bg-zinc-900 dark:text-sky-300"
          >
            {data.externalConnections.length}
          </span>
        )}
      </div>

      <span className="mt-1.5 max-w-[52px] text-center text-[10px] font-medium leading-tight text-zinc-700 dark:text-zinc-300">
        {data.label}
      </span>
      <span className="text-[10px] leading-tight text-zinc-500 dark:text-zinc-400">
        {formatDelay(data.distribution, data.meanDelay, data.standardDeviation)}
      </span>
    </div>
  );
});

TransitionNode.displayName = "TransitionNode";
