import { useEffect } from "react";
import { Trans, useTranslation } from "react-i18next";
import { useAuthStore } from "@/stores/auth-store";
import { useServerConfigStore } from "@/stores/server-config-store";
import { CopyField } from "./CopyField";
import { IntegrationSwitch } from "./IntegrationSwitch";
import { ApiKeysLink, IntegrationHeader, IntegrationSteps } from "./IntegrationLayout";

/** The example key placeholder. Deliberately not a real prefix-shaped value:
 *  nobody should be able to paste this snippet and have it half-work. */
const KEY_PLACEHOLDER = "sk-your-api-key";

export function McpSection() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const { config, isLoading, error, load } = useServerConfigStore();

  useEffect(() => {
    load();
  }, [load]);

  // Absent on a server that predates the switch -- read that as "on", the
  // same default the backend applies.
  const enabled = user?.mcp_enabled !== false;

  const endpoint = config
    ? `${window.location.origin}${config.mcp_path}`
    : "";

  const clientConfig = JSON.stringify(
    {
      mcpServers: {
        "petri-net-sim": {
          type: "http",
          url: endpoint,
          headers: { Authorization: `Bearer ${KEY_PLACEHOLDER}` },
        },
      },
    },
    null,
    2,
  );

  return (
    <div className="flex flex-col gap-6">
      <IntegrationHeader
        title={t("settings.integrations.mcp.title")}
        description={t("settings.integrations.mcp.description")}
      />

      <IntegrationSwitch
        field="mcp_enabled"
        checked={enabled}
        label={t("settings.integrations.mcp.switchLabel")}
        description={t("settings.integrations.mcp.switchDescription")}
        unavailableNote={
          config && !config.mcp_enabled
            ? t("settings.integrations.mcp.serverDisabled")
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
              label={t("settings.integrations.mcp.endpointLabel")}
              value={endpoint}
            />
            <CopyField
              label={t("settings.integrations.mcp.configLabel")}
              value={clientConfig}
              multiline
            />
            <p className="text-xs text-text-muted">
              {t("settings.integrations.mcp.transportNote")}
            </p>
          </div>

          <IntegrationSteps
            title={t("settings.integrations.howTo")}
            steps={[
              <Trans
                i18nKey="settings.integrations.mcp.step1"
                components={{ keys: <ApiKeysLink /> }}
              />,
              t("settings.integrations.mcp.step2"),
              t("settings.integrations.mcp.step3"),
            ]}
          />
        </>
      )}
    </div>
  );
}
