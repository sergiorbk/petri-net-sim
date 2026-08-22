import { PanelLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { IconButton } from "@/components/common/IconButton";
import { useUiStore } from "@/stores/ui-store";

export function SidebarToggle() {
  const { t } = useTranslation();
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);

  return (
    <IconButton
      aria-label={t("sidebar.newChat")}
      onClick={toggleSidebar}
    >
      <PanelLeft size={20} />
    </IconButton>
  );
}
