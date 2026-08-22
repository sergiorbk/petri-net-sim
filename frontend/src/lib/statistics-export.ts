/**
 * Pure data-shaping for the statistics panel: no React, no DOM, so it is
 * cheap to unit-test the one part of the feature with real edge cases
 * (forward-fill, quoting) without a browser.
 */

export interface SeriesPoint {
  time: number;
  value: number;
}

export interface ExportSeries {
  id: string;
  name: string;
  kind: "place" | "transition";
  points: SeriesPoint[];
}

export interface NamedElement {
  id: string;
  name: string;
  /** Owning Petri-object frame's id, if this element sits inside one. */
  objectId?: string;
}

/**
 * A composed net can instantiate the same Petri-object more than once, and
 * each copy keeps the template's element names -- so "Ready" or "Out" is
 * exactly the kind of name that recurs across a net without meaning the
 * same place twice. Qualify a name with its owning object's name only when
 * the bare name collides with another element in the same group (i.e. the
 * same net.places or net.transitions list); a name that is already unique
 * stays short. If qualifying still leaves a collision -- two elements with
 * the same name in the same object, or duplicates with no owning object at
 * all -- there is nothing left to distinguish them with, so those fall back
 * to their raw id, which is always unique.
 */
export function disambiguateNames(
  items: readonly NamedElement[],
  objects: readonly { id: string; name: string }[],
): Map<string, string> {
  const objectName = new Map(objects.map((o) => [o.id, o.name?.trim()] as const));

  const baseNameOf = (item: NamedElement) => item.name?.trim() || item.id;

  const groups = new Map<string, NamedElement[]>();
  for (const item of items) {
    const base = baseNameOf(item);
    const group = groups.get(base) ?? [];
    group.push(item);
    groups.set(base, group);
  }

  const result = new Map<string, string>();
  for (const [base, group] of groups) {
    if (group.length === 1) {
      result.set(group[0].id, base);
      continue;
    }

    // Ambiguous bare name: qualify with the owning object's name where one
    // exists. An item with no object (or an unrecognized one) has nothing to
    // qualify with, so its candidate is just the still-ambiguous base name.
    const candidateOf = new Map<string, string>();
    const byCandidate = new Map<string, NamedElement[]>();
    for (const item of group) {
      const objName = item.objectId ? objectName.get(item.objectId) : undefined;
      const candidate = objName ? `${base} (${objName})` : base;
      candidateOf.set(item.id, candidate);
      const bucket = byCandidate.get(candidate) ?? [];
      bucket.push(item);
      byCandidate.set(candidate, bucket);
    }

    for (const item of group) {
      const candidate = candidateOf.get(item.id)!;
      const stillAmbiguous = (byCandidate.get(candidate)?.length ?? 0) > 1;
      result.set(item.id, stillAmbiguous ? item.id : candidate);
    }
  }

  return result;
}

/**
 * A marking/buffer holds until the next recorded change, so a series with no
 * sample exactly at time `t` should read as its last known value, not as a
 * gap -- except before its first sample, where nothing is known yet and the
 * cell must stay empty. Shared by the CSV writer and by the panel's charts,
 * which need the same union-of-times, forward-filled shape to plot several
 * series that were not necessarily sampled at the same instants.
 */
export function buildWideRows(series: ExportSeries[]): Array<{ time: number } & Record<string, number>> {
  const times = new Set<number>();
  for (const s of series) {
    for (const p of s.points) times.add(p.time);
  }
  const sortedTimes = Array.from(times).sort((a, b) => a - b);

  const sortedPoints = series.map((s) => [...s.points].sort((a, b) => a.time - b.time));
  const cursors = series.map(() => 0);
  const lastValues: (number | undefined)[] = series.map(() => undefined);

  return sortedTimes.map((t) => {
    const row: { time: number } & Record<string, number> = { time: t };
    series.forEach((s, i) => {
      const pts = sortedPoints[i];
      while (cursors[i] < pts.length && pts[cursors[i]].time <= t) {
        lastValues[i] = pts[cursors[i]].value;
        cursors[i]++;
      }
      const v = lastValues[i];
      if (v !== undefined) row[s.id] = v;
    });
    return row;
  });
}

function seriesColumnName(s: ExportSeries): string {
  const prefix = s.kind === "place" ? "Place" : "Transition";
  return `${prefix}: ${s.name}`;
}

/** RFC 4180: quote a field that contains a comma, quote or newline, doubling any inner quotes. */
function csvField(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

/**
 * Wide-format CSV: one `time` column plus one column per series. This is
 * the shape Excel and PowerBI want, versus a long/tidy format with a
 * series-id column -- a wide table is what a spreadsheet user expects to
 * paste straight into a pivot or a chart.
 */
export function buildStatisticsCsv(series: ExportSeries[]): string {
  const header = ["time", ...series.map((s) => csvField(seriesColumnName(s)))];
  const rows = buildWideRows(series);

  const lines = [header.join(",")];
  for (const row of rows) {
    const cells = [String(row.time)];
    for (const s of series) {
      const v = row[s.id];
      cells.push(v === undefined ? "" : String(v));
    }
    lines.push(cells.join(","));
  }

  // Trailing newline: several CSV readers (and diff tools) treat a file that
  // doesn't end in one as missing its last line.
  return lines.join("\n") + "\n";
}

/** Characters no major filesystem accepts in a name, plus the control range. */
// eslint-disable-next-line no-control-regex
const FILENAME_UNSAFE = /[\\\/:*?"<>|\u0000-\u001f]/g;

/** How much of the net name to keep, so the result stays a manageable name. */
const NAME_LIMIT = 60;

/**
 * e.g. statisticsFileName("My Net", "csv") -> "My_Net-statistics.csv"
 *
 * Only genuinely unsafe characters are replaced, not every non-ASCII one. A
 * net named in Cyrillic is the normal case here, and stripping to [a-zA-Z0-9]
 * turned "простая сеть петри" into a row of underscores that told its owner
 * nothing about which run they had just exported.
 */
export function statisticsFileName(
  netName: string,
  extension: string,
  /**
   * Distinguishes one export from another for the same net, e.g. "places".
   * Kept separate from netName rather than concatenated by the caller: the
   * length cap below applies to the net name only, so a long name can never
   * truncate the suffix away and leave two charts fighting over one filename.
   */
  suffix?: string,
): string {
  const safe = netName
    .trim()
    .replace(FILENAME_UNSAFE, "_")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    // Windows rejects a name ending in a dot or a space, and a leading dot
    // would make the file hidden on unix.
    .replace(/^[._]+|[._]+$/g, "")
    .slice(0, NAME_LIMIT)
    .replace(/[._]+$/g, "");

  const tail = suffix ? `-${suffix}` : "";
  return `${safe || "net"}${tail}-statistics.${extension}`;
}
