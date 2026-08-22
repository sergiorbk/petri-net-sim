import type { ReactNode } from "react";
import { DropdownMenu } from "@/components/common/DropdownMenu";

export interface CanvasContextMenuItem {
  label: string;
  action: () => void;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  separatorBefore?: boolean;
}

interface CanvasContextMenuProps {
  /** Viewport coordinates of the right-click. */
  x: number;
  y: number;
  items: CanvasContextMenuItem[];
  onClose: () => void;
}

/**
 * Right-click menu for the editor canvas. A thin adapter over the shared
 * DropdownMenu: the canvas thinks in click points and plain actions, the
 * dropdown owns positioning, portalling, outside-click and keyboard nav.
 */
export function CanvasContextMenu({ x, y, items, onClose }: CanvasContextMenuProps) {
  return (
    <DropdownMenu
      open
      onClose={onClose}
      position={{ x, y }}
      className="min-w-[200px]"
      items={items.map((item, i) => ({
        key: `${i}-${item.label}`,
        label: item.label,
        icon: item.icon,
        danger: item.danger,
        disabled: item.disabled,
        separatorBefore: item.separatorBefore,
        onClick: item.action,
      }))}
    />
  );
}
