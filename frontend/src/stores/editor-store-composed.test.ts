import { describe, expect, it, beforeEach } from "vitest";
import type { PetriNetData } from "@/types/petri";
import { objectLevel, resolveObjectBand } from "@/lib/petri-object-model";
import { FRAME_MIN_H, FRAME_MIN_W } from "@/lib/petri-geometry";
import { useEditorStore } from "./editor-store";

function resetStore() {
  useEditorStore.getState().resetNet();
}

describe("editor-store object frames", () => {
  beforeEach(resetStore);

  it("addObjectFrame creates an empty frame and selects it", () => {
    const id = useEditorStore.getState().addObjectFrame(10, 20);
    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(1);
    expect(s.net.objects![0].id).toBe(id);
    expect(s.selection).toEqual([{ id, kind: "object" }]);
  });

  it("existing nets with no frames behave identically (ownerOf is always undefined)", () => {
    useEditorStore.getState().addPlace(0, 0);
    useEditorStore.getState().addTransition(50, 0);
    const s = useEditorStore.getState();
    const p = s.net.places[0];
    const t = s.net.transitions[0];
    const created = useEditorStore.getState().addArc(p.id, t.id);
    expect(created).not.toBeNull();
    expect(useEditorStore.getState().net.arcs).toHaveLength(1);
  });

  it("groupSelectionIntoObject requires a place/transition selection", () => {
    const result = useEditorStore.getState().groupSelectionIntoObject();
    expect(result).toBeNull();
  });

  it("groupSelectionIntoObject assigns objectId and sizes the frame", () => {
    const pid = useEditorStore.getState().addPlace(100, 100);
    useEditorStore.getState().setSelection([{ id: pid, kind: "place" }]);
    const objId = useEditorStore.getState().groupSelectionIntoObject("MyObject");
    expect(objId).not.toBeNull();
    const s = useEditorStore.getState();
    const place = s.net.places.find((p) => p.id === pid)!;
    expect(place.objectId).toBe(objId);
    expect(s.net.objects!.find((o) => o.id === objId)!.name).toBe("MyObject");
  });

  it("groupSelectionIntoObject converts a boundary-crossing arc into an ObjectLink instead of dropping it", () => {
    const pid = useEditorStore.getState().addPlace(0, 0);
    const tid = useEditorStore.getState().addTransition(100, 0);
    useEditorStore.getState().addArc(pid, tid);
    expect(useEditorStore.getState().net.arcs).toHaveLength(1);

    // Group only the place — the arc to the (still free) transition now crosses a boundary.
    useEditorStore.getState().setSelection([{ id: pid, kind: "place" }]);
    useEditorStore.getState().groupSelectionIntoObject();

    const s = useEditorStore.getState();
    expect(s.net.arcs).toHaveLength(0); // not silently dropped, converted
    expect(s.net.links).toHaveLength(1);
    expect(s.net.links![0].type).toBe("placeToTransition");
    expect(s.net.links![0].sourceId).toBe(pid);
    expect(s.net.links![0].targetId).toBe(tid);
  });

  it("moveObject shifts the frame and every member by the same delta", () => {
    const objId = useEditorStore.getState().addObjectFrame(0, 0, 200, 200);
    const pid = useEditorStore.getState().addPlace(20, 20);
    useEditorStore.getState().addElementToObject(pid, "place", objId);

    // Taking on a member re-fits the frame, so read the post-fit origin rather
    // than assuming the one addObjectFrame was called with.
    const before = useEditorStore.getState();
    const origin = before.net.objects!.find((o) => o.id === objId)!.graphics;
    const placeBefore = before.net.places.find((p) => p.id === pid)!.graphics;

    useEditorStore.getState().moveObject(objId, 50, 60);

    const s = useEditorStore.getState();
    const frame = s.net.objects!.find((o) => o.id === objId)!;
    const place = s.net.places.find((p) => p.id === pid)!;
    expect(frame.graphics.x).toBe(50);
    expect(frame.graphics.y).toBe(60);
    expect(place.graphics.x).toBe(placeBefore.x + (50 - origin.x));
    expect(place.graphics.y).toBe(placeBefore.y + (60 - origin.y));
  });

  it("deleteObject with default keepContents frees members instead of deleting them", () => {
    const objId = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(10, 10);
    useEditorStore.getState().addElementToObject(pid, "place", objId);

    useEditorStore.getState().deleteObject(objId);

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places).toHaveLength(1);
    expect(s.net.places[0].objectId).toBeUndefined();
  });

  it("deleteObject with keepContents:false removes members, their arcs and touching links", () => {
    const objId = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(10, 10);
    const tid = useEditorStore.getState().addTransition(200, 10);
    useEditorStore.getState().addElementToObject(pid, "place", objId);
    useEditorStore.getState().addArc(pid, tid); // rejected: different owners (place framed, transition free)
    expect(useEditorStore.getState().net.arcs).toHaveLength(0);

    useEditorStore.getState().addObjectLink("placeToTransition", pid, tid);
    expect(useEditorStore.getState().net.links).toHaveLength(1);

    useEditorStore.getState().deleteObject(objId, { keepContents: false });

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places).toHaveLength(0);
    expect(s.net.links).toHaveLength(0);
    expect(s.net.transitions).toHaveLength(1); // the free transition survives
  });

  it("removeElementFromObject converts a now-boundary-crossing place->transition arc into a synthesized fusion instead of leaving it dangling", () => {
    const objId = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(10, 10);
    const tid = useEditorStore.getState().addTransition(100, 10);
    useEditorStore.getState().addElementToObject(pid, "place", objId);
    useEditorStore.getState().addElementToObject(tid, "transition", objId);
    useEditorStore.getState().addArc(pid, tid);
    expect(useEditorStore.getState().net.arcs).toHaveLength(1);
    expect(useEditorStore.getState().net.places).toHaveLength(1);

    // Removing only the place from the object leaves the transition framed
    // and the place free — the arc between them now crosses a boundary. No
    // placeToTransition link exists any more (retired, matching
    // PetriObjModelPaint): a local proxy place is synthesized inside the
    // transition's own object, wired to it with a fresh local arc, and
    // fused back to the place that lost its membership.
    useEditorStore.getState().removeElementFromObject(pid);

    const s = useEditorStore.getState();
    expect(s.net.arcs).toHaveLength(1); // the synthesized local arc, not the old one
    expect(s.net.arcs[0].source_id).not.toBe(pid); // it's the proxy place, not pid
    expect(s.net.arcs[0].target_id).toBe(tid);
    expect(s.net.places).toHaveLength(2); // pid plus the synthesized proxy
    expect(s.net.links).toHaveLength(1);
    expect(s.net.links![0].type).toBe("placeFusion");
    // pid is the master (the real place, holds the marking); the proxy is
    // the copy, so storage direction (copy -> master) puts the proxy first.
    expect(s.net.links![0].sourceId).toBe(s.net.arcs[0].source_id);
    expect(s.net.links![0].targetId).toBe(pid);
  });

  it("addObjectFrame avoids colliding with a place/transition id from an externally-loaded net", () => {
    useEditorStore.getState().setNet({
      name: "external",
      places: [
        {
          id: "o1",
          name: "o1",
          tokens: 0,
          graphics: { x: 0, y: 0 },
        },
      ],
      transitions: [],
      arcs: [],
    });

    const frameId = useEditorStore.getState().addObjectFrame(0, 0);

    expect(frameId).not.toBe("o1");
    const s = useEditorStore.getState();
    const ids = [
      ...s.net.places.map((p) => p.id),
      ...s.net.transitions.map((t) => t.id),
      ...s.net.objects!.map((o) => o.id),
    ];
    expect(new Set(ids).size).toBe(ids.length); // no duplicate node ids
  });

  it("deleteSelection removing a frame takes its contents with it", () => {
    const objId = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(10, 10);
    const outside = useEditorStore.getState().addPlace(400, 10);
    useEditorStore.getState().addElementToObject(pid, "place", objId);

    useEditorStore.getState().setSelection([{ id: objId, kind: "object" }]);
    useEditorStore.getState().deleteSelection();

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places.map((p) => p.id)).toEqual([outside]);
  });

  it("deleteElement on a frame takes its contents with it too", () => {
    const objId = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(10, 10);
    useEditorStore.getState().addElementToObject(pid, "place", objId);

    useEditorStore.getState().deleteElement({ id: objId, kind: "object" });

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places).toHaveLength(0);
  });

  it("ungroupObject is the way to drop the frame but keep its members", () => {
    const objId = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(10, 10);
    useEditorStore.getState().addElementToObject(pid, "place", objId);

    useEditorStore.getState().ungroupObject(objId);

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places).toHaveLength(1);
    expect(s.net.places[0].objectId).toBeUndefined();
  });
});

describe("editor-store object links", () => {
  beforeEach(resetStore);

  function twoFramedPlaces() {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0);
    const o2 = useEditorStore.getState().addObjectFrame(300, 0);
    const p1 = useEditorStore.getState().addPlace(10, 10);
    const p2 = useEditorStore.getState().addPlace(310, 10);
    useEditorStore.getState().addElementToObject(p1, "place", o1);
    useEditorStore.getState().addElementToObject(p2, "place", o2);
    return { o1, o2, p1, p2 };
  }

  it("addArc refuses to connect elements in different objects", () => {
    const { p1 } = twoFramedPlaces();
    const t1 = useEditorStore.getState().addTransition(500, 500); // free transition
    useEditorStore.getState().addElementToObject(p1, "place", useEditorStore.getState().net.objects![0].id);
    const created = useEditorStore.getState().addArc(p1, t1);
    // p1 belongs to an object, t1 is free (different owner) -> rejected
    expect(created).toBeNull();
  });

  it("addObjectLink creates a placeFusion link between two different objects' places", () => {
    const { p1, p2 } = twoFramedPlaces();
    const id = useEditorStore.getState().addObjectLink("placeFusion", p1, p2);
    expect(id).not.toBeNull();
    const s = useEditorStore.getState();
    expect(s.net.links).toHaveLength(1);
    expect(s.net.links![0].type).toBe("placeFusion");
  });

  it("addObjectLink rejects a placeFusion within the same object", () => {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0);
    const p1 = useEditorStore.getState().addPlace(10, 10);
    const p2 = useEditorStore.getState().addPlace(20, 10);
    useEditorStore.getState().addElementToObject(p1, "place", o1);
    useEditorStore.getState().addElementToObject(p2, "place", o1);
    const id = useEditorStore.getState().addObjectLink("placeFusion", p1, p2);
    expect(id).toBeNull();
  });

  it("addObjectLink rejects a duplicate fusion regardless of endpoint order", () => {
    const { p1, p2 } = twoFramedPlaces();
    useEditorStore.getState().addObjectLink("placeFusion", p1, p2);
    const dup = useEditorStore.getState().addObjectLink("placeFusion", p2, p1);
    expect(dup).toBeNull();
    expect(useEditorStore.getState().net.links).toHaveLength(1);
  });

  it("deleteObjectLink removes the link", () => {
    const { p1, p2 } = twoFramedPlaces();
    const id = useEditorStore.getState().addObjectLink("placeFusion", p1, p2)!;
    useEditorStore.getState().deleteObjectLink(id);
    expect(useEditorStore.getState().net.links).toHaveLength(0);
  });

  it("splitConnector on a connector of one link behaves like deleteObjectLink", () => {
    const { p1, p2 } = twoFramedPlaces();
    const id = useEditorStore.getState().addObjectLink("placeFusion", p1, p2)!;
    useEditorStore.getState().splitConnector(id);
    expect(useEditorStore.getState().net.links).toHaveLength(0);
  });

  it("splitConnector removes every link of the connector, leaves other connectors untouched, one undo step for all of them", () => {
    const { o1, o2, p1, p2 } = twoFramedPlaces();
    const firstLinkId = useEditorStore.getState().addObjectLink("placeFusion", p1, p2)!;
    // Two more places shared between the SAME pair of objects, together with
    // firstLinkId, a connector of three placeFusion links, o1 <-> o2.
    const extraLinkIds = [0, 1].map((i) => {
      const a = useEditorStore.getState().addPlace(10, 40 + i * 40);
      const b = useEditorStore.getState().addPlace(310, 40 + i * 40);
      useEditorStore.getState().addElementToObject(a, "place", o1);
      useEditorStore.getState().addElementToObject(b, "place", o2);
      return useEditorStore.getState().addObjectLink("placeFusion", a, b)!;
    });
    const connectorLinkIds = [firstLinkId, ...extraLinkIds];

    // A DIFFERENT connector: a third object sharing one place with o1. This
    // must survive splitting the (o1, o2) connector untouched.
    const o3 = useEditorStore.getState().addObjectFrame(600, 0);
    const p5 = useEditorStore.getState().addPlace(10, 500);
    const p6 = useEditorStore.getState().addPlace(610, 10);
    useEditorStore.getState().addElementToObject(p5, "place", o1);
    useEditorStore.getState().addElementToObject(p6, "place", o3);
    const unrelatedLinkId = useEditorStore.getState().addObjectLink("placeFusion", p5, p6)!;

    expect(useEditorStore.getState().net.links).toHaveLength(4);

    useEditorStore.getState().splitConnector(connectorLinkIds[1]);

    const after = useEditorStore.getState().net;
    expect(after.links!.map((l) => l.id)).toEqual([unrelatedLinkId]);

    useEditorStore.getState().undo();
    const restored = useEditorStore.getState().net;
    expect(restored.links).toHaveLength(4);
    expect(new Set(restored.links!.map((l) => l.id))).toEqual(
      new Set([...connectorLinkIds, unrelatedLinkId]),
    );
  });

  it("updateObjectLink patches quantity/informational", () => {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0);
    const o2 = useEditorStore.getState().addObjectFrame(300, 0);
    const p1 = useEditorStore.getState().addPlace(10, 10);
    const t2 = useEditorStore.getState().addTransition(310, 10);
    useEditorStore.getState().addElementToObject(p1, "place", o1);
    useEditorStore.getState().addElementToObject(t2, "transition", o2);

    const id = useEditorStore.getState().addObjectLink("placeToTransition", p1, t2)!;
    useEditorStore.getState().updateObjectLink(id, { informational: true, quantity: 3 });

    const link = useEditorStore.getState().net.links!.find((l) => l.id === id)!;
    expect(link.informational).toBe(true);
    expect(link.quantity).toBe(3);
  });

  it("addObjectLink placeFusion adopts the master (target) place's token count", () => {
    const { p1, p2 } = twoFramedPlaces();
    useEditorStore.getState().updatePlace(p1, { tokens: 7 });
    useEditorStore.getState().updatePlace(p2, { tokens: 2 });

    // Storage direction: sourceId is the copy, targetId is the master (see
    // addObjectLink's own doc comment): a caller resolving a drawn gesture
    // flips its own (source, target) order to get here; the store itself
    // never reasons about which end the gesture started from.
    useEditorStore.getState().addObjectLink("placeFusion", p1, p2);

    const s = useEditorStore.getState();
    expect(s.net.places.find((p) => p.id === p1)!.tokens).toBe(2);
    expect(s.net.places.find((p) => p.id === p2)!.tokens).toBe(2);
  });

  it("addObjectLink placeFusion adopts the master's count the other way round too", () => {
    const { p1, p2 } = twoFramedPlaces();
    useEditorStore.getState().updatePlace(p1, { tokens: 7 });
    useEditorStore.getState().updatePlace(p2, { tokens: 2 });

    useEditorStore.getState().addObjectLink("placeFusion", p2, p1); // p1 is now the master (target)

    const s = useEditorStore.getState();
    expect(s.net.places.find((p) => p.id === p1)!.tokens).toBe(7);
    expect(s.net.places.find((p) => p.id === p2)!.tokens).toBe(7);
  });

  it("joining a fusion (link creation + marking adoption) is a single undoable step", () => {
    const { p1, p2 } = twoFramedPlaces();
    useEditorStore.getState().updatePlace(p1, { tokens: 5 }); // p1 is the copy here
    const pastBefore = useEditorStore.getState().past.length;

    useEditorStore.getState().addObjectLink("placeFusion", p1, p2); // p2 is the master, tokens 0
    expect(useEditorStore.getState().past.length).toBe(pastBefore + 1);
    // p1 (the copy) gave up its own count for the master's on join.
    expect(useEditorStore.getState().net.places.find((p) => p.id === p1)!.tokens).toBe(0);

    useEditorStore.getState().undo();
    const s = useEditorStore.getState();
    expect(s.net.links ?? []).toHaveLength(0);
    expect(s.net.places.find((p) => p.id === p1)!.tokens).toBe(5); // marking adoption undone together with the link
    expect(s.net.places.find((p) => p.id === p2)!.tokens).toBe(0);
  });

  it("a fan of three copies from one master is accepted: the desktop's core change from strict 1-to-1", () => {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0); // holds the master
    const o2 = useEditorStore.getState().addObjectFrame(300, 0);
    const o3 = useEditorStore.getState().addObjectFrame(600, 0);
    const o4 = useEditorStore.getState().addObjectFrame(900, 0);
    const master = useEditorStore.getState().addPlace(10, 10);
    const copyA = useEditorStore.getState().addPlace(310, 10);
    const copyB = useEditorStore.getState().addPlace(610, 10);
    const copyC = useEditorStore.getState().addPlace(910, 10);
    useEditorStore.getState().addElementToObject(master, "place", o1);
    useEditorStore.getState().addElementToObject(copyA, "place", o2);
    useEditorStore.getState().addElementToObject(copyB, "place", o3);
    useEditorStore.getState().addElementToObject(copyC, "place", o4);

    const idA = useEditorStore.getState().addObjectLink("placeFusion", copyA, master);
    const idB = useEditorStore.getState().addObjectLink("placeFusion", copyB, master);
    const idC = useEditorStore.getState().addObjectLink("placeFusion", copyC, master);
    expect(idA).not.toBeNull();
    expect(idB).not.toBeNull();
    expect(idC).not.toBeNull();

    const s = useEditorStore.getState();
    expect(s.net.links).toHaveLength(3);
    for (const link of s.net.links!) expect(link.targetId).toBe(master);
  });

  it("addObjectLink refuses a second master for the same copy", () => {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0);
    const o2 = useEditorStore.getState().addObjectFrame(300, 0);
    const o3 = useEditorStore.getState().addObjectFrame(600, 0);
    const copy = useEditorStore.getState().addPlace(10, 10);
    const masterA = useEditorStore.getState().addPlace(310, 10);
    const masterB = useEditorStore.getState().addPlace(610, 10);
    useEditorStore.getState().addElementToObject(copy, "place", o1);
    useEditorStore.getState().addElementToObject(masterA, "place", o2);
    useEditorStore.getState().addElementToObject(masterB, "place", o3);

    useEditorStore.getState().addObjectLink("placeFusion", copy, masterA);
    // copy already repeats masterA: it cannot also repeat masterB, or there
    // would be no saying which marking it holds.
    const second = useEditorStore.getState().addObjectLink("placeFusion", copy, masterB);
    expect(second).toBeNull();

    const s = useEditorStore.getState();
    expect(s.net.links).toHaveLength(1);
  });

  it("addObjectLink refuses a link that would close a loop of copies", () => {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0);
    const o2 = useEditorStore.getState().addObjectFrame(300, 0);
    const o3 = useEditorStore.getState().addObjectFrame(600, 0);
    const a = useEditorStore.getState().addPlace(10, 10);
    const b = useEditorStore.getState().addPlace(310, 10);
    const c = useEditorStore.getState().addPlace(610, 10);
    useEditorStore.getState().addElementToObject(a, "place", o1);
    useEditorStore.getState().addElementToObject(b, "place", o2);
    useEditorStore.getState().addElementToObject(c, "place", o3);

    useEditorStore.getState().addObjectLink("placeFusion", a, b); // a copies b
    useEditorStore.getState().addObjectLink("placeFusion", b, c); // b copies c

    const closesLoop = useEditorStore.getState().addObjectLink("placeFusion", c, a); // c copies a
    expect(closesLoop).toBeNull();
    expect(useEditorStore.getState().net.links).toHaveLength(2);
  });

  it("addObjectLink allows fusing two free (no-object) places", () => {
    const free1 = useEditorStore.getState().addPlace(0, 0);
    const free2 = useEditorStore.getState().addPlace(300, 0);

    const id = useEditorStore.getState().addObjectLink("placeFusion", free1, free2);
    expect(id).not.toBeNull();
    expect(useEditorStore.getState().net.links).toHaveLength(1);
  });

  it("the whole chain adopts the ROOT master's token count, not just the two places just linked", () => {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0);
    const o2 = useEditorStore.getState().addObjectFrame(300, 0);
    const o3 = useEditorStore.getState().addObjectFrame(600, 0);
    const root = useEditorStore.getState().addPlace(10, 10);
    const mid = useEditorStore.getState().addPlace(310, 10);
    const leaf = useEditorStore.getState().addPlace(610, 10);
    useEditorStore.getState().addElementToObject(root, "place", o1);
    useEditorStore.getState().addElementToObject(mid, "place", o2);
    useEditorStore.getState().addElementToObject(leaf, "place", o3);

    useEditorStore.getState().updatePlace(root, { tokens: 9 });
    useEditorStore.getState().updatePlace(mid, { tokens: 4 });
    useEditorStore.getState().updatePlace(leaf, { tokens: 4 });
    // leaf copies mid first, while mid still holds its own separate count:
    // the pair merges at 4, mid not yet linked to the eventual root at all.
    useEditorStore.getState().addObjectLink("placeFusion", leaf, mid);
    expect(useEditorStore.getState().net.places.find((p) => p.id === leaf)!.tokens).toBe(4);

    // Now mid copies root. The merge must reach the WHOLE existing group,
    // leaf included, and adopt root's count, not just overwrite mid.
    useEditorStore.getState().addObjectLink("placeFusion", mid, root);

    const s = useEditorStore.getState();
    expect(s.net.places.find((p) => p.id === root)!.tokens).toBe(9);
    expect(s.net.places.find((p) => p.id === mid)!.tokens).toBe(9);
    expect(s.net.places.find((p) => p.id === leaf)!.tokens).toBe(9);
  });
});

describe("editor-store object frame auto-fit", () => {
  beforeEach(resetStore);

  function framedPlace(x: number, y: number): { objectId: string; placeId: string } {
    const placeId = useEditorStore.getState().addPlace(x, y);
    useEditorStore.getState().setSelection([{ id: placeId, kind: "place" }]);
    const objectId = useEditorStore.getState().groupSelectionIntoObject()!;
    return { objectId, placeId };
  }

  function frameOf(objectId: string) {
    return useEditorStore.getState().net.objects!.find((o) => o.id === objectId)!;
  }

  it("keeps a padding around the member rather than hugging its corner", () => {
    const { objectId, placeId } = framedPlace(200, 200);
    const frame = frameOf(objectId).graphics;
    const place = useEditorStore.getState().net.places.find((p) => p.id === placeId)!;

    expect(frame.x).toBeLessThan(place.graphics.x);
    expect(frame.y).toBeLessThan(place.graphics.y);
    // The whole 56px-wide place fits, with room to spare on the far side.
    expect(frame.x + frame.width).toBeGreaterThan(place.graphics.x + 56);
    expect(frame.y + frame.height).toBeGreaterThan(place.graphics.y + 56);
  });

  it("follows a member as it moves", () => {
    const { objectId, placeId } = framedPlace(200, 200);
    const before = frameOf(objectId).graphics;

    useEditorStore.getState().moveNode(placeId, 500, 200);

    const after = frameOf(objectId).graphics;
    expect(after.x).toBe(before.x + 300);
    expect(after.width).toBe(before.width);
  });

  it("stops following once the user resizes the frame by hand", () => {
    const { objectId, placeId } = framedPlace(200, 200);
    useEditorStore.getState().resizeObject(objectId, 500, 400);
    expect(frameOf(objectId).autoFit).toBe(false);

    const before = frameOf(objectId).graphics;
    useEditorStore.getState().moveNode(placeId, 260, 260);
    expect(frameOf(objectId).graphics).toEqual(before);
  });

  it("enableObjectAutoFit snaps a hand-sized frame back around its members", () => {
    const { objectId } = framedPlace(200, 200);
    useEditorStore.getState().resizeObject(objectId, 900, 700);
    useEditorStore.getState().enableObjectAutoFit(objectId);

    const frame = frameOf(objectId);
    expect(frame.autoFit).toBe(true);
    expect(frame.graphics.width).toBeLessThan(900);
  });

  it("an emptied frame keeps its box instead of collapsing to nothing", () => {
    const { objectId, placeId } = framedPlace(200, 200);
    const before = frameOf(objectId).graphics;
    useEditorStore.getState().removeElementFromObject(placeId);
    expect(frameOf(objectId).graphics).toEqual(before);
  });
});

describe("editor-store addSubnetAsObject", () => {
  beforeEach(resetStore);

  const subnet = {
    places: [{ id: "sp1", name: "In", tokens: 0, graphics: { x: 100, y: 100 } }],
    transitions: [
      {
        id: "st1",
        name: "Step",
        priority: 1,
        distribution: "exp" as const,
        mean_delay: 1,
        standard_deviation: 0,
        probability: null,
        graphics: { x: 200, y: 100 },
      },
    ],
    arcs: [
      { id: "sa1", source_id: "sp1", target_id: "st1", weight: 1, arc_type: "NORMAL" as const },
    ],
  };

  it("drops a template already framed, with every element a member", () => {
    const id = useEditorStore.getState().addSubnetAsObject(subnet, "Generator");
    const s = useEditorStore.getState();

    expect(s.net.objects).toHaveLength(1);
    expect(s.net.objects![0].name).toBe("Generator");
    expect(s.net.places[0].objectId).toBe(id);
    expect(s.net.transitions[0].objectId).toBe(id);
    expect(s.net.arcs).toHaveLength(1);
    expect(s.selection).toEqual([{ id, kind: "object" }]);
  });

  it("is a single undoable step", () => {
    useEditorStore.getState().addSubnetAsObject(subnet, "Generator");
    useEditorStore.getState().undo();

    const s = useEditorStore.getState();
    expect(s.net.objects ?? []).toHaveLength(0);
    expect(s.net.places).toHaveLength(0);
    expect(s.net.arcs).toHaveLength(0);
  });

  it("records the library entry it came from", () => {
    const id = useEditorStore.getState().addSubnetAsObject(subnet, "Generator", {
      templateId: "lib-42",
    });
    expect(useEditorStore.getState().net.objects![0].templateId).toBe("lib-42");
    expect(id).toBeTruthy();
  });

  it("keeps object names unique on the canvas", () => {
    useEditorStore.getState().addSubnetAsObject(subnet, "Generator");
    useEditorStore.getState().addSubnetAsObject(subnet, "Generator");
    const names = useEditorStore.getState().net.objects!.map((o) => o.name);
    expect(new Set(names).size).toBe(2);
  });
});

describe("editor-store ungroupObject", () => {
  beforeEach(resetStore);

  it("dissolves the frame and leaves its members on the canvas", () => {
    const placeId = useEditorStore.getState().addPlace(100, 100);
    useEditorStore.getState().setSelection([{ id: placeId, kind: "place" }]);
    const objectId = useEditorStore.getState().groupSelectionIntoObject()!;

    useEditorStore.getState().ungroupObject(objectId);

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places).toHaveLength(1);
    expect(s.net.places[0].objectId).toBeUndefined();
  });
});

describe("editor-store object duplication and clipboard", () => {
  beforeEach(resetStore);

  /** One object containing place → transition, plus a free place outside it. */
  function objectWithContents(): { objId: string; pid: string; tid: string; outside: string } {
    const pid = useEditorStore.getState().addPlace(100, 100);
    const tid = useEditorStore.getState().addTransition(200, 100);
    useEditorStore.getState().addArc(pid, tid);
    const outside = useEditorStore.getState().addPlace(600, 100);
    useEditorStore.getState().setSelection([
      { id: pid, kind: "place" },
      { id: tid, kind: "transition" },
    ]);
    const objId = useEditorStore.getState().groupSelectionIntoObject("Widget")!;
    return { objId, pid, tid, outside };
  }

  it("duplicateObject copies the frame with its contents and wiring", () => {
    const { objId } = objectWithContents();

    const copyId = useEditorStore.getState().duplicateObject(objId)!;
    const s = useEditorStore.getState();

    expect(copyId).not.toBe(objId);
    expect(s.net.objects).toHaveLength(2);
    const members = [...s.net.places, ...s.net.transitions].filter((e) => e.objectId === copyId);
    expect(members).toHaveLength(2);
    // The copy is wired to itself, not to the original's elements.
    const memberIds = new Set(members.map((m) => m.id));
    const copiedArc = s.net.arcs.find(
      (a) => memberIds.has(a.source_id) && memberIds.has(a.target_id),
    );
    expect(copiedArc).toBeDefined();
    expect(s.net.arcs).toHaveLength(2);
  });

  it("duplicateObject offsets the copy, renames it and selects it", () => {
    const { objId } = objectWithContents();
    const before = useEditorStore.getState().net.objects![0].graphics;

    const copyId = useEditorStore.getState().duplicateObject(objId)!;
    const s = useEditorStore.getState();
    const copy = s.net.objects!.find((o) => o.id === copyId)!;

    expect(copy.graphics.x).toBeGreaterThan(before.x);
    expect(copy.name).not.toBe("Widget");
    expect(s.selection).toEqual([{ id: copyId, kind: "object" }]);
  });

  it("duplicateObject is a single undoable step", () => {
    const { objId } = objectWithContents();
    useEditorStore.getState().duplicateObject(objId);
    useEditorStore.getState().undo();

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(1);
    expect(s.net.places).toHaveLength(2);
  });

  it("copying an object carries its contents to the paste", () => {
    const { objId } = objectWithContents();
    useEditorStore.getState().setSelection([{ id: objId, kind: "object" }]);
    useEditorStore.getState().copySelection();
    useEditorStore.getState().paste();

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(2);
    const pastedId = s.net.objects!.find((o) => o.id !== objId)!.id;
    expect(
      [...s.net.places, ...s.net.transitions].filter((e) => e.objectId === pastedId),
    ).toHaveLength(2);
    expect(s.selection).toEqual([{ id: pastedId, kind: "object" }]);
  });

  it("a member pasted without its object comes out free", () => {
    const { pid } = objectWithContents();
    useEditorStore.getState().setSelection([{ id: pid, kind: "place" }]);
    useEditorStore.getState().copySelection();
    useEditorStore.getState().paste();

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(1);
    const pasted = s.selection[0];
    expect(s.net.places.find((p) => p.id === pasted.id)!.objectId).toBeUndefined();
  });

  it("cut removes the object with its contents and paste brings both back", () => {
    const { objId, outside } = objectWithContents();
    useEditorStore.getState().setSelection([{ id: objId, kind: "object" }]);
    useEditorStore.getState().cutSelection();

    let s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places.map((p) => p.id)).toEqual([outside]);

    useEditorStore.getState().paste();
    s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(1);
    expect([...s.net.places, ...s.net.transitions].filter((e) => e.objectId)).toHaveLength(2);
  });

  it("selectAll reaches objects and links, not just plain elements", () => {
    const { objId } = objectWithContents();
    const other = useEditorStore.getState().addTransition(800, 100);
    const outsidePlace = useEditorStore.getState().net.places.find((p) => !p.objectId)!.id;
    const linkId = useEditorStore
      .getState()
      .addObjectLink("placeToTransition", outsidePlace, other);

    useEditorStore.getState().selectAll();
    const kinds = useEditorStore.getState().selection;

    expect(kinds.some((r) => r.id === objId && r.kind === "object")).toBe(true);
    if (linkId) expect(kinds.some((r) => r.id === linkId && r.kind === "link")).toBe(true);
  });
});

describe("editor-store groupElementsIntoObject", () => {
  beforeEach(resetStore);

  it("frames exactly the given elements, ignoring the current selection", () => {
    const p1 = useEditorStore.getState().addPlace(100, 100);
    const p2 = useEditorStore.getState().addPlace(300, 100);
    useEditorStore.getState().setSelection([{ id: p2, kind: "place" }]);

    const objId = useEditorStore.getState().groupElementsIntoObject([p1])!;

    const s = useEditorStore.getState();
    expect(s.net.places.find((p) => p.id === p1)!.objectId).toBe(objId);
    expect(s.net.places.find((p) => p.id === p2)!.objectId).toBeUndefined();
  });

  it("refuses to create a frame when nothing resolves", () => {
    expect(useEditorStore.getState().groupElementsIntoObject([])).toBeNull();
    expect(useEditorStore.getState().groupElementsIntoObject(["nope"])).toBeNull();
    expect(useEditorStore.getState().net.objects ?? []).toHaveLength(0);
  });

  it("nests two selected object frames as children instead of stealing their members", () => {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0, 200, 150);
    const o2 = useEditorStore.getState().addObjectFrame(400, 0, 200, 150);
    const p1 = useEditorStore.getState().addPlace(20, 20);
    const p2 = useEditorStore.getState().addPlace(420, 20);
    useEditorStore.getState().addElementToObject(p1, "place", o1);
    useEditorStore.getState().addElementToObject(p2, "place", o2);

    const parentId = useEditorStore.getState().groupElementsIntoObject([o1, o2])!;

    const s = useEditorStore.getState();
    // The two original frames became children of the new one...
    expect(s.net.objects!.find((o) => o.id === o1)!.objectId).toBe(parentId);
    expect(s.net.objects!.find((o) => o.id === o2)!.objectId).toBe(parentId);
    // ...and, critically, kept their own members rather than losing them to the new frame.
    expect(s.net.places.find((p) => p.id === p1)!.objectId).toBe(o1);
    expect(s.net.places.find((p) => p.id === p2)!.objectId).toBe(o2);
  });

  it("a marquee-style selection mixing the two frames with their own members still nests correctly", () => {
    // Mirrors what a real marquee band produces: the frame refs plus every
    // element inside them, since a band enclosing a whole frame also
    // encloses its contents.
    const o1 = useEditorStore.getState().addObjectFrame(0, 0, 200, 150);
    const o2 = useEditorStore.getState().addObjectFrame(400, 0, 200, 150);
    const p1 = useEditorStore.getState().addPlace(20, 20);
    const p2 = useEditorStore.getState().addPlace(420, 20);
    useEditorStore.getState().addElementToObject(p1, "place", o1);
    useEditorStore.getState().addElementToObject(p2, "place", o2);

    const parentId = useEditorStore.getState().groupElementsIntoObject([o1, o2, p1, p2])!;

    const s = useEditorStore.getState();
    expect(s.net.objects!.find((o) => o.id === o1)!.objectId).toBe(parentId);
    expect(s.net.objects!.find((o) => o.id === o2)!.objectId).toBe(parentId);
    expect(s.net.places.find((p) => p.id === p1)!.objectId).toBe(o1);
    expect(s.net.places.find((p) => p.id === p2)!.objectId).toBe(o2);
  });
});

describe("editor-store place fusion marking write-through", () => {
  beforeEach(resetStore);

  /** Two places, each in its own object, already fused. */
  function fusedPair() {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0);
    const o2 = useEditorStore.getState().addObjectFrame(300, 0);
    const p1 = useEditorStore.getState().addPlace(10, 10);
    const p2 = useEditorStore.getState().addPlace(310, 10);
    useEditorStore.getState().addElementToObject(p1, "place", o1);
    useEditorStore.getState().addElementToObject(p2, "place", o2);
    useEditorStore.getState().addObjectLink("placeFusion", p1, p2);
    return { p1, p2 };
  }

  it("updatePlace tokens writes through to every member of the fusion group", () => {
    const { p1, p2 } = fusedPair();

    useEditorStore.getState().updatePlace(p2, { tokens: 12 });

    const s = useEditorStore.getState();
    expect(s.net.places.find((p) => p.id === p1)!.tokens).toBe(12);
    expect(s.net.places.find((p) => p.id === p2)!.tokens).toBe(12);
  });

  it("the write-through is part of the same undoable step as the edit", () => {
    const { p1, p2 } = fusedPair();
    const pastBefore = useEditorStore.getState().past.length;

    useEditorStore.getState().updatePlace(p2, { tokens: 12 });
    expect(useEditorStore.getState().past.length).toBe(pastBefore + 1);

    useEditorStore.getState().undo();
    const s = useEditorStore.getState();
    expect(s.net.places.find((p) => p.id === p1)!.tokens).toBe(0);
    expect(s.net.places.find((p) => p.id === p2)!.tokens).toBe(0);
  });

  it("renaming or moving a fused place does not affect its partner", () => {
    const { p1, p2 } = fusedPair();

    useEditorStore.getState().updatePlace(p1, { name: "Renamed" });
    useEditorStore.getState().updatePlace(p1, { graphics: { x: 999, y: 999 } });

    const s = useEditorStore.getState();
    const partner = s.net.places.find((p) => p.id === p2)!;
    expect(partner.name).not.toBe("Renamed");
    expect(partner.graphics).not.toEqual({ x: 999, y: 999 });
  });

  it("updating a place with no fusion partner only touches itself (existing flat-net behavior)", () => {
    const pid = useEditorStore.getState().addPlace(0, 0);
    useEditorStore.getState().updatePlace(pid, { tokens: 4 });
    expect(useEditorStore.getState().net.places).toHaveLength(1);
    expect(useEditorStore.getState().net.places[0].tokens).toBe(4);
  });
});

describe("editor-store deleteSelection confines edits to what's locally editable", () => {
  beforeEach(resetStore);

  it("a member of a top-level object, visible only because the object is expanded, is skipped", () => {
    const oid = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(10, 10);
    useEditorStore.getState().addElementToObject(pid, "place", oid);

    useEditorStore.getState().setSelection([{ id: pid, kind: "place" }]);
    useEditorStore.getState().deleteSelection();

    const s = useEditorStore.getState();
    expect(s.net.places.some((p) => p.id === pid)).toBe(true);
  });

  it("a nested child frame, visible only because its parent is expanded, is skipped — even though it's a frame, same as a top-level one is deletable", () => {
    const outer = useEditorStore.getState().addObjectFrame(0, 0, 300, 300);
    const inner = useEditorStore
      .getState()
      .addObjectFrame(20, 20, 100, 100, { parentId: outer });

    useEditorStore.getState().setSelection([{ id: inner, kind: "object" }]);
    useEditorStore.getState().deleteSelection();

    expect(useEditorStore.getState().net.objects!.some((o) => o.id === inner)).toBe(true);
  });

  it("a top-level object is still deletable, taking its own nested contents with it as always", () => {
    const outer = useEditorStore.getState().addObjectFrame(0, 0, 300, 300);
    const inner = useEditorStore
      .getState()
      .addObjectFrame(20, 20, 100, 100, { parentId: outer });

    useEditorStore.getState().setSelection([{ id: outer, kind: "object" }]);
    useEditorStore.getState().deleteSelection();

    const s = useEditorStore.getState();
    expect(s.net.objects!.some((o) => o.id === outer || o.id === inner)).toBe(false);
  });

  it("a link stays deletable regardless of which side it's clicked from — it crosses a boundary by definition", () => {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0);
    const o2 = useEditorStore.getState().addObjectFrame(300, 0);
    const p1 = useEditorStore.getState().addPlace(10, 10);
    const p2 = useEditorStore.getState().addPlace(310, 10);
    useEditorStore.getState().addElementToObject(p1, "place", o1);
    useEditorStore.getState().addElementToObject(p2, "place", o2);
    const linkId = useEditorStore.getState().addObjectLink("placeFusion", p1, p2)!;

    useEditorStore.getState().setSelection([{ id: linkId, kind: "link" }]);
    useEditorStore.getState().deleteSelection();

    expect(useEditorStore.getState().net.links ?? []).toHaveLength(0);
  });

  it("a mixed selection deletes only what's local, leaving the rest of the selection untouched", () => {
    const oid = useEditorStore.getState().addObjectFrame(0, 0);
    const framedPid = useEditorStore.getState().addPlace(10, 10);
    useEditorStore.getState().addElementToObject(framedPid, "place", oid);
    const freePid = useEditorStore.getState().addPlace(200, 10);

    useEditorStore.getState().setSelection([
      { id: framedPid, kind: "place" },
      { id: freePid, kind: "place" },
    ]);
    useEditorStore.getState().deleteSelection();

    const s = useEditorStore.getState();
    expect(s.net.places.some((p) => p.id === framedPid)).toBe(true);
    expect(s.net.places.some((p) => p.id === freePid)).toBe(false);
  });
});

describe("editor-store nested object cascade delete", () => {
  beforeEach(resetStore);

  /** o1 (outer, holds p1) with o2 nested inside it (holds p2, t2, wired p2->t2). */
  function nestedObjectNet(): PetriNetData {
    return {
      name: "nested",
      objects: [
        { id: "o1", name: "Outer", priority: 0, graphics: { x: 0, y: 0, width: 300, height: 300 } },
        {
          id: "o2",
          name: "Inner",
          priority: 0,
          graphics: { x: 20, y: 20, width: 100, height: 100 },
          objectId: "o1",
        },
      ],
      places: [
        { id: "p1", name: "p1", tokens: 0, graphics: { x: 10, y: 10 }, objectId: "o1" },
        { id: "p2", name: "p2", tokens: 0, graphics: { x: 30, y: 30 }, objectId: "o2" },
      ],
      transitions: [
        {
          id: "t2",
          name: "t2",
          priority: 1,
          distribution: "exp",
          mean_delay: 1,
          standard_deviation: 0,
          probability: null,
          graphics: { x: 50, y: 50 },
          objectId: "o2",
        },
      ],
      arcs: [{ id: "a1", source_id: "p2", target_id: "t2", weight: 1, arc_type: "NORMAL" }],
      links: [],
    };
  }

  it("deleteObject keepContents:false removes the whole nested subtree, not just direct members", () => {
    useEditorStore.getState().setNet(nestedObjectNet());

    useEditorStore.getState().deleteObject("o1", { keepContents: false });

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0); // o1 AND the nested o2
    expect(s.net.places).toHaveLength(0); // p1 AND p2
    expect(s.net.transitions).toHaveLength(0); // t2
    expect(s.net.arcs).toHaveLength(0); // a1
  });

  it("deleteObject keepContents:false also drops a link touching a nested member, and spares free elements", () => {
    const net = nestedObjectNet();
    net.places.push({ id: "p3", name: "p3", tokens: 0, graphics: { x: 500, y: 500 } }); // free
    // Valid at creation time: p3 is free, t2 belongs to the nested o2 — different owners.
    net.links = [{ id: "link1", type: "placeToTransition", sourceId: "p3", targetId: "t2", quantity: 1 }];
    useEditorStore.getState().setNet(net);

    useEditorStore.getState().deleteObject("o1", { keepContents: false });

    const s = useEditorStore.getState();
    expect(s.net.links).toHaveLength(0);
    expect(s.net.places.map((p) => p.id)).toEqual(["p3"]); // the free place survives
  });

  it("is a single undoable step", () => {
    useEditorStore.getState().setNet(nestedObjectNet());
    const pastBefore = useEditorStore.getState().past.length;

    useEditorStore.getState().deleteObject("o1", { keepContents: false });
    expect(useEditorStore.getState().past.length).toBe(pastBefore + 1);

    useEditorStore.getState().undo();
    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(2);
    expect(s.net.places).toHaveLength(2);
  });

  it("deleteSelection removing a frame cascades through its nested subtree too", () => {
    useEditorStore.getState().setNet(nestedObjectNet());
    useEditorStore.getState().setSelection([{ id: "o1", kind: "object" }]);

    useEditorStore.getState().deleteSelection();

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places).toHaveLength(0);
    expect(s.net.transitions).toHaveLength(0);
    expect(s.net.arcs).toHaveLength(0);
  });
});

describe("editor-store link reconciliation on membership change", () => {
  beforeEach(resetStore);

  it("ungroupObject drops a placeFusion that becomes invalid once its other half is freed too", () => {
    const free = useEditorStore.getState().addPlace(0, 0);
    const o1 = useEditorStore.getState().addObjectFrame(300, 0);
    const framed = useEditorStore.getState().addPlace(310, 10);
    useEditorStore.getState().addElementToObject(framed, "place", o1);
    // Valid at creation: free is unowned, framed belongs to o1 — different owners.
    useEditorStore.getState().addObjectLink("placeFusion", free, framed);
    expect(useEditorStore.getState().net.links).toHaveLength(1);

    useEditorStore.getState().ungroupObject(o1);

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places.find((p) => p.id === framed)!.objectId).toBeUndefined();
    // Both places are free now — the fusion no longer connects two different
    // objects, so it's dropped instead of left dangling.
    expect(s.net.links).toHaveLength(0);
  });

  it("ungroupObject converts a directional link into a plain arc once both endpoints share an owner", () => {
    const freeTransition = useEditorStore.getState().addTransition(0, 0);
    const o1 = useEditorStore.getState().addObjectFrame(300, 0);
    const framedPlace = useEditorStore.getState().addPlace(310, 10);
    useEditorStore.getState().addElementToObject(framedPlace, "place", o1);
    const linkId = useEditorStore
      .getState()
      .addObjectLink("transitionToPlace", freeTransition, framedPlace, { quantity: 5 });
    expect(linkId).not.toBeNull();

    useEditorStore.getState().ungroupObject(o1);

    const s = useEditorStore.getState();
    expect(s.net.links).toHaveLength(0);
    expect(s.net.arcs).toHaveLength(1);
    expect(s.net.arcs[0]).toMatchObject({
      source_id: freeTransition,
      target_id: framedPlace,
      weight: 5,
      arc_type: "NORMAL",
    });
  });

  it("removeElementFromObject drops a fusion link that becomes invalid once the element is freed", () => {
    const free = useEditorStore.getState().addPlace(0, 0);
    const o1 = useEditorStore.getState().addObjectFrame(300, 0);
    const framed = useEditorStore.getState().addPlace(310, 10);
    useEditorStore.getState().addElementToObject(framed, "place", o1);
    useEditorStore.getState().addObjectLink("placeFusion", free, framed);

    useEditorStore.getState().removeElementFromObject(framed);

    const s = useEditorStore.getState();
    expect(s.net.places.find((p) => p.id === framed)!.objectId).toBeUndefined();
    expect(s.net.links).toHaveLength(0);
  });

  it("removeElementFromObject converts a directional link into a plain arc (informational -> READ)", () => {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0);
    const framedTransition = useEditorStore.getState().addTransition(10, 10);
    const freePlace = useEditorStore.getState().addPlace(300, 10);
    useEditorStore.getState().addElementToObject(framedTransition, "transition", o1);
    useEditorStore.getState().addObjectLink("placeToTransition", freePlace, framedTransition, {
      quantity: 2,
      informational: true,
    });

    useEditorStore.getState().removeElementFromObject(framedTransition);

    const s = useEditorStore.getState();
    expect(s.net.links).toHaveLength(0);
    expect(s.net.arcs).toHaveLength(1);
    expect(s.net.arcs[0]).toMatchObject({
      source_id: freePlace,
      target_id: framedTransition,
      weight: 2,
      arc_type: "READ",
    });
  });

  it("link reconciliation is folded into the same undoable step as the membership change", () => {
    const free = useEditorStore.getState().addPlace(0, 0);
    const o1 = useEditorStore.getState().addObjectFrame(300, 0);
    const framed = useEditorStore.getState().addPlace(310, 10);
    useEditorStore.getState().addElementToObject(framed, "place", o1);
    useEditorStore.getState().addObjectLink("placeFusion", free, framed);
    const pastBefore = useEditorStore.getState().past.length;

    useEditorStore.getState().removeElementFromObject(framed);
    expect(useEditorStore.getState().past.length).toBe(pastBefore + 1);

    useEditorStore.getState().undo();
    expect(useEditorStore.getState().net.links).toHaveLength(1);
  });
});

describe("editor-store copy/paste and duplicate preserve object links", () => {
  beforeEach(resetStore);

  it("copy+paste of a fused pair keeps the fusion between the copies, not pointing back at the originals", () => {
    const o1 = useEditorStore.getState().addObjectFrame(0, 0);
    const o2 = useEditorStore.getState().addObjectFrame(300, 0);
    const p1 = useEditorStore.getState().addPlace(10, 10);
    const p2 = useEditorStore.getState().addPlace(310, 10);
    useEditorStore.getState().addElementToObject(p1, "place", o1);
    useEditorStore.getState().addElementToObject(p2, "place", o2);
    useEditorStore.getState().addObjectLink("placeFusion", p1, p2);

    // Select the whole group (both objects) the way the user would to copy
    // a fused pair together, then copy+paste it.
    useEditorStore.getState().setSelection([
      { id: o1, kind: "object" },
      { id: o2, kind: "object" },
    ]);
    useEditorStore.getState().copySelection();
    useEditorStore.getState().paste();

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(4); // 2 originals + 2 copies
    expect(s.net.links).toHaveLength(2); // the original fusion + the pasted copy's own

    const copiedObjectIds = new Set(
      s.net.objects!.filter((o) => o.id !== o1 && o.id !== o2).map((o) => o.id),
    );
    const copiedPlaceIds = new Set(
      s.net.places.filter((p) => p.objectId && copiedObjectIds.has(p.objectId)).map((p) => p.id),
    );
    expect(copiedPlaceIds.size).toBe(2);

    const pastedLink = s.net.links!.find(
      (l) => copiedPlaceIds.has(l.sourceId) && copiedPlaceIds.has(l.targetId),
    );
    expect(pastedLink).toBeDefined();

    const originalLink = s.net.links!.find((l) => l.sourceId === p1 && l.targetId === p2);
    expect(originalLink).toBeDefined(); // the original fusion is untouched
  });

  it("duplicateObject copies a nested child object's frame and its members, re-parented to the new outer copy", () => {
    const net: PetriNetData = {
      name: "nested",
      objects: [
        { id: "o1", name: "Outer", priority: 0, graphics: { x: 0, y: 0, width: 300, height: 300 } },
        {
          id: "o2",
          name: "Inner",
          priority: 0,
          graphics: { x: 20, y: 20, width: 100, height: 100 },
          objectId: "o1",
        },
      ],
      places: [
        { id: "p1", name: "p1", tokens: 0, graphics: { x: 10, y: 10 }, objectId: "o1" },
        { id: "p2", name: "p2", tokens: 0, graphics: { x: 30, y: 30 }, objectId: "o2" },
      ],
      transitions: [],
      arcs: [],
      links: [],
    };
    useEditorStore.getState().setNet(net);

    const copyOuterId = useEditorStore.getState().duplicateObject("o1")!;

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(4); // o1, o2 + their copies
    const copyInner = s.net.objects!.find((o) => o.objectId === copyOuterId);
    expect(copyInner).toBeDefined();
    expect(copyInner!.id).not.toBe("o2"); // a fresh frame, not the original nested child

    const copiedPlaces = s.net.places.filter(
      (p) => p.objectId === copyOuterId || p.objectId === copyInner!.id,
    );
    expect(copiedPlaces).toHaveLength(2); // both p1's and p2's copies came along
  });
});

describe("editor-store addElementGroup (composed import merge)", () => {
  beforeEach(resetStore);

  it("appends frames, members, arcs and links as one undoable step at their own coordinates", () => {
    const store = useEditorStore.getState();
    store.addPlace(500, 500); // pre-existing content the merge must not disturb

    const group = {
      objects: [
        { id: "io1", name: "A", priority: 0, graphics: { x: 40, y: 40, width: 200, height: 160 } },
        { id: "io2", name: "B", priority: 0, graphics: { x: 300, y: 40, width: 200, height: 160 } },
      ],
      places: [
        { id: "ip1", name: "P1", tokens: 2, graphics: { x: 80, y: 100 }, objectId: "io1" },
        { id: "ip2", name: "P2", tokens: 2, graphics: { x: 340, y: 100 }, objectId: "io2" },
      ],
      transitions: [],
      arcs: [],
      links: [
        { id: "il1", type: "placeFusion" as const, sourceId: "ip1", targetId: "ip2", quantity: 1 },
      ],
    };
    useEditorStore.getState().addElementGroup(group);

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(2);
    expect(s.net.links).toHaveLength(1);
    // Absolute coordinates land untouched: no drop-point math, no re-centring.
    expect(s.net.objects![0].graphics).toMatchObject({ x: 40, y: 40 });
    expect(s.net.places.find((p) => p.id === "ip1")!.graphics).toEqual({ x: 80, y: 100 });

    useEditorStore.getState().undo();
    const after = useEditorStore.getState().net;
    expect(after.objects ?? []).toHaveLength(0);
    expect(after.links ?? []).toHaveLength(0);
    expect(after.places).toHaveLength(1); // the pre-existing place survived the undo
  });
});

describe("editor-store creating elements inside a frame", () => {
  beforeEach(resetStore);

  it("addPlace with objectId creates the place as a member in one undo step", () => {
    const frameId = useEditorStore.getState().addObjectFrame(0, 0, 300, 200);
    const placeId = useEditorStore.getState().addPlace(60, 80, { objectId: frameId });

    const s = useEditorStore.getState();
    expect(s.net.places.find((p) => p.id === placeId)!.objectId).toBe(frameId);

    useEditorStore.getState().undo();
    const after = useEditorStore.getState().net;
    expect(after.places).toHaveLength(0);
    expect(after.objects).toHaveLength(1); // only the creation went, not the frame
  });

  it("addTransition with objectId joins the frame; addObjectFrame with parentId nests", () => {
    const outerId = useEditorStore.getState().addObjectFrame(0, 0, 400, 300);
    const tId = useEditorStore.getState().addTransition(50, 60, { objectId: outerId });
    const innerId = useEditorStore
      .getState()
      .addObjectFrame(120, 90, 150, 100, { parentId: outerId });

    const s = useEditorStore.getState();
    expect(s.net.transitions.find((t) => t.id === tId)!.objectId).toBe(outerId);
    expect(s.net.objects!.find((o) => o.id === innerId)!.objectId).toBe(outerId);
  });
});

describe("editor-store grouping nests inside the owning frame", () => {
  beforeEach(resetStore);

  function frameWithTwoMembers() {
    const store = useEditorStore.getState();
    const outerId = store.addObjectFrame(0, 0, 400, 300);
    const pId = useEditorStore.getState().addPlace(60, 80, { objectId: outerId });
    const tId = useEditorStore.getState().addTransition(160, 80, { objectId: outerId });
    return { outerId, pId, tId };
  }

  it("grouping members of one frame creates a nested child, one undo step", () => {
    const { outerId, pId, tId } = frameWithTwoMembers();

    const childId = useEditorStore.getState().groupElementsIntoObject([pId, tId])!;

    const s = useEditorStore.getState();
    const child = s.net.objects!.find((o) => o.id === childId)!;
    expect(child.objectId).toBe(outerId);
    expect(s.net.places.find((p) => p.id === pId)!.objectId).toBe(childId);
    expect(s.net.transitions.find((t) => t.id === tId)!.objectId).toBe(childId);

    // The parent grew around the child's padding rather than clipping it.
    const outer = s.net.objects!.find((o) => o.id === outerId)!;
    expect(outer.graphics.x).toBeLessThanOrEqual(child.graphics.x);
    expect(outer.graphics.y).toBeLessThanOrEqual(child.graphics.y);

    useEditorStore.getState().undo();
    const after = useEditorStore.getState().net;
    expect(after.objects).toHaveLength(1);
    expect(after.places[0].objectId).toBe(outerId);
  });

  it("grouping elements from two different frames stays top-level", () => {
    const store = useEditorStore.getState();
    const aId = store.addObjectFrame(0, 0, 200, 150);
    const bId = useEditorStore.getState().addObjectFrame(300, 0, 200, 150);
    const pA = useEditorStore.getState().addPlace(40, 60, { objectId: aId });
    const pB = useEditorStore.getState().addPlace(340, 60, { objectId: bId });

    const groupedId = useEditorStore.getState().groupElementsIntoObject([pA, pB])!;
    const grouped = useEditorStore.getState().net.objects!.find((o) => o.id === groupedId)!;
    expect(grouped.objectId).toBeUndefined();
  });

  it("an explicit parent hint nests free elements drawn inside a frame", () => {
    const store = useEditorStore.getState();
    const outerId = store.addObjectFrame(0, 0, 400, 300);
    const freeId = useEditorStore.getState().addPlace(100, 100); // free, merely drawn over

    const childId = useEditorStore
      .getState()
      .groupElementsIntoObject([freeId], undefined, { parentId: outerId })!;

    const child = useEditorStore.getState().net.objects!.find((o) => o.id === childId)!;
    expect(child.objectId).toBe(outerId);
  });
});

describe("editor-store moveObject carries the nested subtree", () => {
  beforeEach(resetStore);

  it("moving a parent frame moves child frames and their members by the same delta", () => {
    const outerId = useEditorStore.getState().addObjectFrame(0, 0, 400, 300);
    const pOuter = useEditorStore.getState().addPlace(40, 60, { objectId: outerId });
    const childId = useEditorStore
      .getState()
      .addObjectFrame(150, 100, 180, 120, { parentId: outerId });
    const pInner = useEditorStore.getState().addPlace(190, 150, { objectId: childId });

    // Auto-fit already re-boxed both frames around their members; the
    // invariant under test is the DELTA, not any absolute geometry.
    const frameOf = (fid: string) =>
      useEditorStore.getState().net.objects!.find((o) => o.id === fid)!.graphics;
    const childBefore = { ...frameOf(childId) };
    const outerBefore = { ...frameOf(outerId) };

    useEditorStore.getState().moveObject(outerId, outerBefore.x + 100, outerBefore.y + 50);

    const s = useEditorStore.getState().net;
    expect(frameOf(childId)).toMatchObject({ x: childBefore.x + 100, y: childBefore.y + 50 });
    expect(s.places.find((p) => p.id === pOuter)!.graphics).toEqual({ x: 140, y: 110 });
    expect(s.places.find((p) => p.id === pInner)!.graphics).toEqual({ x: 290, y: 200 });

    useEditorStore.getState().undo();
    const after = useEditorStore.getState().net;
    expect(frameOf(childId)).toMatchObject({ x: childBefore.x, y: childBefore.y });
    expect(after.places.find((p) => p.id === pInner)!.graphics).toEqual({ x: 190, y: 150 });
  });
});

describe("editor-store moveManyTo commits a whole gesture as one undo step", () => {
  beforeEach(resetStore);

  it("moves a frame subtree and explicit element targets together, undone in one step", () => {
    const outerId = useEditorStore.getState().addObjectFrame(0, 0, 400, 300);
    const pIn = useEditorStore.getState().addPlace(60, 80, { objectId: outerId });
    const pFree = useEditorStore.getState().addPlace(600, 80);
    const frameBefore = useEditorStore
      .getState()
      .net.objects!.find((o) => o.id === outerId)!.graphics;
    const pastLen = useEditorStore.getState().past.length;

    // The canvas hands absolute FINAL targets: the member's target already
    // includes the frame's shift, whatever order the entries arrive in.
    useEditorStore.getState().moveManyTo([
      { id: pIn, kind: "element", x: 160, y: 130 },
      { id: outerId, kind: "object", x: frameBefore.x + 100, y: frameBefore.y + 50 },
      { id: pFree, kind: "element", x: 700, y: 90 },
    ]);

    const s = useEditorStore.getState();
    expect(s.past.length).toBe(pastLen + 1);
    expect(s.net.places.find((p) => p.id === pFree)!.graphics).toEqual({ x: 700, y: 90 });
    const frameAfter = s.net.objects!.find((o) => o.id === outerId)!.graphics;
    expect(frameAfter.x).toBeCloseTo(frameBefore.x + 100);

    useEditorStore.getState().undo();
    const after = useEditorStore.getState().net;
    expect(after.places.find((p) => p.id === pFree)!.graphics).toEqual({ x: 600, y: 80 });
    expect(after.places.find((p) => p.id === pIn)!.graphics).toEqual({ x: 60, y: 80 });
  });

  it("a member arriving before its frame is not double-shifted", () => {
    const outerId = useEditorStore.getState().addObjectFrame(0, 0, 400, 300);
    const pIn = useEditorStore.getState().addPlace(60, 80, { objectId: outerId });
    const frameBefore = useEditorStore
      .getState()
      .net.objects!.find((o) => o.id === outerId)!.graphics;

    // Whole-selection drag by +100/+50: the element's FINAL spot is 160/130.
    useEditorStore.getState().moveManyTo([
      { id: pIn, kind: "element", x: 160, y: 130 },
      { id: outerId, kind: "object", x: frameBefore.x + 100, y: frameBefore.y + 50 },
    ]);
    // The subtree shift lands the member at 160/130 too, so the explicit
    // target and the shift agree instead of stacking.
    expect(useEditorStore.getState().net.places.find((p) => p.id === pIn)!.graphics)
      .toEqual({ x: 160, y: 130 });
  });
});

describe("editor-store membership changes convert stale links to arcs", () => {
  beforeEach(resetStore);

  it("grouping both endpoints of a directional link into one frame makes it an arc", () => {
    const s = useEditorStore.getState();
    const oA = s.addObjectFrame(0, 0, 200, 150);
    const oB = useEditorStore.getState().addObjectFrame(400, 0, 200, 150);
    const p = useEditorStore.getState().addPlace(40, 60, { objectId: oA });
    const t = useEditorStore.getState().addTransition(440, 60, { objectId: oB });
    const linkId = useEditorStore.getState().addObjectLink("placeToTransition", p, t, { quantity: 2 })!;
    expect(linkId).toBeTruthy();

    // Both endpoints end up in one new frame: the link is a local flow now.
    useEditorStore.getState().groupElementsIntoObject([p, t]);

    const net = useEditorStore.getState().net;
    expect((net.links ?? []).find((l) => l.id === linkId)).toBeUndefined();
    const arc = net.arcs.find((a) => a.source_id === p && a.target_id === t);
    expect(arc).toBeDefined();
    expect(arc!.weight).toBe(2);
  });

  it("drag-adopting a link partner into the other endpoint's frame converts too", () => {
    const s = useEditorStore.getState();
    const oA = s.addObjectFrame(0, 0, 300, 200);
    const t = useEditorStore.getState().addTransition(40, 60, { objectId: oA });
    const p = useEditorStore.getState().addPlace(500, 60); // free
    useEditorStore.getState().addObjectLink("transitionToPlace", t, p, { quantity: 1 });

    useEditorStore.getState().addElementToObject(p, "place", oA);

    const net = useEditorStore.getState().net;
    expect(net.links ?? []).toHaveLength(0);
    expect(net.arcs.some((a) => a.source_id === t && a.target_id === p)).toBe(true);
  });
});

describe("library round trip keeps the nested structure", () => {
  beforeEach(resetStore);

  it("extract, instantiate and drop reproduce nested frames, links and arcs", async () => {
    const { extractObjectAsTemplate } = await import("@/lib/petri-object-model");
    const { instantiateTemplate } = await import("@/lib/petri-object-instantiate");

    // Original: outer object with one member transition, a nested child with
    // a place, an arc inside the child, and a link crossing outer->child.
    const s = useEditorStore.getState();
    const outerId = s.addObjectFrame(0, 0, 400, 300);
    const tOuter = useEditorStore.getState().addTransition(40, 60, { objectId: outerId });
    const childId = useEditorStore
      .getState()
      .addObjectFrame(150, 100, 180, 140, { parentId: outerId });
    const pChild = useEditorStore.getState().addPlace(190, 150, { objectId: childId });
    const tChild = useEditorStore.getState().addTransition(260, 150, { objectId: childId });
    useEditorStore.getState().addArc(pChild, tChild);
    useEditorStore.getState().addObjectLink("transitionToPlace", tOuter, pChild);

    const net = useEditorStore.getState().net;
    const template = extractObjectAsTemplate(net, outerId)!;
    expect(template.objects).toHaveLength(1);
    expect(template.links).toHaveLength(1);
    expect(template.places).toHaveLength(1);
    expect(template.transitions).toHaveLength(2);
    expect(template.arcs).toHaveLength(1);

    // Drop it onto a fresh canvas like the palette does.
    useEditorStore.getState().resetNet();
    const subnet = instantiateTemplate(
      { name: "Tpl", ...template },
      500,
      500,
      useEditorStore.getState().net,
    );
    const wrapperId = useEditorStore.getState().addSubnetAsObject(subnet, "Copy");

    const after = useEditorStore.getState().net;
    expect(after.objects).toHaveLength(2);
    const wrapper = after.objects!.find((o) => o.id === wrapperId)!;
    const nested = after.objects!.find((o) => o.id !== wrapperId)!;
    expect(nested.objectId).toBe(wrapperId);

    const nestedMembers = [...after.places, ...after.transitions].filter(
      (e) => e.objectId === nested.id,
    );
    expect(nestedMembers).toHaveLength(2);
    expect(after.arcs).toHaveLength(1);
    expect(after.links ?? []).toHaveLength(1);
    const link = after.links![0];
    // The link's endpoints are the COPIES, wired outer->child like the original.
    const tOuterCopy = after.transitions.find((t) => t.objectId === wrapperId)!;
    expect(link.sourceId).toBe(tOuterCopy.id);
    expect(nestedMembers.map((m) => m.id)).toContain(link.targetId);
    void wrapper;
  });
});

describe("drawing a Petri-object band around an existing object", () => {
  beforeEach(resetStore);

  /** What EditorCanvas does on pointerup with the object tool, minus React. */
  function drawBand(band: { minX: number; minY: number; maxX: number; maxY: number }) {
    const net = useEditorStore.getState().net;
    const { parentId, capturedIds } = resolveObjectBand(net, band);
    if (capturedIds.length > 0) {
      return useEditorStore
        .getState()
        .groupElementsIntoObject(capturedIds, undefined, parentId ? { parentId } : undefined);
    }
    return useEditorStore
      .getState()
      .addObjectFrame(
        band.minX,
        band.minY,
        Math.max(FRAME_MIN_W, band.maxX - band.minX),
        Math.max(FRAME_MIN_H, band.maxY - band.minY),
        parentId ? { parentId } : undefined,
      );
  }

  /** A band dragged generously around one frame, the way the user draws it. */
  function bandAround(id: string, margin = 40) {
    const g = (useEditorStore.getState().net.objects ?? []).find((o) => o.id === id)!.graphics;
    return {
      minX: g.x - margin,
      minY: g.y - margin,
      maxX: g.x + g.width + margin,
      maxY: g.y + g.height + margin,
    };
  }

  /** Ancestors from a frame upward. Throws rather than spinning on a cycle. */
  function parentChain(id: string) {
    const objects = useEditorStore.getState().net.objects ?? [];
    const chain: string[] = [];
    let current: string | undefined = id;
    while (current) {
      if (chain.includes(current)) {
        throw new Error(`parent cycle: ${[...chain, current].join(" -> ")}`);
      }
      chain.push(current);
      if (chain.length > 20) throw new Error("parent chain runs away");
      current = objects.find((o) => o.id === current)?.objectId;
    }
    return chain;
  }

  const frameOf = (id: string) =>
    (useEditorStore.getState().net.objects ?? []).find((o) => o.id === id)!;

  it("wraps the object instead of nesting a new one inside it", () => {
    const pid = useEditorStore.getState().addPlace(200, 200);
    const inner = drawBand({ minX: 150, minY: 150, maxX: 400, maxY: 400 })!;
    const outer = drawBand(bandAround(inner))!;

    expect(outer).not.toBe(inner);
    // place -> inner -> outer, and nothing above the outer frame.
    expect(useEditorStore.getState().net.places.find((p) => p.id === pid)!.objectId).toBe(inner);
    expect(frameOf(inner).objectId).toBe(outer);
    expect(frameOf(outer).objectId).toBeUndefined();
  });

  it("names the objects in creation order: the wrapper is the newer name", () => {
    useEditorStore.getState().addPlace(200, 200);
    const inner = drawBand({ minX: 150, minY: 150, maxX: 400, maxY: 400 })!;
    const outer = drawBand(bandAround(inner))!;

    // The user's report was "the names swapped places": the new frame used to
    // land INSIDE the old one, so the outer box carried the older name.
    expect(frameOf(inner).name).toBe("Object_1");
    expect(frameOf(outer).name).toBe("Object_2");
  });

  it("survives a third level: no parent cycle, no runaway", () => {
    const pid = useEditorStore.getState().addPlace(200, 200);
    const l1 = drawBand({ minX: 150, minY: 150, maxX: 400, maxY: 400 })!;
    const l2 = drawBand(bandAround(l1))!;
    const l3 = drawBand(bandAround(l2))!;

    expect(parentChain(l1)).toEqual([l1, l2, l3]);
    expect(frameOf(l3).objectId).toBeUndefined();
    expect(useEditorStore.getState().net.places.find((p) => p.id === pid)!.objectId).toBe(l1);
    expect(objectLevel(useEditorStore.getState().net, l1)).toBe(3);
  });

  it("a band drawn INSIDE an object still builds a nested child there", () => {
    const outer = useEditorStore.getState().addObjectFrame(0, 0, 600, 600);
    const pid = useEditorStore.getState().addPlace(200, 200, { objectId: outer });
    const inner = drawBand({ minX: 150, minY: 150, maxX: 350, maxY: 350 })!;

    expect(inner).not.toBe(outer);
    expect(frameOf(inner).objectId).toBe(outer);
    expect(useEditorStore.getState().net.places.find((p) => p.id === pid)!.objectId).toBe(inner);
  });

  it("groupElementsIntoObject refuses a parent it is about to swallow", () => {
    // Called directly with a parentId naming a frame inside the very object
    // being grouped: the shape that used to close the cycle.
    useEditorStore.getState().addPlace(200, 200);
    const l1 = drawBand({ minX: 150, minY: 150, maxX: 400, maxY: 400 })!;
    const l2 = drawBand(bandAround(l1))!;

    const l3 = useEditorStore.getState().groupElementsIntoObject([l2], undefined, { parentId: l1 })!;
    expect(frameOf(l3).objectId).toBeUndefined();
    expect(parentChain(l1)).toEqual([l1, l2, l3]);
  });
});
