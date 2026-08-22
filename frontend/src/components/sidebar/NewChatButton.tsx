import { SquarePen } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chat-store";

export function NewChatButton() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const createChat = useChatStore((s) => s.createChat);

  const handleClick = () => {
    const id = createChat();
    navigate(`/chat/${id}`);
  };

  return (
    <button
      type="button"
      className={cn(
        "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm",
        "text-text-primary hover:bg-sidebar-hover",
        "transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-2",
        "focus-visible:outline-accent",
      )}
      onClick={handleClick}
    >
      <SquarePen size={18} />
      <span>{t("sidebar.newChat")}</span>
    </button>
  );
}
