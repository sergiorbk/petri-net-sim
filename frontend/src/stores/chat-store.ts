import { create } from "zustand";
import { apiClient, publicApiClient } from "@/lib/api-client";
import { streamChatCompletion, UNCAPPED_AGENT_EFFORT } from "@/lib/sse-client";
import { createStreamFlusher } from "@/lib/stream-flush";
import { useLlmCredentialsStore } from "@/stores/llm-credentials-store";
import { useNetStyleStore } from "@/stores/net-style-store";
import { useLayoutDirectionStore } from "@/stores/layout-direction-store";
import { getItem, setItem } from "@/lib/storage";
import type {
  AgentStep,
  AgentToolCall,
  ChatMessage,
  ChatSession,
  SessionVisibility,
  TimelineItem,
} from "@/types/chat";
import { useSimulationStore } from "@/stores/simulation-store";

function generateId(): string {
  return crypto.randomUUID();
}

/**
 * Resolve the effective backend session ID for a session.
 * Sessions created locally first get a UUID as `id`, then receive a SHA-256
 * backend ID stored in `backendSessionId`. Sessions loaded directly from the
 * backend list have their backend ID as `id` (64 hex chars) and no
 * `backendSessionId` field.
 */
export function getBackendSessionId(session: ChatSession): string | undefined {
  if (session.backendSessionId) return session.backendSessionId;
  if (session.id.length === 64) return session.id;
  return undefined;
}

const SESSIONS_KEY = "chat-sessions";
const ACTIVE_CHAT_KEY = "active-chat-id";
const LAST_USER_KEY = "last-user-id";

function persistSessions(sessions: ChatSession[]): void {
  setItem(SESSIONS_KEY, sessions);
}

function loadSessions(): ChatSession[] {
  return getItem<ChatSession[]>(SESSIONS_KEY, []);
}

function loadActiveChatId(): string | null {
  return getItem<string | null>(ACTIVE_CHAT_KEY, null);
}

interface ChatState {
  sessions: ChatSession[];
  activeChatId: string | null;
  searchQuery: string;
  isSending: boolean;
  streamingContent: string;
  error: string | null;
  sessionsHasMore: boolean;
  sessionsOffset: number;
  sessionsLoading: boolean;
  abortController: AbortController | null;
  // Assistant message IDs whose netSnapshot is being fetched via loadNet()
  // right after the stream ends. isSending flips to false before that fetch
  // resolves, so ChatWorkbench's cold-load effect (gated on isSending) would
  // otherwise race ahead of it and 404 against a snapshot it hasn't been
  // handed locally yet -- see ChatWorkbench's version-resolution effect.
  attachingSnapshotMsgIds: Record<string, true>;

  getActiveChat: () => ChatSession | undefined;
  getFilteredSessions: () => ChatSession[];

  createChat: () => string;
  deleteChat: (id: string) => void;
  setActiveChat: (id: string | null) => void;
  setSearchQuery: (query: string) => void;
  addMessage: (
    chatId: string,
    message: Pick<ChatMessage, "role" | "content">,
  ) => void;
  updateSessionTitle: (chatId: string, title: string) => void;
  updateVisibility: (chatId: string, visibility: SessionVisibility) => Promise<string | null>;
  syncMessages: (chatId: string) => Promise<void>;
  addSharedSession: (shareToken: string) => Promise<{ chatId: string } | null>;
  sendMessage: (content: string) => Promise<void>;
  abortGeneration: () => void;
  loadSessionsFromBackend: () => Promise<void>;
  loadMoreSessions: () => Promise<void>;
  loadMessages: (chatId: string) => Promise<void>;
  clearMessageSnapshotId: (chatId: string, messageId: string) => void;
  clearError: () => void;
  initForUser: (userId: string) => void;
  clearSessions: () => void;
}

/**
 * How often streamed tokens are written into the store. Every write walks
 * all sessions and re-renders the conversation, so it is the cost that
 * matters here rather than the token rate: 20 writes a second is far
 * faster than anyone reads and cheap enough to leave the tab responsive.
 */
const STREAM_FLUSH_MS = 50;

const PAGE_SIZE = 30;

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: loadSessions(),
  activeChatId: loadActiveChatId(),
  searchQuery: "",
  isSending: false,
  streamingContent: "",
  error: null,
  sessionsHasMore: true,
  sessionsOffset: 0,
  sessionsLoading: false,
  abortController: null,
  attachingSnapshotMsgIds: {},

  getActiveChat: () => {
    const { sessions, activeChatId } = get();
    return sessions.find((s) => s.id === activeChatId);
  },

  getFilteredSessions: () => {
    const { sessions, searchQuery } = get();
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase();
    return sessions.filter((s) => s.title.toLowerCase().includes(q));
  },

  createChat: () => {
    const { sessions, activeChatId } = get();
    const simStore = useSimulationStore.getState();
    const activeChat = sessions.find((s) => s.id === activeChatId);
    if (activeChat && activeChat.messages.length === 0 && activeChat.title === "New Chat") {
      simStore.clearActiveBlock();
      return activeChat.id;
    }

    const existing = sessions.find(
      (s) => s.messages.length === 0 && s.title === "New Chat",
    );
    if (existing) {
      set({ activeChatId: existing.id });
      setItem(ACTIVE_CHAT_KEY, existing.id);
      simStore.clearActiveBlock();
      return existing.id;
    }

    const id = generateId();
    const now = Date.now();
    const session: ChatSession = {
      id,
      title: "New Chat",
      messages: [],
      createdAt: now,
      updatedAt: now,
    };
    set((s) => {
      const sessions = [session, ...s.sessions];
      persistSessions(sessions);
      return { sessions, activeChatId: id };
    });
    simStore.clearActiveBlock();
    return id;
  },

  deleteChat: (id) => {
    set((s) => {
      const sessions = s.sessions.filter((c) => c.id !== id);
      persistSessions(sessions);
      return {
        sessions,
        activeChatId: s.activeChatId === id ? null : s.activeChatId,
      };
    });
    // Best-effort backend delete (session may not exist there yet)
    apiClient(`/api/v1/sessions/${id}`, { method: "DELETE" });
  },

  setActiveChat: (id) => {
    set({ activeChatId: id });
    setItem(ACTIVE_CHAT_KEY, id);

    const simStore = useSimulationStore.getState();
    if (id === null) {
      simStore.clearSimulation();
      return;
    }

    const session = get().sessions.find((s) => s.id === id);

    // Lazy-load messages when the session has none cached locally
    if (session && session.messages.length === 0 && !session.isShared) {
      void get().loadMessages(id);
    }

    const backendId = session ? getBackendSessionId(session) : undefined;
    if (backendId) {
      simStore.setSessionId(backendId);
      simStore.loadNet();
    } else {
      simStore.clearSimulation();
    }
  },

  setSearchQuery: (searchQuery) => set({ searchQuery }),

  addMessage: (chatId, msg) => {
    const message: ChatMessage = {
      id: generateId(),
      role: msg.role,
      content: msg.content,
      timestamp: Date.now(),
    };
    set((s) => {
      const sessions = s.sessions.map((session) =>
        session.id === chatId
          ? {
              ...session,
              messages: [...session.messages, message],
              updatedAt: Date.now(),
            }
          : session,
      );
      persistSessions(sessions);
      return { sessions };
    });
  },

  updateSessionTitle: (chatId, title) =>
    set((s) => {
      const sessions = s.sessions.map((session) =>
        session.id === chatId ? { ...session, title } : session,
      );
      persistSessions(sessions);
      return { sessions };
    }),

  updateVisibility: async (chatId, visibility) => {
    const session = get().sessions.find((s) => s.id === chatId);
    if (!session) return null;

    const backendId = session.backendSessionId ?? session.id;
    const result = await apiClient<{ share_token: string; visibility: string }>(
      `/api/v1/sessions/${backendId}/share`,
      { method: "PATCH", body: JSON.stringify({ visibility }) },
    );

    if (!result.ok) return null;

    const shareToken = result.data.share_token;
    set((s) => {
      const sessions = s.sessions.map((sess) =>
        sess.id === chatId ? { ...sess, shareToken, visibility } : sess,
      );
      persistSessions(sessions);
      return { sessions };
    });
    return shareToken;
  },

  syncMessages: async (chatId) => {
    const session = get().sessions.find((s) => s.id === chatId);
    if (!session || session.isShared) return;

    const backendId = session.backendSessionId ?? session.id;
    // Only sync sessions that have a real backend ID (64-char SHA-256 fingerprint)
    if (!backendId || backendId.length !== 64) return;

    const payload = session.messages.map((m) => ({
      role: m.role,
      content: m.content,
      timestamp: m.timestamp,
      ...(m.snapshotId ? { snapshot_id: m.snapshotId } : {}),
    }));

    await apiClient(`/api/v1/sessions/${backendId}/messages`, {
      method: "PUT",
      body: JSON.stringify({ messages: payload }),
    });
  },

  addSharedSession: async (shareToken) => {
    const existing = get().sessions.find((s) => s.shareToken === shareToken);
    if (existing) return { chatId: existing.id };

    const result = await publicApiClient<{
      title: string | null;
      share_token: string;
      visibility: string;
      messages: Array<{ role: string; content: string; timestamp: number; snapshot_id?: string }>;
      created_at: string;
      updated_at: string;
    }>(`/api/v1/sessions/shared/${shareToken}`);

    if (!result.ok) return null;

    const data = result.data;
    const messages: ChatMessage[] = data.messages.map((m: { role: string; content: string; timestamp: number; snapshot_id?: string }) => ({
      id: generateId(),
      role: m.role as "user" | "assistant",
      content: m.content,
      timestamp: m.timestamp,
      ...(m.snapshot_id ? { snapshotId: m.snapshot_id } : {}),
    }));

    const session: ChatSession = {
      id: shareToken,
      title: data.title ?? "Спільний чат",
      messages,
      createdAt: new Date(data.created_at).getTime(),
      updatedAt: new Date(data.updated_at).getTime(),
      shareToken,
      visibility: data.visibility as SessionVisibility,
      isShared: true,
    };

    set((s) => {
      const sessions = [session, ...s.sessions.filter((x) => x.id !== shareToken)];
      persistSessions(sessions);
      return { sessions };
    });

    return { chatId: shareToken };
  },

  clearError: () => set({ error: null }),

  clearMessageSnapshotId: (chatId: string, messageId: string) => {
    set((s) => {
      const sessions = s.sessions.map((session) =>
        session.id === chatId
          ? {
              ...session,
              messages: session.messages.map((m) =>
                m.id === messageId ? { ...m, snapshotId: undefined, netSnapshot: undefined } : m,
              ),
            }
          : session,
      );
      persistSessions(sessions);
      return { sessions };
    });
  },

  loadMessages: async (chatId: string) => {
    const session = get().sessions.find((s) => s.id === chatId);
    if (!session || session.messages.length > 0 || session.isShared) return;

    const backendId = session.backendSessionId ?? session.id;
    // Backend session IDs are 64-char SHA-256 fingerprints; skip local-only UUIDs
    if (!backendId || backendId.length !== 64) return;

    const result = await apiClient<{
      messages: Array<{
        role: string;
        content: string;
        timestamp: number;
        snapshot_id?: string;
      }>;
    }>(`/api/v1/sessions/${backendId}/messages`);

    if (!result.ok || result.data.messages.length === 0) return;

    const messages: ChatMessage[] = result.data.messages.map((m) => ({
      id: generateId(),
      role: m.role as "user" | "assistant",
      content: m.content,
      timestamp: m.timestamp,
      ...(m.snapshot_id ? { snapshotId: m.snapshot_id } : {}),
    }));

    set((s) => {
      const sessions = s.sessions.map((sess) =>
        sess.id === chatId ? { ...sess, messages } : sess,
      );
      persistSessions(sessions);
      return { sessions };
    });
  },

  initForUser: (userId: string) => {
    const lastUserId = getItem<string | null>(LAST_USER_KEY, null);
    if (lastUserId !== userId) {
      setItem(SESSIONS_KEY, []);
      setItem(ACTIVE_CHAT_KEY, null);
      setItem(LAST_USER_KEY, userId);
      set({ sessions: [], activeChatId: null, sessionsOffset: 0, sessionsHasMore: true });
    }
  },

  clearSessions: () => {
    set({ sessions: [], activeChatId: null, sessionsOffset: 0, sessionsHasMore: true });
  },

  abortGeneration: () => {
    const { abortController } = get();
    if (abortController) {
      abortController.abort();
      set({ abortController: null });
    }
  },

  sendMessage: async (content: string) => {
    const state = get();
    let chatId = state.activeChatId;

    // Create local session if needed
    if (!chatId) {
      chatId = get().createChat();
    }

    // Add user message
    get().addMessage(chatId, { role: "user", content });

    // Update title from first message
    const chat = get().sessions.find((s) => s.id === chatId);
    if (chat && chat.messages.length === 1) {
      const title =
        content.length > 60 ? content.slice(0, 60) + "..." : content;
      get().updateSessionTitle(chatId, title);
    }

    // Build message history for API
    const currentChat = get().sessions.find((s) => s.id === chatId);
    if (!currentChat) return;

    const apiMessages = currentChat.messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const controller = new AbortController();
    set({ isSending: true, streamingContent: "", error: null, abortController: controller });

    // Add placeholder assistant message
    const assistantMsgId = generateId();
    set((s) => {
      const sessions = s.sessions.map((session) =>
        session.id === chatId
          ? {
              ...session,
              messages: [
                ...session.messages,
                {
                  id: assistantMsgId,
                  role: "assistant" as const,
                  content: "",
                  timestamp: Date.now(),
                },
              ],
              updatedAt: Date.now(),
            }
          : session,
      );
      return { sessions };
    });

    let accumulated = "";
    let timeline: TimelineItem[] = [];
    let currentTextBlock: { kind: "text"; content: string } | null = null;
    let simulationRan = false;
    let snapshotReceived = false;

    const { selectedCredentialId } = useLlmCredentialsStore.getState();
    const { netStyle } = useNetStyleStore.getState();
    // The workbench never caps a turn. A build that stops partway leaves
    // a half-finished net behind, which is worse than a long one, and
    // there is nothing here worth asking the user to decide per message.
    // The backend still honours "standard"/"thorough" for any other
    // OpenAI-compatible client that asks for them.
    const agentEffort = UNCAPPED_AGENT_EFFORT;
    const { layoutDirection } = useLayoutDirectionStore.getState();

    // Text now arrives a TOKEN at a time, where it used to arrive in a
    // handful of pieces. Writing each one into the store means walking
    // every session and every message in it, deep-copying the timeline and
    // re-rendering the whole conversation -- fine a few times per message,
    // and enough to lock the tab up hundreds of times per message. So the
    // tokens are gathered here and written at most every STREAM_FLUSH_MS,
    // which is still far faster than anyone reads.
    const applyText = () => {
      const snapshotTimeline = timeline.map((t) => ({ ...t }));
      set((s) => ({
        streamingContent: accumulated,
        sessions: s.sessions.map((session) =>
          session.id === chatId
            ? {
                ...session,
                messages: session.messages.map((m) =>
                  m.id === assistantMsgId
                    ? { ...m, content: accumulated, timeline: snapshotTimeline }
                    : m,
                ),
              }
            : session,
        ),
      }));
    };
    const textStream = createStreamFlusher(applyText, STREAM_FLUSH_MS);
    const writeText = textStream.flush;
    const scheduleTextWrite = textStream.schedule;

    await streamChatCompletion(
      apiMessages,
      {
        onChunk: (chunk) => {
        const delta = chunk.choices[0]?.delta;
        if (delta?.content) {
          accumulated += delta.content;
          if (currentTextBlock) {
            currentTextBlock.content += delta.content;
          } else {
            const block: { kind: "text"; content: string } = { kind: "text", content: delta.content };
            currentTextBlock = block;
            timeline = [...timeline, block];
          }
          scheduleTextWrite();
        }

        if (delta?.agent_event) {
          // Anything else that touches the store has to see the text that
          // came before it, so the pending tokens go in first. Otherwise a
          // tool event could be recorded ahead of the sentence introducing
          // it, and the flush afterwards would put the sentence back.
          writeText();
          const ev = delta.agent_event;
          if (ev.type === "tool_call") {
            currentTextBlock = null;
            timeline = [...timeline, { kind: "tool_call", stepId: ev.id }];
          }
          const snapshotTimeline = timeline.map((t) => ({ ...t }));
          set((s) => ({
            sessions: s.sessions.map((session) =>
              session.id === chatId
                ? {
                    ...session,
                    messages: session.messages.map((m) => {
                      if (m.id !== assistantMsgId) return m;
                      const steps: AgentStep[] = m.steps ? [...m.steps] : [];

                      if (ev.type === "tool_call") {
                        steps.push({
                          type: "tool_call",
                          id: ev.id,
                          name: ev.name ?? "tool",
                          input: ev.input ?? {},
                          status: "running",
                        });
                      } else {
                        const resultStatus: "success" | "error" =
                          ev.status === "error" ? "error" : "success";
                        const callIdx = steps.findIndex(
                          (st) =>
                            st.type === "tool_call" && st.id === ev.id,
                        );
                        if (
                          callIdx !== -1 &&
                          steps[callIdx].type === "tool_call"
                        ) {
                          const call = steps[callIdx] as AgentToolCall;
                          // Find the matching tool_call to check if it's run_simulation
                          const isSimulation = call.name === "run_simulation";
                          steps[callIdx] = { ...call, status: resultStatus };

                          // After run_simulation completes, load the net and show panel
                          if (isSimulation && resultStatus === "success") {
                            simulationRan = true;
                            const simStore = useSimulationStore.getState();
                            simStore.loadNet();
                          }
                        }
                        steps.push({
                          type: "tool_result",
                          id: ev.id,
                          status: resultStatus,
                          output: ev.output ?? "",
                        });
                      }
                      return { ...m, steps, timeline: snapshotTimeline };
                    }),
                  }
                : session,
            ),
          }));
        }

        if (chunk.session_id) {
          const simStore = useSimulationStore.getState();
          simStore.setSessionId(chunk.session_id);
          // Persist backend session ID on the local chat session
          set((s) => ({
            sessions: s.sessions.map((session) =>
              session.id === chatId
                ? { ...session, backendSessionId: chunk.session_id! }
                : session,
            ),
          }));
        }

        if (chunk.snapshot_id) {
          snapshotReceived = true;
          // Attach the DB snapshot UUID to the assistant message so that
          // future simulate calls use snapshot_id (DB lookup) instead of
          // sending the full net_data JSON. Works across backend restarts.
          set((s) => ({
            sessions: s.sessions.map((session) =>
              session.id === chatId
                ? {
                    ...session,
                    messages: session.messages.map((m) =>
                      m.id === assistantMsgId
                        ? { ...m, snapshotId: chunk.snapshot_id! }
                        : m,
                    ),
                  }
                : session,
            ),
          }));
        }
      },
      onDone: () => {
        // Nothing may be left waiting on a timer once the stream is over.
        writeText();
        const wasAborted = controller.signal.aborted;

        if (!accumulated && timeline.length === 0) {
          set((s) => {
            const sessions = s.sessions.map((session) =>
              session.id === chatId
                ? {
                    ...session,
                    messages: session.messages.filter(
                      (m) => m.id !== assistantMsgId,
                    ),
                  }
                : session,
            );
            persistSessions(sessions);
            return {
              sessions,
              isSending: false,
              streamingContent: "",
              abortController: null,
              // Only show an error when the stream ended unexpectedly, not on user abort
              ...(!wasAborted
                ? { error: "Agent did not respond. Check your API key or account balance and try again." }
                : {}),
            };
          });
          return;
        }

        // snapshotId is already attached from the SSE chunk; netSnapshot is
        // fetched below (async) as a localStorage fallback for when the
        // backend DB is unavailable. isSending must NOT flip to false until
        // that fetch is at least marked pending -- ChatWorkbench's cold-load
        // effect is gated on isSending, and a gap between the two would let
        // it race ahead and 404 against a snapshot it hasn't been handed yet.
        const simStore = useSimulationStore.getState();
        const willAttachSnapshot = Boolean(
          simStore.sessionId && (simulationRan || snapshotReceived),
        );

        set((s) => {
          const sessions = s.sessions.map((session) =>
            session.id === chatId
              ? {
                  ...session,
                  messages: session.messages.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: accumulated }
                      : m,
                  ),
                }
              : session,
          );
          persistSessions(sessions);
          return {
            sessions,
            isSending: false,
            streamingContent: "",
            abortController: null,
            ...(willAttachSnapshot
              ? { attachingSnapshotMsgIds: { ...s.attachingSnapshotMsgIds, [assistantMsgId]: true as const } }
              : {}),
          };
        });

        // Best-effort: sync message history to backend for sharing
        get().syncMessages(chatId!);

        // Refresh net, then if a simulation ran, attach the loaded net
        // as a snapshot on the assistant message for inline history blocks.
        if (willAttachSnapshot) {
          simStore
            .loadNet()
            .then(() => {
              const net = useSimulationStore.getState().net;
              if (!net) return;

              set((s) => {
                const sessions = s.sessions.map((session) =>
                  session.id === chatId
                    ? {
                        ...session,
                        messages: session.messages.map((m) => {
                          if (m.id !== assistantMsgId) return m;
                          return { ...m, netSnapshot: net };
                        }),
                      }
                    : session,
                );
                persistSessions(sessions);
                return { sessions };
              });
            })
            .finally(() => {
              set((s) => {
                const { [assistantMsgId]: _cleared, ...rest } = s.attachingSnapshotMsgIds;
                return { attachingSnapshotMsgIds: rest };
              });
            });
        }
      },
        onError: (errorMsg) => {
          writeText();
          // Remove the empty assistant message on error
          set((s) => {
            const sessions = s.sessions.map((session) =>
              session.id === chatId
                ? {
                    ...session,
                    messages: session.messages.filter(
                      (m) => m.id !== assistantMsgId,
                    ),
                  }
                : session,
            );
            persistSessions(sessions);
            return {
              sessions,
              isSending: false,
              streamingContent: "",
              abortController: null,
              error: errorMsg,
            };
          });
        },
      },
      {
        credentialId: selectedCredentialId,
        netStyle,
        agentEffort,
        layoutDirection,
        signal: controller.signal,
      },
    );
  },

  loadSessionsFromBackend: async () => {
    if (get().sessionsLoading) return;
    set({ sessionsLoading: true });

    const result = await apiClient<{
      items: Array<{
        id: string;
        title: string | null;
        share_token: string;
        visibility: string;
        created_at: string;
        updated_at: string;
      }>;
      has_more: boolean;
    }>(`/api/v1/sessions?limit=${PAGE_SIZE}&offset=0`);

    set({ sessionsLoading: false });
    if (!result.ok) return;

    const localSessions = get().sessions;
    const localMap = new Map(localSessions.map((s) => [s.id, s]));
    // Index: backendSessionId → real local session (sessions that have sent messages)
    const byBackendId = new Map(
      localSessions
        .filter((s) => s.backendSessionId)
        .map((s) => [s.backendSessionId!, s]),
    );

    for (const bs of result.data.items) {
      if (byBackendId.has(bs.id)) {
        // This backend session is already tracked locally under a different local ID.
        // Remove stale duplicate entry (id === bs.id, no backendSessionId) if present.
        const dup = localMap.get(bs.id);
        if (dup && !dup.backendSessionId) {
          localMap.delete(bs.id);
        }
        const local = byBackendId.get(bs.id)!;
        if (bs.title && local.title === "New Chat") {
          local.title = bs.title;
        }
      } else if (localMap.has(bs.id)) {
        const local = localMap.get(bs.id)!;
        if (bs.title && local.title === "New Chat") {
          local.title = bs.title;
        }
      } else {
        localMap.set(bs.id, {
          id: bs.id,
          title: bs.title ?? "Chat",
          messages: [],
          createdAt: new Date(bs.created_at).getTime(),
          updatedAt: new Date(bs.updated_at).getTime(),
          shareToken: bs.share_token,
          visibility: bs.visibility as SessionVisibility,
        });
      }
    }

    const merged = Array.from(localMap.values()).sort(
      (a, b) => b.updatedAt - a.updatedAt,
    );

    // If activeChatId pointed to a stale duplicate that was just removed,
    // redirect it to the real local session.
    const { activeChatId } = get();
    let correctedActiveChatId = activeChatId;
    if (activeChatId && !localMap.has(activeChatId)) {
      const real = byBackendId.get(activeChatId);
      if (real) {
        correctedActiveChatId = real.id;
        setItem(ACTIVE_CHAT_KEY, real.id);
      }
    }

    persistSessions(merged);
    set({
      sessions: merged,
      sessionsHasMore: result.data.has_more,
      sessionsOffset: PAGE_SIZE,
      ...(correctedActiveChatId !== activeChatId
        ? { activeChatId: correctedActiveChatId }
        : {}),
    });
  },

  loadMoreSessions: async () => {
    const { sessionsLoading, sessionsHasMore, sessionsOffset, sessions } = get();
    if (sessionsLoading || !sessionsHasMore) return;

    set({ sessionsLoading: true });
    const result = await apiClient<{
      items: Array<{
        id: string;
        title: string | null;
        share_token: string;
        visibility: string;
        created_at: string;
        updated_at: string;
      }>;
      has_more: boolean;
    }>(`/api/v1/sessions?limit=${PAGE_SIZE}&offset=${sessionsOffset}`);

    set({ sessionsLoading: false });
    if (!result.ok) return;

    const localMap = new Map(sessions.map((s) => [s.id, s]));
    const byBackendId = new Map(
      sessions
        .filter((s) => s.backendSessionId)
        .map((s) => [s.backendSessionId!, s]),
    );
    for (const bs of result.data.items) {
      if (!localMap.has(bs.id) && !byBackendId.has(bs.id)) {
        localMap.set(bs.id, {
          id: bs.id,
          title: bs.title ?? "Chat",
          messages: [],
          createdAt: new Date(bs.created_at).getTime(),
          updatedAt: new Date(bs.updated_at).getTime(),
          shareToken: bs.share_token,
          visibility: bs.visibility as SessionVisibility,
        });
      }
    }

    const merged = Array.from(localMap.values()).sort(
      (a, b) => b.updatedAt - a.updatedAt,
    );

    persistSessions(merged);
    set({
      sessions: merged,
      sessionsHasMore: result.data.has_more,
      sessionsOffset: sessionsOffset + PAGE_SIZE,
    });
  },
}));
