import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useChatStore, getBackendSessionId } from "@/stores/chat-store";
import { useSimulationStore } from "@/stores/simulation-store";
import { useUiStore } from "@/stores/ui-store";
import { useWorkbenchStore } from "@/stores/workbench-store";
import { toast } from "@/stores/toast-store";
import { fetchSnapshot } from "@/lib/snapshot-client";
import { useIsMobile } from "@/hooks/use-media-query";
import { ChatInput } from "@/components/chat/ChatInput";
import { ChatMessageList } from "@/components/chat/ChatMessageList";
import { EmptyState } from "@/components/chat/EmptyState";
import { Sidebar } from "@/components/layout/Sidebar";
import { SidebarToggle } from "@/components/layout/SidebarToggle";
import { ReadOnlyCanvas } from "./ReadOnlyCanvas";
import { VersionSwitcher } from "./VersionSwitcher";
import { PanelToggle } from "./PanelToggle";
import { useForkToUserNet } from "./use-fork-to-user-net";
import { getVersionList } from "./version-list";
import { useAuthStore } from "@/stores/auth-store";
import { NameDialog } from "@/components/common/NameDialog";
import { getItem, setItem } from "@/lib/storage";

const CHAT_WIDTH_KEY = "chat-workbench-chat-width";
const CHAT_MIN_PX = 320;
const CHAT_MAX_PX = 720;
const CHAT_DEFAULT_PX = 440;

function clampChatWidth(n: number): number {
  if (!Number.isFinite(n)) return CHAT_DEFAULT_PX;
  return Math.min(CHAT_MAX_PX, Math.max(CHAT_MIN_PX, n));
}

export function ChatWorkbench() {
  const { chatId, versionIndex: versionParam } = useParams<{
    chatId?: string;
    versionIndex?: string;
  }>();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const loadSessionsFromBackend = useChatStore((s) => s.loadSessionsFromBackend);
  const setActiveChat = useChatStore((s) => s.setActiveChat);
  const activeChatId = useChatStore((s) => s.activeChatId);
  const sessions = useChatStore((s) => s.sessions);
  const isSending = useChatStore((s) => s.isSending);
  const attachingSnapshotMsgIds = useChatStore((s) => s.attachingSnapshotMsgIds);
  const error = useChatStore((s) => s.error);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const abortGeneration = useChatStore((s) => s.abortGeneration);
  const clearError = useChatStore((s) => s.clearError);

  const setActiveBlock = useSimulationStore((s) => s.setActiveBlock);
  const clearActiveBlock = useSimulationStore((s) => s.clearActiveBlock);
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);
  const setSidebarOpen = useUiStore((s) => s.setSidebarOpen);
  const chatPanelOpen = useUiStore((s) => s.chatPanelOpen);
  const canvasPanelOpen = useUiStore((s) => s.canvasPanelOpen);
  const toggleChatPanel = useUiStore((s) => s.toggleChatPanel);
  const toggleCanvasPanel = useUiStore((s) => s.toggleCanvasPanel);
  const isMobile = useIsMobile();
  const beginLiveBuild = useWorkbenchStore((s) => s.beginLiveBuild);
  const endLiveBuild = useWorkbenchStore((s) => s.endLiveBuild);
  const applyToolEvent = useWorkbenchStore((s) => s.applyToolEvent);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const forkNet = useForkToUserNet();
  const [forkDialogOpen, setForkDialogOpen] = useState(false);

  useEffect(() => {
    loadSessionsFromBackend();
  }, [loadSessionsFromBackend]);

  useEffect(() => {
    if (chatId && chatId !== activeChatId) {
      setActiveChat(chatId);
    }
  }, [chatId, activeChatId, setActiveChat]);

  // Opening a chat folds the chat list away. The list is how a conversation
  // is CHOSEN, and once one is open it is competing for width with the two
  // things actually being worked on -- the conversation and the net. Keyed
  // on the chat id rather than on "a chat is open", so re-opening the list
  // to look at something is respected and only picking another conversation
  // folds it again.
  useEffect(() => {
    if (chatId) {
      setSidebarOpen(false);
    }
  }, [chatId, setSidebarOpen]);

  const session = useMemo(
    () => sessions.find((s) => s.id === chatId),
    [sessions, chatId],
  );

  const versions = useMemo(() => getVersionList(session), [session]);

  const effectiveBackendId = useMemo(
    () => (session ? getBackendSessionId(session) : undefined),
    [session],
  );

  const requestedIndex = versionParam ? Number.parseInt(versionParam, 10) : null;
  const validIndex =
    requestedIndex !== null &&
    Number.isInteger(requestedIndex) &&
    requestedIndex >= 1 &&
    requestedIndex <= versions.length
      ? requestedIndex
      : null;

  // Tracks the snapshot fetch that is currently in-flight to prevent parallel
  // duplicate requests when the effect re-runs due to unrelated state updates
  // (e.g. loadMessages completing and updating the sessions reference).
  const inflightSnapshotRef = useRef<string | null>(null);
  // Incremented after a cancelled fetch completes so the effect can re-run
  // and make a fresh attempt once the inflight slot is free.
  const [snapshotFetchRevision, setSnapshotFetchRevision] = useState(0);

  // Resolve URL → simulation-store. If versionIndex is invalid but versions exist,
  // redirect to the latest. If no versions, drop the segment and wipe the
  // canvas so a stale net from a previous chat doesn't linger.
  useEffect(() => {
    if (!chatId) {
      clearActiveBlock();
      return;
    }
    if (versions.length === 0) {
      clearActiveBlock();
      if (versionParam !== undefined) {
        navigate(`/chat/${chatId}`, { replace: true });
      }
      return;
    }
    if (validIndex === null) {
      navigate(`/chat/${chatId}/v/${versions.length}`, { replace: true });
      return;
    }
    const version = versions[validIndex - 1];
    if (version.netSnapshot) {
      setActiveBlock(version.messageId, version.netSnapshot, version.snapshotId);
      return;
    }
    // Cold load: snapshot exists on the backend but the full net JSON is not
    // in localStorage (incognito, shared link, different device). Resolve it.
    // Skip while the stream is live, and while onDone's own snapshot fetch is
    // still pending for this message — otherwise this races ahead of it and
    // can 404 against a snapshot netSnapshot hasn't been attached from yet.
    if (
      !version.snapshotId ||
      !effectiveBackendId ||
      isSending ||
      attachingSnapshotMsgIds[version.messageId]
    ) {
      return;
    }

    // Deduplicate: skip if an identical fetch is already in flight.
    // The ref is NOT cleared in cleanup — only here in finally — so that a
    // rapid re-render (e.g. sessions reference update after loadMessages)
    // hitting the same fetchKey is blocked rather than spawning a parallel request.
    const fetchKey = `${effectiveBackendId}:${version.snapshotId}`;
    if (inflightSnapshotRef.current === fetchKey) return;
    inflightSnapshotRef.current = fetchKey;

    let cancelled = false;
    (async () => {
      try {
        const result = await fetchSnapshot(effectiveBackendId, version.snapshotId!);
        if (cancelled) {
          // This attempt was superseded by a cleanup; bump the revision so the
          // effect re-runs after the inflight slot is released below.
          setSnapshotFetchRevision((r) => r + 1);
          return;
        }
        if (result.ok) {
          setActiveBlock(version.messageId, result.data, version.snapshotId);
        } else if (result.status === 404) {
          // Snapshot no longer exists in the DB (e.g. backend was wiped).
          // Guard against a parallel fetch that already cleared the id.
          const store = useChatStore.getState();
          const msg = store.sessions
            .find((s) => s.id === chatId)
            ?.messages.find((m) => m.id === version.messageId);
          if (msg?.snapshotId) {
            store.clearMessageSnapshotId(chatId!, version.messageId);
            toast(t("workbench.errors.snapshotNotFound"));
          }
        } else {
          toast(t("workbench.errors.snapshotLoadFailed"));
          navigate(`/chat/${chatId}`, { replace: true });
        }
      } finally {
        if (inflightSnapshotRef.current === fetchKey) {
          inflightSnapshotRef.current = null;
        }
      }
    })();
    return () => {
      cancelled = true;
      // Do NOT clear inflightSnapshotRef here — the HTTP request is still
      // in-flight. Keeping the ref set prevents a parallel duplicate from
      // starting in the next effect run for the same fetchKey.
    };
  }, [chatId, versionParam, validIndex, versions, snapshotFetchRevision, navigate, setActiveBlock, clearActiveBlock, effectiveBackendId, isSending, attachingSnapshotMsgIds, t]);

  const goToVersion = useCallback(
    (index: number) => {
      if (!chatId) return;
      navigate(`/chat/${chatId}/v/${index}`);
    },
    [chatId, navigate],
  );

  // Auto-advance: when a new snapshot is appended to the session, navigate to it.
  // Uses a ref so we only react to growth, not to initial mount or unrelated changes.
  const lastSeenCountRef = useRef<number | null>(null);
  useEffect(() => {
    if (!chatId) return;
    const prev = lastSeenCountRef.current;
    lastSeenCountRef.current = versions.length;
    if (prev === null) return;
    if (versions.length > prev) {
      navigate(`/chat/${chatId}/v/${versions.length}`);
    }
  }, [chatId, versions.length, navigate]);

  // Keyboard nav: Ctrl+Alt+Left / Right walk versions.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.ctrlKey && e.altKey)) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      if (e.key === "ArrowLeft" && validIndex !== null && validIndex > 1) {
        e.preventDefault();
        goToVersion(validIndex - 1);
      } else if (e.key === "ArrowRight" && validIndex !== null && validIndex < versions.length) {
        e.preventDefault();
        goToVersion(validIndex + 1);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [validIndex, versions.length, goToVersion]);

  // Live build: while the last assistant message is streaming, apply each
  // successful tool_call to the workbench liveDraft. Phase 3 only activates
  // when the backend emits net-mutating tool events (add_place/add_transition
  // /add_arc); otherwise the spinner stays until the final snapshot lands.
  const lastMsg = session?.messages[session.messages.length - 1];
  const lastSteps = lastMsg?.role === "assistant" ? lastMsg.steps : undefined;
  useEffect(() => {
    if (!isSending || !lastSteps) return;
    for (const step of lastSteps) {
      if (step.type !== "tool_call") continue;
      if (step.status !== "success") continue;
      applyToolEvent(step.id, step.name, step.input);
    }
  }, [isSending, lastSteps, applyToolEvent]);

  // Start a live draft when a new send begins; end it when the snapshot lands
  // or the request finishes (auto-advance effect picks up the real net).
  const wasSendingRef = useRef(false);
  useEffect(() => {
    if (isSending && !wasSendingRef.current) {
      beginLiveBuild();
    } else if (!isSending && wasSendingRef.current) {
      endLiveBuild();
    }
    wasSendingRef.current = isSending;
  }, [isSending, beginLiveBuild, endLiveBuild]);

  const handleSend = (content: string) => {
    // Bootstrap a chat when sending from the bare /chat route so the URL
    // reflects the new chat id.
    if (!chatId) {
      const newId = useChatStore.getState().createChat();
      navigate(`/chat/${newId}`, { replace: true });
    }
    sendMessage(content);
  };

  const messages = session?.messages ?? [];
  const showEmptyState = messages.length === 0 && !session?.isShared;

  // Resizable splitter between chat and canvas. Only relevant when both are open.
  const containerRef = useRef<HTMLDivElement>(null);
  const [chatWidth, setChatWidth] = useState<number>(() =>
    clampChatWidth(getItem<number>(CHAT_WIDTH_KEY, CHAT_DEFAULT_PX)),
  );
  useEffect(() => {
    setItem(CHAT_WIDTH_KEY, chatWidth);
  }, [chatWidth]);
  const draggingRef = useRef(false);
  const onSeparatorDown = (e: React.PointerEvent<HTMLDivElement>) => {
    draggingRef.current = true;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onSeparatorMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setChatWidth(clampChatWidth(e.clientX - rect.left));
  };
  const onSeparatorUp = (e: React.PointerEvent<HTMLDivElement>) => {
    draggingRef.current = false;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
  };

  // On desktop the collapsed strip carries its own re-expand toggle, so the
  // chat header only needs a sidebar toggle on mobile where the sidebar lives
  // as an overlay.
  const showSidebarToggle = isMobile && !sidebarOpen;

  const chatPanel = (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-border px-2">
        {showSidebarToggle && <SidebarToggle />}
        <span className="min-w-0 flex-1 truncate px-1 text-xs font-medium text-text-secondary">
          {session?.title ?? t("sidebar.newChat")}
        </span>
        <PanelToggle
          onToggle={toggleChatPanel}
          label={t("workbench.panel.collapseChat")}
          direction="left"
          disabled={!canvasPanelOpen}
        />
      </div>
      {showEmptyState ? (
        <EmptyState onSend={handleSend} />
      ) : (
        <>
          <ChatMessageList messages={messages} />
          {!session?.isShared && (
            <>
              {error && (
                <div className="px-3">
                  <div className="mb-2 flex items-center justify-between rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
                    <span>{error}</span>
                    <button
                      type="button"
                      className="ml-2 text-red-500 hover:text-red-700"
                      onClick={clearError}
                      aria-label={t("workbench.dismissError")}
                    >
                      x
                    </button>
                  </div>
                </div>
              )}
              <div className="px-3 pb-3 pt-2">
                <ChatInput onSend={handleSend} disabled={isSending} onStop={abortGeneration} />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );

  const canvasPanel = (
    <div className="relative flex h-full min-h-0 min-w-0 flex-1 flex-col">
      <div className="absolute right-2 top-2 z-30">
        <PanelToggle
          onToggle={toggleCanvasPanel}
          label={t("workbench.panel.collapseCanvas")}
          direction="right"
          disabled={!chatPanelOpen}
        />
      </div>
      <div className="flex min-h-0 flex-1">
        <ReadOnlyCanvas />
      </div>
      {validIndex !== null && (
        <VersionSwitcher
          versions={versions}
          currentIndex={validIndex}
          onSelect={goToVersion}
          shareUrl={`${window.location.origin}/chat/${chatId}/v/${validIndex}`}
          onFork={() => setForkDialogOpen(true)}
          forkDisabled={!isAuthenticated}
        />
      )}
    </div>
  );

  const showSidebar = isMobile || sidebarOpen;

  return (
    <div className="flex h-full min-h-0 w-full">
      {showSidebar ? (
        <div className="w-[260px] shrink-0 overflow-hidden">
          <Sidebar />
        </div>
      ) : (
        <CollapsedStrip
          side="left"
          onExpand={toggleSidebar}
          label={t("workbench.panel.expandChatList")}
          caption={t("workbench.panel.chatListLabel")}
        />
      )}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div ref={containerRef} className="flex min-h-0 min-w-0 flex-1">
          {chatPanelOpen ? (
            <div
              className="flex h-full min-h-0 flex-col"
              style={
                canvasPanelOpen
                  ? { width: chatWidth, flexShrink: 0 }
                  : { flex: 1, minWidth: 0 }
              }
            >
              {chatPanel}
            </div>
          ) : (
            <CollapsedStrip
              side="left"
              onExpand={toggleChatPanel}
              label={t("workbench.panel.expandChat")}
              caption={t("workbench.panel.chatLabel")}
              header={showSidebarToggle ? <SidebarToggle /> : null}
            />
          )}
          {chatPanelOpen && canvasPanelOpen && (
            <div
              role="separator"
              aria-orientation="vertical"
              onPointerDown={onSeparatorDown}
              onPointerMove={onSeparatorMove}
              onPointerUp={onSeparatorUp}
              className="w-1 shrink-0 cursor-col-resize bg-zinc-200 transition-colors hover:bg-accent dark:bg-zinc-800 dark:hover:bg-accent"
            />
          )}
          {canvasPanelOpen ? (
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              {canvasPanel}
            </div>
          ) : (
            <CollapsedStrip
              side="right"
              onExpand={toggleCanvasPanel}
              label={t("workbench.panel.expandCanvas")}
              caption={t("workbench.panel.canvasLabel")}
            />
          )}
        </div>
      </div>
      {forkDialogOpen && validIndex !== null && versions[validIndex - 1]?.netSnapshot && (
        <NameDialog
          title={t("workbench.fork.dialogTitle")}
          initialName={
            (session?.title && session.title !== "New Chat"
              ? `${session.title} v${validIndex}`
              : versions[validIndex - 1].netSnapshot!.name) ||
            t("workbench.fork.defaultName")
          }
          submitLabel={t("workbench.fork.save")}
          placeholder={t("workbench.fork.namePlaceholder")}
          onSubmit={async (name) => {
            const version = versions[validIndex - 1];
            const ok = await forkNet(name, version.netSnapshot!, version.snapshotId);
            if (ok) setForkDialogOpen(false);
          }}
          onClose={() => setForkDialogOpen(false)}
        />
      )}
    </div>
  );
}

interface CollapsedStripProps {
  side: "left" | "right";
  onExpand: () => void;
  label: string;
  caption: string;
  header?: React.ReactNode;
}

function CollapsedStrip({ side, onExpand, label, caption, header }: CollapsedStripProps) {
  return (
    <div
      className={cn(
        "flex h-full w-9 shrink-0 flex-col items-center gap-2 border-border bg-surface-secondary py-2",
        side === "left" ? "border-r" : "border-l",
      )}
    >
      {header}
      <PanelToggle
        onToggle={onExpand}
        label={label}
        direction={side === "left" ? "right" : "left"}
      />
      <button
        type="button"
        onClick={onExpand}
        aria-label={label}
        className="select-none cursor-pointer text-[11px] text-text-muted hover:text-text-primary"
        style={{ writingMode: "vertical-rl", transform: "rotate(180deg)" }}
      >
        {caption}
      </button>
    </div>
  );
}
