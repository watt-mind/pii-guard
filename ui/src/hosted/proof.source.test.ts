import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { AGENT_TRAFFIC, COMPARISON, HARD_CASES, HARNESS, IMAGE_LIMITS, IMAGE_PROOF, INFLECTION, LATENCY, OPEN_MODELS, POLISH, RUNS, SMOKE_BY_LANGUAGE, SMOKE_DOCS, VISUAL_PLACEHOLDERS, WEAKER } from "./proof";

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

/**
 * The cells of the first row in `rows` whose system cell starts with `system`, skipping `†`
 * rows: those are older systems not run on every language of the current fixtures (LAB-1302).
 * `partial` takes a `†` row instead, for figures the landing labels as not like-for-like.
 */
function cells(rows: string[], system: string, partial = false): string[] {
  const row = rows.find((line) => line.slice(2).startsWith(system) && line.split("|")[1]!.includes("†") === partial);
  expect(row, `row ${system}`).toBeDefined();
  return row!.split("|").slice(1, -1).map((cell) => cell.trim());
}

/** The rows of the table in one set's section whose header row contains `column`. */
function tableWith(set: string, column: string): { header: string[]; rows: string[] } {
  const start = report.indexOf(`### \`${set}\`\n`);
  const end = report.indexOf("\n### ", start + 5);
  const lines = report.slice(start, end < 0 ? undefined : end).split("\n");
  const at = lines.findIndex((line) => line.startsWith("| System") && line.includes(column));
  expect(at, `${set}: table with ${column}`).toBeGreaterThanOrEqual(0);
  const rows: string[] = [];
  for (let i = at + 2; i < lines.length && lines[i]!.startsWith("| "); i++) rows.push(lines[i]!);
  return { header: lines[at]!.split("|").slice(1, -1).map((c) => c.trim()), rows };
}

// The fast-mode row label in the report: the run records' system.label of FAST_MODE_SYSTEM (changes with the NER pin).
const OURS = "pii-guard fast, NER v4.2 (published";
const SYSTEMS: Record<string, string> = { "PII Guard": OURS, PrivAiTe: "PrivAiTe", Presidio: "Presidio", "LLM Guard": "LLM Guard" };
const SET_IDS = ["smoke", "cee-pii", "nemotron-pii"];
// Result table columns: System, Docs, Precision, Recall, F1, Leak, Partial leak, Over-masking, Round trip, Detect p50
const DOCS = 1, F1 = 4, LEAK = 5, OVER = 7, P50 = 9;

describe("landing numbers match their sources (LAB-1499)", () => {
  it("text comparison: leak and F1 for each tool on each set", () => {
    for (const row of COMPARISON) {
      SET_IDS.forEach((set, i) => {
        const c = cells(section(set), SYSTEMS[row.system]!);
        expect([c[LEAK], c[F1]], `${row.system} on ${set}`).toEqual([`${row.leak[i]}%`, `${row.f1[i]}%`]);
      });
    }
  });

  it("the landing's leak-vs-latency chart: smoke documents and detection p50 for each tool", () => {
    for (const row of COMPARISON) {
      const c = cells(section("smoke"), SYSTEMS[row.system]!);
      expect(c[DOCS], row.system).toBe(String(SMOKE_DOCS));
      expect(c[P50]!.replaceAll("*", ""), row.system).toBe(`${row.p50} ms`);
    }
  });

  it("agent traffic: leak and over-masking, partial rows marked as such", () => {
    for (const row of AGENT_TRAFFIC) {
      const c = cells(section("agent-traffic"), SYSTEMS[row.system]!, Boolean(row.partial));
      expect([c[DOCS], c[LEAK], c[OVER]], row.system).toEqual([String(row.docs), `${row.leak}%`, `${row.over}%`]);
    }
  });

  it("zero leaks per language on the hand-written set", () => {
    const { header, rows } = tableWith("smoke", "de leak");
    const c = cells(rows, OURS);
    for (const [lang, leak] of Object.entries(SMOKE_BY_LANGUAGE)) expect(c[header.indexOf(`${lang} leak`)], lang).toBe(`${leak}%`);
    expect(Object.keys(SMOKE_BY_LANGUAGE).sort()).toEqual(header.filter((h) => h.endsWith(" leak")).map((h) => h.split(" ")[0]).sort());
  });

  it("hard cases: valid and mistyped numbers on CEE-PII", () => {
    const { header, rows } = tableWith("cee-pii", "Leak, valid numbers");
    const valid = header.indexOf("Leak, valid numbers"), invalid = header.indexOf("Leak, invalid numbers");
    for (const row of HARD_CASES.rows) {
      const c = cells(rows, SYSTEMS[row.system]!);
      expect([c[valid]!.split(" ")[0], c[invalid]!.split(" ")[0]], row.system).toEqual([`${row.valid}%`, `${row.invalid}%`]);
    }
  });

  it("Hungarian inflection and Polish with its language pack", () => {
    const infl = section("inflection");
    expect([cells(infl, OURS)[DOCS], cells(infl, OURS)[LEAK], cells(infl, "**pii-guard rules**")[LEAK]]).toEqual([String(INFLECTION.docs), `${INFLECTION.leak}%`, `${INFLECTION.rulesLeak}%`]);
    const pl = section("pl-pii-bench");
    expect([cells(pl, OURS)[DOCS], cells(pl, OURS)[LEAK], cells(pl, "**pii-guard rules**")[LEAK]]).toEqual([String(POLISH.docs), `${POLISH.leak}%`, `${POLISH.rulesLeak}%`]);
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
    const v20 = "pii-guard fast, NER v2.0 (selection-only re-score, LAB-1625)";
    expect([cells(section("cee-pii"), OURS)[LEAK], cells(section("cee-pii"), v20)[LEAK], cells(section("pl-pii-bench"), v20)[LEAK]]).toEqual([`${WEAKER.cee}%`, `${WEAKER.ceeV20}%`, `${WEAKER.polishV20}%`]);
    // MAPA is report-only: no MAPA figure on the landing (LAB-1656).
    expect(Object.keys(WEAKER).some((k) => k.toLowerCase().includes("mapa"))).toBe(false);
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

  it("NER latency on CPU: the README's measurement, rounded as the README rounds it", () => {
    const m = JSON.parse(readFileSync(join(ROOT, "eval/results/2026-10-30-lab-1625-ner-v42/latency-cpu-local.json"), "utf8")).results["v42-b3"];
    expect([LATENCY.value, LATENCY.p95]).toEqual([`${Math.round(m.p50_ms)} ms`, `${Math.round(m.p95_ms)} ms`]);
    const readme = readFileSync(join(ROOT, "README.md"), "utf8");
    expect(readme).toContain(`The NER takes ${LATENCY.value} per message on a laptop CPU (p50; p95 ${LATENCY.p95}`);
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
