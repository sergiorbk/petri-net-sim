import { useCallback, useEffect } from "react";
import { useEditorStore, type EditorTool } from "@/stores/editor-store";
import { useSimulationStore } from "@/stores/simulation-store";
import { useUiStore } from "@/stores/ui-store";
import { parsePnml, summarizeImportWarnings } from "@/lib/pnml-import";
import { TopBar } from "./TopBar";
import { EditorCanvas } from "./EditorCanvas";
import { CanvasTabsBar } from "./CanvasTabsBar";
import { LeftPanel } from "./LeftPanel/LeftPanel";
import { TOOLS } from "./LeftPanel/ToolPalette";
import { PropertyInspector } from "./PropertyInspector";
import { PlaybackBar, ReadOnlyBar } from "./PlaybackBar";
import { StatusBar } from "./StatusBar";
import { StatisticsPanel } from "./StatisticsPanel/StatisticsPanel";
import { saveNet } from "./hooks/use-file-actions";
import { toast } from "@/stores/toast-store";

// Keyed by event.code so shortcuts work regardless of keyboard layout.
// Derived from the palette so a tool can never advertise a shortcut this
// handler does not implement (B/L/D/F used to be shown but dead).
export const TOOL_SHORTCUTS: Record<string, EditorTool> = Object.fromEntries(
  TOOLS.map((tool) => [`Key${tool.shortcut}`, tool.id]),
);

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export function SimulatorApp({ readOnly = false }: { readOnly?: boolean }) {
  const setTool = useEditorStore((s) => s.setTool);
  const editorMode = useSimulationStore((s) => s.editorMode);
  const isSimulating = editorMode === "simulating";
  const statisticsOpen = useUiStore((s) => s.statisticsOpen);

  useEffect(() => {
    if (readOnly) return;
    function onKey(event: KeyboardEvent) {
      if (isSimulating) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      const next = TOOL_SHORTCUTS[event.code];
      if (!next) return;
      event.preventDefault();
      setTool(next);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setTool, isSimulating, readOnly]);

  useGlobalShortcuts(readOnly);

  const handleDrop = useCallback((event: React.DragEvent) => {
    if (readOnly) return;
    event.preventDefault();

    if (event.dataTransfer.types.includes("application/petri-object-id")) {
      return;
    }

    const file = event.dataTransfer.files[0];
    if (!file || !file.name.endsWith(".pnml")) return;

    // Same import path as File > Import and a drop on the canvas itself: an
    // undoable merge into the open document. Replacing the whole net here
    // used to clear cloudNetId, which NetLoader answered by re-fetching the
    // route's net right over the freshly dropped file.
    file.text().then((xml) => {
      try {
        const { data, warnings } = parsePnml(xml);
        if (warnings.length > 0) {
          console.warn("PNML import warnings:", warnings);
          toast(summarizeImportWarnings(warnings), "warning");
        }
        window.dispatchEvent(new CustomEvent("petri:import-pnml", { detail: data }));
      } catch (err) {
        toast(
          `Failed to parse PNML file: ${err instanceof Error ? err.message : String(err)}`,
          "error",
        );
      }
    });
  }, []);

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, []);

  return (
    <div
      className="flex h-full min-h-0 w-full flex-col"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
    >
      {!readOnly && <TopBar />}
      <div className="flex min-h-0 flex-1">
        {!isSimulating && !readOnly && <LeftPanel />}
        <main className="relative min-w-0 flex-1">
          <EditorCanvas />
          {isSimulating && <ModeBadge />}
          {statisticsOpen && <StatisticsPanel />}
        </main>
        <PropertyInspector readOnly={isSimulating || readOnly} />
      </div>
      {!readOnly && <CanvasTabsBar />}
      {readOnly ? <ReadOnlyBar /> : <PlaybackBar />}
      {!readOnly && <StatusBar />}
    </div>
  );
}

function useGlobalShortcuts(readOnly = false) {
  useEffect(() => {
    if (readOnly) return;
    function onKey(event: KeyboardEvent) {
      const ctrl = event.ctrlKey || event.metaKey;

      if (ctrl) {
        const code = event.code;

        if (code === "KeyZ" && !event.shiftKey) {
          event.preventDefault();
          useEditorStore.getState().undo();
          return;
        }
        if ((code === "KeyZ" && event.shiftKey) || code === "KeyY") {
          event.preventDefault();
          useEditorStore.getState().redo();
          return;
        }
        if (code === "KeyC" && !isTypingTarget(event.target)) {
          event.preventDefault();
          useEditorStore.getState().copySelection();
          return;
        }
        if (code === "KeyX" && !isTypingTarget(event.target)) {
          event.preventDefault();
          useEditorStore.getState().cutSelection();
          return;
        }
        if (code === "KeyV" && !isTypingTarget(event.target)) {
          event.preventDefault();
          useEditorStore.getState().paste();
          return;
        }
        if (code === "KeyA" && !isTypingTarget(event.target)) {
          event.preventDefault();
          useEditorStore.getState().selectAll();
          return;
        }
        if (code === "KeyN" && !event.shiftKey) {
          event.preventDefault();
          const { dirty, resetNet } = useEditorStore.getState();
          if (dirty) {
            const ok = window.confirm(
              "You have unsaved changes. Discard and create a new net?",
            );
            if (!ok) return;
          }
          resetNet();
          useEditorStore.setState({ cloudNetId: null });
          return;
        }
        if (code === "KeyO" && !event.shiftKey) {
          event.preventDefault();
          openPnmlFile();
          return;
        }
        if (code === "KeyS") {
          event.preventDefault();
          saveNet();
          return;
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

function ModeBadge() {
  const status = useSimulationStore((s) => s.status);
  const failed = status === "error";
  const label =
    status === "running"
      ? "Simulating"
      : status === "paused"
        ? "Paused"
        : status === "done"
          ? "Done"
          : failed
            ? "Failed"
            : "Simulation";
  return (
    <div className="pointer-events-none absolute right-3 top-3 z-10">
      <span
        className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold text-white shadow ${
          failed ? "bg-red-500/90" : "bg-amber-500/90"
        }`}
      >
        {status === "running" && (
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
        )}
        {label}
      </span>
    </div>
  );
}

async function openPnmlFile() {
  const { dirty, setNet } = useEditorStore.getState();
  if (dirty) {
    const ok = window.confirm(
      "You have unsaved changes. Discard and open a file?",
    );
    if (!ok) return;
  }

  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".pnml";
  input.style.cssText = "position:fixed;top:-9999px;left:-9999px;opacity:0";
  document.body.appendChild(input);

  const cleanup = () => {
    if (!input.parentNode) return;
    document.body.removeChild(input);
  };

  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    cleanup();
    if (!file) return;
    try {
      const xml = await file.text();
      const { data, warnings } = parsePnml(xml);
      if (warnings.length > 0) {
        console.warn("PNML import warnings:", warnings);
        toast(summarizeImportWarnings(warnings), "warning");
      }
      setNet(data);
    } catch (err) {
      toast(`Failed to parse PNML: ${err instanceof Error ? err.message : String(err)}`, "error");
    }
  });

  input.addEventListener("cancel", cleanup);
  input.click();
}
