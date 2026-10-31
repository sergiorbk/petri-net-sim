import { render } from "@testing-library/react";
import type { EdgeProps } from "@xyflow/react";
import i18n from "@/i18n";
import { withArcHint } from "./arc-hint";

function Line() {
  return <path className="line" d="M 0 0 L 10 0" />;
}

const Hinted = withArcHint(Line);

function renderHinted(data: Record<string, unknown> | undefined) {
  const { container } = render(
    <svg>
      <g>
        <Hinted {...({ id: "e1", data } as unknown as EdgeProps)} />
      </g>
    </svg>,
  );
  return container;
}

describe("withArcHint", () => {
  it("names the connection in a <title> next to the edge, so hovering any part shows it", () => {
    const container = renderHinted({ arcKind: "fusion" });
    const title = container.querySelector("g > title")!;
    expect(title.textContent).toBe(i18n.t("canvas.arcHint.fusion"));
    expect(container.querySelector("g > path.line")).not.toBeNull();
  });

  it("has a hint for every kind the canvas hands out", () => {
    for (const kind of ["input", "output", "read", "inhibitor", "fusion"]) {
      const key = `canvas.arcHint.${kind}`;
      expect(i18n.exists(key, { lng: "en" })).toBe(true);
      expect(i18n.exists(key, { lng: "uk" })).toBe(true);
    }
  });

  it("adds nothing to an edge that carries no kind", () => {
    const container = renderHinted(undefined);
    expect(container.querySelector("title")).toBeNull();
  });
});
