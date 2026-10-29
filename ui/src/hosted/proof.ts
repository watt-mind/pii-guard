/*
 * The landing's benchmark numbers, in one place (LAB-1466, LAB-1478). Every value is copied from
 * the generated report, docs/benchmarks.md; nothing here is rounded up or computed from a
 * different run. Fictional or public test data only.
 *
 * - Text: the `smoke` hand-written set (51 docs, de + en + hu) and the public test splits
 *   CEE-PII (451) and Nemotron-PII (300). pii-guard fast is the published NER v2.0
 *   (watt-mind/pii-guard-ner-xlmr-base) run of 2026-10-28, commit 72026a5; the comparison tools
 *   are the runs of 2026-10-27 (8944f96, cd119ae).
 * - Open models: `smoke`, "rules + <model> in place of pii-guard NER", runs of 2026-10-28
 *   (97ee284): the same rules, only the NER differs.
 * - Images: "Image masking", `specimens` (65 official specimen ID documents from 24 countries),
 *   runs `2026-10-27-image-baselines-specimens-*`.
 * - Latency: "Gateway latency", `2026-10-28-ner-concurrency-cpu-fast`, concurrency 1, no stream.
 */

export const MEASURED = "Fictional German, English and Hungarian data · measured 27–28 Oct 2026";

/** Leak and F1 (%) by set, in the order of `SETS`. */
export const SETS = ["Hand-written de + en + hu (51)", "CEE-PII (451)", "Nemotron-PII (300)"] as const;
type Row = { system: string; leak: readonly string[]; f1: readonly string[]; ours?: boolean };
export const COMPARISON: readonly Row[] = [
  { system: "PII Guard", leak: ["0.0", "0.4", "0.7"], f1: ["94.3", "82.6", "89.4"], ours: true },
  { system: "PrivAiTe", leak: ["12.7", "4.4", "4.0"], f1: ["55.2", "34.2", "80.8"] },
  { system: "Presidio", leak: ["24.3", "36.5", "12.8"], f1: ["64.9", "41.4", "66.4"] },
  { system: "LLM Guard", leak: ["45.1", "75.8", "28.8"], f1: ["53.2", "24.7", "72.9"] },
];

/** The best comparison tool on one set and metric: lowest leak, highest F1. */
export function nextBest(metric: "leak" | "f1", set: number) {
  const others = COMPARISON.filter((row) => !row.ours);
  const pick = others.reduce((best, row) => {
    const a = Number(row[metric][set]), b = Number(best[metric][set]);
    return (metric === "leak" ? a < b : a > b) ? row : best;
  });
  return `${pick.system} ${pick[metric][set]}\u00a0%`;
}

const ours = COMPARISON[0]!;
/** The hero's three numbers, each with the best of the other tools on the same set. */
export const PROOF = [
  { value: `${ours.leak[1]}\u00a0%`, label: "Values leaked, CEE-PII public set", hint: `Next best: ${nextBest("leak", 1)}` },
  { value: `${ours.leak[0]}\u00a0%`, label: "Values leaked, 51 hand-written docs", hint: `Next best: ${nextBest("leak", 0)}` },
  { value: `${ours.f1[0]}\u00a0%`, label: "Detection F1, same docs", hint: `Next best: ${nextBest("f1", 0)}` },
] as const;

export const LATENCY = { value: "~34 ms", label: "Gateway overhead per request", hint: "p50 on CPU, rules + NER, one request at a time" } as const;

/** Our NER against other open PII models, the same rules around each. Sorted by leak. */
export const OPEN_MODELS = [
  { model: "PII Guard NER v2.0", id: "watt-mind/pii-guard-ner-xlmr-base", leak: "0.0", f1: "94.3", over: "1.1", ours: true },
  { model: "bardsai multilang v1", id: "bardsai/eu-pii-anonimization-multilang", leak: "1.2", f1: "93.4", over: "10.4" },
  { model: "Wismut nym-pii", id: "Wismut/nym-pii-multilingual", leak: "4.0", f1: "90.6", over: "6.0" },
  { model: "tabularisai eu-pii-safeguard", id: "tabularisai/eu-pii-safeguard", leak: "5.8", f1: "91.9", over: "4.6" },
  { model: "Horizon-Labs pii-redactor-small", id: "Horizon-Labs/pii-redactor-small", leak: "8.7", f1: "85.4", over: "5.8" },
  { model: "Horizon-Labs pii-redactor-base", id: "Horizon-Labs/pii-redactor-base", leak: "9.2", f1: "86.3", over: "4.7" },
  { model: "bardsai multilang v3", id: "bardsai/eu-pii-anonimization-multilang-v3", leak: "9.8", f1: "89.7", over: "1.3" },
] as const;

/** Image masking on official specimen IDs: regions found (IoU ≥ 0.5), self-hosted with SAM 3.1. */
export const IMAGE_PROOF = [
  { value: "90.8\u00a0%", label: "Portraits covered", hint: "Presidio Image Redactor can’t mask portraits" },
  { value: "83.8\u00a0%", label: "Signatures covered", hint: "Self-hosted with SAM 3.1; kept visible in the hosted preview" },
  { value: "37.9\u00a0%", label: "All labelled regions", hint: "Presidio Image Redactor 13.3\u00a0%. Printed text is the weak spot: 15.0\u00a0%" },
] as const;

/**
 * Where it's weaker, from the same report: Gretel finance (PII Guard fast vs Presidio, 27–28 Oct),
 * over-masking on CEE-PII, and MAPA EUR-Lex (21 EU languages, 42 docs).
 */
export const WEAKER = { gretel: "19.0", gretelPresidio: "18.8", ceeOverMasking: "26.4", mapaLeak: "8.5" } as const;

/** Same placeholder in text and image: `visual-placeholders`, fuzzy matching, run of 2026-10-27 (recall; precision 100.0 %). */
export const VISUAL_PLACEHOLDERS = { docs: 24, recall: "98.0" } as const;
