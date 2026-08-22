import { useEffect } from "react";
import { cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/use-media-query";
import { useUiStore } from "@/stores/ui-store";
import { NewChatButton } from "@/components/sidebar/NewChatButton";
import { ChatSearch } from "@/components/sidebar/ChatSearch";
import { ChatList } from "@/components/sidebar/ChatList";
import { SidebarToggle } from "@/components/layout/SidebarToggle";

export function Sidebar() {
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);
  const setSidebarOpen = useUiStore((s) => s.setSidebarOpen);
  const isMobile = useIsMobile();

  useEffect(() => {
    if (isMobile) {
      setSidebarOpen(false);
    }
  }, [isMobile, setSidebarOpen]);

  const sidebarContent = (
    <nav
      className={cn(
        "flex h-full w-[260px] flex-col bg-sidebar-bg",
        "border-r border-border",
      )}
    >
      <div className="flex flex-col gap-1 p-2">
        <div className="flex items-center gap-1">
          <div className="min-w-0 flex-1">
            <NewChatButton />
          </div>
          <SidebarToggle />
        </div>
        <ChatSearch />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <ChatList />
      </div>
    </nav>
  );

  if (isMobile) {
    return (
      <>
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-40 bg-backdrop"
            onClick={() => setSidebarOpen(false)}
            aria-hidden="true"
          />
        )}
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-50 transition-transform duration-300",
            sidebarOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          {sidebarContent}
        </aside>
      </>
    );
  }

  return (
    <aside className="h-full overflow-hidden">
      {sidebarContent}
    </aside>
  );
}
