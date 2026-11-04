import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { DuplicateNameDialog } from "./DuplicateNameDialog";
import {
  useNameConflictStore,
  type NameDecision,
} from "@/stores/name-conflict-store";
import type { NameConflict } from "@/lib/petri-names";

const row = (id: string, name: string, suggestion: string): NameConflict => ({
  ids: [id],
  kind: "place",
  name,
  suggestion,
});

function open(conflicts: NameConflict[], taken: string[] = conflicts.map((c) => c.name)) {
  const onDecision = vi.fn<(d: NameDecision) => void>();
  act(() => {
    useNameConflictStore.setState({
      policy: "ask",
      pending: { conflicts, taken: new Set(taken), onDecision },
    });
  });
  return onDecision;
}

beforeEach(() => {
  localStorage.clear();
  useNameConflictStore.setState({ policy: "ask", pending: null });
});

describe("DuplicateNameDialog", () => {
  it("renders nothing while no request is open", () => {
    const { container } = render(<DuplicateNameDialog />);
    expect(container.firstChild).toBeNull();
  });

  it("names the clashing name and offers the suggestion as a placeholder", () => {
    render(<DuplicateNameDialog />);
    open([row("p1", "Queue", "Queue_2")]);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/"Queue" is already used/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Queue_2")).toBeInTheDocument();
  });

  it("an untouched field applies the suggested name", () => {
    render(<DuplicateNameDialog />);
    const onDecision = open([row("p1", "Queue", "Queue_2")]);

    fireEvent.click(screen.getByRole("button", { name: "Use these names" }));

    expect(onDecision).toHaveBeenCalledWith({
      kind: "rename",
      renames: new Map([["p1", "Queue_2"]]),
    });
    expect(useNameConflictStore.getState().pending).toBeNull();
  });

  it("a typed name is applied instead", () => {
    render(<DuplicateNameDialog />);
    const onDecision = open([row("p1", "Queue", "Queue_2")]);

    fireEvent.change(screen.getByLabelText("New name for Queue"), {
      target: { value: "  Buffer " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use these names" }));

    expect(onDecision).toHaveBeenCalledWith({
      kind: "rename",
      renames: new Map([["p1", "Buffer"]]),
    });
  });

  it("refuses a typed name that is still taken, and says so", () => {
    render(<DuplicateNameDialog />);
    const onDecision = open([row("p1", "Queue", "Queue_2")], ["Queue", "Taken"]);

    fireEvent.change(screen.getByLabelText("New name for Queue"), {
      target: { value: "Taken" },
    });

    expect(screen.getByText("This name is already used.")).toBeInTheDocument();
    const apply = screen.getByRole("button", { name: "Use these names" });
    expect(apply).toBeDisabled();
    fireEvent.click(apply);
    expect(onDecision).not.toHaveBeenCalled();
  });

  it("refuses the same typed name in two rows", () => {
    render(<DuplicateNameDialog />);
    open([row("p1", "A", "A_2"), row("p2", "B", "B_2")], ["A", "B"]);

    fireEvent.change(screen.getByLabelText("New name for A"), { target: { value: "Same" } });
    fireEvent.change(screen.getByLabelText("New name for B"), { target: { value: "Same" } });

    expect(screen.getAllByText("Two fields have the same name.")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Use these names" })).toBeDisabled();
  });

  it("a typed name cannot be taken by another row's suggestion", () => {
    render(<DuplicateNameDialog />);
    const onDecision = open([row("p1", "A", "A_2"), row("p2", "A", "A_3")], ["A"]);

    // Row 1 is typed as A_3; row 2 is left empty and must not land on it.
    fireEvent.change(screen.getAllByLabelText("New name for A")[0], {
      target: { value: "A_3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Use these names" }));

    const decision = onDecision.mock.calls[0][0];
    expect(decision.kind).toBe("rename");
    const names = [...(decision as { renames: Map<string, string> }).renames.values()];
    expect(new Set(names).size).toBe(2);
    expect(names).toContain("A_3");
  });

  it("'Pick automatically' with the box ticked saves the policy", () => {
    render(<DuplicateNameDialog />);
    const onDecision = open([row("p1", "Queue", "Queue_2")]);

    fireEvent.click(screen.getByLabelText("Remember my choice"));
    fireEvent.click(screen.getByRole("button", { name: "Pick automatically" }));

    expect(onDecision).toHaveBeenCalledWith({
      kind: "rename",
      renames: new Map([["p1", "Queue_2"]]),
    });
    expect(useNameConflictStore.getState().policy).toBe("auto");
  });

  it("'Keep duplicate' with the box ticked saves that policy", () => {
    render(<DuplicateNameDialog />);
    const onDecision = open([row("p1", "Queue", "Queue_2")]);

    fireEvent.click(screen.getByLabelText("Remember my choice"));
    fireEvent.click(screen.getByRole("button", { name: "Keep duplicate" }));

    expect(onDecision).toHaveBeenCalledWith({ kind: "keep" });
    expect(useNameConflictStore.getState().policy).toBe("keep");
  });

  it("without the box ticked nothing is saved", () => {
    render(<DuplicateNameDialog />);
    open([row("p1", "Queue", "Queue_2")]);

    fireEvent.click(screen.getByRole("button", { name: "Pick automatically" }));

    expect(useNameConflictStore.getState().policy).toBe("ask");
  });

  it("Escape cancels", () => {
    render(<DuplicateNameDialog />);
    const onDecision = open([row("p1", "Queue", "Queue_2")]);

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onDecision).toHaveBeenCalledWith({ kind: "cancel" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("lists every conflict when a whole subnet is pasted", () => {
    render(<DuplicateNameDialog />);
    open([row("p1", "A", "A_2"), row("p2", "B", "B_2"), row("p3", "C", "C_2")]);

    expect(screen.getByText("Names already in use")).toBeInTheDocument();
    expect(screen.getByText(/3 names are already used/)).toBeInTheDocument();
    expect(screen.getAllByRole("textbox")).toHaveLength(3);
  });
});
