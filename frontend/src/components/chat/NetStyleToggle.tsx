import { useTranslation } from "react-i18next";
import { useNetStyleStore, type NetStyle } from "@/stores/net-style-store";
import { ComposerSegmented } from "./ComposerControl";

/**
 * Which net shape the agent builds next: a single flat net, or every
 * logical block wrapped in its own Petri-object (the default -- see
 * net-style-store.ts). Read fresh on every sendMessage call, so flipping
 * it mid-conversation changes how the VERY NEXT message gets built.
 */
export function NetStyleToggle() {
  const { t } = useTranslation();
  const netStyle = useNetStyleStore((s) => s.netStyle);
  const setNetStyle = useNetStyleStore((s) => s.setNetStyle);

  const options = [
    {
      value: "classical" as NetStyle,
      content: t("chat.netStyle.classical"),
      title: t("chat.netStyle.classicalHint"),
    },
    {
      value: "object" as NetStyle,
      content: t("chat.netStyle.object"),
      title: t("chat.netStyle.objectHint"),
    },
  ];

  return (
    <ComposerSegmented
      label={t("chat.netStyle.label")}
      value={netStyle}
      options={options}
      onChange={setNetStyle}
    />
  );
}
