import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { useEditorStore } from "@/stores/editor-store";
import { useUiStore } from "@/stores/ui-store";
import { useAuthStore } from "@/stores/auth-store";
import { useForkToUserNet } from "@/apps/chat-workbench/use-fork-to-user-net";
import { NameDialog } from "@/components/common/NameDialog";
import { ExportDialog } from "@/apps/simulator/dialogs/ExportDialog";
import type { PetriNetData } from "@/types/petri";

interface SimulationBlockProps {
  messageId: string;
  net: PetriNetData;
  versionIndex: number;
  totalVersions: number;
  allBlockIds: string[];
  snapshotId?: string;
}

function useWorkbenchContext(): { chatId: string | null; activeVersion: number | null } {
  const { chatId, versionIndex } = useParams<{ chatId?: string; versionIndex?: string }>();
  const parsed = versionIndex ? Number.parseInt(versionIndex, 10) : NaN;
  return {
    chatId: chatId ?? null,
    activeVersion: Number.isInteger(parsed) ? parsed : null,
  };
}

export function SimulationBlock({
  messageId,
  net,
  versionIndex,
  totalVersions,
  allBlockIds,
  snapshotId,
}: SimulationBlockProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { chatId: workbenchChatId, activeVersion } = useWorkbenchContext();
  const isActive = workbenchChatId !== null && activeVersion === versionIndex;
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const forkNet = useForkToUserNet();
  const [forkDialogOpen, setForkDialogOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  function saveToMyNets(e: React.MouseEvent) {
    e.stopPropagation();
    setForkDialogOpen(true);
  }

  function scrollToBlock(targetId: string) {
    document
      .getElementById(`sim-block-${targetId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function openInSimulator(e: React.MouseEvent) {
    if ((e.target as HTMLElement).closest("button[data-nav]")) return;
    if (workbenchChatId) {
      // Ensure the canvas is visible — explicit user intent to open the net.
      useUiStore.getState().setCanvasPanelOpen(true);
      navigate(`/chat/${workbenchChatId}/v/${versionIndex}`);
      return;
    }
    useEditorStore.getState().setNet(net);
    useEditorStore.setState({ cloudNetId: null });
    navigate("/editor");
  }

  const prevId = versionIndex > 1 ? allBlockIds[versionIndex - 2] : null;
  const nextId = versionIndex < totalVersions ? allBlockIds[versionIndex] : null;

  const markedCount = net.places.filter((p) => p.tokens > 0).length;

  return (
    <>
    <div id={`sim-block-${messageId}`} className="mx-auto mt-2 w-full max-w-3xl px-4">
      <div
        role="button"
        tabIndex={0}
        onClick={openInSimulator}
        onKeyDown={(e) => e.key === "Enter" && openInSimulator(e as unknown as React.MouseEvent)}
        aria-label={`Open ${net.name} in simulator`}
        className={cn(
          "overflow-hidden rounded-xl border bg-white shadow-sm",
          "dark:bg-zinc-900",
          "cursor-pointer transition-colors hover:border-accent hover:shadow-md",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          isActive
            ? "border-accent ring-1 ring-accent/40"
            : "border-zinc-200 dark:border-zinc-700",
        )}
      >
        <div className="flex items-center gap-3 px-4 py-2.5">
          <PetriIcon className="h-5 w-5 shrink-0 text-zinc-400" />

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">
                {net.name}
              </span>
              <span className="shrink-0 text-[11px] text-zinc-400">
                — {t("gallery.card.openInSimulator")}
              </span>
            </div>

            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-zinc-400">
              <span>
                {t("gallery.stats.placesTransitions", {
                  places: net.places.length,
                  transitions: net.transitions.length,
                })}
              </span>
              {markedCount > 0 && (
                <>
                  <span className="text-zinc-200 dark:text-zinc-700">|</span>
                  <span className="text-emerald-600 dark:text-emerald-400">
                    {t("gallery.stats.markedPlaces", { count: markedCount })}
                  </span>
                </>
              )}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-1">
            {isAuthenticated && (
              <button
                type="button"
                data-nav="save"
                onClick={saveToMyNets}
                className="rounded p-0.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
                aria-label={t("workbench.fork.save")}
                title={t("workbench.fork.save")}
              >
                <SaveIcon className="h-3.5 w-3.5" />
              </button>
            )}

            <button
              type="button"
              data-nav="download"
              onClick={(e) => { e.stopPropagation(); setExportOpen(true); }}
              className="rounded p-0.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
              aria-label={t("dialog.export.title")}
              title={t("dialog.export.title")}
            >
              <DownloadIcon className="h-3.5 w-3.5" />
            </button>

            {totalVersions > 1 && (
              <>
                <span className="text-zinc-200 dark:text-zinc-700">|</span>
                <button
                  type="button"
                  data-nav="prev"
                  onClick={(e) => { e.stopPropagation(); prevId && scrollToBlock(prevId); }}
                  disabled={!prevId}
                  className="rounded p-0.5 hover:bg-zinc-100 disabled:opacity-30 dark:hover:bg-zinc-800"
                  aria-label="Previous simulation version"
                >
                  <ChevronLeftIcon className="h-3.5 w-3.5" />
                </button>
                <span className="min-w-[36px] text-center text-xs text-zinc-400">
                  v{versionIndex}/{totalVersions}
                </span>
                <button
                  type="button"
                  data-nav="next"
                  onClick={(e) => { e.stopPropagation(); nextId && scrollToBlock(nextId); }}
                  disabled={!nextId}
                  className="rounded p-0.5 hover:bg-zinc-100 disabled:opacity-30 dark:hover:bg-zinc-800"
                  aria-label="Next simulation version"
                >
                  <ChevronRightIcon className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
    {forkDialogOpen && (
      <NameDialog
        title={t("workbench.fork.dialogTitle")}
        initialName={net.name || t("workbench.fork.defaultName")}
        submitLabel={t("workbench.fork.save")}
        placeholder={t("workbench.fork.namePlaceholder")}
        onSubmit={async (name) => {
          const ok = await forkNet(name, net, snapshotId);
          if (ok) setForkDialogOpen(false);
        }}
        onClose={() => setForkDialogOpen(false)}
      />
    )}
    {exportOpen && (
      // This card's own snapshot, not whatever the editor happens to hold:
      // the button sits under one particular version and has to export
      // that one.
      <ExportDialog
        net={net}
        version={versionIndex}
        id={snapshotId}
        onClose={() => setExportOpen(false)}
      />
    )}
    </>
  );
}

function PetriIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="6" r="3" />
      <circle cx="18" cy="18" r="3" />
      <rect x="10" y="9" width="4" height="6" rx="1" />
      <line x1="9" y1="12" x2="10" y2="12" />
      <line x1="14" y1="10" x2="15" y2="8" />
      <line x1="14" y1="14" x2="15" y2="16" />
    </svg>
  );
}

function ChevronLeftIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M15 18l-6-6 6-6" />
    </svg>
  );
}

function ChevronRightIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

function SaveIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
      <polyline points="17 21 17 13 7 13 7 21" />
      <polyline points="7 3 7 8 15 8" />
    </svg>
  );
}

function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M12 3v13m0 0l-4-4m4 4l4-4" />
      <path d="M3 18h18" strokeLinecap="round" />
    </svg>
  );
}
