import type { Metrics, SystemInfo } from "../api/benchmarks";
import { LeakLatencyChart, type ScatterPoint } from "../screens/BenchmarksCharts";

/*
 * The landing's comparison chart (LAB-1466), loaded on demand: the console's own leak-vs-latency
 * chart (Evaluation), fed with the hand-written `smoke` rows of docs/benchmarks.md rather than the
 * full benchmark index, so the landing doesn't download the index. Every value is copied from the
 * generated report: pii-guard fast is the published NER v2.0 run of 2026-10-28 (commit 72026a5),
 * the comparison tools are the runs of 2026-10-27 (commit 8944f96). The marker colour and shape
 * are the systems' registry entries (docs/benchmarks/colours.json), as on the Evaluation screen.
 */

const system = (key: string, label: string, short: string, family: SystemInfo["family"], color: string, shape: SystemInfo["shape"], def = false): SystemInfo => ({
  color, shape, label, short_label: short, family, tool: key, kind: "text", detectors: [], models: [], featured: true, default: def,
});
const metrics = (leak: number, f1: number, p50: number): Metrics => ({
  documents: 51, gold: 0, pred: 0, precision: null, recall: null, f1, f1_exact: null, macro_f1: null, leak, partial_leak: null, leak_values: 0,
  over_masking: null, roundtrip: null, consistency: null, detect_p50_ms: p50, detect_p95_ms: null, latency_pooled: false, per_type: {},
});

const SMOKE_POINTS: ScatterPoint[] = [
  { key: "rules+ner:xlmr-base-v2-hn", info: system("rules+ner:xlmr-base-v2-hn", "PII Guard fast (rules + our open NER)", "PII Guard", "pii-guard", "#CC79A7", "circle", true), metrics: metrics(0.0, 0.943, 39) },
  { key: "privaite", info: system("privaite", "PrivAiTe", "PrivAiTe", "comparison", "#595959", "diamond"), metrics: metrics(0.127, 0.552, 170) },
  { key: "presidio", info: system("presidio", "Presidio", "Presidio", "comparison", "#595959", "square"), metrics: metrics(0.243, 0.649, 88) },
  { key: "llm-guard", info: system("llm-guard", "LLM Guard", "LLM Guard", "comparison", "#595959", "triangle"), metrics: metrics(0.451, 0.532, 110) },
];

/** The chart draws its own legend (each system with its leak and time). */
export default function ResultsChart() {
  return <LeakLatencyChart points={SMOKE_POINTS} />;
}
