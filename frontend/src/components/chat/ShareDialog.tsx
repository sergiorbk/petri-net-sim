import { useEffect, useRef, useState } from "react";
import { Check, Copy, Link, Lock, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/stores/chat-store";
import type { ChatSession, SessionVisibility } from "@/types/chat";
import { Button } from "@/components/common/Button";

interface ShareDialogProps {
  session: ChatSession;
  onClose: () => void;
}

const VISIBILITY_OPTIONS: Array<{
  value: SessionVisibility;
  label: string;
  description: string;
  icon: React.ReactNode;
}> = [
  {
    value: "private",
    label: "Тільки я",
    description: "Доступ лише для власника",
    icon: <Lock size={16} />,
  },
  {
    value: "link_only",
    label: "За посиланням",
    description: "Будь-хто з посиланням може переглянути",
    icon: <Link size={16} />,
  },
];

export function ShareDialog({ session, onClose }: ShareDialogProps) {
  const updateVisibility = useChatStore((s) => s.updateVisibility);
  const [visibility, setVisibility] = useState<SessionVisibility>(
    session.visibility ?? "private",
  );
  const [shareToken, setShareToken] = useState<string | null>(
    session.shareToken ?? null,
  );
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const backdropRef = useRef<HTMLDivElement>(null);
  const linkInputRef = useRef<HTMLInputElement>(null);

  const hasBackend = !!(session.backendSessionId ?? session.id?.length === 64);
  const shareUrl = shareToken
    ? `${window.location.origin}/share/${shareToken}`
    : null;

  async function applyVisibility(next: SessionVisibility) {
    setVisibility(next);
    setSaving(true);
    const token = await updateVisibility(session.id, next);
    if (token) setShareToken(token);
    setSaving(false);
  }

  async function copyLink() {
    if (!shareUrl) return;
    await navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={(e) => {
        if (e.target === backdropRef.current) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-surface shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 className="text-sm font-semibold text-text-primary">
            Поділитися чатом
          </h2>
          <button
            type="button"
            className="rounded p-1 text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            onClick={onClose}
            aria-label="Закрити"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {!hasBackend && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-400">
              Надішліть перше повідомлення, щоб активувати шаринг.
            </p>
          )}

          {/* Visibility options */}
          <div className="space-y-2">
            {VISIBILITY_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={!hasBackend || saving}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors",
                  "disabled:pointer-events-none disabled:opacity-50",
                  visibility === opt.value
                    ? "border-accent bg-accent/10 text-text-primary"
                    : "border-border hover:bg-surface-hover text-text-secondary",
                )}
                onClick={() => applyVisibility(opt.value)}
              >
                <span
                  className={cn(
                    "shrink-0",
                    visibility === opt.value
                      ? "text-accent"
                      : "text-text-tertiary",
                  )}
                >
                  {opt.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium leading-none text-text-primary">
                    {opt.label}
                  </p>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    {opt.description}
                  </p>
                </div>
                <span
                  className={cn(
                    "h-4 w-4 shrink-0 rounded-full border-2 transition-colors",
                    visibility === opt.value
                      ? "border-accent bg-accent"
                      : "border-border",
                  )}
                />
              </button>
            ))}
          </div>

          {/* Share link */}
          {shareUrl && visibility !== "private" && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-text-secondary">
                Посилання
              </p>
              <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-secondary px-3 py-2">
                <input
                  ref={linkInputRef}
                  readOnly
                  value={shareUrl ?? ""}
                  onClick={() => linkInputRef.current?.select()}
                  className="min-w-0 flex-1 bg-transparent font-mono text-xs text-text-primary outline-none"
                />
                <button
                  type="button"
                  className="shrink-0 rounded p-1 text-text-secondary hover:text-text-primary"
                  onClick={copyLink}
                  aria-label="Скопіювати посилання"
                >
                  {copied ? (
                    <Check size={14} className="text-green-500" />
                  ) : (
                    <Copy size={14} />
                  )}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end border-t border-border px-5 py-3">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Закрити
          </Button>
        </div>
      </div>
    </div>
  );
}
