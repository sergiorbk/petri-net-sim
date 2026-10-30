import { type FormEvent, useEffect, useState } from "react";
import { CheckCircle, LogOut } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

type SaveStatus = "idle" | "saving" | "saved" | "error";

function AvatarDisplay({ name, src }: { name: string; src?: string | null }) {
  const initials = name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();

  return (
    <span
      className="inline-flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-accent text-xl font-semibold text-white select-none"
      aria-hidden="true"
    >
      {src ? (
        <img src={src} alt="" className="h-full w-full rounded-full object-cover" />
      ) : (
        initials
      )}
    </span>
  );
}

export function ProfileSection() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const updateProfile = useAuthStore((s) => s.updateProfile);
  const authMode = useAuthStore((s) => s.authMode);
  const logout = useAuthStore((s) => s.logout);

  const [name, setName] = useState(user?.name ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [workType, setWorkType] = useState(user?.work_type ?? "");
  const [customInstructions, setCustomInstructions] = useState(
    user?.custom_instructions ?? "",
  );
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [contributor, setContributor] = useState(user?.contributor ?? {});

  useEffect(() => {
    if (user) {
      setContributor(user.contributor ?? {});
      setName(user.name ?? "");
      setDisplayName(user.display_name ?? "");
      setWorkType(user.work_type ?? "");
      setCustomInstructions(user.custom_instructions ?? "");
    }
  }, [user]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setStatus("saving");
    const result = await updateProfile({
      name: name || undefined,
      display_name: displayName || null,
      work_type: workType || null,
      custom_instructions: customInstructions || null,
      contributor: Object.fromEntries(["nickname", "organization", "group", "contacts"].map((key) => [key, contributor[key] ?? ""])),
    });
    if (result.ok) {
      setStatus("saved");
      setTimeout(() => setStatus("idle"), 2500);
    } else {
      setStatus("error");
    }
  };

  const displayName_ = user?.name ?? user?.email ?? "User";

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
      <fieldset className="space-y-4 rounded-xl border border-border p-5">
        <legend className="px-2 text-sm font-semibold">{t("review.contributorTitle")}</legend>
        <p className="text-sm text-text-muted">{t("review.contributorHint")}</p>
        {["nickname", "organization", "group", "contacts"].map((key) => <label key={key} className="block space-y-1 text-sm"><span>{t(`review.contributor.${key}`)}</span><Input value={contributor[key] ?? ""} maxLength={1000} disabled={status === "saving"} onChange={(e) => setContributor({ ...contributor, [key]: e.target.value })} /></label>)}
      </fieldset>
      <div>
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-text-muted">
          {t("settings.profile.avatar")}
        </p>
        <AvatarDisplay name={displayName_} src={user?.picture} />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-text-primary">
          {t("settings.profile.fullName")}
        </label>
        <Input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("settings.profile.fullNamePlaceholder")}
          disabled={status === "saving"}
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-text-primary">
          {t("settings.profile.displayName")}
        </label>
        <Input
          type="text"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder={t("settings.profile.displayNamePlaceholder")}
          disabled={status === "saving"}
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-text-primary">
          {t("settings.profile.workType")}
        </label>
        <Input
          type="text"
          value={workType}
          onChange={(e) => setWorkType(e.target.value)}
          placeholder={t("settings.profile.workTypePlaceholder")}
          disabled={status === "saving"}
        />
      </div>

      <div>
        <label className="mb-1.5 block text-sm font-medium text-text-primary">
          {t("settings.profile.customInstructions")}
        </label>
        <textarea
          value={customInstructions}
          onChange={(e) => setCustomInstructions(e.target.value)}
          placeholder={t("settings.profile.customInstructionsPlaceholder")}
          disabled={status === "saving"}
          rows={4}
          className={cn(
            "w-full resize-y rounded-lg border border-border bg-surface-secondary",
            "px-3 py-2 text-sm text-text-primary placeholder:text-text-muted",
            "transition-colors duration-150",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        />
      </div>

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={status === "saving"}>
          {status === "saving"
            ? t("settings.profile.saving")
            : t("settings.profile.save")}
        </Button>
        {status === "saved" && (
          <span className="flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400">
            <CheckCircle size={15} />
            {t("settings.profile.saved")}
          </span>
        )}
        {status === "error" && (
          <span className="text-sm text-red-500">{t("settings.profile.errorSaving")}</span>
        )}
      </div>

      {/* Signing out lives with everything else about the account. It used
          to hang off the avatar's dropdown, and the avatar is now a route
          into this page rather than a menu -- leaving it there would have
          meant keeping a menu for one item. There is nothing to sign out
          of in single-user mode, which is why it is absent there. */}
      {authMode !== "single_user" && (
        <div className="border-t border-border pt-4">
          <button
            type="button"
            onClick={() => logout()}
            className={cn(
              "flex items-center gap-2 rounded-lg px-3 py-2 text-sm",
              "text-red-500 transition-colors hover:bg-surface-hover",
              "focus-visible:outline-2 focus-visible:outline-offset-2",
              "focus-visible:outline-accent",
            )}
          >
            <LogOut size={16} />
            {t("account.logout")}
          </button>
        </div>
      )}
    </form>
  );
}
