import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import type {
  AgentStep,
  AgentToolCall,
  AgentToolResult,
} from "@/types/chat";

interface AgentStepListProps {
  steps: AgentStep[];
}

interface PairedStep {
  call: AgentToolCall;
  result: AgentToolResult | null;
}

function pairSteps(steps: AgentStep[]): PairedStep[] {
  const calls = steps.filter(
    (s): s is AgentToolCall => s.type === "tool_call",
  );
  const results = new Map<string, AgentToolResult>();
  for (const s of steps) {
    if (s.type === "tool_result") {
      results.set(s.id, s);
    }
  }
  return calls.map((call) => ({
    call,
    result: results.get(call.id) ?? null,
  }));
}

export function AgentStepList({ steps }: AgentStepListProps) {
  const pairs = useMemo(() => pairSteps(steps), [steps]);
  if (pairs.length === 0) return null;

  return (
    <ul
      className="mb-3 flex flex-col gap-1.5"
      aria-label="Agent reasoning steps"
    >
      {pairs.map((pair) => (
        <AgentStepCard
          key={pair.call.id}
          call={pair.call}
          result={pair.result}
        />
      ))}
    </ul>
  );
}

function prettyResult(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

export interface AgentStepCardProps {
  call: AgentToolCall;
  result: AgentToolResult | null;
  hideResult?: boolean;
}

export function AgentStepCard({ call, result, hideResult = false }: AgentStepCardProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(call.status === "running");
  const statusLabel =
    call.status === "running"
      ? t("agent.running")
      : call.status === "error"
        ? t("agent.failed")
        : t("agent.done");

  const prettyName = call.name.replace(/_/g, " ");
  const hasDetails =
    Object.keys(call.input).length > 0 || (result !== null && !hideResult);

  return (
    <li
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-surface",
        "transition-colors",
      )}
    >
      <button
        type="button"
        onClick={() => hasDetails && setExpanded((v) => !v)}
        disabled={!hasDetails}
        aria-expanded={expanded}
        className={cn(
          "flex w-full items-center gap-2 px-3 py-2 text-left",
          hasDetails && "hover:bg-surface-hover",
          "disabled:cursor-default",
        )}
      >
        <StatusIcon status={call.status} />
        <span className="font-mono text-xs text-text-primary">
          {prettyName}
        </span>
        <span
          className={cn(
            "ml-auto text-[11px] uppercase tracking-wide",
            call.status === "error"
              ? "text-red-500"
              : "text-text-muted",
          )}
        >
          {statusLabel}
        </span>
        {hasDetails && (
          <Chevron expanded={expanded} />
        )}
      </button>

      {expanded && hasDetails && (
        <div className="border-t border-border bg-surface-secondary px-3 py-2 text-xs">
          {Object.keys(call.input).length > 0 && (
            <div className="mb-2">
              <div className="mb-1 text-[11px] uppercase tracking-wide text-text-muted">
                {t("agent.input")}
              </div>
              <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] text-text-primary [overflow-wrap:anywhere]">
                {JSON.stringify(call.input, null, 2)}
              </pre>
            </div>
          )}
          {!hideResult && result && result.output && (
            <div>
              <div className="mb-1 text-[11px] uppercase tracking-wide text-text-muted">
                {t("agent.result")}
              </div>
              <pre
                className={cn(
                  "max-h-48 overflow-y-auto whitespace-pre-wrap break-words font-mono text-[11px] [overflow-wrap:anywhere]",
                  result.status === "error"
                    ? "text-red-500"
                    : "text-text-primary",
                )}
              >
                {prettyResult(result.output)}
              </pre>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function StatusIcon({ status }: { status: AgentToolCall["status"] }) {
  if (status === "running") {
    return (
      <svg
        className="h-3.5 w-3.5 shrink-0 animate-spin text-accent"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="9" opacity="0.25" />
        <path d="M21 12a9 9 0 0 1-9 9" />
      </svg>
    );
  }
  if (status === "error") {
    return (
      <svg
        className="h-3.5 w-3.5 shrink-0 text-red-500"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M18 6 6 18" />
        <path d="m6 6 12 12" />
      </svg>
    );
  }
  return (
    <svg
      className="h-3.5 w-3.5 shrink-0 text-accent"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function Chevron({ expanded }: { expanded: boolean }) {
  return (
    <svg
      className={cn(
        "h-3 w-3 shrink-0 text-text-muted transition-transform",
        expanded && "rotate-180",
      )}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}
