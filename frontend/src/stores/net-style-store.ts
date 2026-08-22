import { create } from "zustand";
import { getItem, setItem } from "@/lib/storage";

/**
 * Which net shape the chat agent should build for this and future turns:
 * "object" wraps every logical block in its own Petri-object (composed
 * model, ISO/IEC 15909 module convention — see chat_node.py's
 * _NET_STYLE_NOTES for the exact per-turn instruction this drives), while
 * "classical" keeps a single flat net. Sent with every sendMessage call
 * (chat-store.ts) as metadata.net_style, so the agent sees it fresh on
 * every message rather than only at conversation start.
 */
export type NetStyle = "classical" | "object";

const STORAGE_KEY = "chat-net-style";

interface NetStyleState {
  netStyle: NetStyle;
  setNetStyle: (style: NetStyle) => void;
}

export const useNetStyleStore = create<NetStyleState>((set) => ({
  netStyle: getItem<NetStyle>(STORAGE_KEY, "object"),
  setNetStyle: (style) => {
    setItem(STORAGE_KEY, style);
    set({ netStyle: style });
  },
}));
