/**
 * Fixed hex colors for statistics series, cycled by index.
 *
 * These are deliberately literal hex strings, not the app's usual
 * `var(--color-accent)` CSS variables: the PNG export in chart-image-export.ts
 * clones each chart's <svg> out of the document and rasterizes it in an
 * isolated <canvas>/<img>, where a CSS custom property has nothing to
 * resolve against and every line comes out black. A literal color survives
 * that trip unchanged.
 */
export const SERIES_COLORS = [
  "#2563eb", // blue
  "#10b981", // emerald
  "#f59e0b", // amber
  "#ef4444", // red
  "#8b5cf6", // violet
  "#ec4899", // pink
  "#14b8a6", // teal
  "#f97316", // orange
  "#6366f1", // indigo
  "#84cc16", // lime
];

export function colorForIndex(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}
