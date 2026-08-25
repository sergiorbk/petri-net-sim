import { beforeEach, describe, expect, it } from "vitest";
import { PLACE_H, PLACE_W, TRANS_H } from "@/lib/petri-geometry";
import { useEditorStore } from "./editor-store";

function resetStore() {
  useEditorStore.getState().resetNet();
}

// eraseAt/eraseInBand didn't exist before the eraser tool (desktop #56, #58)
// was ported, so every test in this file fails against that prior code
// simply because the methods aren't there to call.
describe("editor-store eraseInBand (sweep)", () => {
  beforeEach(resetStore);

  it("erases everything the band catches as one undo step", () => {
    const p1 = useEditorStore.getState().addPlace(0, 0);
    const p2 = useEditorStore.getState().addPlace(100, 0);
    const pastBefore = useEditorStore.getState().past.length;

    useEditorStore.getState().eraseInBand({ minX: -50, minY: -50, maxX: 200, maxY: 100 });

    const s = useEditorStore.getState();
    expect(s.net.places).toHaveLength(0);
    expect(s.past.length).toBe(pastBefore + 1);

    useEditorStore.getState().undo();
    const undone = useEditorStore.getState();
    expect(undone.net.places.map((p) => p.id).sort()).toEqual([p1, p2].sort());
  });

  it("does nothing, and pushes no undo step, when the band catches nothing", () => {
    useEditorStore.getState().addPlace(0, 0);
    const pastBefore = useEditorStore.getState().past.length;

    useEditorStore.getState().eraseInBand({ minX: 5000, minY: 5000, maxX: 5100, maxY: 5100 });

    const s = useEditorStore.getState();
    expect(s.net.places).toHaveLength(1);
    expect(s.past.length).toBe(pastBefore);
  });

  it("erasing an object takes its members, arcs and links with it", () => {
    const oid = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(10, 10);
    const tid = useEditorStore.getState().addTransition(80, 10);
    useEditorStore.getState().addElementToObject(pid, "place", oid);
    useEditorStore.getState().addElementToObject(tid, "transition", oid);
    const arcId = useEditorStore.getState().addArc(pid, tid);
    expect(arcId).not.toBeNull();

    const outsidePlace = useEditorStore.getState().addPlace(500, 500);
    const linkId = useEditorStore.getState().addObjectLink("placeFusion", outsidePlace, pid);
    expect(linkId).not.toBeNull();

    // Sweep a band around the frame's actual (auto-fit) bounds, wide enough
    // to swallow it whole: resolveEraserBand only takes an object frame
    // when the band fully encloses it, the same rule the select-box marquee
    // uses.
    const frame = useEditorStore.getState().net.objects!.find((o) => o.id === oid)!;
    const pastBefore = useEditorStore.getState().past.length;
    useEditorStore.getState().eraseInBand({
      minX: frame.graphics.x - 10,
      minY: frame.graphics.y - 10,
      maxX: frame.graphics.x + frame.graphics.width + 10,
      maxY: frame.graphics.y + frame.graphics.height + 10,
    });

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places.some((p) => p.id === pid)).toBe(false);
    expect(s.net.transitions.some((t) => t.id === tid)).toBe(false);
    expect(s.net.arcs).toHaveLength(0);
    expect(s.net.links ?? []).toHaveLength(0);
    // The free place outside the frame is untouched: deleting an object
    // takes its own subtree, not everything a dangling link once reached.
    expect(s.net.places.some((p) => p.id === outsidePlace)).toBe(true);
    expect(s.past.length).toBe(pastBefore + 1);
  });

  it("does not reach into a foreign object's member from the root canvas, even when the band lands exactly on it", () => {
    const oid = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(10, 10);
    useEditorStore.getState().addElementToObject(pid, "place", oid);

    const place = useEditorStore.getState().net.places.find((p) => p.id === pid)!;
    const cx = place.graphics.x + PLACE_W / 2;
    const cy = place.graphics.y + PLACE_H / 2;
    // A tiny band right on the member's own centre, nowhere near swallowing
    // the frame around it whole, so this is a plain "member" catch, not an
    // "object" catch, and the scope rule applies to it.
    useEditorStore.getState().eraseInBand({ minX: cx - 2, minY: cy - 2, maxX: cx + 2, maxY: cy + 2 });

    const s = useEditorStore.getState();
    expect(s.net.places.some((p) => p.id === pid)).toBe(true);
    expect(s.net.objects).toHaveLength(1);
  });
});

describe("editor-store eraseAt (click)", () => {
  beforeEach(resetStore);

  it("erases the nearest reachable element, up to the fixed screen-pixel reach", () => {
    // A place and a transition whose centres share a y-coordinate (graphics.y
    // offset by -H/2 each), so the arc between them is a flat line straight
    // through the origin: 5 canvas units from a click 5 units off that
    // line, past the arc's own hit corridor but within eraserReachUnits(1) = 6.
    const p1 = useEditorStore.getState().addPlace(-300, -PLACE_H / 2);
    const t1 = useEditorStore.getState().addTransition(300, -TRANS_H / 2);
    const arcId = useEditorStore.getState().addArc(p1, t1);
    expect(arcId).not.toBeNull();

    useEditorStore.getState().eraseAt({ x: 0, y: 5 }, 1);

    expect(useEditorStore.getState().net.arcs).toHaveLength(0);
  });

  it("does nothing when nothing is within reach", () => {
    useEditorStore.getState().addPlace(5000, 5000);
    useEditorStore.getState().eraseAt({ x: 0, y: 0 }, 1);
    expect(useEditorStore.getState().net.places).toHaveLength(1);
  });

  it("a whole Petri-object is erased without a confirmation prompt, click or sweep", () => {
    const oid = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(10, 10);
    useEditorStore.getState().addElementToObject(pid, "place", oid);

    // Click near the frame's own top-right corner, well clear of its one
    // member's box (which auto-fit built the frame around, near the
    // top-left): a click on the frame's own body, not on anything inside it.
    const frame = useEditorStore.getState().net.objects!.find((o) => o.id === oid)!;
    useEditorStore.getState().eraseAt(
      { x: frame.graphics.x + frame.graphics.width - 2, y: frame.graphics.y + 2 },
      1,
    );

    const s = useEditorStore.getState();
    expect(s.net.objects).toHaveLength(0);
    expect(s.net.places).toHaveLength(0);
  });

  it("does not reach into a foreign object's member, even when the pointer lands exactly on it", () => {
    const oid = useEditorStore.getState().addObjectFrame(0, 0);
    const pid = useEditorStore.getState().addPlace(0, 0);
    useEditorStore.getState().addElementToObject(pid, "place", oid);

    // Dead centre of the member's own box, well inside it, so the fixed
    // reach never escapes to something the eraser IS allowed to erase.
    useEditorStore.getState().eraseAt({ x: PLACE_W / 2, y: PLACE_H / 2 }, 1);

    const s = useEditorStore.getState();
    expect(s.net.places.some((p) => p.id === pid)).toBe(true);
    expect(s.net.objects).toHaveLength(1);
  });
});
