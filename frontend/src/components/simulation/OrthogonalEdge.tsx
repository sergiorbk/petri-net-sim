import { memo } from "react";
import { BaseEdge, useNodes, Position, type EdgeProps } from "@xyflow/react";
import { buildObstacleRects, pullBackFromPort, tangentDir, type Rect } from "./edge-obstacles";

const NODE_PAD = 10;
const CORNER_OFFSET = 20;

function isHorizontal(pos: Position): boolean {
  return pos === Position.Left || pos === Position.Right;
}

function buildOrthogonalPath(
  sx: number,
  sy: number,
  srcPos: Position,
  tx: number,
  ty: number,
  tgtPos: Position,
  _obstacles: Rect[],
  midOffset: number,
): [path: string, labelX: number, labelY: number] {
  const [sdx, sdy] = tangentDir(srcPos);
  const [tdx, tdy] = tangentDir(tgtPos);

  const srcH = isHorizontal(srcPos);
  const tgtH = isHorizontal(tgtPos);

  const points: [number, number][] = [[sx, sy]];

  if (srcH && tgtH) {
    const midX = (sx + sdx * CORNER_OFFSET + tx + tdx * CORNER_OFFSET) / 2 + midOffset;
    points.push([midX, sy]);
    points.push([midX, ty]);
  } else if (!srcH && !tgtH) {
    const midY = (sy + sdy * CORNER_OFFSET + ty + tdy * CORNER_OFFSET) / 2 + midOffset;
    points.push([sx, midY]);
    points.push([tx, midY]);
  } else if (srcH && !tgtH) {
    const ex = tx + tdx * CORNER_OFFSET;
    if ((sdx > 0 && ex > sx) || (sdx < 0 && ex < sx)) {
      points.push([ex, sy]);
      points.push([ex, ty]);
    } else {
      const midX = sx + sdx * CORNER_OFFSET;
      const midY = (sy + ty) / 2 + midOffset;
      points.push([midX, sy]);
      points.push([midX, midY]);
      points.push([tx, midY]);
    }
  } else {
    const ey = ty + tdy * CORNER_OFFSET;
    if ((sdy > 0 && ey > sy) || (sdy < 0 && ey < sy)) {
      points.push([sx, ey]);
      points.push([tx, ey]);
    } else {
      const midY = sy + sdy * CORNER_OFFSET;
      const midX = (sx + tx) / 2 + midOffset;
      points.push([sx, midY]);
      points.push([midX, midY]);
      points.push([midX, ty]);
    }
  }

  points.push([tx, ty]);

  const segments = points.map(([x, y], i) =>
    i === 0 ? `M ${x} ${y}` : `L ${x} ${y}`,
  );

  const mid = Math.floor(points.length / 2);
  const p0 = points[mid - 1] ?? points[0];
  const p1 = points[mid];
  const lx = (p0[0] + p1[0]) / 2;
  const ly = (p0[1] + p1[1]) / 2;

  return [segments.join(" "), lx, ly];
}

export const OrthogonalEdge = memo(
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
    data,
  }: EdgeProps) => {
    const nodes = useNodes();
    const midOffset = (data?.midOffset as number | undefined) ?? 0;

    const src = pullBackFromPort({ x: sourceX, y: sourceY }, tangentDir(sourcePosition), source, nodes);
    const tgt = pullBackFromPort({ x: targetX, y: targetY }, tangentDir(targetPosition), target, nodes);

    const obstacles: Rect[] = buildObstacleRects(
      nodes,
      new Set([source, target]),
      NODE_PAD,
    );

    const [edgePath, labelX, labelY] = buildOrthogonalPath(
      src.x,
      src.y,
      sourcePosition,
      tgt.x,
      tgt.y,
      targetPosition,
      obstacles,
      midOffset,
    );

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

OrthogonalEdge.displayName = "OrthogonalEdge";
