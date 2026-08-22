import type { AuthMode } from "@/types/auth";

/** Response of GET /api/v1/config -- non-secret facts about this deployment. */
export interface ServerConfig {
  auth_mode: AuthMode;
  /**
   * External sign-in providers this deployment has credentials for, by the
   * name in their route path. Empty when none are configured.
   */
  oauth_providers: string[];
  /** Whether this server mounts the MCP endpoint at all (MCP_ENABLED). */
  mcp_enabled: boolean;
  /** Path the MCP endpoint answers on, e.g. "/mcp" (MCP_PATH). */
  mcp_path: string;
  /** Whether the OpenAI-compatible HTTP API is served (OPENAI_ENABLED). */
  http_api_enabled: boolean;
  /** Base path of that API, e.g. "/api/v1". */
  http_api_path: string;
  /** Null where API docs are switched off, as they are in production. */
  openapi_url: string | null;
  docs_url: string | null;
}
