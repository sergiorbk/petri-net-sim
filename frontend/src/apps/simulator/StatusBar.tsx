import { useState } from "react";
import { Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useEditorStore, type EditorTool } from "@/stores/editor-store";
import { useAuthStore } from "@/stores/auth-store";
import { useSimulationStore, formatSimTime, type EditorMode } from "@/stores/simulation-store";
import { saveNet } from "./hooks/use-file-actions";

const TOOL_LABEL_KEYS: Record<EditorTool, string> = {
  select: "toolPalette.select",
  "select-box": "toolPalette.selectBox",
  "select-lasso": "toolPalette.selectLasso",
  delete: "toolPalette.delete",
  "add-place": "toolPalette.addPlace",
  "add-transition": "toolPalette.addTransition",
  "add-arc": "toolPalette.addArc",
  "add-object": "toolPalette.addObject",
};

export function StatusBar() {
  const { t } = useTranslation();
  const net = useEditorStore((s) => s.net);
  const tool = useEditorStore((s) => s.tool);
  const selection = useEditorStore((s) => s.selection);
  const dirty = useEditorStore((s) => s.dirty);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  const editorMode = useSimulationStore((s) => s.editorMode);
  const currentSnapshot = useSimulationStore((s) => s.currentSnapshot);
  const timeUnitScale = useSimulationStore((s) => s.timeUnitScale);

  const [saving, setSaving] = useState(false);

  const selectionSummary = describeSelection(t, selection.length);
  const isSimulating = editorMode === "simulating";
  const canSave = dirty && isAuthenticated && !isSimulating;

  async function handleSave() {
    if (!canSave || saving) return;
    setSaving(true);
    try {
      await saveNet();
    } finally {
      setSaving(false);
    }
  }

  return (
    <footer
      role="status"
      aria-label="Editor status"
      className={cn(
        "flex h-7 shrink-0 items-center gap-4 border-t border-border",
        "bg-surface-secondary px-3 text-[11px] text-text-muted",
      )}
    >
      <Cell label={t("statusBar.places")}>{net.places.length}</Cell>
      <Cell label={t("statusBar.transitions")}>{net.transitions.length}</Cell>
      <Cell label={t("statusBar.arcs")}>{net.arcs.length}</Cell>
      <span className="ml-auto flex items-center gap-3">
        {isSimulating && currentSnapshot && (
          <>
            <Cell label={t("statusBar.simTime")}>
              {formatSimTime(currentSnapshot.current_time, timeUnitScale)}
            </Cell>
            <Cell label={t("statusBar.step")}>{currentSnapshot.step_number}</Cell>
          </>
        )}
        {!isSimulating && (
          <>
            <Cell label={t("statusBar.tool")}>{t(TOOL_LABEL_KEYS[tool])}</Cell>
            <Cell label={t("statusBar.selection")}>{selectionSummary}</Cell>
          </>
        )}
        <ModeIndicator mode={editorMode} dirty={dirty} />
        {canSave && (
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            title="Save (Ctrl+S)"
            className={cn(
              "flex items-center gap-1 rounded px-2 py-0.5",
              "text-[10px] font-medium transition-colors",
              saving
                ? "cursor-wait text-text-muted"
                : "bg-accent/10 text-accent hover:bg-accent/20",
            )}
          >
            <Save size={10} />
            {saving ? t("statusBar.saving") : t("statusBar.save")}
          </button>
        )}
      </span>
    </footer>
  );
}

function ModeIndicator({ mode, dirty }: { mode: EditorMode; dirty: boolean }) {
  const { t } = useTranslation();
  if (mode === "simulating") {
    return (
      <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
        {t("statusBar.simulation")}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[10px] font-medium",
        dirty
          ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
          : "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
      )}
    >
      {dirty ? t("statusBar.unsavedChanges") : t("statusBar.saved")}
    </span>
  );
}

function Cell({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <span className="flex items-center gap-1">
      <span className="text-text-muted/70">{label}:</span>
      <span className="font-medium text-text-secondary">{children}</span>
    </span>
  );
}

function describeSelection(t: ReturnType<typeof useTranslation>["t"], count: number): string {
  if (count === 0) return t("statusBar.selectionNone");
  if (count === 1) return t("statusBar.selectionOne");
  return t("statusBar.selectionMany", { count });
}
