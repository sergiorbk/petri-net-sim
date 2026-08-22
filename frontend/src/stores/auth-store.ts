import { create } from "zustand";
import {
  apiClient,
  clearStoredTokens,
  getStoredTokens,
  publicApiClient,
  storeTokens,
} from "@/lib/api-client";
import { useChatStore } from "@/stores/chat-store";
import type {
  AuthMode,
  AuthUser,
  LoginPayload,
  SignupPayload,
  TokenPair,
} from "@/types/auth";

type AuthActionResult = { ok: true } | { ok: false; error: string };

export interface UpdateProfilePayload {
  name?: string;
  display_name?: string | null;
  work_type?: string | null;
  custom_instructions?: string | null;
  /** Integration switches. Omitted keys are left as they are server-side. */
  mcp_enabled?: boolean;
  http_api_enabled?: boolean;
}

interface AuthState {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  /** "single_user" means the backend runs with no login: every request is
   * already the one local account. Fetched once from GET /api/v1/config
   * during initialize(), before any route decision is made. */
  authMode: AuthMode;

  setTokensAndUser: (tokens: TokenPair, user: AuthUser) => void;
  logout: () => void;
  initialize: () => Promise<void>;
  fetchUser: () => Promise<AuthUser | null>;
  signup: (payload: SignupPayload) => Promise<AuthActionResult>;
  loginWithPassword: (payload: LoginPayload) => Promise<AuthActionResult>;
  updateProfile: (payload: UpdateProfilePayload) => Promise<AuthActionResult>;
}

async function fetchAuthMode(): Promise<AuthMode> {
  // Deliberately unauthenticated -- this has to resolve before we know
  // whether there's a session to check at all.
  const result = await publicApiClient<{ auth_mode: AuthMode }>(
    "/api/v1/config",
  );
  if (!result.ok) return "multi";
  return result.data.auth_mode === "single_user" ? "single_user" : "multi";
}

async function exchangeTokensForUser(tokens: TokenPair): Promise<AuthUser | null> {
  storeTokens(tokens);
  const result = await apiClient<AuthUser>("/api/v1/auth/me");
  if (!result.ok) {
    clearStoredTokens();
    return null;
  }
  return result.data;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  authMode: "multi",

  setTokensAndUser: (tokens, user) => {
    storeTokens(tokens);
    useChatStore.getState().initForUser(user.id);
    set({ user, isAuthenticated: true, isLoading: false });
  },

  logout: () => {
    // No accounts to log out of -- and there is no login screen to land on,
    // since single-user mode's routes never redirect there.
    if (get().authMode === "single_user") return;
    clearStoredTokens();
    useChatStore.getState().clearSessions();
    set({ user: null, isAuthenticated: false, isLoading: false });
  },

  fetchUser: async () => {
    const result = await apiClient<AuthUser>("/api/v1/auth/me");
    if (result.ok) {
      set({ user: result.data, isAuthenticated: true });
      return result.data;
    }
    return null;
  },

  signup: async (payload) => {
    const result = await publicApiClient<TokenPair>("/api/v1/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!result.ok) {
      return { ok: false, error: result.error };
    }
    const user = await exchangeTokensForUser(result.data);
    if (!user) {
      return { ok: false, error: "Failed to load user profile" };
    }
    useChatStore.getState().initForUser(user.id);
    set({ user, isAuthenticated: true, isLoading: false });
    return { ok: true };
  },

  loginWithPassword: async (payload) => {
    const result = await publicApiClient<TokenPair>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (!result.ok) {
      return { ok: false, error: result.error };
    }
    const user = await exchangeTokensForUser(result.data);
    if (!user) {
      return { ok: false, error: "Failed to load user profile" };
    }
    useChatStore.getState().initForUser(user.id);
    set({ user, isAuthenticated: true, isLoading: false });
    return { ok: true };
  },

  updateProfile: async (payload) => {
    const result = await apiClient<AuthUser>("/api/v1/auth/me", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    if (!result.ok) return { ok: false, error: result.error };
    set({ user: result.data });
    return { ok: true };
  },

  initialize: async () => {
    // Every awaited call below can THROW rather than resolve with
    // { ok: false } -- a thrown fetch (offline, connection refused, DNS
    // failure) is not the same thing as a non-ok HTTP response, and is not
    // caught anywhere lower in the chain (fetchAuthMode, fetchUser,
    // apiClient/publicApiClient, fetchWithAuth all let it propagate). Left
    // unguarded, that throw would escape initialize() entirely and leave
    // isLoading stuck at true forever -- no route ever mounts, not even
    // /login. The try/finally here guarantees isLoading always settles,
    // and each inner try/catch falls back to the same "can't tell, assume
    // the safe default" behavior already used for non-ok responses.
    try {
      let authMode: AuthMode = "multi";
      try {
        authMode = await fetchAuthMode();
      } catch {
        // Can't reach /api/v1/config at all: fail closed into the default
        // multi-user mode, same as a non-ok response already does.
        authMode = "multi";
      }
      set({ authMode });

      if (authMode === "single_user") {
        // No tokens involved: fetchWithAuth sends no Authorization header,
        // and the backend treats that as the one local account. The session
        // is authenticated regardless of whether this profile fetch
        // succeeds -- it only fills in a display name / avatar.
        try {
          const user = await get().fetchUser();
          if (user) {
            useChatStore.getState().initForUser(user.id);
          }
        } catch {
          // Profile fetch threw outright: still authenticated, just no
          // display name/avatar yet.
        }
        set({ isAuthenticated: true });
        return;
      }

      const tokens = getStoredTokens();
      if (!tokens?.access_token) {
        return;
      }

      try {
        const user = await get().fetchUser();
        if (!user) {
          clearStoredTokens();
          set({ user: null, isAuthenticated: false });
        } else {
          useChatStore.getState().initForUser(user.id);
        }
      } catch {
        // Couldn't verify the stored token at all: treat it the same as an
        // explicitly invalid one rather than getting stuck loading.
        clearStoredTokens();
        set({ user: null, isAuthenticated: false });
      }
    } finally {
      set({ isLoading: false });
    }
  },
}));
