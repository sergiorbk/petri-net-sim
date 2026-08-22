import { PanelLeft, PanelRight } from "lucide-react";
import { IconButton } from "@/components/common/IconButton";

interface PanelToggleProps {
  onToggle: () => void;
  label: string;
  /** Visual direction of the collapse action: which side the panel slides toward. */
  direction: "left" | "right";
  disabled?: boolean;
}

export function PanelToggle({ onToggle, label, direction, disabled }: PanelToggleProps) {
  const Icon = direction === "left" ? PanelLeft : PanelRight;
  return (
    <IconButton aria-label={label} title={label} onClick={onToggle} disabled={disabled}>
      <Icon size={18} />
    </IconButton>
  );
}
