import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Toggle } from "@/components/common/Toggle";
import { useAuthStore, type UpdateProfilePayload } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

interface IntegrationSwitchProps {
  label: string;
  description: string;
  checked: boolean;
  /** Which profile field this switch writes: "mcp_enabled" or "http_api_enabled". */
  field: keyof Pick<UpdateProfilePayload, "mcp_enabled" | "http_api_enabled">;
  /** Set when the server does not serve this integration at all. */
  unavailableNote?: string;
}

/**
 * The on/off switch for one integration.
 *
 * It writes through to PATCH /api/v1/auth/me immediately -- there is no Save
 * button on this page, so a switch that only moved locally would be a switch
 * that lies. The optimistic flip is rolled back if the request fails.
 */
export function IntegrationSwitch({
  label,
  description,
  checked,
  field,
  unavailableNote,
}: IntegrationSwitchProps) {
  const { t } = useTranslation();
  const updateProfile = useAuthStore((s) => s.updateProfile);
  const descriptionId = useId();

  const [pending, setPending] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  const shown = pending ?? checked;

  const handleChange = async (next: boolean) => {
    setPending(next);
    setError(null);
    const result = await updateProfile({ [field]: next });
    setPending(null);
    if (!result.ok) setError(result.error);
  };

  return (
    <div
      className={cn(
        "flex items-start gap-4 rounded-lg border border-border",
        "bg-surface-secondary p-4",
      )}
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-text-primary">{label}</p>
        <p id={descriptionId} className="mt-1 text-xs text-text-muted">
          {description}
        </p>
        {unavailableNote && (
          <p className="mt-1.5 text-xs text-amber-600 dark:text-amber-500">
            {unavailableNote}
          </p>
        )}
        {error && (
          <p className="mt-1.5 text-xs text-red-500" role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2 pt-0.5">
        <span className="text-xs text-text-muted">
          {shown ? t("settings.integrations.on") : t("settings.integrations.off")}
        </span>
        <Toggle
          checked={shown}
          onChange={handleChange}
          label={label}
          describedBy={descriptionId}
          disabled={pending !== null}
        />
      </div>
    </div>
  );
}
