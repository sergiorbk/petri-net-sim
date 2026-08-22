import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { createStreamFlusher } from "./stream-flush";

describe("createStreamFlusher", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("turns a burst of arrivals into a single write", () => {
    const write = vi.fn();
    const flusher = createStreamFlusher(write, 50);

    for (let i = 0; i < 200; i++) flusher.schedule();
    vi.advanceTimersByTime(50);

    expect(write).toHaveBeenCalledTimes(1);
  });

  it("keeps writing as long as arrivals keep coming", () => {
    const write = vi.fn();
    const flusher = createStreamFlusher(write, 50);

    for (let round = 0; round < 3; round++) {
      flusher.schedule();
      vi.advanceTimersByTime(50);
    }

    expect(write).toHaveBeenCalledTimes(3);
  });

  it("writes nothing when nothing arrived", () => {
    const write = vi.fn();
    createStreamFlusher(write, 50);

    vi.advanceTimersByTime(500);

    expect(write).not.toHaveBeenCalled();
  });

  it("flush writes what is pending, immediately", () => {
    const write = vi.fn();
    const flusher = createStreamFlusher(write, 50);

    flusher.schedule();
    flusher.flush();

    expect(write).toHaveBeenCalledTimes(1);
  });

  it("flush cancels the write it just did", () => {
    const write = vi.fn();
    const flusher = createStreamFlusher(write, 50);

    flusher.schedule();
    flusher.flush();
    vi.advanceTimersByTime(500);

    expect(write).toHaveBeenCalledTimes(1);
  });

  it("flush with nothing pending does nothing", () => {
    const write = vi.fn();
    const flusher = createStreamFlusher(write, 50);

    flusher.flush();

    expect(write).not.toHaveBeenCalled();
  });
});
