import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { FAST_MODE_SYSTEM, groupOf, type BenchmarkIndex, type BenchmarkLoader } from "../api/benchmarks";
import bundled from "virtual:pii-guard/benchmarks-index";
import type { HttpGuardClient } from "../api/http";
import { UnreachableError } from "../api/http";
import { createMockClient } from "../api/mock";

const INDEX = bundled as BenchmarkIndex;
const load = vi.fn(() => Promise.resolve(INDEX));

function offlineApi(): HttpGuardClient {
  const down = () => Promise.reject(new UnreachableError());
  return { health: down, analyze: down, mask: down, unmask: down, maskImage: down };
}

async function openBenchmarks(loader: BenchmarkLoader = load) {
  const user = userEvent.setup();
  render(<App api={offlineApi()} mock={createMockClient()} loadBenchmarks={loader} />);
  await user.click(screen.getByRole("link", { name: /evaluation/i }));
  const panel = screen.getByRole("region", { name: "Evaluation" });
  return { user, panel };
}

function resultsTable(panel: HTMLElement) {
  const section = within(panel).getByRole("region", { name: "Results" });
  return within(section).getByRole("table");
}

const nameOf = (h: HTMLElement | null) => h?.textContent?.replace(/ ?fast mode$/, "").replace(/ +([A-Z]{2}( \+ [A-Z]{2})* only)$/, "$1").trim();

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
  history.replaceState(null, "", "#playground/text");
  load.mockClear();
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
});

describe("Benchmarks screen", () => {
  it("opens as Evaluation from the sidebar, and loads lazily", async () => {
    const user = userEvent.setup();
    render(<App api={offlineApi()} mock={createMockClient()} loadBenchmarks={load} />);
    expect(load).not.toHaveBeenCalled();
    await user.click(screen.getByRole("link", { name: /evaluation/i }));
    expect(screen.getByRole("link", { name: /evaluation/i })).toHaveAttribute("aria-current", "page");
    expect(location.hash).toBe("#evaluation");
    expect(load).toHaveBeenCalledTimes(1);
    const panel = screen.getByRole("region", { name: "Evaluation" });
    expect(await within(panel).findByRole("region", { name: "Results" })).toBeInTheDocument();
  });

  it("works in demo mode without the API and says the data is bundled", async () => {
    const { panel } = await openBenchmarks();
    expect(await screen.findByText(/Benchmarks are bundled with this page/)).toBeInTheDocument();
    await within(panel).findByRole("region", { name: "Results" });
    expect(within(panel).getByText(new RegExp(`^${INDEX.runs.length} runs · `))).toBeInTheDocument();
  });

  it("opens on the headline set with the featured systems, safest first", async () => {
    const { panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    const table = resultsTable(panel);
    const set = INDEX.headline_set!;
    expect(within(panel).getByRole("combobox", { name: "Fixture set" })).toHaveValue(set);
    const featured = INDEX.featured.filter((k) => INDEX.snapshots.some((s) => s.fixture_set === set && s.system === k));
    expect(rowNames(table)).toHaveLength(featured.length);
    // Pooled, systems run on every language come first, safest first.
    const full = featured.filter((k) => INDEX.fixture_sets[set]!.languages.every((l) => snap(set, k).languages[l]));
    const leaks = full.map((k) => snap(set, k).all.leak ?? 1).sort((a, b) => a - b);
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

    await user.selectOptions(within(panel).getByRole("combobox", { name: "Fixture set" }), "synth-sample");
    expect(within(panel).getByRole("note")).toHaveTextContent(/flatters\s+Muse-based detection/);
    expect(cell(resultsTable(panel), "rules", "Leak")).toBe(pct(snap("synth-sample", "rules").languages.hu!.leak));
  });

  it("picks systems, sorts columns, and asks for a system when none is left", async () => {
    const { user, panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    await user.click(within(panel).getByRole("button", { name: "Select all" }));
    const all = INDEX.snapshots.filter((s) => s.fixture_set === "smoke").length;
    expect(rowNames(resultsTable(panel))).toHaveLength(all);

    await user.click(within(panel).getByRole("button", { name: "F1" }));
    const table = resultsTable(panel);
    expect(within(table).getByRole("columnheader", { name: "F1" })).toHaveAttribute("aria-sort", "descending");
    // Pooled, systems run on only some languages ("EN only") are listed after the rest.
    const names = rowNames(table);
    const partial = names.findIndex((n) => / only$/.test(n!));
    if (partial >= 0) expect(names.slice(partial).every((n) => / only$/.test(n!))).toBe(true);
    const f1s = names.filter((n) => !/ only$/.test(n!)).map((n) => parseFloat(cell(table, n!, "F1")));
    expect(f1s).toEqual([...f1s].sort((a, b) => b - a));

    for (const box of within(panel).getAllByRole("checkbox")) {
      if ((box as HTMLInputElement).checked) await user.click(box);
    }
    expect(within(panel).getByText("Pick at least one system to compare.")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Select featured" }));
    expect(within(panel).getByRole("region", { name: "Results" })).toBeInTheDocument();
    // Clicks every system checkbox: with the 13 NER v2 candidates (LAB-1150) this takes ~2 s
    // locally and over 5 s on CI runners.
  }, 20_000);

  it("keeps its filters when switching sections", async () => {
    const { user, panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    await user.click(within(panel).getByRole("radio", { name: "English" }));
    await user.click(screen.getByRole("link", { name: /playground/i }));
    await user.click(screen.getByRole("link", { name: /evaluation/i }));
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
    // The latest runs first; the rest on request (LAB-1531).
    await user.click(within(panel).getByRole("button", { name: `Show all ${INDEX.runs.length} runs` }));
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
    await user.selectOptions(within(panel).getByRole("combobox", { name: "Fixture set" }), "synth-dev");
    await user.click(within(panel).getByRole("button", { name: "Select all" }));
    expect(caveats()).toHaveAttribute("open");
    expect(caveats()).toHaveTextContent(/trained on the seed-7 synthetic split/);
    expect(within(panel).getByText(/open-source tools weren’t run on this set/)).toBeInTheDocument();
  });
});

describe("Benchmarks screen, round E1 (LAB-1493)", () => {
  it("leads with fast mode against the best open-source tool, numbers from the index", async () => {
    const { panel } = await openBenchmarks();
    const head = await within(panel).findByTestId("bench-headline");
    const set = INDEX.headline_set!;
    const fast = snap(set, FAST_MODE_SYSTEM);
    const tools = INDEX.snapshots.filter((s) => s.fixture_set === set && INDEX.systems[s.system]?.family === "comparison");
    const best = Math.min(...tools.map((s) => s.all.leak ?? 1));
    expect(head).toHaveTextContent(new RegExp(`fast mode lets ${pct(fast.all.leak).replace(".", "\\.")} of personal values through`));
    expect(head).toHaveTextContent(new RegExp(`lets ${pct(best).replace(".", "\\.")} through`));
    expect(head).toHaveTextContent(/hand-written German, English and Hungarian documents/);
    expect(head).not.toHaveTextContent(/pii-guard/);
    // The production row is marked in the table.
    const row = within(resultsTable(panel)).getAllByRole("row").find((r) => within(r).queryByText("fast mode"));
    expect(row).toBeDefined();
  });

  it("shows other organisations' models apart from PII Guard's own", async () => {
    const { user, panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    expect(within(panel).queryByText("Other open models")).not.toBeInTheDocument(); // collapsed: featured only
    await user.click(within(panel).getByRole("button", { name: /^More systems/ }));
    expect(within(panel).getByText("Other open models")).toBeInTheDocument();
    for (const [, info] of Object.entries(INDEX.systems)) {
      if (/^(rules \+ )?(bardsai|tabularisai|Horizon-Labs|Wismut)\//.test(info.short_label)) expect(groupOf(info)).toBe("other-model");
    }
    expect(groupOf(INDEX.systems[FAST_MODE_SYSTEM])).toBe("ours");
  });

  it("never calls a mixed-origin set hand-written", async () => {
    const { panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    const mixed = Object.entries(INDEX.fixture_sets).find(([, v]) => v.kind === "text" && v.origin === "mixed");
    if (!mixed) return;
    const group = within(panel).getByRole("group", { name: "Mixed origin" });
    expect(within(group).getByRole("option", { name: new RegExp(`^${mixed[0]} ·`) })).toBeInTheDocument();
  });
});

describe("Benchmarks screen, round E2 (LAB-1531)", () => {
  it("compares fast mode with the best open-source tool on every set both ran on, and a row picks its set", async () => {
    const { user, panel } = await openBenchmarks();
    const section = await within(panel).findByRole("region", { name: "Every test set, at a glance" });
    const fastSets = new Set(INDEX.snapshots.filter((s) => s.system === FAST_MODE_SYSTEM).map((s) => s.fixture_set));
    const toolSets = new Set(INDEX.snapshots.filter((s) => INDEX.systems[s.system]?.family === "comparison").map((s) => s.fixture_set));
    const expected = Object.keys(INDEX.fixture_sets).filter((k) => fastSets.has(k) && toolSets.has(k) && INDEX.fixture_sets[k]!.origin !== "generated");
    const table = within(section).getByRole("table");
    const names = within(table).getAllByRole("rowheader").map((h) => within(h).getByRole("button").textContent);
    expect(names.sort()).toEqual([...expected].sort());
    // Numbers come from the index: fast mode's pooled leak on a public set.
    const other = expected.find((k) => k !== INDEX.headline_set)!;
    const row = within(table).getAllByRole("row").find((r) => within(r).queryByRole("button", { name: other }))!;
    expect(row).toHaveTextContent(pct(snap(other, FAST_MODE_SYSTEM).all.leak));
    await user.click(within(row).getByRole("button", { name: other }));
    expect(within(panel).getByRole("combobox", { name: "Fixture set" })).toHaveValue(other);
  });

  it("names the production system briefly and marks it in the chart", async () => {
    const { panel } = await openBenchmarks();
    await within(panel).findByRole("region", { name: "Results" });
    expect(rowNames(resultsTable(panel))).toContain("rules + NER v2.0");
    const chart = within(panel).getByRole("region", { name: "Leak rate vs latency" });
    const legend = within(chart).getAllByRole("listitem").find((li) => /^rules \+ NER v2\.0/.test(li.textContent ?? ""));
    expect(legend).toHaveTextContent(/fast mode/);
    expect(within(chart).getByText(/p50 to p95/)).toBeInTheDocument();
  });
});
