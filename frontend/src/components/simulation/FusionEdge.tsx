import { memo } from "react";
import { BaseEdge, type EdgeProps } from "@xyflow/react";

/** Stroke width of each of the two rails. */
const STROKE_WIDTH = 1.4;
const STROKE_WIDTH_SELECTED = 2.2;

/** Distance between the two rails, measured centre to centre. */
const RAIL_GAP = 5;

/** Length of each arm of the open arrowhead. */
const ARROW_ARM = 18;
/** Angle between each arm and the tie, in radians (30 degrees). */
const ARROW_ANGLE = Math.PI / 6;

type Point = { x: number; y: number };

/**
 * The geometry of a fusion tie drawn from `from` (the master, the place the
 * marking lives in) to `to` (the copy that repeats it): two parallel rails
 * that run into the tip of an open arrowhead at the copy end.
 *
 * The rails stop where they meet the arrowhead's arms, so the two lines
 * close into the tip instead of poking through it.
 */
export function fusionTieGeometry(from: Point, to: Point, railGap = RAIL_GAP) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy);
  // A zero-length tie has no direction; any will do, nothing visible depends on it.
  const ux = length > 0 ? dx / length : 1;
  const uy = length > 0 ? dy / length : 0;
  const nx = -uy;
  const ny = ux;
  const half = railGap / 2;
  const back = Math.min(half / Math.tan(ARROW_ANGLE), length);
  const endX = to.x - ux * back;
  const endY = to.y - uy * back;
  const rail = (side: number) =>
    `M ${from.x + nx * half * side} ${from.y + ny * half * side} ` +
    `L ${endX + nx * half * side} ${endY + ny * half * side}`;

  const cos = Math.cos(ARROW_ANGLE);
  const sin = Math.sin(ARROW_ANGLE);
  const arm = (side: number) => ({
    x: to.x - ARROW_ARM * (ux * cos - side * nx * sin),
    y: to.y - ARROW_ARM * (uy * cos - side * ny * sin),
  });
  const a = arm(1);
  const b = arm(-1);

  return {
    rails: `${rail(1)} ${rail(-1)}`,
    arrow: `M ${a.x} ${a.y} L ${to.x} ${to.y} L ${b.x} ${b.y}`,
  };
}

/**
 * A place-fusion tie: the two places it joins are the same place, so it is
 * not a flow and must not look like one. ObjectLink stores a placeFusion
 * copy -> master (see its doc comment), and React Flow's own edge
 * source/target mirror link.sourceId/targetId directly, so the master is the
 * TARGET end here, not the source.
 *
 * Drawn as a double line with an open arrowhead at the copy end, pointing
 * from the master to the copy: the copy's marking follows from what happens
 * in the master, which is the assignment copy := master the simulation makes.
 * A double line is a difference of kind from every arc on the canvas,
 * including the dashed informational ones, so it stays told apart once the
 * canvas is zoomed out, printed, or screenshotted.
 *
 * `data.lit` means a running step is passing through the place this tie
 * declares, and draws it as heavily as a selected one. It is carried in data
 * rather than through React Flow's own `selected` flag on purpose: that flag
 * feeds the canvas's selection change handler, so borrowing it for an
 * animation would leave the tie sitting in the user's selection once the run
 * had moved on.
 */
export const FusionEdge = memo(
  ({ sourceX, sourceY, targetX, targetY, style, selected, data }: EdgeProps) => {
    const { rails, arrow } = fusionTieGeometry(
      { x: targetX, y: targetY },
      { x: sourceX, y: sourceY },
    );
    const color = (style?.stroke as string | undefined) ?? "#a855f7";
    const emphasised = selected === true || (data as { lit?: boolean } | undefined)?.lit === true;
    const strokeWidth = emphasised ? STROKE_WIDTH_SELECTED : STROKE_WIDTH;

    return (
      <>
        <BaseEdge
          path={rails}
          style={{
            ...style,
            stroke: color,
            strokeWidth,
            strokeLinecap: "butt",
          }}
        />
        <path
          className="react-flow__fusion-arrow"
          d={arrow}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeLinejoin="miter"
        />
      </>
    );
  },
);

FusionEdge.displayName = "FusionEdge";
