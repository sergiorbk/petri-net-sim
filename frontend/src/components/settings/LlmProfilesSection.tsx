import { type FormEvent, useEffect, useState } from "react";
import { CheckCircle, Loader2, Plus, Trash2, XCircle, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { useLlmCredentialsStore } from "@/stores/llm-credentials-store";
import { cn } from "@/lib/utils";
import type { CreateLlmCredentialPayload, LlmProvider } from "@/types/llm-credentials";

const PROVIDER_LABELS: Record<LlmProvider, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  ollama: "Ollama",
};

const MODEL_PLACEHOLDERS: Record<LlmProvider, string> = {
  openai: "gpt-4o",
  anthropic: "claude-sonnet-4-6",
  ollama: "llama3",
};

const PROVIDER_COLORS: Record<LlmProvider, string> = {
  openai:
    "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
  anthropic:
    "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  ollama:
    "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
};

const EMPTY_FORM: {
  name: string;
  provider: LlmProvider;
  api_key: string;
  base_url: string;
  model: string;
} = { name: "", provider: "openai", api_key: "", base_url: "", model: "" };

export function LlmProfilesSection() {
  const { t } = useTranslation();
  const {
    credentials,
    isLoading,
    testingId,
    testResults,
    error,
    loadCredentials,
    addCredential,
    removeCredential,
    testCredential,
    clearError,
  } = useLlmCredentialsStore();

  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);

  useEffect(() => {
    loadCredentials();
  }, [loadCredentials]);

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    setCreating(true);
    clearError();
    const payload: CreateLlmCredentialPayload = {
      name: form.name,
      provider: form.provider,
      api_key: form.api_key || null,
      base_url: form.base_url || null,
      model: form.model,
    };
    const ok = await addCredential(payload);
    setCreating(false);
    if (ok) {
      setShowForm(false);
      setForm(EMPTY_FORM);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm(t("settings.llmProfiles.confirmDelete"))) return;
    clearError();
    await removeCredential(id);
  };

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });

  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-text-primary">
        {t("settings.llmProfiles.title")}
      </label>
      <p className="mb-3 text-xs text-text-muted">
        {t("settings.llmProfiles.description")}
      </p>

      <div className="rounded-lg bg-surface-secondary p-1">
        {isLoading ? (
          <p className="px-3 py-4 text-center text-sm text-text-muted">
            {t("settings.llmProfiles.loading")}
          </p>
        ) : credentials.length === 0 ? (
          <p className="px-3 py-4 text-center text-sm text-text-muted">
            {t("settings.llmProfiles.empty")}
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {credentials.map((cred) => {
              const testResult = testResults[cred.id];
              const isTesting = testingId === cred.id;
              return (
                <li key={cred.id} className="rounded-md px-3 py-2.5">
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium text-text-primary">
                          {cred.name}
                        </span>
                        <span
                          className={cn(
                            "rounded px-1.5 py-0.5 text-xs font-medium",
                            PROVIDER_COLORS[cred.provider],
                          )}
                        >
                          {PROVIDER_LABELS[cred.provider]}
                        </span>
                        <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-xs text-text-muted">
                          {cred.model}
                        </code>
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-3 text-xs text-text-muted">
                        {cred.api_key_preview && (
                          <span className="font-mono">{cred.api_key_preview}</span>
                        )}
                        <span>
                          {t("settings.llmProfiles.created")}{" "}
                          {formatDate(cred.created_at)}
                        </span>
                        {cred.last_validated_at && (
                          <span className="flex items-center gap-1 text-green-600 dark:text-green-400">
                            <CheckCircle size={11} />
                            {t("settings.llmProfiles.testedOn")}{" "}
                            {formatDate(cred.last_validated_at)}
                          </span>
                        )}
                      </div>
                      {testResult && (
                        <div
                          className={cn(
                            "mt-1.5 flex items-center gap-1.5 rounded px-2 py-1 text-xs",
                            testResult.success
                              ? "bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300"
                              : "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
                          )}
                        >
                          {testResult.success ? (
                            <>
                              <CheckCircle size={12} />
                              {t("settings.llmProfiles.testSuccess")}
                              {testResult.latency_ms != null &&
                                ` (${testResult.latency_ms}ms)`}
                            </>
                          ) : (
                            <>
                              <XCircle size={12} />
                              {testResult.error ?? t("settings.llmProfiles.testFailed")}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => testCredential(cred.id)}
                        disabled={isTesting || testingId !== null}
                        aria-label={t("settings.llmProfiles.test")}
                        className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
                      >
                        {isTesting ? (
                          <Loader2 size={16} className="animate-spin" />
                        ) : (
                          <Zap size={16} />
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(cred.id)}
                        aria-label={t("settings.llmProfiles.delete")}
                        className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-red-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {error && (
        <p className="mt-2 text-sm text-red-500" role="alert">
          {error}
        </p>
      )}

      <div className="mt-3">
        {showForm ? (
          <form
            onSubmit={handleCreate}
            className="rounded-lg border border-border bg-surface-secondary p-4"
          >
            <p className="mb-3 text-sm font-medium text-text-primary">
              {t("settings.llmProfiles.addProfile")}
            </p>
            <div className="flex flex-col gap-3">
              <div>
                <label className="mb-1 block text-xs text-text-muted">
                  {t("settings.llmProfiles.form.name")}
                </label>
                <Input
                  type="text"
                  placeholder={t("settings.llmProfiles.form.namePlaceholder")}
                  value={form.name}
                  onChange={(e) => setForm((d) => ({ ...d, name: e.target.value }))}
                  required
                  disabled={creating}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs text-text-muted">
                  {t("settings.llmProfiles.form.provider")}
                </label>
                <select
                  value={form.provider}
                  onChange={(e) =>
                    setForm((d) => ({
                      ...d,
                      provider: e.target.value as LlmProvider,
                      model: "",
                    }))
                  }
                  disabled={creating}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {(["openai", "anthropic", "ollama"] as LlmProvider[]).map((p) => (
                    <option key={p} value={p}>
                      {PROVIDER_LABELS[p]}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs text-text-muted">
                  {t("settings.llmProfiles.form.model")}
                </label>
                <Input
                  type="text"
                  placeholder={MODEL_PLACEHOLDERS[form.provider]}
                  value={form.model}
                  onChange={(e) => setForm((d) => ({ ...d, model: e.target.value }))}
                  required
                  disabled={creating}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs text-text-muted">
                  {t("settings.llmProfiles.form.apiKey")}
                  {form.provider === "ollama" && (
                    <span className="ml-1 opacity-60">
                      ({t("settings.llmProfiles.form.optional")})
                    </span>
                  )}
                </label>
                <Input
                  type="password"
                  placeholder={t("settings.llmProfiles.form.apiKeyPlaceholder")}
                  value={form.api_key}
                  onChange={(e) => setForm((d) => ({ ...d, api_key: e.target.value }))}
                  required={form.provider !== "ollama"}
                  disabled={creating}
                />
              </div>

              <div>
                <label className="mb-1 block text-xs text-text-muted">
                  {t("settings.llmProfiles.form.baseUrl")}
                  {form.provider !== "ollama" && (
                    <span className="ml-1 opacity-60">
                      ({t("settings.llmProfiles.form.optional")})
                    </span>
                  )}
                </label>
                <Input
                  type="text"
                  placeholder={
                    form.provider === "ollama"
                      ? "http://localhost:11434"
                      : t("settings.llmProfiles.form.baseUrlPlaceholder")
                  }
                  value={form.base_url}
                  onChange={(e) => setForm((d) => ({ ...d, base_url: e.target.value }))}
                  required={form.provider === "ollama"}
                  disabled={creating}
                />
              </div>
            </div>

            <div className="mt-4 flex gap-2">
              <Button type="submit" size="sm" disabled={creating}>
                {creating ? "..." : t("settings.llmProfiles.form.save")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowForm(false);
                  setForm(EMPTY_FORM);
                  clearError();
                }}
                disabled={creating}
              >
                {t("settings.llmProfiles.form.cancel")}
              </Button>
            </div>
          </form>
        ) : (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setShowForm(true)}
          >
            <Plus size={14} className="mr-1" />
            {t("settings.llmProfiles.addProfile")}
          </Button>
        )}
      </div>
    </div>
  );
}
