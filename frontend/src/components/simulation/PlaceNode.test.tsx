import { render } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { PlaceNode, type PlaceNodeData } from "./PlaceNode";

function baseData(overrides: Partial<PlaceNodeData> = {}): PlaceNodeData {
  return {
    label: "P1",
    tokens: 0,
    initialTokens: 0,
    handles: [],
    ...overrides,
  };
}

function renderPlace(data: PlaceNodeData) {
  const { container } = render(
    <ReactFlowProvider>
      <PlaceNode data={data} />
    </ReactFlowProvider>,
  );
  return container.querySelector(".rounded-full")!;
}

/**
 * Desktop 2.3.0 draws every place taking part in a fusion, master or copy,
 * with a grey interior: once two places are one instance the marking is no
 * more the master's own than the copy's. This pins that both roles get the
 * same treatment and a place outside every group gets neither.
 */
describe("PlaceNode linked fill", () => {
  it("leaves an unlinked place with the plain interior", () => {
    const circle = renderPlace(baseData({ linked: false }));
    expect(circle.className).toContain("bg-white");
    expect(circle.className).toContain("dark:bg-zinc-900");
    expect(circle.className).not.toContain("bg-zinc-400");
  });

  it("gives a linked place the grey interior, master role", () => {
    // The master end of a fusion is never the link's sourceId (see
    // fusionGroupsByPlace's root resolution), but the fill only cares that
    // the place is IN a group, not which end it is.
    const circle = renderPlace(baseData({ linked: true, fusionLabel: "A" }));
    expect(circle.className).toContain("bg-zinc-400");
    expect(circle.className).toContain("dark:bg-zinc-600");
    expect(circle.className).not.toContain("bg-white");
  });

  it("gives a linked place the grey interior, copy role", () => {
    // A copy renders through the exact same `linked` flag as the master;
    // there is no separate "is this the copy" prop to fall out of sync.
    const circle = renderPlace(baseData({ linked: true, fusionLabel: "A" }));
    expect(circle.className).toContain("bg-zinc-400");
    expect(circle.className).toContain("dark:bg-zinc-600");
  });
});
