import { memo } from "react";
import { BaseEdge, useNodes, type EdgeProps } from "@xyflow/react";
import { pullBackFromPort, tangentDir } from "./edge-obstacles";

export const StraightEdge = memo(
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
    const src = pullBackFromPort({ x: sourceX, y: sourceY }, tangentDir(sourcePosition), source, nodes);
    const tgt = pullBackFromPort({ x: targetX, y: targetY }, tangentDir(targetPosition), target, nodes);
    const labelX = (src.x + tgt.x) / 2;
    const labelY = (src.y + tgt.y) / 2;
    const edgePath = `M ${src.x} ${src.y} L ${tgt.x} ${tgt.y}`;

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

StraightEdge.displayName = "StraightEdge";
