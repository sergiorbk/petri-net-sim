import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { getUserNet } from "@/lib/nets-client";
import { useEditorStore } from "@/stores/editor-store";
import { useCanvasTabsStore } from "@/stores/canvas-tabs-store";
import { SimulatorApp } from "./SimulatorApp";

export function NetLoader() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    useEditorStore.getState().cloudNetId === id ? "ready" : "loading",
  );
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Keyed on the ROUTE id alone, deliberately. cloudNetId is not a stable
  // document identity during a session: opening an object's own canvas
  // stashes the net and sets it to null precisely so a fragment cannot be
  // cloud-saved over the whole net — re-running this effect on that change
  // used to close the freshly opened canvas and refetch the root net right
  // over it.
  useEffect(() => {
    if (!id) { navigate("/", { replace: true }); return; }
    // A document is entering the editor: whatever object canvases were open
    // belonged to the previous document (or to a pre-reload session whose
    // editor content is gone) and must not carry over.
    useCanvasTabsStore.getState().resetToRoot();
    // Already loaded by gallery (e.g. after create) — skip fetch
    if (useEditorStore.getState().cloudNetId === id) { setStatus("ready"); return; }

    setStatus("loading");
    getUserNet(id).then((res) => {
      if (!res.ok) {
        setErrorMsg(res.error ?? "Failed to load net");
        setStatus("error");
        return;
      }
      useEditorStore.getState().setNet(res.data.net_data);
      useEditorStore.setState({ cloudNetId: id });
      setStatus("ready");
    });
  }, [id, navigate]);

  if (status === "loading") {
    return (
      <div className="flex h-full items-center justify-center bg-surface">
        <svg
          className="h-7 w-7 animate-spin text-accent"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25" />
          <path d="M4 12a8 8 0 0 1 8-8" stroke="currentColor" strokeWidth="3" strokeLinecap="round" className="opacity-75" />
        </svg>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-surface text-center">
        <p className="text-sm text-red-500">{errorMsg}</p>
        <button
          type="button"
          onClick={() => navigate("/", { replace: true })}
          className="text-xs text-text-muted underline hover:text-text-primary"
        >
          Back to gallery
        </button>
      </div>
    );
  }

  return <SimulatorApp />;
}
