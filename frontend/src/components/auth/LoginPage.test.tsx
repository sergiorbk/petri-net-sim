import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LoginPage } from "./LoginPage";
import { useAuthStore } from "@/stores/auth-store";
import { useServerConfigStore } from "@/stores/server-config-store";
import type { ServerConfig } from "@/types/server-config";

const BASE_CONFIG: ServerConfig = {
  auth_mode: "multi",
  oauth_providers: [],
  mcp_enabled: true,
  mcp_path: "/mcp",
  http_api_enabled: true,
  http_api_path: "/api/v1",
  openapi_url: "/openapi.json",
  docs_url: "/docs",
};

function setServerConfig(providers: string[]) {
  useServerConfigStore.setState({
    config: { ...BASE_CONFIG, oauth_providers: providers },
    isLoading: false,
    error: null,
  });
}

function renderLoginRoute() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/nets" element={<div>gallery</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  // The page loads the server config on mount; jsdom's fetch rejects the
  // relative path, so answer it here rather than leave a rejection behind.
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: BASE_CONFIG }),
    }),
  );
  setServerConfig([]);
});

describe("LoginPage route redirect", () => {
  it("redirects to the gallery when the session is already authenticated (single-user mode never shows a login form)", () => {
    useAuthStore.setState({ isAuthenticated: true, authMode: "single_user" });

    renderLoginRoute();

    expect(screen.getByText("gallery")).toBeInTheDocument();
  });

  it("renders the sign-in form when not authenticated (multi mode, default)", () => {
    useAuthStore.setState({ isAuthenticated: false, authMode: "multi" });

    renderLoginRoute();

    expect(screen.queryByText("gallery")).not.toBeInTheDocument();
    // The email field: "sign in" matches both the tab and the submit button.
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });
});

describe("external sign-in", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: false, authMode: "multi" });
  });

  it("offers Google when the server has credentials for it", () => {
    setServerConfig(["google"]);

    renderLoginRoute();

    expect(screen.getByRole("button", { name: /google/i })).toBeInTheDocument();
  });

  it("hides it, and its separator, when the server has none", () => {
    setServerConfig([]);

    renderLoginRoute();

    // A button that leads straight to "not configured" is worse than no
    // button, so the whole block goes, divider included.
    expect(screen.queryByRole("button", { name: /google/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/^or$/i)).not.toBeInTheDocument();
  });
});
