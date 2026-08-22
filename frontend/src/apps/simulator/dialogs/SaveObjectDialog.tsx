import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

interface SaveObjectDialogProps {
  onSave: (name: string, description: string) => void;
  onClose: () => void;
}

export function SaveObjectDialog({ onSave, onClose }: SaveObjectDialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = name.trim();
      if (!trimmed) return;
      onSave(trimmed, description.trim());
    },
    [name, description, onSave],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface p-5 shadow-2xl">
        <h2 className="mb-4 text-sm font-semibold text-text-primary">
          {t("dialog.saveObject.title")}
        </h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-medium text-text-secondary">
              {t("common.name")}
            </span>
            <input
              ref={inputRef}
              autoFocus
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("dialog.saveObject.namePlaceholder")}
              className={cn(
                "rounded-md border border-border bg-surface-secondary px-2.5 py-1.5",
                "text-sm text-text-primary placeholder:text-text-muted",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
              )}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] font-medium text-text-secondary">
              {t("dialog.saveObject.description")}
            </span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder={t("dialog.saveObject.descriptionPlaceholder")}
              className={cn(
                "resize-none rounded-md border border-border bg-surface-secondary px-2.5 py-1.5",
                "text-sm text-text-primary placeholder:text-text-muted",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
              )}
            />
          </label>
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium",
                "text-text-secondary hover:bg-surface-hover",
              )}
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={!name.trim()}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium",
                "transition-colors",
                name.trim()
                  ? "bg-accent text-white hover:bg-accent/90"
                  : "cursor-not-allowed bg-surface-hover text-text-muted",
              )}
            >
              {t("common.save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
