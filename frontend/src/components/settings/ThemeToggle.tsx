import { Monitor, Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { Theme } from "@/types/ui";

const themes: { value: Theme; icon: typeof Sun; labelKey: string }[] = [
  { value: "light", icon: Sun, labelKey: "settings.themeLight" },
  { value: "dark", icon: Moon, labelKey: "settings.themeDark" },
  { value: "system", icon: Monitor, labelKey: "settings.themeSystem" },
];

export function ThemeToggle() {
  const { t } = useTranslation();
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);

  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-text-primary">
        {t("settings.theme")}
      </label>
      <div className="flex gap-1 rounded-lg bg-surface-secondary p-1">
        {themes.map(({ value, icon: Icon, labelKey }) => (
          <button
            key={value}
            type="button"
            className={cn(
              "flex flex-1 items-center justify-center gap-2 rounded-md px-3 py-1.5",
              "text-sm transition-colors duration-150",
              "focus-visible:outline-2 focus-visible:outline-offset-2",
              "focus-visible:outline-accent",
              theme === value
                ? "bg-surface text-text-primary shadow-sm"
                : "text-text-muted hover:text-text-secondary",
            )}
            onClick={() => setTheme(value)}
            aria-pressed={theme === value}
          >
            <Icon size={16} />
            <span>{t(labelKey)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
