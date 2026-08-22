import { apiClient } from "@/lib/api-client";
import type {
  CreateLlmCredentialPayload,
  LlmCredential,
  TestLlmCredentialResponse,
  UpdateLlmCredentialPayload,
} from "@/types/llm-credentials";

export function listLlmCredentials() {
  return apiClient<LlmCredential[]>("/api/v1/llm-credentials");
}

export function createLlmCredential(payload: CreateLlmCredentialPayload) {
  return apiClient<LlmCredential>("/api/v1/llm-credentials", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateLlmCredential(id: string, payload: UpdateLlmCredentialPayload) {
  return apiClient<LlmCredential>(`/api/v1/llm-credentials/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteLlmCredential(id: string) {
  return apiClient(`/api/v1/llm-credentials/${id}`, { method: "DELETE" });
}

export function testLlmCredential(id: string) {
  return apiClient<TestLlmCredentialResponse>(
    `/api/v1/llm-credentials/${id}/test`,
    { method: "POST" },
  );
}
