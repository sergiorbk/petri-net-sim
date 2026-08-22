import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { SettingsView } from "@/components/settings/SettingsView";
import { useAuthStore } from "@/stores/auth-store";
import { useServerConfigStore } from "@/stores/server-config-store";
import type { AuthUser } from "@/types/auth";

const USER: AuthUser = {
  id: "u1",
  email: "owner@example.com",
  name: "Owner",
  picture: null,
  is_active: true,
  created_at: new Date().toISOString(),
  display_name: null,
  work_type: null,
  custom_instructions: null,
  mcp_enabled: true,
  http_api_enabled: true,
};

function renderSettings(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings" element={<SettingsView />} />
        <Route path="/settings/:section" element={<SettingsView />} />
      </Routes>
    </MemoryRouter>,
  );
}

const SERVER_CONFIG = {
  auth_mode: "multi" as const,
  oauth_providers: [],
  mcp_enabled: true,
  mcp_path: "/mcp",
  http_api_enabled: true,
  http_api_path: "/api/v1",
  openapi_url: "/openapi.json",
  docs_url: "/docs",
};

beforeEach(() => {
  // The sections load the server config on mount. jsdom's fetch rejects the
  // relative path outright, so answer it here rather than leaving unhandled
  // rejections behind every test.
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: SERVER_CONFIG }),
    }),
  );

  useAuthStore.setState({ user: USER, isAuthenticated: true });
  useServerConfigStore.setState({
    isLoading: false,
    error: null,
    config: {
      auth_mode: "multi",
      oauth_providers: [],
      mcp_enabled: true,
      mcp_path: "/mcp",
      http_api_enabled: true,
      http_api_path: "/api/v1",
      openapi_url: "/openapi.json",
      docs_url: "/docs",
    },
  });
});

describe("settings sections addressed by URL", () => {
  it("opens the MCP section straight from its path", async () => {
    renderSettings("/settings/mcp");

    expect(
      await screen.findByRole("switch", { name: /allow mcp access/i }),
    ).toBeInTheDocument();
  });

  it("opens the OpenAPI section straight from its path", async () => {
    renderSettings("/settings/api");

    expect(
      await screen.findByRole("switch", { name: /allow api access/i }),
    ).toBeInTheDocument();
  });

  it("falls back to Appearance for a path that names no real section", () => {
    renderSettings("/settings/not-a-section");

    expect(screen.getByText("Theme")).toBeInTheDocument();
  });
});

describe("connection details", () => {
  it("builds the MCP endpoint from the path the server reports", async () => {
    useServerConfigStore.setState((s) => ({
      config: { ...s.config!, mcp_path: "/custom-mcp" },
    }));

    renderSettings("/settings/mcp");

    // window.location.origin under jsdom is http://localhost:3000
    expect(
      await screen.findByText(`${window.location.origin}/custom-mcp`),
    ).toBeInTheDocument();
  });

  it("says so instead of linking when the server serves no docs", async () => {
    useServerConfigStore.setState((s) => ({
      config: { ...s.config!, openapi_url: null, docs_url: null },
    }));

    renderSettings("/settings/api");

    expect(
      await screen.findByText(/API docs are switched off/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /OpenAPI schema/i }),
    ).not.toBeInTheDocument();
  });

  it("warns when the deployment does not serve MCP at all", async () => {
    useServerConfigStore.setState((s) => ({
      config: { ...s.config!, mcp_enabled: false },
    }));

    renderSettings("/settings/mcp");

    expect(
      await screen.findByText(/running with MCP switched off/i),
    ).toBeInTheDocument();
  });
});

describe("the switch", () => {
  it("writes through to the profile rather than only moving on screen", async () => {
    const updateProfile = vi.fn().mockResolvedValue({ ok: true });
    useAuthStore.setState({ updateProfile });

    renderSettings("/settings/mcp");
    const toggle = await screen.findByRole("switch", { name: /allow mcp access/i });
    // The click kicks off an awaited profile write; let it settle.
    await act(async () => {
      fireEvent.click(toggle);
    });

    expect(updateProfile).toHaveBeenCalledWith({ mcp_enabled: false });
  });

  it("reverts and reports when the write fails", async () => {
    const updateProfile = vi
      .fn()
      .mockResolvedValue({ ok: false, error: "network is down" });
    useAuthStore.setState({ updateProfile });

    renderSettings("/settings/api");
    const toggle = await screen.findByRole("switch", { name: /allow api access/i });
    // The click kicks off an awaited profile write; let it settle.
    await act(async () => {
      fireEvent.click(toggle);
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("network is down"),
    );
    // The store still holds the old value, so the switch goes back to it.
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  it("reads a missing flag as enabled, the same default the server applies", async () => {
    const { mcp_enabled: _omitted, ...withoutFlag } = USER;
    useAuthStore.setState({ user: withoutFlag as AuthUser });

    renderSettings("/settings/mcp");

    expect(
      await screen.findByRole("switch", { name: /allow mcp access/i }),
    ).toHaveAttribute("aria-checked", "true");
  });
});
