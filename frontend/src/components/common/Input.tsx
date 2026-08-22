import { type InputHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/utils";

type InputProps = InputHTMLAttributes<HTMLInputElement>;

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "w-full rounded-lg border border-border bg-surface-secondary",
        "px-3 py-2 text-sm text-text-primary placeholder:text-text-muted",
        "transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-2",
        "focus-visible:outline-accent",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);

Input.displayName = "Input";
