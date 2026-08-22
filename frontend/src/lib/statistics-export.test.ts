import { describe, expect, it } from "vitest";
import {
  buildStatisticsCsv,
  disambiguateNames,
  statisticsFileName,
  type ExportSeries,
  type NamedElement,
} from "./statistics-export";

describe("buildStatisticsCsv", () => {
  it("unions the time values across series and sorts them ascending", () => {
    const series: ExportSeries[] = [
      { id: "p1", name: "A", kind: "place", points: [{ time: 5, value: 1 }, { time: 0, value: 3 }] },
      { id: "p2", name: "B", kind: "place", points: [{ time: 2, value: 9 }] },
    ];

    const csv = buildStatisticsCsv(series);
    const lines = csv.trim().split("\n");

    expect(lines[0]).toBe("time,Place: A,Place: B");
    expect(lines.slice(1).map((l) => l.split(",")[0])).toEqual(["0", "2", "5"]);
  });

  it("carries a series' previous value forward when another series samples at a new time", () => {
    const series: ExportSeries[] = [
      { id: "p1", name: "A", kind: "place", points: [{ time: 0, value: 10 }, { time: 10, value: 20 }] },
      { id: "t1", name: "B", kind: "transition", points: [{ time: 5, value: 1 }] },
    ];

    const csv = buildStatisticsCsv(series);
    const lines = csv.trim().split("\n");

    // At t=5, series A has no sample of its own -- it should hold its last
    // known value (10) rather than leave a gap, since a marking holds until
    // it next changes.
    expect(lines).toEqual([
      "time,Place: A,Transition: B",
      "0,10,",
      "5,10,1",
      "10,20,1",
    ]);
  });

  it("leaves a cell empty before a series' first sample", () => {
    const series: ExportSeries[] = [
      { id: "p1", name: "A", kind: "place", points: [{ time: 0, value: 1 }] },
      { id: "p2", name: "B", kind: "place", points: [{ time: 3, value: 2 }] },
    ];

    const csv = buildStatisticsCsv(series);
    const lines = csv.trim().split("\n");

    expect(lines).toEqual([
      "time,Place: A,Place: B",
      "0,1,",
      "3,1,2",
    ]);
  });

  it("quotes a series name containing a comma", () => {
    const series: ExportSeries[] = [
      { id: "p1", name: "Buffer, primary", kind: "place", points: [{ time: 0, value: 1 }] },
    ];

    const csv = buildStatisticsCsv(series);
    expect(csv.split("\n")[0]).toBe('time,"Place: Buffer, primary"');
  });

  it("quotes and doubles an inner quote in a series name", () => {
    const series: ExportSeries[] = [
      { id: "t1", name: 'The "main" queue', kind: "transition", points: [{ time: 0, value: 1 }] },
    ];

    const csv = buildStatisticsCsv(series);
    expect(csv.split("\n")[0]).toBe('time,"Transition: The ""main"" queue"');
  });

  it("ends the file with a trailing newline", () => {
    const series: ExportSeries[] = [
      { id: "p1", name: "A", kind: "place", points: [{ time: 0, value: 1 }] },
    ];

    const csv = buildStatisticsCsv(series);
    expect(csv.endsWith("\n")).toBe(true);
    expect(csv.endsWith("\n\n")).toBe(false);
  });

  it("produces just the header, with a trailing newline, for no series", () => {
    const csv = buildStatisticsCsv([]);
    expect(csv).toBe("time\n");
  });
});

describe("statisticsFileName", () => {
  it("builds a name with the given extension", () => {
    expect(statisticsFileName("my-net", "csv")).toBe("my-net-statistics.csv");
  });

  it("replaces only the characters a filesystem rejects", () => {
    expect(statisticsFileName('a/b:c*d?e"f<g>h|i', "png")).toBe("a_b_c_d_e_f_g_h_i-statistics.png");
  });

  it("replaces a backslash but keeps a hyphen", () => {
    // A hyphen is safe everywhere and common in net names; a backslash is a
    // path separator on the platform this is most often exported from.
    expect(statisticsFileName("queue\\v2-final", "csv")).toBe("queue_v2-final-statistics.csv");
  });

  it("collapses whitespace and keeps ordinary punctuation", () => {
    expect(statisticsFileName("My Net!  v2", "png")).toBe("My_Net!_v2-statistics.png");
  });

  it("keeps a non-Latin name readable", () => {
    // The real case: nets here are named in Cyrillic, and stripping to ASCII
    // produced a filename that was one long row of underscores.
    expect(statisticsFileName("простая сеть", "csv")).toBe("простая_сеть-statistics.csv");
  });

  it("does not end the name in a dot or an underscore", () => {
    expect(statisticsFileName("счетчик. парам...", "csv")).toBe("счетчик._парам-statistics.csv");
  });

  it("keeps the suffix even when the net name is capped", () => {
    // The cap applies to the name alone. Concatenating the suffix into the
    // name first let a long name truncate it away, so both charts exported
    // under one filename and only one file survived.
    const long = "n".repeat(100);
    expect(statisticsFileName(long, "png", "places")).toBe(
      "n".repeat(60) + "-places-statistics.png",
    );
    expect(statisticsFileName(long, "png", "transitions")).toBe(
      "n".repeat(60) + "-transitions-statistics.png",
    );
  });

  it("falls back when nothing usable is left", () => {
    expect(statisticsFileName("   ", "csv")).toBe("net-statistics.csv");
    expect(statisticsFileName("///", "csv")).toBe("net-statistics.csv");
  });
});

describe("disambiguateNames", () => {
  it("leaves a unique name untouched", () => {
    const items: NamedElement[] = [
      { id: "p1", name: "Arrivals_Ready", objectId: "obj1" },
      { id: "p2", name: "Something_Else" },
    ];
    const names = disambiguateNames(items, [{ id: "obj1", name: "Generator" }]);
    expect(names.get("p1")).toBe("Arrivals_Ready");
    expect(names.get("p2")).toBe("Something_Else");
  });

  it("qualifies duplicate names with their owning object's name", () => {
    const items: NamedElement[] = [
      { id: "p1", name: "Arrivals_Ready", objectId: "obj1" },
      { id: "p2", name: "Arrivals_Ready", objectId: "obj2" },
    ];
    const objects = [
      { id: "obj1", name: "Generator" },
      { id: "obj2", name: "Backup Generator" },
    ];
    const names = disambiguateNames(items, objects);
    expect(names.get("p1")).toBe("Arrivals_Ready (Generator)");
    expect(names.get("p2")).toBe("Arrivals_Ready (Backup Generator)");
  });

  it("falls back to the raw id when duplicates have no owning object", () => {
    const items: NamedElement[] = [
      { id: "p1", name: "Exit_Counter" },
      { id: "p2", name: "Exit_Counter" },
    ];
    const names = disambiguateNames(items, []);
    expect(names.get("p1")).toBe("p1");
    expect(names.get("p2")).toBe("p2");
  });

  it("falls back to the raw id when qualifying still collides", () => {
    // Same name, same owning object -- qualifying produces the same string
    // for both, so there is still nothing to tell them apart with.
    const items: NamedElement[] = [
      { id: "p1", name: "Exit_Counter", objectId: "obj1" },
      { id: "p2", name: "Exit_Counter", objectId: "obj1" },
    ];
    const objects = [{ id: "obj1", name: "Generator" }];
    const names = disambiguateNames(items, objects);
    expect(names.get("p1")).toBe("p1");
    expect(names.get("p2")).toBe("p2");
  });

  it("only qualifies the duplicates that actually lack an object, once qualifying resolves the rest", () => {
    const items: NamedElement[] = [
      { id: "p1", name: "Ready", objectId: "obj1" },
      { id: "p2", name: "Ready" },
    ];
    const objects = [{ id: "obj1", name: "Generator" }];
    const names = disambiguateNames(items, objects);
    expect(names.get("p1")).toBe("Ready (Generator)");
    expect(names.get("p2")).toBe("Ready");
  });
});
