import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

interface CopyFieldProps {
  label: string;
  value: string;
  /** Multi-line values (config snippets, curl commands) wrap instead of truncating. */
  multiline?: boolean;
}

/** A read-only value the user is meant to paste somewhere else. */
export function CopyField({ label, value, multiline }: CopyFieldProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be refused (insecure origin, denied permission).
      // The value is on screen and selectable either way.
    }
  };

  return (
    <div>
      <label className="mb-1.5 block text-xs font-medium text-text-secondary">
        {label}
      </label>
      <div
        className={cn(
          "flex gap-2 rounded-lg border border-border bg-surface-secondary p-2",
          multiline ? "items-start" : "items-center",
        )}
      >
        <code
          className={cn(
            "min-w-0 flex-1 font-mono text-xs text-text-primary",
            multiline ? "whitespace-pre-wrap break-all" : "truncate",
          )}
        >
          {value}
        </code>
        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? t("settings.integrations.copied") : t("settings.integrations.copy")}
          title={copied ? t("settings.integrations.copied") : t("settings.integrations.copy")}
          className={cn(
            "shrink-0 rounded-md p-1.5 text-text-muted transition-colors",
            "hover:bg-surface-hover hover:text-text-primary",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          )}
        >
          {copied ? (
            <Check size={14} className="text-accent" />
          ) : (
            <Copy size={14} />
          )}
        </button>
      </div>
    </div>
  );
}
