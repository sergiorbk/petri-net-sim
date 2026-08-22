import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { Language } from "@/types/ui";

const languages: { value: Language; labelKey: string }[] = [
  { value: "en", labelKey: "settings.languageEn" },
  { value: "uk", labelKey: "settings.languageUk" },
];

export function LanguageSwitcher() {
  const { t } = useTranslation();
  const language = useUiStore((s) => s.language);
  const setLanguage = useUiStore((s) => s.setLanguage);

  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-text-primary">
        {t("settings.language")}
      </label>
      <div className="flex gap-1 rounded-lg bg-surface-secondary p-1">
        {languages.map(({ value, labelKey }) => (
          <button
            key={value}
            type="button"
            className={cn(
              "flex flex-1 items-center justify-center rounded-md px-3 py-1.5",
              "text-sm transition-colors duration-150",
              "focus-visible:outline-2 focus-visible:outline-offset-2",
              "focus-visible:outline-accent",
              language === value
                ? "bg-surface text-text-primary shadow-sm"
                : "text-text-muted hover:text-text-secondary",
            )}
            onClick={() => setLanguage(value)}
            aria-pressed={language === value}
          >
            {t(labelKey)}
          </button>
        ))}
      </div>
    </div>
  );
}
