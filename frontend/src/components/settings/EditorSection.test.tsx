import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { EditorSection } from "./EditorSection";
import { useNameConflictStore } from "@/stores/name-conflict-store";

beforeEach(() => {
  localStorage.clear();
  useNameConflictStore.setState({ policy: "ask", pending: null });
});

describe("EditorSection", () => {
  it("offers the three behaviours, with the saved one selected", () => {
    render(<EditorSection />);
    expect(screen.getByRole("radio", { name: /Ask me/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Pick another automatically/ })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /Allow the duplicate/ })).not.toBeChecked();
  });

  it("reflects a policy the warning's 'remember' box saved", () => {
    useNameConflictStore.setState({ policy: "keep" });
    render(<EditorSection />);
    expect(screen.getByRole("radio", { name: /Allow the duplicate/ })).toBeChecked();
  });

  it("choosing one changes the policy the editor actually uses, and keeps it", () => {
    render(<EditorSection />);
    fireEvent.click(screen.getByRole("radio", { name: /Pick another automatically/ }));

    expect(useNameConflictStore.getState().policy).toBe("auto");
    expect(localStorage.getItem("petri-net-sim-duplicate-name-policy")).toBe('"auto"');
  });

  it("can be switched back to asking after being remembered as something else", () => {
    useNameConflictStore.getState().setPolicy("keep");
    render(<EditorSection />);
    fireEvent.click(screen.getByRole("radio", { name: /Ask me/ }));
    expect(useNameConflictStore.getState().policy).toBe("ask");
  });
});
