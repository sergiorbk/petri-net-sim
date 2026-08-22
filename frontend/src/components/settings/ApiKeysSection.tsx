import { type FormEvent, useEffect, useState } from "react";
import { Copy, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/common/Button";
import { Input } from "@/components/common/Input";
import { apiClient } from "@/lib/api-client";
import { useLlmCredentialsStore } from "@/stores/llm-credentials-store";
import { cn } from "@/lib/utils";
import type { ApiKey, ApiKeyCreateResponse } from "@/types/auth";

export function ApiKeysSection() {
  const { t } = useTranslation();
  const { credentials, loadCredentials } = useLlmCredentialsStore();

  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [selectedCredentialId, setSelectedCredentialId] = useState<string>("");
  const [createdKey, setCreatedKey] = useState<ApiKeyCreateResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const loadKeys = async () => {
    setError(null);
    const result = await apiClient<ApiKey[]>("/api/v1/auth/api-keys");
    if (result.ok) {
      setKeys(result.data);
    } else {
      setError(result.error);
    }
    setLoading(false);
  };

  useEffect(() => {
    loadKeys();
    loadCredentials();
  }, [loadCredentials]);

  const handleCreate = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setCreating(true);
    setError(null);
    const result = await apiClient<ApiKeyCreateResponse>(
      "/api/v1/auth/api-keys",
      {
        method: "POST",
        body: JSON.stringify({
          name: newName || null,
          llm_credential_id: selectedCredentialId || null,
        }),
      },
    );
    setCreating(false);
    if (result.ok) {
      setCreatedKey(result.data);
      setNewName("");
      setSelectedCredentialId("");
      setShowCreateForm(false);
      setCopied(false);
      await loadKeys();
    } else {
      setError(result.error);
    }
  };

  const handleRevoke = async (id: string) => {
    if (!window.confirm(t("settings.apiKeys.confirmRevoke"))) return;
    setError(null);
    const result = await apiClient(`/api/v1/auth/api-keys/${id}`, {
      method: "DELETE",
    });
    if (result.ok) {
      await loadKeys();
    } else {
      setError(result.error);
    }
  };

  const handleCopy = async () => {
    if (!createdKey) return;
    try {
      await navigator.clipboard.writeText(createdKey.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });

  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-text-primary">
        {t("settings.apiKeys.title")}
      </label>

      {createdKey && (
        <div className="mb-3 rounded-lg border border-accent bg-surface-secondary p-3">
          <p className="mb-2 text-xs text-text-muted">
            {t("settings.apiKeys.createdRawWarning")}
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 truncate rounded bg-surface px-2 py-1.5 font-mono text-xs text-text-primary">
              {createdKey.key}
            </code>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={handleCopy}
            >
              <Copy size={14} className="mr-1" />
              {copied
                ? t("settings.apiKeys.copied")
                : t("settings.apiKeys.copy")}
            </Button>
          </div>
        </div>
      )}

      <div className="rounded-lg bg-surface-secondary p-1">
        {loading ? (
          <p className="px-3 py-4 text-center text-sm text-text-muted">
            {t("settings.apiKeys.loading")}
          </p>
        ) : keys.length === 0 ? (
          <p className="px-3 py-4 text-center text-sm text-text-muted">
            {t("settings.apiKeys.empty")}
          </p>
        ) : (
          <ul className="flex flex-col">
            {keys.map((key) => (
              <li
                key={key.id}
                className="flex items-center gap-3 rounded-md px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm text-text-primary">
                      {key.name || t("settings.apiKeys.unnamed")}
                    </span>
                    <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-xs text-text-muted">
                      {key.prefix}…
                    </code>
                    {key.llm_credential_name && (
                      <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs text-accent">
                        {key.llm_credential_name}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-text-muted">
                    {t("settings.apiKeys.created")} {formatDate(key.created_at)}
                    {" · "}
                    {t("settings.apiKeys.lastUsed")}{" "}
                    {key.last_used_at
                      ? formatDate(key.last_used_at)
                      : t("settings.apiKeys.never")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => handleRevoke(key.id)}
                  aria-label={t("settings.apiKeys.revoke")}
                  className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-hover hover:text-red-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  <Trash2 size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && (
        <p className="mt-2 text-sm text-red-500" role="alert">
          {error}
        </p>
      )}

      <div className="mt-3">
        {showCreateForm ? (
          <form onSubmit={handleCreate} className="flex flex-col gap-2">
            <Input
              type="text"
              placeholder={t("settings.apiKeys.namePlaceholder")}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              disabled={creating}
              autoFocus
            />
            <select
              value={selectedCredentialId}
              onChange={(e) => setSelectedCredentialId(e.target.value)}
              disabled={creating}
              aria-label={t("settings.apiKeys.modelLabel")}
              className={cn(
                "w-full rounded-lg border border-border bg-surface-secondary",
                "px-3 py-2 text-sm text-text-primary",
                "transition-colors duration-150",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                "disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              <option value="">{t("settings.apiKeys.modelDefault")}</option>
              {credentials.length === 0 ? (
                <option disabled value="__no_profiles__">
                  {t("settings.apiKeys.modelNoProfiles")}
                </option>
              ) : (
                credentials.map((cred) => (
                  <option key={cred.id} value={cred.id}>
                    {cred.name} — {cred.model}
                  </option>
                ))
              )}
            </select>
            <div className="flex gap-2">
              <Button type="submit" disabled={creating} size="sm">
                {creating ? "..." : t("settings.apiKeys.create")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowCreateForm(false);
                  setNewName("");
                  setSelectedCredentialId("");
                }}
                disabled={creating}
              >
                {t("settings.apiKeys.cancel")}
              </Button>
            </div>
          </form>
        ) : (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => {
              setShowCreateForm(true);
              setCreatedKey(null);
            }}
          >
            <Plus size={14} className="mr-1" />
            {t("settings.apiKeys.create")}
          </Button>
        )}
      </div>
    </div>
  );
}
