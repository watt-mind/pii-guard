# pii-guard fast and strict vs Presidio, LLM Guard and PrivAiTe (2026-10-27)

A fresh head-to-head after the distilled NER (LAB-1128), the Hungarian lexicon, address and ID
rules (LAB-1126, LAB-1127), prompt-injection hardening (LAB-1107) and Muse Spark Open on
Baseten (LAB-1108). Same scorer and tool configurations as
[2026-10-26-baselines](../2026-10-26-baselines/README.md), on our five fixture sets **and** a
public benchmark nobody here wrote. Every number below is in `scorecards/` and in the run
records `eval/results/runs/2026-10-27-comparison-*.json`
([benchmarks.md](../../../docs/benchmarks.md) and its charts are generated from them).

## Systems

| System | What runs |
|---|---|
| pii-guard rules | rules only (the floor; no name detection) |
| **pii-guard fast** | rules + NER, the distilled XLM-RoBERTa-large checkpoint of LAB-1128 (not published; `model.safetensors` sha256 `ec9844dfc84eb8ee…`, `training_meta.json` sha256 `a3cd7136d79e5e6f…`), PyTorch device `auto` (Apple MPS) |
| **pii-guard strict** | rules + the same NER + Muse Spark Open (`meta-models/muse-spark-open-1026`) on Baseten Model APIs, `reasoning_effort: low`, one request at a time |
| Presidio 2.2.365 | default analyzer + anonymizer; `en_core_web_lg` (en, and de, which falls back to the English pipeline), huSpaCy `hu_core_news_lg` (hu) |
| LLM Guard 0.3.16 | `Anonymize` defaults, `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea9927`, language `en` for every document |
| PrivAiTe 0.7.3 | shipped proxy config, preset `onnx` (`openai/privacy-filter@7ffa9a0` q4 + spaCy `en_core_web_lg`, `fr_core_news_md`) |

Configurations, label mapping and scoring rules:
[evaluation.md](../../../docs/evaluation.md#comparison-with-open-source-tools).

## Fixtures

| Fixture | Docs | Written by |
|---|---:|---|
| `hu-smoke`, `en-smoke`, `de-smoke` | 31, 10, 10 | hand-written, fictional values |
| `hu-synth-sample`, `en-synth-sample` | 20, 10 | Muse Spark 1.3 (flatters Muse-based detection) |
| `hu-ai4privacy`, `en-ai4privacy`, `de-ai4privacy` | 200 each | [Ai4Privacy OpenPII 1M](../../fixtures/public/README.md) (CC-BY-4.0), seeded sample of the validation split |

## Results

Overlap P/R/F1, exact F1, leak, partial leak, over-masking and round trip in %; detection
latency per document in ms; strict-mode cost per 1,000 messages (one document = one message)
at Baseten list prices ($1.25 / 1M input, $0.15 / 1M cached input, $4.25 / 1M output tokens).
Round trip is n/a for Presidio (its default operator can't be undone).

| Fixture | System | Docs | P | R | F1 | F1 exact | Leak | Partial leak | Over-masking | Round trip | p50 ms | p95 ms | $ / 1k msgs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu-smoke` | pii-guard rules | 31 | 100.0 | 55.8 | 71.7 | 71.7 | 40.6 | 3.8 | 0.0 | 100.0 | 0.2 | 0.4 | - |
| `hu-smoke` | pii-guard fast | 31 | 97.5 | 98.3 | 97.9 | 93.8 | 0.9 | 1.9 | 0.9 | 100.0 | 28.3 | 38.4 | - |
| `hu-smoke` | pii-guard strict | 31 | 94.5 | 99.2 | 96.8 | 89.9 | 0.9 | 0.9 | 1.8 | 100.0 | 2,191 | 4,220 | 2.40 |
| `hu-smoke` | presidio | 31 | 74.8 | 61.7 | 67.6 | 46.8 | 33.0 | 12.3 | 17.4 | n/a | 78.7 | 135 | - |
| `hu-smoke` | llm-guard | 31 | 53.0 | 41.7 | 46.7 | 4.5 | 50.0 | 5.7 | 45.2 | 100.0 | 71.9 | 110 | - |
| `hu-smoke` | privaite | 31 | 42.8 | 50.8 | 46.5 | 22.2 | 17.9 | 9.4 | 28.3 | 96.8 | 73.5 | 109 | - |
| `en-smoke` | pii-guard rules | 10 | 100.0 | 47.1 | 64.0 | 56.0 | 46.7 | 13.3 | 0.0 | 100.0 | 0.2 | 0.2 | - |
| `en-smoke` | pii-guard fast | 10 | 100.0 | 97.1 | 98.5 | 85.3 | 0.0 | 6.7 | 0.0 | 100.0 | 25.1 | 37.9 | - |
| `en-smoke` | pii-guard strict | 10 | 87.2 | 100.0 | 93.2 | 90.4 | 0.0 | 3.3 | 11.8 | 100.0 | 2,076 | 7,895 | 2.77 |
| `en-smoke` | presidio | 10 | 61.9 | 76.5 | 68.4 | 65.8 | 10.0 | 13.3 | 26.2 | n/a | 7.3 | 23.1 | - |
| `en-smoke` | llm-guard | 10 | 100.0 | 61.8 | 76.4 | 31.7 | 30.0 | 13.3 | 0.0 | 100.0 | 60.2 | 83.9 | - |
| `en-smoke` | privaite | 10 | 70.7 | 79.4 | 74.8 | 61.3 | 0.0 | 13.3 | 22.0 | 100.0 | 56.7 | 63.9 | - |
| `de-smoke` | pii-guard rules | 10 | 100.0 | 52.5 | 68.9 | 64.5 | 43.2 | 8.1 | 0.0 | 100.0 | 0.2 | 0.3 | - |
| `de-smoke` | pii-guard fast | 10 | 100.0 | 100.0 | 100.0 | 91.4 | 0.0 | 2.7 | 0.0 | 100.0 | 24.4 | 43.2 | - |
| `de-smoke` | pii-guard strict | 10 | 100.0 | 100.0 | 100.0 | 97.5 | 0.0 | 0.0 | 0.0 | 100.0 | 1,663 | 3,124 | 1.99 |
| `de-smoke` | presidio | 10 | 43.1 | 77.5 | 55.4 | 39.3 | 10.8 | 10.8 | 44.4 | n/a | 7.0 | 18.1 | - |
| `de-smoke` | llm-guard | 10 | 97.1 | 50.0 | 66.0 | 16.0 | 43.2 | 10.8 | 0.0 | 100.0 | 68.3 | 107 | - |
| `de-smoke` | privaite | 10 | 62.5 | 70.0 | 66.0 | 47.7 | 8.1 | 8.1 | 20.8 | 100.0 | 52.8 | 71.7 | - |
| `hu-synth-sample` | pii-guard rules | 20 | 100.0 | 46.1 | 63.1 | 63.1 | 41.6 | 1.2 | 0.0 | 100.0 | 0.9 | 2.4 | - |
| `hu-synth-sample` | pii-guard fast | 20 | 99.6 | 100.0 | 99.8 | 98.9 | 0.0 | 0.0 | 0.4 | 100.0 | 66.6 | 159 | - |
| `hu-synth-sample` | pii-guard strict | 20 | 99.6 | 100.0 | 99.8 | 98.0 | 0.0 | 0.0 | 0.4 | 100.0 | 2,324 | 3,187 | 3.85 |
| `hu-synth-sample` | presidio | 20 | 83.1 | 70.8 | 76.5 | 54.3 | 28.9 | 23.1 | 9.7 | n/a | 300 | 655 | - |
| `hu-synth-sample` | llm-guard | 20 | 58.1 | 39.1 | 46.8 | 5.6 | 60.1 | 9.2 | 38.6 | 100.0 | 220 | 941 | - |
| `hu-synth-sample` | privaite | 20 | 51.7 | 49.4 | 50.6 | 31.7 | 24.3 | 11.6 | 25.2 | 75.0 | 267 | 730 | - |
| `en-synth-sample` | pii-guard rules | 10 | 100.0 | 37.5 | 54.5 | 33.9 | 46.2 | 25.0 | 0.0 | 100.0 | 1.7 | 12.2 | - |
| `en-synth-sample` | pii-guard fast | 10 | 97.6 | 100.0 | 98.8 | 98.8 | 0.0 | 3.8 | 2.7 | 100.0 | 62.6 | 176 | - |
| `en-synth-sample` | pii-guard strict | 10 | 97.6 | 100.0 | 98.8 | 98.8 | 0.0 | 3.8 | 2.7 | 100.0 | 2,099 | 4,749 | 3.01 |
| `en-synth-sample` | presidio | 10 | 50.5 | 83.3 | 62.9 | 47.2 | 11.2 | 26.2 | 44.6 | n/a | 32.1 | 80.2 | - |
| `en-synth-sample` | llm-guard | 10 | 98.4 | 46.7 | 63.3 | 36.3 | 48.8 | 13.8 | 1.6 | 100.0 | 108 | 307 | - |
| `en-synth-sample` | privaite | 10 | 73.1 | 80.8 | 76.8 | 66.1 | 7.5 | 3.8 | 21.6 | 100.0 | 158 | 331 | - |
| `hu-ai4privacy` | pii-guard rules | 200 | 100.0 | 27.8 | 43.5 | 39.8 | 72.2 | 2.4 | 0.0 | 100.0 | 0.2 | 0.6 | - |
| `hu-ai4privacy` | pii-guard fast | 200 | 79.4 | 59.3 | 67.9 | 50.2 | 40.4 | 1.7 | 14.7 | 100.0 | 29.8 | 46.1 | - |
| `hu-ai4privacy` | pii-guard strict | 200 | 82.2 | 95.6 | 88.4 | 81.7 | 3.5 | 0.3 | 13.7 | 100.0 | 2,531 | 5,602 | 2.98 |
| `hu-ai4privacy` | presidio | 200 | 54.1 | 44.9 | 49.1 | 29.3 | 46.1 | 5.7 | 35.1 | n/a | 86.2 | 202 | - |
| `hu-ai4privacy` | llm-guard | 200 | 60.2 | 52.8 | 56.3 | 9.9 | 44.7 | 2.9 | 37.7 | 100.0 | 62.5 | 115 | - |
| `hu-ai4privacy` | privaite | 200 | 48.4 | 59.8 | 53.5 | 35.1 | 14.0 | 3.5 | 29.0 | 98.0 | 74.9 | 188 | - |
| `en-ai4privacy` | pii-guard rules | 200 | 95.6 | 24.1 | 38.5 | 38.3 | 74.7 | 0.4 | 0.5 | 100.0 | 0.3 | 0.8 | - |
| `en-ai4privacy` | pii-guard fast | 200 | 82.7 | 64.1 | 72.2 | 55.9 | 34.8 | 1.9 | 12.8 | 100.0 | 30.4 | 52.6 | - |
| `en-ai4privacy` | pii-guard strict | 200 | 83.0 | 92.8 | 87.6 | 79.3 | 3.7 | 0.2 | 11.1 | 100.0 | 1,905 | 3,561 | 2.65 |
| `en-ai4privacy` | presidio | 200 | 38.5 | 48.3 | 42.8 | 33.0 | 22.5 | 9.9 | 37.2 | n/a | 9.4 | 24.5 | - |
| `en-ai4privacy` | llm-guard | 200 | 96.5 | 51.6 | 67.2 | 15.9 | 46.1 | 1.0 | 1.1 | 100.0 | 59.0 | 112 | - |
| `en-ai4privacy` | privaite | 200 | 57.1 | 68.6 | 62.3 | 39.4 | 7.7 | 1.1 | 22.7 | 99.5 | 83.0 | 212 | - |
| `de-ai4privacy` | pii-guard rules | 200 | 98.2 | 26.1 | 41.3 | 39.0 | 73.4 | 1.4 | 0.0 | 100.0 | 0.2 | 0.6 | - |
| `de-ai4privacy` | pii-guard fast | 200 | 82.5 | 60.2 | 69.6 | 53.1 | 39.2 | 1.8 | 14.9 | 100.0 | 28.6 | 43.6 | - |
| `de-ai4privacy` | pii-guard strict | 200 | 84.8 | 93.5 | 88.9 | 79.9 | 4.3 | 0.0 | 11.5 | 100.0 | 1,881 | 3,776 | 2.58 |
| `de-ai4privacy` | presidio | 200 | 20.3 | 56.5 | 29.8 | 18.8 | 18.9 | 7.6 | 70.2 | n/a | 7.4 | 17.6 | - |
| `de-ai4privacy` | llm-guard | 200 | 92.4 | 57.5 | 70.9 | 14.7 | 39.8 | 1.6 | 4.6 | 100.0 | 58.3 | 98.8 | - |
| `de-ai4privacy` | privaite | 200 | 52.3 | 68.0 | 59.1 | 37.0 | 6.5 | 3.2 | 28.1 | 96.5 | 81.0 | 165 | - |

### Reading it

- **Our fixtures.** Fast mode leaks 0.9 % on `hu-smoke` (one value of 106) and 0.0 % on
  `en-smoke` and `de-smoke`, at 24–28 ms p50; strict mode is the same on leak (0.9 / 0.0 /
  0.0 %) at about 2 s and $2–2.80 per 1,000 messages. On the hand-written sets the best
  comparison tool leaks 17.9 % (`hu`, PrivAiTe), 0.0 % (`en`, PrivAiTe) and 8.1 % (`de`,
  PrivAiTe).
- **Strict is not more precise than fast on our sets.** Adding the LLM to rules + NER found
  one more Hungarian value but masked more harmless spans (`en-smoke` over-masking 11.8 %
  vs 0.0 % for fast; precision 87.2 vs 100). On these small hand-written sets fast mode is the
  better trade-off; strict earns its cost on unfamiliar text (below).
- **Public set.** Strict mode leaks 3.5 % (`hu`), 3.7 % (`en`) and 4.3 % (`de`), the lowest of
  every system; the best comparison tool is PrivAiTe at 14.0 / 7.7 / 6.5 %. **Fast mode
  leaks 35–40 % here, worse than PrivAiTe and Presidio on leak.** Most of what it misses is
  numbers: only about 10 % of the set's card, tax and TAJ numbers pass their checksums, and
  phone numbers use formats no numbering plan has, while pii-guard's rules validate both on
  purpose. Its NER isn't trained to find unvalidated numbers. The LLM pass catches them.
- **Over-masking on the public set** is inflated for every system that masks dates or towns:
  those labels are policy-excluded (not in the gold spans), so masking them counts against
  the system.
- **LLM Guard** was fine-tuned on an earlier Ai4Privacy release: its public-set numbers are
  probably optimistic (it still leaks 40–46 %). PrivAiTe's training data isn't documented.

### Run conditions

- **The machine was not idle.** Other jobs were running throughout (one-minute load average
  9–34 on 10 cores at the start of each run, briefly over 100 during the English public
  strict run; each run record has its load). Latency is relative, not a benchmark of the
  hardware. Apple Silicon arm64, macOS 26.5, Python 3.12.15; the comparison tools run CPU
  only, the NER on MPS.
- Each pii-guard system gets one warm-up call before timing, like the comparison tools.
- **Strict mode, availability:** 0 refusals and 0 invalid outputs in the 682 requests of the committed runs.
  One run of `de-ai4privacy` aborted when the detector's completion was truncated twice
  (`finish_reason=length`) on one document; the pipeline failed closed, as the gateway would
  for that request. The re-run had 0 blocked documents (one empty answer was re-asked,
  `empty_challenged: 1`). The driver now counts such documents as blocked instead of
  aborting.
- **Code.** Fast and the baselines ran at `e394a06` (this branch on develop `0ad202a`),
  strict on our fixtures and on `de-ai4privacy` too; strict on `hu-` and `en-ai4privacy` ran at
  `688b940`, this branch before its rebase (develop `f8727dc` plus the driver; detection code
  identical). The only uncommitted change during the runs was prose in `docs/evaluation.md`,
  so the scorecards say `dirty`.

## Spend

Baseten, all of LAB-1148: **about $2.60** of the $5 budget, metered from the token counts the
endpoint reported, at list prices:

| What | Cost |
|---|---:|
| The eight committed strict runs (682 requests, warm-up calls included) | $1.88 |
| Five earlier strict runs on our fixtures, superseded by the re-runs at `e394a06` | $0.23 |
| The aborted first `de-ai4privacy` run (not metered; estimated as the full re-run's cost) | ≤ $0.52 |
| **Total** | **≤ $2.63** |

## Reproduce

```bash
uv sync --extra baselines                      # Presidio, plus worker envs for the others
for f in hu-smoke en-smoke de-smoke hu-synth-sample en-synth-sample; do
  uv run pii-guard eval --fixtures eval/fixtures/$f.jsonl --detectors rules \
      --baselines presidio,llm-guard,privaite --json scorecards/$f-baselines.json
done                                           # and eval/fixtures/public/<lang>-ai4privacy.jsonl
UV_PROJECT_ENVIRONMENT=.venv-ner uv sync --extra ner   # ner conflicts with baselines
export PII_GUARD_NER_MODEL=/path/to/pii-guard-ner-xlmr-large-distilled
uv run python -m pii_guard.eval.baselines.suite --system fast \
    --fixtures eval/fixtures/hu-smoke.jsonl --json scorecards/hu-smoke-fast.json
export PII_GUARD_LLM_DETECTOR_API_KEY=$BASETEN_API_KEY PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=low
uv run python -m pii_guard.eval.baselines.suite --system strict \
    --fixtures eval/fixtures/hu-smoke.jsonl --json scorecards/hu-smoke-strict.json
python -m pii_guard.eval.baselines.table scorecards/*.json --out table.md
python -m pii_guard.eval.baselines.records scorecards     # run records, then:
uv run pii-guard eval report
```
