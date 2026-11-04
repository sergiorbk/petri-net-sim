import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useNameConflictStore, type DuplicateNamePolicy } from "@/stores/name-conflict-store";

const OPTIONS: { value: DuplicateNamePolicy; labelKey: string; hintKey: string }[] = [
  { value: "ask", labelKey: "settings.editor.ask", hintKey: "settings.editor.askHint" },
  { value: "auto", labelKey: "settings.editor.auto", hintKey: "settings.editor.autoHint" },
  { value: "keep", labelKey: "settings.editor.keep", hintKey: "settings.editor.keepHint" },
];

/**
 * Editor behaviour that is personal rather than part of a net. The only
 * entry for now is what happens when a name is already taken; it is the same
 * value the warning's "Remember my choice" box writes, so either place can
 * change it back.
 */
export function EditorSection() {
  const { t } = useTranslation();
  const policy = useNameConflictStore((s) => s.policy);
  const setPolicy = useNameConflictStore((s) => s.setPolicy);

  return (
    <div className="flex flex-col gap-3">
      <div>
        <h2 className="text-sm font-medium text-text-primary">
          {t("settings.editor.duplicateNames")}
        </h2>
        <p className="mt-1 text-sm text-text-secondary">
          {t("settings.editor.duplicateNamesHint")}
        </p>
      </div>

      <div role="radiogroup" aria-label={t("settings.editor.duplicateNames")} className="flex flex-col gap-2">
        {OPTIONS.map(({ value, labelKey, hintKey }) => (
          <label
            key={value}
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-lg border px-4 py-3",
              "transition-colors duration-100 focus-within:outline-2 focus-within:outline-accent",
              policy === value
                ? "border-accent bg-surface-hover"
                : "border-border hover:bg-surface-hover",
            )}
          >
            <input
              type="radio"
              name="duplicate-name-policy"
              value={value}
              checked={policy === value}
              onChange={() => setPolicy(value)}
              className="mt-1 accent-[var(--color-accent)]"
            />
            <span className="flex flex-col">
              <span className="text-sm font-medium text-text-primary">{t(labelKey)}</span>
              <span className="text-xs text-text-secondary">{t(hintKey)}</span>
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}
