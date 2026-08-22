import { create } from "zustand";
import {
  createLlmCredential,
  deleteLlmCredential,
  listLlmCredentials,
  testLlmCredential,
} from "@/lib/llm-credentials-client";
import { getItem, setItem } from "@/lib/storage";
import type {
  CreateLlmCredentialPayload,
  LlmCredential,
  TestLlmCredentialResponse,
} from "@/types/llm-credentials";

const SELECTED_CREDENTIAL_KEY = "selected-llm-credential-id";

interface LlmCredentialsState {
  credentials: LlmCredential[];
  isLoading: boolean;
  testingId: string | null;
  testResults: Record<string, TestLlmCredentialResponse>;
  selectedCredentialId: string | null;
  error: string | null;

  loadCredentials: () => Promise<void>;
  addCredential: (payload: CreateLlmCredentialPayload) => Promise<boolean>;
  removeCredential: (id: string) => Promise<boolean>;
  testCredential: (id: string) => Promise<void>;
  setSelectedCredentialId: (id: string | null) => void;
  clearError: () => void;
}

export const useLlmCredentialsStore = create<LlmCredentialsState>((set, get) => ({
  credentials: [],
  isLoading: false,
  testingId: null,
  testResults: {},
  selectedCredentialId: getItem<string | null>(SELECTED_CREDENTIAL_KEY, null),
  error: null,

  loadCredentials: async () => {
    set({ isLoading: true, error: null });
    const result = await listLlmCredentials();
    set({ isLoading: false });
    if (result.ok) {
      const data = result.data;
      set({ credentials: data });
      // BYOK-only: a model must always be selected when any exist. Keep the
      // current selection if still valid, otherwise fall back to the first
      // model (or null when the user has none).
      const { selectedCredentialId } = get();
      const stillValid =
        selectedCredentialId != null && data.some((c) => c.id === selectedCredentialId);
      if (!stillValid) {
        const next = data.length > 0 ? data[0].id : null;
        set({ selectedCredentialId: next });
        setItem(SELECTED_CREDENTIAL_KEY, next);
      }
    } else {
      set({ error: result.error });
    }
  },

  addCredential: async (payload) => {
    const result = await createLlmCredential(payload);
    if (result.ok) {
      set((s) => {
        const credentials = [...s.credentials, result.data];
        // Auto-select the first model the user adds so chat works immediately.
        if (s.selectedCredentialId == null) {
          setItem(SELECTED_CREDENTIAL_KEY, result.data.id);
          return { credentials, selectedCredentialId: result.data.id };
        }
        return { credentials };
      });
      return true;
    }
    set({ error: result.error });
    return false;
  },

  removeCredential: async (id) => {
    const result = await deleteLlmCredential(id);
    if (result.ok) {
      set((s) => {
        const credentials = s.credentials.filter((c) => c.id !== id);
        let selectedCredentialId = s.selectedCredentialId;
        // If the selected model was removed, fall back to the first remaining
        // model (or null when none are left).
        if (selectedCredentialId === id) {
          selectedCredentialId = credentials.length > 0 ? credentials[0].id : null;
          setItem(SELECTED_CREDENTIAL_KEY, selectedCredentialId);
        }
        return {
          credentials,
          selectedCredentialId,
          testResults: Object.fromEntries(
            Object.entries(s.testResults).filter(([k]) => k !== id),
          ),
        };
      });
      return true;
    }
    set({ error: result.error });
    return false;
  },

  testCredential: async (id) => {
    set({ testingId: id });
    const result = await testLlmCredential(id);
    set({ testingId: null });
    if (result.ok) {
      set((s) => ({
        testResults: { ...s.testResults, [id]: result.data },
        credentials: s.credentials.map((c) =>
          c.id === id ? { ...c, last_validated_at: new Date().toISOString() } : c,
        ),
      }));
    } else {
      set((s) => ({
        testResults: {
          ...s.testResults,
          [id]: {
            success: false,
            latency_ms: null,
            model_response_preview: null,
            error: result.error,
          },
        },
      }));
    }
  },

  setSelectedCredentialId: (id) => {
    set({ selectedCredentialId: id });
    setItem(SELECTED_CREDENTIAL_KEY, id);
  },

  clearError: () => set({ error: null }),
}));
