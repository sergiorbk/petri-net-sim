import { Outlet } from "react-router-dom";
import { useTheme } from "@/hooks/use-theme";
import { ActivityBar } from "./ActivityBar";

export function AppShell() {
  useTheme();

  return (
    <div className="flex h-full w-full bg-surface">
      <ActivityBar />
      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <Outlet />
      </div>
    </div>
  );
}
