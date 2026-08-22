export type LlmProvider = "openai" | "anthropic" | "ollama";

export interface LlmCredential {
  id: string;
  name: string;
  provider: LlmProvider;
  api_key_preview: string | null;
  base_url: string | null;
  model: string;
  created_at: string;
  last_validated_at: string | null;
}

export interface CreateLlmCredentialPayload {
  name: string;
  provider: LlmProvider;
  api_key: string | null;
  base_url: string | null;
  model: string;
}

export interface UpdateLlmCredentialPayload {
  name?: string;
  api_key?: string | null;
  base_url?: string | null;
  model?: string;
}

export interface TestLlmCredentialResponse {
  success: boolean;
  latency_ms: number | null;
  model_response_preview: string | null;
  error: string | null;
}
