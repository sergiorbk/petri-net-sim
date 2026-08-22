import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "./auth-store";

const originalFetch = globalThis.fetch;

function jsonResponse(data: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => ({ success: ok, data }),
  } as unknown as Response;
}

function urlOf(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input.toString();
}

function resetAuthStore() {
  useAuthStore.setState({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    authMode: "multi",
  });
  localStorage.clear();
}

describe("auth-store initialize (single-user mode)", () => {
  beforeEach(resetAuthStore);
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("marks the session authenticated with no stored tokens at all", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/api/v1/config")) {
        return jsonResponse({ auth_mode: "single_user" });
      }
      if (url.includes("/api/v1/auth/me")) {
        return jsonResponse({
          id: "local-user-id",
          email: "local@petri-net-sim.local",
          name: "Local User",
          picture: null,
          is_active: true,
          created_at: new Date().toISOString(),
          display_name: null,
          work_type: null,
          custom_instructions: null,
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }) as unknown as typeof fetch;

    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.authMode).toBe("single_user");
    expect(state.isAuthenticated).toBe(true);
    expect(state.isLoading).toBe(false);
    expect(state.user?.email).toBe("local@petri-net-sim.local");
    // No token pair was ever stored -- the request that populated `user`
    // above went out with no Authorization header.
    expect(localStorage.getItem("petri-net-sim-tokens")).toBeNull();
  });

  it("stays authenticated even if the profile fetch itself fails", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/api/v1/config")) {
        return jsonResponse({ auth_mode: "single_user" });
      }
      if (url.includes("/api/v1/auth/me")) {
        return jsonResponse({}, false, 500);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }) as unknown as typeof fetch;

    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.isLoading).toBe(false);
    expect(state.user).toBeNull();
  });
});

describe("auth-store initialize (multi mode, default, backward compat)", () => {
  beforeEach(resetAuthStore);
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("leaves the session unauthenticated with no stored tokens", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/api/v1/config")) {
        return jsonResponse({ auth_mode: "multi" });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }) as unknown as typeof fetch;

    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.authMode).toBe("multi");
    expect(state.isAuthenticated).toBe(false);
    expect(state.isLoading).toBe(false);
    expect(state.user).toBeNull();
  });

  it("falls back to multi mode if the config fetch fails (fail closed, not open)", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/api/v1/config")) {
        return jsonResponse({}, false, 500);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }) as unknown as typeof fetch;

    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.authMode).toBe("multi");
    expect(state.isAuthenticated).toBe(false);
  });
});

describe("auth-store initialize (thrown fetch, not just non-ok)", () => {
  beforeEach(resetAuthStore);
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("resolves and clears isLoading when the config fetch throws outright", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/api/v1/config")) {
        throw new TypeError("Failed to fetch");
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }) as unknown as typeof fetch;

    await expect(useAuthStore.getState().initialize()).resolves.toBeUndefined();

    const state = useAuthStore.getState();
    expect(state.isLoading).toBe(false);
    expect(state.authMode).toBe("multi");
    expect(state.isAuthenticated).toBe(false);
  });

  it("resolves and clears isLoading when the single-user profile fetch throws outright", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/api/v1/config")) {
        return jsonResponse({ auth_mode: "single_user" });
      }
      if (url.includes("/api/v1/auth/me")) {
        throw new TypeError("Failed to fetch");
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }) as unknown as typeof fetch;

    await expect(useAuthStore.getState().initialize()).resolves.toBeUndefined();

    const state = useAuthStore.getState();
    expect(state.isLoading).toBe(false);
    expect(state.authMode).toBe("single_user");
    expect(state.isAuthenticated).toBe(true);
    expect(state.user).toBeNull();
  });

  it("resolves and clears isLoading when a stored-token profile fetch throws outright", async () => {
    localStorage.setItem(
      "petri-net-sim-tokens",
      JSON.stringify({ access_token: "at", refresh_token: "rt" }),
    );
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = urlOf(input);
      if (url.includes("/api/v1/config")) {
        return jsonResponse({ auth_mode: "multi" });
      }
      if (url.includes("/api/v1/auth/me")) {
        throw new TypeError("Failed to fetch");
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }) as unknown as typeof fetch;

    await expect(useAuthStore.getState().initialize()).resolves.toBeUndefined();

    const state = useAuthStore.getState();
    expect(state.isLoading).toBe(false);
    expect(state.authMode).toBe("multi");
    expect(state.isAuthenticated).toBe(false);
    expect(state.user).toBeNull();
  });
});

describe("auth-store logout", () => {
  beforeEach(resetAuthStore);

  it("is a no-op in single-user mode (there is no account to log out of)", () => {
    useAuthStore.setState({ authMode: "single_user", isAuthenticated: true });
    useAuthStore.getState().logout();
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it("clears the session in multi mode", () => {
    useAuthStore.setState({
      authMode: "multi",
      isAuthenticated: true,
      user: {
        id: "u1",
        email: "u1@example.com",
        name: null,
        picture: null,
        is_active: true,
        created_at: new Date().toISOString(),
        display_name: null,
        work_type: null,
        custom_instructions: null,
        mcp_enabled: true,
        http_api_enabled: true,
      },
    });
    useAuthStore.getState().logout();
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.user).toBeNull();
  });
});
