import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { cn } from "@/lib/utils";

export type HandleSide = "left" | "right" | "top" | "bottom";

/** A single connection point rendered on a node for one specific arc. */
export interface ComputedHandle {
  id: string;
  type: "source" | "target";
  side: HandleSide;
  /** Percentage offset along the side (0–100). */
  offset: number;
}

export interface PlaceNodeData {
  label: string;
  tokens: number;
  initialTokens: number;
  handles: ComputedHandle[];
  /** Set to true for one animation frame to trigger pulse on token change. */
  pulsing?: boolean;
  /**
   * Name of the fusion group this place belongs to, if any. Fusion means two
   * places in different objects ARE one place; the badge says so on the place
   * itself, which still reads when the partner is off-screen or on another
   * canvas and the tie between them isn't visible.
   */
  fusionLabel?: string;
  /** Tooltip naming the places this one is fused with. */
  fusionTitle?: string;
  /**
   * Names of elements outside this object this place connects to. Only set
   * while viewing the object's own canvas — extracting it for editing drops
   * every arc/link that crossed the boundary (the other end isn't part of
   * this sub-net at all), so without this badge a place wired to the outside
   * world looks exactly like one that never was.
   */
  externalConnections?: string[];
}

interface PlaceNodeProps {
  data: PlaceNodeData;
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


function TokenDisplay({ tokens }: { tokens: number }) {
  if (tokens <= 0) return null;

  return (
    <span className="select-none text-base font-bold leading-none text-emerald-700 dark:text-emerald-300">
      {tokens}
    </span>
  );
}

export const PlaceNode = memo(({ data, selected }: PlaceNodeProps) => {
  const hasTokens = data.tokens > 0;
  const pulsing = data.pulsing ?? false;

  return (
    <div className="flex flex-col items-center">
      {/* Handles live inside the circle so top/left % is relative to its
          dimensions — this keeps connection points visually centred. */}
      <div
        className={cn(
          "relative flex h-14 w-14 items-center justify-center rounded-full border-[3px]",
          !pulsing && "transition-colors duration-200",
          selected
            ? "border-blue-500 shadow-md shadow-blue-200/60 dark:shadow-blue-900/60"
            : hasTokens
              ? "border-zinc-300 dark:border-zinc-200"
              : "border-zinc-200 dark:border-zinc-400",
          "bg-white dark:bg-zinc-900",
          pulsing && "petri-pulse-place",
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
        <div className="flex h-8 w-8 items-center justify-center">
          <TokenDisplay tokens={data.tokens} />
        </div>

        {data.fusionLabel && (
          <span
            title={data.fusionTitle}
            className={cn(
              "absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center",
              "rounded-full border-2 border-violet-500 bg-white text-[8px] font-bold",
              "text-violet-600 dark:bg-zinc-900 dark:text-violet-300",
            )}
          >
            {data.fusionLabel}
          </span>
        )}

        {data.externalConnections && data.externalConnections.length > 0 && (
          <span
            title={data.externalConnections.join(", ")}
            className={cn(
              "absolute -bottom-1.5 -left-1.5 flex h-4 w-4 items-center justify-center",
              "rounded-full border-2 border-sky-500 bg-white text-[8px] font-bold",
              "text-sky-600 dark:bg-zinc-900 dark:text-sky-300",
            )}
          >
            {data.externalConnections.length}
          </span>
        )}
      </div>

      <span className="mt-1.5 max-w-[80px] text-center text-[10px] font-medium leading-tight text-zinc-600 dark:text-zinc-400">
        {data.label}
      </span>
    </div>
  );
});

PlaceNode.displayName = "PlaceNode";
