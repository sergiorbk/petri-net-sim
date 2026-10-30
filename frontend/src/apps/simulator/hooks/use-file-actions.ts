import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useEditorStore } from "@/stores/editor-store";
import { useAuthStore } from "@/stores/auth-store";
import { useCanvasTabsStore } from "@/stores/canvas-tabs-store";
import { createUserNet, updateUserNet } from "@/lib/nets-client";
import { useUserNetsStore } from "@/stores/user-nets-store";
import { ExportDialog } from "../dialogs/ExportDialog";
import { parsePnml, summarizeImportWarnings } from "@/lib/pnml-import";
import { toast } from "@/stores/toast-store";
import { randomNetName } from "@/lib/random-net-name";
import { openTrainingFile, useTrainingStore } from "@/stores/training-store";

function pickImportFile(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pnml,.xml,.zip";
    input.style.cssText = "position:fixed;top:-9999px;left:-9999px;opacity:0";
    document.body.appendChild(input);
    const cleanup = () => {
      if (input.parentNode) document.body.removeChild(input);
    };
    input.addEventListener("change", () => {
      const file = input.files?.[0] ?? null;
      cleanup();
      resolve(file);
    });
    input.addEventListener("cancel", () => {
      cleanup();
      resolve(null);
    });
    input.click();
  });
}

async function importFile(file: File): Promise<void> {
  if (file.name.toLowerCase().endsWith(".zip")) return openTrainingFile(file);
  const text = await file.text();
  const lower = file.name.toLowerCase();
  const looksLikePnml =
    lower.endsWith(".pnml") ||
    lower.endsWith(".xml") ||
    text.trimStart().startsWith("<");

  if (looksLikePnml) {
    const { data, warnings } = parsePnml(text);
    if (warnings.length > 0) {
      console.warn("PNML import warnings:", warnings);
      toast(summarizeImportWarnings(warnings), "warning");
    }
    window.dispatchEvent(
      new CustomEvent("petri:import-pnml", { detail: data }),
    );
    return;
  }
  throw new Error("Unsupported file format");
}

export async function saveNet(): Promise<void> {
  // On a Petri-object's own canvas, "save" means writing the object back to
  // the canvas that owns it — saving it to the cloud as a net of its own is
  // never what the user meant.
  if (useCanvasTabsStore.getState().saveActiveObjectTab()) return;

  if (!useAuthStore.getState().isAuthenticated) return;
  const { net, markClean, cloudNetId } = useEditorStore.getState();
  try {
    if (cloudNetId) {
      const result = await updateUserNet(cloudNetId, { name: net.name, net_data: net });
      if (result.ok) {
        markClean();
        useUserNetsStore.getState().invalidate();
      } else {
        toast(`Save failed: ${result.error}`, "error");
      }
    } else {
      const result = await createUserNet({ name: net.name, net_data: net });
      if (result.ok) {
        useEditorStore.setState({ cloudNetId: result.data.id });
        markClean();
        useUserNetsStore.getState().invalidate();
      } else {
        toast(`Save failed: ${result.error}`, "error");
      }
    }
  } catch (err) {
    toast(`Save failed: ${err instanceof Error ? err.message : String(err)}`, "error");
  }
}

export function useFileActions() {
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const navigate = useNavigate();

  // "New" means a new document, and a document is a cloud net with a route of
  // its own. Merely blanking the editor in place used to null cloudNetId,
  // which NetLoader answered by re-fetching the route's net over the fresh
  // canvas — the "new net" reverted to the old one within a frame.
  const handleNew = useCallback(async () => {
    const { dirty } = useEditorStore.getState();
    if (dirty) {
      const ok = window.confirm(
        "You have unsaved changes. Discard and create a new net?",
      );
      if (!ok) return;
    }
    if (!useAuthStore.getState().isAuthenticated) return;
    try {
      const name = randomNetName();
      const result = await createUserNet({
        name,
        net_data: { name, places: [], transitions: [], arcs: [] },
      });
      if (!result.ok) {
        toast(`Could not create a net: ${result.error}`, "error");
        return;
      }
      useUserNetsStore.getState().invalidate();
      useTrainingStore.getState().clear();
      useEditorStore.getState().setNet({ name, places: [], transitions: [], arcs: [] });
      useEditorStore.setState({ cloudNetId: result.data.id, dirty: false });
      navigate(`/nets/${result.data.id}`);
    } catch (err) {
      toast(`Could not create a net: ${err instanceof Error ? err.message : String(err)}`, "error");
    }
  }, [navigate]);

  const handleSave = useCallback(() => saveNet(), []);

  const handleSaveAs = useCallback(async () => {
    const isAuthenticated = useAuthStore.getState().isAuthenticated;
    if (!isAuthenticated) return;

    const { net, markClean, renameNet } = useEditorStore.getState();
    const newName = window.prompt("Save as:", net.name);
    if (!newName?.trim()) return;

    try {
      const trimmedName = newName.trim();
      if (trimmedName !== net.name) {
        renameNet(trimmedName);
      }
      const result = await createUserNet({
        name: trimmedName,
        net_data: { ...net, name: trimmedName },
      });
      if (result.ok) {
        useEditorStore.setState({ cloudNetId: result.data.id });
        markClean();
        // The copy is a new document with a route of its own; staying on the
        // old route would make NetLoader re-fetch the old net over it.
        navigate(`/nets/${result.data.id}`);
      } else {
        toast(`Save failed: ${result.error}`, "error");
      }
    } catch (err) {
      toast(`Save failed: ${err instanceof Error ? err.message : String(err)}`, "error");
    }
  }, [navigate]);

  const openExportDialog = useCallback(() => setExportDialogOpen(true), []);
  const closeExportDialog = useCallback(() => setExportDialogOpen(false), []);

  const handleImport = useCallback(async () => {
    const file = await pickImportFile();
    if (!file) return;
    try {
      await importFile(file);
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    }
  }, []);

  return {
    handleNew,
    handleSave,
    handleSaveAs,
    openExportDialog,
    closeExportDialog,
    exportDialogOpen,
    ExportDialogComponent: ExportDialog,
    handleImport,
  };
}
