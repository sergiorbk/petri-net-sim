import { useEffect } from "react";
import { ExternalLink } from "lucide-react";
import { Trans, useTranslation } from "react-i18next";
import { useAuthStore } from "@/stores/auth-store";
import { useServerConfigStore } from "@/stores/server-config-store";
import { cn } from "@/lib/utils";
import { CopyField } from "./CopyField";
import { IntegrationSwitch } from "./IntegrationSwitch";
import { ApiKeysLink, IntegrationHeader, IntegrationSteps } from "./IntegrationLayout";

const KEY_PLACEHOLDER = "sk-your-api-key";

/** The single model this API serves (backend: openai_chat_service.MODEL_ID). */
const MODEL_ID = "petri-net-sim";

export function HttpApiSection() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const { config, isLoading, error, load } = useServerConfigStore();

  useEffect(() => {
    load();
  }, [load]);

  const enabled = user?.http_api_enabled !== false;

  const origin = window.location.origin;
  const baseUrl = config ? `${origin}${config.http_api_path}` : "";

  const curlExample = [
    `curl ${baseUrl}/chat/completions \\`,
    `  -H "Authorization: Bearer ${KEY_PLACEHOLDER}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"model": "${MODEL_ID}", "messages": [{"role": "user", "content": "Model a queue with two servers"}]}'`,
  ].join("\n");

  return (
    <div className="flex flex-col gap-6">
      <IntegrationHeader
        title={t("settings.integrations.api.title")}
        description={t("settings.integrations.api.description")}
      />

      <IntegrationSwitch
        field="http_api_enabled"
        checked={enabled}
        label={t("settings.integrations.api.switchLabel")}
        description={t("settings.integrations.api.switchDescription")}
        unavailableNote={
          config && !config.http_api_enabled
            ? t("settings.integrations.api.serverDisabled")
            : undefined
        }
      />

      {isLoading && !config && (
        <p className="text-sm text-text-muted">
          {t("settings.integrations.loading")}
        </p>
      )}

      {error && (
        <p className="text-sm text-red-500" role="alert">
          {t("settings.integrations.configError")}
        </p>
      )}

      {config && (
        <>
          <div className="flex flex-col gap-3">
            <CopyField
              label={t("settings.integrations.api.baseUrlLabel")}
              value={baseUrl}
            />
            <CopyField
              label={t("settings.integrations.api.modelLabel")}
              value={MODEL_ID}
            />
            <CopyField
              label={t("settings.integrations.api.exampleLabel")}
              value={curlExample}
              multiline
            />
          </div>

          <IntegrationSteps
            title={t("settings.integrations.howTo")}
            steps={[
              <Trans
                i18nKey="settings.integrations.api.step1"
                components={{ keys: <ApiKeysLink /> }}
              />,
              t("settings.integrations.api.step2"),
              t("settings.integrations.api.step3"),
            ]}
          />

          <div>
            <h3 className="mb-2 text-sm font-medium text-text-primary">
              {t("settings.integrations.api.schemaTitle")}
            </h3>
            {config.openapi_url || config.docs_url ? (
              <div className="flex flex-wrap gap-4 text-sm">
                {config.docs_url && (
                  <DocsLink
                    href={`${origin}${config.docs_url}`}
                    label={t("settings.integrations.api.docsLink")}
                  />
                )}
                {config.openapi_url && (
                  <DocsLink
                    href={`${origin}${config.openapi_url}`}
                    label={t("settings.integrations.api.schemaLink")}
                  />
                )}
              </div>
            ) : (
              <p className="text-sm text-text-muted">
                {t("settings.integrations.api.docsDisabled")}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function DocsLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={cn(
        "inline-flex items-center gap-1 font-medium text-accent",
        "underline underline-offset-2 transition-opacity hover:opacity-80",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
      )}
    >
      {label}
      <ExternalLink size={13} className="shrink-0" />
    </a>
  );
}
