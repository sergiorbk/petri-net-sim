export type AuthMode = "multi" | "single_user";

export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  picture: string | null;
  is_active: boolean;
  created_at: string;
  display_name: string | null;
  work_type: string | null;
  custom_instructions: string | null;
  /** Whether this account's API keys may reach the MCP server. */
  mcp_enabled: boolean;
  /** Whether this account's API keys may reach the HTTP API. */
  http_api_enabled: boolean;
  contributor?: Record<string, string>;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  expires_in?: number;
}

export interface SignupPayload {
  email: string;
  password: string;
  name?: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface ApiKey {
  id: string;
  name: string | null;
  prefix: string;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
  llm_credential_id: string | null;
  llm_credential_name: string | null;
}

export interface ApiKeyCreateResponse {
  id: string;
  key: string;
  name: string | null;
  llm_credential_id: string | null;
}
