import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useEditorStore } from "@/stores/editor-store";
import type { AgentToolCall, AgentToolResult, ChatMessage } from "@/types/chat";

export function SimulationResultRenderer({
  call,
  message,
}: {
  call: AgentToolCall;
  result: AgentToolResult;
  message: ChatMessage;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const net = message.netSnapshot;

  if (!net || call.status !== "success") return null;

  const markedCount = net.places.filter((p) => p.tokens > 0).length;

  function openInEditor() {
    useEditorStore.getState().setNet(net!);
    useEditorStore.setState({ cloudNetId: null });
    navigate("/editor");
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={openInEditor}
      onKeyDown={(e) => e.key === "Enter" && openInEditor()}
      className={cn(
        "mt-1 overflow-hidden rounded-lg border border-border bg-surface",
        "cursor-pointer transition-colors hover:border-accent hover:shadow-sm",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
      )}
    >
      <div className="flex items-center gap-2.5 px-3 py-2">
        <PetriIcon className="h-4 w-4 shrink-0 text-text-muted" />

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-xs font-medium text-text-primary">
              {net.name}
            </span>
            <span className="shrink-0 text-[10px] text-text-muted">
              {t("gallery.card.openInEditor")}
            </span>
          </div>

          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-text-muted">
            <span>
              {t("gallery.stats.placesTransitions", {
                places: net.places.length,
                transitions: net.transitions.length,
              })}
            </span>
            {markedCount > 0 && (
              <>
                <span className="text-border">|</span>
                <span className="text-emerald-600 dark:text-emerald-400">
                  {t("gallery.stats.markedPlaces", { count: markedCount })}
                </span>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
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
