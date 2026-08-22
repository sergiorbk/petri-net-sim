import type { ObjectLinkType, PetriNetData } from "@/types/petri";
import { getLinks, getObjects, ownerOf } from "@/lib/petri-object-model";
import { fetchWithAuth } from "@/lib/api-client";
import type { SimulationStreamCallbacks } from "@/lib/simulation-client";
import { consumeSimulationStream } from "@/lib/simulation-client";

/**
 * Request shape of POST /api/v1/simulate/composed. Links address their
 * endpoints by position — object index in `objects`, then element index within
 * that object's own places or transitions — because a composed model is a set
 * of independent nets whose ids only have to be unique inside each one.
 */
export interface ComposedObjectSpec {
  name: string;
  priority: number;
  x: number;
  y: number;
  net_data: Pick<PetriNetData, "name" | "places" | "transitions" | "arcs">;
  /**
   * Everything below describes how the object is *drawn*, which the simulator
   * has no use for — the endpoint's model ignores unknown fields — but the
   * PNML writer does: these are exactly the `<petriObject>` attributes of the
   * v2.2 dialect (PnmlModelGenerator.createPage), and a save that dropped them
   * would come back as a differently-shaped canvas.
   */
  width?: number;
  height?: number;
  collapsed?: boolean;
  /** Index of the enclosing object in the same `objects` array; absent = top level. */
  parent?: number;
  auto_fit?: boolean;
  /**
   * The anonymous bucket holding elements that belong to no object. Never
   * serialised as an attribute: the document says it by carrying an all-default
   * `<petriObject>` marker, which is how the desktop recognises it too.
   */
  free?: boolean;
}

export interface ComposedLinkSpec {
  type: ObjectLinkType;
  source_object: number;
  source_element: number;
  target_object: number;
  target_element: number;
  quantity: number;
  informational: boolean;
}

export interface ComposedSimulateBody {
  name: string;
  objects: ComposedObjectSpec[];
  links: ComposedLinkSpec[];
}

/** Object frames have no counterpart in a composed model's flat object list. */
const FREE_OBJECT_INDEX_KEY = "";

/**
 * Splits a canvas into the object list a composed model is made of.
 *
 * Every element belongs to exactly one object, so nesting flattens here: an
 * object built inside another is simply another object in the list. Elements
 * on the canvas that belong to no object are collected into one object of
 * their own — a composed model has no notion of a loose element, and dropping
 * them would silently change the net.
 */
function partitionIntoObjects(net: PetriNetData, includeEmptyObjects: boolean) {
  const order: string[] = [];
  const byOwner = new Map<string, { places: typeof net.places; transitions: typeof net.transitions }>();

  const bucket = (ownerKey: string) => {
    let entry = byOwner.get(ownerKey);
    if (!entry) {
      entry = { places: [], transitions: [] };
      byOwner.set(ownerKey, entry);
      order.push(ownerKey);
    }
    return entry;
  };

  // Frames first and in their own order, so object indices stay stable and
  // readable rather than depending on which element happens to come first.
  for (const frame of getObjects(net)) bucket(frame.id);
  for (const place of net.places) bucket(place.objectId ?? FREE_OBJECT_INDEX_KEY).places.push(place);
  for (const transition of net.transitions) {
    bucket(transition.objectId ?? FREE_OBJECT_INDEX_KEY).transitions.push(transition);
  }

  // An object with nothing in it cannot be simulated and carries no meaning —
  // so simulation drops it. A saved document must keep it: a frame that only
  // holds other frames is pure structure and has no direct elements at all,
  // and a frame the user emptied on purpose is still a frame they drew.
  const kept = includeEmptyObjects
    ? order
    : order.filter((key) => {
        const entry = byOwner.get(key)!;
        return entry.places.length > 0 || entry.transitions.length > 0;
      });

  return { order: kept, byOwner };
}

export interface ComposedRequestOptions {
  /**
   * Emit frames with no direct elements as (empty) objects. Off by default, so
   * a simulation request keeps containing only objects the engine can run.
   */
  includeEmptyObjects?: boolean;
}

/**
 * Builds the composed-model request for a canvas, or null when the canvas has
 * nothing a composed model could describe.
 */
export function buildComposedRequest(
  net: PetriNetData,
  options: ComposedRequestOptions = {},
): ComposedSimulateBody | null {
  const { order, byOwner } = partitionIntoObjects(net, options.includeEmptyObjects === true);
  if (order.length === 0) return null;

  const frameById = new Map(getObjects(net).map((o) => [o.id, o]));
  const objectIndexOf = new Map(order.map((key, index) => [key, index]));

  // A link whose endpoints have since come to share one owner (grouping and
  // drag-adoption change memberships after links are drawn) cannot be a link
  // any more: composed PNML and the engine both reject an object linked to
  // itself. A directional one is simply a local flow now, so it is projected
  // into that object's own arcs; a same-owner fusion says "this place is
  // itself" and is dropped. The net data is not touched — the editor heals
  // it on the next membership change; this keeps already-saved documents
  // simulating in the meantime.
  const healedArcsByOwner = new Map<string, PetriNetData["arcs"]>();
  const sameOwnerLinkIds = new Set<string>();
  for (const link of getLinks(net)) {
    const sourceOwner = ownerOf(net, link.sourceId) ?? FREE_OBJECT_INDEX_KEY;
    const targetOwner = ownerOf(net, link.targetId) ?? FREE_OBJECT_INDEX_KEY;
    if (sourceOwner !== targetOwner) continue;
    sameOwnerLinkIds.add(link.id);
    if (link.type === "placeFusion") continue;
    const duplicate = net.arcs.some(
      (a) => a.source_id === link.sourceId && a.target_id === link.targetId,
    );
    if (duplicate) continue;
    const healed = healedArcsByOwner.get(sourceOwner) ?? [];
    healed.push({
      id: `healed_${link.id}`,
      source_id: link.sourceId,
      target_id: link.targetId,
      weight: link.quantity,
      arc_type: link.informational ? "READ" : "NORMAL",
    });
    healedArcsByOwner.set(sourceOwner, healed);
  }

  const objects: ComposedObjectSpec[] = order.map((key, index) => {
    const contents = byOwner.get(key)!;
    const frame = frameById.get(key);
    const memberIds = new Set([
      ...contents.places.map((p) => p.id),
      ...contents.transitions.map((t) => t.id),
    ]);
    // Nesting is drawn, not simulated: the parent's own index in this same
    // list, and only when the parent survived the partition — a link to an
    // object nobody emitted would be a dangling index.
    const parent = frame?.objectId != null ? objectIndexOf.get(frame.objectId) : undefined;
    const spec: ComposedObjectSpec = {
      name: frame?.name ?? net.name ?? `Object ${index + 1}`,
      priority: frame?.priority ?? 0,
      x: frame?.graphics.x ?? 0,
      y: frame?.graphics.y ?? 0,
      net_data: {
        name: frame?.name ?? net.name,
        places: contents.places,
        transitions: contents.transitions,
        // Only arcs inside this object; anything crossing a boundary is a
        // link — plus the local flows healed from links whose endpoints
        // have come to share this owner.
        arcs: [
          ...net.arcs.filter(
            (a) => memberIds.has(a.source_id) && memberIds.has(a.target_id),
          ),
          ...(healedArcsByOwner.get(key) ?? []),
        ],
      },
    };
    if (frame) {
      spec.width = frame.graphics.width;
      spec.height = frame.graphics.height;
      // Collapse only flips a boolean on the canvas: graphics always holds the
      // expanded bounds, so a collapsed object exports the box it reopens into.
      if (frame.collapsed) spec.collapsed = true;
      if (parent !== undefined) spec.parent = parent;
      // Absent means "re-fit me"; only a hand-resized frame has something to say.
      if (frame.autoFit === false) spec.auto_fit = false;
    } else if (key === FREE_OBJECT_INDEX_KEY) {
      spec.free = true;
    }
    return spec;
  });

  /** Position of an element within its own object's places or transitions. */
  const locate = (elementId: string): { object: number; element: number } | null => {
    const ownerKey = ownerOf(net, elementId) ?? FREE_OBJECT_INDEX_KEY;
    const objectIndex = objectIndexOf.get(ownerKey);
    if (objectIndex === undefined) return null;
    const contents = byOwner.get(ownerKey)!;
    const placeIndex = contents.places.findIndex((p) => p.id === elementId);
    if (placeIndex >= 0) return { object: objectIndex, element: placeIndex };
    const transitionIndex = contents.transitions.findIndex((t) => t.id === elementId);
    if (transitionIndex >= 0) return { object: objectIndex, element: transitionIndex };
    return null;
  };

  const links: ComposedLinkSpec[] = [];

  for (const link of getLinks(net)) {
    if (sameOwnerLinkIds.has(link.id)) continue; // healed into local arcs above
    const source = locate(link.sourceId);
    const target = locate(link.targetId);
    if (!source || !target) continue;
    links.push({
      type: link.type,
      source_object: source.object,
      source_element: source.element,
      target_object: target.object,
      target_element: target.element,
      quantity: link.quantity,
      informational: link.informational ?? false,
    });
  }

  // An arc drawn between two objects is a cross-object flow that the model can
  // only express as a link — it was left in net.arcs, but no single object owns
  // it, so it would vanish from every object's net_data above.
  for (const arc of net.arcs) {
    const sourceOwner = ownerOf(net, arc.source_id) ?? FREE_OBJECT_INDEX_KEY;
    const targetOwner = ownerOf(net, arc.target_id) ?? FREE_OBJECT_INDEX_KEY;
    if (sourceOwner === targetOwner) continue;

    const source = locate(arc.source_id);
    const target = locate(arc.target_id);
    if (!source || !target) continue;
    const sourceIsPlace = net.places.some((p) => p.id === arc.source_id);
    links.push({
      type: sourceIsPlace ? "placeToTransition" : "transitionToPlace",
      source_object: source.object,
      source_element: source.element,
      target_object: target.object,
      target_element: target.element,
      quantity: arc.weight,
      informational: arc.arc_type === "READ",
    });
  }

  return { name: net.name, objects, links };
}

/**
 * True when a canvas needs the Petri-object engine rather than the flat
 * projection a built-in engine can run.
 *
 * Read off the very request that would be sent, so the question "which engine"
 * and the answer "what would we send it" cannot drift apart. One object with no
 * links is a plain net someone drew a frame around: the projection does nothing
 * to it but drop the frame, so it means exactly the same thing. A second object
 * or any link is where the flat formalism starts losing — a conflict between
 * objects is settled by object priority, and a flat net has no such notion.
 */
export function needsObjectEngine(net: PetriNetData): boolean {
  const request = buildComposedRequest(net);
  if (!request) return false;
  return request.objects.length > 1 || request.links.length > 0;
}

export interface ComposedSimulationParams {
  timeStep?: number;
  snapshotInterval?: number;
  animationDelay: number;
}

/**
 * Streams a composed-model simulation from the v2 endpoint, which runs it on
 * the external petri-server engine. Markings and buffers come back keyed by
 * this canvas's own element ids.
 */
export async function streamComposedSimulation(
  net: PetriNetData,
  simulationTime: number,
  params: ComposedSimulationParams,
  callbacks: SimulationStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const body = buildComposedRequest(net);
  if (!body) {
    callbacks.onError("This canvas has no Petri-objects to simulate.");
    return;
  }

  const query = new URLSearchParams({
    simulation_time: String(simulationTime),
    animation_delay: String(params.animationDelay),
  });
  if (params.snapshotInterval != null) {
    query.set("snapshot_interval", String(params.snapshotInterval));
  } else if (params.timeStep != null) {
    query.set("time_step", String(params.timeStep));
  }

  const response = await fetchWithAuth(`/api/v1/simulate/composed?${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    let message = "Composed simulation request failed";
    let parsed = false;
    try {
      const json = await response.json();
      const detailMessages: string[] = Array.isArray(json.error?.details)
        ? json.error.details
            .map((d: { message?: string }) => d?.message)
            .filter((m: unknown): m is string => typeof m === "string")
        : [];
      const base = json.error?.message ?? json.detail;
      if (base) {
        message = detailMessages.length > 0 ? `${base}: ${detailMessages.join("; ")}` : base;
        parsed = true;
      }
    } catch {
      // keep the generic message
    }
    // A 4xx with a parsed body is the API rejecting THIS model — its message
    // (e.g. which transition has no input arc) is exactly what the user can
    // act on. Anything else is deployment vocabulary.
    callbacks.onError(
      message,
      parsed && response.status >= 400 && response.status < 500 ? "model" : "transport",
    );
    return;
  }

  await consumeSimulationStream(response, callbacks);
}
