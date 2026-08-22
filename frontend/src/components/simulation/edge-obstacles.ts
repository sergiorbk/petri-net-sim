import { Position, type Node as FlowNode } from "@xyflow/react";

/** Axis-aligned obstacle box in flow coordinates. */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Node types that occupy canvas area without being something an edge should
 * route around. An object frame is the *region its members live in* — treating
 * it as an obstacle would push every arc that legitimately enters the object
 * out and around the frame it belongs inside.
 */
const NON_OBSTACLE_TYPES: ReadonlySet<string> = new Set(["objectFrame"]);

/**
 * React Flow keeps a child node's `position` relative to its parent, so a node
 * inside an object frame reports frame-local coordinates. Walk the parent chain
 * to recover the absolute position the edge geometry is expressed in.
 */
function absolutePosition(
  node: FlowNode,
  byId: Map<string, FlowNode>,
): { x: number; y: number } {
  let { x, y } = node.position;
  const seen = new Set<string>([node.id]);
  let parentId = node.parentId;
  while (parentId && !seen.has(parentId)) {
    const parent = byId.get(parentId);
    if (!parent) break;
    x += parent.position.x;
    y += parent.position.y;
    seen.add(parentId);
    parentId = parent.parentId;
  }
  return { x, y };
}

/**
 * Bounding boxes an edge should avoid: every measured node except the edge's
 * own endpoints and the container types above, each grown by `pad` px of
 * clearance. Shared by SmartEdge and OrthogonalEdge so both route around the
 * same set of things.
 */
export function buildObstacleRects(
  nodes: FlowNode[],
  exclude: ReadonlySet<string>,
  pad: number,
): Rect[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const rects: Rect[] = [];
  for (const node of nodes) {
    if (exclude.has(node.id)) continue;
    if (node.type && NON_OBSTACLE_TYPES.has(node.type)) continue;
    const width = node.measured?.width;
    if (!width) continue;
    const { x, y } = absolutePosition(node, byId);
    rects.push({
      x: x - pad,
      y: y - pad,
      w: width + pad * 2,
      h: (node.measured?.height ?? 0) + pad * 2,
    });
  }
  return rects;
}

/**
 * The outgoing tangent vector (dx, dy) for a handle on a given side — the
 * direction the edge should leave (or arrive from) the boundary so it looks
 * like it grows from the element's center. Shared by every edge type that
 * needs to know which way "outward" is at an endpoint.
 */
export function tangentDir(position: Position): [number, number] {
  switch (position) {
    case Position.Right:  return [ 1,  0];
    case Position.Left:   return [-1,  0];
    case Position.Bottom: return [ 0,  1];
    case Position.Top:    return [ 0, -1];
  }
}

/**
 * A collapsed Petri-object frame's border port is a ~10px dot — about the
 * same size as an edge's own arrowhead marker, so an edge terminating exactly
 * on one reads as a single merged blob rather than an arrow pointing at a
 * dot. A plain place/transition doesn't need this: its handle already sits on
 * that shape's own boundary, so the arrowhead touches the edge of something
 * much bigger than itself and the two never visually compete.
 */
const PORT_ENDPOINT_GAP = 8;

/**
 * Pulls an edge endpoint back along its own approach direction when it lands
 * on a collapsed frame's port, leaving the port's dot visible next to the
 * arrowhead instead of underneath it. A no-op for any other node type.
 */
export function pullBackFromPort(
  point: { x: number; y: number },
  tangent: readonly [number, number],
  nodeId: string,
  nodes: FlowNode[],
): { x: number; y: number } {
  const node = nodes.find((n) => n.id === nodeId);
  if (node?.type !== "objectFrame") return point;
  return { x: point.x + tangent[0] * PORT_ENDPOINT_GAP, y: point.y + tangent[1] * PORT_ENDPOINT_GAP };
}
