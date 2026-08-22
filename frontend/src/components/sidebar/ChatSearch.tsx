import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chat-store";

export function ChatSearch() {
  const { t } = useTranslation();
  const searchQuery = useChatStore((s) => s.searchQuery);
  const setSearchQuery = useChatStore((s) => s.setSearchQuery);

  return (
    <div className="relative">
      <Search
        size={16}
        className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted"
        aria-hidden="true"
      />
      <input
        type="search"
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        placeholder={t("sidebar.searchChats")}
        className={cn(
          "w-full rounded-lg bg-surface py-1.5 pl-8 pr-3 text-sm",
          "text-text-primary placeholder:text-text-muted",
          "border border-border focus:border-accent focus:outline-none",
          "transition-colors duration-150",
        )}
      />
    </div>
  );
}
