import {
  type TextareaHTMLAttributes,
  forwardRef,
  useCallback,
  useEffect,
  useRef,
} from "react";
import { cn } from "@/lib/utils";

const MAX_HEIGHT = 200;

interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  onSubmit?: () => void;
}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(
  ({ className, onSubmit, onChange, ...props }, forwardedRef) => {
    const localRef = useRef<HTMLTextAreaElement | null>(null);

    const setRef = useCallback(
      (el: HTMLTextAreaElement | null) => {
        localRef.current = el;
        if (typeof forwardedRef === "function") {
          forwardedRef(el);
        } else if (forwardedRef) {
          forwardedRef.current = el;
        }
      },
      [forwardedRef],
    );

    const resize = useCallback(() => {
      const el = localRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
    }, []);

    useEffect(() => {
      resize();
    }, [resize]);

    return (
      <textarea
        ref={setRef}
        rows={1}
        className={cn(
          "w-full resize-none bg-transparent text-text-primary",
          "placeholder:text-text-muted",
          "focus:outline-none",
          className,
        )}
        onChange={(e) => {
          onChange?.(e);
          resize();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSubmit?.();
          }
        }}
        {...props}
      />
    );
  },
);

TextArea.displayName = "TextArea";
