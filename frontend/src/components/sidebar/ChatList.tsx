import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useChatStore } from "@/stores/chat-store";
import { ChatListItem } from "./ChatListItem";

export function ChatList() {
  const { t } = useTranslation();
  const allSessions = useChatStore((s) => s.sessions);
  const searchQuery = useChatStore((s) => s.searchQuery);
  const q = searchQuery.trim().toLowerCase();
  const sessions = q
    ? allSessions.filter((s) => s.title.toLowerCase().includes(q))
    : allSessions;
  const hasMore = useChatStore((s) => s.sessionsHasMore);
  const isLoading = useChatStore((s) => s.sessionsLoading);
  const loadMore = useChatStore((s) => s.loadMoreSessions);
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMore();
        }
      },
      { threshold: 0.1 },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMore]);

  if (sessions.length === 0 && !isLoading) {
    return (
      <p className="px-3 py-4 text-center text-xs text-text-muted">
        {t("sidebar.noChats")}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-0.5">
      {sessions.map((session) => (
        <ChatListItem key={session.id} session={session} />
      ))}

      {/* Sentinel: triggers loadMore when scrolled into view */}
      <div ref={sentinelRef} className="py-1">
        {isLoading && (
          <div className="flex justify-center py-2">
            <span className="inline-flex gap-1">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-text-muted" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-text-muted [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-text-muted [animation-delay:300ms]" />
            </span>
          </div>
        )}
        {!hasMore && sessions.length > 0 && (
          <p className="py-2 text-center text-[11px] text-text-muted opacity-50">
            {t("sidebar.allLoaded", "All chats loaded")}
          </p>
        )}
      </div>
    </div>
  );
}
