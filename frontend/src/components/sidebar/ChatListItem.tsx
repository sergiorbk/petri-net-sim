import { useRef, useState } from "react";
import { MoreHorizontal, Share2, Trash2, Users } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chat-store";
import { DropdownMenu } from "@/components/common/DropdownMenu";
import { ShareDialog } from "@/components/chat/ShareDialog";
import type { ChatSession } from "@/types/chat";

interface ChatListItemProps {
  session: ChatSession;
}

export function ChatListItem({ session }: ChatListItemProps) {
  const navigate = useNavigate();
  const activeChatId = useChatStore((s) => s.activeChatId);
  const setActiveChat = useChatStore((s) => s.setActiveChat);
  const deleteChat = useChatStore((s) => s.deleteChat);
  const isActive = activeChatId === session.id;

  const [menuOpen, setMenuOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const handleClick = () => {
    setActiveChat(session.id);
    navigate(`/chat/${session.id}`);
  };

  const menuItems = session.isShared
    ? [
        {
          key: "delete",
          label: "Прибрати зі списку",
          icon: <Trash2 size={14} />,
          danger: true as const,
          onClick: () => deleteChat(session.id),
        },
      ]
    : [
        {
          key: "share",
          label: "Поділитися",
          icon: <Share2 size={14} />,
          onClick: () => setShareOpen(true),
        },
        {
          key: "delete",
          label: "Видалити",
          icon: <Trash2 size={14} />,
          danger: true as const,
          onClick: () => deleteChat(session.id),
        },
      ];

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        className={cn(
          "group flex items-center gap-2 rounded-lg px-3 py-2 text-sm",
          "cursor-pointer transition-colors duration-150",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          isActive
            ? "bg-sidebar-hover text-text-primary"
            : "text-text-secondary hover:bg-sidebar-hover hover:text-text-primary",
        )}
        onClick={handleClick}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleClick();
          }
        }}
      >
        {session.isShared && (
          <Users size={15} className="shrink-0 text-accent" />
        )}
        <span className="flex-1 truncate">{session.title}</span>

        {/* Three-dots menu trigger */}
        <div className="relative shrink-0">
          <button
            ref={triggerRef}
            type="button"
            className={cn(
              "rounded p-0.5 transition-opacity",
              "hover:bg-surface-hover hover:text-text-primary",
              "focus-visible:opacity-100 focus-visible:outline-none",
              menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100",
            )}
            aria-label="Дії з чатом"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen((v) => !v);
            }}
          >
            <MoreHorizontal size={14} />
          </button>

          <DropdownMenu
            open={menuOpen}
            onClose={() => setMenuOpen(false)}
            items={menuItems}
            anchorEl={triggerRef.current}
          />
        </div>
      </div>

      {shareOpen && !session.isShared && (
        <ShareDialog session={session} onClose={() => setShareOpen(false)} />
      )}
    </>
  );
}
