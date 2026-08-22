import type { ReactNode } from "react";
import { KeyRound } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";

interface IntegrationHeaderProps {
  title: string;
  description: string;
}

export function IntegrationHeader({ title, description }: IntegrationHeaderProps) {
  return (
    <div>
      <h2 className="text-base font-semibold text-text-primary">{title}</h2>
      <p className="mt-1 text-sm text-text-secondary">{description}</p>
    </div>
  );
}

interface IntegrationStepsProps {
  title: string;
  steps: ReactNode[];
}

/** The short how-to. Numbered because the order genuinely matters:
 *  a key has to exist before a client can be pointed at the endpoint. */
export function IntegrationSteps({ title, steps }: IntegrationStepsProps) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-medium text-text-primary">{title}</h3>
      <ol className="flex list-decimal flex-col gap-1.5 pl-5 text-sm text-text-secondary">
        {steps.map((step, i) => (
          <li key={i} className="pl-1">
            {step}
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Sends the reader to the API Keys section, which is where every one of
 * these instructions starts: without a key, neither door opens.
 */
export function ApiKeysLink() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <button
      type="button"
      onClick={() => navigate("/settings/api-keys")}
      className={cn(
        "inline-flex items-center gap-1 rounded font-medium text-accent",
        "underline underline-offset-2 transition-opacity hover:opacity-80",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
      )}
    >
      <KeyRound size={13} className="shrink-0" />
      {t("settings.integrations.apiKeysLink")}
    </button>
  );
}
