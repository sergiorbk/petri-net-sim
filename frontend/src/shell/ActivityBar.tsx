import { type MouseEvent, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Lock, LogIn, MessageSquare, Network, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar } from "@/components/common/Avatar";
import { WordMark } from "@/components/common/WordMark";
import { useAuthStore } from "@/stores/auth-store";

/** Settings sections that have their own icon down here, so the gear does
 *  not also light up while the reader is looking at one of them. */
const OWN_ICON_SECTIONS = ["/settings/mcp", "/settings/api"];

export function ActivityBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);

  const handleChatClick = (e: MouseEvent) => {
    if (!isAuthenticated) {
      e.preventDefault();
      navigate("/login");
    }
  };

  const userName = user?.name ?? user?.email ?? "User";

  const inSettings = location.pathname.startsWith("/settings");
  const settingsActive =
    inSettings && !OWN_ICON_SECTIONS.includes(location.pathname);

  return (
    <nav
      aria-label="Applications"
      className={cn(
        // 44px wide against 40px items: the gutter is the 2px that keeps the
        // icons off the border, and nothing more.
        "flex h-full w-11 shrink-0 flex-col items-center gap-2",
        "border-r border-border bg-sidebar-bg py-1",
      )}
    >
      <ActivityItem
        to="/"
        end
        icon={<Network size={20} />}
        label="Simulator"
      />
      <ActivityItem
        to="/chat"
        icon={<MessageSquare size={20} />}
        label={
          isAuthenticated
            ? "Chat generator (Beta)"
            : "Chat generator (Beta) — sign in to use"
        }
        onClick={handleChatClick}
        locked={!isAuthenticated}
      />

      <div className="mt-auto flex flex-col items-center gap-2">
        {isAuthenticated && (
          <>
            <ActivityItem
              to="/settings/mcp"
              icon={<WordMark className="text-[11px]">MCP</WordMark>}
              label={t("settings.integrations.mcp.title")}
            />
            <ActivityItem
              to="/settings/api"
              icon={<WordMark className="text-[11px]">API</WordMark>}
              label={t("settings.integrations.api.title")}
            />
            <ActivityItem
              to="/settings"
              icon={<Settings size={20} />}
              label={t("account.settings")}
              active={settingsActive}
            />
          </>
        )}
        {isAuthenticated ? (
          <button
            type="button"
            onClick={() => navigate("/settings/profile")}
            aria-label={userName}
            title={userName}
            className={cn(
              "flex h-10 w-10 items-center justify-center rounded-lg",
              "transition-colors hover:bg-sidebar-hover",
              "focus-visible:outline-2 focus-visible:outline-offset-2",
              "focus-visible:outline-accent",
            )}
          >
            <Avatar
              name={userName}
              src={user?.picture ?? undefined}
              size="sm"
            />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => navigate("/login")}
            aria-label="Sign in"
            title="Sign in"
            className={cn(
              "flex h-10 w-10 items-center justify-center rounded-lg",
              "text-text-muted transition-colors",
              "hover:bg-sidebar-hover hover:text-text-primary",
              "focus-visible:outline-2 focus-visible:outline-offset-2",
              "focus-visible:outline-accent",
            )}
          >
            <LogIn size={20} />
          </button>
        )}
      </div>
    </nav>
  );
}

interface ActivityItemProps {
  to: string;
  icon: ReactNode;
  label: string;
  end?: boolean;
  onClick?: (e: MouseEvent) => void;
  locked?: boolean;
  /** Overrides NavLink's own path matching where it is too broad -- the
   *  gear covers /settings/*, minus the sections with their own icon. */
  active?: boolean;
}

function ActivityItem({
  to,
  icon,
  label,
  end,
  onClick,
  locked,
  active,
}: ActivityItemProps) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onClick}
      title={label}
      aria-label={label}
      className={({ isActive }) =>
        cn(
          "relative flex h-10 w-10 items-center justify-center rounded-lg",
          "transition-colors focus-visible:outline-2",
          "focus-visible:outline-offset-2 focus-visible:outline-accent",
          (active ?? isActive) && !locked
            ? "bg-sidebar-hover text-text-primary"
            : "text-text-muted hover:bg-sidebar-hover hover:text-text-primary",
          locked && "opacity-60",
        )
      }
    >
      {icon}
      {locked && (
        <span
          aria-hidden="true"
          className={cn(
            "absolute -bottom-0.5 -right-0.5 flex h-4 w-4 items-center",
            "justify-center rounded-full bg-surface text-text-muted",
            "shadow-sm ring-1 ring-border",
          )}
        >
          <Lock size={10} />
        </span>
      )}
    </NavLink>
  );
}
