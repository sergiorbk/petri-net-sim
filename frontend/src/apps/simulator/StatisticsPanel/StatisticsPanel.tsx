import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import { useStatisticsStore } from "@/stores/statistics-store";
import { formatSimTime, useSimulationStore, type TimeUnitScale } from "@/stores/simulation-store";
import { toast } from "@/stores/toast-store";
import {
  buildStatisticsCsv,
  buildWideRows,
  disambiguateNames,
  statisticsFileName,
  type ExportSeries,
  type NamedElement,
  type SeriesPoint,
} from "@/lib/statistics-export";
import { exportChartsAsPng, exportChartsAsSvg, type ChartExportTarget } from "./chart-image-export";
import { colorForIndex } from "./palette";

/**
 * Net order first, so series line up the way the net was authored, then
 * anything the statistics store recorded that the net lookup doesn't
 * recognize (a composed-model edge case) tacked on at the end -- nothing
 * collected during the run is ever silently dropped from the panel. Names
 * are disambiguated across the whole group before building series, since a
 * composed net can instantiate the same Petri-object twice and end up with
 * two places both named e.g. "Ready".
 */
function orderedSeries(
  recorded: Record<string, SeriesPoint[]>,
  namedList: readonly NamedElement[],
  objects: readonly { id: string; name: string }[],
  kind: ExportSeries["kind"],
): ExportSeries[] {
  const seen = new Set<string>();
  const items: NamedElement[] = [];
  for (const item of namedList) {
    if (!(item.id in recorded)) continue;
    seen.add(item.id);
    items.push(item);
  }
  for (const id of Object.keys(recorded)) {
    if (seen.has(id)) continue;
    items.push({ id, name: id });
  }

  const names = disambiguateNames(items, objects);
  return items.map((item) => ({
    id: item.id,
    name: names.get(item.id) ?? item.name,
    kind,
    points: recorded[item.id],
  }));
}

export function StatisticsPanel() {
  const { t } = useTranslation();
  const setOpen = useUiStore((s) => s.setStatisticsOpen);
  const resolvedTheme = useUiStore((s) => s.resolvedTheme);
  const placeMarkings = useStatisticsStore((s) => s.placeMarkings);
  const transitionBuffers = useStatisticsStore((s) => s.transitionBuffers);
  const net = useSimulationStore((s) => s.net);
  const timeUnitScale = useSimulationStore((s) => s.timeUnitScale);

  const placeSeries = useMemo(
    () => orderedSeries(placeMarkings, net?.places ?? [], net?.objects ?? [], "place"),
    [placeMarkings, net],
  );
  const transitionSeries = useMemo(
    () => orderedSeries(transitionBuffers, net?.transitions ?? [], net?.objects ?? [], "transition"),
    [transitionBuffers, net],
  );
  const allSeries = useMemo(() => [...placeSeries, ...transitionSeries], [placeSeries, transitionSeries]);

  const colorMap = useMemo(() => {
    const map: Record<string, string> = {};
    allSeries.forEach((s, i) => {
      map[s.id] = colorForIndex(i);
    });
    return map;
  }, [allSeries]);

  // Toggle state lives only in this panel, per the brief: it resets every
  // time the panel is opened rather than surviving in a store. Default is
  // "all on" for both places and transitions.
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  useEffect(() => {
    setEnabled((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const s of allSeries) {
        if (!(s.id in next)) {
          next[s.id] = true;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [allSeries]);

  const toggle = useCallback((id: string) => {
    setEnabled((prev) => ({ ...prev, [id]: !(prev[id] ?? true) }));
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [setOpen]);

  const placeChartRef = useRef<HTMLDivElement>(null);
  const transitionChartRef = useRef<HTMLDivElement>(null);

  const netName = net?.name || "net";
  const chartBackground = resolvedTheme === "dark" ? "#0f0f0f" : "#ffffff";

  const handleExportCsv = useCallback(() => {
    if (allSeries.length === 0) {
      toast(t("statisticsPanel.nothingToExport"), "warning");
      return;
    }
    const csv = buildStatisticsCsv(allSeries);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = statisticsFileName(netName, "csv");
    a.click();
    URL.revokeObjectURL(url);
  }, [allSeries, netName, t]);

  // Both charts go into one file, in the order they are shown. The filename
  // carries no per-chart suffix for the same reason: there is one image.
  const collectChartTargets = useCallback((): ChartExportTarget[] => {
    const targets: ChartExportTarget[] = [];
    if (placeChartRef.current && placeSeries.length > 0) {
      targets.push({ container: placeChartRef.current });
    }
    if (transitionChartRef.current && transitionSeries.length > 0) {
      targets.push({ container: transitionChartRef.current });
    }
    return targets;
  }, [placeSeries.length, transitionSeries.length]);

  const handleExportSvg = useCallback(() => {
    const count = exportChartsAsSvg(
      collectChartTargets(),
      statisticsFileName(netName, "svg", "charts"),
      chartBackground,
    );
    if (count === 0) toast(t("statisticsPanel.nothingToExport"), "warning");
  }, [collectChartTargets, netName, chartBackground, t]);

  const handleExportPng = useCallback(async () => {
    try {
      const count = await exportChartsAsPng(
        collectChartTargets(),
        statisticsFileName(netName, "png", "charts"),
        chartBackground,
      );
      if (count === 0) toast(t("statisticsPanel.nothingToExport"), "warning");
    } catch (err) {
      toast(err instanceof Error ? err.message : t("statisticsPanel.exportFailed"), "error");
    }
  }, [collectChartTargets, netName, chartBackground, t]);

  return (
    <div className="absolute inset-0 z-30 flex flex-col bg-surface">
      <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-2.5">
        <button
          type="button"
          onClick={() => setOpen(false)}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium",
            "text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary",
          )}
        >
          <ArrowLeft size={14} />
          {t("statisticsPanel.back")}
        </button>
        <h2 className="text-sm font-semibold text-text-primary">{t("statisticsPanel.title")}</h2>
        <div className="ml-auto flex items-center gap-1.5">
          <ExportButton label={t("statisticsPanel.exportCsv")} onClick={handleExportCsv} />
          <ExportButton label={t("statisticsPanel.exportPng")} onClick={handleExportPng} />
          <ExportButton label={t("statisticsPanel.exportSvg")} onClick={handleExportSvg} />
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {allSeries.length === 0 ? (
          <p className="text-sm text-text-muted">{t("statisticsPanel.noData")}</p>
        ) : (
          <>
            <SeriesLegend series={allSeries} enabled={enabled} onToggle={toggle} colorMap={colorMap} />

            <div className="mt-3 flex flex-col gap-4">
              {placeSeries.length > 0 && (
                <ChartCard
                  ref={placeChartRef}
                  title={t("statisticsPanel.chartPlaces")}
                  series={placeSeries}
                  enabled={enabled}
                  colorMap={colorMap}
                  timeUnitScale={timeUnitScale}
                />
              )}
              {transitionSeries.length > 0 && (
                <ChartCard
                  ref={transitionChartRef}
                  title={t("statisticsPanel.chartTransitions")}
                  series={transitionSeries}
                  enabled={enabled}
                  colorMap={colorMap}
                  timeUnitScale={timeUnitScale}
                />
              )}
            </div>

            <SummaryTable series={allSeries} colorMap={colorMap} />
          </>
        )}
      </div>
    </div>
  );
}

function ExportButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-1 rounded-md border border-border px-2.5 py-1",
        "text-[11px] font-medium text-text-secondary transition-colors",
        "hover:bg-surface-hover hover:text-text-primary",
      )}
    >
      <Download size={12} />
      {label}
    </button>
  );
}

function SeriesLegend({
  series,
  enabled,
  onToggle,
  colorMap,
}: {
  series: ExportSeries[];
  enabled: Record<string, boolean>;
  onToggle: (id: string) => void;
  colorMap: Record<string, string>;
}) {
  const { t } = useTranslation();
  const places = series.filter((s) => s.kind === "place");
  const transitions = series.filter((s) => s.kind === "transition");

  return (
    <div className="flex flex-col gap-2">
      {places.length > 0 && (
        <LegendRow
          label={t("statisticsPanel.legendPlaces")}
          items={places}
          enabled={enabled}
          onToggle={onToggle}
          colorMap={colorMap}
        />
      )}
      {transitions.length > 0 && (
        <LegendRow
          label={t("statisticsPanel.legendTransitions")}
          items={transitions}
          enabled={enabled}
          onToggle={onToggle}
          colorMap={colorMap}
        />
      )}
    </div>
  );
}

function LegendRow({
  label,
  items,
  enabled,
  onToggle,
  colorMap,
}: {
  label: string;
  items: ExportSeries[];
  enabled: Record<string, boolean>;
  onToggle: (id: string) => void;
  colorMap: Record<string, string>;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 shrink-0 text-[11px] font-medium text-text-muted">{label}:</span>
      {items.map((s) => {
        const on = enabled[s.id] ?? true;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onToggle(s.id)}
            aria-pressed={on}
            className={cn(
              "flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5",
              "text-[11px] transition-colors",
              on ? "bg-surface text-text-primary" : "bg-surface text-text-muted opacity-45",
            )}
          >
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: colorMap[s.id] }}
            />
            {s.name}
          </button>
        );
      })}
    </div>
  );
}

interface ChartCardProps {
  title: string;
  series: ExportSeries[];
  enabled: Record<string, boolean>;
  colorMap: Record<string, string>;
  timeUnitScale: TimeUnitScale;
}

const ChartCard = forwardRef<HTMLDivElement, ChartCardProps>(function ChartCard(
  { title, series, enabled, colorMap, timeUnitScale },
  ref,
) {
  const data = useMemo(() => buildWideRows(series), [series]);
  // Ticks and the tooltip label read as "1 m 30 s", matching the playback
  // bar, instead of the raw simulation-time float underneath -- the data
  // itself stays numeric, only the display goes through the formatter.
  const formatTime = useCallback(
    (t: number) => formatSimTime(t, timeUnitScale),
    [timeUnitScale],
  );

  return (
    <div className="rounded-lg border border-border bg-surface-secondary p-3">
      <p className="mb-2 text-xs font-medium text-text-primary">{title}</p>
      <div ref={ref} className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="time" tick={{ fontSize: 11 }} tickFormatter={formatTime} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip labelFormatter={(label) => formatTime(Number(label))} />
            {series.map((s) =>
              (enabled[s.id] ?? true) ? (
                <Line
                  key={s.id}
                  type="monotone"
                  dataKey={s.id}
                  name={s.name}
                  stroke={colorMap[s.id]}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              ) : null,
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
});

function SummaryTable({ series, colorMap }: { series: ExportSeries[]; colorMap: Record<string, string> }) {
  const { t } = useTranslation();

  return (
    <div className="mt-4 overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="border-b border-border bg-surface-secondary text-left text-text-muted">
            <th className="px-2 py-1.5 font-medium">{t("statisticsPanel.table.series")}</th>
            <th className="px-2 py-1.5 font-medium">{t("statisticsPanel.table.points")}</th>
            <th className="px-2 py-1.5 font-medium">{t("statisticsPanel.table.min")}</th>
            <th className="px-2 py-1.5 font-medium">{t("statisticsPanel.table.max")}</th>
            <th className="px-2 py-1.5 font-medium">{t("statisticsPanel.table.mean")}</th>
            <th className="px-2 py-1.5 font-medium">{t("statisticsPanel.table.last")}</th>
          </tr>
        </thead>
        <tbody>
          {series.map((s) => {
            const values = s.points.map((p) => p.value);
            const hasValues = values.length > 0;
            const min = hasValues ? Math.min(...values) : null;
            const max = hasValues ? Math.max(...values) : null;
            const mean = hasValues ? values.reduce((a, b) => a + b, 0) / values.length : null;
            const last = s.points[s.points.length - 1]?.value;
            return (
              <tr key={s.id} className="border-b border-border last:border-0">
                <td className="px-2 py-1.5 text-text-secondary">
                  <span
                    className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle"
                    style={{ backgroundColor: colorMap[s.id] }}
                  />
                  {s.name}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-text-muted">{s.points.length}</td>
                <td className="px-2 py-1.5 tabular-nums text-text-muted">{min ?? "-"}</td>
                <td className="px-2 py-1.5 tabular-nums text-text-muted">{max ?? "-"}</td>
                <td className="px-2 py-1.5 tabular-nums text-text-muted">{mean !== null ? mean.toFixed(2) : "-"}</td>
                <td className="px-2 py-1.5 tabular-nums text-text-muted">{last ?? "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
