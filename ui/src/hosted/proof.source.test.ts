import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { COMPARISON, HARNESS, IMAGE_LIMITS, IMAGE_PROOF, LATENCY, OPEN_MODELS, RUNS, VISUAL_PLACEHOLDERS, WEAKER } from "./proof";

/*
 * Every landing number against its source (LAB-1499): docs/benchmarks.md (generated from the
 * committed run records), the 2026-10-29 harness matrix and the run records themselves. A
 * regenerated report that moves a figure fails here instead of leaving the landing stale.
 */

// Vitest runs from ui/.
const ROOT = join(process.cwd(), "..");
const report = readFileSync(join(ROOT, "docs/benchmarks.md"), "utf8");
const harness = readFileSync(join(ROOT, "docs/integrations/harness-matrix-2026-10-29.md"), "utf8");

/** The rows of one `### \`set\`` section's first (results) table. */
function section(set: string): string[] {
  const start = report.indexOf(`### \`${set}\`\n`);
  expect(start, `section ${set}`).toBeGreaterThanOrEqual(0);
  const end = report.indexOf("\n### ", start + 5);
  return report.slice(start, end < 0 ? undefined : end).split("\n").filter((line) => line.startsWith("| "));
}

/** The cells of the first row in `rows` whose system cell starts with `system`. */
function cells(rows: string[], system: string): string[] {
  const row = rows.find((line) => line.slice(2).startsWith(system));
  expect(row, `row ${system}`).toBeDefined();
  return row!.split("|").slice(1, -1).map((cell) => cell.trim());
}

const OURS = "pii-guard fast, NER v2.0 (published";
const SYSTEMS: Record<string, string> = { "PII Guard": OURS, PrivAiTe: "PrivAiTe", Presidio: "Presidio", "LLM Guard": "LLM Guard" };
const SET_IDS = ["smoke", "cee-pii", "nemotron-pii"];
// Result table columns: System, Docs, Precision, Recall, F1, Leak, …
const F1 = 4, LEAK = 5, OVER = 7;

describe("landing numbers match their sources (LAB-1499)", () => {
  it("text comparison: leak and F1 for each tool on each set", () => {
    for (const row of COMPARISON) {
      SET_IDS.forEach((set, i) => {
        const c = cells(section(set), SYSTEMS[row.system]!);
        expect([c[LEAK], c[F1]], `${row.system} on ${set}`).toEqual([`${row.leak[i]}%`, `${row.f1[i]}%`]);
      });
    }
  });

  it("open NER models with the same rules", () => {
    const rows = section("smoke");
    for (const m of OPEN_MODELS) {
      const c = "ours" in m ? cells(rows, OURS) : cells(rows, `rules + ${m.id.includes("bardsai/eu-pii-anonimization-multilang") && !m.id.endsWith("v3") ? "the public fallback bardsai/eu-pii-anonimization-multilang v1" : `${m.id} in place of pii-guard NER`}`);
      expect([c[LEAK], c[F1], c[OVER]], m.model).toEqual([`${m.leak}%`, `${m.f1}%`, `${m.over}%`]);
    }
  });

  it("where it's weaker", () => {
    expect(cells(section("gretel-finance"), OURS)[LEAK]).toBe(`${WEAKER.gretel}%`);
    expect(cells(section("gretel-finance"), "Presidio")[LEAK]).toBe(`${WEAKER.gretelPresidio}%`);
    expect(cells(section("cee-pii"), OURS)[OVER]).toBe(`${WEAKER.ceeOverMasking}%`);
    expect(cells(section("mapa-eur-lex"), OURS)[LEAK]).toBe(`${WEAKER.mapaLeak}%`);
  });

  it("images: same placeholder, portraits, signatures and the weak spots", () => {
    const fuzzy = cells(section("visual-placeholders"), "pii-guard image placeholders (fuzzy matching)");
    expect([fuzzy[1], fuzzy[2], fuzzy[3]]).toEqual([String(VISUAL_PLACEHOLDERS.docs), "100.0%", `${VISUAL_PLACEHOLDERS.recall}%`]);
    const row = report.split("\n").find((line) => line.startsWith("| `2026-10-27-image-baselines-specimens-pii-guard-rules` "))!;
    const c = row.split("|").slice(1, -1).map((cell) => cell.trim());
    // Run, Set, Images, Countries, portrait, signature, mrz, text, All regions
    expect([c[2], c[3]]).toEqual([String(IMAGE_LIMITS.ids), String(IMAGE_LIMITS.countries)]);
    expect([`${c[4]}`, `${c[5]}`]).toEqual([IMAGE_PROOF[1].value.replace(" ", ""), IMAGE_PROOF[2].value.replace(" ", "")]);
    expect([c[7], c[8]]).toEqual([`${IMAGE_LIMITS.text}%`, `${IMAGE_LIMITS.all}%`]);
    const presidio = report.split("\n").find((line) => line.startsWith("| `2026-10-27-image-baselines-specimens-presidio-image` "))!;
    expect(presidio.split("|").slice(1, -1).map((cell) => cell.trim())[8]).toBe(`${IMAGE_LIMITS.presidio}%`);
  });

  it("gateway latency on CPU, one request at a time", () => {
    const row = report.split("\n").find((line) => line.includes("`2026-10-28-ner-concurrency-cpu-fast`") && /\| 1 \| no \|/.test(line))!;
    expect(row).toContain(`| ${LATENCY.value.replace("~", "")} |`);
  });

  it("real coding agents: requests, leaks and refusals", () => {
    expect(harness).toContain(`${HARNESS.requests} agent requests through the gateway`);
    expect(harness).toContain(`→ ${HARNESS.refused}.**`);
    for (const agent of HARNESS.agents) expect(harness).toContain(agent);
    expect(harness.match(/pass \(0 of 9, \d+ requests\)/g)).toHaveLength(HARNESS.agents.length);
  });

  it("committed run records: at least the floor the page states", () => {
    const runs = readdirSync(join(ROOT, "eval/results/runs")).filter((f) => f.endsWith(".json"));
    expect(runs.length).toBeGreaterThanOrEqual(RUNS.floor);
  });
});
