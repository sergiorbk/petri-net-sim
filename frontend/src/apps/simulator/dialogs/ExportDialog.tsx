import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor-store";
import type { PetriNetData } from "@/types/petri";
import { exportPnml, buildExportFilename } from "@/lib/pnml-export";
import { toast } from "@/stores/toast-store";

/**
 * Both write the same PNML document; only the file extension differs.
 * PNML is an XML dialect, and some tools accept a `.xml` file and refuse
 * an unfamiliar extension without ever looking inside it -- so the choice
 * is which name the file leaves under, not what it contains.
 *
 * JSON, PNG and SVG used to sit here as permanently disabled options. An
 * option that has never been available is not a promise, it is clutter,
 * and it made the one real choice look like a quarter of the menu.
 */
type ExportFormat = "pnml" | "xml";

const FORMAT_IDS: readonly { id: ExportFormat; enabled: boolean }[] = [
  { id: "pnml", enabled: true },
  { id: "xml", enabled: true },
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

export function ExportDialog({ onClose, net: netProp, version, id }: ExportDialogProps) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<ExportFormat>("pnml");
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleExport = useCallback(() => {
    const editor = useEditorStore.getState();
    const net = netProp ?? editor.net;
    let xml: string;
    try {
      xml = exportPnml(net);
    } catch (err) {
      // A composed canvas can be drawn in ways PNML has no shape for, an
      // object linked to itself above all. Saying so beats a button that
      // looks like it worked and left no file.
      toast(err instanceof Error ? err.message : "This canvas cannot be exported as PNML");
      return;
    }
    const filename = buildExportFilename(net.name, selected, {
      version,
      id: id ?? editor.cloudNetId ?? undefined,
    });
    downloadBlob(xml, filename, "application/xml");
    onClose();
  }, [selected, onClose, netProp, version, id]);

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
                    {t(`dialog.export.${fmt.id}.description`)}
                  </p>
                </div>
              </label>
            ))}
          </div>
        </fieldset>

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
            disabled={!selectedFmt?.enabled}
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
