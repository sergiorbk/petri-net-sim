import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { AgentStepList } from "./AgentStepList";
import type { AgentStep } from "@/types/chat";

describe("AgentStepList", () => {
  it("returns nothing when step list is empty", () => {
    const { container } = render(<AgentStepList steps={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a running tool call with pretty-printed name", () => {
    const steps: AgentStep[] = [
      {
        type: "tool_call",
        id: "t1",
        name: "create_network",
        input: { name: "X" },
        status: "running",
      },
    ];

    render(<AgentStepList steps={steps} />);

    expect(screen.getByText("create network")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(
      screen.getByRole("list", { name: /agent reasoning steps/i }),
    ).toBeInTheDocument();
  });

  it("pairs a tool result with its call by id", () => {
    // Matches the store's post-result state: the call has been promoted
    // from "running" to "success" and the result carries the output.
    const steps: AgentStep[] = [
      {
        type: "tool_call",
        id: "t1",
        name: "add_machine",
        input: { name: "Lathe" },
        status: "success",
      },
      {
        type: "tool_result",
        id: "t1",
        status: "success",
        output: "Machine p2 created",
      },
    ];

    render(<AgentStepList steps={steps} />);

    expect(screen.getByText("Done")).toBeInTheDocument();

    // Completed cards are collapsed by default — expand to inspect details.
    fireEvent.click(screen.getByRole("button", { name: /add machine/i }));

    expect(screen.getByText(/"name": "Lathe"/)).toBeInTheDocument();
    expect(screen.getByText(/Machine p2 created/)).toBeInTheDocument();
  });

  it("renders an error result in red with Failed label", () => {
    const steps: AgentStep[] = [
      {
        type: "tool_call",
        id: "t1",
        name: "run_simulation",
        input: {},
        status: "error",
      },
      {
        type: "tool_result",
        id: "t1",
        status: "error",
        output: "Boom",
      },
    ];

    render(<AgentStepList steps={steps} />);

    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("toggles details when the header button is clicked on a completed step", () => {
    const steps: AgentStep[] = [
      {
        type: "tool_call",
        id: "t1",
        name: "add_generator",
        input: { interval: 1 },
        status: "success",
      },
      {
        type: "tool_result",
        id: "t1",
        status: "success",
        output: "Generator p1",
      },
    ];

    render(<AgentStepList steps={steps} />);

    // Completed steps are collapsed by default.
    expect(screen.queryByText(/"interval": 1/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /add generator/i }));

    expect(screen.getByText(/"interval": 1/)).toBeInTheDocument();
    expect(screen.getByText(/Generator p1/)).toBeInTheDocument();
  });

  it("does not render details section for a call with no input and no result", () => {
    const steps: AgentStep[] = [
      {
        type: "tool_call",
        id: "t1",
        name: "optimize_network",
        input: {},
        status: "success",
      },
    ];

    render(<AgentStepList steps={steps} />);

    // Button is still rendered but disabled; no Input / Result section.
    expect(screen.queryByText(/Input/i)).toBeNull();
    expect(screen.queryByText(/Result/i)).toBeNull();
  });
});
