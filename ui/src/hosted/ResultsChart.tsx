import type { Metrics, SystemInfo } from "../api/benchmarks";
import { LeakLatencyChart, type ScatterPoint } from "../screens/BenchmarksCharts";
import { COMPARISON, SMOKE_DOCS } from "./proof";

/*
 * The landing's comparison chart (LAB-1466), loaded on demand: the console's own leak-vs-latency
 * chart (Evaluation), fed with the hand-written `smoke` column of `COMPARISON` (leak, F1 and
 * detection p50, all checked against docs/benchmarks.md by proof.source.test.ts) rather than the
 * full benchmark index, so the landing doesn't download the index (LAB-1656: no numbers typed
 * here). The marker colour and shape are the systems' registry entries
 * (docs/benchmarks/colours.json), as on the Evaluation screen.
 */

const STYLE: Record<string, { label: string; color: string; shape: SystemInfo["shape"] }> = {
  "PII Guard": { label: "PII Guard fast (rules + our open NER)", color: "#CC79A7", shape: "circle" },
  PrivAiTe: { label: "PrivAiTe", color: "#595959", shape: "diamond" },
  Presidio: { label: "Presidio", color: "#595959", shape: "square" },
  "LLM Guard": { label: "LLM Guard", color: "#595959", shape: "triangle" },
};

const info = (key: string, system: string, ours: boolean): SystemInfo => {
  const style = STYLE[system]!;
  const family: SystemInfo["family"] = ours ? "pii-guard" : "comparison";
  return {
    color: style.color, shape: style.shape, label: style.label, short_label: system, family, role: ours ? "own" : "tool", tool: key, kind: "text",
    detectors: [], models: [], featured: true, default: ours,
  };
};

const metrics = (leak: number, f1: number, p50: number): Metrics => ({
  documents: SMOKE_DOCS, gold: 0, pred: 0, precision: null, recall: null, f1, f1_exact: null, macro_f1: null, leak, partial_leak: null, leak_values: 0,
  over_masking: null, roundtrip: null, consistency: null, detect_p50_ms: p50, detect_p95_ms: null, latency_pooled: false, per_type: {},
});

/** `COMPARISON`'s smoke column as chart points; percentages become fractions as the index stores them. */
const SMOKE_POINTS: ScatterPoint[] = COMPARISON.map((row) => ({
  key: row.key,
  info: info(row.key, row.system, Boolean(row.ours)),
  metrics: metrics(Number(row.leak[0]) / 100, Number(row.f1[0]) / 100, row.p50),
}));

/** The chart draws its own legend (each system with its leak and time). */
export default function ResultsChart() {
  return <LeakLatencyChart points={SMOKE_POINTS} />;
}
