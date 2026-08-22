/**
 * Rasterizing/serializing the panel's charts for download. No new dependency:
 * recharts already renders plain SVG, so cloning it out with explicit
 * dimensions and an XMLSerializer round-trip is enough to hand it to either a
 * direct .svg download or a <canvas> for .png.
 *
 * Every export is ONE file holding every chart, stacked. Two files per click
 * reads as tidier and is worse in both directions: browsers guard against a
 * page starting several downloads at once and silently drop all but the
 * first, and a reader who wants these in a report wants one picture of the
 * run, not a pair to arrange themselves.
 */

const GAP = 16;

interface SerializedChart {
  svgString: string;
  width: number;
  height: number;
}

function serializeChartSvg(container: HTMLElement): SerializedChart | null {
  const svg = container.querySelector("svg");
  if (!svg) return null;

  const rect = svg.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));

  // Clone rather than serialize in place: the live node has no explicit
  // width/height (it fills a ResponsiveContainer via percentages), and a
  // standalone SVG file needs real dimensions to render outside the page.
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));

  return { svgString: new XMLSerializer().serializeToString(clone), width, height };
}

/**
 * One SVG document with each chart nested inside it, offset down the page.
 * A nested <svg> establishes its own viewport, so each chart keeps its own
 * coordinate system and needs no rewriting of what is inside it.
 */
function combineCharts(charts: SerializedChart[], backgroundColor: string): SerializedChart {
  const width = Math.max(...charts.map((c) => c.width));
  const height =
    charts.reduce((sum, c) => sum + c.height, 0) + GAP * (charts.length - 1);

  let y = 0;
  const parts: string[] = [];
  for (const chart of charts) {
    // Strip the xmlns from the inner documents: repeating it is legal but
    // noisy, and the outer element already declares it for the whole tree.
    const inner = chart.svgString.replace(/ xmlns="[^"]*"/, "");
    parts.push(`<g transform="translate(0 ${y})">${inner}</g>`);
    y += chart.height + GAP;
  }

  const svgString =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" ` +
    `viewBox="0 0 ${width} ${height}">` +
    `<rect width="100%" height="100%" fill="${backgroundColor}"/>` +
    parts.join("") +
    `</svg>`;

  return { svgString, width, height };
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * SVG Blob -> data URL -> <img> -> <canvas> -> PNG Blob. Going through a data
 * URL (rather than an object URL) for the <img> source avoids a same-origin
 * hiccup some browsers apply to object URLs referencing SVG documents. Both
 * schemes need the app's Content-Security-Policy to name them under img-src,
 * which is why it does (see backend security_config.py).
 */
function rasterizeSvg(
  svgString: string,
  width: number,
  height: number,
  scale: number,
  backgroundColor: string,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const svgBlob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read the chart SVG"));
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = width * scale;
        canvas.height = height * scale;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          reject(new Error("Canvas is not supported in this browser"));
          return;
        }
        // Opaque background: an SVG line chart has a transparent backdrop,
        // and a PNG viewed outside the app's theme should not show through
        // to whatever is behind it (e.g. black on a dark desktop).
        ctx.fillStyle = backgroundColor;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.scale(scale, scale);
        ctx.drawImage(img, 0, 0, width, height);
        canvas.toBlob((blob) => {
          if (blob) resolve(blob);
          else reject(new Error("Could not render the chart image"));
        }, "image/png");
      };
      img.onerror = () => reject(new Error("Could not load the chart image"));
      img.src = reader.result as string;
    };
    reader.readAsDataURL(svgBlob);
  });
}

export interface ChartExportTarget {
  container: HTMLElement;
}

function serializeAll(targets: ChartExportTarget[]): SerializedChart[] {
  return targets
    .map(({ container }) => serializeChartSvg(container))
    .filter((c): c is SerializedChart => c !== null);
}

/** Returns how many charts went into the file, 0 if there was nothing to export. */
export function exportChartsAsSvg(
  targets: ChartExportTarget[],
  filename: string,
  backgroundColor: string,
): number {
  const charts = serializeAll(targets);
  if (charts.length === 0) return 0;

  const combined = combineCharts(charts, backgroundColor);
  downloadBlob(new Blob([combined.svgString], { type: "image/svg+xml" }), filename);
  return charts.length;
}

/** Returns how many charts went into the file. Throws if rasterizing fails. */
export async function exportChartsAsPng(
  targets: ChartExportTarget[],
  filename: string,
  backgroundColor: string,
  scale = 2,
): Promise<number> {
  const charts = serializeAll(targets);
  if (charts.length === 0) return 0;

  const combined = combineCharts(charts, backgroundColor);
  const blob = await rasterizeSvg(
    combined.svgString,
    combined.width,
    combined.height,
    scale,
    backgroundColor,
  );
  downloadBlob(blob, filename);
  return charts.length;
}
