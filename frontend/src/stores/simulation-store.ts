import { create } from "zustand";
import { persist } from "zustand/middleware";
import { apiClient } from "@/lib/api-client";
import {
  streamSimulation,
  streamSimulationStandalone,
  precomputeSimulation,
  precomputeSimulationStandalone,
  STREAM_ENDED_EARLY,
  type PrecomputeError,
  type StandaloneSimulationParams,
} from "@/lib/simulation-client";

function isPrecomputeError(r: unknown): r is PrecomputeError {
  return typeof r === "object" && r !== null && "error" in r;
}
import type { PetriNetData, SimulationSnapshot } from "@/types/petri";
import {
  fusionMarkingExpander,
  projectForSimulation,
  type SimulationProjection,
} from "@/lib/petri-composed";
import { needsObjectEngine, streamComposedSimulation } from "@/lib/composed-simulation-client";
import { toast } from "@/stores/toast-store";
import { useUiStore } from "@/stores/ui-store";

/**
 * What to tell a user whose model could not reach the object engine.
 *
 * The route answers in the vocabulary of whoever deploys it — an unset
 * environment variable, a backend URL, an HTTP status. That is the right answer
 * for the person who can act on it and no answer at all for the person looking
 * at the canvas, who needs to know only that this particular model cannot run
 * without a service that is missing, and that nothing was silently substituted
 * for it.
 */
function composedFailure(reported: string, kind?: "transport" | "model"): string {
  // A cut-short run already says something a user can act on, and says it about
  // their run rather than about a deployment. So does a model-vocabulary
  // rejection: "transition T_1 has no input arc" is exactly what the person
  // looking at the canvas needs, and hiding it behind the service-unavailable
  // wording sent them debugging a deployment that was fine.
  if (reported === STREAM_ENDED_EARLY || kind === "model") return reported;
  return "The Petri-object simulation service is unavailable — nothing was simulated in its place.";
}

/**
 * An engine notice is said once, where it happens. The run is still going,
 * it is just not going on the engine the deployment asked for, and a canvas
 * that quietly showed different numbers than the configured engine would give
 * is exactly the substitution this codebase refuses to make silently.
 */
function reportEngineNotice(warning: string): void {
  toast(warning, "warning");
}

function makeInitialSnapshot(net: PetriNetData): SimulationSnapshot {
  return {
    current_time: 0,
    step_number: 0,
    markings: Object.fromEntries(net.places.map((p) => [p.id, p.tokens])),
    buffers: Object.fromEntries(net.transitions.map((t) => [t.id, 0])),
    progress: 0,
  };
}

function expandSnapshot(snapshot: SimulationSnapshot): SimulationSnapshot[] {
  const seq = snapshot.firing_sequence;
  if (!seq || seq.length === 0) return [snapshot];

  const expanded: SimulationSnapshot[] = [];
  for (const step of seq) {
    expanded.push({
      current_time: snapshot.current_time,
      step_number: snapshot.step_number,
      markings: { ...step.markings },
      buffers: { ...step.buffers },
      progress: snapshot.progress,
      fired_transitions: [step.transition_id],
      active_transition_id: step.transition_id,
      active_phase: step.phase,
    });
  }
  return expanded;
}

type SimulationStatus = "idle" | "loading" | "running" | "paused" | "done" | "error";

export type EditorMode = "edit" | "simulating";

export type TimeUnitScale = "seconds" | "minutes" | "hours" | "abstract";

/**
 * Snapshot mode:
 * - "time"      — one snapshot every `timeStep` simulation units (default, visual)
 * - "scientific" — one snapshot every `snapshotInterval` discrete events
 */
export type SnapshotMode = "time" | "scientific";

/**
 * Playback rate in simulation units per real second.
 * Only used in "time" mode. Examples:
 *   1   → 1 sim unit plays back in 1 real second
 *   60  → 60 sim units per real second  (1 sim-minute → 1 real-second)
 *   600 → 600 sim units per real second (10 sim-minutes → 1 real-second)
 */
export type PlaybackRate = 1 | 10 | 60 | 600 | 3600;

interface SimulationState {
  sessionId: string | null;
  net: PetriNetData | null;
  netLoading: boolean;
  /** Message ID of the chat block whose net is currently loaded in the store. */
  activeBlockId: string | null;
  /**
   * UUID of the backend NetSnapshot row for the active block.
   * When set, simulate requests send snapshot_id instead of the full net JSON.
   * Null for the session's current net or for old messages without a snapshot ID.
   */
  snapshotId: string | null;

  status: SimulationStatus;
  error: string | null;
  progress: number;
  currentSnapshot: SimulationSnapshot | null;
  previousSnapshot: SimulationSnapshot | null;

  smoothAnimations: boolean;

  simulationTime: number;
  /** Resolution: how many sim units between snapshots (time mode only). */
  timeStep: number;
  /** Playback rate: sim units displayed per real second (time mode only). */
  playbackRate: PlaybackRate;
  /** Step interval for scientific mode. */
  snapshotInterval: number;
  snapshotMode: SnapshotMode;

  timeUnitScale: TimeUnitScale;
  overlayOpen: boolean;

  // Actions
  setSessionId: (id: string) => void;
  loadNet: () => Promise<void>;
  startSimulation: () => Promise<void>;
  /** Start simulation and immediately pause at step 0 (initial marking) for manual stepping. */
  startSimulationStepped: () => Promise<void>;
  stopSimulation: () => void;
  /** Pause the client-side render loop without stopping the backend stream. */
  pauseSimulation: () => void;
  /** Resume the render loop after a pause. */
  resumeSimulation: () => void;
  /**
   * Reset playback state to initial marking without re-running the simulation.
   * Keeps sessionId and net intact so Run can be called again.
   */
  resetSimulation: () => void;
  /**
   * Full clear: stops any running simulation and wipes net + session.
   * Called when switching to a chat that has no associated backend session.
   */
  clearSimulation: () => void;
  /**
   * Drop the currently-displayed net while keeping the backend sessionId and
   * sim settings. Used when entering an empty chat where no snapshot has
   * been generated yet — canvas should show its empty state, not the
   * previous chat's net.
   */
  clearActiveBlock: () => void;
  /**
   * Switch the active simulation block to the given chat message.
   * Loads that message's stored net snapshot into the store so the
   * canvas and the next Run call use that specific version.
   * Pass snapshotId when available so simulate uses the DB row instead of
   * re-sending the full net JSON (works across backend restarts).
   */
  setActiveBlock: (blockId: string, net: PetriNetData, snapshotId?: string | null) => void;
  setSimulationTime: (t: number) => void;
  setTimeStep: (t: number) => void;
  /** Change playback rate — takes effect immediately, even mid-simulation. */
  setPlaybackRate: (r: PlaybackRate) => void;
  setSnapshotInterval: (n: number) => void;
  setSnapshotMode: (m: SnapshotMode) => void;
  setTimeUnitScale: (scale: TimeUnitScale) => void;
  openOverlay: () => void;
  closeOverlay: () => void;

  /**
   * Step mode — active when `stepIndex` is not null (only possible while paused).
   * `snapshotCount` mirrors `snapshotHistory.length` at the time of the last step
   * action so the UI can show "step X / N" reactively.
   */
  stepIndex: number | null;
  snapshotCount: number;
  /** Advance one snapshot forward in the received history. */
  stepForward: () => void;
  /** Go back one snapshot in the received history. */
  stepBackward: () => void;

  /** Editor ↔ Simulation mode for the standalone simulator app. */
  editorMode: EditorMode;
  /**
   * Enter simulation mode: reads the current net from editor-store,
   * starts the SSE stream, and freezes editing.
   */
  enterSimulationMode: () => Promise<void>;
  /**
   * Enter simulation mode but pause immediately at step 0 (initial marking)
   * so the user can step through manually.
   *
   * With `landOnFinalState`, it computes the same run and lands on its last
   * snapshot instead of its first: the end state without watching it arrive.
   * The history is kept either way, so stepping backward from the end works
   * exactly as stepping forward from the start does.
   */
  enterSimulationModeStepped: (options?: { landOnFinalState?: boolean }) => Promise<void>;
  /** Run to the end and show the final state, skipping the animation. */
  enterSimulationModeAtEnd: () => Promise<void>;
  /** Exit simulation mode: stops playback and returns to editing. */
  exitSimulationMode: () => void;

  setSmoothAnimations: (enabled: boolean) => void;
}

// ── Module-level runtime state (not stored in Zustand to avoid extra renders) ─

let abortController: AbortController | null = null;

/** All snapshots received during the current run, in arrival order. */
let snapshotHistory: SimulationSnapshot[] = [];

/** Snapshots received but not yet rendered by the playback loop. */
let snapshotQueue: SimulationSnapshot[] = [];

/** How many snapshots have been displayed by the render loop so far. */
let displayedCount = 0;

/** Set to true once the SSE stream sends [DONE]. */
let streamingComplete = false;

/** Handle for the client-side render timer. */
let renderTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * Monotonically-increasing counter that is bumped whenever a pending loadNet
 * result should be discarded (session change, clearActiveBlock, clearSimulation).
 * loadNet captures it at call time and checks it after the fetch; if they
 * differ, the result belongs to a superseded request and is dropped.
 */
let netLoadGeneration = 0;

/**
 * Bumped whenever a run is torn down. A streaming run captures it and checks it
 * before touching store state, so a stream that outlives its own run — an abort
 * the reader has not noticed yet, a superseded restart — can never publish.
 */
let simulationRun = 0;

function clearRenderLoop() {
  ++simulationRun;
  if (renderTimer !== null) {
    clearTimeout(renderTimer);
    renderTimer = null;
  }
  snapshotHistory = [];
  snapshotQueue = [];
  displayedCount = 0;
  streamingComplete = false;
}

/** Everything both playback modes need before they diverge. */
interface RunSetup {
  editorNet: PetriNetData;
  projection: SimulationProjection;
  expandFusionMarkings: (s: SimulationSnapshot) => SimulationSnapshot;
  step0: SimulationSnapshot;
  streamParams: StandaloneSimulationParams;
  simulationTime: number;
  controller: AbortController;
  /** Generation this run owns; anything else means the run was superseded. */
  run: number;
}

// ── Store ────────────────────────────────────────────────────────────────────

export const useSimulationStore = create<SimulationState>(
  // @ts-ignore - persist middleware typing
  persist(
    (set, get) => {
  /**
   * Client-side render loop.
   *
   * The backend streams all snapshots with animationDelay = 0 (as fast as
   * possible).  This loop pulls from `snapshotQueue` at the pace defined by
   * the current `playbackRate` / `timeStep`, so the user can change speed at
   * any time without restarting the simulation.
   *
   * - Time mode  : one snapshot every (timeStep / playbackRate) real seconds.
   *   If that delay is shorter than one animation frame (< 16 ms) we batch
   *   multiple snapshots per 16 ms tick and show the latest one so the browser
   *   never falls behind.
   * - Scientific : one snapshot every 50 ms (enough to see individual steps).
   */
  function scheduleRender() {
    const { timeStep, playbackRate, snapshotMode, status } = get();

    // Pause: stop scheduling until resumeSimulation restarts the loop.
    if (status === "paused") {
      renderTimer = null;
      return;
    }

    if (snapshotQueue.length === 0) {
      if (streamingComplete) {
        // Stream ended and queue drained — simulation is visually complete.
        set({ status: "done", progress: 1 });
        renderTimer = null;
        return;
      }
      // Queue temporarily empty; backend is still streaming — wait one frame.
      renderTimer = setTimeout(scheduleRender, 16);
      return;
    }

    const delayMs =
      snapshotMode === "time"
        ? (timeStep / playbackRate) * 1000
        : 50; // scientific: fixed 50 ms per step

    if (delayMs < 16) {
      const batchSize = Math.max(1, Math.floor(16 / Math.max(delayMs, 1)));
      const count = Math.min(batchSize, snapshotQueue.length);
      const snapshot = snapshotQueue[count - 1];
      snapshotQueue = snapshotQueue.slice(count);
      displayedCount += count;

      set({ previousSnapshot: get().currentSnapshot, currentSnapshot: snapshot, progress: snapshot.progress });
      renderTimer = setTimeout(scheduleRender, 16);
    } else {
      renderTimer = setTimeout(() => {
        if (snapshotQueue.length === 0) {
          scheduleRender();
          return;
        }
        const snapshot = snapshotQueue.shift()!;
        displayedCount++;
        set({ previousSnapshot: get().currentSnapshot, currentSnapshot: snapshot, progress: snapshot.progress });
        scheduleRender();
      }, delayMs);
    }
  }

  /**
   * Tears down whatever was running and prepares the next run. The model is
   * projected here and only here, so which engine will run it is decided in one
   * place instead of once per playback mode. Returns null when there is nothing
   * to simulate.
   */
  async function beginRun(): Promise<RunSetup | null> {
    const { useEditorStore } = await import("@/stores/editor-store");
    const { useStatisticsStore } = await import("@/stores/statistics-store");
    const editorNet = useEditorStore.getState().net;

    // Guard before the teardown: an empty canvas must not kill a live run.
    if (editorNet.places.length === 0) return null;

    abortController?.abort();
    clearRenderLoop();
    const controller = new AbortController();
    abortController = controller;
    const run = simulationRun;
    useStatisticsStore.getState().startCollecting();

    const { simulationTime, timeStep, snapshotInterval, snapshotMode } = get();

    // A composed model is projected onto the flat formalism the built-in engine
    // speaks; the canvas keeps showing the original net, so every snapshot is
    // mapped back through the projection before it is displayed.
    const projection = projectForSimulation(editorNet);
    const isTimeBased = snapshotMode === "time";

    return {
      editorNet,
      projection,
      expandFusionMarkings: fusionMarkingExpander(editorNet),
      step0: projection.expandSnapshot(makeInitialSnapshot(projection.net)),
      streamParams: {
        timeStep: isTimeBased ? timeStep : undefined,
        snapshotInterval: isTimeBased ? undefined : snapshotInterval,
        // Always 0: pacing is fully client-side so speed can be changed live.
        animationDelay: 0,
      },
      simulationTime,
      controller,
      run,
    };
  }

  return {
    sessionId: null,
    net: null,
    netLoading: false,
    activeBlockId: null,
    snapshotId: null,

    status: "idle",
    error: null,
    progress: 0,
    currentSnapshot: null,
    previousSnapshot: null,

    smoothAnimations: true,

    simulationTime: 3600,
    timeStep: 1,
    playbackRate: 60,
    snapshotInterval: 100,
    snapshotMode: "time",

    timeUnitScale: "seconds",
    overlayOpen: false,

    stepIndex: null,
    snapshotCount: 0,

    editorMode: "edit",

    setSessionId: (id) => {
      const prev = get().sessionId;
      if (prev === id) return;
      clearRenderLoop();
      abortController?.abort();
      abortController = null;
      ++netLoadGeneration;
      set({ sessionId: id, net: null, snapshotId: null, status: "idle" });
    },

    loadNet: async () => {
      const { sessionId } = get();
      if (!sessionId) return;

      const gen = ++netLoadGeneration;
      set({ netLoading: true, error: null });
      const result = await apiClient<PetriNetData>(`/api/v1/sessions/${sessionId}/net`);
      if (gen !== netLoadGeneration) return;
      if (result.ok && result.data?.places?.length > 0) {
        set({ net: result.data, netLoading: false, error: null });
      } else {
        set({ netLoading: false });
      }
    },

    startSimulation: async () => {
      const {
        sessionId, net, snapshotId,
        simulationTime, timeStep,
        snapshotInterval, snapshotMode,
      } = get();
      if (!sessionId || !net) return;

      abortController?.abort();
      abortController = new AbortController();
      clearRenderLoop();

      // Seed step 0 (initial marking) into history so the user can step back to it.
      // Not pushed to queue — auto-play starts from backend snapshots directly.
      snapshotHistory.push(makeInitialSnapshot(net));
      displayedCount = 1;

      set({ status: "running", progress: 0, currentSnapshot: null, previousSnapshot: null, error: null, stepIndex: null, snapshotCount: 0 });

      const isTimeBased = snapshotMode === "time";

      // Start the client render loop before the stream begins so the first
      // snapshot is rendered as soon as it arrives.
      scheduleRender();

      await streamSimulation(
        sessionId,
        simulationTime,
        {
          timeStep: isTimeBased ? timeStep : undefined,
          snapshotInterval: isTimeBased ? undefined : snapshotInterval,
          // Always 0: pacing is now fully client-side so speed can be changed live.
          animationDelay: 0,
          // Prefer snapshot_id (DB lookup, survives backend restarts) over net_data.
          snapshotId: snapshotId ?? null,
          netData: snapshotId ? null : net,
        },
        {
          onSnapshot: (snapshot) => {
            const expanded = expandSnapshot(snapshot);
            for (const sub of expanded) {
              snapshotHistory.push(sub);
              snapshotQueue.push(sub);
            }
          },
          onDone: () => {
            streamingComplete = true;
            abortController = null;
          },
          onError: (error) => {
            streamingComplete = true;
            clearRenderLoop();
            set({ status: "error", error });
            abortController = null;
          },
          onWarning: reportEngineNotice,
        },
        abortController.signal,
      );
    },

    startSimulationStepped: async () => {
      const {
        sessionId, net, snapshotId,
        simulationTime, timeStep,
        snapshotInterval, snapshotMode,
      } = get();
      if (!sessionId || !net) return;

      abortController?.abort();
      abortController = null;
      clearRenderLoop();

      const step0 = makeInitialSnapshot(net);

      set({
        status: "loading",
        progress: 0,
        currentSnapshot: step0,
        previousSnapshot: null,
        error: null,
        stepIndex: 0,
        snapshotCount: 1,
      });

      const isTimeBased = snapshotMode === "time";

      const result = await precomputeSimulation(sessionId, simulationTime, {
        timeStep: isTimeBased ? timeStep : undefined,
        snapshotInterval: isTimeBased ? undefined : snapshotInterval,
        animationDelay: 0,
        snapshotId: snapshotId ?? null,
        netData: snapshotId ? null : net,
      });

      if (!result || isPrecomputeError(result)) {
        set({ status: "error", error: result ? result.error : "Failed to precompute simulation" });
        return;
      }

      snapshotHistory = [step0, ...result.snapshots.flatMap(expandSnapshot)];
      streamingComplete = true;

      set({ status: "paused", snapshotCount: snapshotHistory.length });
    },

    stopSimulation: () => {
      abortController?.abort();
      abortController = null;
      clearRenderLoop();
      set({ status: "idle" });
    },

    pauseSimulation: () => {
      // Stop the render timer but keep the queue and the SSE stream alive.
      if (renderTimer !== null) {
        clearTimeout(renderTimer);
        renderTimer = null;
      }
      // displayedCount is 1-based relative to snapshotHistory (step-0 at index 0 is pre-consumed).
      // So the last rendered snapshot lives at snapshotHistory[displayedCount - 1].
      const idx = Math.max(0, displayedCount - 1);
      const snap = snapshotHistory[idx] ?? get().currentSnapshot;
      set({ status: "paused", stepIndex: idx, snapshotCount: snapshotHistory.length, currentSnapshot: snap ?? get().currentSnapshot });
    },

    resumeSimulation: () => {
      const { stepIndex } = get();
      // If the user stepped backward, rewind the queue to resume from that position.
      if (stepIndex !== null) {
        const resumeFrom = stepIndex + 1;
        snapshotQueue = snapshotHistory.slice(resumeFrom);
        displayedCount = resumeFrom;
      }
      set({ status: "running", stepIndex: null });
      scheduleRender();
    },

    resetSimulation: () => {
      abortController?.abort();
      abortController = null;
      clearRenderLoop();
      set({ status: "idle", error: null, progress: 0, currentSnapshot: null, previousSnapshot: null, stepIndex: null, snapshotCount: 0 });
    },

    clearSimulation: () => {
      abortController?.abort();
      abortController = null;
      clearRenderLoop();
      ++netLoadGeneration;
      set({
        sessionId: null, net: null, snapshotId: null, activeBlockId: null,
        status: "idle", error: null, progress: 0, currentSnapshot: null, previousSnapshot: null,
        stepIndex: null, snapshotCount: 0,
      });
    },

    clearActiveBlock: () => {
      abortController?.abort();
      abortController = null;
      clearRenderLoop();
      ++netLoadGeneration;
      set({
        net: null, snapshotId: null, activeBlockId: null,
        status: "idle", error: null, progress: 0,
        currentSnapshot: null, previousSnapshot: null,
        stepIndex: null, snapshotCount: 0,
      });
    },

    setActiveBlock: (blockId, net, snapshotId) => {
      abortController?.abort();
      abortController = null;
      clearRenderLoop();
      set({
        activeBlockId: blockId, net, snapshotId: snapshotId ?? null,
        status: "idle", error: null, progress: 0, currentSnapshot: null, previousSnapshot: null,
      });
    },

    stepForward: () => {
      const { stepIndex } = get();
      if (stepIndex === null) return;
      const next = stepIndex + 1;
      const total = snapshotHistory.length;
      if (next < total) {
        const snapshot = snapshotHistory[next];
        set({ previousSnapshot: get().currentSnapshot, stepIndex: next, snapshotCount: total, currentSnapshot: snapshot, progress: snapshot.progress });
      } else {
        set({ snapshotCount: total });
      }
    },

    stepBackward: () => {
      const { stepIndex } = get();
      if (stepIndex === null || stepIndex === 0) return;
      const prev = stepIndex - 1;
      const snapshot = snapshotHistory[prev];
      set({ previousSnapshot: get().currentSnapshot, stepIndex: prev, snapshotCount: snapshotHistory.length, currentSnapshot: snapshot, progress: snapshot.progress });
    },

    setSimulationTime: (t) => set({ simulationTime: t }),
    setTimeStep: (t) => set({ timeStep: t }),
    setPlaybackRate: (r) => set({ playbackRate: r }),
    setSnapshotInterval: (n) => set({ snapshotInterval: n }),
    setSnapshotMode: (m) => set({ snapshotMode: m }),
    setTimeUnitScale: (scale) => set({ timeUnitScale: scale }),
    openOverlay: () => set({ overlayOpen: true }),
    closeOverlay: () => set({ overlayOpen: false }),
    setSmoothAnimations: (enabled) => set({ smoothAnimations: enabled }),

    enterSimulationMode: async () => {
      const setup = await beginRun();
      if (!setup) return;
      const {
        editorNet, projection, expandFusionMarkings, step0,
        streamParams, simulationTime, controller,
      } = setup;

      snapshotHistory.push(step0);
      displayedCount = 1;

      set({
        editorMode: "simulating",
        net: editorNet,
        snapshotId: null,
        status: "running",
        progress: 0,
        currentSnapshot: null,
        previousSnapshot: null,
        error: null,
        stepIndex: null,
        snapshotCount: 0,
      });

      scheduleRender();

      // Sub-steps are split first and mapped back afterwards: each animation
      // sub-step carries its own markings straight from the engine, so mapping
      // before the split would be undone by it.
      const receive = (expandMarkings: (s: SimulationSnapshot) => SimulationSnapshot) =>
        (snapshot: SimulationSnapshot) => {
          for (const sub of expandSnapshot(snapshot).map(expandMarkings)) {
            snapshotHistory.push(sub);
            snapshotQueue.push(sub);
          }
        };

      const finish = {
        onDone: () => {
          streamingComplete = true;
          abortController = null;
        },
        onError: (error: string) => {
          streamingComplete = true;
          clearRenderLoop();
          set({ status: "error", error });
          abortController = null;
        },
        onWarning: reportEngineNotice,
      };

      // A model with linked objects goes to the engine that understands them
      // natively, and only there: PetriObjModel resolves a conflict between
      // objects by OBJECT priority, which the flat projection does not have — it
      // drops the frames that carry it. Substituting the projection would answer
      // a different question, so a failure is reported instead.
      if (needsObjectEngine(editorNet)) {
        await streamComposedSimulation(
          editorNet,
          simulationTime,
          streamParams,
          {
            onSnapshot: receive(expandFusionMarkings),
            onDone: finish.onDone,
            onError: (error, kind) => finish.onError(composedFailure(error, kind)),
            onWarning: finish.onWarning,
          },
          controller.signal,
        );
        return;
      }

      await streamSimulationStandalone(
        projection.net,
        simulationTime,
        streamParams,
        { onSnapshot: receive(projection.expandSnapshot), ...finish },
        controller.signal,
      );
    },

    enterSimulationModeStepped: async ({ landOnFinalState = false } = {}) => {
      /**
       * Where a computed history leaves the stepper: on step 0 by default,
       * on the last snapshot when the caller asked to skip the animation.
       *
       * Nothing rendered the middle of the run in that case, so the
       * statistics collector (which samples currentSnapshot as the render
       * loop advances it) would have seen the final state alone. It gets the
       * whole history handed to it instead, and the panel draws the run.
       */
      const settle = async (fallbackProgress?: number) => {
        const lastIndex = snapshotHistory.length - 1;
        const base = {
          status: "paused" as const,
          snapshotCount: snapshotHistory.length,
          ...(fallbackProgress !== undefined ? { progress: fallbackProgress } : {}),
        };

        if (!landOnFinalState || lastIndex <= 0) {
          set(base);
          return;
        }

        const { useStatisticsStore } = await import("@/stores/statistics-store");
        useStatisticsStore.getState().recordSnapshots(snapshotHistory);

        const last = snapshotHistory[lastIndex];
        displayedCount = snapshotHistory.length;
        set({
          ...base,
          stepIndex: lastIndex,
          currentSnapshot: last,
          previousSnapshot: snapshotHistory[lastIndex - 1] ?? null,
          progress: last.progress,
        });
      };

      const setup = await beginRun();
      if (!setup) return;
      const {
        editorNet, projection, expandFusionMarkings, step0,
        streamParams, simulationTime, controller, run,
      } = setup;

      set({
        editorMode: "simulating",
        net: editorNet,
        snapshotId: null,
        status: "loading",
        progress: 0,
        currentSnapshot: step0,
        previousSnapshot: null,
        error: null,
        stepIndex: 0,
        snapshotCount: 1,
      });

      // A composed model runs on the engine that understands objects, whichever
      // button started it. Stepped mode consumes the same stream continuous mode
      // does and keeps the snapshots instead of animating them — which is exactly
      // the shape precompute hands back for a flat net.
      if (needsObjectEngine(editorNet)) {
        const collected: SimulationSnapshot[] = [];
        let failure: string | null = null;

        try {
          await streamComposedSimulation(
            editorNet,
            simulationTime,
            streamParams,
            {
              onSnapshot: (snapshot) => {
                if (run !== simulationRun) return;
                collected.push(snapshot);
                set({ progress: snapshot.progress });
              },
              // Nothing to do on completion: the history is published below,
              // once, after the stream has settled one way or the other.
              onDone: () => {},
              onError: (error, kind) => { failure ??= composedFailure(error, kind); },
            },
            controller.signal,
          );
        } catch (err) {
          // fetchWithAuth rejects when the request phase is aborted, and the
          // composed client does not catch it.
          if (controller.signal.aborted || run !== simulationRun) return;
          failure ??= composedFailure(err instanceof Error ? err.message : "");
        }

        if (run !== simulationRun || controller.signal.aborted) return;
        abortController = null;

        // A truncated history is never published: the stepper has no way to say
        // "cut off", so a partial run would read exactly like a finished one.
        // consumeSimulationStream reports a body that ended without the stream's
        // own sentinel as an error, which is what makes that guarantee hold.
        if (failure !== null) {
          set({ status: "error", error: failure, progress: step0.progress });
          return;
        }

        snapshotHistory = [step0, ...collected.flatMap(expandSnapshot).map(expandFusionMarkings)];
        streamingComplete = true;

        // Back to where the stepper actually is. The streamed progress was
        // feedback for the wait, and leaving it would show a full bar beside
        // step 0 of N and then count backwards as the user steps forward.
        await settle(step0.progress);
        return;
      }

      const result = await precomputeSimulationStandalone(
        projection.net,
        simulationTime,
        streamParams,
      );

      if (!result || isPrecomputeError(result)) {
        set({ status: "error", error: result ? result.error : "Failed to precompute simulation" });
        return;
      }

      snapshotHistory = [
        step0,
        ...result.snapshots.flatMap(expandSnapshot).map(projection.expandSnapshot),
      ];
      streamingComplete = true;

      await settle();
    },

    enterSimulationModeAtEnd: async () => {
      await get().enterSimulationModeStepped({ landOnFinalState: true });
    },

    exitSimulationMode: async () => {
      abortController?.abort();
      abortController = null;
      clearRenderLoop();
      const { useStatisticsStore } = await import("@/stores/statistics-store");
      useStatisticsStore.getState().stopCollecting();
      // The statistics panel is per-run: leaving simulation mode closes it so
      // a fresh run never opens with the previous run's panel still showing.
      useUiStore.getState().setStatisticsOpen(false);
      set({
        editorMode: "edit",
        status: "idle",
        error: null,
        progress: 0,
        currentSnapshot: null,
        previousSnapshot: null,
        stepIndex: null,
        snapshotCount: 0,
      });
    },
  };
    },
    {
      name: "simulation-prefs",
      partialize: (state) => ({
        simulationTime: state.simulationTime,
        timeStep: state.timeStep,
        playbackRate: state.playbackRate,
        snapshotInterval: state.snapshotInterval,
        snapshotMode: state.snapshotMode,
        timeUnitScale: state.timeUnitScale,
        smoothAnimations: state.smoothAnimations,
      }),
    },
  ),
);

// ── Time formatting utility ──────────────────────────────────────────────────

export function formatSimTime(t: number, scale: TimeUnitScale): string {
  if (scale === "abstract") return `${t.toFixed(1)} units`;

  const secs =
    scale === "seconds" ? t : scale === "minutes" ? t * 60 : t * 3600;

  if (secs < 60) return `${Math.round(secs)} s`;
  if (secs < 3600) {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return s > 0 ? `${m} m ${s} s` : `${m} m`;
  }
  if (secs < 86400) {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    return m > 0 ? `${h} h ${m} m` : `${h} h`;
  }
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  return h > 0 ? `${d} d ${h} h` : `${d} d`;
}

/**
 * Human-readable label for a playback rate given the time unit scale.
 * e.g. rate=60, scale="seconds" → "1 min/s"
 */
export function formatPlaybackRate(rate: PlaybackRate, scale: TimeUnitScale): string {
  if (scale === "abstract") return `${rate}×`;

  const secsPerFrame =
    scale === "seconds" ? rate : scale === "minutes" ? rate * 60 : rate * 3600;

  if (secsPerFrame < 60) return `${secsPerFrame} s/s`;
  if (secsPerFrame < 3600) return `${secsPerFrame / 60} min/s`;
  if (secsPerFrame < 86400) return `${secsPerFrame / 3600} h/s`;
  return `${secsPerFrame / 86400} d/s`;
}
