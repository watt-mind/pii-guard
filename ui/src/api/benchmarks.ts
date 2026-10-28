/**
 * The benchmark index (`eval/results/index.json`, schema_version 1), shipped with the page.
 *
 * The Vite plugin in `vite.config.ts` builds it from the committed run records
 * (`pii-guard eval report --print-index`), so the Benchmarks tab works without the API (demo
 * mode, static hosting). It is not committed (LAB-1269). The index is about 7 MB, so it ships in
 * parts (`benchmarksSplit.ts`, LAB-1454): hashed static JSON files the screen fetches when it
 * needs them, the summary and run log first, then one fixture set's results at a time.
 */

import manifestModule from "virtual:pii-guard/benchmarks-manifest";
import { DETAIL_PART, joinIndex, RUNS_PART, setPart, SUMMARY_PART, type BenchmarkManifest } from "./benchmarksSplit";

export interface TypeMetrics {
  gold: number;
  recall: number | null;
  precision: number | null;
  leak: number | null;
  leak_values: number | null;
}

/** Compact metrics for one run (or pooled runs) on one language or `all`. Rates are 0-1. */
export interface Metrics {
  documents: number;
  gold: number;
  pred: number;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  f1_exact: number | null;
  macro_f1: number | null;
  leak: number | null;
  partial_leak: number | null;
  leak_values: number;
  over_masking: number | null;
  roundtrip: number | null;
  consistency: number | null;
  detect_p50_ms: number | null;
  detect_p95_ms: number | null;
  latency_pooled: boolean;
  per_type: Record<string, TypeMetrics>;
}

export type Family = "pii-guard" | "comparison";

export interface SystemInfo {
  color: string;
  shape: "circle" | "square" | "triangle" | "diamond" | "cross";
  label: string;
  short_label: string;
  family: Family;
  tool: string;
  kind: "text" | "visual";
  detectors: string[];
  models: string[];
  featured: boolean;
  default: boolean;
}

export interface FixtureSetInfo {
  origin: string;
  kind: "text" | "visual";
  languages: string[];
  documents: Record<string, number>;
  generators: string[];
}

export interface RunCost {
  usd: number | null;
  estimated: boolean;
  gpu_minutes: number | null;
  note: string | null;
  shared_with: string[];
}

export interface RunInfo {
  run_id: string;
  kind: "text" | "visual";
  date: string;
  recorded_at: string | null;
  source: "recorded" | "imported";
  title: string;
  commit: string;
  dirty: boolean;
  system: string;
  fixture_set: string;
  origin: string;
  languages: string[];
  hardware: string | null;
  cost: RunCost | null;
  notes: string[];
  imported_from: string | null;
}

export interface Snapshot {
  fixture_set: string;
  system: string;
  origin: string;
  run_ids: string[];
  dates: string[];
  commits: string[];
  languages: Record<string, Metrics>;
  all: Metrics;
}

export interface HistoryPoint {
  system: string;
  fixture_set: string;
  origin: string;
  date: string;
  commit: string;
  run_ids: string[];
  languages: Record<string, Metrics>;
  all: Metrics;
}

export interface RegionRecall {
  regions: number;
  recall_iou50: number | null;
}

export interface VisualRun {
  run_id: string;
  date: string;
  commit: string;
  system: string;
  notes: string[];
  fixture_set: string | null;
  specimens: number;
  overall: RegionRecall;
  by_region_type: Record<string, RegionRecall>;
  countries: number;
  over_masking_mean: number | null;
  cost_usd: number | null;
}

export interface BenchmarkIndex {
  schema_version: number;
  headline_set?: string;
  languages: string[];
  entity_types: string[];
  fixture_sets: Record<string, FixtureSetInfo>;
  systems: Record<string, SystemInfo>;
  featured: string[];
  runs: RunInfo[];
  history: HistoryPoint[];
  snapshots: Snapshot[];
  visual: VisualRun[];
}

/** `"all"` pools every language; otherwise a language code. */
export type LanguageFilter = "all" | string;

/** One fixture set's results: the part of the index the screen fetches when the set is picked. */
export type SetResults = Pick<BenchmarkIndex, "snapshots" | "history">;

/** The index in parts, fetched as the screen needs them. */
export interface BenchmarkSource {
  /** Everything but the per-set results: `snapshots` and `history` are empty. */
  summary(): Promise<BenchmarkIndex>;
  /** One fixture set's snapshots and history (empty lists for a set without results). */
  set(fixtureSet: string): Promise<SetResults>;
}

/** A source, or a function that resolves the whole index at once (tests, embedders). */
export type BenchmarkLoader = BenchmarkSource | (() => Promise<BenchmarkIndex>);

const EMPTY_SET: SetResults = { snapshots: [], history: [] };

function fetchJson(url: string): Promise<Record<string, unknown>> {
  return fetch(url).then((r) => {
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
    return r.json() as Promise<Record<string, unknown>>;
  });
}

/**
 * The split index served next to the page. Each part is fetched once (a failed fetch is retried
 * on the next call); the headline set's results are fetched with the summary, not after it.
 */
export function fetchedBenchmarks(
  manifest: BenchmarkManifest = manifestModule as BenchmarkManifest,
  get: (url: string) => Promise<Record<string, unknown>> = fetchJson,
  base: string = import.meta.env.BASE_URL,
): BenchmarkSource & { full(): Promise<BenchmarkIndex> } {
  const cache = new Map<string, Promise<Record<string, unknown>>>();
  const part = (name: string): Promise<Record<string, unknown>> => {
    const file = manifest.parts[name];
    if (!file) return Promise.reject(new Error(`benchmark index: no part ${name}`));
    let p = cache.get(name);
    if (!p) {
      p = get(base + file);
      p.catch(() => cache.delete(name));
      cache.set(name, p);
    }
    return p;
  };
  const set = (fixtureSet: string): Promise<SetResults> =>
    manifest.parts[setPart(fixtureSet)] ? (part(setPart(fixtureSet)) as Promise<unknown> as Promise<SetResults>) : Promise.resolve(EMPTY_SET);
  return {
    summary() {
      if (manifest.headline_set) set(manifest.headline_set).catch(() => undefined); // in parallel
      return Promise.all([part(SUMMARY_PART), part(RUNS_PART)]).then(
        ([summary, runs]) => ({ ...summary, ...runs, ...EMPTY_SET }) as unknown as BenchmarkIndex,
      );
    },
    set,
    async full() {
      const names = [SUMMARY_PART, RUNS_PART, DETAIL_PART, ...manifest.sets.map(setPart)];
      const parts = await Promise.all(names.map(part));
      return joinIndex(manifest, Object.fromEntries(names.map((n, i) => [n, parts[i]!]))) as unknown as BenchmarkIndex;
    },
  };
}

const served = fetchedBenchmarks();

/** The index the screen reads by default: fetched in parts from next to the page. */
export const benchmarkSource: BenchmarkSource = served;

/** The whole index, every part fetched and put back together. */
export const loadBenchmarks = (): Promise<BenchmarkIndex> => served.full();

/** A loader as a source: a whole-index function is called once and filtered per set. */
export function sourceOf(load: BenchmarkLoader): BenchmarkSource {
  if (typeof load !== "function") return load;
  let index: Promise<BenchmarkIndex> | undefined;
  const all = () => (index ??= load());
  return {
    summary: all,
    set: (fixtureSet) =>
      all().then((i) => ({
        snapshots: i.snapshots.filter((s) => s.fixture_set === fixtureSet),
        history: i.history.filter((h) => h.fixture_set === fixtureSet),
      })),
  };
}

/** The metrics block a language filter selects, or null when that language wasn't run. */
export function pick(block: { languages: Record<string, Metrics>; all: Metrics }, lang: LanguageFilter): Metrics | null {
  return lang === "all" ? block.all : (block.languages[lang] ?? null);
}

export function textSets(index: BenchmarkIndex): string[] {
  const head = index.headline_set;
  return Object.entries(index.fixture_sets)
    .filter(([, v]) => v.kind === "text")
    .map(([k]) => k)
    .sort((a, b) => Number(b === head) - Number(a === head) || a.localeCompare(b));
}

/** Systems with a result on `set`, in the index's order (pii-guard first, then the tools). */
export function systemsOn(index: BenchmarkIndex, set: string): string[] {
  const present = new Set(index.snapshots.filter((s) => s.fixture_set === set).map((s) => s.system));
  return Object.keys(index.systems).filter((k) => present.has(k));
}

export function snapshotsFor(index: BenchmarkIndex, set: string, systems: readonly string[]): Snapshot[] {
  const bySystem = new Map(index.snapshots.filter((s) => s.fixture_set === set).map((s) => [s.system, s]));
  return systems.map((k) => bySystem.get(k)).filter((s): s is Snapshot => s !== undefined);
}

export function formatPct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "–" : `${(v * 100).toFixed(digits)}%`;
}

export function formatMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  if (v >= 1000) return `${(v / 1000).toFixed(1)} s`;
  if (v >= 10) return `${v.toFixed(0)} ms`;
  if (v >= 1) return `${v.toFixed(1)} ms`;
  return `${v.toFixed(2)} ms`;
}

const languageNames = (() => {
  try {
    return new Intl.DisplayNames(["en"], { type: "language" });
  } catch {
    return null;
  }
})();

export function languageName(code: string): string {
  return languageNames?.of(code) ?? code;
}

export function originLabel(info: FixtureSetInfo | undefined): string {
  if (!info) return "unknown";
  if (info.origin === "generated") return info.generators.length ? `generated by ${info.generators.join(", ")}` : "model-generated";
  return info.origin;
}

export function documentCount(info: FixtureSetInfo | undefined, lang: LanguageFilter): number | null {
  if (!info) return null;
  if (lang !== "all") return info.documents[lang] ?? null;
  return Object.values(info.documents).reduce((a, b) => a + b, 0);
}

export interface HeadlineSide {
  system: string;
  label: string;
  leak: number;
  p50: number | null;
  hardware: string | null;
}

/**
 * The one-sentence result for a set and language: the lowest-leak pii-guard configuration
 * against the lowest-leak open-source tool (ties go to the faster one). Null when either side
 * has no result.
 */
/**
 * Languages of the set a snapshot was not run on. A pooled number from a system that ran on
 * one language only is not comparable with one that ran on all of them.
 */
export function missingLanguages(index: BenchmarkIndex, s: Snapshot): string[] {
  const langs = index.fixture_sets[s.fixture_set]?.languages ?? [];
  return langs.filter((l) => !s.languages[l]);
}

/** "EN only", "DE + EN only", or null when the snapshot covers every language of its set. */
export function coverageTag(index: BenchmarkIndex, s: Snapshot): string | null {
  const langs = index.fixture_sets[s.fixture_set]?.languages ?? [];
  const ran = langs.filter((l) => s.languages[l]);
  return ran.length && ran.length < langs.length ? `${ran.map((l) => l.toUpperCase()).join(" + ")} only` : null;
}

export function headline(index: BenchmarkIndex, set: string, lang: LanguageFilter): { ours: HeadlineSide; theirs: HeadlineSide } | null {
  const best = (family: Family): HeadlineSide | null => {
    let out: HeadlineSide | null = null;
    for (const s of index.snapshots) {
      const sys = index.systems[s.system];
      if (s.fixture_set !== set || sys?.family !== family) continue;
      // The pooled headline compares like with like: only systems run on every language.
      if (lang === "all" && missingLanguages(index, s).length) continue;
      const m = pick(s, lang);
      if (!m || m.leak === null) continue;
      const p50 = m.detect_p50_ms;
      const better = !out || m.leak < out.leak || (m.leak === out.leak && (p50 ?? Infinity) < (out.p50 ?? Infinity));
      if (!better) continue;
      const run = index.runs.find((r) => s.run_ids.includes(r.run_id) && r.hardware);
      out = { system: s.system, label: sys.short_label || sys.label, leak: m.leak, p50, hardware: run?.hardware ?? null };
    }
    return out;
  };
  const ours = best("pii-guard");
  const theirs = best("comparison");
  return ours && theirs ? { ours, theirs } : null;
}

/**
 * The system the gateway's fast mode runs: rules + the distilled on-device NER (the production
 * path). The index's own `default` flag still marks the rules-only baseline, which is what fast
 * mode falls back to without a NER checkpoint.
 */
export const FAST_MODE_SYSTEM = "rules+ner:xlmr-large-distilled-glimmer";

/** One spelling for detector names in labels: the index has both "ner" and "NER". */
export function tidyLabels(index: BenchmarkIndex): BenchmarkIndex {
  const tidy = (l: string) => l.replace(/\bner\b/g, "NER");
  const systems = Object.fromEntries(
    Object.entries(index.systems).map(([k, v]) => [k, { ...v, label: tidy(v.label), short_label: v.short_label && tidy(v.short_label) }]),
  );
  return { ...index, systems };
}

/**
 * A run-record note or hardware line as a reader of the Evaluation screen reads it: ticket ids
 * and internal machine notes ("shared with parallel agent runs") are maintainer context
 * (LAB-1266). The run log keeps the notes as recorded; the generator should grow a public
 * `display_note` so this stays a fallback.
 */
export function readerNote(note: string): string {
  const s = note
    .replace(/machine shared with parallel agent runs/gi, "machine shared with other jobs")
    .replace(/\s*\(LAB-\d+\)/g, "")
    .replace(/^LAB-\d+:?\s+/, "")
    .trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const VISUAL_PART: Record<string, string> = {
  tesseract: "Tesseract",
  rules: "rules",
  captions: "captions",
  eka: "EKA",
  "presidio-image": "Presidio Image Redactor",
  "efficientsam-vitt": "EfficientSAM",
  "yolos-tiny-signature": "YOLOS-tiny (signatures)",
};

function visualPart(p: string): string {
  if (p.startsWith("sam-")) return `SAM ${p.slice(4)}`;
  if (p.startsWith("yunet")) return "YuNet";
  if (p.startsWith("llm:")) return `LLM (${p.slice(4).split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ")})`;
  const tuned = p.endsWith("-tuned");
  const base = tuned ? p.slice(0, -6) : p;
  return `${VISUAL_PART[base] ?? base}${tuned ? " (tuned)" : ""}`;
}

/** "visual:sam-3.1+tesseract+rules" -> "pii-guard: SAM 3.1 + Tesseract + rules" (LAB-1266). */
export function visualRunLabel(system: string): string {
  const [kind, rest = ""] = system.includes(":") ? [system.slice(0, system.indexOf(":")), system.slice(system.indexOf(":") + 1)] : ["visual", system];
  const parts = rest.split("+").filter(Boolean).map(visualPart);
  const joined = parts.join(" + ");
  if (kind === "visual-segment") return `Segmenter: ${joined}`;
  return rest.startsWith("sam-") ? `pii-guard: ${joined}` : joined;
}
