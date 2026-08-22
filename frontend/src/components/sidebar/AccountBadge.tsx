import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { LogOut, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar } from "@/components/common/Avatar";
import { DropdownMenu } from "@/components/common/DropdownMenu";
import { useAuthStore } from "@/stores/auth-store";
import { useUiStore } from "@/stores/ui-store";

export function AccountBadge() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const accountDropdownOpen = useUiStore((s) => s.accountDropdownOpen);
  const setAccountDropdownOpen = useUiStore((s) => s.setAccountDropdownOpen);
  const authUser = useAuthStore((s) => s.user);
  const authMode = useAuthStore((s) => s.authMode);
  const logout = useAuthStore((s) => s.logout);

  const userName = authUser?.name ?? authUser?.email ?? "User";

  const menuItems = [
    {
      key: "settings",
      label: t("account.settings"),
      icon: <Settings size={16} />,
      onClick: () => navigate("/settings"),
    },
    // No accounts to log out of in single-user mode.
    ...(authMode === "single_user"
      ? []
      : [
          {
            key: "logout",
            label: t("account.logout"),
            icon: <LogOut size={16} />,
            onClick: () => logout(),
          },
        ]),
  ];

  return (
    <div className="relative">
      <button
        type="button"
        className={cn(
          "flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm",
          "text-text-primary hover:bg-sidebar-hover",
          "transition-colors duration-150",
          "focus-visible:outline-2 focus-visible:outline-offset-2",
          "focus-visible:outline-accent",
        )}
        onClick={() => setAccountDropdownOpen(!accountDropdownOpen)}
        aria-expanded={accountDropdownOpen}
        aria-haspopup="menu"
      >
        <Avatar name={userName} src={authUser?.picture ?? undefined} size="sm" />
        <span className="flex-1 truncate text-left">{userName}</span>
      </button>

      <DropdownMenu
        open={accountDropdownOpen}
        onClose={() => setAccountDropdownOpen(false)}
        items={menuItems}
        className="bottom-full left-0 mb-1"
      />
    </div>
  );
}
