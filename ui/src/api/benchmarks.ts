/**
 * The benchmark index (`eval/results/index.json`, schema_version 1), bundled at build time.
 *
 * `pii-guard eval report` writes a compact copy to `benchmarks.index.json` next to this
 * file, so the Benchmarks tab works without the API (demo mode, static hosting). The JSON is
 * loaded lazily, in its own chunk, the first time the tab opens.
 */

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

export type BenchmarkLoader = () => Promise<BenchmarkIndex>;

export const loadBenchmarks: BenchmarkLoader = () =>
  import("./benchmarks.index.json").then((m) => m.default as unknown as BenchmarkIndex);

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
export function headline(index: BenchmarkIndex, set: string, lang: LanguageFilter): { ours: HeadlineSide; theirs: HeadlineSide } | null {
  const best = (family: Family): HeadlineSide | null => {
    let out: HeadlineSide | null = null;
    for (const s of index.snapshots) {
      const sys = index.systems[s.system];
      if (s.fixture_set !== set || sys?.family !== family) continue;
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
