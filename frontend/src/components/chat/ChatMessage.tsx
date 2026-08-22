import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { Avatar } from "@/components/common/Avatar";
import { useAuthStore } from "@/stores/auth-store";
import type {
  AgentToolCall,
  AgentToolResult,
  ChatMessage as ChatMessageType,
} from "@/types/chat";
import { AgentStepCard, AgentStepList } from "./AgentStepList";
import { MarkdownContent } from "./MarkdownContent";
import { PetriAvatar } from "./PetriAvatar";
import { getToolRenderer } from "./tool-renderers";

interface ChatMessageProps {
  message: ChatMessageType;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === "user";
  const hasTimeline = !isUser && !!message.timeline && message.timeline.length > 0;
  const hasSteps = !isUser && !!message.steps && message.steps.length > 0;
  const hasContent = !!message.content;
  const isEmpty = !hasContent && !hasSteps && !hasTimeline;
  const authUser = useAuthStore((s) => s.user);

  return (
    <div
      className={cn(
        "flex gap-3 px-4 py-3",
        isUser ? "justify-end" : "justify-start",
      )}
    >
      {!isUser && <PetriAvatar isThinking={isEmpty} />}

      <div
        className={cn(
          "flex min-w-0 flex-col gap-2",
          isUser ? "max-w-[70%] items-end" : "max-w-[80%] items-start",
        )}
      >
        {isEmpty ? (
          <div className="rounded-2xl bg-surface-secondary px-4 py-2.5">
            <span className="inline-flex gap-1">
              <span className="h-2 w-2 animate-pulse rounded-full bg-text-muted" />
              <span className="h-2 w-2 animate-pulse rounded-full bg-text-muted [animation-delay:150ms]" />
              <span className="h-2 w-2 animate-pulse rounded-full bg-text-muted [animation-delay:300ms]" />
            </span>
          </div>
        ) : isUser ? (
          <div
            className={cn(
              "rounded-2xl px-4 py-2.5 text-sm",
              "break-words [overflow-wrap:anywhere]",
              "bg-accent text-white",
            )}
          >
            <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
          </div>
        ) : hasTimeline ? (
          <TimelineView message={message} />
        ) : (
          <>
            {hasSteps && (
              <div className="w-full">
                <AgentStepList steps={message.steps ?? []} />
              </div>
            )}
            {hasContent && (
              <div
                className={cn(
                  "rounded-2xl px-4 py-2.5 text-sm",
                  "break-words [overflow-wrap:anywhere]",
                  "bg-surface-secondary text-text-primary",
                )}
              >
                <MarkdownContent content={message.content} />
              </div>
            )}
          </>
        )}
      </div>

      {isUser && (
        <Avatar
          name={authUser?.name ?? authUser?.email ?? "User"}
          src={authUser?.picture ?? undefined}
          size="sm"
          className="mt-0.5 shrink-0"
        />
      )}
    </div>
  );
}

interface TimelineViewProps {
  message: ChatMessageType;
}

function TimelineView({ message }: TimelineViewProps) {
  const { timeline, steps } = message;

  const stepMap = useMemo(() => {
    const calls = new Map<string, AgentToolCall>();
    const results = new Map<string, AgentToolResult>();
    for (const s of steps ?? []) {
      if (s.type === "tool_call") calls.set(s.id, s);
      else results.set(s.id, s);
    }
    return { calls, results };
  }, [steps]);

  return (
    <div className="flex w-full flex-col gap-2">
      {timeline!.map((item, i) => {
        if (item.kind === "text") {
          return (
            <div
              key={i}
              className={cn(
                "rounded-2xl px-4 py-2.5 text-sm",
                "break-words [overflow-wrap:anywhere]",
                "bg-surface-secondary text-text-primary",
              )}
            >
              <MarkdownContent content={item.content} />
            </div>
          );
        }
        const call = stepMap.calls.get(item.stepId);
        if (!call) return null;
        const result = stepMap.results.get(item.stepId) ?? null;
        const Renderer = getToolRenderer(call.name);
        return (
          <div key={item.stepId} className="flex flex-col gap-1">
            <AgentStepCard call={call} result={result} hideResult={!!Renderer} />
            {Renderer && result && (
              <Renderer call={call} result={result} message={message} />
            )}
          </div>
        );
      })}
    </div>
  );
}

