import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ComposedSimulateBody } from "@/lib/composed-simulation-client";
import { STREAM_ENDED_EARLY } from "@/lib/simulation-client";
import type { PetriNetData, SimulationSnapshot } from "@/types/petri";
import { useSimulationStore } from "./simulation-store";
import { useEditorStore } from "./editor-store";
import { useStatisticsStore } from "./statistics-store";

// ── Fake network ─────────────────────────────────────────────────────────────

let calls: { url: string; init: RequestInit }[] = [];
let reply: (url: string) => Response = () => {
  throw new Error("no reply configured for this test");
};
let realFetch: typeof globalThis.fetch;

const encoder = new TextEncoder();

function frames(...bodies: string[]): string {
  return bodies.map((body) => `data: ${body}\n\n`).join("");
}

/** An SSE response whose whole text arrives in one chunk, so runs terminate. */
function sse(...bodies: string[]): Response {
  let sent = false;
  const reader = {
    read: async () => {
      if (sent) return { done: true, value: undefined };
      sent = true;
      return { done: false, value: encoder.encode(frames(...bodies)) };
    },
    releaseLock: () => {},
  };
  return { ok: true, body: { getReader: () => reader } } as unknown as Response;
}

/**
 * An SSE response that stalls between the two chunks until `gate` resolves and
 * keeps delivering afterwards regardless of the abort signal — a cancelled run
 * has to prove it drops what arrives late, not that fetch was polite about it.
 */
function gatedSse(first: string[], gate: Promise<void>, rest: string[]): Response {
  let index = 0;
  const reader = {
    read: async () => {
      if (index === 0) {
        index++;
        return { done: false, value: encoder.encode(frames(...first)) };
      }
      if (index === 1) {
        index++;
        await gate;
        return { done: false, value: encoder.encode(frames(...rest)) };
      }
      return { done: true, value: undefined };
    },
    releaseLock: () => {},
  };
  return { ok: true, body: { getReader: () => reader } } as unknown as Response;
}

function precompute(snapshots: SimulationSnapshot[]): Response {
  return {
    ok: true,
    json: async () => ({ snapshots, total: snapshots.length }),
  } as unknown as Response;
}

function openGate(): { gate: Promise<void>; release: () => void } {
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { gate, release };
}

/** Waits for a condition the fake network reaches on its own microtask chain. */
async function until(condition: () => boolean): Promise<void> {
  for (let i = 0; i < 200; i++) {
    if (condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error("condition was never reached");
}

// ── Fixtures ─────────────────────────────────────────────────────────────────

function place(id: string, tokens = 0, objectId?: string) {
  return { id, name: id, tokens, graphics: { x: 0, y: 0 }, ...(objectId ? { objectId } : {}) };
}

function transition(id: string, objectId?: string) {
  return {
    id,
    name: id,
    priority: 1,
    distribution: "exp" as const,
    mean_delay: 1,
    standard_deviation: 0,
    probability: null,
    graphics: { x: 0, y: 0 },
    ...(objectId ? { objectId } : {}),
  };
}

function arc(id: string, source_id: string, target_id: string) {
  return { id, source_id, target_id, weight: 1, arc_type: "NORMAL" as const };
}

/** Two objects of different priority sharing one place through a fusion. */
function composedNet(): PetriNetData {
  return {
    name: "composed",
    places: [place("p1", 1, "oA"), place("p2", 0, "oA"), place("p3", 0, "oB")],
    transitions: [transition("t1", "oA"), transition("t2", "oB")],
    arcs: [arc("a1", "p1", "t1"), arc("a2", "t1", "p2"), arc("a3", "p3", "t2")],
    objects: [
      { id: "oA", name: "A", priority: 0, graphics: { x: 0, y: 0, width: 10, height: 10 } },
      { id: "oB", name: "B", priority: 2, graphics: { x: 0, y: 0, width: 10, height: 10 } },
    ],
    links: [{ id: "fusion1", type: "placeFusion", sourceId: "p2", targetId: "p3", quantity: 1 }],
  };
}

/** One object frame drawn round an ordinary net, with nothing to link it to. */
function framedNet(): PetriNetData {
  return {
    name: "framed",
    places: [place("p1", 1, "oA"), place("p2", 0, "oA")],
    transitions: [transition("t1", "oA")],
    arcs: [arc("a1", "p1", "t1"), arc("a2", "t1", "p2")],
    objects: [
      { id: "oA", name: "A", priority: 3, graphics: { x: 0, y: 0, width: 10, height: 10 } },
    ],
  };
}

function flatNet(): PetriNetData {
  return {
    name: "flat",
    places: [place("q1", 1), place("q2"), place("q3")],
    transitions: [transition("u1")],
    arcs: [arc("b1", "q1", "u1"), arc("b2", "u1", "q2")],
  };
}

function snapshotFrame(
  markings: Record<string, number>,
  extra: Partial<SimulationSnapshot> = {},
): string {
  return JSON.stringify({
    current_time: 1,
    step_number: 1,
    markings,
    buffers: {},
    progress: 0.5,
    ...extra,
  });
}

function expectNoFlatEngine() {
  for (const call of calls) {
    expect(call.url.startsWith("/api/v1/simulate?")).toBe(false);
    expect(call.url.startsWith("/api/v1/simulate/precompute")).toBe(false);
  }
}

function composedBody(): ComposedSimulateBody & { net_data?: unknown } {
  return JSON.parse(calls[0].init.body as string);
}

// ── Suite ────────────────────────────────────────────────────────────────────

describe("simulation-store engine choice", () => {
  beforeEach(async () => {
    realFetch = globalThis.fetch;
    globalThis.fetch = ((input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      calls.push({ url, init });
      return Promise.resolve(reply(url));
    }) as typeof globalThis.fetch;
    calls = [];

    await useSimulationStore.getState().exitSimulationMode();
    // The seven persisted prefs survive in localStorage across tests, so the
    // request bytes are pinned here rather than trusted to the declared defaults.
    useSimulationStore.setState({
      status: "idle",
      error: null,
      progress: 0,
      currentSnapshot: null,
      previousSnapshot: null,
      stepIndex: null,
      snapshotCount: 0,
      editorMode: "edit",
      simulationTime: 10,
      timeStep: 1,
      playbackRate: 60,
      snapshotInterval: 100,
      snapshotMode: "time",
    });
    useEditorStore.getState().resetNet();
    useStatisticsStore.getState().reset();
  });

  afterEach(async () => {
    await useSimulationStore.getState().exitSimulationMode();
    globalThis.fetch = realFetch;
  });

  it("runs a composed model on petri-server in stepped mode instead of precomputing the flat projection", async () => {
    useEditorStore.getState().setNet(composedNet());
    reply = () => sse(snapshotFrame({ p1: 0, p2: 1 }), "[DONE]");

    await useSimulationStore.getState().enterSimulationModeStepped();

    expect(calls).toHaveLength(1);
    expect(calls[0].url.startsWith("/api/v1/simulate/composed?")).toBe(true);
    expectNoFlatEngine();
  });

  it("sends the object model to petri-server, never the flattened projection", async () => {
    useEditorStore.getState().setNet(composedNet());
    reply = () => sse("[DONE]");

    await useSimulationStore.getState().enterSimulationModeStepped();

    const body = composedBody();
    expect(body.objects).toHaveLength(2);
    // The projection would have dropped both frames and with them this priority.
    expect(body.objects[1].priority).toBe(2);
    expect(body.links.some((link) => link.type === "placeFusion")).toBe(true);
    // The projection would have collapsed p3 into p2 and deleted it.
    expect(body.objects[1].net_data.places.map((p) => p.id)).toContain("p3");
    expect(body.net_data).toBeUndefined();
  });

  it("turns the streamed snapshots into a steppable history, phases first and fusion members filled in", async () => {
    useEditorStore.getState().setNet(composedNet());
    reply = () =>
      sse(
        snapshotFrame(
          { p1: 0, p2: 1 },
          {
            firing_sequence: [
              { transition_id: "t1", phase: "before_act_in", markings: { p1: 0, p2: 0 }, buffers: { t1: 1 } },
              { transition_id: "t1", phase: "after_act_out", markings: { p1: 0, p2: 1 }, buffers: { t1: 0 } },
            ],
          },
        ),
        "[DONE]",
      );

    await useSimulationStore.getState().enterSimulationModeStepped();

    expect(useSimulationStore.getState().status).toBe("paused");
    expect(useSimulationStore.getState().stepIndex).toBe(0);
    expect(useSimulationStore.getState().snapshotCount).toBe(3);

    useSimulationStore.getState().stepForward();
    expect(useSimulationStore.getState().currentSnapshot?.active_phase).toBe("before_act_in");
    expect(useSimulationStore.getState().currentSnapshot?.active_transition_id).toBe("t1");

    useSimulationStore.getState().stepForward();
    const last = useSimulationStore.getState().currentSnapshot;
    expect(last?.active_phase).toBe("after_act_out");
    expect(last?.markings.p2).toBe(1);
    expect(last?.markings.p3).toBe(1);
  });

  it("reports a composed run that fails before any snapshot as an error instead of rerunning the flat projection", async () => {
    useEditorStore.getState().setNet(composedNet());
    reply = () =>
      sse(
        JSON.stringify({ error: "Composed-model simulation requires SIMULATION_REMOTE_URL" }),
        "[DONE]",
      );

    await useSimulationStore.getState().enterSimulationMode();

    const { status, error } = useSimulationStore.getState();
    expect(status).toBe("error");
    // The route answers whoever deploys it; the canvas is read by someone else.
    expect(error).not.toContain("SIMULATION_REMOTE_URL");
    expect(error).toContain("object simulation service");
    expect(calls).toHaveLength(1);
    expectNoFlatEngine();
  });

  it("still reports a composed run that fails after snapshots have arrived", async () => {
    useEditorStore.getState().setNet(composedNet());
    reply = () =>
      sse(snapshotFrame({ p1: 0, p2: 1 }), JSON.stringify({ error: "HTTP 500 from 10.0.0.4:8081" }));

    await useSimulationStore.getState().enterSimulationMode();

    const { status, error } = useSimulationStore.getState();
    expect(status).toBe("error");
    expect(error).not.toContain("10.0.0.4");
    expect(error).toContain("object simulation service");
    expect(calls).toHaveLength(1);
  });

  it("never publishes a partial history when a stepped composed run fails halfway", async () => {
    useEditorStore.getState().setNet(composedNet());
    reply = () =>
      sse(
        snapshotFrame({ p1: 0, p2: 1 }),
        snapshotFrame({ p1: 0, p2: 2 }),
        JSON.stringify({ error: "petri-server closed the stream" }),
      );

    await useSimulationStore.getState().enterSimulationModeStepped();

    expect(useSimulationStore.getState().status).toBe("error");
    expect(useSimulationStore.getState().error).toContain("object simulation service");
    expect(useSimulationStore.getState().snapshotCount).toBe(1);
    expect(useSimulationStore.getState().editorMode).toBe("simulating");
    // The streamed progress was feedback for the wait, not a position reached.
    expect(useSimulationStore.getState().progress).toBe(0);

    useSimulationStore.getState().stepForward();
    expect(useSimulationStore.getState().currentSnapshot?.markings.p1).toBe(1);
  });

  it("keeps a net that is merely framed on the built-in engine", async () => {
    // A frame with nothing linked to it is organisation, not structure: the
    // projection only drops the frame, so both engines answer the same question
    // and there is no reason to make the net unrunnable without petri-server.
    useEditorStore.getState().setNet(framedNet());
    reply = () => precompute([JSON.parse(snapshotFrame({ p1: 0, p2: 1 }))]);

    await useSimulationStore.getState().enterSimulationModeStepped();

    expect(useSimulationStore.getState().status).toBe("paused");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain("/api/v1/simulate/precompute");
    for (const call of calls) {
      expect(call.url).not.toContain("/simulate/composed");
    }
  });

  it("treats a stream that ends without its sentinel as a cut-short run, not a finished one", async () => {
    useEditorStore.getState().setNet(composedNet());
    // No "[DONE]": what a reaped connection or a restarted backend leaves behind.
    reply = () => sse(snapshotFrame({ p1: 0, p2: 1 }), snapshotFrame({ p1: 0, p2: 2 }));

    await useSimulationStore.getState().enterSimulationModeStepped();

    const { status, error, snapshotCount } = useSimulationStore.getState();
    expect(status).toBe("error");
    expect(error).toBe(STREAM_ENDED_EARLY);
    expect(snapshotCount).toBe(1);
  });

  it("a stepped composed run that was cancelled never publishes anything", async () => {
    useEditorStore.getState().setNet(composedNet());
    const { gate, release } = openGate();
    reply = () => gatedSse([snapshotFrame({ p1: 0, p2: 1 })], gate, ["[DONE]"]);

    const run = useSimulationStore.getState().enterSimulationModeStepped();
    await until(() => calls.length === 1);
    await useSimulationStore.getState().exitSimulationMode();
    release();
    await run;

    expect(useSimulationStore.getState().status).toBe("idle");
    expect(useSimulationStore.getState().editorMode).toBe("edit");
    expect(useSimulationStore.getState().snapshotCount).toBe(0);
    expect(calls[0].init.signal?.aborted).toBe(true);
  });

  it("a superseded stepped composed run never overwrites the run that replaced it", async () => {
    useEditorStore.getState().setNet(composedNet());
    const { gate, release } = openGate();
    let served = 0;
    reply = () =>
      served++ === 0
        ? gatedSse(
            [snapshotFrame({ p1: 0, p2: 1 }), snapshotFrame({ p1: 0, p2: 2 })],
            gate,
            [snapshotFrame({ p1: 0, p2: 9 }), "[DONE]"],
          )
        : sse(snapshotFrame({ p1: 0, p2: 3 }), "[DONE]");

    const superseded = useSimulationStore.getState().enterSimulationModeStepped();
    await until(() => calls.length === 1);
    await useSimulationStore.getState().enterSimulationModeStepped();
    release();
    await superseded;

    expect(useSimulationStore.getState().status).toBe("paused");
    expect(useSimulationStore.getState().snapshotCount).toBe(2);

    useSimulationStore.getState().stepForward();
    expect(useSimulationStore.getState().currentSnapshot?.markings.p2).toBe(3);
  });

  it("precomputes a flat net in stepped mode, exactly as before", async () => {
    useEditorStore.getState().setNet(flatNet());
    const snapshots: SimulationSnapshot[] = [
      { current_time: 1, step_number: 1, markings: { q1: 0, q2: 1 }, buffers: {}, progress: 0.5 },
      { current_time: 2, step_number: 2, markings: { q1: 0, q2: 1 }, buffers: {}, progress: 1 },
    ];
    reply = () => precompute(snapshots);

    await useSimulationStore.getState().enterSimulationModeStepped();

    expect(calls).toHaveLength(1);
    expect(calls[0].url.startsWith("/api/v1/simulate/precompute?")).toBe(true);
    expect(calls[0].url).toContain("simulation_time=10");
    expect(calls[0].url).toContain("time_step=1");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ net_data: flatNet() });
    expect(useSimulationStore.getState().status).toBe("paused");
    expect(useSimulationStore.getState().snapshotCount).toBe(1 + snapshots.length);
  });

  it("lands on the final state, keeping the run steppable behind it", async () => {
    useEditorStore.getState().setNet(flatNet());
    const snapshots: SimulationSnapshot[] = [
      { current_time: 1, step_number: 1, markings: { q1: 0, q2: 1 }, buffers: {}, progress: 0.5 },
      { current_time: 2, step_number: 2, markings: { q1: 0, q2: 2 }, buffers: {}, progress: 1 },
    ];
    reply = () => precompute(snapshots);

    await useSimulationStore.getState().enterSimulationModeAtEnd();

    const state = useSimulationStore.getState();
    // The same one precompute request the stepped button makes: skipping the
    // animation is a landing choice, not a different way of running.
    expect(calls).toHaveLength(1);
    expect(calls[0].url.startsWith("/api/v1/simulate/precompute?")).toBe(true);
    expect(state.status).toBe("paused");
    expect(state.currentSnapshot?.markings.q2).toBe(2);
    expect(state.stepIndex).toBe(snapshots.length);
    expect(state.snapshotCount).toBe(1 + snapshots.length);

    // Behind the end state is the whole history, so stepping back works.
    useSimulationStore.getState().stepBackward();
    expect(useSimulationStore.getState().currentSnapshot?.markings.q2).toBe(1);
  });

  it("hands the skipped run to the statistics collector, which saw none of it", async () => {
    const { useStatisticsStore } = await import("./statistics-store");
    useStatisticsStore.getState().reset();
    useEditorStore.getState().setNet(flatNet());
    const snapshots: SimulationSnapshot[] = [
      { current_time: 1, step_number: 1, markings: { q1: 0, q2: 1 }, buffers: {}, progress: 0.5 },
      { current_time: 2, step_number: 2, markings: { q1: 0, q2: 2 }, buffers: {}, progress: 1 },
    ];
    reply = () => precompute(snapshots);

    await useSimulationStore.getState().enterSimulationModeAtEnd();

    // Nothing animated the middle of this run, so a collector that only
    // samples the rendered snapshot would hold a single point and the
    // statistics panel would draw a run that never happened.
    const series = useStatisticsStore.getState().placeMarkings.q2;
    expect(series.map((p) => p.value)).toEqual([0, 1, 2]);
    expect(series.map((p) => p.time)).toEqual([0, 1, 2]);
  });

  it("streams a flat net from the flat endpoint in continuous mode, exactly as before", async () => {
    useEditorStore.getState().setNet(flatNet());
    reply = () => sse(snapshotFrame({ q1: 0, q2: 1 }), "[DONE]");

    await useSimulationStore.getState().enterSimulationMode();

    expect(calls).toHaveLength(1);
    expect(calls[0].url.startsWith("/api/v1/simulate?")).toBe(true);
    expect(calls.some((call) => call.url.startsWith("/api/v1/simulate/composed"))).toBe(false);
    expect(useSimulationStore.getState().error).toBeNull();
  });
});
