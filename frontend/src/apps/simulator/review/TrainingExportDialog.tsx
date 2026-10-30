import { useState } from "react";
import { useTranslation } from "react-i18next";
import { exportTrainingData, useTrainingStore } from "@/stores/training-store";

export function TrainingExportDialog({ onClose }: { onClose: () => void }) {
    const { t } = useTranslation();
    const info = useTrainingStore((s) => s.info);
    const [task, setTask] = useState(info?.task.task ?? "");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(false);
    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
            role="dialog"
            aria-modal="true"
            aria-label={t("review.exportTitle")}
        >
            <form
                className="w-full max-w-xl space-y-4 rounded-2xl bg-surface p-6 text-text-primary shadow-2xl"
                onSubmit={async (e) => {
                    e.preventDefault();
                    setBusy(true);
                    setError(false);
                    try {
                        await exportTrainingData(task);
                        onClose();
                    } catch {
                        setError(true);
                    } finally {
                        setBusy(false);
                    }
                }}
            >
                <h2 className="text-lg font-semibold">
                    {t("review.exportTitle")}
                </h2>
                <p className="text-sm text-text-muted">
                    {t("review.exportHint")}
                </p>
                <label className="block space-y-2 text-sm">
                    <span>{t("review.task")}</span>
                    <textarea
                        className="w-full rounded-lg border border-border bg-surface-secondary p-3"
                        rows={5}
                        value={task}
                        onChange={(e) => setTask(e.target.value)}
                    />
                </label>
                {error && (
                    <p role="alert" className="text-sm text-red-500">
                        {t("review.exportFailed")}
                    </p>
                )}
                <div className="flex justify-end gap-3">
                    <button
                        type="button"
                        className="rounded-lg border border-border px-4 py-2 text-sm"
                        disabled={busy}
                        onClick={onClose}
                    >
                        {t("review.cancel")}
                    </button>
                    <button
                        className="rounded-lg bg-accent px-4 py-2 text-sm text-white"
                        disabled={busy}
                    >
                        {t(busy ? "review.working" : "review.downloadArchive")}
                    </button>
                </div>
            </form>
        </div>
    );
}
