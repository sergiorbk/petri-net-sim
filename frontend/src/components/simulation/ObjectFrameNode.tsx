import { memo, useMemo } from "react";
import { Handle, NodeResizer, Position } from "@xyflow/react";
import { Eye, EyeOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import type { FrameStyle } from "@/stores/editor-store";
import { FRAME_HEADER_H } from "@/lib/petri-geometry";

/** One border edge a collapsed frame's ports may sit on — never "top", which is the header. */
export type FramePortSide = "left" | "right" | "bottom";

/**
 * A connection point standing in for a hidden member's external connection
 * while its object frame is collapsed. Positioned on the frame's own border,
 * near where that member actually sits inside, so the connection's approximate
 * origin stays legible even with the member itself hidden.
 */
export interface ObjectFramePort {
  /** Handle id — also the edge's sourceHandle/targetHandle once redirected here. */
  id: string;
  type: "source" | "target";
  side: FramePortSide;
  /** Percentage offset along that side (0–100). */
  offset: number;
  /** The hidden member's own kind — place ports and transition ports look different. */
  kind: "place" | "transition";
  /** Name of the element on the other end of the connection. */
  counterpartLabel: string;
  /** The hidden member this port stands in for — lets a click/drop on the port resolve to a real connection endpoint. */
  elementId: string;
}

export interface ObjectFrameNodeData {
  label: string;
  priority: number;
  collapsed?: boolean;
  memberCount: number;
  ports: ObjectFramePort[];
  /** Boundary look, from the canvas-wide appearance setting. */
  frameStyle: FrameStyle;
  /** Frame size in flow units — the drawn boundary needs it before measurement. */
  width: number;
  height: number;
  /** True while the simulation is acting on one of this object's members. */
  active?: boolean;
  /**
   * True when this frame is only visible because its actual owner is
   * expanded — it can be opened and viewed but not resized from here, only
   * from its own canvas. False for a frame directly local to the current
   * net, which is managed as a unit (moved, resized, deleted) like any free
   * element.
   */
  locked?: boolean;
  onToggleCollapsed?: () => void;
  /** Opens this object on its own canvas. */
  onEdit?: () => void;
}

interface ObjectFrameNodeProps {
  data: ObjectFrameNodeData;
  selected?: boolean;
  width?: number;
  height?: number;
}

const SIDE_TO_POSITION: Record<FramePortSide, Position> = {
  left: Position.Left,
  right: Position.Right,
  bottom: Position.Bottom,
};

/** Offset along the side, same convention as PlaceNode/TransitionNode's own handleStyle. */
function framePortHandleStyle(side: FramePortSide, offset: number): React.CSSProperties {
  return side === "left" || side === "right" ? { top: `${offset}%` } : { left: `${offset}%` };
}

/**
 * A connection's line and arrowhead approach the port from the same outward
 * side the caption sits on, along the port's own centerline — so the caption
 * is nudged sideways, off that centerline, rather than just held back along
 * it. Held-back-only was tried first: it just relocated the overlap, since
 * the arrowhead is wide (not a point) and the pulled-back gap in EditorCanvas
 * (see pullBackFromPort) lands it exactly where the caption used to start.
 */
const LABEL_SIDESTEP_PX = 9;

function framePortLabelStyle(side: FramePortSide, offset: number): React.CSSProperties {
  switch (side) {
    case "left":
      return {
        right: "100%",
        top: `${offset}%`,
        transform: `translateY(calc(-50% - ${LABEL_SIDESTEP_PX}px))`,
        marginRight: 6,
      };
    case "right":
      return {
        left: "100%",
        top: `${offset}%`,
        transform: `translateY(calc(-50% - ${LABEL_SIDESTEP_PX}px))`,
        marginLeft: 6,
      };
    case "bottom":
      return {
        top: "100%",
        left: `${offset}%`,
        transform: `translateX(calc(-50% + ${LABEL_SIDESTEP_PX}px))`,
        marginTop: 5,
      };
  }
}

/**
 * Both port kinds are circles — the shape reads as "connector" rather than as
 * a net element. What tells them apart is the fill: a place port is hollow
 * like the place it stands for, a transition port is solid.
 */
function FramePort({ port }: { port: ObjectFramePort }) {
  const isPlace = port.kind === "place";
  return (
    <>
      <Handle
        id={port.id}
        type={port.type}
        position={SIDE_TO_POSITION[port.side]}
        // React Flow's own drag/click-to-connect machinery stays off here (the
        // app never wires onConnect and draws its own arcs entirely by hand,
        // via EditorCanvas's data-handleid hit-testing) — only the CSS pointer
        // events are forced back on, since that hit-testing needs the port's
        // DOM node to actually be reachable by elementFromPoint/e.target.
        isConnectableStart={false}
        isConnectableEnd={false}
        style={framePortHandleStyle(port.side, port.offset)}
        className={cn(
          "!z-10 !h-2.5 !w-2.5 !rounded-full !border-2 !pointer-events-auto",
          isPlace
            ? "!border-emerald-500 !bg-white dark:!border-emerald-400 dark:!bg-zinc-900"
            : "!border-amber-500 !bg-amber-500 dark:!border-amber-400 dark:!bg-amber-400",
        )}
      />
      <span
        className={cn(
          "pointer-events-none absolute z-10 whitespace-nowrap rounded px-1 py-px",
          "text-[9px] leading-none text-zinc-500 dark:text-zinc-400",
          "bg-zinc-50/85 dark:bg-zinc-950/85",
        )}
        style={framePortLabelStyle(port.side, port.offset)}
      >
        {port.counterpartLabel}
      </span>
    </>
  );
}

/** Peak deviation of the wavy boundary from its baseline, in px. */
const WAVE_AMPLITUDE = 4;
/** Target length of one half-wave; the real one is rounded to fit each side exactly. */
const WAVE_HALF_LENGTH = 18;

/**
 * One side of the wavy boundary, as quadratic segments alternating outward and
 * inward. Each side is divided into a whole number of half-waves so the wave
 * always starts and ends exactly on a corner, leaving no seam there.
 */
function wavySide(
  from: { x: number; y: number },
  to: { x: number; y: number },
  outward: { x: number; y: number },
): string {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy);
  const count = Math.max(2, Math.round(length / WAVE_HALF_LENGTH));
  const step = 1 / count;

  let d = "";
  for (let i = 0; i < count; i++) {
    const midT = (i + 0.5) * step;
    const endT = (i + 1) * step;
    const sign = i % 2 === 0 ? 1 : -1;
    // A quadratic peaks at half its control-point deviation, so the control
    // point is placed at twice the amplitude we actually want to see.
    const cx = from.x + dx * midT + outward.x * WAVE_AMPLITUDE * 2 * sign;
    const cy = from.y + dy * midT + outward.y * WAVE_AMPLITUDE * 2 * sign;
    const ex = from.x + dx * endT;
    const ey = from.y + dy * endT;
    d += ` Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`;
  }
  return d;
}

function wavyRectPath(width: number, height: number): string {
  // Inset by the amplitude so outward bulges stay inside the node's own box.
  const a = WAVE_AMPLITUDE;
  const x1 = Math.max(a, width - a);
  const y1 = Math.max(a, height - a);

  const tl = { x: a, y: a };
  const tr = { x: x1, y: a };
  const br = { x: x1, y: y1 };
  const bl = { x: a, y: y1 };

  return (
    `M ${a} ${a}` +
    wavySide(tl, tr, { x: 0, y: -1 }) +
    wavySide(tr, br, { x: 1, y: 0 }) +
    wavySide(br, bl, { x: 0, y: 1 }) +
    wavySide(bl, tl, { x: -1, y: 0 }) +
    " Z"
  );
}

/**
 * A visible boundary grouping a subset of places/transitions into one
 * Petri-object. Children are attached via React Flow's native parentId +
 * extent:"parent" (see EditorCanvas.buildGraph) — this component renders the
 * frame's own chrome: the dashed boundary, the header, and the border ports
 * that stand in for hidden members while it is collapsed.
 */
export const ObjectFrameNode = memo(({ data, selected, width, height }: ObjectFrameNodeProps) => {
  const { t } = useTranslation();
  const w = width ?? data.width;
  const h = height ?? data.height;

  const outlinePath = useMemo(
    () => (data.frameStyle === "wavy" ? wavyRectPath(w, h) : null),
    [data.frameStyle, w, h],
  );

  const strokeClass = selected
    ? "stroke-blue-500"
    : data.active
      ? "stroke-[#ff4d4d]"
      : "stroke-zinc-400 dark:stroke-zinc-500";
  const outlineClass = cn(strokeClass, data.active && "petri-pulse-frame");

  return (
    <>
      <NodeResizer
        isVisible={selected && !data.locked}
        minWidth={160}
        minHeight={100}
        lineClassName="!border-blue-400"
        handleClassName="!h-2 !w-2 !rounded-sm !border !border-blue-400 !bg-white"
      />
      <div
        className={cn(
          "relative flex h-full w-full flex-col rounded-lg",
          data.active ? "bg-red-500/5" : "bg-zinc-50/50 dark:bg-zinc-800/30",
        )}
        style={{ width: w, height: h }}
      >
        {/* The boundary is drawn rather than CSS-bordered so the same component
            can render either a straight dashed rectangle or a wavy one. */}
        <svg className="pointer-events-none absolute inset-0" width={w} height={h} aria-hidden>
          {outlinePath ? (
            <path
              d={outlinePath}
              fill="none"
              strokeWidth={2}
              strokeDasharray="7 5"
              strokeLinejoin="round"
              className={outlineClass}
            />
          ) : (
            <rect
              x={1}
              y={1}
              width={Math.max(0, w - 2)}
              height={Math.max(0, h - 2)}
              rx={8}
              fill="none"
              strokeWidth={2}
              strokeDasharray="7 5"
              className={outlineClass}
            />
          )}
        </svg>

        <div
          className={cn(
            "relative z-[1] mx-2 mt-1 flex cursor-grab items-center",
            "justify-between gap-2 rounded px-1.5",
          )}
          style={{ height: FRAME_HEADER_H - 4 }}
        >
          <span className="truncate text-xs font-semibold text-zinc-700 dark:text-zinc-200">
            {data.label}
          </span>
          <div className="flex items-center gap-1.5">
            {data.priority !== 0 && (
              <span className="rounded bg-zinc-200 px-1 text-[10px] font-medium text-zinc-600 dark:bg-zinc-600 dark:text-zinc-200">
                P{data.priority}
              </span>
            )}
            <button
              type="button"
              className="nodrag rounded p-0.5 text-zinc-500 hover:bg-zinc-200 dark:text-zinc-400 dark:hover:bg-zinc-600"
              onClick={(e) => {
                e.stopPropagation();
                data.onToggleCollapsed?.();
              }}
              title={data.collapsed ? t("objectFrame.expand") : t("objectFrame.collapse")}
            >
              {data.collapsed ? <Eye size={12} /> : <EyeOff size={12} />}
            </button>
          </div>
        </div>

        {data.collapsed ? (
          <div className="flex flex-1 items-center justify-center text-[11px] text-zinc-500 dark:text-zinc-400">
            {t("objectFrame.memberCount", { count: data.memberCount })}
          </div>
        ) : (
          data.memberCount === 0 && (
            // A freshly drawn object is empty; say what to do with it rather
            // than leaving an unexplained box on the canvas.
            <div className="flex flex-1 flex-col items-center justify-center gap-1.5 px-3 text-center">
              <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
                {t("objectFrame.emptyHint")}
              </span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  data.onEdit?.();
                }}
                className={cn(
                  "nodrag rounded border border-zinc-300 px-2 py-1 text-[11px] font-medium",
                  "text-zinc-600 hover:bg-zinc-100",
                  "dark:border-zinc-600 dark:text-zinc-300 dark:hover:bg-zinc-700",
                )}
              >
                {t("objectFrame.startEditing")}
              </button>
            </div>
          )
        )}
        {data.collapsed && data.ports.map((port) => <FramePort key={port.id} port={port} />)}
      </div>
    </>
  );
});

ObjectFrameNode.displayName = "ObjectFrameNode";
