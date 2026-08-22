import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { storeTokens } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import type { TokenPair } from "@/types/auth";

type CallbackState = "loading" | "error";

export function AuthCallback() {
  const { t } = useTranslation();
  const [state, setState] = useState<CallbackState>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const fetchUser = useAuthStore((s) => s.fetchUser);

  useEffect(() => {
    const hash = window.location.hash.slice(1);
    const params = new URLSearchParams(hash);

    const error = params.get("error");
    if (error) {
      setErrorMessage(error);
      setState("error");
      return;
    }

    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");

    if (!accessToken || !refreshToken) {
      setErrorMessage("Missing tokens");
      setState("error");
      return;
    }

    const tokens: TokenPair = {
      access_token: accessToken,
      refresh_token: refreshToken,
    };

    storeTokens(tokens);

    fetchUser().then((user) => {
      if (user) {
        // Clear the hash and navigate to root
        window.location.replace("/");
      } else {
        setErrorMessage("Failed to fetch user profile");
        setState("error");
      }
    });
  }, [fetchUser]);

  if (state === "error") {
    return (
      <div className="flex h-full items-center justify-center bg-surface px-4">
        <div className="text-center">
          <p className="mb-4 text-sm text-red-500">
            {t("auth.authError")}: {errorMessage}
          </p>
          <a
            href="/"
            className="text-sm text-accent hover:text-accent-hover"
          >
            {t("auth.tryAgain")}
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full items-center justify-center bg-surface">
      <div className="text-center">
        <svg
          className="mx-auto h-8 w-8 animate-spin text-accent"
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
        <p className="mt-4 text-sm text-text-muted">{t("auth.signingIn")}</p>
      </div>
    </div>
  );
}
