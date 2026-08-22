import {
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

interface DropdownItem {
  key: string;
  label: string;
  icon?: ReactNode;
  danger?: boolean;
  /** Rendered greyed out and inert — kept in the list so the menu shape is stable. */
  disabled?: boolean;
  /** Draws a divider above this item. */
  separatorBefore?: boolean;
  onClick: () => void;
}

interface DropdownMenuProps {
  open: boolean;
  onClose: () => void;
  items: DropdownItem[];
  /** When provided, renders into document.body via portal at fixed coordinates. */
  anchorEl?: HTMLElement | null;
  /**
   * Free viewport coordinates to open at (a right-click point), as an
   * alternative to `anchorEl`. Kept inside the viewport once measured.
   */
  position?: { x: number; y: number } | null;
  className?: string;
}

/** Gap kept between the menu and the viewport edge when it would overflow. */
const VIEWPORT_MARGIN = 8;

export function DropdownMenu({
  open,
  onClose,
  items,
  anchorEl,
  position,
  className,
}: DropdownMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const focusedIndex = useRef(0);
  const [clamped, setClamped] = useState<{ x: number; y: number } | null>(null);

  const focusItem = useCallback((index: number) => {
    const menu = menuRef.current;
    if (!menu) return;
    const buttons = menu.querySelectorAll<HTMLButtonElement>(
      '[role="menuitem"]:not([disabled])',
    );
    if (buttons[index]) {
      focusedIndex.current = index;
      buttons[index].focus();
    }
  }, []);

  // Compute portal position from anchor element
  const rect = anchorEl && open ? anchorEl.getBoundingClientRect() : null;
  const point = position && open ? (clamped ?? position) : null;

  // A right-click near the bottom/right edge would otherwise open a menu that
  // runs off screen; measure once mounted and pull it back inside.
  useLayoutEffect(() => {
    if (!open || !position) {
      setClamped(null);
      return;
    }
    const menu = menuRef.current;
    if (!menu) return;
    const { width, height } = menu.getBoundingClientRect();
    const maxX = window.innerWidth - width - VIEWPORT_MARGIN;
    const maxY = window.innerHeight - height - VIEWPORT_MARGIN;
    const next = {
      x: Math.max(VIEWPORT_MARGIN, Math.min(position.x, maxX)),
      y: Math.max(VIEWPORT_MARGIN, Math.min(position.y, maxY)),
    };
    setClamped((prev) =>
      prev && prev.x === next.x && prev.y === next.y ? prev : next,
    );
  }, [open, position]);

  useEffect(() => {
    if (!open) return;

    focusedIndex.current = 0;
    const frame = requestAnimationFrame(() => focusItem(0));

    const handleClickOutside = (e: MouseEvent) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(e.target as Node) &&
        !(anchorEl && anchorEl.contains(e.target as Node))
      ) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [open, onClose, focusItem, anchorEl]);

  const handleKeyDown = (e: KeyboardEvent) => {
    switch (e.key) {
      case "Escape":
        e.preventDefault();
        onClose();
        break;
      case "ArrowDown":
        e.preventDefault();
        focusItem(focusedIndex.current + 1);
        break;
      case "ArrowUp":
        e.preventDefault();
        focusItem(Math.max(focusedIndex.current - 1, 0));
        break;
    }
  };

  if (!open) return null;

  const menu = (
    <div
      ref={menuRef}
      role="menu"
      style={
        rect
          ? { position: "fixed", top: rect.bottom + 4, left: rect.left }
          : point
            ? { position: "fixed", top: point.y, left: point.x }
            : undefined
      }
      className={cn(
        "z-50 min-w-[180px] rounded-lg border border-border",
        "bg-surface py-1 shadow-lg",
        !rect && !point && "absolute",
        className,
      )}
      onKeyDown={handleKeyDown}
    >
      {items.map((item) => (
        <div key={item.key}>
          {item.separatorBefore && <div className="my-1 border-t border-border" />}
          <button
            role="menuitem"
            tabIndex={-1}
            disabled={item.disabled}
            className={cn(
              "flex w-full items-center gap-2 px-3 py-2 text-sm",
              "focus:outline-none",
              item.disabled
                ? "cursor-not-allowed text-text-muted/60"
                : item.danger
                  ? "text-red-500 hover:bg-red-50 hover:text-red-600 focus:bg-red-50 dark:hover:bg-red-950/30 dark:focus:bg-red-950/30"
                  : "text-text-secondary hover:bg-surface-hover hover:text-text-primary focus:bg-surface-hover focus:text-text-primary",
            )}
            onClick={() => {
              if (item.disabled) return;
              item.onClick();
              onClose();
            }}
          >
            {item.icon}
            {item.label}
          </button>
        </div>
      ))}
    </div>
  );

  return rect || point ? createPortal(menu, document.body) : menu;
}
