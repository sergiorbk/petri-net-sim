import { type ReactNode } from "react";
import { ArrowLeft, Key, Monitor, Cpu, User } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { cn } from "@/lib/utils";
import { IconButton } from "@/components/common/IconButton";
import { WordMark } from "@/components/common/WordMark";
import { ApiKeysSection } from "./ApiKeysSection";
import { LlmProfilesSection } from "./LlmProfilesSection";
import { ProfileSection } from "./ProfileSection";
import { ThemeToggle } from "./ThemeToggle";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { McpSection } from "./integrations/McpSection";
import { HttpApiSection } from "./integrations/HttpApiSection";

export type SettingsSection =
  | "appearance"
  | "profile"
  | "llm"
  | "api-keys"
  | "mcp"
  | "api";

interface NavItem {
  id: SettingsSection;
  labelKey: string;
  /** Rendered inside a fixed-width column, so glyphs and word marks line up. */
  icon: ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  { id: "appearance", labelKey: "settings.nav.appearance", icon: <Monitor size={16} /> },
  { id: "profile", labelKey: "settings.nav.profile", icon: <User size={16} /> },
  { id: "llm", labelKey: "settings.nav.llmModels", icon: <Cpu size={16} /> },
  { id: "api-keys", labelKey: "settings.nav.apiKeys", icon: <Key size={16} /> },
  // The same word marks the activity bar uses for these two, so the icon a
  // reader clicked out there is the one they land next to in here.
  { id: "mcp", labelKey: "settings.nav.mcp", icon: <WordMark className="text-[10px]">MCP</WordMark> },
  { id: "api", labelKey: "settings.nav.api", icon: <WordMark className="text-[10px]">API</WordMark> },
];

const SECTION_IDS = NAV_ITEMS.map((item) => item.id);

function isSection(value: string | undefined): value is SettingsSection {
  return value !== undefined && SECTION_IDS.includes(value as SettingsSection);
}

export function SettingsView() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { section: sectionParam } = useParams();

  // The section lives in the URL so the activity bar can link straight at
  // one, and so a reload lands where the user was. The location.state form
  // predates that and is still honoured -- older links carry it.
  const stateSection = (location.state as { section?: string } | null)?.section;
  const section: SettingsSection = isSection(sectionParam)
    ? sectionParam
    : isSection(stateSection)
      ? stateSection
      : "appearance";

  return (
    <div className="flex h-full">
      <nav className="flex w-56 shrink-0 flex-col border-r border-border bg-sidebar-bg">
        <div className="flex items-center gap-1.5 px-3 py-3">
          <IconButton aria-label="Back" onClick={() => navigate(-1)}>
            <ArrowLeft size={18} />
          </IconButton>
          <span className="text-sm font-semibold text-text-primary">
            {t("settings.title")}
          </span>
        </div>

        <div className="flex flex-col gap-0.5 px-2 pb-2">
          {NAV_ITEMS.map(({ id, labelKey, icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => navigate(`/settings/${id}`)}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm",
                "transition-colors duration-100",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                section === id
                  ? "bg-surface-hover font-medium text-text-primary"
                  : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
              )}
              aria-current={section === id ? "page" : undefined}
            >
              {/* A fixed column: a word mark is wider than a 16px glyph, and
                  without it every label below MCP would sit further right. */}
              <span className="flex w-5 shrink-0 justify-center" aria-hidden="true">
                {icon}
              </span>
              {t(labelKey)}
            </button>
          ))}
        </div>
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* Full width rather than a centred column: the settings nav already
            takes the left edge, so a centred 2xl column left a gutter wide
            enough to read as a bug. Capped at 5xl so a line of description
            text on an ultrawide monitor is still a line and not a ribbon. */}
        <div className="w-full max-w-5xl px-8 py-8">
          {section === "appearance" && (
            <div className="flex flex-col gap-6">
              <ThemeToggle />
              <LanguageSwitcher />
            </div>
          )}
          {section === "profile" && <ProfileSection />}
          {section === "llm" && <LlmProfilesSection />}
          {section === "api-keys" && <ApiKeysSection />}
          {section === "mcp" && <McpSection />}
          {section === "api" && <HttpApiSection />}
        </div>
      </div>
    </div>
  );
}
