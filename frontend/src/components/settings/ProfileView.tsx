import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { IconButton } from "@/components/common/IconButton";
import { Avatar } from "@/components/common/Avatar";
import { useAuthStore } from "@/stores/auth-store";

export function ProfileView() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);

  const displayName = user?.name ?? "User";

  return (
    <div className="mx-auto h-full max-w-xl overflow-y-auto px-4 py-6">
      <div className="mb-6 flex items-center gap-2">
        <IconButton
          aria-label="Back"
          onClick={() => navigate(-1)}
        >
          <ArrowLeft size={20} />
        </IconButton>
        <h2 className="text-lg font-semibold text-text-primary">
          {t("account.profile")}
        </h2>
      </div>

      <div className="flex flex-col items-center gap-4 rounded-lg border border-border bg-surface-secondary p-8">
        <Avatar
          name={displayName}
          src={user?.picture ?? undefined}
          size="md"
        />
        <div className="text-center">
          <p className="text-sm font-medium text-text-primary">{displayName}</p>
          {user?.email && (
            <p className="mt-1 text-xs text-text-muted">{user.email}</p>
          )}
        </div>
      </div>
    </div>
  );
}
