import { memo } from "react";
import { BaseEdge, getStraightPath, type EdgeProps } from "@xyflow/react";

/** Radius of the dot that anchors the non-master end of the tie. */
const END_DOT_R = 3.5;
/** Length of each barb of the open arrowhead at the master end. */
const ARROW_LEN = 9;
/** Half-angle of the open arrowhead, in radians. */
const ARROW_SPREAD = 0.46;

/**
 * A place-fusion tie: the two places it joins are the same place, so it is not
 * a flow and must not look like one. Following the desktop's UML-dependency
 * convention it is a dashed line with an OPEN arrowhead at the master end,
 * the place whose token count the join adopted (the side the gesture started
 * from, which addObjectLink records as the link's source). The other end gets
 * a plain dot: nothing travels along the tie, so only the master needs
 * pointing out.
 */
export const FusionEdge = memo(
  ({ sourceX, sourceY, targetX, targetY, style, selected }: EdgeProps) => {
    const [path] = getStraightPath({ sourceX, sourceY, targetX, targetY });
    const color = (style?.stroke as string | undefined) ?? "#a855f7";

    // Unit vector pointing along the tie into the master (source) end.
    const dx = sourceX - targetX;
    const dy = sourceY - targetY;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    const angle = Math.atan2(uy, ux);
    const barb = (spread: number) => ({
      x: sourceX - ARROW_LEN * Math.cos(angle + spread),
      y: sourceY - ARROW_LEN * Math.sin(angle + spread),
    });
    const left = barb(ARROW_SPREAD);
    const right = barb(-ARROW_SPREAD);

    return (
      <>
        <BaseEdge path={path} style={style} />
        <path
          d={`M ${left.x} ${left.y} L ${sourceX} ${sourceY} L ${right.x} ${right.y}`}
          fill="none"
          stroke={color}
          strokeWidth={selected ? 2.5 : 1.5}
          strokeLinecap="round"
        />
        <circle
          cx={targetX}
          cy={targetY}
          r={selected ? END_DOT_R + 1 : END_DOT_R}
          fill={color}
        />
      </>
    );
  },
);

FusionEdge.displayName = "FusionEdge";
