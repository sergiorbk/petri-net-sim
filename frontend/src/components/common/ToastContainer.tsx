import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useToastStore, type Toast } from "@/stores/toast-store";

const DURATION_MS = 5000;

const TYPE_CONFIG: Record<
  Toast["type"],
  { bar: string; icon: React.ReactNode; border: string; bg: string }
> = {
  error: {
    bar: "bg-red-500",
    icon: <AlertCircle size={16} className="text-red-500" />,
    border: "border-red-200 dark:border-red-800",
    bg: "bg-red-50 dark:bg-red-950/30",
  },
  success: {
    bar: "bg-green-500",
    icon: <CheckCircle2 size={16} className="text-green-500" />,
    border: "border-green-200 dark:border-green-800",
    bg: "bg-green-50 dark:bg-green-950/30",
  },
  warning: {
    bar: "bg-amber-500",
    icon: <TriangleAlert size={16} className="text-amber-500" />,
    border: "border-amber-200 dark:border-amber-800",
    bg: "bg-amber-50 dark:bg-amber-950/30",
  },
  info: {
    bar: "bg-blue-500",
    icon: <Info size={16} className="text-blue-500" />,
    border: "border-blue-200 dark:border-blue-800",
    bg: "bg-blue-50 dark:bg-blue-950/30",
  },
};

function ToastItem({
  toast,
  onRemove,
}: {
  toast: Toast;
  onRemove: (id: string) => void;
}) {
  const [progress, setProgress] = useState(100);
  const [leaving, setLeaving] = useState(false);
  const startRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);

  const dismiss = () => {
    if (leaving) return;
    setLeaving(true);
    setTimeout(() => onRemove(toast.id), 280);
  };

  useEffect(() => {
    startRef.current = performance.now();

    function tick(now: number) {
      const elapsed = now - (startRef.current ?? now);
      const remaining = Math.max(0, 100 - (elapsed / DURATION_MS) * 100);
      setProgress(remaining);
      if (remaining > 0) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        dismiss();
      }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cfg = TYPE_CONFIG[toast.type];

  return (
    <div
      className={cn(
        "relative flex w-80 flex-col overflow-hidden",
        "rounded-lg border shadow-lg",
        cfg.border,
        cfg.bg,
        "transition-[transform,opacity] duration-[280ms] ease-in-out",
        leaving ? "translate-x-[110%] opacity-0" : "translate-x-0 opacity-100",
      )}
      role="alert"
    >
      <div className="flex items-start gap-3 px-4 py-3">
        <span className="mt-0.5 shrink-0">{cfg.icon}</span>
        <p className="flex-1 whitespace-pre-line text-sm leading-snug text-text-primary">{toast.message}</p>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss"
          className="shrink-0 rounded p-0.5 text-text-muted transition-colors hover:bg-black/5 hover:text-text-primary dark:hover:bg-white/10"
        >
          <X size={14} />
        </button>
      </div>
      <div className="h-0.5 w-full bg-black/10 dark:bg-white/10">
        <div
          className={cn("h-full transition-none", cfg.bar)}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const removeToast = useToastStore((s) => s.removeToast);

  return (
    <div
      aria-live="polite"
      aria-label="Notifications"
      className="pointer-events-none fixed right-4 top-4 z-[9999] flex flex-col gap-2"
    >
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto">
          <ToastItem toast={t} onRemove={removeToast} />
        </div>
      ))}
    </div>
  );
}
