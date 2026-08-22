import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * The shared visual language of the controls under the chat composer.
 *
 * These are secondary knobs sitting directly beneath a primary input, so
 * they deliberately read as one quiet row rather than four separately
 * styled widgets: identical height, radius and type scale, a neutral
 * palette, and "selected" expressed by a raised surface instead of a
 * colour. No accent colour anywhere -- the only saturated element in the
 * composer should be the send button, which is the actual action.
 *
 * The recessed-track-plus-raised-segment shape is the same one
 * settings/ThemeToggle.tsx uses, one step smaller, so a control means the
 * same thing in both places. Every control here is one-of-N for that
 * reason: a lone chip that is merely "pressed" or "not pressed" states
 * itself only by a change of surface, which on a dark background is not a
 * readable difference, whereas one-of-N always has the unselected option
 * sitting right beside the selected one to be read against.
 */

/** Height shared by every control in the row, segmented or not. */
const CONTROL_H = "h-6";

export interface SegmentedOption<T extends string> {
  value: T;
  /** Text label, icon, or both. */
  content: ReactNode;
  /** Tooltip and accessible name when `content` is icon-only. */
  title?: string;
}

interface ComposerSegmentedProps<T extends string> {
  label: string;
  value: T;
  options: readonly SegmentedOption<T>[];
  onChange: (value: T) => void;
}

/** A pick-one-of-N control: net style, build direction. */
export function ComposerSegmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: ComposerSegmentedProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        CONTROL_H,
        "inline-flex items-center rounded-md bg-surface-secondary p-0.5",
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={option.title}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={cn(
              "inline-flex h-5 items-center gap-1 rounded px-2 text-[11px]",
              "transition-colors duration-150",
              "focus-visible:outline-2 focus-visible:outline-offset-1",
              "focus-visible:outline-accent",
              active
                ? "bg-surface font-medium text-text-primary shadow-sm"
                : "text-text-muted hover:text-text-secondary",
            )}
          >
            {option.content}
          </button>
        );
      })}
    </div>
  );
}

/** Class list for a control that is its own trigger, e.g. ModelSelector. */
export const composerChipClasses = cn(
  CONTROL_H,
  "inline-flex items-center gap-1 rounded-md px-2 text-[11px]",
  "text-text-muted transition-colors duration-150",
  "hover:text-text-secondary",
  "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
);
