import { useEffect } from "react";
import { RouterProvider } from "react-router-dom";
import { router } from "./router";
import { useAuthStore } from "@/stores/auth-store";
import { ToastContainer } from "@/components/common/ToastContainer";

export default function App() {
  const isLoading = useAuthStore((s) => s.isLoading);
  const initialize = useAuthStore((s) => s.initialize);

  useEffect(() => {
    initialize();
  }, [initialize]);

  if (isLoading) {
    return <LoadingScreen />;
  }

  return (
    <>
      <RouterProvider router={router} />
      <ToastContainer />
    </>
  );
}

function LoadingScreen() {
  return (
    <div className="flex h-full items-center justify-center bg-surface">
      <svg
        className="h-8 w-8 animate-spin text-accent"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="3"
          className="opacity-25"
        />
        <path
          d="M4 12a8 8 0 0 1 8-8"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          className="opacity-75"
        />
      </svg>
    </div>
  );
}
