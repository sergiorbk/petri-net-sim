import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Key, Loader2, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { useLlmCredentialsStore } from "@/stores/llm-credentials-store";
import { composerChipClasses } from "./ComposerControl";

export function ModelSelector() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const credentials = useLlmCredentialsStore((s) => s.credentials);
  const isLoading = useLlmCredentialsStore((s) => s.isLoading);
  const selectedCredentialId = useLlmCredentialsStore((s) => s.selectedCredentialId);
  const setSelectedCredentialId = useLlmCredentialsStore((s) => s.setSelectedCredentialId);

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [open]);

  const selected = credentials.find((c) => c.id === selectedCredentialId);
  const displayName = selected ? selected.name : t("chat.modelSelector.select");

  const openAddModel = () => {
    setOpen(false);
    navigate("/settings/llm");
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          composerChipClasses,
          open && "bg-surface-secondary text-text-primary",
        )}
      >
        {isLoading ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <Key size={12} />
        )}
        <span className="max-w-[180px] truncate">{displayName}</span>
        <ChevronDown
          size={12}
          className={cn("transition-transform", open && "rotate-180")}
        />
      </button>

      {open && (
        <div
          className={cn(
            "absolute bottom-full left-0 z-50 mb-1",
            "min-w-[240px] rounded-lg border border-border",
            "bg-surface shadow-lg",
          )}
        >
          {/* User models (BYOK) */}
          <div className="px-3 pb-2 pt-2.5">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
              {t("chat.modelSelector.myModels")}
            </p>
            {isLoading ? (
              <p className="py-2 text-center text-xs text-text-muted">
                {t("chat.modelSelector.loading")}
              </p>
            ) : (
              <div className="flex flex-col gap-0.5">
                {credentials.map((cred) => (
                  <button
                    key={cred.id}
                    type="button"
                    onClick={() => {
                      setSelectedCredentialId(cred.id);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                      "transition-colors hover:bg-surface-hover",
                      selectedCredentialId === cred.id
                        ? "text-text-primary"
                        : "text-text-secondary",
                    )}
                  >
                    <Key size={14} className="shrink-0" />
                    <div className="min-w-0 flex-1 overflow-hidden text-left">
                      <p className="truncate text-sm">{cred.name}</p>
                      <p className="truncate text-xs text-text-muted">{cred.model}</p>
                    </div>
                    {selectedCredentialId === cred.id && (
                      <Check size={14} className="shrink-0 text-accent" />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Add a model */}
          <div className="border-t border-border px-3 py-2">
            <button
              type="button"
              onClick={openAddModel}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                "text-accent transition-colors hover:bg-surface-hover",
              )}
            >
              <Plus size={14} className="shrink-0" />
              <span className="flex-1 text-left">
                {t("chat.modelSelector.addModel")}
              </span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
