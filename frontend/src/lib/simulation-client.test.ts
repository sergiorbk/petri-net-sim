import { describe, expect, it, vi } from "vitest";
import type { SimulationSnapshot } from "@/types/petri";
import { consumeSimulationStream, STREAM_ENDED_EARLY } from "./simulation-client";

/** An SSE body carrying the given frames, then [DONE] unless told otherwise. */
function sseResponse(frames: unknown[], opts?: { done?: boolean }): Response {
  const lines = frames.map((f) => `data: ${JSON.stringify(f)}\n\n`);
  if (opts?.done !== false) lines.push("data: [DONE]\n\n");
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const line of lines) controller.enqueue(encoder.encode(line));
      controller.close();
    },
  });
  return new Response(body);
}

function collect() {
  const snapshots: SimulationSnapshot[] = [];
  const warnings: string[] = [];
  const errors: { message: string; kind?: string }[] = [];
  const onDone = vi.fn();
  return {
    snapshots,
    warnings,
    errors,
    onDone,
    callbacks: {
      onSnapshot: (s: SimulationSnapshot) => snapshots.push(s),
      onWarning: (w: string) => warnings.push(w),
      onError: (message: string, kind?: "transport" | "model") =>
        errors.push({ message, kind }),
      onDone,
    },
  };
}

const snapshotFrame = (step: number) => ({
  current_time: step,
  step_number: step,
  markings: { p1: step },
  buffers: { t1: 0 },
  progress: step / 10,
});

describe("consumeSimulationStream", () => {
  it("delivers snapshot frames in order and closes on [DONE]", async () => {
    const c = collect();
    await consumeSimulationStream(sseResponse([snapshotFrame(1), snapshotFrame(2)]), c.callbacks);

    expect(c.snapshots.map((s) => s.step_number)).toEqual([1, 2]);
    expect(c.onDone).toHaveBeenCalledOnce();
    expect(c.errors).toEqual([]);
  });

  it("routes an engine notice to onWarning and keeps the run going", async () => {
    // The backend says this when the configured remote engine is unreachable
    // and the built-in one takes over. It used to be handed on as a snapshot,
    // and the canvas — which indexes markings and buffers off it — threw
    // inside a render memo and took the whole editor route down.
    const c = collect();
    await consumeSimulationStream(
      sseResponse([
        { warning: "Remote backend unavailable, using built-in engine" },
        snapshotFrame(1),
      ]),
      c.callbacks,
    );

    expect(c.warnings).toEqual(["Remote backend unavailable, using built-in engine"]);
    expect(c.snapshots.map((s) => s.step_number)).toEqual([1]);
    expect(c.errors).toEqual([]);
    expect(c.onDone).toHaveBeenCalledOnce();
  });

  it("never hands on a frame that is not a snapshot", async () => {
    const c = collect();
    await consumeSimulationStream(
      sseResponse([{ warning: "engine swapped" }, { note: "vocabulary from a newer server" }]),
      c.callbacks,
    );

    expect(c.snapshots).toEqual([]);
  });

  it("a caller that does not care about notices still consumes the stream", async () => {
    // onWarning is optional — an absent handler must not throw or stall.
    const snapshots: SimulationSnapshot[] = [];
    const onDone = vi.fn();
    await consumeSimulationStream(sseResponse([{ warning: "engine swapped" }, snapshotFrame(1)]), {
      onSnapshot: (s) => snapshots.push(s),
      onError: () => {},
      onDone,
    });

    expect(snapshots).toHaveLength(1);
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("fills in a missing buffers map rather than letting the canvas index undefined", async () => {
    const c = collect();
    await consumeSimulationStream(
      sseResponse([{ current_time: 0, step_number: 1, markings: { p1: 0 }, progress: 0 }]),
      c.callbacks,
    );

    expect(c.snapshots[0].buffers).toEqual({});
  });

  it("stops at the first error frame and reports whose vocabulary it is in", async () => {
    const c = collect();
    await consumeSimulationStream(
      sseResponse([{ error: "transition T_1 has no input arc", kind: "model" }, snapshotFrame(1)]),
      c.callbacks,
    );

    expect(c.errors).toEqual([{ message: "transition T_1 has no input arc", kind: "model" }]);
    expect(c.snapshots).toEqual([]);
    expect(c.onDone).not.toHaveBeenCalled();
  });

  it("treats an error with no kind as being about the deployment", async () => {
    const c = collect();
    await consumeSimulationStream(sseResponse([{ error: "boom" }]), c.callbacks);

    expect(c.errors).toEqual([{ message: "boom", kind: "transport" }]);
  });

  it("reports a stream that stops without [DONE]", async () => {
    const c = collect();
    await consumeSimulationStream(sseResponse([snapshotFrame(1)], { done: false }), c.callbacks);

    expect(c.snapshots).toHaveLength(1);
    expect(c.errors).toEqual([{ message: STREAM_ENDED_EARLY, kind: undefined }]);
  });

  it("skips a malformed frame instead of failing the run", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(encoder.encode("data: {not json\n\n"));
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(snapshotFrame(1))}\n\n`));
        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
      },
    });

    const c = collect();
    await consumeSimulationStream(new Response(body), c.callbacks);

    expect(c.snapshots).toHaveLength(1);
    expect(c.errors).toEqual([]);
  });
});
