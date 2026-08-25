import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ReactFlow,
  Background,
  Controls,
  ConnectionMode,
  applyNodeChanges,
  type Edge as FlowEdge,
  type EdgeChange,
  type Node as FlowNode,
  type NodeChange,
  type NodeMouseHandler,
  type OnSelectionChangeParams,
  MarkerType,
  useReactFlow,
  ReactFlowProvider,
  type ReactFlowInstance,
} from "@xyflow/react";

import { PlaceNode, type PlaceNodeData, type HandleSide, type ComputedHandle } from "@/components/simulation/PlaceNode";
import { TransitionNode, type TransitionNodeData } from "@/components/simulation/TransitionNode";
import {
  ObjectFrameNode,
  type ObjectFrameNodeData,
  type ObjectFramePort,
  type FramePortSide,
} from "@/components/simulation/ObjectFrameNode";
import { SmartEdge } from "@/components/simulation/SmartEdge";
import { OrthogonalEdge } from "@/components/simulation/OrthogonalEdge";
import { StraightEdge } from "@/components/simulation/StraightEdge";
import { FusionEdge } from "@/components/simulation/FusionEdge";
import type {
  ArcType,
  ObjectLink,
  PetriNetData,
  PetriPlace,
  PetriTransition,
  SimulationSnapshot,
} from "@/types/petri";
import {
  useEditorStore,
  type EdgeStyle,
  type EditorTool,
  type ElementRef,
  type FrameStyle,
} from "@/stores/editor-store";
import { useSimulationStore } from "@/stores/simulation-store";
import { usePetriObjectStore } from "@/stores/petri-object-store";
import { useAuthStore } from "@/stores/auth-store";
import { instantiateTemplate } from "@/lib/petri-object-instantiate";
import type { PetriObjectTemplate } from "@/lib/petri-objects-client";
import { getDraggingTemplate } from "@/lib/object-drag-state";
import { parsePnml, summarizeImportWarnings } from "@/lib/pnml-import";
import {
  cloneElements,
  connectorOf,
  frameAtPoint,
  fusionGroupsByPlace,
  getLinks,
  getObjects,
  objectsParentFirst,
  ownerOf,
  rejectionForFusion,
  resolveFusionMarking,
  resolveObjectBand,
} from "@/lib/petri-object-model";
import { isComposedNet } from "@/lib/petri-composed";
import { saveCanvasObjectToLibrary } from "@/lib/petri-object-library";
import { useCanvasTabsStore } from "@/stores/canvas-tabs-store";
import { NameDialog } from "@/components/common/NameDialog";
import {
  FRAME_HEADER_H,
  FRAME_MIN_H,
  FRAME_MIN_W,
  PLACE_H,
  PLACE_W,
  TRANS_H,
  TRANS_W,
} from "@/lib/petri-geometry";
import { toast } from "@/stores/toast-store";
import { TokenAnimationOverlay } from "./TokenAnimationOverlay";
import { CanvasContextMenu, type CanvasContextMenuItem } from "./CanvasContextMenu";

// Point-in-polygon test using ray casting algorithm
function pointInPolygon(point: { x: number; y: number }, polygon: Array<{ x: number; y: number }>): boolean {
  if (polygon.length < 3) return false;

  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x;
    const yi = polygon[i].y;
    const xj = polygon[j].x;
    const yj = polygon[j].y;

    const intersect = (yi > point.y) !== (yj > point.y) && point.x < ((xj - xi) * (point.y - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }

  return inside;
}

const MIN_HANDLE_GAP_PX = 14;

// Fixed handle ids every place/transition node always carries, used only by
// ObjectLink edges (which have no per-arc routing/handles of their own).
const LINK_SOURCE_HANDLE = "__link_src";
const LINK_TARGET_HANDLE = "__link_tgt";

// Exported so any other canvas rendering the same net data (e.g. the chat
// workbench's read-only preview) uses the exact same node/edge components
// and graph-building logic instead of a second, drifting implementation.
export const NODE_TYPES = {
  place: PlaceNode,
  transition: TransitionNode,
  objectFrame: ObjectFrameNode,
} as const;

export const EDGE_TYPES = {
  smart: SmartEdge,
  orthogonal: OrthogonalEdge,
  straight: StraightEdge,
  fusion: FusionEdge,
} as const;

function spreadOffsets(count: number, sideLengthPx: number): number[] {
  if (count === 0) return [];
  if (count === 1) return [50];
  const minGapPct = (MIN_HANDLE_GAP_PX / sideLengthPx) * 100;
  const naturalGapPct = 100 / (count + 1);
  const gap = Math.max(naturalGapPct, minGapPct);
  const totalSpan = gap * (count - 1);
  const start = Math.max(5, 50 - totalSpan / 2);
  return Array.from({ length: count }, (_, i) =>
    Math.min(95, start + i * gap),
  );
}

function pickSides(
  sx: number,
  sy: number,
  tx: number,
  ty: number,
): { sourceSide: HandleSide; targetSide: HandleSide } {
  const dx = tx - sx;
  const dy = ty - sy;
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx >= 0
      ? { sourceSide: "right", targetSide: "left" }
      : { sourceSide: "left", targetSide: "right" };
  }
  return dy >= 0
    ? { sourceSide: "bottom", targetSide: "top" }
    : { sourceSide: "top", targetSide: "bottom" };
}

function centerOf(net: PetriNetData, id: string): { x: number; y: number } | null {
  const p = net.places.find((pl) => pl.id === id);
  if (p) return { x: p.graphics.x + PLACE_W / 2, y: p.graphics.y + PLACE_H / 2 };
  const t = net.transitions.find((tr) => tr.id === id);
  if (t) return { x: t.graphics.x + TRANS_W / 2, y: t.graphics.y + TRANS_H / 2 };
  return null;
}

function elementName(net: PetriNetData, id: string): string {
  return (
    net.places.find((p) => p.id === id)?.name ??
    net.transitions.find((t) => t.id === id)?.name ??
    id
  );
}

function elementKind(net: PetriNetData, id: string): "place" | "transition" | null {
  if (net.places.some((p) => p.id === id)) return "place";
  if (net.transitions.some((t) => t.id === id)) return "transition";
  return null;
}

/** Looks up one border port on an already-built objectFrame FlowNode, by its handle id. */
function findFramePort(nodesList: FlowNode[], frameId: string, handleId: string): ObjectFramePort | null {
  const frameNode = nodesList.find((n) => n.id === frameId && n.type === "objectFrame");
  if (!frameNode) return null;
  const ports = (frameNode.data as unknown as ObjectFrameNodeData).ports;
  return ports.find((p) => p.id === handleId) ?? null;
}

/**
 * Resolves what a mousedown/mouseup landed on, for the drag-to-arc gesture.
 * React Flow stamps every node's own id as `data-id` on its wrapper, and every
 * Handle (including a collapsed frame's border ports) with both `data-nodeid`
 * (its owning node) and `data-handleid` (its own id) — checking handleid first
 * matters because a Handle's *own* `data-id` is a different, composite string,
 * not a real element id. A hit on a frame's port resolves through to the real
 * hidden place/transition it stands for, so the rest of the gesture (preview
 * line, resolveConnection) never needs to know the frame was involved at all.
 */
function resolveArcHit(
  targetEl: HTMLElement | null,
  containerEl: HTMLElement | null,
  net: PetriNetData,
  nodesList: FlowNode[],
): { id: string; kind: "place" | "transition" } | null {
  const handleEl = targetEl?.closest<HTMLElement>("[data-handleid]") ?? null;
  if (handleEl?.dataset.nodeid && handleEl.dataset.handleid) {
    const ownerId = handleEl.dataset.nodeid;
    if (net.places.some((p) => p.id === ownerId)) return { id: ownerId, kind: "place" };
    if (net.transitions.some((t) => t.id === ownerId)) return { id: ownerId, kind: "transition" };
    const port = findFramePort(nodesList, ownerId, handleEl.dataset.handleid);
    return port ? { id: port.elementId, kind: port.kind } : null;
  }
  let el = targetEl;
  while (el && el !== containerEl) {
    if (el.dataset.id) {
      const nodeId = el.dataset.id;
      const kind: "place" | "transition" = net.places.some((p) => p.id === nodeId) ? "place" : "transition";
      return { id: nodeId, kind };
    }
    el = el.parentElement;
  }
  return null;
}

function clampPct(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

/** Left/right ports stay clear of the header — this is roughly its height as a % guard. */
const FRAME_PORT_HEADER_GUARD_PCT = 15;

/**
 * Anything drawn between two net elements: a regular arc or a cross-object
 * link. Ports and edge redirection treat both the same way, so that an arc
 * reaching into an object keeps working once that object is collapsed.
 */
interface BoundaryConnection {
  id: string;
  sourceId: string;
  targetId: string;
}

function connectionsOf(net: PetriNetData): BoundaryConnection[] {
  return [
    ...net.arcs.map((a) => ({ id: a.id, sourceId: a.source_id, targetId: a.target_id })),
    ...getLinks(net).map((l) => ({ id: l.id, sourceId: l.sourceId, targetId: l.targetId })),
  ];
}

/**
 * A directed flow from a place to a transition or back, as the canvas draws
 * it. Regular arcs and directional cross-object links are both this and are
 * rendered identically: a link differs from an arc in the wire format (it is a
 * net-level declaration — see types/petri.ts), not in what it means on screen,
 * so it gets the same routing, the same look and the same firing animation.
 */
interface FlowConnection {
  id: string;
  source_id: string;
  target_id: string;
  weight: number;
  arc_type: ArcType;
}

/** Place fusion is an identity between two places, not a flow — it has no arc form. */
function linkAsFlowConnection(link: ObjectLink): FlowConnection | null {
  if (link.type === "placeFusion") return null;
  return {
    id: link.id,
    source_id: link.sourceId,
    target_id: link.targetId,
    weight: link.quantity,
    // An informational link tests the marking without consuming it, which is
    // exactly what a READ arc does — so it reads as one.
    arc_type: link.informational ? "READ" : "NORMAL",
  };
}

function flowConnectionsOf(net: PetriNetData): FlowConnection[] {
  return [
    ...net.arcs,
    ...getLinks(net)
      .map(linkAsFlowConnection)
      .filter((c): c is FlowConnection => c !== null),
  ];
}

/** True when both ends sit inside the same collapsed frame — nothing to show. */
function isInternalToCollapsedFrame(
  net: PetriNetData,
  hiddenIds: Set<string>,
  conn: BoundaryConnection,
): boolean {
  if (!hiddenIds.has(conn.sourceId) || !hiddenIds.has(conn.targetId)) return false;
  return ownerOf(net, conn.sourceId) === ownerOf(net, conn.targetId);
}

type PortCandidate = ObjectFramePort & { frameId: string; naturalOffset: number };

/**
 * One port on a frame's border, placed on the side nearest the member it
 * stands for — never the top edge, which is the header.
 */
function framePortCandidate(
  net: PetriNetData,
  frame: NonNullable<PetriNetData["objects"]>[number],
  elementId: string,
  type: "source" | "target",
  id: string,
  label: string,
): PortCandidate | null {
  const kind = elementKind(net, elementId);
  if (!kind) return null;

  const isPlace = kind === "place";
  const element = isPlace
    ? net.places.find((p) => p.id === elementId)
    : net.transitions.find((t) => t.id === elementId);
  if (!element) return null;

  const localX = element.graphics.x + (isPlace ? PLACE_W : TRANS_W) / 2 - frame.graphics.x;
  const localY = element.graphics.y + (isPlace ? PLACE_H : TRANS_H) / 2 - frame.graphics.y;

  const distLeft = localX;
  const distRight = frame.graphics.width - localX;
  const distBottom = frame.graphics.height - localY;
  const minDist = Math.min(distLeft, distRight, distBottom);
  const side: FramePortSide =
    minDist === distBottom ? "bottom" : minDist === distLeft ? "left" : "right";

  const naturalOffset =
    side === "bottom"
      ? clampPct((localX / frame.graphics.width) * 100, 5, 95)
      : clampPct((localY / frame.graphics.height) * 100, FRAME_PORT_HEADER_GUARD_PCT, 95);

  return {
    id,
    type,
    side,
    offset: naturalOffset,
    kind,
    counterpartLabel: label,
    elementId,
    frameId: frame.id,
    naturalOffset,
  };
}

/**
 * Border ports for a collapsed frame (see ObjectFrameNode.tsx). A port stands
 * for one member's connection point, and a collapsed object shows its whole
 * interface, not only the parts of it that happen to be wired up:
 *
 * - every connection crossing the boundary gets a port, labelled with the
 *   element on the far end;
 * - so does every member the object leaves open — one nothing inside feeds
 *   (an input) or nothing inside consumes from (an output) — labelled with
 *   its own name.
 *
 * That second rule is what makes a collapsed object still show where it can be
 * connected when nothing is attached to it yet.
 */
function computeFramePorts(
  net: PetriNetData,
  objects: ReturnType<typeof getObjects>,
  hiddenIds: Set<string>,
  connections: BoundaryConnection[],
): Map<string, ObjectFramePort[]> {
  const frameById = new Map(objects.map((o) => [o.id, o]));
  const candidates: PortCandidate[] = [];
  const covered = new Set<string>();

  for (const link of connections) {
    if (isInternalToCollapsedFrame(net, hiddenIds, link)) continue;
    for (const end of ["source", "target"] as const) {
      const elementId = end === "source" ? link.sourceId : link.targetId;
      if (!hiddenIds.has(elementId)) continue;
      const frameId = ownerOf(net, elementId);
      const frame = frameId ? frameById.get(frameId) : undefined;
      if (!frame) continue;

      const counterpartId = end === "source" ? link.targetId : link.sourceId;
      const candidate = framePortCandidate(
        net,
        frame,
        elementId,
        end,
        `port-${end}-${link.id}`,
        elementName(net, counterpartId),
      );
      if (!candidate) continue;
      candidates.push(candidate);
      covered.add(`${elementId}:${end}`);
    }
  }

  // Which members the object wires up internally, in one pass over the arcs —
  // asking per element would rescan every arc for every member.
  const ownerById = new Map<string, string | undefined>();
  for (const element of [...net.places, ...net.transitions]) {
    ownerById.set(element.id, element.objectId);
  }
  const fedFromInside = new Set<string>();
  const drainedInside = new Set<string>();
  for (const arc of net.arcs) {
    const sourceOwner = ownerById.get(arc.source_id);
    if (sourceOwner === undefined || sourceOwner !== ownerById.get(arc.target_id)) continue;
    drainedInside.add(arc.source_id);
    fedFromInside.add(arc.target_id);
  }

  // Members left open by the object itself: nothing inside produces into them
  // (an input) or nothing inside consumes from them (an output).
  for (const element of [...net.places, ...net.transitions]) {
    if (!hiddenIds.has(element.id)) continue;
    const frameId = ownerById.get(element.id);
    const frame = frameId ? frameById.get(frameId) : undefined;
    if (!frame) continue;

    const open: Array<"source" | "target"> = [];
    if (!drainedInside.has(element.id)) open.push("source");
    if (!fedFromInside.has(element.id)) open.push("target");

    for (const type of open) {
      if (covered.has(`${element.id}:${type}`)) continue;
      const candidate = framePortCandidate(
        net,
        frame,
        element.id,
        type,
        `port-interface-${type}-${element.id}`,
        element.name,
      );
      if (candidate) candidates.push(candidate);
    }
  }

  const groups = new Map<string, PortCandidate[]>();
  for (const c of candidates) {
    const key = `${c.frameId}:${c.side}`;
    const arr = groups.get(key) ?? [];
    arr.push(c);
    groups.set(key, arr);
  }

  const result = new Map<string, ObjectFramePort[]>();
  for (const [key, group] of groups.entries()) {
    const [frameId, side] = key.split(":") as [string, FramePortSide];
    const frame = frameById.get(frameId)!;
    const sideLenPx = side === "bottom" ? frame.graphics.width : frame.graphics.height;
    group.sort((a, b) => a.naturalOffset - b.naturalOffset);
    const positions = spreadOffsets(group.length, sideLenPx);
    const arr = result.get(frameId) ?? [];
    group.forEach((c, i) => {
      arr.push({
        id: c.id,
        type: c.type,
        side: c.side,
        offset: positions[i],
        kind: c.kind,
        counterpartLabel: c.counterpartLabel,
        elementId: c.elementId,
      });
    });
    result.set(frameId, arr);
  }

  return result;
}

function sideLen(isPlace: boolean, side: HandleSide): number {
  return side === "left" || side === "right"
    ? isPlace ? PLACE_H : TRANS_H
    : isPlace ? PLACE_W : TRANS_W;
}

interface ArcRouting {
  srcSide: HandleSide;
  tgtSide: HandleSide;
  srcOffset: number;
  tgtOffset: number;
  /** px offset applied to the bend column/row to separate parallel segments. */
  midOffset: number;
}

/** Must match CORNER_OFFSET in OrthogonalEdge.tsx. */
const ORTHO_CORNER = 20;
/** Minimum pixel gap enforced between parallel mid-segments. */
const MID_LANE_PX = 14;

function handleDir(side: HandleSide): [number, number] {
  switch (side) {
    case "right":  return [ 1,  0];
    case "left":   return [-1,  0];
    case "bottom": return [ 0,  1];
    case "top":    return [ 0, -1];
  }
}

/** Pixel position of a node's handle on its boundary. */
function nodeHandlePos(
  net: PetriNetData,
  nodeId: string,
  side: HandleSide,
  offsetPct: number,
): { x: number; y: number } {
  const p = net.places.find((pl) => pl.id === nodeId);
  if (p) {
    const { x, y } = p.graphics;
    switch (side) {
      case "left":   return { x, y: y + (offsetPct / 100) * PLACE_H };
      case "right":  return { x: x + PLACE_W, y: y + (offsetPct / 100) * PLACE_H };
      case "top":    return { x: x + (offsetPct / 100) * PLACE_W, y };
      case "bottom": return { x: x + (offsetPct / 100) * PLACE_W, y: y + PLACE_H };
    }
  }
  const t = net.transitions.find((tr) => tr.id === nodeId);
  if (t) {
    const { x, y } = t.graphics;
    switch (side) {
      case "left":   return { x, y: y + (offsetPct / 100) * TRANS_H };
      case "right":  return { x: x + TRANS_W, y: y + (offsetPct / 100) * TRANS_H };
      case "top":    return { x: x + (offsetPct / 100) * TRANS_W, y };
      case "bottom": return { x: x + (offsetPct / 100) * TRANS_W, y: y + TRANS_H };
    }
  }
  return { x: 0, y: 0 };
}

function routeConnections(
  net: PetriNetData,
  connections: FlowConnection[],
): Record<string, ArcRouting> {
  // Detect anti-parallel pairs for dual-track routing.
  const track = new Map<string, number>();
  const paired = new Set<string>();
  for (let i = 0; i < connections.length; i++) {
    const a = connections[i];
    if (paired.has(a.id)) continue;
    for (let j = i + 1; j < connections.length; j++) {
      const b = connections[j];
      if (paired.has(b.id)) continue;
      if (a.source_id === b.target_id && a.target_id === b.source_id) {
        track.set(a.id, 0);
        track.set(b.id, 1);
        paired.add(a.id);
        paired.add(b.id);
      }
    }
  }

  // Side selection per arc.
  const sides: Record<string, { srcSide: HandleSide; tgtSide: HandleSide }> = {};
  for (const a of connections) {
    const src = centerOf(net, a.source_id);
    const tgt = centerOf(net, a.target_id);
    if (!src || !tgt) continue;
    const { sourceSide, targetSide } = pickSides(src.x, src.y, tgt.x, tgt.y);
    sides[a.id] = { srcSide: sourceSide, tgtSide: targetSide };
  }

  // Group arcs by (node, end, side) so we can spread them.
  type Entry = { arcId: string; isSrc: boolean; peerCoord: number };
  const groups = new Map<string, Entry[]>();

  const pushEntry = (
    nodeId: string,
    side: HandleSide,
    entry: Entry,
    which: "source" | "target",
  ) => {
    const key = `${which}:${nodeId}:${side}`;
    const arr = groups.get(key) ?? [];
    arr.push(entry);
    groups.set(key, arr);
  };

  for (const a of connections) {
    if (track.has(a.id)) continue;
    const s = sides[a.id];
    if (!s) continue;
    const src = centerOf(net, a.source_id)!;
    const tgt = centerOf(net, a.target_id)!;
    pushEntry(a.source_id, s.srcSide, {
      arcId: a.id,
      isSrc: true,
      peerCoord: s.srcSide === "left" || s.srcSide === "right" ? tgt.y : tgt.x,
    }, "source");
    pushEntry(a.target_id, s.tgtSide, {
      arcId: a.id,
      isSrc: false,
      peerCoord: s.tgtSide === "left" || s.tgtSide === "right" ? src.y : src.x,
    }, "target");
  }

  const offsets: Record<string, { srcOffset?: number; tgtOffset?: number }> = {};

  for (const [key, entries] of groups.entries()) {
    const [, nodeId, sideStr] = key.split(":");
    const side = sideStr as HandleSide;
    const isPlace = net.places.some((p) => p.id === nodeId);
    entries.sort((a, b) => a.peerCoord - b.peerCoord);
    const positions = spreadOffsets(entries.length, sideLen(isPlace, side));
    entries.forEach((e, i) => {
      offsets[e.arcId] ??= {};
      if (e.isSrc) offsets[e.arcId].srcOffset = positions[i];
      else offsets[e.arcId].tgtOffset = positions[i];
    });
  }

  const ANTI_PARALLEL_OFFSETS = [35, 65] as const;
  const result: Record<string, ArcRouting> = {};
  for (const a of connections) {
    const s = sides[a.id];
    if (!s) continue;
    if (track.has(a.id)) {
      const slot = track.get(a.id)!;
      result[a.id] = {
        srcSide: s.srcSide,
        tgtSide: s.tgtSide,
        srcOffset: ANTI_PARALLEL_OFFSETS[slot],
        tgtOffset: ANTI_PARALLEL_OFFSETS[slot],
        midOffset: (slot === 0 ? -1 : 1) * (MID_LANE_PX / 2),
      };
    } else {
      result[a.id] = {
        srcSide: s.srcSide,
        tgtSide: s.tgtSide,
        srcOffset: offsets[a.id]?.srcOffset ?? 50,
        tgtOffset: offsets[a.id]?.tgtOffset ?? 50,
        midOffset: 0,
      };
    }
  }

  // Detect near-coincident mid-segment positions for regular arcs and spread them.
  type MidInfo = { arcId: string; axis: "x" | "y"; nominal: number };
  const midInfos: MidInfo[] = [];

  for (const a of connections) {
    if (track.has(a.id)) continue;
    const r = result[a.id];
    if (!r) continue;
    const srcH = r.srcSide === "left" || r.srcSide === "right";
    const tgtH = r.tgtSide === "left" || r.tgtSide === "right";
    if (srcH !== tgtH) continue; // mixed case — geometry differs per arc

    const sh = nodeHandlePos(net, a.source_id, r.srcSide, r.srcOffset);
    const th = nodeHandlePos(net, a.target_id, r.tgtSide, r.tgtOffset);
    const [sdx, sdy] = handleDir(r.srcSide);
    const [tdx, tdy] = handleDir(r.tgtSide);

    if (srcH) {
      const nominal = (sh.x + sdx * ORTHO_CORNER + th.x + tdx * ORTHO_CORNER) / 2;
      midInfos.push({ arcId: a.id, axis: "x", nominal });
    } else {
      const nominal = (sh.y + sdy * ORTHO_CORNER + th.y + tdy * ORTHO_CORNER) / 2;
      midInfos.push({ arcId: a.id, axis: "y", nominal });
    }
  }

  for (const axis of ["x", "y"] as const) {
    const infos = midInfos
      .filter((m) => m.axis === axis)
      .sort((a, b) => a.nominal - b.nominal);

    let i = 0;
    while (i < infos.length) {
      let j = i;
      while (
        j + 1 < infos.length &&
        infos[j + 1].nominal - infos[i].nominal < MID_LANE_PX
      ) {
        j++;
      }
      if (j > i) {
        const cluster = infos.slice(i, j + 1);
        const center =
          cluster.reduce((sum, m) => sum + m.nominal, 0) / cluster.length;
        cluster.forEach((m, k) => {
          const ideal = center + (k - (cluster.length - 1) / 2) * MID_LANE_PX;
          result[m.arcId].midOffset = ideal - m.nominal;
        });
      }
      i = j + 1;
    }
  }

  return result;
}

/** Which node+handle an edge end attaches to, once collapsed frames are taken into account. */
interface ResolvedEndpoint {
  node: string;
  handle: string;
}

/**
 * An endpoint hidden behind a collapsed frame is re-attached to that frame's
 * border port, so the connection stays visible instead of vanishing with the
 * element. Returns null for a hidden element with no owning frame — a broken
 * membership we'd rather not draw at all.
 */
function resolveEndpoint(
  net: PetriNetData,
  hiddenIds: Set<string>,
  elementId: string,
  end: "source" | "target",
  connectionId: string,
  fallbackHandle: string,
): ResolvedEndpoint | null {
  if (!hiddenIds.has(elementId)) return { node: elementId, handle: fallbackHandle };
  const frameId = ownerOf(net, elementId);
  if (!frameId) return null;
  return { node: frameId, handle: `port-${end}-${connectionId}` };
}

/**
 * Two-colour connector highlight, used only where placeFusion edges are
 * drawn below: the strand actually clicked draws in the app's own accent
 * token, and every other link of the same connector draws in a held-back
 * tint of it: one colour for both would say "these are all equally what
 * you picked", which is true of neither. A plain arc or a directional
 * cross-object link is never part of a connector (see connectorOf), so
 * buildEdge below has no third bucket to draw, only "selected" or not, same
 * as before. The tint is mixed against the current surface rather than a
 * second hardcoded literal, so it reads as "the same accent, dialled back"
 * in both light and dark instead of importing the desktop's own light/dark
 * literals.
 */
const CONNECTOR_ACCENT = "var(--accent)";
const CONNECTOR_HELD_BACK = "color-mix(in srgb, var(--accent) 42%, var(--surface))";

function buildEdge(
  arc: FlowConnection,
  selected: boolean,
  edgeStyle: EdgeStyle,
  routing: ArcRouting | undefined,
  animated = false,
  source: ResolvedEndpoint = { node: arc.source_id, handle: `src-${arc.id}` },
  target: ResolvedEndpoint = { node: arc.target_id, handle: `tgt-${arc.id}` },
): FlowEdge {
  const isInhibitor = arc.arc_type === "INHIBITOR";
  const isRead = arc.arc_type === "READ";
  const fireColor = "#ff4d4d";
  const color = animated
    ? fireColor
    : selected
      ? "#3b82f6"
      : isInhibitor
        ? "#ef4444"
        : isRead
          ? "#3b82f6"
          : "#6b7280";
  return {
    id: arc.id,
    source: source.node,
    target: target.node,
    sourceHandle: source.handle,
    targetHandle: target.handle,
    type: edgeStyle === "orthogonal" ? "orthogonal" : edgeStyle === "straight" ? "straight" : "smart",
    label: arc.weight > 1 ? String(arc.weight) : undefined,
    selected,
    animated,
    data: { midOffset: routing?.midOffset ?? 0 },
    markerEnd: isInhibitor
      ? undefined
      : {
          type: MarkerType.ArrowClosed,
          width: 14,
          height: 14,
          color,
        },
    style: {
      stroke: color,
      strokeWidth: animated ? 3 : selected ? 2.5 : 1.5,
      strokeDasharray: isInhibitor ? "4 3" : undefined,
    },
    labelStyle: { fontSize: 10, fill: "#6b7280" },
  };
}

function buildPlaceNode(
  place: PetriPlace,
  handles: ComputedHandle[],
  selected: boolean,
  pendingSource: boolean,
  simTokens: number | undefined,
  pulsingIds: Set<string> | null,
  frameOrigin: { x: number; y: number } | null,
  fusion: { label: string; title: string } | null,
  externalConnections: string[] | undefined,
  canDrag: boolean,
): FlowNode {
  const data: PlaceNodeData = {
    label: place.name,
    tokens: simTokens ?? place.tokens,
    initialTokens: place.tokens,
    handles,
    pulsing: pendingSource || (pulsingIds !== null && pulsingIds.has(place.id)),
    fusionLabel: fusion?.label,
    fusionTitle: fusion?.title,
    // Both ends of a fusion draw the same way: once two places are one
    // instance, neither's marking is any more "its own" than the other's.
    linked: fusion !== null,
    externalConnections,
  };
  return {
    id: place.id,
    type: "place",
    position: frameOrigin
      ? { x: place.graphics.x - frameOrigin.x, y: place.graphics.y - frameOrigin.y }
      : { x: place.graphics.x, y: place.graphics.y },
    data: data as unknown as Record<string, unknown>,
    selected,
    // A member of some object is visible here only because that object
    // happens to be expanded — editing it is confined to the object's own
    // canvas, so it can be selected (for the property panel, read-only) but
    // never dragged from here.
    draggable: canDrag && place.objectId === undefined,
    // Only attach to a frame that is actually on the canvas: React Flow treats
    // a parentId it cannot resolve as a hard error and keeps retrying, which
    // surfaces as "Maximum update depth exceeded" rather than a missing frame.
    ...(place.objectId && frameOrigin
      ? { parentId: place.objectId, extent: "parent" as const }
      : {}),
  };
}

function buildTransitionNode(
  transition: PetriTransition,
  handles: ComputedHandle[],
  selected: boolean,
  pendingSource: boolean,
  simSnapshot: SimulationSnapshot | null,
  pulsingIds: Set<string> | null,
  frameOrigin: { x: number; y: number } | null,
  externalConnections: string[] | undefined,
  canDrag: boolean,
): FlowNode {
  const simBuffer = simSnapshot?.buffers[transition.id];
  const data: TransitionNodeData = {
    label: transition.name,
    distribution: transition.distribution,
    meanDelay: transition.mean_delay,
    standardDeviation: transition.standard_deviation,
    priority: transition.priority,
    probability: transition.probability,
    buffer: simBuffer ?? 0,
    handles,
    pulsing: pendingSource || (pulsingIds !== null && pulsingIds.has(transition.id)),
    externalConnections,
  };
  return {
    id: transition.id,
    type: "transition",
    position: frameOrigin
      ? { x: transition.graphics.x - frameOrigin.x, y: transition.graphics.y - frameOrigin.y }
      : { x: transition.graphics.x, y: transition.graphics.y },
    data: data as unknown as Record<string, unknown>,
    selected,
    draggable: canDrag && transition.objectId === undefined,
    ...(transition.objectId && frameOrigin
      ? { parentId: transition.objectId, extent: "parent" as const }
      : {}),
  };
}

function buildObjectFrameNode(
  frame: NonNullable<PetriNetData["objects"]>[number],
  memberCount: number,
  ports: ObjectFramePort[],
  selected: boolean,
  frameStyle: FrameStyle,
  active: boolean,
  parentOrigin: { x: number; y: number } | null,
  handlers: { onToggleCollapsed: () => void; onEdit: () => void },
  canDrag: boolean,
): FlowNode {
  // A frame with no owner of its own is directly local here — managed as a
  // unit (moved, resized, deleted) the same as any free element. A nested
  // frame is only visible because its actual owner is expanded; it can be
  // opened and viewed but not edited from here, only from its own canvas.
  const local = frame.objectId === undefined;
  const data: ObjectFrameNodeData = {
    label: frame.name,
    priority: frame.priority,
    collapsed: frame.collapsed,
    memberCount,
    ports,
    frameStyle,
    width: frame.graphics.width,
    height: frame.graphics.height,
    active,
    locked: !local,
    ...handlers,
  };
  return {
    id: frame.id,
    type: "objectFrame",
    // A nested object is a child node of the frame it was built inside, so
    // React Flow moves and clips the two together.
    position: parentOrigin
      ? { x: frame.graphics.x - parentOrigin.x, y: frame.graphics.y - parentOrigin.y }
      : { x: frame.graphics.x, y: frame.graphics.y },
    width: frame.graphics.width,
    height: frame.graphics.height,
    ...(frame.objectId && parentOrigin
      ? { parentId: frame.objectId, extent: "parent" as const }
      : {}),
    data: data as unknown as Record<string, unknown>,
    selected,
    draggable: canDrag && local,
    // No dragHandle restriction: the whole frame body (header included)
    // starts a drag, same as any other node — only its own buttons opt out
    // via the "nodrag" class, so a click-then-drag anywhere on an already
    // selected object moves it, not just a grab on the header strip.
    // Sits behind its children while expanded (so they visually read as
    // "inside" it); collapsed, it has no rendered children to sit behind,
    // and its own border ports need to be reachable/visible like any node.
    zIndex: frame.collapsed ? 0 : -1,
  };
}

/**
 * Builds the full node/edge graph for one net: places, transitions, object
 * frames (with border ports for collapsed ones), regular arcs, cross-object
 * links, and place-fusion ties, laid out and routed exactly as the main
 * editor canvas draws them. The single source of truth for that — the read-
 * only chat-workbench preview (ReadOnlyCanvas.tsx) reuses this rather than
 * keeping a second, drifting implementation.
 */
export function buildGraph(
  net: PetriNetData,
  selectedIds: Set<string>,
  pendingArcSourceId: string | null,
  simSnapshot: SimulationSnapshot | null = null,
  edgeStyle: EdgeStyle = "curved",
  frameStyle: FrameStyle = "rect",
  onToggleObjectCollapsed: (id: string) => void = () => {},
  onEditObject: (id: string) => void = () => {},
  externalConnections: Record<string, string[]> | undefined = undefined,
  canDrag: boolean = true,
  // Link ids that share a connector with a selected placeFusion link but
  // aren't themselves selected. Appended last, defaulting to empty, so every
  // existing positional call (tests, ReadOnlyCanvas) keeps working unchanged.
  connectorSiblingIds: Set<string> = new Set(),
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  // Arcs and directional cross-object links are routed and drawn together, so
  // a connection that happens to cross an object boundary looks and behaves
  // like any other arc on the canvas.
  const flowConnections = flowConnectionsOf(net);
  const routing = routeConnections(net, flowConnections);

  const handlesByNode: Record<string, ComputedHandle[]> = {};
  // Every node always gets one fallback source/target handle pair, regardless of
  // whether it has any connections — place-fusion links (rendered further below)
  // attach to these, since they have no per-connection routing of their own.
  for (const p of net.places) {
    handlesByNode[p.id] = [
      { id: LINK_SOURCE_HANDLE, type: "source", side: "right", offset: 50 },
      { id: LINK_TARGET_HANDLE, type: "target", side: "left", offset: 50 },
    ];
  }
  for (const t of net.transitions) {
    handlesByNode[t.id] = [
      { id: LINK_SOURCE_HANDLE, type: "source", side: "right", offset: 50 },
      { id: LINK_TARGET_HANDLE, type: "target", side: "left", offset: 50 },
    ];
  }

  for (const arc of flowConnections) {
    const r = routing[arc.id];
    if (!r) continue;
    handlesByNode[arc.source_id]?.push({
      id: `src-${arc.id}`,
      type: "source",
      side: r.srcSide,
      offset: r.srcOffset,
    });
    handlesByNode[arc.target_id]?.push({
      id: `tgt-${arc.id}`,
      type: "target",
      side: r.tgtSide,
      offset: r.tgtOffset,
    });
  }

  const activeTId = simSnapshot?.active_transition_id ?? null;
  const activePhase = simSnapshot?.active_phase ?? null;

  const pulsingPlaceIds = new Set<string>();
  const pulsingTransitionIds = new Set<string>();
  const animatedArcIds = new Set<string>();

  if (activeTId && activePhase) {
    switch (activePhase) {
      case "before_act_in":
        for (const arc of flowConnections) {
          if (arc.target_id === activeTId) {
            animatedArcIds.add(arc.id);
            pulsingPlaceIds.add(arc.source_id);
          }
        }
        break;
      case "after_act_in":
        pulsingTransitionIds.add(activeTId);
        break;
      case "before_act_out":
        pulsingTransitionIds.add(activeTId);
        for (const arc of flowConnections) {
          if (arc.source_id === activeTId) {
            animatedArcIds.add(arc.id);
          }
        }
        break;
      case "after_act_out":
        for (const arc of flowConnections) {
          if (arc.source_id === activeTId) {
            pulsingPlaceIds.add(arc.target_id);
          }
        }
        break;
    }
  } else if (simSnapshot?.fired_transitions) {
    const firedIds = new Set(simSnapshot.fired_transitions);
    for (const id of firedIds) pulsingTransitionIds.add(id);
  }

  // Fusion is transitive, so the badge names the whole group a place belongs
  // to — the tie between two fused places may be off-screen, or the partner may
  // be hidden inside a collapsed object, and the mark still has to read.
  const fusionGroups = fusionGroupsByPlace(net);

  // A shared place is one marking wearing two faces. The running simulation
  // only ever reports (and pulses) whichever half it happens to know by id —
  // the composed engine tracks the pair as two places, not one — so without
  // this, a token landing in the master never touches the joined half's own
  // display: it keeps showing its stale pre-run count and never joins the
  // pulse or lights its own object's frame.
  for (const placeId of [...pulsingPlaceIds]) {
    const group = fusionGroups.get(placeId);
    if (!group) continue;
    for (const memberId of group.members) pulsingPlaceIds.add(memberId);
  }
  const fusionMarkingFor = (placeId: string): number | undefined =>
    simSnapshot ? resolveFusionMarking(fusionGroups, simSnapshot.markings, placeId) : undefined;

  // Parents must precede children in the node array (React Flow resolves
  // parentId by looking backwards), and nesting makes that ordering matter.
  const objects = objectsParentFirst(net);
  const frameById = new Map(objects.map((o) => [o.id, o]));
  const originById = new Map(objects.map((o) => [o.id, { x: o.graphics.x, y: o.graphics.y }]));
  // A frame counts as non-empty by anything it directly holds, a nested
  // object frame included — a frame grouped entirely from other frames (no
  // loose places/transitions of its own) still has real content, and must
  // not fall back to the "this object is empty" placeholder.
  const memberCountById = new Map<string, number>();
  for (const p of net.places) {
    if (p.objectId) memberCountById.set(p.objectId, (memberCountById.get(p.objectId) ?? 0) + 1);
  }
  for (const t of net.transitions) {
    if (t.objectId) memberCountById.set(t.objectId, (memberCountById.get(t.objectId) ?? 0) + 1);
  }
  for (const o of objects) {
    if (o.objectId) memberCountById.set(o.objectId, (memberCountById.get(o.objectId) ?? 0) + 1);
  }

  // Collapsing an object hides everything it contains at any depth, nested
  // objects included.
  const hiddenFrameIds = new Set<string>();
  for (const frame of objects) {
    const parent = frame.objectId ? frameById.get(frame.objectId) : undefined;
    if (parent && (parent.collapsed || hiddenFrameIds.has(parent.id))) {
      hiddenFrameIds.add(frame.id);
    }
  }
  const hidesContents = (frameId: string): boolean => {
    const frame = frameById.get(frameId);
    return !!frame && (frame.collapsed === true || hiddenFrameIds.has(frame.id));
  };
  const hiddenIds = new Set(
    [...net.places, ...net.transitions]
      .filter((el) => el.objectId && hidesContents(el.objectId))
      .map((el) => el.id),
  );
  const visibleObjects = objects.filter((o) => !hiddenFrameIds.has(o.id));
  const connections = connectionsOf(net);
  const portsByFrame = computeFramePorts(net, objects, hiddenIds, connections);

  const fusionBadgeFor = (placeId: string): { label: string; title: string } | null => {
    const group = fusionGroups.get(placeId);
    if (!group) return null;
    const partners = group.members
      .filter((id) => id !== placeId)
      .map((id) => elementName(net, id));
    return { label: group.label, title: partners.join(", ") };
  };

  // A frame lights up while the simulation touches anything inside it, so an
  // object stays informative even while collapsed.
  const activeFrameIds = new Set<string>();
  for (const el of [...net.places, ...net.transitions]) {
    if (!el.objectId) continue;
    if (pulsingPlaceIds.has(el.id) || pulsingTransitionIds.has(el.id)) {
      activeFrameIds.add(el.objectId);
    }
  }

  const nodes: FlowNode[] = [
    // Frame nodes must precede their children in the array — React Flow v12
    // requires a parentId to already exist among earlier nodes.
    ...visibleObjects.map((o) =>
      buildObjectFrameNode(
        o,
        memberCountById.get(o.id) ?? 0,
        portsByFrame.get(o.id) ?? [],
        selectedIds.has(o.id),
        frameStyle,
        activeFrameIds.has(o.id),
        o.objectId ? (originById.get(o.objectId) ?? null) : null,
        {
          onToggleCollapsed: () => onToggleObjectCollapsed(o.id),
          onEdit: () => onEditObject(o.id),
        },
        canDrag,
      ),
    ),
    ...net.places
      .filter((p) => !hiddenIds.has(p.id))
      .map((p) =>
        buildPlaceNode(
          p,
          handlesByNode[p.id],
          selectedIds.has(p.id),
          pendingArcSourceId === p.id,
          fusionMarkingFor(p.id),
          pulsingPlaceIds.size > 0 ? pulsingPlaceIds : null,
          p.objectId ? (originById.get(p.objectId) ?? null) : null,
          fusionBadgeFor(p.id),
          externalConnections?.[p.id],
          canDrag,
        ),
      ),
    ...net.transitions
      .filter((t) => !hiddenIds.has(t.id))
      .map((t) =>
        buildTransitionNode(
          t,
          handlesByNode[t.id],
          selectedIds.has(t.id),
          pendingArcSourceId === t.id,
          simSnapshot,
          pulsingTransitionIds.size > 0 ? pulsingTransitionIds : null,
          t.objectId ? (originById.get(t.objectId) ?? null) : null,
          externalConnections?.[t.id],
          canDrag,
        ),
      ),
  ];

  // A connection with an endpoint inside a collapsed frame is redirected to
  // that frame's border port rather than dropped, so hiding an object never
  // makes a connection silently disappear. One wholly inside a single collapsed
  // frame has nothing to show and is skipped.
  const edges: FlowEdge[] = [];
  for (const a of flowConnections) {
    const conn = { id: a.id, sourceId: a.source_id, targetId: a.target_id };
    if (isInternalToCollapsedFrame(net, hiddenIds, conn)) continue;
    const source = resolveEndpoint(net, hiddenIds, a.source_id, "source", a.id, `src-${a.id}`);
    const target = resolveEndpoint(net, hiddenIds, a.target_id, "target", a.id, `tgt-${a.id}`);
    if (!source || !target) continue;
    edges.push(
      buildEdge(
        a,
        selectedIds.has(a.id),
        edgeStyle,
        routing[a.id],
        animatedArcIds.has(a.id),
        source,
        target,
      ),
    );
  }

  // Place fusion is the one link that is not a flow: it declares that two
  // places in different objects are the same place. There is no arc form for
  // that, so it keeps a distinct look, a dash-dot tie with no arrowhead,
  // rendered through each node's fixed fallback handle pair. FusionEdge owns
  // the dash pattern and stroke width itself; only the colour (which depends
  // on selection and connector membership) is decided here.
  for (const link of getLinks(net)) {
    if (link.type !== "placeFusion") continue;
    if (isInternalToCollapsedFrame(net, hiddenIds, link)) continue;
    const source = resolveEndpoint(
      net, hiddenIds, link.sourceId, "source", link.id, LINK_SOURCE_HANDLE,
    );
    const target = resolveEndpoint(
      net, hiddenIds, link.targetId, "target", link.id, LINK_TARGET_HANDLE,
    );
    if (!source || !target) continue;
    const isSelected = selectedIds.has(link.id);
    const isSibling = !isSelected && connectorSiblingIds.has(link.id);
    edges.push({
      id: link.id,
      source: source.node,
      target: target.node,
      sourceHandle: source.handle,
      targetHandle: target.handle,
      type: "fusion",
      selected: isSelected,
      style: {
        stroke: isSelected ? CONNECTOR_ACCENT : isSibling ? CONNECTOR_HELD_BACK : "#a855f7",
      },
    });
  }

  return { nodes, edges };
}

/** Node width/height used to centre the node on the cursor when creating it. */
function creationOffsetFor(tool: "add-place" | "add-transition") {
  return tool === "add-place"
    ? { x: PLACE_W / 2, y: PLACE_H / 2 }
    : { x: TRANS_W / 2, y: TRANS_H / 2 };
}

const IMPORT_GAP = 80;
/** Placeholder dimensions for the drag-preview silhouette before the file is parsed. */
const IMPORT_PLACEHOLDER_W = 320;
const IMPORT_PLACEHOLDER_H = 200;

function bboxOfNodes(net: PetriNetData) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of net.places) {
    if (p.graphics.x < minX) minX = p.graphics.x;
    if (p.graphics.y < minY) minY = p.graphics.y;
    if (p.graphics.x + PLACE_W > maxX) maxX = p.graphics.x + PLACE_W;
    if (p.graphics.y + PLACE_H > maxY) maxY = p.graphics.y + PLACE_H;
  }
  for (const t of net.transitions) {
    if (t.graphics.x < minX) minX = t.graphics.x;
    if (t.graphics.y < minY) minY = t.graphics.y;
    if (t.graphics.x + TRANS_W > maxX) maxX = t.graphics.x + TRANS_W;
    if (t.graphics.y + TRANS_H > maxY) maxY = t.graphics.y + TRANS_H;
  }
  if (!isFinite(minX)) return null;
  return { minX, minY, maxX, maxY, w: maxX - minX, h: maxY - minY };
}

const FRAME_DROP_MARGIN = 8;

/**
 * Where a drop lands: frameAtPoint is used at drag END for a FREE (unparented)
 * node, never while a frame itself is being dragged over other elements,
 * which must not auto-capture.
 */

/** Clamp a dropped element's position so it renders fully inside its new parent frame. */
function clampIntoFrame(
  pos: { x: number; y: number },
  size: { w: number; h: number },
  frame: { graphics: { x: number; y: number; width: number; height: number } },
): { x: number; y: number } {
  const minX = frame.graphics.x + FRAME_DROP_MARGIN;
  const minY = frame.graphics.y + FRAME_HEADER_H + FRAME_DROP_MARGIN;
  const maxX = frame.graphics.x + frame.graphics.width - size.w - FRAME_DROP_MARGIN;
  const maxY = frame.graphics.y + frame.graphics.height - size.h - FRAME_DROP_MARGIN;
  return {
    x: Math.min(Math.max(pos.x, minX), Math.max(minX, maxX)),
    y: Math.min(Math.max(pos.y, minY), Math.max(minY, maxY)),
  };
}

function computeImportDrop(
  net: PetriNetData,
  width: number,
  height: number,
  viewportCenter: () => { x: number; y: number },
): { x: number; y: number } {
  const existing = bboxOfNodes(net);
  if (!existing) {
    const c = viewportCenter();
    return { x: c.x - width / 2, y: c.y - height / 2 };
  }
  return { x: existing.maxX + IMPORT_GAP, y: existing.minY };
}

/** Tools that drag out a shape on the canvas instead of panning it. */
function isRubberBandTool(tool: EditorTool): boolean {
  return tool === "select-box" || tool === "select-lasso" || tool === "add-object";
}

/**
 * Smallest drag the Petri-object tool treats as "draw a region" — anything
 * under this is a click, which creates a default-sized empty object instead.
 */
const OBJECT_DRAG_MIN_PX = 10;

/** What the user right-clicked, which decides the menu they get. */
type ContextMenuTarget =
  | { kind: "canvas" }
  | { kind: "node"; id: string; nodeKind: "place" | "transition" }
  | { kind: "frame"; id: string }
  // Always a placeFusion link, the only ObjectLink type a connector is made
  // of (see connectorOf). Other link types (and plain arcs) fall through to
  // the canvas menu unchanged, same as before this case existed.
  | { kind: "link"; id: string };

interface EditorCanvasInnerProps {
  className?: string;
}

function EditorCanvasInner({ className }: EditorCanvasInnerProps) {
  const { t } = useTranslation();
  const net = useEditorStore((s) => s.net);
  const tool = useEditorStore((s) => s.tool);
  const selection = useEditorStore((s) => s.selection);
  const pendingArcSource = useEditorStore((s) => s.pendingArcSource);
  const edgeStyle = useEditorStore((s) => s.edgeStyle);
  const frameStyle = useEditorStore((s) => s.frameStyle);

  const addPlace = useEditorStore((s) => s.addPlace);
  const addTransition = useEditorStore((s) => s.addTransition);
  const addArc = useEditorStore((s) => s.addArc);
  const moveNode = useEditorStore((s) => s.moveNode);
  const deleteElement = useEditorStore((s) => s.deleteElement);
  const setSelection = useEditorStore((s) => s.setSelection);
  const collapseInspector = useEditorStore((s) => s.collapseInspector);
  const setPendingArcSource = useEditorStore((s) => s.setPendingArcSource);
  const setTool = useEditorStore((s) => s.setTool);
  const addObjectFrame = useEditorStore((s) => s.addObjectFrame);
  const moveObject = useEditorStore((s) => s.moveObject);
  const resizeObject = useEditorStore((s) => s.resizeObject);
  const toggleObjectCollapsed = useEditorStore((s) => s.toggleObjectCollapsed);
  const addObjectLink = useEditorStore((s) => s.addObjectLink);
  const linkPlaceToForeignTransition = useEditorStore((s) => s.linkPlaceToForeignTransition);
  const splitConnector = useEditorStore((s) => s.splitConnector);
  const ungroupObject = useEditorStore((s) => s.ungroupObject);
  const duplicateObject = useEditorStore((s) => s.duplicateObject);
  const deleteObject = useEditorStore((s) => s.deleteObject);
  const openObjectTab = useCanvasTabsStore((s) => s.openObjectTab);
  const addElementToObject = useEditorStore((s) => s.addElementToObject);
  const externalConnections = useCanvasTabsStore(
    (s) => s.tabs.find((tab) => tab.id === s.activeId)?.externalConnections,
  );

  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const editorMode = useSimulationStore((s) => s.editorMode);
  const currentSnapshot = useSimulationStore((s) => s.currentSnapshot);
  const isSimulating = editorMode === "simulating";
  // Node dragging must yield to the Arc tool's own drag-to-connect gesture —
  // a node's per-node `draggable` overrides React Flow's global nodesDraggable
  // prop when set, so this has to be threaded into buildGraph itself rather
  // than relying on the top-level prop alone.
  const nodesDraggable = !isSimulating && tool === "select";

  const selectedIds = useMemo(
    () => new Set(selection.map((s) => s.id)),
    [selection],
  );

  // Selecting one strand of a connector lights the whole thing: every OTHER
  // link sharing the pair of objects gets the held-back colour in buildGraph.
  // A selection of several links can belong to several different connectors
  // at once, so this unions every one of them.
  const connectorSiblingIds = useMemo(() => {
    const ids = new Set<string>();
    for (const ref of selection) {
      if (ref.kind !== "link") continue;
      for (const sibling of connectorOf(net, ref.id)) {
        if (sibling.id !== ref.id) ids.add(sibling.id);
      }
    }
    return ids;
  }, [selection, net]);

  const onToggleObjectCollapsed = useCallback(
    (id: string) => toggleObjectCollapsed(id),
    [toggleObjectCollapsed],
  );

  const handleEditObject = useCallback(
    (objectId: string) => {
      if (!openObjectTab(objectId)) toast(t("canvas.contextMenu.editObjectFailed"), "error");
    },
    [openObjectTab, t],
  );

  // The graph memo must depend on data only. A callback whose identity churns
  // would rebuild every node and edge object on each render, and React Flow
  // answers a new edges array by setting its store from an effect — which
  // re-renders us, rebuilds the array again, and runs away as "Maximum update
  // depth exceeded". Routing the handlers through a ref keeps them out of it.
  const graphHandlersRef = useRef({
    toggleCollapsed: onToggleObjectCollapsed,
    edit: handleEditObject,
  });
  graphHandlersRef.current = {
    toggleCollapsed: onToggleObjectCollapsed,
    edit: handleEditObject,
  };
  const stableToggleCollapsed = useCallback(
    (id: string) => graphHandlersRef.current.toggleCollapsed(id),
    [],
  );
  const stableEditObject = useCallback(
    (id: string) => graphHandlersRef.current.edit(id),
    [],
  );

  const { nodes: baseNodes, edges } = useMemo(
    () =>
      buildGraph(
        net,
        selectedIds,
        pendingArcSource?.id ?? null,
        isSimulating ? currentSnapshot : null,
        edgeStyle,
        frameStyle,
        stableToggleCollapsed,
        stableEditObject,
        externalConnections,
        nodesDraggable,
        connectorSiblingIds,
      ),
    [
      net,
      selectedIds,
      connectorSiblingIds,
      pendingArcSource,
      isSimulating,
      currentSnapshot,
      edgeStyle,
      frameStyle,
      stableToggleCollapsed,
      stableEditObject,
      externalConnections,
      nodesDraggable,
    ],
  );

  /**
   * Resolves a completed connection gesture (click-source-then-target, or
   * drag) to either a plain PetriArc (same object, or neither end framed —
   * unchanged behavior) or an ObjectLink (different objects). Reuses the
   * existing add-arc interactions verbatim; no separate "link" tool.
   */
  const resolveConnection = useCallback(
    (sourceId: string, sourceKind: "place" | "transition", targetId: string, targetKind: "place" | "transition") => {
      const currentNet = useEditorStore.getState().net;
      const sharedOwner = ownerOf(currentNet, sourceId);
      if (sharedOwner === ownerOf(currentNet, targetId)) {
        // Both ends inside the same object: a normal arc, same as ever — but
        // only when that object IS the current scope (undefined owner, i.e.
        // both ends are directly local here). Two elements sharing a defined
        // owner are both inside some object visible only because it's
        // expanded, and wiring its own members together is an edit confined
        // to its own canvas, same as moving or deleting them would be.
        if (sharedOwner !== undefined) return null;
        return sourceKind !== targetKind ? addArc(sourceId, targetId) : null;
      }
      if (sourceKind === "place" && targetKind === "place") {
        // The user drags FROM the place being repeated (the master, this
        // gesture's sourceId) TO the place that copies it (this gesture's
        // targetId), but addObjectLink's own sourceId/targetId mean STORAGE
        // direction, copy then master (see its doc comment), so the two are
        // flipped here rather than passed straight through.
        const rejection = rejectionForFusion(currentNet, targetId, sourceId);
        if (rejection) {
          toast(t(`canvas.fusion.rejection.${rejection}`), "error");
          return null;
        }
        return addObjectLink("placeFusion", targetId, sourceId);
      }
      if (sourceKind === "transition" && targetKind === "place") {
        return addObjectLink("transitionToPlace", sourceId, targetId);
      }
      if (sourceKind === "place" && targetKind === "transition") {
        // No placeToTransition link (retired, matching PetriObjModelPaint) —
        // synthesize the fusion-backed equivalent instead. See
        // synthesizePlaceToTransitionFusion for why.
        return linkPlaceToForeignTransition(sourceId, targetId);
      }
      return null; // transition -> transition, even cross-object: not valid
    },
    [addArc, addObjectLink, linkPlaceToForeignTransition, t],
  );

  // Live node positions during drag — keeps ReactFlow in sync on every mousemove.
  const [nodes, setNodes] = useState<FlowNode[]>(baseNodes);
  useEffect(() => { setNodes(baseNodes); }, [baseNodes]);
  // Mirrors `nodes` for the raw-DOM drag handlers below, so they read live
  // frame port data without forcing that effect to re-subscribe on every
  // graph rebuild the way adding `nodes` to its dependency array would.
  const nodesRef = useRef<FlowNode[]>(nodes);
  nodesRef.current = nodes;

  const rfInstance = useRef<ReactFlowInstance | null>(null);
  const { screenToFlowPosition, flowToScreenPosition } = useReactFlow();
  const flowToScreenRef = useRef(flowToScreenPosition);
  flowToScreenRef.current = flowToScreenPosition;
  const screenToFlowRef = useRef(screenToFlowPosition);
  screenToFlowRef.current = screenToFlowPosition;

  const onInit = useCallback((instance: ReactFlowInstance) => {
    rfInstance.current = instance;
  }, []);

  useEffect(() => {
    function handleFitView() {
      rfInstance.current?.fitView({ padding: 0.2, duration: 300 });
    }
    window.addEventListener("petri:fit-view", handleFitView);
    return () => window.removeEventListener("petri:fit-view", handleFitView);
  }, []);

  const viewportCenterFlow = useCallback((): { x: number; y: number } => {
    const containerEl = containerRef.current;
    if (!containerEl) return { x: 0, y: 0 };
    const rect = containerEl.getBoundingClientRect();
    return screenToFlowRef.current({
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    });
  }, []);

  const importNetAtBestDrop = useCallback(
    (imported: PetriNetData) => {
      const currentNet = useEditorStore.getState().net;

      // A composed document (it carries petriObject metadata) reopens at its
      // own absolute coordinates, with its frames, nesting and cross-object
      // links intact — the v2.2 contract's "no normalization, no re-centring".
      // Ids are still re-minted so importing into a non-empty canvas can never
      // collide; only the camera moves to show the result.
      if (isComposedNet(imported)) {
        const copy = cloneElements(
          currentNet,
          {
            objects: imported.objects ?? [],
            places: imported.places,
            transitions: imported.transitions,
            arcs: imported.arcs,
            links: imported.links ?? [],
          },
          { x: 0, y: 0 },
        );
        useEditorStore.getState().addElementGroup(copy);
        requestAnimationFrame(() => {
          rfInstance.current?.fitView({ padding: 0.2, duration: 300 });
        });
        return;
      }

      // A flat net declares no canvas of its own, so it lands like a template:
      // next to what is already there, or centered on an empty canvas.
      const tplBox = bboxOfNodes(imported);
      const w = tplBox?.w ?? 0;
      const h = tplBox?.h ?? 0;
      const drop = computeImportDrop(currentNet, w, h, viewportCenterFlow);

      const subnet = instantiateTemplate(
        {
          name: imported.name,
          places: imported.places,
          transitions: imported.transitions,
          arcs: imported.arcs,
          interface: { input_place_id: null, output_place_id: null },
        },
        drop.x,
        drop.y,
        currentNet,
      );
      useEditorStore.getState().addSubnet(subnet);
      useEditorStore.getState().setSelection([]);

      requestAnimationFrame(() => {
        rfInstance.current?.fitView({ padding: 0.2, duration: 300 });
      });
    },
    [viewportCenterFlow],
  );

  useEffect(() => {
    function handleImport(e: Event) {
      const detail = (e as CustomEvent<PetriNetData>).detail;
      if (!detail) return;
      importNetAtBestDrop(detail);
    }
    window.addEventListener("petri:import-pnml", handleImport);
    return () => window.removeEventListener("petri:import-pnml", handleImport);
  }, [importNetAtBestDrop]);

  const onEdgesChange = useCallback(
    (_changes: EdgeChange[]) => {
      // Edge selection and structure are owned by Zustand (selectedIds drives buildGraph).
      // Providing this handler puts ReactFlow in fully-controlled mode for edges, which
      // prevents its internal setEdges sync effect from conflicting with the controlled
      // `selected` prop and causing infinite update loops on double-click.
    },
    [],
  );

  /**
   * Writes one node's final position into the store. Called only when a drag
   * actually ends: React Flow also emits position changes of its own — most
   * notably when it clamps a child back inside its `extent: "parent"` frame on
   * mount — and feeding those back would start a fight it always wins. It
   * clamps, we store, auto-fit moves the frame, it clamps again, and React
   * gives up with "Maximum update depth exceeded".
   */
  const commitNodePosition = useCallback(
    (id: string, position: { x: number; y: number }) => {
      const currentNet = useEditorStore.getState().net;
      const objects = getObjects(currentNet);
      const frame = objects.find((o) => o.id === id);

      if (frame) {
        // A nested frame reports a position relative to the frame it sits in.
        const parent = frame.objectId ? objects.find((o) => o.id === frame.objectId) : undefined;
        moveObject(
          id,
          position.x + (parent?.graphics.x ?? 0),
          position.y + (parent?.graphics.y ?? 0),
        );
        return;
      }

      const owner = ownerOf(currentNet, id);
      if (owner) {
        // A framed child's position is relative to its parent (React Flow's
        // parentId/extent contract) — translate back to the absolute
        // coordinates the store always deals in.
        const parentFrame = objects.find((o) => o.id === owner);
        moveNode(
          id,
          position.x + (parentFrame?.graphics.x ?? 0),
          position.y + (parentFrame?.graphics.y ?? 0),
        );
        return;
      }

      // Free node: dropping it with its center over a frame joins that frame.
      const isPlace = currentNet.places.some((p) => p.id === id);
      const size = isPlace ? { w: PLACE_W, h: PLACE_H } : { w: TRANS_W, h: TRANS_H };
      const center = { x: position.x + size.w / 2, y: position.y + size.h / 2 };
      const targetFrame = frameAtPoint(objects, center);
      if (targetFrame) {
        const dropPos = clampIntoFrame(position, size, targetFrame);
        moveNode(id, dropPos.x, dropPos.y);
        addElementToObject(id, isPlace ? "place" : "transition", targetFrame.id);
      } else {
        moveNode(id, position.x, position.y);
      }
    },
    [moveNode, moveObject, addElementToObject],
  );

  const onNodeDragStop = useCallback(
    (_event: React.MouseEvent, node: FlowNode, dragged: FlowNode[]) => {
      if (isSimulating) return;
      // `dragged` carries every node in a multi-selection drag; it is empty for
      // a plain single-node drag, where `node` is the one that moved.
      const moved = dragged.length > 0 ? dragged : [node];
      if (moved.length === 1) {
        commitNodePosition(moved[0].id, moved[0].position);
        return;
      }

      // One gesture, one undoable step: committing each node through its own
      // store action used to tear a Ctrl+A drag into as many history entries
      // as there were nodes. React Flow reports child positions relative to
      // their parent frame, so targets resolve parents-first; a child whose
      // parent also moved lands at the parent's NEW origin.
      const currentNet = useEditorStore.getState().net;
      const frames = getObjects(currentNet);
      const frameById = new Map(frames.map((f) => [f.id, f]));
      const movedById = new Map(moved.map((n) => [n.id, n]));
      const targets = new Map<string, { x: number; y: number }>();

      const frameTarget = (id: string): { x: number; y: number } | null => {
        const known = targets.get(id);
        if (known) return known;
        const rf = movedById.get(id);
        const frame = frameById.get(id);
        if (!frame) return null;
        if (!rf) return { x: frame.graphics.x, y: frame.graphics.y };
        const parent = frame.objectId ? frameTarget(frame.objectId) : null;
        const target = {
          x: rf.position.x + (parent?.x ?? 0),
          y: rf.position.y + (parent?.y ?? 0),
        };
        targets.set(id, target);
        return target;
      };

      const moves: { id: string; kind: "element" | "object"; x: number; y: number }[] = [];
      for (const f of objectsParentFirst(currentNet)) {
        if (!movedById.has(f.id)) continue;
        const t = frameTarget(f.id);
        if (t) moves.push({ id: f.id, kind: "object", ...t });
      }
      for (const n of moved) {
        if (frameById.has(n.id)) continue;
        const owner = ownerOf(currentNet, n.id);
        const origin = owner ? frameTarget(owner) : null;
        moves.push({
          id: n.id,
          kind: "element",
          x: n.position.x + (origin?.x ?? 0),
          y: n.position.y + (origin?.y ?? 0),
        });
      }
      useEditorStore.getState().moveManyTo(moves);
    },
    [commitNodePosition, isSimulating],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      if (isSimulating) return; // simulation drives node state via snapshots, not user edits
      // Drop "select" changes — selection is owned by Zustand (selectedIds drives
      // buildGraph). Letting ReactFlow's internal deselection events overwrite the
      // controlled `selected` prop would cause the selection to vanish on the next
      // paint even though Zustand still has it.
      const applied = changes.filter((c) => c.type !== "select");
      if (applied.length > 0) {
        setNodes((ns) => applyNodeChanges(applied, ns) as FlowNode[]);
      }

      // Positions are committed by onNodeDragStop, not from here — see
      // commitNodePosition. Resizing has no such feedback loop and is committed
      // directly, once the gesture finishes.
      for (const change of changes) {
        if (change.type === "dimensions" && change.dimensions && change.resizing === false) {
          if (getObjects(useEditorStore.getState().net).some((o) => o.id === change.id)) {
            resizeObject(change.id, change.dimensions.width, change.dimensions.height);
          }
        }
      }
    },
    [isSimulating, resizeObject],
  );

  const containerRef = useRef<HTMLDivElement | null>(null);

  // Drag-to-arc: track source, active state, start pos, and current hover target.
  const arcDragSourceRef = useRef<{ id: string; kind: "place" | "transition" } | null>(null);
  const arcDragTargetRef = useRef<string | null>(null);
  const arcDragActiveRef = useRef(false);
  const arcDragStartPosRef = useRef<{ x: number; y: number } | null>(null);
  const suppressNextNodeClickRef = useRef(false);

  // Ctrl+drag pan: track whether panning and the start position.
  const ctrlPanRef = useRef(false);
  const ctrlPanStartRef = useRef<{ x: number; y: number } | null>(null);
  const suppressNextPaneClickRef = useRef(false);

  // Preview line coords in container-local px (null = not dragging).
  const [arcDragPreview, setArcDragPreview] = useState<{
    sx: number; sy: number; mx: number; my: number;
  } | null>(null);

  // File drag-and-drop preview rectangle, in flow coords.
  const [fileDropPreview, setFileDropPreview] = useState<{
    x: number; y: number; w: number; h: number;
  } | null>(null);

  // Petri-object ghost preview while dragging from the palette.
  const [objectDropPreview, setObjectDropPreview] = useState<{
    flowX: number; flowY: number; template: PetriObjectTemplate;
  } | null>(null);

  // Right-click menu. What it offers depends on what was under the cursor:
  // empty canvas and plain elements act on the selection, an object frame gets
  // its own lifecycle actions.
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    target: ContextMenuTarget;
  } | null>(null);
  const [createObjectOpen, setCreateObjectOpen] = useState(false);

  // After a box/lasso selection is committed we must block the next
  // onSelectionChange call: switching tool to "select" changes selectionOnDrag,
  // which causes ReactFlow to fire onSelectionChange with its (empty) internal
  // state, wiping the selection we just set in Zustand.
  const suppressSelectionChangeRef = useRef(false);

  // Selection box/lasso tracking
  const selectionStartRef = useRef<{ x: number; y: number } | null>(null);
  const selectionPathRef = useRef<Array<{ x: number; y: number }>>([]);
  const [selectionPreview, setSelectionPreview] = useState<{
    start: { x: number; y: number };
    current: { x: number; y: number };
    path: Array<{ x: number; y: number }>;
  } | null>(null);


  const onNodeMouseEnter = useCallback<NodeMouseHandler>(
    (event, node) => {
      // Same resolution as onNodeClick: React Flow's own hit-testing can
      // report an object frame instead of the specific child the pointer is
      // actually over, since the frame's bounding box contains its
      // children's and must precede them in the node array.
      const domId = (event.target as HTMLElement | null)?.closest<HTMLElement>("[data-id]")?.dataset.id;
      arcDragTargetRef.current = domId ?? node.id;
    },
    [],
  );

  const onNodeMouseLeave = useCallback<NodeMouseHandler>(
    (event, node) => {
      const domId = (event.target as HTMLElement | null)?.closest<HTMLElement>("[data-id]")?.dataset.id;
      const leftId = domId ?? node.id;
      if (arcDragTargetRef.current === leftId) {
        arcDragTargetRef.current = null;
      }
    },
    [],
  );

  useEffect(() => {
    const containerEl = containerRef.current;

    function onMouseDown(e: MouseEvent) {
      // During simulation, any left-button drag pans the viewport. We reuse
      // ctrlPanRef/ctrlPanStartRef so onMouseMove handles it for free.
      // Clicks (no movement) still reach onNodeClick/onEdgeClick via React events.
      if (isSimulating && e.button === 0) {
        ctrlPanRef.current = true;
        ctrlPanStartRef.current = { x: e.clientX, y: e.clientY };
        return;
      }

      // Ctrl+drag on empty canvas pans the viewport. When Ctrl+click lands on a
      // node/edge we must NOT pan — let the click bubble to React Flow so it can
      // toggle that element's selection (multiSelectionKeyCode defaults to
      // Control on non-Mac).
      if (e.ctrlKey && e.button === 0) {
        let el = e.target as HTMLElement | null;
        let onElement = false;
        while (el && el !== containerEl) {
          if (el.dataset.id || el.classList?.contains("react-flow__edge")) {
            onElement = true;
            break;
          }
          el = el.parentElement;
        }
        if (!onElement) {
          ctrlPanRef.current = true;
          ctrlPanStartRef.current = { x: e.clientX, y: e.clientY };
          return;
        }
      }

      if (isRubberBandTool(tool)) {
        if (!containerEl) return;
        const rect = containerEl.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        selectionStartRef.current = { x, y };
        selectionPathRef.current = [{ x, y }];
        return;
      }

      if (tool !== "add-arc") return;
      const hit = resolveArcHit(e.target as HTMLElement | null, containerEl, net, nodesRef.current);
      if (hit) {
        arcDragSourceRef.current = hit;
        arcDragActiveRef.current = false;
        arcDragStartPosRef.current = { x: e.clientX, y: e.clientY };
        arcDragTargetRef.current = hit.id;
      }
    }

    function onMouseMove(e: MouseEvent) {
      // Handle selection box/lasso
      if (selectionStartRef.current) {
        const containerEl = containerRef.current;
        if (containerEl) {
          const rect = containerEl.getBoundingClientRect();
          const x = e.clientX - rect.left;
          const y = e.clientY - rect.top;
          const currentPoint = { x, y };
          selectionPathRef.current.push(currentPoint);
          setSelectionPreview({
            start: selectionStartRef.current,
            current: currentPoint,
            path: selectionPathRef.current,
          });
        }
        return;
      }

      // Handle Ctrl+drag panning
      if (ctrlPanRef.current && ctrlPanStartRef.current && rfInstance.current) {
        const dx = e.clientX - ctrlPanStartRef.current.x;
        const dy = e.clientY - ctrlPanStartRef.current.y;
        if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
          suppressNextPaneClickRef.current = true;
        }
        const viewport = rfInstance.current.getViewport();
        rfInstance.current.setViewport({ x: viewport.x + dx, y: viewport.y + dy, zoom: viewport.zoom }, { duration: 0 });
        ctrlPanStartRef.current = { x: e.clientX, y: e.clientY };
        return;
      }

      if (!arcDragSourceRef.current || !arcDragStartPosRef.current) return;

      const dx = e.clientX - arcDragStartPosRef.current.x;
      const dy = e.clientY - arcDragStartPosRef.current.y;

      if (!arcDragActiveRef.current) {
        if (Math.sqrt(dx * dx + dy * dy) > 6) {
          arcDragActiveRef.current = true;
          setPendingArcSource(arcDragSourceRef.current);
        } else {
          return;
        }
      }

      const containerEl = containerRef.current;
      if (!containerEl || !flowToScreenRef.current) return;

      const rect = containerEl.getBoundingClientRect();
      const currentNet = useEditorStore.getState().net;
      const sourceCenterFlow = centerOf(currentNet, arcDragSourceRef.current.id);
      if (!sourceCenterFlow) return;

      const src = flowToScreenRef.current(sourceCenterFlow);
      setArcDragPreview({
        sx: src.x - rect.left,
        sy: src.y - rect.top,
        mx: e.clientX - rect.left,
        my: e.clientY - rect.top,
      });
    }

    function onMouseUp(e: MouseEvent) {
      // Petri-object tool: a drag frames whatever it encloses, or becomes an
      // empty object of the drawn size when it encloses nothing. Too small a
      // drag is a click, which onPaneClick turns into a default-sized object.
      if (
        selectionStartRef.current &&
        tool === "add-object" &&
        selectionPathRef.current.length > 1 &&
        containerRef.current &&
        rfInstance.current
      ) {
        const rect = containerRef.current.getBoundingClientRect();
        const toFlow = (p: { x: number; y: number }) =>
          rfInstance.current!.screenToFlowPosition({ x: p.x + rect.left, y: p.y + rect.top });
        const a = toFlow(selectionStartRef.current);
        const b = toFlow(selectionPathRef.current[selectionPathRef.current.length - 1]);
        const minX = Math.min(a.x, b.x);
        const maxX = Math.max(a.x, b.x);
        const minY = Math.min(a.y, b.y);
        const maxY = Math.max(a.y, b.y);

        if (maxX - minX >= OBJECT_DRAG_MIN_PX || maxY - minY >= OBJECT_DRAG_MIN_PX) {
          // The band alone decides both what the new object takes and where it
          // is built. See resolveObjectBand, which owns that rule so it can be
          // tested without a canvas.
          const { parentId, capturedIds } = resolveObjectBand(net, {
            minX,
            minY,
            maxX,
            maxY,
          });

          suppressNextPaneClickRef.current = true;
          if (capturedIds.length > 0) {
            useEditorStore
              .getState()
              .groupElementsIntoObject(
                capturedIds,
                undefined,
                parentId ? { parentId } : undefined,
              );
          } else {
            useEditorStore
              .getState()
              .addObjectFrame(
                minX,
                minY,
                Math.max(FRAME_MIN_W, maxX - minX),
                Math.max(FRAME_MIN_H, maxY - minY),
                parentId ? { parentId } : undefined,
              );
          }
        }

        selectionStartRef.current = null;
        selectionPathRef.current = [];
        setSelectionPreview(null);
        return;
      }

      // Handle selection box/lasso completion
      if (selectionStartRef.current && (tool === "select-box" || tool === "select-lasso") && selectionPathRef.current.length > 1) {
        const selected: Array<{ id: string; kind: "place" | "transition" | "object" }> = [];
        const containerEl = containerRef.current;
        if (containerEl && rfInstance.current) {
          const rect = containerEl.getBoundingClientRect();

          // Convert a container-local point to flow coordinates.
          const toFlow = (p: { x: number; y: number }) =>
            rfInstance.current!.screenToFlowPosition({
              x: p.x + rect.left,
              y: p.y + rect.top,
            });

          if (tool === "select-box") {
            const start = selectionStartRef.current;
            const end = selectionPathRef.current[selectionPathRef.current.length - 1];
            const a = toFlow(start);
            const b = toFlow(end);
            const minX = Math.min(a.x, b.x);
            const maxX = Math.max(a.x, b.x);
            const minY = Math.min(a.y, b.y);
            const maxY = Math.max(a.y, b.y);

            net.places.forEach((place) => {
              const cx = place.graphics.x + PLACE_W / 2;
              const cy = place.graphics.y + PLACE_H / 2;
              if (cx >= minX && cx <= maxX && cy >= minY && cy <= maxY) {
                selected.push({ id: place.id, kind: "place" });
              }
            });
            net.transitions.forEach((transition) => {
              const cx = transition.graphics.x + TRANS_W / 2;
              const cy = transition.graphics.y + TRANS_H / 2;
              if (cx >= minX && cx <= maxX && cy >= minY && cy <= maxY) {
                selected.push({ id: transition.id, kind: "transition" });
              }
            });
            // A frame joins the selection when the band swallows it whole —
            // its center is not enough: a large frame's middle under a small
            // band would drag the entire object into a selection the user
            // aimed at a couple of elements. Marquees used to skip frames
            // entirely, leaving no way to select an object without clicking
            // each one.
            getObjects(net).forEach((frame) => {
              const g = frame.graphics;
              if (g.x >= minX && g.y >= minY && g.x + g.width <= maxX && g.y + g.height <= maxY) {
                selected.push({ id: frame.id, kind: "object" });
              }
            });
          } else {
            // Lasso: convert entire path to flow space, then run point-in-polygon.
            const pathFlow = selectionPathRef.current.map(toFlow);
            net.places.forEach((place) => {
              const center = { x: place.graphics.x + PLACE_W / 2, y: place.graphics.y + PLACE_H / 2 };
              if (pointInPolygon(center, pathFlow)) {
                selected.push({ id: place.id, kind: "place" });
              }
            });
            net.transitions.forEach((transition) => {
              const center = { x: transition.graphics.x + TRANS_W / 2, y: transition.graphics.y + TRANS_H / 2 };
              if (pointInPolygon(center, pathFlow)) {
                selected.push({ id: transition.id, kind: "transition" });
              }
            });
            // Same whole-frame rule as the box: every corner must be lassoed.
            getObjects(net).forEach((frame) => {
              const g = frame.graphics;
              const corners = [
                { x: g.x, y: g.y },
                { x: g.x + g.width, y: g.y },
                { x: g.x, y: g.y + g.height },
                { x: g.x + g.width, y: g.y + g.height },
              ];
              if (corners.every((c) => pointInPolygon(c, pathFlow))) {
                selected.push({ id: frame.id, kind: "object" });
              }
            });
          }

          suppressNextPaneClickRef.current = true;
          if (selected.length > 0) {
            suppressSelectionChangeRef.current = true;
            setSelection(selected);
            setTool("select");
          }
        }
      }

      selectionStartRef.current = null;
      selectionPathRef.current = [];
      setSelectionPreview(null);

      // Stop Ctrl+drag panning
      if (ctrlPanRef.current) {
        ctrlPanRef.current = false;
        ctrlPanStartRef.current = null;
        return;
      }

      const source = arcDragSourceRef.current;
      const active = arcDragActiveRef.current;
      arcDragSourceRef.current = null;
      arcDragActiveRef.current = false;
      arcDragStartPosRef.current = null;
      setArcDragPreview(null);

      if (!active || !source) return;

      suppressNextNodeClickRef.current = true;

      const target = arcDragTargetRef.current;
      if (!target || target === source.id) {
        setPendingArcSource(null);
        return;
      }

      const currentNet = useEditorStore.getState().net;
      const targetIsPlace = currentNet.places.some((p) => p.id === target);
      const targetIsTransition = currentNet.transitions.some((t) => t.id === target);
      if (targetIsPlace || targetIsTransition) {
        const targetKind: "place" | "transition" = targetIsPlace ? "place" : "transition";
        resolveConnection(source.id, source.kind, target, targetKind);
        setPendingArcSource(null);
        return;
      }

      // `target` is a node id but neither a place nor a transition — the drop
      // may have landed on a collapsed Petri-object's border port, which
      // stands in for one of its hidden members (see onNodeMouseEnter: the
      // frame itself is what arcDragTargetRef tracks, so the exact port has
      // to be resolved separately, from what's actually under the cursor).
      const dropEl = document.elementFromPoint(e.clientX, e.clientY);
      const handleEl = dropEl instanceof HTMLElement ? dropEl.closest<HTMLElement>("[data-handleid]") : null;
      const port =
        handleEl?.dataset.nodeid === target && handleEl.dataset.handleid
          ? findFramePort(nodesRef.current, target, handleEl.dataset.handleid)
          : null;
      if (port && port.elementId !== source.id) {
        resolveConnection(source.id, source.kind, port.elementId, port.kind);
      }
      setPendingArcSource(null);
    }

    // React Flow's pane click handler unconditionally calls resetSelectedElements()
    // after invoking onPaneClick, which would wipe the selection we just set via
    // box/lasso. Swallow the click at the container boundary so it never reaches RF.
    function onClickCapture(e: MouseEvent) {
      if (suppressNextPaneClickRef.current) {
        suppressNextPaneClickRef.current = false;
        e.stopPropagation();
      }
    }

    if (containerEl) {
      containerEl.addEventListener("mousedown", onMouseDown, true);
      containerEl.addEventListener("click", onClickCapture, true);
    }
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      if (containerEl) {
        containerEl.removeEventListener("mousedown", onMouseDown, true);
        containerEl.removeEventListener("click", onClickCapture, true);
      }
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [resolveConnection, setPendingArcSource, tool, net, setSelection, isSimulating]);

  const onPaneClick = useCallback(
    (event: React.MouseEvent) => {
      if (suppressNextPaneClickRef.current) {
        suppressNextPaneClickRef.current = false;
        return;
      }
      if (!isSimulating) {
        if (tool === "add-place" || tool === "add-transition") {
          const pos = screenToFlowPosition({ x: event.clientX, y: event.clientY });
          const offset = creationOffsetFor(tool);
          const x = pos.x - offset.x;
          const y = pos.y - offset.y;
          if (tool === "add-place") addPlace(x, y);
          else addTransition(x, y);
          return;
        }
        if (tool === "add-object") {
          const pos = screenToFlowPosition({ x: event.clientX, y: event.clientY });
          const id = addObjectFrame(pos.x - 120, pos.y - 80);
          setSelection([{ id, kind: "object" }]);
          return;
        }
        if (tool === "add-arc") {
          setPendingArcSource(null);
          return;
        }
      }
      setSelection([]);
      collapseInspector();
    },
    [
      tool,
      addPlace,
      addTransition,
      addObjectFrame,
      screenToFlowPosition,
      setSelection,
      collapseInspector,
      setPendingArcSource,
      isSimulating,
    ],
  );

  const handleNodeClickForArcTool = useCallback(
    (nodeId: string) => {
      const kind: "place" | "transition" = net.places.some((p) => p.id === nodeId)
        ? "place"
        : "transition";
      if (!pendingArcSource) {
        setPendingArcSource({ id: nodeId, kind });
        return;
      }
      if (pendingArcSource.id === nodeId) {
        setPendingArcSource(null);
        return;
      }
      const created = resolveConnection(pendingArcSource.id, pendingArcSource.kind, nodeId, kind);
      if (created) {
        setPendingArcSource(null);
        return;
      }
      // Not a valid connection between these two (same kind & same object,
      // or transition->transition) — re-anchor instead of silently failing.
      setPendingArcSource({ id: nodeId, kind });
    },
    [pendingArcSource, net.places, resolveConnection, setPendingArcSource],
  );

  const onNodeClick = useCallback<NodeMouseHandler>(
    (event, node) => {
      if (suppressNextNodeClickRef.current) {
        suppressNextNodeClickRef.current = false;
        return;
      }
      // An object frame's bounding box necessarily contains its children's,
      // since they're rendered inside its drawn boundary — near a child's
      // own edge, React Flow's node it reports can disagree with what's
      // actually under the pointer. The DOM is never wrong about that, so
      // the real target is resolved from event.target and preferred
      // whenever it names a different, valid node.
      const currentNet = useEditorStore.getState().net;
      const domId = (event.target as HTMLElement | null)?.closest<HTMLElement>("[data-id]")?.dataset.id;
      let nodeId = node.id;
      let nodeType: string = node.type ?? "";
      if (domId && domId !== nodeId) {
        if (currentNet.places.some((p) => p.id === domId)) {
          nodeId = domId;
          nodeType = "place";
        } else if (currentNet.transitions.some((t) => t.id === domId)) {
          nodeId = domId;
          nodeType = "transition";
        } else if (getObjects(currentNet).some((o) => o.id === domId)) {
          nodeId = domId;
          nodeType = "objectFrame";
        }
      }
      if (nodeType === "objectFrame") {
        const frame = getObjects(currentNet).find((o) => o.id === nodeId);
        // A frame with no owner of its own is managed as a unit from here
        // (moved, deleted, resized); a nested one is only visible because
        // its actual owner is expanded, and editing it — deleting it,
        // adding a new member inside it — is confined to its own canvas.
        const local = frame?.objectId === undefined;
        if (!isSimulating && tool === "delete") {
          if (!local) return;
          deleteElement({ id: nodeId, kind: "object" });
          return;
        }
        // The Arc tool clicking exactly on a collapsed frame's border port
        // reaches through to the hidden member that port stands for — the
        // frame itself is never a valid arc endpoint, only what's behind it.
        if (!isSimulating && tool === "add-arc") {
          const handleEl = (event.target as HTMLElement | null)?.closest<HTMLElement>("[data-handleid]");
          const port = handleEl?.dataset.handleid
            ? findFramePort(nodesRef.current, nodeId, handleEl.dataset.handleid)
            : null;
          if (port) {
            handleNodeClickForArcTool(port.elementId);
            return;
          }
        }
        setSelection([{ id: nodeId, kind: "object" }]);
        return;
      }
      const kind: "place" | "transition" = nodeType === "place" ? "place" : "transition";
      if (!isSimulating) {
        if (tool === "delete") {
          // A member of some object is visible here only because that
          // object is expanded — removing it is confined to the object's
          // own canvas, same as any other edit to its contents.
          if (ownerOf(currentNet, nodeId) !== undefined) return;
          deleteElement({ id: nodeId, kind });
          return;
        }
        if (tool === "add-arc") {
          handleNodeClickForArcTool(nodeId);
          return;
        }
      }
      setSelection([{ id: nodeId, kind }]);
    },
    [tool, setSelection, handleNodeClickForArcTool, deleteElement, isSimulating],
  );

  const onEdgeClick = useCallback(
    (_event: React.MouseEvent, edge: FlowEdge) => {
      const currentNet = useEditorStore.getState().net;
      const isLink = getLinks(currentNet).some((l) => l.id === edge.id);
      const kind: "arc" | "link" = isLink ? "link" : "arc";
      if (!isSimulating && tool === "delete") {
        // A link crosses object boundaries by definition, so deleting one is
        // never "editing a foreign object's internals" — it's removing a
        // declared connection, same spirit as the port-connect feature. A
        // plain arc's two ends always share one owner; if that owner is
        // defined, the arc is wholly inside some object and only that
        // object's own canvas may remove it.
        if (kind === "arc") {
          const arc = currentNet.arcs.find((a) => a.id === edge.id);
          if (arc && ownerOf(currentNet, arc.source_id) !== undefined) return;
        }
        deleteElement({ id: edge.id, kind });
        return;
      }
      setSelection([{ id: edge.id, kind }]);
    },
    [tool, deleteElement, setSelection, isSimulating],
  );

  const onSelectionChange = useCallback(
    (params: OnSelectionChangeParams) => {
      if (isSimulating) return;
      if (tool !== "select") return;
      // Swallow the ReactFlow-internal empty-selection event that fires when
      // selectionOnDrag changes (tool switch from select-box/lasso → select).
      if (suppressSelectionChangeRef.current) {
        suppressSelectionChangeRef.current = false;
        return;
      }
      const currentNet = useEditorStore.getState().net;
      const linkIds = new Set(getLinks(currentNet).map((l) => l.id));
      const refs: ElementRef[] = [];
      for (const n of params.nodes) {
        if (n.type === "objectFrame") {
          refs.push({ id: n.id, kind: "object" });
          continue;
        }
        const kind: "place" | "transition" = n.type === "place" ? "place" : "transition";
        refs.push({ id: n.id, kind });
      }
      for (const e of params.edges) {
        refs.push({ id: e.id, kind: linkIds.has(e.id) ? "link" : "arc" });
      }
      // Avoid redundant updates (ReactFlow fires often during drags).
      // Use set-based comparison — ReactFlow may return elements in any order.
      const current = useEditorStore.getState().selection;
      const same =
        current.length === refs.length &&
        (() => {
          const map = new Map(current.map((c) => [c.id, c.kind]));
          return refs.every((r) => map.get(r.id) === r.kind);
        })();
      if (!same) setSelection(refs);
    },
    [tool, setSelection],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const t = event.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) {
        return;
      }
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const simState = useSimulationStore.getState();
        const { status } = simState;

        if (!isSimulating || status === "idle" || status === "done" || status === "error") {
          simState.enterSimulationModeStepped();
          return;
        }
        if (status === "running") {
          simState.pauseSimulation();
          if (event.key === "ArrowRight") simState.stepForward();
          else simState.stepBackward();
          return;
        }
        if (status === "paused") {
          if (event.key === "ArrowRight") simState.stepForward();
          else simState.stepBackward();
        }
        return;
      }
      if (event.key === "Escape") {
        if (isSimulating) {
          useSimulationStore.getState().exitSimulationMode();
          return;
        }
        setTool("select");
        setPendingArcSource(null);
        return;
      }
      if (event.key === "a" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (!isSimulating) {
          // Deferred so React Flow's own select-all doesn't overwrite ours.
          // The store owns what "everything" means — objects and links included.
          setTimeout(() => {
            suppressSelectionChangeRef.current = true;
            useEditorStore.getState().selectAll();
          }, 0);
        }
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        useEditorStore.getState().deleteSelection();
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [setTool, setPendingArcSource, isSimulating]);

  const proOptions = useMemo(() => ({ hideAttribution: true }), []);

  const cursorClass = (() => {
    if (isSimulating) return "";
    if (tool === "add-place" || tool === "add-transition" || tool === "add-object") {
      return "cursor-crosshair";
    }
    if (tool === "add-arc") return "cursor-pointer";
    return "";
  })();

  const onDragOver = useCallback(
    (event: React.DragEvent) => {
      if (event.dataTransfer.types.includes("application/petri-object-id")) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        const template = getDraggingTemplate();
        if (template) {
          const flowPos = screenToFlowRef.current({ x: event.clientX, y: event.clientY });
          setObjectDropPreview({ flowX: flowPos.x, flowY: flowPos.y, template });
        }
        return;
      }
      if (event.dataTransfer.types.includes("application/editor-tool")) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        return;
      }
      if (event.dataTransfer.types.includes("Files")) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        const currentNet = useEditorStore.getState().net;
        const drop = computeImportDrop(
          currentNet,
          IMPORT_PLACEHOLDER_W,
          IMPORT_PLACEHOLDER_H,
          viewportCenterFlow,
        );
        setFileDropPreview({
          x: drop.x,
          y: drop.y,
          w: IMPORT_PLACEHOLDER_W,
          h: IMPORT_PLACEHOLDER_H,
        });
      }
    },
    [viewportCenterFlow],
  );

  const onDragLeave = useCallback((event: React.DragEvent) => {
    // Only clear if leaving the container itself, not just moving between children.
    const related = event.relatedTarget as Node | null;
    if (related && containerRef.current?.contains(related)) return;
    setFileDropPreview(null);
    setObjectDropPreview(null);
  }, []);

  const onDrop = useCallback(
    async (event: React.DragEvent) => {
      if (event.dataTransfer.types.includes("Files")) {
        event.preventDefault();
        event.stopPropagation();
        setFileDropPreview(null);
        const file = event.dataTransfer.files?.[0];
        if (!file) return;
        const lower = file.name.toLowerCase();
        if (!lower.endsWith(".pnml") && !lower.endsWith(".xml")) {
          toast(`Unsupported file: ${file.name}`, "error");
          return;
        }
        try {
          const text = await file.text();
          const { data, warnings } = parsePnml(text);
          if (warnings.length > 0) {
            console.warn("PNML import warnings:", warnings);
            toast(summarizeImportWarnings(warnings), "warning");
          }
          importNetAtBestDrop(data);
        } catch (err) {
          toast(err instanceof Error ? err.message : String(err), "error");
        }
        return;
      }

      const toolId = event.dataTransfer.getData("application/editor-tool");
      if (toolId) {
        event.preventDefault();
        const pos = screenToFlowPosition({ x: event.clientX, y: event.clientY });
        // Dropped over an expanded frame, the new element joins it, exactly
        // like dragging an existing free element in does.
        const dropFrame = frameAtPoint(getObjects(useEditorStore.getState().net), pos);
        const membership = dropFrame ? { objectId: dropFrame.id } : undefined;
        if (toolId === "add-place") {
          useEditorStore.getState().addPlace(pos.x - PLACE_W / 2, pos.y - PLACE_H / 2, membership);
          setTool("add-place");
        } else if (toolId === "add-transition") {
          useEditorStore
            .getState()
            .addTransition(pos.x - TRANS_W / 2, pos.y - TRANS_H / 2, membership);
          setTool("add-transition");
        }
        return;
      }

      const objectId = event.dataTransfer.getData("application/petri-object-id");
      if (objectId) {
        event.preventDefault();
        setObjectDropPreview(null);
        const detail = await usePetriObjectStore.getState().getDetail(objectId);
        if (!detail) return;
        const flowPos = screenToFlowPosition({ x: event.clientX, y: event.clientY });
        const currentNet = useEditorStore.getState().net;
        const subnet = instantiateTemplate(
          detail.template_data,
          flowPos.x,
          flowPos.y,
          currentNet,
        );
        // A Petri-object arrives already framed, so what lands on the canvas
        // matches the palette entry it came from instead of dissolving into
        // loose places and transitions.
        useEditorStore
          .getState()
          .addSubnetAsObject(subnet, detail.name, { templateId: detail.id });
      }
    },
    [screenToFlowPosition, setTool, importNetAtBestDrop],
  );

  const handleCreateObject = useCallback((name: string) => {
    setCreateObjectOpen(false);
    useEditorStore.getState().groupSelectionIntoObject(name);
  }, []);

  const handleSaveObjectToLibrary = useCallback(
    async (objectId: string) => {
      const result = await saveCanvasObjectToLibrary(objectId);
      if (result.ok) {
        toast(t("canvas.contextMenu.saveToLibraryDone", { name: result.name }), "success");
      } else if (result.reason === "empty") {
        toast(t("canvas.contextMenu.saveToLibraryEmpty"), "error");
      } else if (result.reason === "failed") {
        toast(result.error ?? t("canvas.contextMenu.saveToLibraryFailed"), "error");
      }
    },
    [t],
  );

  const buildContextMenuItems = useCallback(
    (target: ContextMenuTarget): CanvasContextMenuItem[] => {
      const state = useEditorStore.getState();

      if (target.kind === "frame") {
        const frame = getObjects(state.net).find((o) => o.id === target.id);
        // Viewing, opening its own canvas, duplicating (a new copy, not a
        // mutation of this one) and saving a snapshot to the library never
        // touch this frame's own data, so none of that is restricted. Only
        // what actually changes ITS structure — ungrouping it, deleting it
        // and its contents — is confined to a frame directly local here; a
        // nested one is only visible because its real owner is expanded.
        const local = frame?.objectId === undefined;
        return [
          {
            label: t("canvas.contextMenu.editObject"),
            action: () => handleEditObject(target.id),
          },
          {
            label: frame?.collapsed ? t("objectFrame.expand") : t("objectFrame.collapse"),
            action: () => toggleObjectCollapsed(target.id),
          },
          {
            label: t("canvas.contextMenu.duplicateObject"),
            action: () => duplicateObject(target.id),
          },
          {
            label: t("canvas.contextMenu.saveToLibrary"),
            action: () => void handleSaveObjectToLibrary(target.id),
            disabled: !isAuthenticated,
          },
          {
            label: t("canvas.contextMenu.ungroup"),
            action: () => ungroupObject(target.id),
            separatorBefore: true,
            disabled: !local,
          },
          {
            label: t("canvas.contextMenu.deleteObjectWithContents"),
            action: () => deleteObject(target.id, { keepContents: false }),
            danger: true,
            disabled: !local,
          },
        ];
      }

      if (target.kind === "link") {
        // The connector (see connectorOf) is every placeFusion link sharing
        // this one's pair of objects. "Split the whole connector" is only
        // offered once that pair shares more than one place: on a pair
        // sharing exactly one, it would do the same thing as "Split the
        // shared place" under a second name.
        const connector = connectorOf(state.net, target.id);
        const items: CanvasContextMenuItem[] = [
          {
            label: t("canvas.contextMenu.splitSharedPlace"),
            action: () => deleteElement({ id: target.id, kind: "link" }),
            danger: true,
          },
        ];
        if (connector.length > 1) {
          items.push({
            label: t("canvas.contextMenu.splitConnector", { count: connector.length }),
            action: () => splitConnector(target.id),
            danger: true,
          });
        }
        return items;
      }

      const hasNodeSelection = state.selection.some(
        (r) => r.kind === "place" || r.kind === "transition" || r.kind === "object",
      );
      const items: CanvasContextMenuItem[] = [
        {
          label: t("canvas.contextMenu.createObject"),
          action: () => setCreateObjectOpen(true),
          disabled: !hasNodeSelection,
        },
      ];

      if (target.kind === "node") {
        const owner = ownerOf(state.net, target.id);
        // A member of some object is visible here only because that object
        // is expanded — removing it (from the object, or entirely) is an
        // edit confined to the object's own canvas. "Remove from object"
        // only ever applied to such an owned element in the first place, so
        // it has no legitimate use left to gate down to; deleting stays
        // offered, disabled, so the reason a locked element can't be
        // removed this way is visible rather than the option just vanishing.
        items.push({
          label: t("canvas.contextMenu.deleteElement"),
          action: () => deleteElement({ id: target.id, kind: target.nodeKind }),
          danger: true,
          separatorBefore: !owner,
          disabled: owner !== undefined,
        });
      }

      return items;
    },
    [
      t,
      isAuthenticated,
      handleEditObject,
      handleSaveObjectToLibrary,
      toggleObjectCollapsed,
      duplicateObject,
      ungroupObject,
      deleteObject,
      deleteElement,
      splitConnector,
    ],
  );

  const onContextMenu = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      if (isSimulating) return;

      let nodeId: string | null = null;
      let el: HTMLElement | null = event.target as HTMLElement;
      while (el && el !== containerRef.current) {
        const dataId = el.getAttribute("data-id");
        if (dataId) {
          nodeId = dataId;
          break;
        }
        el = el.parentElement;
      }

      const currentNet = useEditorStore.getState().net;
      const point = { x: event.clientX, y: event.clientY };

      if (nodeId && getObjects(currentNet).some((o) => o.id === nodeId)) {
        setSelection([{ id: nodeId, kind: "object" }]);
        setContextMenu({ ...point, target: { kind: "frame", id: nodeId } });
        return;
      }

      // React Flow renders an edge as <g class="react-flow__edge" data-id="…">,
      // the same attribute the walk above already follows for nodes, so a
      // right-click that lands on the tie itself resolves the same way. Only
      // a placeFusion link gets its own menu (the connector-split commands);
      // any other link id, and every plain arc id, falls through unchanged.
      const link = nodeId ? getLinks(currentNet).find((l) => l.id === nodeId) : undefined;
      if (nodeId && link?.type === "placeFusion") {
        const alreadySelected = useEditorStore
          .getState()
          .selection.some((r) => r.id === nodeId);
        if (!alreadySelected) setSelection([{ id: nodeId, kind: "link" }]);
        setContextMenu({ ...point, target: { kind: "link", id: nodeId } });
        return;
      }

      const nodeKind = nodeId ? elementKind(currentNet, nodeId) : null;
      if (nodeId && nodeKind) {
        // Right-clicking outside the current selection re-selects that one
        // element; right-clicking inside it leaves the selection alone, so
        // "Create Petri-object" can act on everything the user picked.
        const alreadySelected = useEditorStore
          .getState()
          .selection.some((r) => r.id === nodeId);
        if (!alreadySelected) setSelection([{ id: nodeId, kind: nodeKind }]);
        setContextMenu({ ...point, target: { kind: "node", id: nodeId, nodeKind } });
        return;
      }

      setContextMenu({ ...point, target: { kind: "canvas" } });
    },
    [setSelection, isSimulating],
  );

  return (
    <div
      ref={containerRef}
      className={`relative h-full w-full ${cursorClass} ${className ?? ""}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onContextMenu={onContextMenu}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        // Never float a selected node above everything else: a selected
        // expanded frame would jump from its deliberate z of -1 to the
        // elevated layer, covering its own members — every click meant for
        // an element inside would select the frame again, and the arc tool
        // could not touch anything in a selected object.
        elevateNodesOnSelect={false}
        onInit={onInit}
        onNodesChange={onNodesChange}
        onNodeDragStop={onNodeDragStop}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseLeave={onNodeMouseLeave}
        onEdgeClick={onEdgeClick}
        onPaneClick={onPaneClick}
        onMoveStart={() => { setSelection([]); collapseInspector(); }}
        onSelectionChange={onSelectionChange}
        proOptions={proOptions}
        connectionMode={ConnectionMode.Loose}
        nodesDraggable={nodesDraggable}
        nodesConnectable={false}
        panOnDrag={!isSimulating && !isRubberBandTool(tool) && tool !== "add-arc"}
        panOnScroll={!isSimulating && !isRubberBandTool(tool) && tool !== "add-arc"}
        selectionOnDrag={!isSimulating && tool === "select"}
        fitView={false}
        minZoom={0.25}
        maxZoom={4}
        className="bg-zinc-50 dark:bg-zinc-950"
      >
        <Background color="#d4d4d8" gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {isSimulating && <TokenAnimationOverlay />}
      {fileDropPreview && containerRef.current && (() => {
        const rect = containerRef.current.getBoundingClientRect();
        const tl = flowToScreenRef.current({ x: fileDropPreview.x, y: fileDropPreview.y });
        const br = flowToScreenRef.current({
          x: fileDropPreview.x + fileDropPreview.w,
          y: fileDropPreview.y + fileDropPreview.h,
        });
        const x = tl.x - rect.left;
        const y = tl.y - rect.top;
        const w = br.x - tl.x;
        const h = br.y - tl.y;
        return (
          <svg className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible">
            <rect
              x={x}
              y={y}
              width={w}
              height={h}
              rx={8}
              fill="rgb(59 130 246 / 0.08)"
              stroke="#3b82f6"
              strokeWidth={1.5}
              strokeDasharray="6 4"
            />
          </svg>
        );
      })()}
      {objectDropPreview && containerRef.current && (() => {
        const { flowX, flowY, template } = objectDropPreview;
        const rect = containerRef.current!.getBoundingClientRect();
        const zoom = rfInstance.current?.getViewport().zoom ?? 1;

        let minX = Infinity, minY = Infinity;
        for (const p of template.places) {
          if (p.graphics.x < minX) minX = p.graphics.x;
          if (p.graphics.y < minY) minY = p.graphics.y;
        }
        for (const t of template.transitions) {
          if (t.graphics.x < minX) minX = t.graphics.x;
          if (t.graphics.y < minY) minY = t.graphics.y;
        }
        if (!isFinite(minX)) return null;

        const ox = flowX - minX;
        const oy = flowY - minY;

        const toLocal = (fx: number, fy: number) => {
          const sc = flowToScreenRef.current({ x: fx, y: fy });
          return { x: sc.x - rect.left, y: sc.y - rect.top };
        };

        const placeR = (PLACE_W / 2) * zoom;
        const twPx = TRANS_W * zoom;
        const thPx = TRANS_H * zoom;

        const pc = (p: typeof template.places[0]) =>
          toLocal(p.graphics.x + ox + PLACE_W / 2, p.graphics.y + oy + PLACE_H / 2);
        const tc = (t: typeof template.transitions[0]) =>
          toLocal(t.graphics.x + ox + TRANS_W / 2, t.graphics.y + oy + TRANS_H / 2);

        const centerById = new Map<string, { x: number; y: number }>();
        for (const p of template.places) centerById.set(p.id, pc(p));
        for (const t of template.transitions) centerById.set(t.id, tc(t));

        return (
          <svg className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible" style={{ opacity: 0.55 }}>
            <defs>
              <marker id="ghost-arrow" markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6" fill="none" stroke="#3b82f6" strokeWidth="1" />
              </marker>
            </defs>
            {template.arcs.map((arc, i) => {
              const s = centerById.get(arc.source_id);
              const tgt = centerById.get(arc.target_id);
              if (!s || !tgt) return null;
              return <line key={arc.id || i} x1={s.x} y1={s.y} x2={tgt.x} y2={tgt.y} stroke="#3b82f6" strokeWidth={1} markerEnd="url(#ghost-arrow)" />;
            })}
            {template.places.map((p) => {
              const c = pc(p);
              return <circle key={p.id} cx={c.x} cy={c.y} r={placeR} fill="rgb(59 130 246 / 0.15)" stroke="#3b82f6" strokeWidth={1.5} />;
            })}
            {template.transitions.map((t) => {
              const c = tc(t);
              return <rect key={t.id} x={c.x - twPx / 2} y={c.y - thPx / 2} width={twPx} height={thPx} fill="rgb(59 130 246 / 0.15)" stroke="#3b82f6" strokeWidth={1.5} />;
            })}
          </svg>
        );
      })()}
      {arcDragPreview && (
        <svg
          className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible"
        >
          <defs>
            <marker
              id="arc-drag-arrow"
              markerWidth="8"
              markerHeight="6"
              refX="7"
              refY="3"
              orient="auto"
            >
              <polygon points="0 0, 8 3, 0 6" fill="#3b82f6" />
            </marker>
          </defs>
          <line
            x1={arcDragPreview.sx}
            y1={arcDragPreview.sy}
            x2={arcDragPreview.mx}
            y2={arcDragPreview.my}
            stroke="#3b82f6"
            strokeWidth="1.5"
            strokeDasharray="6 4"
            markerEnd="url(#arc-drag-arrow)"
          />
        </svg>
      )}
      {selectionPreview && (
        <svg
          className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible"
        >
          {tool !== "select-lasso" ? (
            <rect
              x={Math.min(selectionPreview.start.x, selectionPreview.current.x)}
              y={Math.min(selectionPreview.start.y, selectionPreview.current.y)}
              width={Math.abs(selectionPreview.current.x - selectionPreview.start.x)}
              height={Math.abs(selectionPreview.current.y - selectionPreview.start.y)}
              fill="none"
              stroke="#3b82f6"
              strokeWidth="1.5"
              strokeDasharray="6 4"
            />
          ) : (
            <polyline
              points={selectionPreview.path.map((p) => `${p.x},${p.y}`).join(" ")}
              fill="none"
              stroke="#3b82f6"
              strokeWidth="1.5"
              strokeDasharray="6 4"
            />
          )}
        </svg>
      )}
      {contextMenu && (
        <CanvasContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          items={buildContextMenuItems(contextMenu.target)}
        />
      )}
      {createObjectOpen && (
        <NameDialog
          title={t("canvas.contextMenu.createObjectTitle")}
          initialName={t("canvas.contextMenu.createObjectDefaultName")}
          placeholder={t("canvas.contextMenu.createObjectPlaceholder")}
          submitLabel={t("canvas.contextMenu.createObjectSubmit")}
          onSubmit={handleCreateObject}
          onClose={() => setCreateObjectOpen(false)}
        />
      )}
    </div>
  );
}

export function EditorCanvas(props: EditorCanvasInnerProps) {
  return (
    <ReactFlowProvider>
      <EditorCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
