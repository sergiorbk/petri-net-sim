import { ArrowDown, ArrowRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  useLayoutDirectionStore,
  type LayoutDirection,
} from "@/stores/layout-direction-store";
import { ComposerSegmented } from "./ComposerControl";

/**
 * Which way the next generated net flows. Icon-only on purpose: an arrow
 * states the direction without depending on whether the reader calls a
 * left-to-right net "horizontal" (it grows along a horizontal axis) or
 * "vertical" (its parallel branches stack vertically). The words are still
 * there in the tooltip and accessible name.
 */
export function DirectionToggle() {
  const { t } = useTranslation();
  const layoutDirection = useLayoutDirectionStore((s) => s.layoutDirection);
  const setLayoutDirection = useLayoutDirectionStore((s) => s.setLayoutDirection);

  const options = [
    {
      value: "LR" as LayoutDirection,
      content: <ArrowRight size={12} />,
      title: t("chat.direction.horizontalHint"),
    },
    {
      value: "TB" as LayoutDirection,
      content: <ArrowDown size={12} />,
      title: t("chat.direction.verticalHint"),
    },
  ];

  return (
    <ComposerSegmented
      label={t("chat.direction.label")}
      value={layoutDirection}
      options={options}
      onChange={setLayoutDirection}
    />
  );
}
