import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChatMessage } from "./ChatMessage";
import type { ChatMessage as ChatMessageType } from "@/types/chat";

function makeMessage(overrides: Partial<ChatMessageType> = {}): ChatMessageType {
  return {
    id: "m1",
    role: "assistant",
    content: "hello",
    timestamp: 0,
    ...overrides,
  };
}

describe("ChatMessage", () => {
  it("renders plain assistant text", () => {
    render(<ChatMessage message={makeMessage()} />);
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("wraps pathological unbreakable strings via break-words class", () => {
    const longToken = "x".repeat(400);
    const { container } = render(
      <ChatMessage message={makeMessage({ content: longToken })} />,
    );
    const bubble = container.querySelector(
      '[class*="rounded-2xl"]',
    ) as HTMLElement | null;
    expect(bubble).not.toBeNull();
    // Wrapping safeguards live on the bubble; the flex column above it needs
    // min-w-0 so the row layout lets the bubble shrink below its intrinsic
    // width in the first place.
    expect(bubble!.className).toContain("break-words");
    expect(bubble!.className).toContain("[overflow-wrap:anywhere]");
    const column = bubble!.closest('[class*="min-w-0"]');
    expect(column).not.toBeNull();
  });

  it("renders agent steps inside the assistant bubble", () => {
    render(
      <ChatMessage
        message={makeMessage({
          content: "All done.",
          steps: [
            {
              type: "tool_call",
              id: "t1",
              name: "create_network",
              input: { name: "X" },
              status: "success",
            },
            {
              type: "tool_result",
              id: "t1",
              status: "success",
              output: "created",
            },
          ],
        })}
      />,
    );

    expect(screen.getByText("create network")).toBeInTheDocument();
    expect(screen.getByText("All done.")).toBeInTheDocument();
  });

  it("shows typing indicator when both content and steps are empty", () => {
    const { container } = render(
      <ChatMessage message={makeMessage({ content: "" })} />,
    );
    expect(container.querySelectorAll(".animate-pulse").length).toBe(3);
  });
});
