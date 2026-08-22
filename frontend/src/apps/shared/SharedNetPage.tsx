import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { ArrowLeft, LogIn } from "lucide-react";
import { publicApiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import { useChatStore } from "@/stores/chat-store";
import { ChatMessageList } from "@/components/chat/ChatMessageList";
import type { ChatMessage } from "@/types/chat";

interface SharedSession {
  title: string | null;
  share_token: string;
  visibility: string;
  messages: Array<{
    role: string;
    content: string;
    timestamp: number;
    snapshot_id?: string;
  }>;
  created_at: string;
  updated_at: string;
}

export function SharedNetPage() {
  const { shareToken } = useParams<{ shareToken: string }>();
  const navigate = useNavigate();

  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const addSharedSession = useChatStore((s) => s.addSharedSession);

  const [messages, setMessages] = useState<ChatMessage[] | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const syncedRef = useRef(false);

  useEffect(() => {
    if (!shareToken) return;

    publicApiClient<SharedSession>(`/api/v1/sessions/shared/${shareToken}`).then(
      (res) => {
        if (!res.ok) {
          setError(
            res.status === 404
              ? "Чат не знайдено або доступ закрито."
              : "Помилка завантаження.",
          );
          return;
        }

        const data = res.data;
        setTitle(data.title);

        const mapped: ChatMessage[] = data.messages.map((m, i) => ({
          id: `shared-${i}`,
          role: m.role as "user" | "assistant",
          content: m.content,
          timestamp: m.timestamp,
          ...(m.snapshot_id ? { snapshotId: m.snapshot_id } : {}),
        }));
        setMessages(mapped);
      },
    );
  }, [shareToken]);

  // If authenticated — silently add to the user's sidebar list
  useEffect(() => {
    if (!isAuthenticated || !shareToken || !messages || syncedRef.current) return;
    syncedRef.current = true;
    addSharedSession(shareToken);
  }, [isAuthenticated, shareToken, messages, addSharedSession]);

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-sm text-text-secondary">{error}</p>
        <button
          type="button"
          className="text-sm text-accent hover:underline"
          onClick={() => navigate("/")}
        >
          На головну
        </button>
      </div>
    );
  }

  if (!messages) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-text-secondary">
        Завантаження чату…
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <button
          type="button"
          className="rounded p-1 text-text-secondary hover:bg-surface-hover hover:text-text-primary"
          onClick={() => navigate(-1)}
          aria-label="Назад"
        >
          <ArrowLeft size={16} />
        </button>

        <span className="flex-1 truncate text-sm font-medium text-text-primary">
          {title ?? "Спільний чат"}
        </span>

        {!isAuthenticated && (
          <Link
            to="/login"
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-surface-hover hover:text-text-primary"
          >
            <LogIn size={13} />
            Увійти, щоб зберегти
          </Link>
        )}
      </header>

      {/* Messages */}
      {messages.length === 0 ? (
        <div className="flex flex-1 items-center justify-center text-sm text-text-secondary">
          Цей чат порожній.
        </div>
      ) : (
        <ChatMessageList messages={messages} />
      )}
    </div>
  );
}
