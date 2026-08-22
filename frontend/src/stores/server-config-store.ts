import { create } from "zustand";
import { publicApiClient } from "@/lib/api-client";
import type { ServerConfig } from "@/types/server-config";

/**
 * Whatever the server says about itself, before login.
 *
 * The integration settings print connection URLs, and a URL that is
 * guessed rather than reported is a support ticket: MCP_PATH is
 * configurable, and the docs routes disappear entirely in deployed
 * environments (see backend/main.py). So the paths come from
 * GET /api/v1/config and the origin from the browser -- the frontend is
 * served by the same origin it calls.
 */
const FALLBACK: ServerConfig = {
  auth_mode: "multi",
  // Nothing offered until the server says otherwise: an absent list means an
  // older backend, and a button that leads to "not configured" is worse than
  // no button.
  oauth_providers: [],
  mcp_enabled: false,
  mcp_path: "/mcp",
  http_api_enabled: false,
  http_api_path: "/api/v1",
  openapi_url: null,
  docs_url: null,
};

interface ServerConfigState {
  config: ServerConfig | null;
  isLoading: boolean;
  /** Set when the server could not be reached or answered with an error. */
  error: string | null;
  load: () => Promise<void>;
}

let inflight: Promise<void> | null = null;

export const useServerConfigStore = create<ServerConfigState>((set) => ({
  config: null,
  isLoading: false,
  error: null,

  load: async () => {
    // Both integration sections call this on mount, and the user can switch
    // between them repeatedly; one request answers all of it.
    if (inflight) return inflight;

    set({ isLoading: true, error: null });
    inflight = (async () => {
      const result = await publicApiClient<Partial<ServerConfig>>(
        "/api/v1/config",
      );
      if (result.ok) {
        set({ config: { ...FALLBACK, ...result.data }, isLoading: false });
      } else {
        set({ config: null, isLoading: false, error: result.error });
        // A failed load is worth retrying on the next visit.
        inflight = null;
      }
    })();
    return inflight;
  },
}));
