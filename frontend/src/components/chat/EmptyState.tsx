import { useTranslation } from "react-i18next";
import { ChatInput } from "./ChatInput";

interface EmptyStateProps {
  onSend: (message: string) => void;
}

export function EmptyState({ onSend }: EmptyStateProps) {
  const { t } = useTranslation();

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-4">
      <div className="w-full max-w-2xl">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold text-text-primary">
            {t("emptyState.heading")}
          </h1>
          <p className="mt-2 text-sm text-text-muted">
            {t("emptyState.subheading")}
          </p>
        </div>

        <ChatInput onSend={onSend} />
      </div>
    </div>
  );
}
