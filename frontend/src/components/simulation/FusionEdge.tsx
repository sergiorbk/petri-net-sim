import { memo } from "react";
import { BaseEdge, getStraightPath, type EdgeProps } from "@xyflow/react";

/** Radius of the filled node marking the master (target) end. */
const MASTER_NODE_R = 4;
const MASTER_NODE_R_SELECTED = 5;

/** Stroke width of the tie itself. */
const STROKE_WIDTH = 1.4;
const STROKE_WIDTH_SELECTED = 2.2;

/**
 * Dash, gap, dot, gap. Matches the desktop's GraphPlaceFusion.drawBetweenPorts
 * pattern of {9, 4, 2, 4}. An informational arc (an inhibitor arc's "4 3", say)
 * is an even dash; a fusion tie needs a pattern of a different KIND, not just
 * a different length, so the two stay told apart once the canvas is zoomed
 * out, printed, or screenshotted, where a difference of degree does not
 * survive.
 */
const DASH_DOT = "9 4 2 4";

/**
 * A place-fusion tie: the two places it joins are the same place, so it is
 * not a flow and must not look like one. ObjectLink stores a placeFusion
 * copy -> master (see its doc comment), and React Flow's own edge
 * source/target mirror link.sourceId/targetId directly, so the master is the
 * TARGET end here, not the source.
 *
 * No arrowhead at either end: an arrowhead promises a flow, and nothing
 * flows along a reference link, the target simply repeats the source.
 * Direction is still legible because a filled node marks the master end
 * only, so with one master repeated by several copies those nodes coincide
 * and a fan reads as one origin rather than as several unrelated ties.
 */
export const FusionEdge = memo(
  ({ sourceX, sourceY, targetX, targetY, style, selected }: EdgeProps) => {
    const [path] = getStraightPath({ sourceX, sourceY, targetX, targetY });
    const color = (style?.stroke as string | undefined) ?? "#a855f7";

    return (
      <>
        <BaseEdge
          path={path}
          style={{
            ...style,
            stroke: color,
            strokeWidth: selected ? STROKE_WIDTH_SELECTED : STROKE_WIDTH,
            strokeDasharray: DASH_DOT,
            strokeLinecap: "round",
          }}
        />
        <circle
          cx={targetX}
          cy={targetY}
          r={selected ? MASTER_NODE_R_SELECTED : MASTER_NODE_R}
          fill={color}
        />
      </>
    );
  },
);

FusionEdge.displayName = "FusionEdge";
