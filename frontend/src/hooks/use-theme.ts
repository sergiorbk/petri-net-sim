import { useEffect } from "react";
import { useUiStore } from "@/stores/ui-store";

/**
 * Keeps the document's `dark` class in sync with the Zustand theme state.
 * Call once from the root layout component.
 */
export function useTheme(): void {
  const resolvedTheme = useUiStore((s) => s.resolvedTheme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolvedTheme === "dark");
  }, [resolvedTheme]);
}
