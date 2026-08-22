import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast-store";
import type { NetVersion } from "./version-list";

interface VersionSwitcherProps {
  versions: NetVersion[];
  currentIndex: number;
  onSelect: (versionIndex: number) => void;
  shareUrl: string;
  onFork?: () => void;
  forkDisabled?: boolean;
}

export function VersionSwitcher({
  versions,
  currentIndex,
  onSelect,
  shareUrl,
  onFork,
  forkDisabled,
}: VersionSwitcherProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleOutside(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [open]);

  if (versions.length === 0) return null;

  const total = versions.length;
  const prev = currentIndex > 1 ? currentIndex - 1 : null;
  const next = currentIndex < total ? currentIndex + 1 : null;

  return (
    <div
      ref={rootRef}
      className="absolute left-1/2 top-3 z-20 flex -translate-x-1/2 items-center gap-1 rounded-full border border-zinc-200 bg-white/95 px-2 py-1 text-xs shadow-sm backdrop-blur dark:border-zinc-700 dark:bg-zinc-900/95"
    >
      <button
        type="button"
        onClick={() => prev && onSelect(prev)}
        disabled={prev === null}
        aria-label={t("workbench.version.prev")}
        className="rounded p-1 text-text-secondary hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-30"
      >
        <ChevronIcon className="h-3.5 w-3.5" direction="left" />
      </button>

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 rounded px-2 py-0.5 tabular-nums text-text-primary hover:bg-surface-hover"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span>
          v{currentIndex} / {total}
        </span>
        <ChevronIcon className={cn("h-3 w-3 transition-transform", open && "rotate-180")} direction="down" />
      </button>

      <button
        type="button"
        onClick={() => next && onSelect(next)}
        disabled={next === null}
        aria-label={t("workbench.version.next")}
        className="rounded p-1 text-text-secondary hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-30"
      >
        <ChevronIcon className="h-3.5 w-3.5" direction="right" />
      </button>

      <div className="mx-1 h-4 w-px bg-zinc-200 dark:bg-zinc-700" />

      {onFork && (
        <button
          type="button"
          onClick={onFork}
          disabled={forkDisabled}
          aria-label={t("workbench.fork.save")}
          title={t("workbench.fork.save")}
          className="rounded p-1 text-text-secondary hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          <SaveIcon className="h-3.5 w-3.5" />
        </button>
      )}

      <button
        type="button"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(shareUrl);
            toast(t("workbench.version.copied"), "success");
          } catch {
            toast(t("workbench.version.copyFailed"));
          }
        }}
        aria-label={t("workbench.version.copyLink")}
        title={t("workbench.version.copyLink")}
        className="rounded p-1 text-text-secondary hover:bg-surface-hover"
      >
        <LinkIcon className="h-3.5 w-3.5" />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute left-1/2 top-full mt-1 max-h-72 w-72 -translate-x-1/2 overflow-y-auto rounded-lg border border-zinc-200 bg-white py-1 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
        >
          {versions
            .slice()
            .reverse()
            .map((v) => (
              <button
                key={v.messageId}
                type="button"
                role="option"
                aria-selected={v.versionIndex === currentIndex}
                onClick={() => {
                  onSelect(v.versionIndex);
                  setOpen(false);
                }}
                title={v.label}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-hover",
                  v.versionIndex === currentIndex && "bg-surface-hover",
                )}
              >
                <span className="shrink-0 tabular-nums text-text-muted">v{v.versionIndex}</span>
                <span className="min-w-0 flex-1 truncate text-text-primary">{v.label}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

function SaveIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
      <polyline points="17 21 17 13 7 13 7 21" />
      <polyline points="7 3 7 8 15 8" />
    </svg>
  );
}

function LinkIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M10 14a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.5" strokeLinecap="round" />
      <path d="M14 10a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.5-1.5" strokeLinecap="round" />
    </svg>
  );
}

function ChevronIcon({
  className,
  direction,
}: {
  className?: string;
  direction: "left" | "right" | "down";
}) {
  const d =
    direction === "left"
      ? "M15 18l-6-6 6-6"
      : direction === "right"
        ? "M9 18l6-6-6-6"
        : "M6 9l6 6 6-6";
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
