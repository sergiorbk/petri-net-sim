import { useCallback, useEffect, useMemo, useRef } from "react";
import type { ChatMessage as ChatMessageType } from "@/types/chat";
import { ChatMessage } from "./ChatMessage";
import { SimulationBlock } from "@/components/simulation/SimulationBlock";

interface ChatMessageListProps {
  messages: ChatMessageType[];
}

/**
 * How far from the bottom still counts as "reading the newest message".
 * Generous enough that a stray wheel notch or a bit of layout shift does
 * not read as "the user went looking at something older".
 */
const STICK_THRESHOLD_PX = 64;

export function ChatMessageList({ messages }: ChatMessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Whether to keep the newest content in view as it grows. True until the
  // reader scrolls away from the bottom themselves, and true again the
  // moment they come back -- an answer that streams in for half a minute
  // must not drag someone out of the earlier message they went back to
  // read, and must not require them to chase it either.
  const stick = useRef(true);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stick.current = distance <= STICK_THRESHOLD_PX;
  }, []);

  const lastMessage = messages[messages.length - 1];
  // Everything that makes the last message taller as it streams: its text,
  // the agent steps that render above it, and the simulation block that
  // appears with a net snapshot. Message COUNT alone was the old trigger,
  // which is why the view only caught up between messages and sat still
  // through the whole of the one actually being written.
  const growth = [
    messages.length,
    lastMessage?.id ?? "",
    lastMessage?.content.length ?? 0,
    lastMessage?.steps?.length ?? 0,
    lastMessage?.timeline?.length ?? 0,
    lastMessage?.netSnapshot ? 1 : 0,
  ].join(":");
  const messageCount = messages.length;

  // A new message is the reader's own send or the start of a reply: both
  // are moments to return to the bottom whatever they were doing before.
  useEffect(() => {
    stick.current = true;
  }, [messageCount]);

  useEffect(() => {
    if (!stick.current) return;
    // Instant, not smooth. A smooth scroll restarted on every token never
    // arrives: each call cancels the last one's animation, so the view
    // trails the text and jitters. Pinned is what this should look like.
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [growth]);

  // Collect all message IDs that have a net snapshot, in order
  const simBlockIds = useMemo(
    () => messages.filter((m) => m.netSnapshot != null).map((m) => m.id),
    [messages],
  );

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="min-h-0 flex-1 overflow-y-auto"
    >
      <div className="mx-auto max-w-3xl">
        {messages.map((msg) => {
          const versionIndex = msg.netSnapshot
            ? simBlockIds.indexOf(msg.id) + 1
            : 0;

          return (
            <div key={msg.id}>
              <ChatMessage message={msg} />
              {msg.netSnapshot && (
                <SimulationBlock
                  messageId={msg.id}
                  net={msg.netSnapshot}
                  versionIndex={versionIndex}
                  totalVersions={simBlockIds.length}
                  allBlockIds={simBlockIds}
                  snapshotId={msg.snapshotId}
                />
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
