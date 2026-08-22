/**
 * Coalescing writer for a value that arrives far faster than it needs to
 * be shown.
 *
 * Streamed text arrives a token at a time, and each write into the chat
 * store walks every session, copies the timeline and re-renders the
 * conversation. That is fine a few times per message and locks the tab up
 * hundreds of times per message -- the cost is per WRITE, not per token,
 * so the tokens are gathered and written on an interval instead.
 *
 * `flush` exists because coalescing is only safe while nothing else is
 * looking: anything that touches the same state (a tool event arriving
 * mid-sentence, the stream ending) has to see the tokens that came before
 * it, or it lands ahead of them and the next write puts them back.
 */
export interface StreamFlusher {
  /** Note that there is something to write, and schedule the write. */
  schedule: () => void;
  /** Write now if anything is pending, and cancel the scheduled write. */
  flush: () => void;
}

export function createStreamFlusher(
  write: () => void,
  intervalMs: number,
): StreamFlusher {
  let pending = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    if (!pending) return;
    pending = false;
    write();
  };

  return {
    schedule: () => {
      pending = true;
      // Leading edge deliberately NOT written: the first token of a reply
      // is worth no more than the second, and writing it immediately would
      // cost a full render to show one character.
      if (timer === null) timer = setTimeout(flush, intervalMs);
    },
    flush,
  };
}
