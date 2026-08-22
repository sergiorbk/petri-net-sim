import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

interface NameDialogProps {
  title: string;
  initialName: string;
  submitLabel: string;
  busyLabel?: string;
  placeholder?: string;
  onSubmit: (name: string) => Promise<void> | void;
  onClose: () => void;
}

/**
 * Reusable modal for prompting a single name string before an action.
 * Auto-selects the input on mount; submits on Enter; closes on Escape or
 * backdrop click; passes the trimmed name to onSubmit.
 */
export function NameDialog({
  title,
  initialName,
  submitLabel,
  busyLabel,
  placeholder,
  onSubmit,
  onClose,
}: NameDialogProps) {
  const { t } = useTranslation();
  const nameId = useId();
  const inputRef = useRef<HTMLInputElement>(null);

  const [name, setName] = useState(initialName);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    inputRef.current?.select();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-surface p-6 shadow-xl">
        <h2 className="mb-5 text-base font-semibold text-text-primary">{title}</h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor={nameId} className="text-xs text-text-secondary">
              {t("common.name")}
            </label>
            <input
              id={nameId}
              ref={inputRef}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={cn(
                "w-full rounded-lg border border-border bg-surface-secondary",
                "px-3 py-2 text-sm text-text-primary outline-none",
                "focus:border-accent focus:ring-1 focus:ring-accent",
              )}
              placeholder={placeholder}
              required
              maxLength={255}
              disabled={busy}
            />
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}

          <div className="mt-1 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className={cn(
                "rounded-lg px-4 py-2 text-sm text-text-secondary",
                "transition-colors hover:bg-surface-hover hover:text-text-primary",
                "disabled:opacity-50",
              )}
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={busy || !name.trim()}
              className={cn(
                "rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white",
                "transition-opacity disabled:opacity-50",
              )}
            >
              {busy ? (busyLabel ?? submitLabel) : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
