import { memo } from "react";
import { BaseEdge, getBezierPath, useNodes, type Position, type EdgeProps } from "@xyflow/react";
import { buildObstacleRects, pullBackFromPort, tangentDir, type Rect } from "./edge-obstacles";

/** Extra clearance (px) added around each node's bounding box for collision tests. */
const NODE_PAD = 10;
/** Clearance (px) beyond the obstacle zone when computing the bypass route. */
const BYPASS_GAP = 28;

/**
 * Parametric segment–AABB intersection (slab method).
 * Excludes exact endpoints (t≈0, t≈1) so the edge touching its own node
 * does not count as a collision.
 */
function segmentHitsRect(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  r: Rect,
): boolean {
  let tMin = 0;
  let tMax = 1;
  const dx = x2 - x1;
  const dy = y2 - y1;

  if (Math.abs(dx) < 1e-9) {
    if (x1 < r.x || x1 > r.x + r.w) return false;
  } else {
    const ta = (r.x - x1) / dx;
    const tb = (r.x + r.w - x1) / dx;
    tMin = Math.max(tMin, Math.min(ta, tb));
    tMax = Math.min(tMax, Math.max(ta, tb));
    if (tMin > tMax) return false;
  }

  if (Math.abs(dy) < 1e-9) {
    if (y1 < r.y || y1 > r.y + r.h) return false;
  } else {
    const ta = (r.y - y1) / dy;
    const tb = (r.y + r.h - y1) / dy;
    tMin = Math.max(tMin, Math.min(ta, tb));
    tMax = Math.min(tMax, Math.max(ta, tb));
    if (tMin > tMax) return false;
  }

  return tMax > 1e-9 && tMin < 1 - 1e-9;
}

/** How far the initial tangent arm extends from a handle (px). */
const TANGENT_ARM = 40;

/**
 * Build a cubic Bézier bypass path that arcs above or below the union of all
 * blocking rectangles while respecting the exit/entry direction of each handle.
 * Returns the SVG path string and the curve midpoint (t=0.5) for label placement.
 */
function buildBypassPath(
  sx: number,
  sy: number,
  srcPos: Position,
  tx: number,
  ty: number,
  tgtPos: Position,
  blocking: Rect[],
): [path: string, labelX: number, labelY: number] {
  const top    = Math.min(...blocking.map((r) => r.y)) - BYPASS_GAP;
  const bottom = Math.max(...blocking.map((r) => r.y + r.h)) + BYPASS_GAP;
  const midY   = (sy + ty) / 2;

  // Choose the bypass side that requires the least vertical deviation.
  const bypassY = Math.abs(midY - top) <= Math.abs(midY - bottom) ? top : bottom;

  const [sdx, sdy] = tangentDir(srcPos);
  const [tdx, tdy] = tangentDir(tgtPos);

  // First control point: leave source in the handle's natural direction,
  // then blend toward the bypass lane.
  const cp1x = sx + sdx * TANGENT_ARM;
  const cp1y = Math.abs(sdy) > 0 ? sy + sdy * TANGENT_ARM : bypassY;

  // Second control point: arrive at target from the handle's natural direction,
  // then blend from the bypass lane.
  const cp2x = tx + tdx * TANGENT_ARM;
  const cp2y = Math.abs(tdy) > 0 ? ty + tdy * TANGENT_ARM : bypassY;

  // Bézier midpoint at t=0.5:
  //   B(0.5) = 0.125·P0 + 0.375·P1 + 0.375·P2 + 0.125·P3
  const lx = 0.125 * sx + 0.375 * cp1x + 0.375 * cp2x + 0.125 * tx;
  const ly = 0.125 * sy + 0.375 * cp1y + 0.375 * cp2y + 0.125 * ty;

  return [
    `M ${sx} ${sy} C ${cp1x} ${cp1y} ${cp2x} ${cp2y} ${tx} ${ty}`,
    lx,
    ly,
  ];
}

/**
 * A single-direction edge that:
 *  - draws a straight line when the direct path does not intersect any node,
 *  - otherwise curves above/below the blocking nodes.
 *
 * Obstacle data comes from the live React Flow node store (useNodes), so the
 * routing updates automatically when nodes are dragged.
 */
export const SmartEdge = memo(
  ({
    id,
    source,
    target,
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    markerStart,
    markerEnd,
    style,
    label,
    labelStyle,
    interactionWidth,
  }: EdgeProps) => {
    const nodes = useNodes();

    // A port endpoint pulls back from its raw handle position (see
    // pullBackFromPort) so the arrowhead doesn't visually swallow the port's
    // own dot; a plain place/transition endpoint is unaffected.
    const src = pullBackFromPort({ x: sourceX, y: sourceY }, tangentDir(sourcePosition), source, nodes);
    const tgt = pullBackFromPort({ x: targetX, y: targetY }, tangentDir(targetPosition), target, nodes);

    // Build obstacle rectangles for every node except the edge's own endpoints.
    const obstacles: Rect[] = buildObstacleRects(
      nodes,
      new Set([source, target]),
      NODE_PAD,
    );

    const blocking = obstacles.filter((r) =>
      segmentHitsRect(src.x, src.y, tgt.x, tgt.y, r),
    );

    let edgePath: string;
    let labelX: number;
    let labelY: number;

    if (blocking.length === 0) {
      // getBezierPath uses sourcePosition/targetPosition to build control points
      // that make the edge exit/enter perpendicular to the node side — as if
      // the arc grows out of the element's center.
      [edgePath, labelX, labelY] = getBezierPath({
        sourceX: src.x,
        sourceY: src.y,
        sourcePosition,
        targetX: tgt.x,
        targetY: tgt.y,
        targetPosition,
      });
    } else {
      [edgePath, labelX, labelY] = buildBypassPath(
        src.x,
        src.y,
        sourcePosition,
        tgt.x,
        tgt.y,
        targetPosition,
        blocking,
      );
    }

    return (
      <BaseEdge
        id={id}
        path={edgePath}
        markerStart={markerStart}
        markerEnd={markerEnd}
        style={style}
        label={label}
        labelX={labelX}
        labelY={labelY}
        labelStyle={labelStyle}
        interactionWidth={interactionWidth}
      />
    );
  },
);

SmartEdge.displayName = "SmartEdge";
