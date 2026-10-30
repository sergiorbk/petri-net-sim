import { useCallback, useEffect, useMemo, useState } from "react";
import {
    CheckCheck,
    Download,
    FolderOpen,
    History,
    Maximize2,
    MessageSquarePlus,
    Minimize2,
    MousePointer2,
    Pause,
    Play,
    Scan,
    SkipBack,
    SkipForward,
    X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
    ResponsiveContainer,
    LineChart,
    Line,
    XAxis,
    YAxis,
    Tooltip,
} from "recharts";
import { ReviewCanvas } from "./ReviewCanvas";
import { useTrainingStore, pickTrainingFile } from "@/stores/training-store";
import { useEditorStore } from "@/stores/editor-store";
import { useCanvasTabsStore } from "@/stores/canvas-tabs-store";
import {
    exportArchive,
    inspectArchive,
    saveDownload,
    trainingRequest,
    type BundleInfo,
    type Finding,
    type RevisionChange,
    type SimulationRun,
} from "@/lib/training-client";
import type { SimulationSnapshot } from "@/types/petri";

const button =
    "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-surface-hover disabled:opacity-40";
const input =
    "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm";

export function ReviewWorkspace() {
    const { t } = useTranslation();
    const { archive, info, open, close, adopt } = useTrainingStore();
    const [target, setTarget] = useState<BundleInfo | null>(info);
    const [mode, setMode] = useState<"inspect" | "finding" | "area">("finding");
    const [panel, setPanel] = useState<
        "findings" | "parameters" | "simulation" | "history"
    >("findings");
    const [maximized, setMaximized] = useState(true);
    const [selected, setSelected] = useState<string | null>(null);
    const [findings, setFindings] = useState<Finding[]>([]);
    const [draft, setDraft] = useState<Partial<Finding> | null>(null);
    const [anchorLabel, setAnchorLabel] = useState("");
    const [decision, setDecision] = useState("changes_requested");
    const [comment, setComment] = useState("");
    const [automatic, setAutomatic] = useState(true);
    const [horizons, setHorizons] = useState("100, 1000, 10000");
    const [interval, setIntervalValue] = useState(1);
    const [reason, setReason] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [runs, setRuns] = useState<SimulationRun[]>([]);
    const [activeRun, setActiveRun] = useState<SimulationRun | null>(null);
    const [step, setStep] = useState(0);
    const [playing, setPlaying] = useState(false);
    const [compareId, setCompareId] = useState("");
    const [comparison, setComparison] = useState<BundleInfo | null>(null);
    const [changes, setChanges] = useState<RevisionChange[]>([]);
    useEffect(() => {
        setTarget(info);
    }, [info]);
    useEffect(() => {
        setFindings([]);
        setComment("");
        setRuns([]);
        setActiveRun(null);
        setDraft(null);
        setComparison(null);
        setSelected(null);
        setError("");
    }, [info]);
    useEffect(() => {
        useTrainingStore.setState({
            reviewDirty:
                open &&
                (findings.length > 0 || comment.trim().length > 0 || !!draft),
        });
        return () => {
            useTrainingStore.setState({ reviewDirty: false });
        };
    }, [open, findings, comment, draft]);
    useEffect(() => {
        if (!playing || !activeRun) return;
        const timer = window.setInterval(
            () =>
                setStep((s) => {
                    if (s >= activeRun.trajectory.samples.length - 1) {
                        setPlaying(false);
                        return s;
                    }
                    return s + 1;
                }),
            120,
        );
        return () => window.clearInterval(timer);
    }, [playing, activeRun]);
    const inspect = useCallback((id: string) => {
        setSelected(id);
        setPanel("parameters");
    }, []);
    const addFinding = useCallback(
        (value: Partial<Finding>, label?: string) => {
            if (busy) return;
            setPlaying(false);
            setAnchorLabel(label ?? "");
            setDraft({ severity: "warning", message: "", ...value });
        },
        [busy],
    );
    const snapshot = useMemo<SimulationSnapshot | null>(() => {
        const row = activeRun?.trajectory.samples[step];
        if (!row || !activeRun) return null;
        const markings: Record<string, number> = {},
            buffers: Record<string, number> = {};
        activeRun.trajectory.columns.forEach((column, i) => {
            (column.kind === "place" ? markings : buffers)[column.id] =
                row[i + 1];
        });
        return {
            current_time: row[0],
            step_number: step,
            markings,
            buffers,
            progress: row[0] / (activeRun.horizon || 1),
        };
    }, [activeRun, step]);
    if (!open) return null;
    async function captureCurrent() {
        if (busy) return;
        if (useCanvasTabsStore.getState().activeId !== "main") {
            setError(t("review.useMainCanvas"));
            return;
        }
        setBusy(true);
        setError("");
        try {
            const net = useEditorStore.getState().net;
            const result = await exportArchive({
                net_data: net,
                title: net.name,
            });
            adopt(result.archive, result.info);
        } catch {
            setError(t("review.failed"));
        } finally {
            setBusy(false);
        }
    }
    async function selectVersion(id: string) {
        if (!archive || busy || findings.length) return;
        setBusy(true);
        setError("");
        try {
            setTarget(await inspectArchive(archive, id));
            setSelected(null);
            setActiveRun(null);
            setPlaying(false);
            setComparison(null);
        } catch {
            setError(t("review.failed"));
        } finally {
            setBusy(false);
        }
    }
    async function save() {
        if (
            !target ||
            !archive ||
            !comment.trim() ||
            (!automatic && !reason.trim()) ||
            busy
        )
            return;
        if (useCanvasTabsStore.getState().activeId !== "main") {
            setError(t("review.useMainCanvas"));
            return;
        }
        setBusy(true);
        setError("");
        setPlaying(false);
        try {
            const net = useEditorStore.getState().net;
            const result = await exportArchive({
                net_data: net,
                title: info?.manifest.title ?? net.name,
                archive_base64: archive,
                review: {
                    revision_id: target.revision_id,
                    decision,
                    comment,
                    findings,
                    simulation_horizons: automatic
                        ? horizons
                              .split(/[,;\s]+/)
                              .filter(Boolean)
                              .map(Number)
                        : [],
                    sampling_interval: interval,
                    skip_simulation_reason: automatic ? "" : reason,
                    interactive_runs: runs,
                },
            });
            adopt(result.archive, result.info);
            saveDownload(result.blob, result.name);
            setFindings([]);
            setComment("");
            setRuns([]);
            setActiveRun(null);
            setPanel("history");
        } catch {
            setError(t("review.failed"));
        } finally {
            setBusy(false);
        }
    }
    async function run() {
        if (!target || !archive || busy) return;
        setBusy(true);
        setError("");
        setPlaying(false);
        try {
            const result = await trainingRequest<SimulationRun>("run", {
                archive_base64: archive,
                revision_id: target.revision_id,
                horizon: Number(horizons.split(/[,;\s]+/)[0]) || 100,
                sampling_interval: interval,
            });
            setRuns((old) => [...old, result]);
            setActiveRun(result);
            setStep(0);
        } catch {
            setError(t("review.failed"));
        } finally {
            setBusy(false);
        }
    }
    async function compare() {
        if (!target || !archive || !compareId) return;
        setBusy(true);
        setError("");
        try {
            const [other, diff] = await Promise.all([
                inspectArchive(archive, compareId),
                trainingRequest<RevisionChange[]>("compare", {
                    archive_base64: archive,
                    left: target.revision_id,
                    right: compareId,
                }),
            ]);
            setComparison(other);
            setChanges(diff);
        } catch {
            setError(t("review.failed"));
        } finally {
            setBusy(false);
        }
    }
    const versions = info?.history.revisions ?? [];
    const visibleRuns = runs.filter(
        (run) =>
            run.source_model_sha256 ===
            versions.find((v) => v.id === target?.revision_id)?.model_sha256,
    );
    const versionNumber = (id: string) =>
        versions.findIndex((v) => v.id === id) + 1;
    const selectedElement =
        target &&
        [
            ...target.net_data.places,
            ...target.net_data.transitions,
            ...target.net_data.arcs,
            ...(target.net_data.objects ?? []),
            ...(target.net_data.links ?? []),
        ].find((e) => e.id === selected);
    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
            role="dialog"
            aria-modal="true"
            aria-label={t("review.title")}
            onKeyDown={(e) => e.stopPropagation()}
        >
            <div
                className={`flex min-h-0 min-w-0 flex-col overflow-hidden bg-surface text-text-primary shadow-2xl ${maximized ? "h-full w-full" : "h-[90vh] w-[95vw] rounded-2xl"}`}
            >
                <header className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3">
                    <CheckCheck size={23} className="text-accent" />
                    <div className="min-w-0 flex-1">
                        <h2 className="text-lg font-semibold">
                            {t("review.title")}
                        </h2>
                        <p className="truncate text-xs text-text-muted">
                            {info?.manifest.title ?? t("review.empty")}
                        </p>
                    </div>
                    <button
                        className={button}
                        disabled={busy}
                        onClick={pickTrainingFile}
                    >
                        <FolderOpen size={17} />
                        {t("review.open")}
                    </button>
                    <button
                        className={`${button} bg-accent text-white`}
                        disabled={
                            busy ||
                            !target ||
                            !comment.trim() ||
                            (!automatic && !reason.trim())
                        }
                        onClick={() => void save()}
                    >
                        <Download size={17} />
                        {busy ? t("review.working") : t("review.save")}
                    </button>
                    <button
                        className={button}
                        title={t("review.maximize")}
                        onClick={() => setMaximized(!maximized)}
                    >
                        {maximized ? (
                            <Minimize2 size={17} />
                        ) : (
                            <Maximize2 size={17} />
                        )}
                    </button>
                    <button
                        className={button}
                        aria-label={t("review.close")}
                        disabled={busy}
                        onClick={() => {
                            if (
                                (!findings.length && !comment.trim()) ||
                                window.confirm(t("review.discard"))
                            ) {
                                setFindings([]);
                                setComment("");
                                setDraft(null);
                                close();
                            }
                        }}
                    >
                        <X size={18} />
                    </button>
                </header>
                {error && (
                    <p
                        role="alert"
                        className="bg-red-500/10 px-5 py-2 text-sm text-red-500"
                    >
                        {error}
                    </p>
                )}
                {!target ? (
                    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
                        <History size={40} />
                        <p>{t("review.empty")}</p>
                        <p className="max-w-lg text-center text-sm text-text-muted">
                            {t("review.emptyHint")}
                        </p>
                        <button className={button} onClick={pickTrainingFile}>
                            {t("review.open")}
                        </button>
                        <button
                            className={`${button} bg-accent text-white`}
                            disabled={busy}
                            onClick={() => void captureCurrent()}
                        >
                            {t(
                                busy
                                    ? "review.working"
                                    : "review.captureCurrent",
                            )}
                        </button>
                    </div>
                ) : (
                    <>
                        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface-secondary px-5 py-2">
                            <label className="flex items-center gap-2 text-sm">
                                {t("review.version")}
                                <select
                                    className={input}
                                    value={target.revision_id}
                                    disabled={busy || findings.length > 0}
                                    onChange={(e) =>
                                        void selectVersion(e.target.value)
                                    }
                                >
                                    {versions.map((v, i) => (
                                        <option key={v.id} value={v.id}>
                                            {t("review.versionNumber", {
                                                number: i + 1,
                                            })}
                                        </option>
                                    ))}
                                </select>
                            </label>
                            <span className="mx-2 h-6 border-l border-border" />
                            {(
                                [
                                    ["finding", MessageSquarePlus],
                                    ["area", Scan],
                                    ["inspect", MousePointer2],
                                ] as const
                            ).map(([value, Icon]) => (
                                <button
                                    key={value}
                                    className={`${button} ${mode === value ? "border-accent bg-accent/10 text-accent" : ""}`}
                                    aria-pressed={mode === value}
                                    onClick={() => setMode(value)}
                                >
                                    <Icon size={18} />
                                    {t(`review.mode.${value}`)}
                                </button>
                            ))}
                            <span className="ml-auto text-xs text-text-muted">
                                {t(`review.hint.${mode}`)}
                            </span>
                        </div>
                        {target.warnings.length > 0 && (
                            <p className="bg-amber-500/10 px-5 py-2 text-sm">
                                {t("review.importWarnings", {
                                    count: target.warnings.length,
                                })}
                            </p>
                        )}
                        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
                            <div className="flex min-h-64 min-w-0 flex-1 flex-col">
                                <div className="flex min-h-0 flex-1">
                                    <div className="min-w-0 flex-1">
                                        <ReviewCanvas
                                            key={target.revision_id}
                                            info={target}
                                            mode={mode}
                                            snapshot={snapshot}
                                            onInspect={inspect}
                                            onFinding={addFinding}
                                        />
                                    </div>
                                    {comparison && (
                                        <div className="relative min-w-0 flex-1 border-l border-border">
                                            <button
                                                className="absolute right-3 top-3 z-10 rounded bg-surface p-2"
                                                onClick={() =>
                                                    setComparison(null)
                                                }
                                                aria-label={t(
                                                    "review.closeComparison",
                                                )}
                                            >
                                                <X size={16} />
                                            </button>
                                            <ReviewCanvas
                                                key={comparison.revision_id}
                                                info={comparison}
                                                mode="inspect"
                                                onInspect={() => {}}
                                                onFinding={() => {}}
                                            />
                                        </div>
                                    )}
                                </div>
                                {activeRun && (
                                    <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-2">
                                        <button
                                            className={button}
                                            disabled={step <= 0}
                                            onClick={() => {
                                                setPlaying(false);
                                                setStep(Math.max(0, step - 1));
                                            }}
                                            aria-label={t(
                                                "review.previousStep",
                                            )}
                                        >
                                            <SkipBack size={16} />
                                        </button>
                                        <button
                                            className={button}
                                            onClick={() => setPlaying(!playing)}
                                            aria-label={t("review.playPause")}
                                        >
                                            {playing ? (
                                                <Pause size={16} />
                                            ) : (
                                                <Play size={16} />
                                            )}
                                        </button>
                                        <button
                                            className={button}
                                            disabled={
                                                step >=
                                                activeRun.trajectory.samples
                                                    .length -
                                                    1
                                            }
                                            onClick={() => {
                                                setPlaying(false);
                                                setStep(
                                                    Math.min(
                                                        activeRun.trajectory
                                                            .samples.length - 1,
                                                        step + 1,
                                                    ),
                                                );
                                            }}
                                            aria-label={t("review.nextStep")}
                                        >
                                            <SkipForward size={16} />
                                        </button>
                                        <input
                                            className="min-w-24 flex-1"
                                            type="range"
                                            min={0}
                                            max={Math.max(
                                                0,
                                                activeRun.trajectory.samples
                                                    .length - 1,
                                            )}
                                            value={step}
                                            aria-label={t("review.time")}
                                            onChange={(e) => {
                                                setPlaying(false);
                                                setStep(Number(e.target.value));
                                            }}
                                        />
                                        <span className="text-xs tabular-nums">
                                            {t("review.time")}:{" "}
                                            {snapshot?.current_time ?? 0}
                                        </span>
                                    </div>
                                )}
                            </div>
                            <aside className="flex max-h-[45vh] w-full shrink-0 flex-col border-t border-border lg:max-h-none lg:w-[370px] lg:border-l lg:border-t-0 xl:w-[420px]">
                                <nav className="flex border-b border-border p-2">
                                    {(
                                        [
                                            "findings",
                                            "parameters",
                                            "simulation",
                                            "history",
                                        ] as const
                                    ).map((tab) => (
                                        <button
                                            key={tab}
                                            className={`min-h-10 flex-1 rounded px-2 text-xs font-semibold ${panel === tab ? "bg-accent/10 text-accent" : "text-text-muted"}`}
                                            onClick={() => setPanel(tab)}
                                        >
                                            {t(`review.tabs.${tab}`)}
                                            {tab === "findings" &&
                                            findings.length > 0
                                                ? ` (${findings.length})`
                                                : ""}
                                        </button>
                                    ))}
                                </nav>
                                <fieldset
                                    disabled={busy}
                                    className="min-h-0 min-w-0 flex-1 space-y-4 overflow-y-auto border-0 p-4"
                                >
                                    {panel === "findings" && (
                                        <>
                                            {target.task.task && (
                                                <div className="rounded-xl bg-surface-secondary p-3 text-sm">
                                                    <p className="mb-1 font-semibold">
                                                        {t("review.task")}
                                                    </p>
                                                    <p className="whitespace-pre-wrap">
                                                        {target.task.task}
                                                    </p>
                                                </div>
                                            )}
                                            <label className="block space-y-1 text-sm">
                                                <span>
                                                    {t("review.decision")}
                                                </span>
                                                <select
                                                    className={input}
                                                    value={decision}
                                                    onChange={(e) =>
                                                        setDecision(
                                                            e.target.value,
                                                        )
                                                    }
                                                >
                                                    {[
                                                        "accepted",
                                                        "changes_requested",
                                                        "rejected",
                                                    ].map((d) => (
                                                        <option
                                                            key={d}
                                                            value={d}
                                                        >
                                                            {t(
                                                                `review.decisions.${d}`,
                                                            )}
                                                        </option>
                                                    ))}
                                                </select>
                                            </label>
                                            <label className="block space-y-1 text-sm">
                                                <span>
                                                    {t("review.comment")}
                                                </span>
                                                <textarea
                                                    rows={4}
                                                    className={input}
                                                    value={comment}
                                                    onChange={(e) =>
                                                        setComment(
                                                            e.target.value,
                                                        )
                                                    }
                                                    placeholder={t(
                                                        "review.commentHint",
                                                    )}
                                                />
                                            </label>
                                            <div className="flex items-center justify-between">
                                                <span className="text-sm font-semibold">
                                                    {t("review.tabs.findings")}
                                                </span>
                                                <button
                                                    className={button}
                                                    onClick={() =>
                                                        addFinding({})
                                                    }
                                                >
                                                    <MessageSquarePlus
                                                        size={16}
                                                    />
                                                    {t("review.generalFinding")}
                                                </button>
                                            </div>
                                            {findings.length === 0 && (
                                                <p className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">
                                                    {t("review.noFindings")}
                                                </p>
                                            )}
                                            {findings.map((f, i) => (
                                                <article
                                                    key={i}
                                                    className="rounded-xl border border-border p-3"
                                                >
                                                    <div className="flex items-center justify-between">
                                                        <span className="text-xs font-semibold text-amber-600">
                                                            {t(
                                                                `review.severity.${f.severity}`,
                                                            )}
                                                        </span>
                                                        <button
                                                            className="p-1"
                                                            aria-label={t(
                                                                "review.removeFinding",
                                                            )}
                                                            onClick={() =>
                                                                setFindings(
                                                                    findings.filter(
                                                                        (
                                                                            _,
                                                                            n,
                                                                        ) =>
                                                                            n !==
                                                                            i,
                                                                    ),
                                                                )
                                                            }
                                                        >
                                                            <X size={15} />
                                                        </button>
                                                    </div>
                                                    <p className="mt-2 whitespace-pre-wrap text-sm">
                                                        {f.message}
                                                    </p>
                                                    <p className="mt-2 text-xs text-text-muted">
                                                        {f.region
                                                            ? t(
                                                                  "review.selectedArea",
                                                              )
                                                            : f.element_id
                                                              ? t(
                                                                    "review.linkedElement",
                                                                )
                                                              : t(
                                                                    "review.general",
                                                                )}
                                                    </p>
                                                </article>
                                            ))}
                                        </>
                                    )}
                                    {panel === "parameters" && (
                                        <>
                                            <button
                                                className={button}
                                                onClick={() =>
                                                    setSelected(null)
                                                }
                                            >
                                                {t("review.allParameters")}
                                            </button>
                                            <ParameterList
                                                net={target.net_data}
                                                selected={selectedElement}
                                            />
                                        </>
                                    )}
                                    {panel === "simulation" && (
                                        <>
                                            <p className="text-sm text-text-muted">
                                                {t("review.simulationHint")}
                                            </p>
                                            <label className="flex gap-2 text-sm">
                                                <input
                                                    type="checkbox"
                                                    checked={automatic}
                                                    onChange={(e) =>
                                                        setAutomatic(
                                                            e.target.checked,
                                                        )
                                                    }
                                                />
                                                {t("review.autoRun")}
                                            </label>
                                            <label className="block space-y-1 text-sm">
                                                <span>
                                                    {t("review.horizons")}
                                                </span>
                                                <input
                                                    className={input}
                                                    value={horizons}
                                                    onChange={(e) =>
                                                        setHorizons(
                                                            e.target.value,
                                                        )
                                                    }
                                                />
                                            </label>
                                            <label className="block space-y-1 text-sm">
                                                <span>
                                                    {t("review.sampling")}
                                                </span>
                                                <input
                                                    className={input}
                                                    type="number"
                                                    min={0.001}
                                                    step="any"
                                                    value={interval}
                                                    onChange={(e) =>
                                                        setIntervalValue(
                                                            Number(
                                                                e.target.value,
                                                            ),
                                                        )
                                                    }
                                                />
                                            </label>
                                            {!automatic && (
                                                <label className="block space-y-1 text-sm">
                                                    <span>
                                                        {t("review.skipReason")}
                                                    </span>
                                                    <textarea
                                                        className={input}
                                                        value={reason}
                                                        onChange={(e) =>
                                                            setReason(
                                                                e.target.value,
                                                            )
                                                        }
                                                    />
                                                </label>
                                            )}
                                            <button
                                                className={`${button} w-full bg-emerald-600 text-white`}
                                                disabled={busy}
                                                onClick={() => void run()}
                                            >
                                                <Play size={17} />
                                                {busy
                                                    ? t("review.working")
                                                    : t("review.run")}
                                            </button>
                                            {visibleRuns.map((r, i) => (
                                                <button
                                                    key={i}
                                                    className={`${button} w-full justify-between`}
                                                    onClick={() => {
                                                        setActiveRun(r);
                                                        setStep(0);
                                                        setPlaying(false);
                                                    }}
                                                >
                                                    <span>
                                                        {t("review.runNumber", {
                                                            number: i + 1,
                                                        })}{" "}
                                                        · {r.horizon}
                                                    </span>
                                                    <span>
                                                        {t(
                                                            `review.runStatus.${r.status}`,
                                                        )}
                                                    </span>
                                                </button>
                                            ))}
                                            {activeRun?.error && (
                                                <p className="text-sm text-red-500">
                                                    {activeRun.error}
                                                </p>
                                            )}
                                            {activeRun && (
                                                <RunMonitor run={activeRun} />
                                            )}
                                        </>
                                    )}
                                    {panel === "history" && (
                                        <>
                                            <p className="text-sm text-text-muted">
                                                {t("review.historyHint")}
                                            </p>
                                            <label className="block space-y-1 text-sm">
                                                <span>
                                                    {t("review.compareWith")}
                                                </span>
                                                <select
                                                    className={input}
                                                    value={compareId}
                                                    onChange={(e) =>
                                                        setCompareId(
                                                            e.target.value,
                                                        )
                                                    }
                                                >
                                                    <option value="">
                                                        {t(
                                                            "review.chooseVersion",
                                                        )}
                                                    </option>
                                                    {versions.map((v, i) => (
                                                        <option
                                                            key={v.id}
                                                            value={v.id}
                                                        >
                                                            {t(
                                                                "review.versionNumber",
                                                                {
                                                                    number:
                                                                        i + 1,
                                                                },
                                                            )}
                                                        </option>
                                                    ))}
                                                </select>
                                            </label>
                                            <button
                                                className={`${button} w-full`}
                                                disabled={!compareId || busy}
                                                onClick={() => void compare()}
                                            >
                                                {t("review.compare")}
                                            </button>
                                            {comparison && (
                                                <div className="space-y-2 rounded-xl bg-surface-secondary p-3 text-sm">
                                                    <p className="font-semibold">
                                                        {t("review.changes", {
                                                            count: changes.length,
                                                        })}
                                                    </p>
                                                    {changes
                                                        .slice(0, 100)
                                                        .map((c, i) => (
                                                            <p key={i}>
                                                                {c.name}:{" "}
                                                                {t(
                                                                    `review.change.${c.change}`,
                                                                )}
                                                                {c.change ===
                                                                "changed"
                                                                    ? ` (${c.before ?? "∅"} → ${c.after ?? "∅"})`
                                                                    : ""}
                                                            </p>
                                                        ))}
                                                </div>
                                            )}
                                            {info?.reviews.length === 0 && (
                                                <p className="text-sm text-text-muted">
                                                    {t("review.noHistory")}
                                                </p>
                                            )}
                                            {info?.reviews
                                                .slice()
                                                .reverse()
                                                .map((r, i) => (
                                                    <article
                                                        className="space-y-2 rounded-xl border border-border p-3"
                                                        key={i}
                                                    >
                                                        <div className="flex items-center justify-between">
                                                            <strong className="text-sm">
                                                                {r.reviewer}
                                                            </strong>
                                                            <span className="text-xs text-text-muted">
                                                                {t(
                                                                    `review.reviewerKind.${r.reviewer_kind}`,
                                                                )}
                                                            </span>
                                                        </div>
                                                        <p className="text-xs text-text-muted">
                                                            {t(
                                                                "review.versionNumber",
                                                                {
                                                                    number: versionNumber(
                                                                        r.revision_id,
                                                                    ),
                                                                },
                                                            )}{" "}
                                                            ·{" "}
                                                            {new Date(
                                                                r.created_at,
                                                            ).toLocaleString()}
                                                        </p>
                                                        <p className="text-sm font-medium">
                                                            {t(
                                                                `review.decisions.${r.decision}`,
                                                            )}
                                                        </p>
                                                        <p className="whitespace-pre-wrap text-sm">
                                                            {r.comment}
                                                        </p>
                                                        {r.findings.map(
                                                            (f, n) => (
                                                                <p
                                                                    key={n}
                                                                    className="border-l-2 border-amber-500 pl-2 text-sm"
                                                                >
                                                                    {f.message}
                                                                </p>
                                                            ),
                                                        )}
                                                        {r.simulation && (
                                                            <p className="text-xs text-text-muted">
                                                                {t(
                                                                    "review.savedRuns",
                                                                    {
                                                                        count:
                                                                            r
                                                                                .simulation
                                                                                .automatic_runs
                                                                                .length +
                                                                            r
                                                                                .simulation
                                                                                .interactive_runs
                                                                                .length,
                                                                    },
                                                                )}
                                                                {r.simulation
                                                                    .skip_reason
                                                                    ? ` · ${r.simulation.skip_reason}`
                                                                    : ""}
                                                            </p>
                                                        )}
                                                    </article>
                                                ))}
                                        </>
                                    )}
                                </fieldset>
                            </aside>
                        </div>
                    </>
                )}
                {draft && (
                    <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/40 p-4">
                        <form
                            className="w-full max-w-lg space-y-4 rounded-2xl bg-surface p-6 shadow-2xl"
                            onSubmit={(e) => {
                                e.preventDefault();
                                if (!draft.message?.trim()) return;
                                setFindings([...findings, draft as Finding]);
                                setDraft(null);
                                setPanel("findings");
                            }}
                        >
                            <h3 className="text-lg font-semibold">
                                {t("review.newFinding")}
                            </h3>
                            {anchorLabel && (
                                <p className="text-sm text-text-muted">
                                    {anchorLabel}
                                </p>
                            )}
                            <label className="block space-y-1 text-sm">
                                <span>{t("review.severityLabel")}</span>
                                <select
                                    className={input}
                                    value={draft.severity}
                                    onChange={(e) =>
                                        setDraft({
                                            ...draft,
                                            severity: e.target
                                                .value as Finding["severity"],
                                        })
                                    }
                                >
                                    {["error", "warning", "suggestion"].map(
                                        (s) => (
                                            <option key={s} value={s}>
                                                {t(`review.severity.${s}`)}
                                            </option>
                                        ),
                                    )}
                                </select>
                            </label>
                            <label className="block space-y-1 text-sm">
                                <span>{t("review.findingMessage")}</span>
                                <textarea
                                    className={input}
                                    rows={5}
                                    autoFocus
                                    required
                                    value={draft.message}
                                    onChange={(e) =>
                                        setDraft({
                                            ...draft,
                                            message: e.target.value,
                                        })
                                    }
                                />
                            </label>
                            <div className="flex justify-end gap-2">
                                <button
                                    type="button"
                                    className={button}
                                    onClick={() => setDraft(null)}
                                >
                                    {t("review.cancel")}
                                </button>
                                <button
                                    className={`${button} bg-accent text-white`}
                                    type="submit"
                                >
                                    {t("review.addFinding")}
                                </button>
                            </div>
                        </form>
                    </div>
                )}
            </div>
        </div>
    );
}

function ParameterList({
    net,
    selected,
}: {
    net: BundleInfo["net_data"];
    selected: object | null | undefined;
}) {
    const { t } = useTranslation();
    const groups = selected
        ? [selected]
        : [
              ...net.places,
              ...net.transitions,
              ...net.arcs,
              ...(net.objects ?? []),
              ...(net.links ?? []),
          ];
    const keys = [
        "tokens",
        "mean_delay",
        "distribution",
        "standard_deviation",
        "priority",
        "probability",
        "weight",
        "arc_type",
        "type",
        "quantity",
        "informational",
        "tag",
    ];
    return (
        <>
            <p className="text-sm text-text-muted">
                {t(
                    selected
                        ? "review.parametersSelected"
                        : "review.parametersHint",
                )}
            </p>
            {groups.map((item, i) => {
                const e = item as Record<string, unknown>;
                return (
                    <article
                        key={i}
                        className="rounded-xl border border-border p-3"
                    >
                        <h3 className="mb-2 text-sm font-semibold">
                            {String(e.name ?? t("review.connection"))}
                        </h3>
                        <dl className="space-y-1 text-xs">
                            {keys
                                .filter((k) => k in e)
                                .map((k) => (
                                    <div
                                        className="flex justify-between gap-3"
                                        key={k}
                                    >
                                        <dt className="text-text-muted">
                                            {t(`review.parameters.${k}`)}
                                        </dt>
                                        <dd className="text-right">
                                            {e[k] === null
                                                ? t("review.unspecified")
                                                : String(e[k])}
                                        </dd>
                                    </div>
                                ))}
                        </dl>
                    </article>
                );
            })}
        </>
    );
}

function RunMonitor({ run }: { run: SimulationRun }) {
    const { t } = useTranslation();
    const [column, setColumn] = useState(0);
    const index = Math.min(column, run.trajectory.columns.length - 1);
    const values = run.trajectory.samples.map((row) => ({
        time: row[0],
        value: row[index + 1],
    }));
    return (
        <div className="space-y-3">
            <label className="block text-sm">
                {t("review.monitor")}
                <select
                    className={input}
                    value={index}
                    onChange={(e) => setColumn(Number(e.target.value))}
                >
                    {run.trajectory.columns.map((c, i) => (
                        <option key={i} value={i}>
                            {c.name} · {t(`review.metric.${c.metric}`)}
                        </option>
                    ))}
                </select>
            </label>
            <div className="h-48 w-full">
                <ResponsiveContainer>
                    <LineChart data={values}>
                        <XAxis
                            dataKey="time"
                            type="number"
                            domain={[0, "dataMax"]}
                        />
                        <YAxis />
                        <Tooltip />
                        <Line
                            dataKey="value"
                            name={t("review.value")}
                            type="stepAfter"
                            stroke="#3b82f6"
                            dot={false}
                            isAnimationActive={false}
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>
            <p className="text-xs text-text-muted">
                {t("review.intervalUsed", {
                    value: run.trajectory.effective_interval,
                })}{" "}
                ·{" "}
                {t(
                    run.trajectory.complete
                        ? "review.complete"
                        : "review.incomplete",
                )}
            </p>
        </div>
    );
}
