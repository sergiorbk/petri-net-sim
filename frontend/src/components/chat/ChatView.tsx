import { useTranslation } from "react-i18next";
import { useChatStore } from "@/stores/chat-store";
import { ChatInput } from "./ChatInput";
import { ChatMessageList } from "./ChatMessageList";
import { EmptyState } from "./EmptyState";

export function ChatView() {
  const { t } = useTranslation();
  const activeChat = useChatStore((s) => s.getActiveChat());
  const isSending = useChatStore((s) => s.isSending);
  const error = useChatStore((s) => s.error);
  const sendMessage = useChatStore((s) => s.sendMessage);
  const abortGeneration = useChatStore((s) => s.abortGeneration);
  const clearError = useChatStore((s) => s.clearError);

  const handleSend = (content: string) => {
    sendMessage(content);
  };

  if (!activeChat || activeChat.messages.length === 0) {
    if (activeChat?.isShared) {
      return (
        <div className="flex h-full items-center justify-center text-sm text-text-secondary">
          {t("shared.emptyChat")}
        </div>
      );
    }
    return <EmptyState onSend={handleSend} />;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ChatMessageList messages={activeChat.messages} />

      {!activeChat.isShared && (
        <>
          {error && (
            <div className="mx-auto w-full max-w-3xl px-4">
              <div className="mb-2 flex items-center justify-between rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
                <span>{error}</span>
                <button
                  type="button"
                  className="ml-2 text-red-500 hover:text-red-700"
                  onClick={clearError}
                  aria-label="Dismiss"
                >
                  x
                </button>
              </div>
            </div>
          )}
          <div className="mx-auto w-full max-w-3xl px-4 pb-4 pt-2">
            <ChatInput onSend={handleSend} disabled={isSending} onStop={abortGeneration} />
          </div>
        </>
      )}
    </div>
  );
}
