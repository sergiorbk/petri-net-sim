import type { PetriNetData } from "@/types/petri";

/**
 * Visual dimensions of the canvas nodes, in flow units. These must match the
 * CSS in PlaceNode / TransitionNode — several layout calculations (handle
 * spreading, frame auto-fit, drop clamping) need the box a node occupies
 * before React Flow has measured it.
 */
export const PLACE_W = 56;
export const PLACE_H = 56;
export const TRANS_W = 28;
export const TRANS_H = 64;

/** Header chrome height reserved at the top of every ObjectFrameNode. */
export const FRAME_HEADER_H = 28;

/**
 * Vertical room a node's caption needs below its box. Places render one line
 * of label; transitions render a label plus a delay line, which is the taller
 * of the two and therefore what the frame has to clear.
 */
export const NODE_LABEL_H = 26;

/** Breathing room kept between an auto-fitted frame and its outermost members. */
export const FRAME_PADDING = 28;

/** Smallest an object frame may get — mirrors NodeResizer's min in ObjectFrameNode. */
export const FRAME_MIN_W = 160;
export const FRAME_MIN_H = 100;

export type NodeKind = "place" | "transition";

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function sizeOfKind(kind: NodeKind): { w: number; h: number } {
  return kind === "place" ? { w: PLACE_W, h: PLACE_H } : { w: TRANS_W, h: TRANS_H };
}

export function kindOfElement(net: PetriNetData, id: string): NodeKind | null {
  if (net.places.some((p) => p.id === id)) return "place";
  if (net.transitions.some((t) => t.id === id)) return "transition";
  return null;
}

/**
 * The box a node occupies, in absolute flow coordinates. Object frames count
 * as nodes here: a frame nested inside another has to be enclosed by its
 * parent just like a place does.
 */
export function boxOfElement(net: PetriNetData, id: string): Box | null {
  const place = net.places.find((p) => p.id === id);
  if (place) return { x: place.graphics.x, y: place.graphics.y, w: PLACE_W, h: PLACE_H };
  const transition = net.transitions.find((t) => t.id === id);
  if (transition) {
    return { x: transition.graphics.x, y: transition.graphics.y, w: TRANS_W, h: TRANS_H };
  }
  const frame = (net.objects ?? []).find((o) => o.id === id);
  if (frame) {
    return {
      x: frame.graphics.x,
      y: frame.graphics.y,
      w: frame.graphics.width,
      h: frame.graphics.height,
    };
  }
  return null;
}

export function centerOfBox(box: Box): { x: number; y: number } {
  return { x: box.x + box.w / 2, y: box.y + box.h / 2 };
}
