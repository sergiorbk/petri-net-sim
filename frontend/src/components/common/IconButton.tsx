import { type ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  "aria-label": string;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ className, children, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      className={cn(
        "inline-flex items-center justify-center rounded-lg p-2",
        "text-text-muted transition-colors duration-150",
        "hover:bg-surface-hover hover:text-text-primary",
        "focus-visible:outline-2 focus-visible:outline-offset-2",
        "focus-visible:outline-accent",
        "disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  ),
);

IconButton.displayName = "IconButton";
