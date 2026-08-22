import { cn } from "@/lib/utils";

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** Accessible name. Pass this when no visible <label> wraps the switch. */
  label: string;
  /** Id of the element describing the switch, for screen readers. */
  describedBy?: string;
  disabled?: boolean;
}

/**
 * A two-state switch.
 *
 * role="switch" rather than a styled checkbox: the control applies its
 * change immediately, with no form to submit, which is exactly the
 * distinction the two roles carry for assistive technology.
 */
export function Toggle({
  checked,
  onChange,
  label,
  describedBy,
  disabled,
}: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-describedby={describedBy}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full",
        "transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-accent" : "bg-surface-hover",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-block h-4 w-4 rounded-full bg-white shadow-sm",
          "transition-transform duration-150",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}
