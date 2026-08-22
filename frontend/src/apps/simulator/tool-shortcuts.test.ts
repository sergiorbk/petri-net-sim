import { describe, expect, it } from "vitest";
import { TOOL_SHORTCUTS } from "./SimulatorApp";
import { TOOLS } from "./LeftPanel/ToolPalette";

describe("tool shortcuts", () => {
  it("implements every shortcut the palette advertises", () => {
    // The palette used to show B/L/D/F next to tools the keydown handler
    // never knew about; deriving the map from TOOLS fixed that, and this
    // pins the invariant against anyone replacing it with a hand-written
    // list again.
    for (const tool of TOOLS) {
      expect(TOOL_SHORTCUTS[`Key${tool.shortcut}`]).toBe(tool.id);
    }
  });

  it("advertises every shortcut it implements", () => {
    expect(Object.keys(TOOL_SHORTCUTS)).toHaveLength(TOOLS.length);
  });
});
