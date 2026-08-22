import { getItem, setItem } from "@/lib/storage";
import type { TokenPair } from "@/types/auth";

const TOKEN_KEY = "tokens";

export function getStoredTokens(): TokenPair | null {
  return getItem<TokenPair | null>(TOKEN_KEY, null);
}

export function storeTokens(tokens: TokenPair): void {
  setItem(TOKEN_KEY, tokens);
}

export function clearStoredTokens(): void {
  try {
    localStorage.removeItem("petri-net-sim-" + TOKEN_KEY);
  } catch {
    // ignore
  }
}

let refreshPromise: Promise<TokenPair | null> | null = null;

async function refreshTokens(refreshToken: string): Promise<TokenPair | null> {
  try {
    const response = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) return null;

    const json = await response.json();
    const tokens: TokenPair = json.data;
    storeTokens(tokens);
    return tokens;
  } catch {
    return null;
  }
}

/**
 * fetch wrapper that transparently refreshes the access token on 401 and retries.
 * Returns the final Response (either successful or failed after refresh attempt).
 * On refresh failure clears stored tokens and returns the 401 response.
 */
export async function fetchWithAuth(
  url: string,
  options: RequestInit = {},
): Promise<Response> {
  const tokens = getStoredTokens();
  const headers = new Headers(options.headers);

  if (tokens?.access_token) {
    headers.set("Authorization", `Bearer ${tokens.access_token}`);
  }

  let response = await fetch(url, { ...options, headers });

  if (response.status === 401 && tokens?.refresh_token) {
    if (!refreshPromise) {
      refreshPromise = refreshTokens(tokens.refresh_token);
    }
    const newTokens = await refreshPromise;
    refreshPromise = null;

    if (newTokens) {
      headers.set("Authorization", `Bearer ${newTokens.access_token}`);
      response = await fetch(url, { ...options, headers });
    } else {
      clearStoredTokens();
    }
  }

  return response;
}

export async function apiClient<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<{ data: T; ok: true } | { error: string; status: number; ok: false }> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && options.body && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetchWithAuth(path, { ...options, headers });

  if (response.status === 401) {
    return { error: "Session expired", status: 401, ok: false };
  }

  if (!response.ok) {
    let error = "Request failed";
    try {
      const body = await response.json();
      error = body.error?.message ?? body.detail ?? error;
    } catch {
      // ignore parse errors
    }
    return { error, status: response.status, ok: false };
  }

  const json = await response.json();
  return { data: json.data as T, ok: true };
}

export async function publicApiClient<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<{ data: T; ok: true } | { error: string; status: number; ok: false }> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && options.body && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...options, headers });

  if (!response.ok) {
    let error = "Request failed";
    try {
      const body = await response.json();
      error = body.error?.message ?? body.detail ?? error;
    } catch {
      // ignore parse errors
    }
    return { error, status: response.status, ok: false };
  }

  const json = await response.json();
  return { data: json.data as T, ok: true };
}
