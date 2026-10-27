import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { BenchmarkIndex, BenchmarkLoader } from "../api/benchmarks";
import bundled from "../api/benchmarks.index.json";
import type { HttpGuardClient } from "../api/http";
import { UnreachableError } from "../api/http";
import { createMockClient } from "../api/mock";

const INDEX = bundled as unknown as BenchmarkIndex;
const load = vi.fn(() => Promise.resolve(INDEX));

function offlineApi(): HttpGuardClient {
  const down = () => Promise.reject(new UnreachableError());
  return { health: down, analyze: down, mask: down, unmask: down, maskImage: down };
}

async function openBenchmarks(loader: BenchmarkLoader = load) {
  const user = userEvent.setup();
  render(<App api={offlineApi()} mock={createMockClient()} loadBenchmarks={loader} />);
  await user.click(screen.getByRole("tab", { name: /benchmarks/i }));
  const panel = screen.getByRole("tabpanel", { name: /benchmarks/i });
  return { user, panel };
}

function resultsTable(panel: HTMLElement) {
  const section = within(panel).getByRole("region", { name: "Results" });
  return within(section).getByRole("table");
}

const nameOf = (h: HTMLElement | null) => h?.textContent?.replace(/fast mode$/, "").trim();

function rowNames(table: HTMLElement) {
  return within(table).getAllByRole("rowheader").map(nameOf);
}

function cell(table: HTMLElement, system: string, column: string): string {
  const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent?.replace(/[▲▼]/g, "").trim());
  const row = within(table)
    .getAllByRole("row")
    .find((r) => nameOf(within(r).queryByRole("rowheader")) === system);
  if (!row) throw new Error(`no row ${system}`);
  const cells = [within(row).getByRole("rowheader"), ...within(row).getAllByRole("cell")];
  return cells[headers.indexOf(column)]!.textContent!.trim();
}

const snap = (set: string, system: string) => INDEX.snapshots.find((s) => s.fixture_set === set && s.system === system)!;
const pct = (v: number | null) => `${((v ?? 0) * 100).toFixed(1)}%`;

beforeEach(() => {
  localStorage.clear();
  load.mockClear();
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
});

describe("Benchmarks screen", () => {
  it("is the fourth tab, reachable with the arrow keys, and loads lazily", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} loadBenchmarks={load} />);
    expect(load).not.toHaveBeenCalled();
    await user.click(screen.getByRole("tab", { name: /images/i }));
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: /benchmarks/i })).toHaveAttribute("aria-selected", "true");
    expect(load).toHaveBeenCalledTimes(1);
    const panel = screen.getByRole("tabpanel", { name: /benchmarks/i });
    expect(await within(panel).findByRole("region", { name: "Results" })).toBeInTheDocument();
  });

  it("works in demo mode without the API and says the data is bundled", async () => {
    const { panel } = await openBenchmarks();
    expect(await screen.findByText(/Benchmarks are bundled with this page/)).toBeInTheDocument();
    await within(panel).findByRole("region", { name: "Results" });
    expect(within(panel).getByText(String(INDEX.runs.length))).toBeInTheDocument();
  });

  it("opens on the headline set with the featured systems, safest first", async () => {
    const { panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    const table = resultsTable(panel);
    const set = INDEX.headline_set!;
    expect(within(panel).getByRole("radio", { name: new RegExp(`^${set}`) })).toBeChecked();
    const featured = INDEX.featured.filter((k) => INDEX.snapshots.some((s) => s.fixture_set === set && s.system === k));
    expect(rowNames(table)).toHaveLength(featured.length);
    const leaks = featured.map((k) => snap(set, k).all.leak ?? 1).sort((a, b) => a - b);
    expect(cell(table, rowNames(table)[0]!, "Leak")).toBe(pct(leaks[0]!));
    expect(cell(table, "rules", "Leak")).toBe(pct(snap(set, "rules").all.leak));
    expect(within(table).getByRole("columnheader", { name: "Leak" })).toHaveAttribute("aria-sort", "ascending");
  });

  it("filters by language and by fixture set, warning on generated sets", async () => {
    const { user, panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    await user.click(within(panel).getByRole("radio", { name: "Hungarian" }));
    expect(cell(resultsTable(panel), "rules", "Leak")).toBe(pct(snap("smoke", "rules").languages.hu!.leak));
    expect(within(panel).queryByRole("note")).not.toBeInTheDocument();

    await user.click(within(panel).getByRole("radio", { name: /^synth-sample/ }));
    expect(within(panel).getByRole("note")).toHaveTextContent(/flatters\s+Muse-based detection/);
    expect(cell(resultsTable(panel), "rules", "Leak")).toBe(pct(snap("synth-sample", "rules").languages.hu!.leak));
  });

  it("picks systems, sorts columns, and asks for a system when none is left", async () => {
    const { user, panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    await user.click(within(panel).getByRole("button", { name: "All" }));
    const all = INDEX.snapshots.filter((s) => s.fixture_set === "smoke").length;
    expect(rowNames(resultsTable(panel))).toHaveLength(all);

    await user.click(within(panel).getByRole("button", { name: "F1" }));
    const table = resultsTable(panel);
    expect(within(table).getByRole("columnheader", { name: "F1" })).toHaveAttribute("aria-sort", "descending");
    const f1s = rowNames(table).map((n) => parseFloat(cell(table, n!, "F1")));
    expect(f1s).toEqual([...f1s].sort((a, b) => b - a));

    for (const box of within(panel).getAllByRole("checkbox")) {
      if ((box as HTMLInputElement).checked) await user.click(box);
    }
    expect(within(panel).getByText("Pick at least one system to compare.")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Featured" }));
    expect(within(panel).getByRole("region", { name: "Results" })).toBeInTheDocument();
  });

  it("keeps its filters when switching tabs", async () => {
    const { user, panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    await user.click(within(panel).getByRole("radio", { name: "English" }));
    await user.click(screen.getByRole("tab", { name: /mask/i }));
    await user.click(screen.getByRole("tab", { name: /benchmarks/i }));
    expect(within(panel).getByRole("radio", { name: "English" })).toBeChecked();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("draws the charts with text alternatives and lists every run", async () => {
    const { user, panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    expect(within(panel).getByRole("img", { name: /Leak rate against detection latency/ })).toBeInTheDocument();
    expect(within(panel).getByRole("img", { name: /over time/ })).toBeInTheDocument();
    expect(within(within(panel).getByRole("region", { name: "Recall per entity type" })).getByRole("table")).toBeInTheDocument();
    expect(within(panel).getByRole("region", { name: "Image masking" })).toBeInTheDocument();
    await user.click(within(panel).getByText(/Run log/));
    expect(within(panel).getAllByRole("listitem").length).toBeGreaterThanOrEqual(INDEX.runs.length);
  });

  it("says so when the results can't be loaded", async () => {
    const { panel } = await openBenchmarks(() => Promise.reject(new Error("chunk failed")));
    expect(await within(panel).findByRole("alert")).toHaveTextContent(/could not be loaded.*chunk failed/);
  });
});

describe("Benchmarks screen, critique round", () => {
  it("reverses a sort on a second click and sorts every numeric column", async () => {
    const { user, panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    const leakHeader = () => within(resultsTable(panel)).getByRole("columnheader", { name: "Leak" });
    await user.click(within(panel).getByRole("button", { name: "Leak" }));
    expect(leakHeader()).toHaveAttribute("aria-sort", "descending");
    await user.click(within(panel).getByRole("button", { name: "Recall" }));
    expect(within(resultsTable(panel)).getByRole("columnheader", { name: "Recall" })).toHaveAttribute("aria-sort", "descending");
  });

  it("shows where runs ran and their caveats, open by default on generated sets", async () => {
    const { user, panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    const caveats = () => within(panel).getByText("Where these ran, and caveats").closest("details")!;
    expect(caveats()).not.toHaveAttribute("open");
    await user.click(within(panel).getByRole("radio", { name: /^synth-dev/ }));
    await user.click(within(panel).getByRole("button", { name: "All" }));
    expect(caveats()).toHaveAttribute("open");
    expect(caveats()).toHaveTextContent(/trained on the seed-7 synthetic split/);
    expect(within(panel).getByText(/open-source tools weren’t run on this set/)).toBeInTheDocument();
  });
});
