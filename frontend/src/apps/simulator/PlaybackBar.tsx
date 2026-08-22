import { ChevronLeft, ChevronRight, LineChart, Pause, Play, RotateCcw, SkipForward, Square } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { useStatisticsStore } from "@/stores/statistics-store";
import { useUiStore } from "@/stores/ui-store";
import {
  useSimulationStore,
  formatSimTime,
  formatPlaybackRate,
  type PlaybackRate,
  type SnapshotMode,
  type TimeUnitScale,
} from "@/stores/simulation-store";

const PLAYBACK_RATES: PlaybackRate[] = [1, 10, 60, 600, 3600];

const TIME_UNIT_SCALES: { value: TimeUnitScale; label: string }[] = [
  { value: "seconds",  label: "1 unit = 1 s" },
  { value: "minutes",  label: "1 unit = 1 min" },
  { value: "hours",    label: "1 unit = 1 h" },
  { value: "abstract", label: "Abstract" },
];

const CONTROL_INPUT = cn(
  "rounded border border-border bg-surface px-1.5 py-0.5",
  "text-[11px] text-text-primary focus:outline-none",
  "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
  "disabled:opacity-50",
);

const SEP = "mx-1.5 h-4 w-px shrink-0 bg-border";

export function PlaybackBar() {
  const editorMode = useSimulationStore((s) => s.editorMode);
  if (editorMode === "edit") return <EditBar />;
  return <SimBar />;
}

function EditBar() {
  const { t } = useTranslation();
  const isAuthenticated    = useAuthStore((s) => s.isAuthenticated);
  const simulationTime     = useSimulationStore((s) => s.simulationTime);
  const setSimulationTime  = useSimulationStore((s) => s.setSimulationTime);
  const timeUnitScale      = useSimulationStore((s) => s.timeUnitScale);
  const setTimeUnitScale   = useSimulationStore((s) => s.setTimeUnitScale);
  const snapshotMode       = useSimulationStore((s) => s.snapshotMode);
  const setSnapshotMode    = useSimulationStore((s) => s.setSnapshotMode);
  const timeStep           = useSimulationStore((s) => s.timeStep);
  const setTimeStep        = useSimulationStore((s) => s.setTimeStep);
  const snapshotInterval   = useSimulationStore((s) => s.snapshotInterval);
  const setSnapshotInterval = useSimulationStore((s) => s.setSnapshotInterval);
  const playbackRate       = useSimulationStore((s) => s.playbackRate);
  const setPlaybackRate    = useSimulationStore((s) => s.setPlaybackRate);
  const enterSimulationMode = useSimulationStore((s) => s.enterSimulationMode);
  const enterSimulationModeStepped = useSimulationStore((s) => s.enterSimulationModeStepped);
  const enterSimulationModeAtEnd = useSimulationStore((s) => s.enterSimulationModeAtEnd);

  return (
    <div
      className={cn(
        "flex h-10 shrink-0 items-center gap-1.5 border-t border-border",
        "bg-surface-secondary px-3 overflow-x-auto",
      )}
    >
      <button
        type="button"
        onClick={enterSimulationMode}
        disabled={!isAuthenticated}
        title={isAuthenticated ? t("simulator.runTitle") : t("simulator.signInToRun")}
        className={cn(
          "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors",
          isAuthenticated
            ? "bg-emerald-600 text-white hover:bg-emerald-700"
            : "cursor-not-allowed bg-surface-hover text-text-muted",
        )}
      >
        <Play size={11} />
        {t("simulator.run")}
      </button>

      <button
        type="button"
        // Wrapped, not passed directly: the action takes an options object,
        // and handing it the click event would read as one.
        onClick={() => enterSimulationModeStepped()}
        disabled={!isAuthenticated}
        title={isAuthenticated ? t("simulator.runAndStepTitle") : t("simulator.signInToRun")}
        className={cn(
          "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors",
          isAuthenticated
            ? "bg-surface-hover text-text-primary hover:bg-border"
            : "cursor-not-allowed bg-surface-hover text-text-muted",
        )}
      >
        <ChevronRight size={11} />
        {t("simulator.runAndStep")}
      </button>

      <button
        type="button"
        onClick={enterSimulationModeAtEnd}
        disabled={!isAuthenticated}
        title={isAuthenticated ? t("simulator.runToEndTitle") : t("simulator.signInToRun")}
        className={cn(
          "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors",
          isAuthenticated
            ? "bg-surface-hover text-text-primary hover:bg-border"
            : "cursor-not-allowed bg-surface-hover text-text-muted",
        )}
      >
        <SkipForward size={11} />
        {t("simulator.runToEnd")}
      </button>

      <div className={SEP} />

      <span className="shrink-0 text-[11px] text-text-muted">{t("simulator.duration")}</span>
      <input
        type="number"
        min={1}
        step={100}
        value={simulationTime}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          if (!isNaN(v) && v > 0) setSimulationTime(v);
        }}
        aria-label="Simulation duration"
        className={cn(CONTROL_INPUT, "w-20")}
      />
      <select
        value={timeUnitScale}
        onChange={(e) => setTimeUnitScale(e.target.value as TimeUnitScale)}
        aria-label="Time unit scale"
        className={cn(CONTROL_INPUT, "shrink-0")}
      >
        {TIME_UNIT_SCALES.map((s) => (
          <option key={s.value} value={s.value}>{s.label}</option>
        ))}
      </select>

      <div className={SEP} />

      <div
        role="group"
        aria-label="Snapshot mode"
        className="flex shrink-0 gap-0.5 rounded border border-border p-0.5"
      >
        {(["time", "scientific"] as SnapshotMode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            onClick={() => setSnapshotMode(mode)}
            aria-pressed={snapshotMode === mode}
            className={cn(
              "rounded px-2 py-0.5 text-[11px] font-medium transition-colors",
              snapshotMode === mode
                ? "bg-accent text-white"
                : "text-text-muted hover:text-text-primary",
            )}
          >
            {mode === "time" ? t("simulator.visual") : t("simulator.scientific")}
          </button>
        ))}
      </div>

      {snapshotMode === "time" && (
        <>
          <span className="shrink-0 text-[11px] text-text-muted">{t("simulator.step")}</span>
          <input
            type="number"
            min={0.1}
            step={1}
            value={timeStep}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              if (!isNaN(v) && v > 0) setTimeStep(v);
            }}
            aria-label="Time step per snapshot"
            className={cn(CONTROL_INPUT, "w-14")}
          />
          <div className={SEP} />
          <div
            role="group"
            aria-label="Playback rate"
            className="flex shrink-0 items-center gap-0.5"
          >
            {PLAYBACK_RATES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setPlaybackRate(r)}
                aria-pressed={playbackRate === r}
                title={formatPlaybackRate(r, timeUnitScale)}
                className={cn(
                  "rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors",
                  playbackRate === r
                    ? "bg-accent text-white"
                    : "bg-surface-hover text-text-muted hover:text-text-primary",
                )}
              >
                {formatPlaybackRate(r, timeUnitScale)}
              </button>
            ))}
          </div>
        </>
      )}

      {snapshotMode === "scientific" && (
        <>
          <span className="shrink-0 text-[11px] text-text-muted">{t("simulator.every")}</span>
          <input
            type="number"
            min={1}
            step={10}
            value={snapshotInterval}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              if (!isNaN(v) && v >= 1) setSnapshotInterval(v);
            }}
            aria-label="Snapshot every N steps"
            className={cn(CONTROL_INPUT, "w-16")}
          />
          <span className="shrink-0 text-[11px] text-text-muted">{t("simulator.steps")}</span>
        </>
      )}
    </div>
  );
}

function SimBar() {
  const { t } = useTranslation();
  const status          = useSimulationStore((s) => s.status);
  const progress        = useSimulationStore((s) => s.progress);
  const currentSnapshot = useSimulationStore((s) => s.currentSnapshot);
  const simulationTime  = useSimulationStore((s) => s.simulationTime);
  const playbackRate    = useSimulationStore((s) => s.playbackRate);
  const setPlaybackRate = useSimulationStore((s) => s.setPlaybackRate);
  const timeUnitScale   = useSimulationStore((s) => s.timeUnitScale);
  const snapshotMode    = useSimulationStore((s) => s.snapshotMode);
  const stepIndex       = useSimulationStore((s) => s.stepIndex);
  const snapshotCount   = useSimulationStore((s) => s.snapshotCount);
  const error           = useSimulationStore((s) => s.error);

  const pauseSimulation   = useSimulationStore((s) => s.pauseSimulation);
  const resumeSimulation  = useSimulationStore((s) => s.resumeSimulation);
  const stepForward       = useSimulationStore((s) => s.stepForward);
  const stepBackward      = useSimulationStore((s) => s.stepBackward);
  const exitSimulationMode = useSimulationStore((s) => s.exitSimulationMode);
  const enterSimulationMode = useSimulationStore((s) => s.enterSimulationMode);
  const resetSimulation   = useSimulationStore((s) => s.resetSimulation);

  const hasStatisticsData = useStatisticsStore(
    (s) => Object.keys(s.placeMarkings).length > 0 || Object.keys(s.transitionBuffers).length > 0,
  );
  const setStatisticsOpen = useUiStore((s) => s.setStatisticsOpen);

  const isRunning  = status === "running";
  const isPaused   = status === "paused";
  const isDone     = status === "done";
  const isError    = status === "error";
  const isIdle     = status === "idle";
  const isLoading  = status === "loading";

  const simTime    = currentSnapshot?.current_time ?? 0;
  const totalLabel = formatSimTime(simulationTime, timeUnitScale);

  return (
    <div
      className={cn(
        "flex h-10 shrink-0 items-center gap-1 border-t border-border",
        "bg-surface-secondary px-3 overflow-x-auto",
      )}
    >
      {(isRunning || isPaused) && (
        <button
          type="button"
          onClick={isPaused ? resumeSimulation : pauseSimulation}
          title={isPaused ? t("simulator.resumeTitle") : t("simulator.pauseTitle")}
          className={cn(ICON_BTN)}
        >
          {isPaused ? <Play size={14} /> : <Pause size={14} />}
        </button>
      )}

      {isPaused && stepIndex !== null && (
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            onClick={stepBackward}
            disabled={stepIndex === 0}
            title={t("simulator.stepBackTitle")}
            className={cn(ICON_BTN)}
          >
            <ChevronLeft size={14} />
          </button>
          <span className="min-w-[52px] text-center text-[11px] tabular-nums text-text-muted">
            {stepIndex} / {snapshotCount - 1}
          </span>
          <button
            type="button"
            onClick={stepForward}
            disabled={stepIndex >= snapshotCount - 1}
            title={t("simulator.stepForwardTitle")}
            className={cn(ICON_BTN)}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      )}

      {(isDone || isError || isIdle) && (
        <button
          type="button"
          onClick={enterSimulationMode}
          title={t("simulator.rerunTitle")}
          className={cn(ICON_BTN)}
        >
          <RotateCcw size={13} />
        </button>
      )}

      {(isDone || isError) && (
        <button
          type="button"
          onClick={resetSimulation}
          title={t("simulator.resetTitle")}
          className={cn(
            "shrink-0 rounded px-2 py-0.5 text-[11px] text-text-muted",
            "hover:bg-surface-hover hover:text-text-primary transition-colors",
          )}
        >
          {t("simulator.reset")}
        </button>
      )}

      {/* Also while paused, not only when a run played to its end: landing
          straight on the final state leaves the stepper paused there with the
          whole run already collected, and that is exactly when these numbers
          are wanted. */}
      {(isDone || isPaused) && hasStatisticsData && (
        <button
          type="button"
          onClick={() => setStatisticsOpen(true)}
          title={t("simulator.statisticsTitle")}
          className={cn(
            "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium",
            "bg-accent text-white transition-colors hover:bg-accent-hover",
          )}
        >
          <LineChart size={13} />
          {t("simulator.statistics")}
        </button>
      )}

      <button
        type="button"
        onClick={exitSimulationMode}
        title={t("simulator.stopTitle")}
        className={cn(ICON_BTN, "text-red-500 hover:text-red-400")}
      >
        <Square size={13} />
      </button>

      <div className={SEP} />

      {snapshotMode === "time" && (
        <>
          <div
            role="group"
            aria-label="Playback rate"
            className="flex shrink-0 items-center gap-0.5"
          >
            {PLAYBACK_RATES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setPlaybackRate(r)}
                aria-pressed={playbackRate === r}
                title={formatPlaybackRate(r, timeUnitScale)}
                className={cn(
                  "rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors",
                  playbackRate === r
                    ? "bg-accent text-white"
                    : "bg-surface-hover text-text-muted hover:text-text-primary",
                )}
              >
                {formatPlaybackRate(r, timeUnitScale)}
              </button>
            ))}
          </div>
          <div className={SEP} />
        </>
      )}

      <div className="flex shrink-0 items-center gap-3 text-[11px] text-text-muted">
        {isLoading && (
          <span className="flex items-center gap-1.5 text-blue-500">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-blue-400 border-t-transparent" />
            {t("simulator.computing")}
          </span>
        )}
        {isRunning && (
          <span className="flex items-center gap-1.5 text-emerald-500">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
            </span>
            {t("simulator.running")}
          </span>
        )}
        {isPaused && (
          <span className="text-amber-500">{t("simulator.paused")}</span>
        )}
        {isDone && <span>{t("simulator.done")}</span>}

        <span className="tabular-nums">
          t = {formatSimTime(simTime, timeUnitScale)}
          <span className="text-text-muted/60"> / {totalLabel}</span>
        </span>

        <span>{Math.round(progress * 100)}%</span>

        {currentSnapshot && (
          <span>{t("simulator.step")} {currentSnapshot.step_number}</span>
        )}
      </div>

      <div className="relative ml-auto h-1 w-40 shrink-0 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-700">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-emerald-500 transition-[width] duration-200"
          style={{ width: `${progress * 100}%` }}
        />
      </div>

      {error && (
        <span className="ml-2 shrink-0 text-[11px] text-red-500">{error}</span>
      )}
    </div>
  );
}

export function ReadOnlyBar() {
  const { t } = useTranslation();
  return (
    <div
      className={cn(
        "flex h-10 shrink-0 items-center justify-between border-t border-border",
        "bg-surface-secondary px-4",
      )}
    >
      <div className="flex items-center gap-2 text-[11px] text-text-muted">
        <Play size={12} className="opacity-40" />
        <span>{t("simulator.readOnlyNotice")}</span>
        <Link
          to="/login"
          className="font-medium text-accent hover:underline"
        >
          {t("simulator.signInToRun")}
        </Link>
      </div>
    </div>
  );
}

const ICON_BTN = cn(
  "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
  "text-text-secondary transition-colors",
  "hover:bg-surface-hover hover:text-text-primary",
  "disabled:cursor-not-allowed disabled:opacity-40",
);
