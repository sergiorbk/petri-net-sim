import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor-store";
import type { PetriNetData } from "@/types/petri";
import { exportPnml, buildExportFilename } from "@/lib/pnml-export";
import { downloadNetworkImage } from "@/lib/export-client";
import { toast } from "@/stores/toast-store";

type ExportFormat = "pnml" | "xml" | "png";

const FORMAT_IDS: readonly { id: ExportFormat; enabled: boolean }[] = [
    { id: "pnml", enabled: true },
    { id: "xml", enabled: true },
    { id: "png", enabled: true },
];

function downloadBlob(content: string, filename: string, mime: string) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

interface ExportDialogProps {
    onClose: () => void;
    /**
     * What to export. Defaults to whatever the editor is currently showing,
     * which is what the File menu means. A chat's version card passes its
     * own snapshot instead: that card is about one particular version, and
     * exporting the editor's net from it would hand over a different model
     * than the one the button sits under.
     */
    net?: PetriNetData;
    /** Version number to put in the filename, when the source has one. */
    version?: number;
    /** Stable id for the filename, so the same net exports under one name. */
    id?: string;
}

export function ExportDialog({
    onClose,
    net: netProp,
    version,
    id,
}: ExportDialogProps) {
    const { t } = useTranslation();
    const [selected, setSelected] = useState<ExportFormat>("pnml");
    const [scope, setScope] = useState("document");
    const [imageFormat, setImageFormat] = useState("png");
    const [scale, setScale] = useState(1);
    const [maxDimension, setMaxDimension] = useState(4096);
    const [transparent, setTransparent] = useState(false);
    const [parameters, setParameters] = useState(true);
    const [overview, setOverview] = useState(true);
    const [objectIndices, setObjectIndices] = useState<number[]>([]);
    const [exporting, setExporting] = useState(false);
    const imageNet = netProp ?? useEditorStore.getState().net;
    const dialogRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        function onKey(e: KeyboardEvent) {
            if (e.key === "Escape") onClose();
        }
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, [onClose]);

    const handleExport = useCallback(async () => {
        const editor = useEditorStore.getState();
        const net = netProp ?? editor.net;
        if (selected === "png") {
            setExporting(true);
            try {
                await downloadNetworkImage(net, {
                    scope,
                    format: scope === "objects" ? "zip" : imageFormat,
                    scale,
                    max_dimension: maxDimension,
                    transparent_background: transparent,
                    include_parameters: parameters,
                    include_overview: overview,
                    ...(scope === "objects" && objectIndices.length
                        ? { object_indices: objectIndices }
                        : {}),
                    ...(scope === "selection"
                        ? {
                              element_ids: editor.selection
                                  .filter((s) =>
                                      [
                                          "place",
                                          "transition",
                                          "object",
                                          "arc",
                                          "link",
                                      ].includes(s.kind),
                                  )
                                  .map((s) => s.id),
                          }
                        : {}),
                });
                onClose();
            } catch {
                toast(t("trainingExport.failed"), "error");
            } finally {
                setExporting(false);
            }
            return;
        }
        let xml: string;
        try {
            xml = exportPnml(net, (message) => toast(message, "warning"));
        } catch (err) {
            // A composed canvas can be drawn in ways PNML has no shape for, an
            // object linked to itself above all. Saying so beats a button that
            // looks like it worked and left no file.
            toast(
                err instanceof Error
                    ? err.message
                    : "This canvas cannot be exported as PNML",
            );
            return;
        }
        const filename = buildExportFilename(net.name, selected, {
            version,
            id: id ?? editor.cloudNetId ?? undefined,
        });
        downloadBlob(xml, filename, "application/xml");
        onClose();
    }, [
        selected,
        onClose,
        netProp,
        version,
        id,
        t,
        scope,
        imageFormat,
        scale,
        maxDimension,
        transparent,
        parameters,
        overview,
        objectIndices,
    ]);

    const selectedFmt = FORMAT_IDS.find((f) => f.id === selected);

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-backdrop"
            onClick={(e) => {
                if (e.target === e.currentTarget) onClose();
            }}
        >
            <div
                ref={dialogRef}
                role="dialog"
                aria-label={t("dialog.export.title")}
                className={cn(
                    "w-full max-w-md rounded-xl border border-border",
                    "bg-surface p-6 shadow-xl",
                )}
            >
                <h2 className="mb-4 text-lg font-semibold text-text-primary">
                    {t("dialog.export.title")}
                </h2>

                <fieldset className="mb-5">
                    <legend className="mb-2 text-sm font-medium text-text-secondary">
                        {t("dialog.export.format")}
                    </legend>
                    <div className="flex flex-col gap-1.5">
                        {FORMAT_IDS.map((fmt) => (
                            <label
                                key={fmt.id}
                                className={cn(
                                    "flex items-start gap-3 rounded-lg border px-3 py-2.5",
                                    "transition-colors",
                                    fmt.enabled
                                        ? selected === fmt.id
                                            ? "border-accent bg-accent/5"
                                            : "border-border hover:bg-surface-hover cursor-pointer"
                                        : "cursor-not-allowed border-border opacity-50",
                                )}
                            >
                                <input
                                    type="radio"
                                    name="export-format"
                                    value={fmt.id}
                                    checked={selected === fmt.id}
                                    disabled={!fmt.enabled}
                                    onChange={() => setSelected(fmt.id)}
                                    className="mt-0.5"
                                />
                                <div className="min-w-0">
                                    <span className="text-sm font-medium text-text-primary">
                                        {t(`dialog.export.${fmt.id}.label`)}
                                    </span>
                                    {!fmt.enabled && (
                                        <span className="ml-2 text-[10px] font-medium text-text-muted">
                                            {t("common.comingSoon")}
                                        </span>
                                    )}
                                    <p className="text-xs text-text-muted">
                                        {t(
                                            `dialog.export.${fmt.id}.description`,
                                        )}
                                    </p>
                                </div>
                            </label>
                        ))}
                    </div>
                </fieldset>
                {selected === "png" && (
                    <fieldset className="my-4 max-h-[45vh] space-y-3 overflow-y-auto text-sm">
                        <label className="block space-y-1">
                            <span>{t("review.imageScope")}</span>
                            <select
                                className="w-full rounded border border-border bg-surface p-2"
                                value={scope}
                                onChange={(e) => setScope(e.target.value)}
                            >
                                {[
                                    "document",
                                    "active",
                                    "objects",
                                    "selection",
                                ].map((s) => (
                                    <option key={s} value={s}>
                                        {t(`review.scopes.${s}`)}
                                    </option>
                                ))}
                            </select>
                        </label>
                        {scope !== "objects" && (
                            <label className="block space-y-1">
                                <span>{t("review.imageFormat")}</span>
                                <select
                                    className="w-full rounded border border-border bg-surface p-2"
                                    value={imageFormat}
                                    onChange={(e) =>
                                        setImageFormat(e.target.value)
                                    }
                                >
                                    <option value="png">PNG</option>
                                    <option value="zip">ZIP</option>
                                </select>
                            </label>
                        )}
                        {scope === "objects" && (
                            <>
                                <label className="flex gap-2">
                                    <input
                                        type="checkbox"
                                        checked={overview}
                                        onChange={(e) =>
                                            setOverview(e.target.checked)
                                        }
                                    />
                                    {t("review.includeOverview")}
                                </label>
                                <p className="text-xs text-text-muted">
                                    {t("review.allObjectsHint")}
                                </p>
                                {imageNet.objects?.map((o, i) => (
                                    <label key={o.id} className="flex gap-2">
                                        <input
                                            type="checkbox"
                                            checked={objectIndices.includes(i)}
                                            onChange={(e) =>
                                                setObjectIndices(
                                                    e.target.checked
                                                        ? [...objectIndices, i]
                                                        : objectIndices.filter(
                                                              (n) => n !== i,
                                                          ),
                                                )
                                            }
                                        />
                                        {o.name}
                                    </label>
                                ))}
                            </>
                        )}
                        <label className="block space-y-1">
                            <span>{t("review.imageScale")}</span>
                            <input
                                className="w-full rounded border border-border bg-surface p-2"
                                type="number"
                                min={0.1}
                                max={4}
                                step={0.1}
                                value={scale}
                                onChange={(e) =>
                                    setScale(Number(e.target.value))
                                }
                            />
                        </label>
                        <label className="block space-y-1">
                            <span>{t("review.maxDimension")}</span>
                            <select
                                className="w-full rounded border border-border bg-surface p-2"
                                value={maxDimension}
                                onChange={(e) =>
                                    setMaxDimension(Number(e.target.value))
                                }
                            >
                                {[1024, 2048, 4096, 8192].map((n) => (
                                    <option key={n} value={n}>
                                        {n}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="flex gap-2">
                            <input
                                type="checkbox"
                                checked={transparent}
                                onChange={(e) =>
                                    setTransparent(e.target.checked)
                                }
                            />
                            {t("review.transparent")}
                        </label>
                        <label className="flex gap-2">
                            <input
                                type="checkbox"
                                checked={parameters}
                                onChange={(e) =>
                                    setParameters(e.target.checked)
                                }
                            />
                            {t("review.includeParameters")}
                        </label>
                    </fieldset>
                )}

                <div className="flex items-center justify-end gap-2">
                    <button
                        type="button"
                        onClick={onClose}
                        className={cn(
                            "rounded-lg px-4 py-2 text-sm font-medium",
                            "text-text-secondary hover:bg-surface-hover transition-colors",
                        )}
                    >
                        {t("common.cancel")}
                    </button>
                    <button
                        type="button"
                        onClick={handleExport}
                        disabled={!selectedFmt?.enabled || exporting}
                        className={cn(
                            "rounded-lg px-4 py-2 text-sm font-medium text-white",
                            "bg-accent hover:bg-accent-hover transition-colors",
                            "disabled:cursor-not-allowed disabled:opacity-50",
                        )}
                    >
                        {t("dialog.export.submit")}
                    </button>
                </div>
            </div>
        </div>
    );
}
