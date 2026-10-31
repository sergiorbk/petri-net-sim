import { render } from "@testing-library/react";
import { Position, type EdgeProps } from "@xyflow/react";
import { FusionEdge, fusionTieGeometry } from "./FusionEdge";

/**
 * FusionEdge draws the one link on the canvas that is a reference, not a
 * flow. These pin the desktop notation (a double line with an open arrowhead
 * at the copy end) down at the SVG level, since nothing else in this app
 * renders and inspects a custom edge: a rendering regression here (a dash
 * creeping back, the arrowhead on the wrong end) would otherwise ship
 * unnoticed.
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

function rails(container: Element) {
  return container.querySelector<SVGPathElement>("path.react-flow__edge-path")!;
}

function arrow(container: Element) {
  return container.querySelector<SVGPathElement>("path.react-flow__fusion-arrow")!;
}

describe("FusionEdge", () => {
  it("draws a solid double line, not a dashed one", () => {
    const container = renderEdge();
    const path = rails(container);
    expect(path.style.strokeDasharray).toBe("");
    // Two rails, each its own move-to.
    expect(path.getAttribute("d")!.match(/M/g)!.length).toBe(2);
  });

  it("puts the arrowhead tip at the source (copy) end, pointing away from the master", () => {
    const container = renderEdge();
    const d = arrow(container).getAttribute("d")!;
    // M arm L tip L arm: the tip is the middle point.
    const tip = d.split("L")[1].trim().split(/\s+/).map(Number);
    expect(tip).toEqual([0, 0]);
  });

  it("renders the arrowhead open, as a stroke rather than a filled shape", () => {
    const container = renderEdge();
    expect(arrow(container).getAttribute("fill")).toBe("none");
  });

  it("renders no end node: only the rails, their hit target and the arrowhead", () => {
    const container = renderEdge();
    expect(container.querySelectorAll("circle").length).toBe(0);
    expect(container.querySelectorAll("path").length).toBe(3);
  });

  it("widens the rails and the arrowhead when selected", () => {
    const normal = renderEdge({ selected: false });
    const selected = renderEdge({ selected: true });
    expect(rails(normal).style.strokeWidth).toBe("1.4");
    expect(rails(selected).style.strokeWidth).toBe("2.2");
    expect(arrow(normal).getAttribute("stroke-width")).toBe("1.4");
    expect(arrow(selected).getAttribute("stroke-width")).toBe("2.2");
  });

  it("colours the arrowhead to match the tie's own stroke colour", () => {
    const container = renderEdge({ style: { stroke: "#3b82f6" } });
    expect(arrow(container).getAttribute("stroke")).toBe("#3b82f6");
  });

  it("draws a tie the running step lights as heavily as a selected one", () => {
    const lit = renderEdge({ selected: false, data: { lit: true } });
    expect(rails(lit).style.strokeWidth).toBe("2.2");
  });
});

describe("fusionTieGeometry", () => {
  it("offsets the two rails to either side of the tie", () => {
    const { rails } = fusionTieGeometry({ x: 0, y: 0 }, { x: 100, y: 0 }, 4);
    const ys = [...rails.matchAll(/[ML] ([-\d.e]+) ([-\d.e]+)/g)].map((m) => Number(m[2]));
    expect(ys).toEqual([2, 2, -2, -2]);
  });

  it("does not break on a zero-length tie", () => {
    const { rails, arrow } = fusionTieGeometry({ x: 5, y: 5 }, { x: 5, y: 5 });
    expect(rails).not.toContain("NaN");
    expect(arrow).not.toContain("NaN");
  });
});
