import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { ChatMessageList } from "./ChatMessageList";
import type { ChatMessage as ChatMessageType } from "@/types/chat";

function assistant(content: string, overrides: Partial<ChatMessageType> = {}): ChatMessageType {
  return { id: "a1", role: "assistant", content, timestamp: 0, ...overrides };
}

const user: ChatMessageType = {
  id: "u1", role: "user", content: "build me a net", timestamp: 0,
};

/** jsdom has no layout, so the scroll container reports zeroes and every
 * position reads as "at the bottom". Give it real numbers to say otherwise. */
function setScrollPosition(
  container: HTMLElement,
  { scrollTop, scrollHeight, clientHeight }: Record<string, number>,
) {
  const el = container.querySelector(".overflow-y-auto") as HTMLElement;
  Object.defineProperty(el, "scrollHeight", { value: scrollHeight, configurable: true });
  Object.defineProperty(el, "clientHeight", { value: clientHeight, configurable: true });
  el.scrollTop = scrollTop;
  fireEvent.scroll(el);
  return el;
}

describe("ChatMessageList auto-scroll", () => {
  let scrollIntoView: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
  });

  it("follows the reply as it is being written, not just between messages", () => {
    const { rerender } = render(
      <ChatMessageList messages={[user, assistant("Sure")]} />,
    );
    scrollIntoView.mockClear();

    // Same message, more text: exactly what streaming does, and exactly
    // what a message-count trigger cannot see.
    rerender(<ChatMessageList messages={[user, assistant("Sure, here is")]} />);

    expect(scrollIntoView).toHaveBeenCalled();
  });

  it("follows agent steps appearing above the text too", () => {
    const { rerender } = render(
      <ChatMessageList messages={[user, assistant("")]} />,
    );
    scrollIntoView.mockClear();

    rerender(
      <ChatMessageList
        messages={[user, assistant("", {
          steps: [{ type: "tool_call", id: "t1", name: "add_generator", input: {}, status: "running" }],
        })]}
      />,
    );

    expect(scrollIntoView).toHaveBeenCalled();
  });

  it("stays put once the reader has scrolled up to read something older", () => {
    const { container, rerender } = render(
      <ChatMessageList messages={[user, assistant("Sure")]} />,
    );
    setScrollPosition(container, { scrollTop: 0, scrollHeight: 4000, clientHeight: 600 });
    scrollIntoView.mockClear();

    rerender(<ChatMessageList messages={[user, assistant("Sure, here is")]} />);

    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("follows again as soon as the reader returns to the bottom", () => {
    const { container, rerender } = render(
      <ChatMessageList messages={[user, assistant("Sure")]} />,
    );
    setScrollPosition(container, { scrollTop: 0, scrollHeight: 4000, clientHeight: 600 });
    setScrollPosition(container, { scrollTop: 3400, scrollHeight: 4000, clientHeight: 600 });
    scrollIntoView.mockClear();

    rerender(<ChatMessageList messages={[user, assistant("Sure, here is")]} />);

    expect(scrollIntoView).toHaveBeenCalled();
  });

  it("returns to the bottom when a new message arrives, wherever the reader was", () => {
    const { container, rerender } = render(
      <ChatMessageList messages={[user, assistant("Sure")]} />,
    );
    setScrollPosition(container, { scrollTop: 0, scrollHeight: 4000, clientHeight: 600 });
    scrollIntoView.mockClear();

    rerender(
      <ChatMessageList
        messages={[user, assistant("Sure"), { ...user, id: "u2", content: "and now" }]}
      />,
    );

    expect(scrollIntoView).toHaveBeenCalled();
  });
});
