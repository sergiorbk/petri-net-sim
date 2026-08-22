import { fetchWithAuth } from "@/lib/api-client";
import type { PetriNetData, SimulationSnapshot } from "@/types/petri";

export interface PrecomputeResult {
  snapshots: SimulationSnapshot[];
  total: number;
}

export interface SimulationStreamParams {
  timeStep?: number;
  snapshotInterval?: number;
  animationDelay: number;
  /**
   * UUID of a net snapshot stored in the backend DB.
   * Preferred over netData — the backend resolves it from the snapshots table,
   * so the full net JSON doesn't need to travel over the wire.
   */
  snapshotId?: string | null;
  /**
   * Full net JSON fallback for messages that pre-date snapshot versioning
   * (old localStorage entries without a snapshotId).
   */
  netData?: PetriNetData | null;
}

/**
 * Reported through `onError` when the response body ended without the stream's
 * `[DONE]` sentinel. Exported so a caller can tell "the run was cut short" from
 * "the engine refused the run" — the two need different things said to a user.
 */
export const STREAM_ENDED_EARLY = "The simulation stream ended before the run finished.";

export interface SimulationStreamCallbacks {
  onSnapshot: (snapshot: SimulationSnapshot) => void;
  onDone: () => void;
  /**
   * `kind` says whose vocabulary the message is in. "model" means the model
   * itself was rejected (a validation message the canvas user can act on,
   * shown verbatim); absent or "transport" means the failure is about the
   * deployment (URLs, HTTP statuses) and the caller substitutes wording a
   * canvas user can do something with.
   */
  onError: (error: string, kind?: "transport" | "model") => void;
  /**
   * A notice about the run that is not a failure: today, that the configured
   * remote engine was unreachable and the built-in one ran the model instead.
   * The run continues; the caller decides how loudly to say so.
   */
  onWarning?: (warning: string) => void;
}

export interface StandaloneSimulationParams {
  timeStep?: number;
  snapshotInterval?: number;
  animationDelay: number;
}

export async function streamSimulationStandalone(
  netData: PetriNetData,
  simulationTime: number,
  params: StandaloneSimulationParams,
  callbacks: SimulationStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const query = new URLSearchParams({
    simulation_time: String(simulationTime),
    animation_delay: String(params.animationDelay),
  });

  if (params.snapshotInterval != null) {
    query.set("snapshot_interval", String(params.snapshotInterval));
  } else if (params.timeStep != null) {
    query.set("time_step", String(params.timeStep));
  }

  const response = await fetchWithAuth(`/api/v1/simulate?${query}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ net_data: netData }),
    signal,
  });

  if (!response.ok) {
    let errorMsg = response.status === 401 ? "Session expired" : "Simulation request failed";
    try {
      const json = await response.json();
      errorMsg = json.error?.message ?? json.detail ?? errorMsg;
    } catch {
      // ignore
    }
    callbacks.onError(errorMsg);
    return;
  }

  return consumeSimulationStream(response, callbacks);
}

export async function streamSimulation(
  sessionId: string,
  simulationTime: number,
  params: SimulationStreamParams,
  callbacks: SimulationStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const query = new URLSearchParams({
    simulation_time: String(simulationTime),
    animation_delay: String(params.animationDelay),
  });

  if (params.snapshotInterval != null) {
    query.set("snapshot_interval", String(params.snapshotInterval));
  } else if (params.timeStep != null) {
    query.set("time_step", String(params.timeStep));
  }

  const url = `/api/v1/sessions/${encodeURIComponent(sessionId)}/simulate?${query}`;

  let body: string | undefined;
  if (params.snapshotId) {
    body = JSON.stringify({ snapshot_id: params.snapshotId });
  } else if (params.netData) {
    body = JSON.stringify({ net_data: params.netData });
  }

  const response = await fetchWithAuth(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body,
    signal,
  });

  if (!response.ok) {
    let errorMsg = response.status === 401 ? "Session expired" : "Simulation request failed";
    try {
      const json = await response.json();
      errorMsg = json.error?.message ?? json.detail ?? errorMsg;
    } catch {
      // ignore
    }
    callbacks.onError(errorMsg);
    return;
  }

  return consumeSimulationStream(response, callbacks);
}

export interface PrecomputeError {
  error: string;
}

async function readPrecomputeResponse(response: Response): Promise<PrecomputeResult | PrecomputeError | null> {
  if (response.ok) return response.json() as Promise<PrecomputeResult>;
  try {
    const json = await response.json() as { detail?: string };
    const msg = json.detail ?? `Precompute failed (HTTP ${response.status})`;
    return { error: msg };
  } catch {
    return null;
  }
}

export async function precomputeSimulationStandalone(
  netData: PetriNetData,
  simulationTime: number,
  params: StandaloneSimulationParams,
): Promise<PrecomputeResult | PrecomputeError | null> {
  const query = new URLSearchParams({ simulation_time: String(simulationTime) });
  if (params.snapshotInterval != null) {
    query.set("snapshot_interval", String(params.snapshotInterval));
  } else if (params.timeStep != null) {
    query.set("time_step", String(params.timeStep));
  }

  try {
    const response = await fetchWithAuth(`/api/v1/simulate/precompute?${query}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ net_data: netData }),
    });
    return readPrecomputeResponse(response);
  } catch {
    return null;
  }
}

export async function precomputeSimulation(
  sessionId: string,
  simulationTime: number,
  params: SimulationStreamParams,
): Promise<PrecomputeResult | PrecomputeError | null> {
  const query = new URLSearchParams({ simulation_time: String(simulationTime) });
  if (params.snapshotInterval != null) {
    query.set("snapshot_interval", String(params.snapshotInterval));
  } else if (params.timeStep != null) {
    query.set("time_step", String(params.timeStep));
  }

  let body: string | undefined;
  if (params.snapshotId) {
    body = JSON.stringify({ snapshot_id: params.snapshotId });
  } else if (params.netData) {
    body = JSON.stringify({ net_data: params.netData });
  }

  try {
    const response = await fetchWithAuth(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/simulate/precompute?${query}`,
      {
        method: "POST",
        headers: body ? { "Content-Type": "application/json" } : {},
        body,
      },
    );
    return readPrecomputeResponse(response);
  } catch {
    return null;
  }
}

/**
 * Reads one simulation SSE stream. Exported so the composed-model client can
 * reuse the exact same event handling — the v2 endpoint speaks the identical
 * protocol, only the URL and request body differ.
 *
 * Exactly one terminal callback is made. A run is only done when the stream says
 * so with its `[DONE]` sentinel, which every route emits on every path including
 * its error ones; a body that simply ends was cut short, and reporting that as
 * done would present a partial run as a whole one — invisibly so for the stepped
 * mode, which has no way to render "and then it stopped".
 */
export async function consumeSimulationStream(
  response: Response,
  callbacks: SimulationStreamCallbacks,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) {
    callbacks.onError("No response body");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(":")) continue;

        if (trimmed === "data: [DONE]") {
          callbacks.onDone();
          return;
        }

        if (trimmed.startsWith("data: ")) {
          const jsonStr = trimmed.slice(6);
          try {
            const parsed = JSON.parse(jsonStr) as Partial<SimulationSnapshot> & {
              error?: string;
              /** Whose vocabulary the error is in; see SimulationStreamCallbacks. */
              kind?: string;
              warning?: string;
            };
            if (parsed.error) {
              callbacks.onError(parsed.error, parsed.kind === "model" ? "model" : "transport");
              return;
            }
            if (parsed.warning) {
              callbacks.onWarning?.(parsed.warning);
              continue;
            }
            // Not every frame on this stream is a snapshot, and one that is not
            // must never be handed on as one: the canvas indexes `markings` and
            // `buffers` off it directly, so the engine's "remote unavailable,
            // using the built-in engine" notice arriving as a snapshot threw
            // inside a render memo and took the whole editor route down with
            // it. A frame carrying markings is a snapshot; anything else is
            // vocabulary this reader does not know yet, and is skipped.
            if (!parsed.markings) continue;
            callbacks.onSnapshot({ ...parsed, buffers: parsed.buffers ?? {} } as SimulationSnapshot);
          } catch {
            // skip malformed
          }
        }
      }
    }

    if (buffer.trim() === "data: [DONE]") {
      callbacks.onDone();
      return;
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    callbacks.onError(err instanceof Error ? err.message : "Stream error");
    return;
  } finally {
    reader.releaseLock();
  }

  callbacks.onError(STREAM_ENDED_EARLY);
}
