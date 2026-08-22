import { create } from "zustand";
import { useSimulationStore } from "@/stores/simulation-store";
import type { SimulationSnapshot } from "@/types/petri";

interface SeriesPoint {
  time: number;
  value: number;
}

interface StatisticsState {
  placeMarkings: Record<string, SeriesPoint[]>;
  transitionBuffers: Record<string, SeriesPoint[]>;
  collecting: boolean;

  startCollecting: () => void;
  stopCollecting: () => void;
  reset: () => void;
  /**
   * Record a whole run at once, for a run that was never animated.
   *
   * The subscription below samples `currentSnapshot` as the render loop
   * advances it, which is the entire series when a run plays out. Jumping
   * straight to the final state skips that loop, so the collector would see
   * one point and the panel would draw two dots where a run should be.
   */
  recordSnapshots: (snapshots: SimulationSnapshot[]) => void;
}

export const useStatisticsStore = create<StatisticsState>((set) => ({
  placeMarkings: {},
  transitionBuffers: {},
  collecting: false,

  startCollecting: () => {
    set({ collecting: true, placeMarkings: {}, transitionBuffers: {} });
  },

  stopCollecting: () => {
    set({ collecting: false });
  },

  reset: () => {
    set({ placeMarkings: {}, transitionBuffers: {}, collecting: false });
  },

  recordSnapshots: (snapshots) => {
    if (snapshots.length === 0) return;

    const pm: Record<string, SeriesPoint[]> = {};
    const tb: Record<string, SeriesPoint[]> = {};
    for (const snap of snapshots) {
      for (const [id, value] of Object.entries(snap.markings)) {
        (pm[id] ??= []).push({ time: snap.current_time, value });
      }
      for (const [id, value] of Object.entries(snap.buffers)) {
        (tb[id] ??= []).push({ time: snap.current_time, value });
      }
    }

    // Claim the last step as already seen, so the state change that puts the
    // final snapshot on the canvas does not append it a second time.
    prevStepNumber = snapshots[snapshots.length - 1].step_number;

    set({ placeMarkings: pm, transitionBuffers: tb });
  },
}));

let prevStepNumber = -1;

useSimulationStore.subscribe((state) => {
  const { collecting } = useStatisticsStore.getState();
  if (!collecting) return;

  const snap = state.currentSnapshot;
  if (!snap || snap.step_number === prevStepNumber) return;
  prevStepNumber = snap.step_number;

  useStatisticsStore.setState((s) => {
    const pm = { ...s.placeMarkings };
    for (const [id, val] of Object.entries(snap.markings)) {
      const arr = pm[id] ?? [];
      arr.push({ time: snap.current_time, value: val });
      pm[id] = arr;
    }

    const tb = { ...s.transitionBuffers };
    for (const [id, val] of Object.entries(snap.buffers)) {
      const arr = tb[id] ?? [];
      arr.push({ time: snap.current_time, value: val });
      tb[id] = arr;
    }

    return { placeMarkings: pm, transitionBuffers: tb };
  });
});
