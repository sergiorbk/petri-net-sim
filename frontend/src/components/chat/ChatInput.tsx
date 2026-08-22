import { useEffect, useRef, useState } from "react";
import { ArrowUp, Mic, Paperclip, Plus, Square } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { IconButton } from "@/components/common/IconButton";
import { TextArea } from "@/components/common/TextArea";
import { useLlmCredentialsStore } from "@/stores/llm-credentials-store";
import { composerChipClasses } from "./ComposerControl";
import { DirectionToggle } from "./DirectionToggle";
import { ModelSelector } from "./ModelSelector";
import { NetStyleToggle } from "./NetStyleToggle";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  onStop?: () => void;
}

export function ChatInput({ onSend, disabled, onStop }: ChatInputProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const credentials = useLlmCredentialsStore((s) => s.credentials);
  const isLoadingModels = useLlmCredentialsStore((s) => s.isLoading);
  const loadCredentials = useLlmCredentialsStore((s) => s.loadCredentials);

  useEffect(() => {
    loadCredentials();
  }, [loadCredentials]);

  const hasModels = credentials.length > 0;

  const trimmed = value.trim();

  const canSend = !!trimmed && !disabled;

  const handleSubmit = () => {
    if (!canSend) return;
    onSend(trimmed);
    setValue("");
  };

  return (
    <div className="flex flex-col gap-0.5">
      <div
        className={cn(
          "flex items-end gap-1 rounded-2xl border border-border",
          "bg-input-bg px-2 py-2",
          "focus-within:border-accent",
          "transition-colors duration-150",
        )}
      >
        <IconButton
          aria-label={t("chat.upload")}
          onClick={() => fileInputRef.current?.click()}
        >
          <Paperclip size={20} />
        </IconButton>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          tabIndex={-1}
          aria-hidden="true"
        />

        <TextArea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onSubmit={handleSubmit}
          placeholder={t("chat.placeholder")}
          // my-2, not my-1: the icon buttons beside it are 36px tall (p-2
          // around a 20px icon) while one line of text-sm is 20px, so a
          // 4px margin bottom-aligned the caret 4px below their centre.
          // 8px makes a single-line composer exactly button-height, which
          // centres it; a grown textarea still bottom-aligns as before.
          className="my-2 text-sm"
          disabled={disabled}
        />

        <IconButton aria-label={t("chat.microphone")}>
          <Mic size={20} />
        </IconButton>

        {disabled && onStop ? (
          <IconButton
            aria-label={t("chat.stop")}
            onClick={onStop}
            className="bg-accent text-white hover:bg-accent-hover hover:text-white"
          >
            <Square size={16} fill="currentColor" />
          </IconButton>
        ) : (
          <IconButton
            aria-label={t("chat.send")}
            onClick={handleSubmit}
            disabled={!canSend}
            className={cn(
              canSend &&
                "bg-accent text-white hover:bg-accent-hover hover:text-white",
            )}
          >
            <ArrowUp size={20} />
          </IconButton>
        )}
      </div>
      {/* Wraps rather than overflows: this row lives in a panel the user
          can drag narrow, and four controls do not always fit on one line. */}
      <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 pt-0.5">
        <NetStyleToggle />
        <DirectionToggle />
        {!isLoadingModels && !hasModels ? (
          <button
            type="button"
            onClick={() => navigate("/settings/llm")}
            className={composerChipClasses}
          >
            <Plus size={12} />
            {t("chat.modelSelector.addModel")}
          </button>
        ) : (
          <ModelSelector />
        )}
      </div>
    </div>
  );
}
