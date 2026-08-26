import { render } from "@testing-library/react";
import { Position, type EdgeProps } from "@xyflow/react";
import { FusionEdge } from "./FusionEdge";

/**
 * FusionEdge draws the one link on the canvas that is a reference, not a
 * flow. These pin the desktop 2.3.0 notation down at the SVG level, since
 * nothing else in this app renders and inspects a custom edge: a rendering
 * regression here (wrong dash kind, a stray arrowhead, the node on the wrong
 * end) would otherwise ship unnoticed.
 */
function edgeProps(overrides: Partial<EdgeProps> = {}): EdgeProps {
  return {
    id: "l1",
    source: "copy",
    target: "master",
    sourceX: 0,
    sourceY: 0,
    targetX: 100,
    targetY: 40,
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    selected: false,
    style: { stroke: "#a855f7" },
    ...overrides,
  } as EdgeProps;
}

// BaseEdge renders bare <path>/<circle> elements; React Flow normally hosts
// them inside an <svg>, which the assertions below rely on for valid markup.
function renderEdge(overrides: Partial<EdgeProps> = {}) {
  const { container } = render(
    <svg>
      <FusionEdge {...edgeProps(overrides)} />
    </svg>,
  );
  return container;
}

describe("FusionEdge", () => {
  it("uses a dash-dot pattern, not an even dash", () => {
    const container = renderEdge();
    const path = container.querySelector<SVGPathElement>("path.react-flow__edge-path")!;
    expect(path.style.strokeDasharray).toBe("9 4 2 4");
  });

  it("draws the filled node at the target (master) end, not the source end", () => {
    const container = renderEdge();
    const circle = container.querySelector("circle")!;
    expect(circle.getAttribute("cx")).toBe("100");
    expect(circle.getAttribute("cy")).toBe("40");
  });

  it("renders exactly one node, so a fan of copies onto the same master reads as one origin", () => {
    const container = renderEdge();
    expect(container.querySelectorAll("circle").length).toBe(1);
  });

  it("renders no arrowhead: only BaseEdge's own visible and interaction paths", () => {
    const container = renderEdge();
    // An arrowhead would show up as a third <path>; BaseEdge itself always
    // renders exactly two (the visible line and its invisible hit target).
    expect(container.querySelectorAll("path").length).toBe(2);
  });

  it("widens the stroke and the node when selected", () => {
    const normal = renderEdge({ selected: false });
    const selected = renderEdge({ selected: true });

    const normalPath = normal.querySelector<SVGPathElement>("path.react-flow__edge-path")!;
    const selectedPath = selected.querySelector<SVGPathElement>("path.react-flow__edge-path")!;
    expect(normalPath.style.strokeWidth).toBe("1.4");
    expect(selectedPath.style.strokeWidth).toBe("2.2");

    const normalCircle = normal.querySelector("circle")!;
    const selectedCircle = selected.querySelector("circle")!;
    expect(normalCircle.getAttribute("r")).toBe("4");
    expect(selectedCircle.getAttribute("r")).toBe("5");
  });

  it("colours the node to match the tie's own stroke colour", () => {
    const container = renderEdge({ style: { stroke: "#3b82f6" } });
    const circle = container.querySelector("circle")!;
    expect(circle.getAttribute("fill")).toBe("#3b82f6");
  });

  it("draws a tie the running step lights as heavily as a selected one", () => {
    const lit = renderEdge({ selected: false, data: { lit: true } });
    const path = lit.querySelector<SVGPathElement>("path.react-flow__edge-path")!;
    expect(path.style.strokeWidth).toBe("2.2");
    expect(lit.querySelector("circle")!.getAttribute("r")).toBe("5");
  });
});
