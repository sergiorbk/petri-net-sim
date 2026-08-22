import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "@/shell/AppShell";
import { SimulatorApp } from "@/apps/simulator/SimulatorApp";
import { NetLoader } from "@/apps/simulator/NetLoader";
import { NetGallery } from "@/apps/gallery/NetGallery";
import { ChatWorkbench } from "@/apps/chat-workbench/ChatWorkbench";
import { SharedNetPage } from "@/apps/shared/SharedNetPage";
import { SharedNetViewPage } from "@/apps/shared/SharedNetViewPage";
import { SettingsView } from "@/components/settings/SettingsView";
import { LoginPage } from "@/components/auth/LoginPage";
import { AuthCallback } from "@/components/auth/AuthCallback";
import { RequireAuth } from "@/shell/RequireAuth";

export const router = createBrowserRouter([
  {
    path: "/auth/callback",
    element: <AuthCallback />,
  },
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/nets" replace /> },
      { path: "nets", element: <NetGallery /> },
      { path: "nets/share/:shareToken", element: <SharedNetViewPage /> },
      { path: "nets/:id", element: <NetLoader /> },
      { path: "editor", element: <SimulatorApp /> },
      { path: "share/:shareToken", element: <SharedNetPage /> },
      {
        path: "chat",
        element: (
          <RequireAuth>
            <ChatWorkbench />
          </RequireAuth>
        ),
      },
      {
        path: "chat/:chatId",
        element: (
          <RequireAuth>
            <ChatWorkbench />
          </RequireAuth>
        ),
      },
      {
        path: "chat/:chatId/v/:versionIndex",
        element: (
          <RequireAuth>
            <ChatWorkbench />
          </RequireAuth>
        ),
      },
      {
        path: "settings",
        element: (
          <RequireAuth>
            <SettingsView />
          </RequireAuth>
        ),
      },
      {
        // The section in the path, so the activity bar can link at one
        // directly and a reload keeps the reader where they were.
        path: "settings/:section",
        element: (
          <RequireAuth>
            <SettingsView />
          </RequireAuth>
        ),
      },
      {
        path: "profile",
        element: <Navigate to="/settings" replace />,
      },
      { path: "*", element: <Navigate to="/nets" replace /> },
    ],
  },
]);
