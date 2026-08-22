import { create } from "zustand";
import i18n from "@/i18n";
import { getItem, setItem } from "@/lib/storage";
import type { Language, ResolvedTheme, Theme } from "@/types/ui";

function resolveTheme(theme: Theme): ResolvedTheme {
  if (theme !== "system") return theme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function applyThemeClass(resolved: ResolvedTheme): void {
  document.documentElement.classList.toggle("dark", resolved === "dark");
}

interface UiState {
  sidebarOpen: boolean;
  chatPanelOpen: boolean;
  canvasPanelOpen: boolean;
  theme: Theme;
  resolvedTheme: ResolvedTheme;
  language: Language;
  accountDropdownOpen: boolean;
  /**
   * Whether the post-run statistics panel is showing. Per-run, not persisted:
   * it always starts closed for a fresh run and is force-closed when
   * simulation mode is exited (see simulation-store's exitSimulationMode).
   */
  statisticsOpen: boolean;

  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleChatPanel: () => void;
  setChatPanelOpen: (open: boolean) => void;
  toggleCanvasPanel: () => void;
  setCanvasPanelOpen: (open: boolean) => void;
  setTheme: (theme: Theme) => void;
  setLanguage: (lang: Language) => void;
  setAccountDropdownOpen: (open: boolean) => void;
  setStatisticsOpen: (open: boolean) => void;
}

const savedTheme = getItem<Theme>("theme", "system");
const savedLanguage = getItem<Language>("language", "en");
const initialResolved = resolveTheme(savedTheme);

applyThemeClass(initialResolved);

const savedChatPanelOpen = getItem<boolean>("chatPanelOpen", true);
const savedCanvasPanelOpen = getItem<boolean>("canvasPanelOpen", true);

export const useUiStore = create<UiState>((set) => ({
  sidebarOpen: true,
  chatPanelOpen: savedChatPanelOpen,
  canvasPanelOpen: savedCanvasPanelOpen,
  theme: savedTheme,
  resolvedTheme: initialResolved,
  language: savedLanguage,
  accountDropdownOpen: false,
  statisticsOpen: false,

  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  setSidebarOpen: (open) => set({ sidebarOpen: open }),

  toggleChatPanel: () =>
    set((s) => {
      const next = !s.chatPanelOpen;
      setItem("chatPanelOpen", next);
      // Prevent collapsing both content panels at once.
      const canvasPanelOpen = next ? s.canvasPanelOpen : true;
      if (canvasPanelOpen !== s.canvasPanelOpen) setItem("canvasPanelOpen", canvasPanelOpen);
      return { chatPanelOpen: next, canvasPanelOpen };
    }),

  setChatPanelOpen: (open) => {
    setItem("chatPanelOpen", open);
    set({ chatPanelOpen: open });
  },

  toggleCanvasPanel: () =>
    set((s) => {
      const next = !s.canvasPanelOpen;
      setItem("canvasPanelOpen", next);
      const chatPanelOpen = next ? s.chatPanelOpen : true;
      if (chatPanelOpen !== s.chatPanelOpen) setItem("chatPanelOpen", chatPanelOpen);
      return { canvasPanelOpen: next, chatPanelOpen };
    }),

  setCanvasPanelOpen: (open) => {
    setItem("canvasPanelOpen", open);
    set({ canvasPanelOpen: open });
  },

  setTheme: (theme) => {
    const resolved = resolveTheme(theme);
    applyThemeClass(resolved);
    setItem("theme", theme);
    set({ theme, resolvedTheme: resolved });
  },

  setLanguage: (language) => {
    i18n.changeLanguage(language);
    document.documentElement.lang = language;
    setItem("language", language);
    set({ language });
  },

  setAccountDropdownOpen: (accountDropdownOpen) =>
    set({ accountDropdownOpen }),

  setStatisticsOpen: (statisticsOpen) => set({ statisticsOpen }),
}));

window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => {
    const { theme } = useUiStore.getState();
    if (theme === "system") {
      const resolved = resolveTheme("system");
      applyThemeClass(resolved);
      useUiStore.setState({ resolvedTheme: resolved });
    }
  });
