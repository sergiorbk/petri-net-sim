import type { PetriNetData } from "@/types/petri";
import { boxOfElement, centerOfBox, PLACE_H, PLACE_W, TRANS_H, TRANS_W } from "@/lib/petri-geometry";
import { getLinks, getObjects } from "@/lib/petri-object-model";

/**
 * Pure geometry for the eraser tool (desktop #56, #58). Kept out of the
 * canvas component so the reach/sweep/band rules can be tested without a
 * pointer or a React Flow instance: the canvas only converts screen
 * coordinates to flow coordinates and calls into here.
 */

export interface Point {
  x: number;
  y: number;
}

export interface Band {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/**
 * Fixed screen-pixel reach the eraser probes past the pointer. The hit tests
 * themselves are in canvas units, which shrink on screen as the view zooms
 * out, so a reach expressed in canvas units would shrink right along with
 * them; the eraser needs the opposite, a reach that GROWS in canvas units
 * as the view shrinks, to stay a constant size on screen.
 */
export const ERASER_REACH_PIXELS = 6;

/**
 * Smallest on-screen drag treated as a sweep rather than a click. Below this
 * a real click's hand-shake would draw a band a pixel across, which encloses
 * nothing, and the eraser would answer an ordinary click by deleting nothing
 * at all, the opposite of what a click is supposed to do.
 */
export const ERASER_SWEEP_MIN_PIXELS = 6;

/**
 * Half-width, in canvas units, of the strip around an arc or link treated as
 * hitting the line itself. Fixed rather than reach-scaled: reach's job is
 * relocating the sample point around the cursor, not thickening the line;
 * conflating the two would make the ring probing redundant.
 */
const ARC_HIT_CORRIDOR = 4;

/** Converts the fixed screen-pixel reach into canvas units at the given zoom. */
export function eraserReachUnits(zoom: number, reachPixels: number = ERASER_REACH_PIXELS): number {
  return Math.max(1, Math.round(reachPixels / zoom));
}

/**
 * Sample points a click probes, nearest first: the exact point, then a near
 * ring at half reach, then a far ring at full reach, each in eight
 * directions (the four axes and four diagonals). Two passes rather than one
 * widened pass: widening in one pass would let a place six pixels away win
 * over an arc directly under the pointer, since both would be probed at the
 * same time with no way to prefer the closer one.
 */
export function eraserProbePoints(center: Point, reach: number): Point[] {
  const nearRadius = Math.max(1, reach / 2);
  const farRadius = reach;
  const directionsDeg = [0, 45, 90, 135, 180, 225, 270, 315];
  const ring = (radius: number): Point[] =>
    directionsDeg.map((deg) => {
      const rad = (deg * Math.PI) / 180;
      return { x: center.x + radius * Math.cos(rad), y: center.y + radius * Math.sin(rad) };
    });
  return [{ x: center.x, y: center.y }, ...ring(nearRadius), ...ring(farRadius)];
}

/**
 * Whether a press-then-release gesture is a sweep rather than a click. Press
 * and release are in canvas (flow) coordinates, same as everything else the
 * eraser reasons about; zoom converts their distance back to the screen
 * pixels the threshold is actually defined in, so the decision doesn't drift
 * as the view is zoomed.
 */
export function isEraserSweep(
  press: Point,
  release: Point,
  zoom: number,
  minPixels: number = ERASER_SWEEP_MIN_PIXELS,
): boolean {
  const screenDistance = Math.hypot(release.x - press.x, release.y - press.y) * zoom;
  return screenDistance >= minPixels;
}

export type EraserElementKind = "place" | "transition" | "object" | "arc" | "link";

export interface EraserHit {
  id: string;
  kind: EraserElementKind;
}

function centerOfElement(net: PetriNetData, id: string): Point | null {
  const box = boxOfElement(net, id);
  return box ? centerOfBox(box) : null;
}

function pointInBand(p: Point, band: Band): boolean {
  return p.x >= band.minX && p.x <= band.maxX && p.y >= band.minY && p.y <= band.maxY;
}

function frameFullyInBand(g: { x: number; y: number; width: number; height: number }, band: Band): boolean {
  return g.x >= band.minX && g.y >= band.minY && g.x + g.width <= band.maxX && g.y + g.height <= band.maxY;
}

function orientation(a: Point, b: Point, c: Point): number {
  const val = (b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y);
  if (val === 0) return 0;
  return val > 0 ? 1 : 2;
}

function onSegment(a: Point, b: Point, c: Point): boolean {
  return (
    b.x <= Math.max(a.x, c.x) &&
    b.x >= Math.min(a.x, c.x) &&
    b.y <= Math.max(a.y, c.y) &&
    b.y >= Math.min(a.y, c.y)
  );
}

function segmentsIntersect(p1: Point, p2: Point, p3: Point, p4: Point): boolean {
  const o1 = orientation(p1, p2, p3);
  const o2 = orientation(p1, p2, p4);
  const o3 = orientation(p3, p4, p1);
  const o4 = orientation(p3, p4, p2);

  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSegment(p1, p3, p2)) return true;
  if (o2 === 0 && onSegment(p1, p4, p2)) return true;
  if (o3 === 0 && onSegment(p3, p1, p4)) return true;
  if (o4 === 0 && onSegment(p3, p2, p4)) return true;
  return false;
}

/** Whether the segment a-b crosses the band at all: an endpoint inside it, or a crossing of one of its four sides. */
function segmentCrossesBand(a: Point, b: Point, band: Band): boolean {
  if (pointInBand(a, band) || pointInBand(b, band)) return true;
  const corners: Point[] = [
    { x: band.minX, y: band.minY },
    { x: band.maxX, y: band.minY },
    { x: band.maxX, y: band.maxY },
    { x: band.minX, y: band.maxY },
  ];
  for (let i = 0; i < 4; i++) {
    if (segmentsIntersect(a, b, corners[i], corners[(i + 1) % 4])) return true;
  }
  return false;
}

export interface EraserBandCatch {
  placeIds: string[];
  transitionIds: string[];
  objectIds: string[];
  arcIds: string[];
  linkIds: string[];
}

/**
 * What a band (dragged out by the eraser's sweep gesture) catches. Places,
 * transitions and objects go by the same rule the select-box marquee uses:
 * a place/transition by its centre, an object frame only when the band
 * swallows it whole, so the eraser takes what a selection band of the same
 * shape would have picked out. Arcs and links have no centre worth speaking
 * of, so they're caught by crossing the band at all instead.
 */
export function resolveEraserBand(net: PetriNetData, band: Band): EraserBandCatch {
  const placeIds = net.places
    .filter((p) => pointInBand({ x: p.graphics.x + PLACE_W / 2, y: p.graphics.y + PLACE_H / 2 }, band))
    .map((p) => p.id);

  const transitionIds = net.transitions
    .filter((t) => pointInBand({ x: t.graphics.x + TRANS_W / 2, y: t.graphics.y + TRANS_H / 2 }, band))
    .map((t) => t.id);

  const objectIds = getObjects(net)
    .filter((o) => frameFullyInBand(o.graphics, band))
    .map((o) => o.id);

  const arcIds = net.arcs
    .filter((a) => {
      const p1 = centerOfElement(net, a.source_id);
      const p2 = centerOfElement(net, a.target_id);
      return !!p1 && !!p2 && segmentCrossesBand(p1, p2, band);
    })
    .map((a) => a.id);

  const linkIds = getLinks(net)
    .filter((l) => {
      const p1 = centerOfElement(net, l.sourceId);
      const p2 = centerOfElement(net, l.targetId);
      return !!p1 && !!p2 && segmentCrossesBand(p1, p2, band);
    })
    .map((l) => l.id);

  return { placeIds, transitionIds, objectIds, arcIds, linkIds };
}

/** Whether any ancestor frame (or the object itself) is collapsed, hiding it from the canvas entirely. */
function isHiddenByCollapsedAncestor(net: PetriNetData, ownerId: string | undefined): boolean {
  const framesById = new Map(getObjects(net).map((f) => [f.id, f]));
  let current = ownerId ? framesById.get(ownerId) : undefined;
  while (current) {
    if (current.collapsed) return true;
    current = current.objectId ? framesById.get(current.objectId) : undefined;
  }
  return false;
}

function pointInBox(point: Point, box: { x: number; y: number; w: number; h: number }): boolean {
  return point.x >= box.x && point.x <= box.x + box.w && point.y >= box.y && point.y <= box.y + box.h;
}

function distanceToSegment(point: Point, a: Point, b: Point): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq === 0) return Math.hypot(point.x - a.x, point.y - a.y);
  let t = ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSq;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy));
}

/**
 * What is exactly at a point, ignoring reach: a place/transition by its box,
 * an arc/link by a small corridor around its line, an object frame by its
 * box otherwise (checked last, since a frame's box necessarily contains its
 * children's, so a child hit always wins over the frame it sits in). A member
 * hidden behind a collapsed ancestor is skipped: nothing is rendered there
 * to click on, only the collapsed frame itself.
 */
export function eraserHitAt(net: PetriNetData, point: Point): EraserHit | null {
  for (const p of net.places) {
    if (isHiddenByCollapsedAncestor(net, p.objectId)) continue;
    if (pointInBox(point, { x: p.graphics.x, y: p.graphics.y, w: PLACE_W, h: PLACE_H })) {
      return { id: p.id, kind: "place" };
    }
  }
  for (const t of net.transitions) {
    if (isHiddenByCollapsedAncestor(net, t.objectId)) continue;
    if (pointInBox(point, { x: t.graphics.x, y: t.graphics.y, w: TRANS_W, h: TRANS_H })) {
      return { id: t.id, kind: "transition" };
    }
  }
  for (const a of net.arcs) {
    const p1 = centerOfElement(net, a.source_id);
    const p2 = centerOfElement(net, a.target_id);
    if (p1 && p2 && distanceToSegment(point, p1, p2) <= ARC_HIT_CORRIDOR) {
      return { id: a.id, kind: "arc" };
    }
  }
  for (const l of getLinks(net)) {
    const p1 = centerOfElement(net, l.sourceId);
    const p2 = centerOfElement(net, l.targetId);
    if (p1 && p2 && distanceToSegment(point, p1, p2) <= ARC_HIT_CORRIDOR) {
      return { id: l.id, kind: "link" };
    }
  }
  const frames = getObjects(net)
    .filter(
      (f) =>
        !isHiddenByCollapsedAncestor(net, f.objectId) &&
        point.x >= f.graphics.x &&
        point.x <= f.graphics.x + f.graphics.width &&
        point.y >= f.graphics.y &&
        point.y <= f.graphics.y + f.graphics.height,
    )
    // Nested frames both contain the point when one sits inside the other;
    // the smaller (innermost) one is what the click actually landed on.
    .sort((a, b) => a.graphics.width * a.graphics.height - b.graphics.width * b.graphics.height);
  if (frames[0]) return { id: frames[0].id, kind: "object" };
  return null;
}

/**
 * The nearest eligible hit within reach of a click, probing nearest point
 * first and skipping anything `isEligible` rejects, so an out-of-scope
 * neighbour under the cursor doesn't block reaching an in-scope element a
 * little farther out. `isEligible` defaults to accepting anything, since
 * scope is an editing rule the store owns, not a geometry concern.
 */
export function eraserPick(
  net: PetriNetData,
  center: Point,
  reach: number,
  isEligible: (hit: EraserHit) => boolean = () => true,
): EraserHit | null {
  for (const probe of eraserProbePoints(center, reach)) {
    const hit = eraserHitAt(net, probe);
    if (hit && isEligible(hit)) return hit;
  }
  return null;
}
