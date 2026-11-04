import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PetriNetData } from "@/types/petri";
import { cloneElements } from "@/lib/petri-object-model";
import { instantiateTemplate } from "@/lib/petri-object-instantiate";
import { settleNewObjectName, useEditorStore } from "./editor-store";
import { useNameConflictStore, type DuplicateNamePolicy } from "./name-conflict-store";

const editor = () => useEditorStore.getState();
const conflicts = () => useNameConflictStore.getState();

function setup(policy: DuplicateNamePolicy) {
  useNameConflictStore.setState({ policy, pending: null });
  localStorage.clear();
  editor().resetNet();
}

function everyName(net: PetriNetData): string[] {
  return [
    ...(net.objects ?? []).map((o) => o.name),
    ...net.places.map((p) => p.name),
    ...net.transitions.map((t) => t.name),
  ];
}

/** One object holding a place and a transition. */
function oneObject() {
  const object = editor().addObjectFrame(0, 0);
  const place = editor().addPlace(20, 40, { objectId: object });
  const transition = editor().addTransition(120, 40, { objectId: object });
  return { object, place, transition };
}

function nameOf(id: string): string {
  const net = editor().net;
  return (
    net.places.find((p) => p.id === id)?.name ??
    net.transitions.find((t) => t.id === id)?.name ??
    net.objects?.find((o) => o.id === id)?.name ??
    ""
  );
}

describe("names are unique across places, transitions and objects", () => {
  beforeEach(() => setup("auto"));

  it("default names skip a name another kind already holds", () => {
    const place = editor().addPlace(0, 0);
    // A transition squatting on the next place name.
    const transition = editor().addTransition(50, 0);
    editor().renameElement(transition, "Place_2");
    expect(nameOf(place)).toBe("Place_1");

    const next = editor().addPlace(100, 0);
    expect(nameOf(next)).toBe("Place_3");
  });

  it("duplicating an object leaves every name on the canvas distinct", () => {
    const { object } = oneObject();
    editor().duplicateObject(object);
    const names = everyName(editor().net);
    expect(names).toHaveLength(6);
    expect(new Set(names).size).toBe(6);
  });

  it("pasting a place whose name a transition holds renames the copy", () => {
    const place = editor().addPlace(0, 0);
    const transition = editor().addTransition(50, 0);
    // Build the clash the way an old file would have it: allowed once, then
    // back to the default policy for the paste itself.
    useNameConflictStore.setState({ policy: "keep" });
    editor().renameElement(transition, "Work");
    editor().renameElement(place, "Work");
    useNameConflictStore.setState({ policy: "auto" });
    expect(everyName(editor().net)).toEqual(["Work", "Work"]);

    editor().setSelection([{ id: transition, kind: "transition" }]);
    editor().copySelection();
    editor().paste();

    const pasted = editor().net.transitions.find((t) => t.id !== transition)!;
    expect(pasted.name).toBe("Work_2");
  });

  it("shared places keep ONE name in the copy, and a new one", () => {
    const a = editor().addObjectFrame(0, 0);
    const b = editor().addObjectFrame(400, 0);
    const pa = editor().addPlace(20, 40, { objectId: a });
    const pb = editor().addPlace(420, 40, { objectId: b });
    editor().renameElement(pa, "Hand_off");
    // Fused places may share a name, so this is allowed without a warning.
    editor().addObjectLink("placeFusion", pb, pa);
    editor().renameElement(pb, "Hand_off");
    expect(nameOf(pa)).toBe("Hand_off");
    expect(nameOf(pb)).toBe("Hand_off");

    editor().setSelection([
      { id: a, kind: "object" },
      { id: b, kind: "object" },
    ]);
    editor().copySelection();
    editor().paste();

    const net = editor().net;
    const copies = net.places.filter((p) => p.id !== pa && p.id !== pb);
    expect(copies).toHaveLength(2);
    expect(copies.map((p) => p.name)).toEqual(["Hand_off_2", "Hand_off_2"]);
    // The originals are untouched, and the other pairs do not repeat them.
    expect(nameOf(pa)).toBe("Hand_off");
    expect(nameOf(pb)).toBe("Hand_off");
  });
});

describe("import keeps names exactly as they are", () => {
  beforeEach(() => setup("ask"));

  it("a composed import repeats names without asking, whatever the policy", () => {
    const { object } = oneObject();
    const net = editor().net;
    const imported = {
      objects: net.objects ?? [],
      places: net.places,
      transitions: net.transitions,
      arcs: net.arcs,
      links: net.links ?? [],
    };
    const copy = cloneElements(net, imported, { x: 0, y: 0 });
    expect(copy.objects[0].name).toBe(net.objects![0].name);
    expect(copy.places[0].name).toBe(net.places[0].name);
    expect(copy.transitions[0].name).toBe(net.transitions[0].name);

    editor().addElementGroup(copy);
    expect(conflicts().pending).toBeNull();
    expect(editor().net.places.map((p) => p.name)).toEqual(["Place_1", "Place_1"]);
    expect(object).toBeTruthy();
  });
});

describe("policy: ask", () => {
  beforeEach(() => setup("ask"));

  it("duplicating parks the copy behind a warning and adds nothing yet", () => {
    const { object } = oneObject();
    editor().duplicateObject(object);

    expect(editor().net.objects).toHaveLength(1);
    const pending = conflicts().pending;
    expect(pending).not.toBeNull();
    expect(pending!.conflicts.map((c) => c.name).sort()).toEqual(["Object_1", "Place_1", "T_1"]);
  });

  it("'pick automatically' lands the copy with free names", () => {
    const { object } = oneObject();
    editor().duplicateObject(object);
    conflicts().answer("auto");

    expect(conflicts().pending).toBeNull();
    const names = everyName(editor().net);
    expect(names).toHaveLength(6);
    expect(new Set(names).size).toBe(6);
  });

  it("a typed name is used for that row, the rest are picked", () => {
    const { object } = oneObject();
    editor().duplicateObject(object);
    const row = conflicts().pending!.conflicts.find((c) => c.name === "Place_1")!;
    conflicts().answer({ rename: new Map([[row.ids[0], "Buffer"]]) });

    expect(editor().net.places.map((p) => p.name)).toContain("Buffer");
  });

  it("'keep' lands the copy with the same names", () => {
    const { object } = oneObject();
    editor().duplicateObject(object);
    conflicts().answer("keep");

    expect(editor().net.places.map((p) => p.name)).toEqual(["Place_1", "Place_1"]);
  });

  it("cancel adds nothing and does not touch the policy, even with remember", () => {
    const { object } = oneObject();
    editor().duplicateObject(object);
    conflicts().answer("cancel", true);

    expect(editor().net.objects).toHaveLength(1);
    expect(editor().net.places).toHaveLength(1);
    expect(conflicts().policy).toBe("ask");
  });

  it("remembering 'pick automatically' stops the warning for the next one", () => {
    const { object } = oneObject();
    editor().duplicateObject(object);
    conflicts().answer("auto", true);
    expect(conflicts().policy).toBe("auto");
    expect(localStorage.getItem("petri-net-sim-duplicate-name-policy")).toBe('"auto"');

    editor().duplicateObject(object);
    expect(conflicts().pending).toBeNull();
    expect(editor().net.objects).toHaveLength(3);
  });

  it("remembering 'keep duplicate' is saved too", () => {
    const { object } = oneObject();
    editor().duplicateObject(object);
    conflicts().answer("keep", true);
    expect(conflicts().policy).toBe("keep");
    expect(localStorage.getItem("petri-net-sim-duplicate-name-policy")).toBe('"keep"');
  });

  it("answering without remember leaves the policy as it was", () => {
    const { object } = oneObject();
    editor().duplicateObject(object);
    conflicts().answer("auto", false);
    expect(conflicts().policy).toBe("ask");
  });

  it("a paste waits for the answer and lands as one undoable step", () => {
    const place = editor().addPlace(0, 0);
    editor().setSelection([{ id: place, kind: "place" }]);
    editor().copySelection();
    const before = editor().past.length;

    editor().paste();
    expect(editor().net.places).toHaveLength(1);
    expect(editor().past.length).toBe(before);

    conflicts().answer("auto");
    expect(editor().net.places.map((p) => p.name)).toEqual(["Place_1", "Place_2"]);
    expect(editor().past.length).toBe(before + 1);

    editor().undo();
    expect(editor().net.places).toHaveLength(1);
  });

  it("dropping a template object warns about its names too", () => {
    const first = instantiateTemplate(
      {
        name: "Tpl",
        places: [{ id: "p", name: "Queue", tokens: 0, graphics: { x: 0, y: 0 } }],
        transitions: [],
        arcs: [],
        interface: { input_place_id: null, output_place_id: null },
      },
      0,
      0,
    );
    editor().addSubnetAsObject(first, "Tpl");
    expect(conflicts().pending).toBeNull();
    expect(editor().net.places.map((p) => p.name)).toEqual(["Queue"]);

    editor().addSubnetAsObject(
      instantiateTemplate(
        {
          name: "Tpl",
          places: [{ id: "p", name: "Queue", tokens: 0, graphics: { x: 0, y: 0 } }],
          transitions: [],
          arcs: [],
          interface: { input_place_id: null, output_place_id: null },
        },
        500,
        0,
      ),
      "Tpl",
    );
    expect(conflicts().pending!.conflicts.map((c) => c.name).sort()).toEqual(["Queue", "Tpl"]);
    conflicts().answer("auto");
    expect(editor().net.places.map((p) => p.name)).toEqual(["Queue", "Queue_2"]);
    expect(editor().net.objects!.map((o) => o.name)).toEqual(["Tpl", "Tpl_2"]);
  });
});

describe("policy: auto and keep", () => {
  it("auto never shows the warning", () => {
    setup("auto");
    const { object } = oneObject();
    editor().duplicateObject(object);
    expect(conflicts().pending).toBeNull();
    expect(editor().net.objects).toHaveLength(2);
  });

  it("keep never shows the warning and repeats the names", () => {
    setup("keep");
    const { object } = oneObject();
    editor().duplicateObject(object);
    expect(conflicts().pending).toBeNull();
    expect(editor().net.objects!.map((o) => o.name)).toEqual(["Object_1", "Object_1"]);
  });
});

describe("renaming by hand", () => {
  it("applies a free name directly under every policy", () => {
    for (const policy of ["ask", "auto", "keep"] as const) {
      setup(policy);
      const place = editor().addPlace(0, 0);
      expect(editor().renameElement(place, "Fresh")).toBe(true);
      expect(nameOf(place)).toBe("Fresh");
      expect(conflicts().pending).toBeNull();
    }
  });

  it("ask: a taken name opens the warning with a suggestion and changes nothing yet", () => {
    setup("ask");
    const a = editor().addPlace(0, 0);
    const b = editor().addPlace(50, 0);
    expect(editor().renameElement(b, nameOf(a))).toBe(false);

    expect(nameOf(b)).toBe("Place_2");
    const [row] = conflicts().pending!.conflicts;
    // The element being renamed gives up its old name, so Place_2 is free again.
    expect(row).toMatchObject({ name: "Place_1", suggestion: "Place_2", kind: "place" });
  });

  it("ask: the typed replacement is applied", () => {
    setup("ask");
    const a = editor().addPlace(0, 0);
    const b = editor().addPlace(50, 0);
    editor().renameElement(b, nameOf(a));
    conflicts().answer({ rename: new Map([[b, "Buffer"]]) });
    expect(nameOf(b)).toBe("Buffer");
  });

  it("ask: cancel leaves the old name", () => {
    setup("ask");
    const a = editor().addPlace(0, 0);
    const b = editor().addPlace(50, 0);
    editor().renameElement(b, nameOf(a));
    conflicts().answer("cancel");
    expect(nameOf(b)).toBe("Place_2");
  });

  it("auto: a taken name becomes name_2 silently, across kinds", () => {
    setup("auto");
    const place = editor().addPlace(0, 0);
    const transition = editor().addTransition(50, 0);
    expect(editor().renameElement(transition, nameOf(place))).toBe(true);
    expect(nameOf(transition)).toBe("Place_2");
    expect(conflicts().pending).toBeNull();
  });

  it("keep: the duplicate is allowed", () => {
    setup("keep");
    const a = editor().addPlace(0, 0);
    const b = editor().addPlace(50, 0);
    editor().renameElement(b, nameOf(a));
    expect(nameOf(b)).toBe("Place_1");
  });

  it("a fused place can take its partner's name without any warning", () => {
    setup("ask");
    const a = editor().addObjectFrame(0, 0);
    const b = editor().addObjectFrame(400, 0);
    const pa = editor().addPlace(20, 40, { objectId: a });
    const pb = editor().addPlace(420, 40, { objectId: b });
    editor().addObjectLink("placeFusion", pb, pa);

    expect(editor().renameElement(pb, nameOf(pa))).toBe(true);
    expect(conflicts().pending).toBeNull();
    expect(nameOf(pb)).toBe(nameOf(pa));
  });

  it("returns false for an id that is not on the canvas", () => {
    setup("ask");
    expect(editor().renameElement("nope", "X")).toBe(false);
  });

  it("renames object frames through the same check", () => {
    setup("auto");
    const a = editor().addObjectFrame(0, 0);
    const b = editor().addObjectFrame(300, 0);
    editor().renameElement(b, nameOf(a));
    // b was Object_2 and gave that name up, so it is the first free one.
    expect(nameOf(b)).toBe("Object_2");
  });
});

describe("naming a new object", () => {
  it("auto: hands back a free name", () => {
    setup("auto");
    editor().addPlace(0, 0);
    const proceed = vi.fn();
    settleNewObjectName("Place_1", proceed);
    expect(proceed).toHaveBeenCalledWith("Place_2");
  });

  it("a free name goes straight through", () => {
    setup("ask");
    const proceed = vi.fn();
    settleNewObjectName("Line", proceed);
    expect(proceed).toHaveBeenCalledWith("Line");
    expect(conflicts().pending).toBeNull();
  });

  it("ask: waits for the answer, and cancel never proceeds", () => {
    setup("ask");
    editor().addPlace(0, 0);
    const proceed = vi.fn();
    settleNewObjectName("Place_1", proceed);
    expect(proceed).not.toHaveBeenCalled();
    conflicts().answer("cancel");
    expect(proceed).not.toHaveBeenCalled();
  });

  it("ask: a typed name is passed on", () => {
    setup("ask");
    const place = editor().addPlace(0, 0);
    const proceed = vi.fn();
    settleNewObjectName(nameOf(place), proceed);
    const row = conflicts().pending!.conflicts[0];
    conflicts().answer({ rename: new Map([[row.ids[0], "Line"]]) });
    expect(proceed).toHaveBeenCalledWith("Line");
  });
});

describe("saved policy", () => {
  it("an unknown stored value falls back to asking", async () => {
    localStorage.setItem("petri-net-sim-duplicate-name-policy", '"sometimes"');
    vi.resetModules();
    const fresh = await import("./name-conflict-store");
    expect(fresh.useNameConflictStore.getState().policy).toBe("ask");
  });

  it("a stored value is read back", async () => {
    localStorage.setItem("petri-net-sim-duplicate-name-policy", '"keep"');
    vi.resetModules();
    const fresh = await import("./name-conflict-store");
    expect(fresh.useNameConflictStore.getState().policy).toBe("keep");
  });

  it("a second request while one is open cancels the first instead of dropping it", () => {
    setup("ask");
    const first = vi.fn();
    const second = vi.fn();
    const row = { ids: ["a"], kind: "place" as const, name: "X", suggestion: "X_2" };
    conflicts().resolve([row], new Set(["X"]), first);
    conflicts().resolve([row], new Set(["X"]), second);
    expect(first).toHaveBeenCalledWith({ kind: "cancel" });
    expect(second).not.toHaveBeenCalled();
  });
});
