import "@testing-library/jest-dom/vitest";

// Components render through react-i18next; without an initialized i18n
// instance they fall back to raw translation keys ("agent.failed"), which is
// not what any user ever sees. Importing the app's own i18n module gives
// tests the same English bundle the app boots with (jsdom has no saved
// language, so the storage lookup inside resolves to "en").
import "@/i18n";

// jsdom implements no media queries, and the theme store asks for
// prefers-color-scheme the moment it is imported -- which any component
// pulling in the simulation canvas does transitively.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}
