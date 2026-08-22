import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./RequireAuth";
import { useAuthStore } from "@/stores/auth-store";

function renderProtectedRoute() {
  return render(
    <MemoryRouter initialEntries={["/protected"]}>
      <Routes>
        <Route
          path="/protected"
          element={
            <RequireAuth>
              <div>secret content</div>
            </RequireAuth>
          }
        />
        <Route path="/login" element={<div>login page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RequireAuth", () => {
  it("passes through when isAuthenticated is true (multi mode with a session, or single-user mode)", () => {
    useAuthStore.setState({ isAuthenticated: true });

    renderProtectedRoute();

    expect(screen.getByText("secret content")).toBeInTheDocument();
    expect(screen.queryByText("login page")).not.toBeInTheDocument();
  });

  it("redirects to /login when isAuthenticated is false", () => {
    useAuthStore.setState({ isAuthenticated: false });

    renderProtectedRoute();

    expect(screen.getByText("login page")).toBeInTheDocument();
    expect(screen.queryByText("secret content")).not.toBeInTheDocument();
  });
});
