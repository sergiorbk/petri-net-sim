import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { useServerConfigStore } from "@/stores/server-config-store";

type Tab = "signIn" | "signUp";

export function LoginPage() {
  const { t } = useTranslation();
  const signup = useAuthStore((s) => s.signup);
  const loginWithPassword = useAuthStore((s) => s.loginWithPassword);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const navigate = useNavigate();
  const location = useLocation();
  const redirectTo =
    (location.state as { from?: string } | null)?.from ?? "/nets";

  const [tab, setTab] = useState<Tab>("signIn");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);

  // Only offer a sign-in this deployment actually has credentials for.
  // Without them the authorize call answers with an error, so the button
  // would be a dead end dressed up as a choice.
  const serverConfig = useServerConfigStore((s) => s.config);
  const loadServerConfig = useServerConfigStore((s) => s.load);
  const googleAvailable = serverConfig?.oauth_providers.includes("google") ?? false;

  useEffect(() => {
    loadServerConfig();
  }, [loadServerConfig]);

  const busy = submitting || googleLoading;

  const handleGoogleLogin = async () => {
    setGoogleLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/oauth/google/authorize");
      const json = await response.json();
      const url = json.data?.url;
      if (url) {
        window.location.href = url;
      } else {
        setError(t("auth.authError"));
        setGoogleLoading(false);
      }
    } catch {
      setError(t("auth.authError"));
      setGoogleLoading(false);
    }
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    const result =
      tab === "signIn"
        ? await loginWithPassword({ email, password })
        : await signup({ email, password, name: name || undefined });

    if (!result.ok) {
      setError(result.error || t(`auth.${tab}.error`));
      setSubmitting(false);
      return;
    }
    navigate(redirectTo, { replace: true });
  };

  // If the user is already signed in (e.g. they hit /login with a valid
  // session), bounce to the protected route they came from or the gallery.
  useEffect(() => {
    if (isAuthenticated) navigate(redirectTo, { replace: true });
  }, [isAuthenticated, navigate, redirectTo]);

  if (isAuthenticated) {
    return <Navigate to={redirectTo} replace />;
  }

  return (
    <div className="flex h-full items-center justify-center bg-surface px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold text-text-primary">
            Petri Net Sim
          </h1>
          <p className="mt-2 text-sm text-text-muted">{t("auth.subtitle")}</p>
        </div>

        <div className="mb-6 flex gap-1 rounded-lg bg-surface-secondary p-1">
          {(["signIn", "signUp"] as const).map((value) => (
            <button
              key={value}
              type="button"
              className={cn(
                "flex-1 rounded-md px-3 py-1.5 text-sm transition-colors",
                "focus-visible:outline-2 focus-visible:outline-offset-2",
                "focus-visible:outline-accent",
                tab === value
                  ? "bg-surface text-text-primary shadow-sm"
                  : "text-text-muted hover:text-text-secondary",
              )}
              onClick={() => {
                setTab(value);
                setError(null);
              }}
              aria-pressed={tab === value}
              disabled={busy}
            >
              {t(`auth.tabs.${value}`)}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm text-text-secondary">
            {t(`auth.${tab}.email`)}
            <Input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={busy}
            />
          </label>

          <label className="flex flex-col gap-1 text-sm text-text-secondary">
            {t(`auth.${tab}.password`)}
            <Input
              type="password"
              autoComplete={
                tab === "signIn" ? "current-password" : "new-password"
              }
              required
              minLength={tab === "signUp" ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy}
            />
          </label>

          {tab === "signUp" && (
            <label className="flex flex-col gap-1 text-sm text-text-secondary">
              {t("auth.signUp.name")}
              <Input
                type="text"
                autoComplete="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={busy}
              />
            </label>
          )}

          {error && (
            <p className="text-sm text-red-500" role="alert">
              {error}
            </p>
          )}

          <Button type="submit" disabled={busy} className="mt-2">
            {submitting
              ? t("auth.signingIn")
              : t(`auth.${tab}.submit`)}
          </Button>
        </form>

        {googleAvailable && (
          <>
            <div className="my-6 flex items-center gap-3 text-xs text-text-muted">
              <div className="h-px flex-1 bg-border" />
              {t("auth.or")}
              <div className="h-px flex-1 bg-border" />
            </div>

            <button
              type="button"
              disabled={busy}
              onClick={handleGoogleLogin}
              className={cn(
                "flex w-full items-center justify-center gap-3",
                "rounded-lg border border-border bg-surface px-4 py-3",
                "text-sm font-medium text-text-primary",
                "transition-colors duration-150 hover:bg-surface-hover",
                "focus-visible:outline-2 focus-visible:outline-offset-2",
                "focus-visible:outline-accent",
                "disabled:opacity-50",
              )}
            >
              {googleLoading ? <LoadingSpinner /> : <GoogleIcon />}
              <span>{t("auth.signInWithGoogle")}</span>
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
        fill="#4285F4"
      />
      <path
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
        fill="#34A853"
      />
      <path
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
        fill="#FBBC05"
      />
      <path
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
        fill="#EA4335"
      />
    </svg>
  );
}

function LoadingSpinner() {
  return (
    <svg
      className="h-5 w-5 animate-spin text-text-muted"
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
  );
}
