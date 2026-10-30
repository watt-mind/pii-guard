import { FAST_MODE_SYSTEM } from "../api/benchmarks";

/*
 * The landing's benchmark numbers, in one place (LAB-1466, LAB-1478, LAB-1656). Every value is
 * copied from the generated report, docs/benchmarks.md, which is built from the run records in
 * eval/results/runs/ (the same source as the README's results block); nothing here is rounded up
 * or computed from a different run. proof.source.test.ts checks every value against the report,
 * so a regenerated report that moves a figure fails the UI tests. Fictional or public test data
 * only.
 *
 * - Text: the `smoke` hand-written set (62 docs, de + en + hu + pl) and the public test splits
 *   CEE-PII (451) and Nemotron-PII (300), "Results by fixture set". pii-guard fast is
 *   `FAST_MODE_SYSTEM`, the published NER.
 * - pii-guard fast is NER v4.2 (LAB-1625; its records keep candidate B3's key and label, same
 *   weights): `2026-10-30-lab-1625-*-v42-b3`, commit 40accd5 (357175c for smoke hu/en/de and
 *   inflection).
 * - Open models: `smoke`, "rules + <model> in place of pii-guard NER", runs of 2026-10-30
 *   (18edc24, LAB-1302): the same rules, only the NER differs. v4.2 was scored on a later
 *   commit; v2.0 scored the same on both (0.0 % leak, 95.4 % F1, 0.9 % over-masking on smoke), so the rules
 *   around the models did not move the smoke result.
 * - `smoke` rows of the comparison tools are the LAB-1302 re-runs of 2026-10-30 (18edc24),
 *   after the hu/de phones moved to the ADR 0005 fictional ranges, pooled with the LAB-1589
 *   Polish runs of the same day (252b680): every row covers all four languages.
 * - Images: "Image masking", `specimens` (65 official specimen ID documents from 24 countries),
 *   runs `2026-10-27-image-baselines-specimens-*`.
 * - Latency: the NER model alone per message on CPU, `LATENCY` (not the whole gateway).
 */

export const MEASURED = "Fictional German, English, Hungarian and Polish data · measured 27–30 Oct 2026";

/** Leak and F1 (%) by set, in the order of `SETS`; `p50` is detection per document on `smoke` (ms). */
export const SETS = ["Hand-written de + en + hu + pl (62)", "CEE-PII (451)", "Nemotron-PII (300)"] as const;
type Row = { system: string; key: string; leak: readonly string[]; f1: readonly string[]; p50: number; ours?: boolean };
export const COMPARISON: readonly Row[] = [
  { system: "PII Guard", key: FAST_MODE_SYSTEM, leak: ["0.0", "0.8", "0.6"], f1: ["95.9", "91.1", "94.0"], p50: 37, ours: true },
  { system: "PrivAiTe", key: "privaite", leak: ["13.0", "4.4", "4.0"], f1: ["55.4", "34.2", "80.8"], p50: 60 },
  { system: "Presidio", key: "presidio", leak: ["25.5", "36.5", "12.8"], f1: ["62.9", "41.4", "66.4"], p50: 42 },
  { system: "LLM Guard", key: "llm-guard", leak: ["46.3", "75.8", "28.8"], f1: ["54.0", "24.7", "72.9"], p50: 60 },
];
/** Documents in the `smoke` set behind `COMPARISON`'s first column and the landing's scatter chart. */
export const SMOKE_DOCS = 62;

/** The best comparison tool on one set and metric: lowest leak, highest F1. */
export function nextBest(metric: "leak" | "f1", set: number) {
  const others = COMPARISON.filter((row) => !row.ours);
  const pick = others.reduce((best, row) => {
    const a = Number(row[metric][set]), b = Number(best[metric][set]);
    return (metric === "leak" ? a < b : a > b) ? row : best;
  });
  return `${pick.system} ${pick[metric][set]}\u00a0%`;
}

/**
 * The NER model's own detection time per ~400-character message on CPU (p50), v4.2 alternating
 * with v2.0 in one process: eval/results/2026-10-30-lab-1625-ner-v42/latency-cpu-local.json
 * (the README's latency line). It is the model alone, not the whole gateway: LAB-1625's gateway
 * records were taken on an overloaded machine and are too noisy to quote.
 */
export const LATENCY = { value: "43 ms", p95: "50 ms", label: "NER time per message on CPU", hint: "p50 for a ~400-character message, the model alone" } as const;

/**
 * Our NER against other open PII models on `smoke`, the same rules around each, so only the NER
 * differs (LAB-1302 runs). Sorted by leak; rendered on the landing as a table (LAB-1656).
 */
export const OPEN_MODELS = [
  { model: "PII Guard NER v4.2", id: "watt-mind/pii-guard-ner-xlmr-base", leak: "0.0", f1: "95.9", over: "1.3", ours: true },
  { model: "bardsai multilang v1", id: "bardsai/eu-pii-anonimization-multilang", leak: "0.9", f1: "94.1", over: "8.8" },
  { model: "Wismut nym-pii", id: "Wismut/nym-pii-multilingual", leak: "2.8", f1: "91.8", over: "4.9" },
  { model: "tabularisai eu-pii-safeguard", id: "tabularisai/eu-pii-safeguard", leak: "6.5", f1: "91.8", over: "3.8" },
  { model: "bardsai multilang v3", id: "bardsai/eu-pii-anonimization-multilang-v3", leak: "10.7", f1: "90.1", over: "1.5" },
  { model: "Horizon-Labs pii-redactor-small", id: "Horizon-Labs/pii-redactor-small", leak: "11.1", f1: "84.8", over: "5.7" },
  { model: "Horizon-Labs pii-redactor-base", id: "Horizon-Labs/pii-redactor-base", leak: "12.5", f1: "84.8", over: "4.9" },
] as const;

/** Same placeholder in text and image: `visual-placeholders`, fuzzy matching, run of 2026-10-27 (recall; precision 100.0 %). */
export const VISUAL_PLACEHOLDERS = { docs: 24, recall: "98.0" } as const;

/**
 * Image masking on official specimen IDs (`specimens`, run
 * `2026-10-27-image-baselines-specimens-pii-guard-rules`, regions found at IoU ≥ 0.5, self-hosted
 * with SAM 3.1), led by the same-placeholder figure (`VISUAL_PLACEHOLDERS`). The weaker figures
 * from the same run are in `IMAGE_LIMITS`, shown under the page's limits.
 */
export const IMAGE_PROOF = [
  { value: `${VISUAL_PLACEHOLDERS.recall}\u00a0%`, label: "Same placeholder as in the text", hint: `Values on ${VISUAL_PLACEHOLDERS.docs} fictional documents, no false merges` },
  { value: "90.8\u00a0%", label: "Portraits covered", hint: "Presidio Image Redactor can’t mask portraits" },
  { value: "83.8\u00a0%", label: "Signatures covered", hint: "Self-hosted with SAM 3.1; kept visible in the hosted preview" },
] as const;

/** The same image run's weak spots: all labelled regions, and printed text alone. */
export const IMAGE_LIMITS = { all: "37.9", presidio: "13.3", text: "15.0", ids: 65, countries: 24 } as const;

/**
 * Where it's weaker, from the same report: Gretel finance on the dataset's own labels (PII Guard
 * fast vs Presidio) and over-masking on CEE-PII. MAPA EUR-Lex is report-only (benchmarks.md) and
 * is not shown on the landing (LAB-1656). `ceeV20`/`polishV20` are v2.0 on the same commit as v4.2
 * (the LAB-1625 re-score): the two public sets where v4.2 leaks more than the model it replaced.
 */
export const WEAKER = { gretel: "19.1", gretelPresidio: "18.8", ceeOverMasking: "7.3", cee: "0.8", ceeV20: "0.4", polishV20: "3.5" } as const;

/**
 * Agent traffic (`agent-traffic`, generated tool calls, JSON and logs): leak and over-masking of
 * fast mode against the comparison tools, all on the same 990 documents (de + en + hu; the tools
 * re-run on the current files by LAB-1656, `2026-10-30-lab-1656-agent-traffic-*`). `docs` is each row's pooled documents; a tool row with
 * `partial` ran on fewer languages (a † row in the report), so the landing labels it with the
 * reason and doesn't call it a like-for-like win.
 */
/** `partial` names why a tool couldn't run on every language (shown in the § footnote). */
type TrafficRow = { system: string; leak: string; over: string; docs: number; partial?: string; ours?: boolean };
export const AGENT_TRAFFIC: readonly TrafficRow[] = [
  { system: "PII Guard", leak: "0.2", over: "0.7", docs: 990, ours: true },
  { system: "PrivAiTe", leak: "2.4", over: "35.2", docs: 990 },
  { system: "Presidio", leak: "16.6", over: "33.4", docs: 990 },
  { system: "LLM Guard", leak: "20.2", over: "16.9", docs: 990 },
];

const ours = AGENT_TRAFFIC.find((row) => row.ours)!;
/** The best of the other tools on agent traffic (all of them ran on the same 990 documents). */
export function trafficNextBest(metric: "leak" | "over") {
  const pick = AGENT_TRAFFIC.filter((row) => !row.ours && !row.partial).reduce((best, row) => (Number(row[metric]) < Number(best[metric]) ? row : best));
  return `${pick.system} ${pick[metric]}\u00a0%`;
}
const smokeOurs = COMPARISON[0]!;
/**
 * The hero's three numbers, led by agent traffic (LAB-1656), each with the best of the other
 * tools on the same documents; `short` labels fit a phone's third (L2 carryover 8).
 */
export const PROOF = [
  { value: `${ours.over}\u00a0%`, label: "Masked text that wasn’t personal data, agent traffic", short: "Over-masked, agent traffic", hint: `Next best: ${trafficNextBest("over")}` },
  { value: `${ours.leak}\u00a0%`, label: `Values leaked, same ${ours.docs} documents`, short: "Leaked, agent traffic", hint: `Next best: ${trafficNextBest("leak")}` },
  { value: `${smokeOurs.leak[0]}\u00a0%`, label: `Values leaked, ${SMOKE_DOCS} hand-written docs in 4 languages`, short: `Leaked, ${SMOKE_DOCS} docs`, hint: `Next best: ${nextBest("leak", 0)}` },
] as const;

/** Fast mode's leak per language on `smoke` (the report's "By language" table). */
export const SMOKE_BY_LANGUAGE = { de: "0.0", en: "0.0", hu: "0.0", pl: "0.0" } as const;

/**
 * Hard cases: structured identifiers on CEE-PII split by the language packs' validators (the
 * report's "Number validity" table): leak on numbers whose checksum passes, and on mistyped ones.
 */
export const HARD_CASES = {
  set: "CEE-PII (451)",
  rows: [
    { system: "PII Guard", valid: "0.0", invalid: "0.0", ours: true },
    { system: "PrivAiTe", valid: "6.4", invalid: "0.0" },
    { system: "Presidio", valid: "80.4", invalid: "0.0" },
    { system: "LLM Guard", valid: "88.6", invalid: "57.5" },
  ],
} as const;

/** Hungarian inflected names (`inflection`, hand-written, 12 docs): fast mode against the rules alone. */
export const INFLECTION = { docs: 12, leak: "0.0", rulesLeak: "84.0" } as const;

/** Polish (`pl-pii-bench`, public, 346 docs) with the Polish language pack: fast mode and the rules alone. */
export const POLISH = { docs: 346, leak: "4.2", rulesLeak: "54.1" } as const;

/**
 * Real coding agents through the gateway: docs/integrations/harness-matrix-2026-10-29.md
 * (LAB-1475). 115 agent requests through the gateway, none of the 9 fictional values in any
 * body the upstream received, and 0 of 10 agent turns refused (7 of 15 the day before).
 */
export const HARNESS = { agents: ["Codex", "OpenCode", "Muse Code", "pi"], requests: 115, leaked: 0, refused: "0 of 10", date: "29 Oct 2026" } as const;

/** Committed run records in eval/results/runs/ (733 on 29 Oct 2026): shown as a floor, so a new run never makes it wrong. */
export const RUNS = { floor: 700, label: "700+" } as const;

/** Our NER, the other open PII models it was compared with and the comparison tools, from `OPEN_MODELS` and `COMPARISON`. */
export const COMPARED = { tools: COMPARISON.length - 1, openModels: OPEN_MODELS.length - 1 } as const;
