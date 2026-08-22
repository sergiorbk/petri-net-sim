import { create } from "zustand";
import { getItem, setItem } from "@/lib/storage";

/**
 * Which way a generated net flows. The two values are the domain layout
 * engine's own tokens (domain/layout/sugiyama.py takes direction="LR"|"TB")
 * rather than a UI vocabulary that would need translating on the way down.
 *
 * "LR" is presented as Horizontal: the net grows left to right, and steps
 * that run in parallel stack underneath each other in the same column.
 * "TB" is the same layout turned a quarter turn, growing top to bottom.
 *
 * Sent with every sendMessage call (chat-store.ts) as
 * metadata.layout_direction, so switching it mid-conversation changes how
 * the very next message is laid out. The LLM never sees coordinates: the
 * backend applies this to the builder and Sugiyama computes positions.
 */
export type LayoutDirection = "LR" | "TB";

const STORAGE_KEY = "chat-layout-direction";

interface LayoutDirectionState {
  layoutDirection: LayoutDirection;
  setLayoutDirection: (direction: LayoutDirection) => void;
}

export const useLayoutDirectionStore = create<LayoutDirectionState>((set) => ({
  layoutDirection: getItem<LayoutDirection>(STORAGE_KEY, "LR"),
  setLayoutDirection: (layoutDirection) => {
    setItem(STORAGE_KEY, layoutDirection);
    set({ layoutDirection });
  },
}));
