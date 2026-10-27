# Public fallback NER for fast mode (LAB-1192)

`make demo` and `pii-guard` fast mode need a NER model that anyone can download from a clean
checkout, because the trained pii-guard checkpoints are not published (LAB-1137). LAB-1150
compared two public zero-shot models (GLiNER multi v2.1 and Davlan's XLM-R). This run adds a
third, a public multilingual PII token classifier, on the same fixtures with the same scorer,
and it becomes the fallback (`pii_guard.detect.ner_resolve.PUBLIC_FALLBACK`,
[docs/models.md](../../../docs/models.md#which-ner-model-fast-mode-runs)).

- **Model:** [`bardsai/eu-pii-anonimization-multilang`](https://huggingface.co/bardsai/eu-pii-anonimization-multilang)
  at revision `62ca5712368705bac11b8fea19e42e65cce088dd`, `model.safetensors` SHA-256
  `03ec34b3cd297c25ab8c720352c125f571ebf844684d3fbb583927a73a7752fd` (1,110,048,500 bytes).
  XLM-RoBERTa base, 24 EU languages including hu/en/de.
- **Licence:** `license: apache-2.0` in the model card front matter at that revision. No
  weights are committed; they are fetched into `~/.cache/pii-guard/models/ner/`.
- **System:** fast mode, `rules,ner`, the model loaded from its pinned directory, default
  thresholds (0.5), `first` aggregation, PyTorch device `auto` (MPS), M1 Max.

## Results (rules + model)

`scorecards/` (`training/ner/eval_candidates.py`), table by `training/ner/table.py`; GLiNER and
Davlan rows are LAB-1150's scorecards in
[`../2026-10-27-ner-v2/scorecards/`](../2026-10-27-ner-v2/scorecards/).

| Fixture | bardsai EU PII v1: F1 / leak / over-masking | GLiNER multi v2.1 | Davlan XLM-R base |
|---|---|---|---|
| `hu-smoke` | 91.7 / **1.9** / 11.8 | 95.1 / 2.8 / 6.3 | 93.7 / 7.5 / 5.7 |
| `en-smoke` | 88.3 / **0.0** / 23.1 | 94.4 / 3.3 / 5.7 | 90.7 / 10.0 / 10.8 |
| `de-smoke` | 98.8 / **0.0** / 2.6 | 91.6 / 5.4 / 10.0 | 96.1 / 8.1 / 0.0 |
| `hu-ai4privacy`\* | 79.1 / **11.8** / 11.3 | 73.6 / 26.3 / 5.5 | 73.1 / 34.3 / 12.4 |
| `en-ai4privacy`\* | 86.2 / **11.2** / 8.1 | 77.1 / 21.7 / 6.2 | 77.6 / 26.8 / 8.6 |
| `de-ai4privacy`\* | 88.4 / **7.8** / 9.3 | 76.9 / 18.8 / 5.2 | 80.4 / 24.5 / 10.0 |
| `hu-synth-sample` | 96.8 / **0.0** / 6.7 | 87.5 / 4.0 / 20.8 | 94.6 / 9.8 / 4.3 |
| `en-synth-sample` | 97.2 / **1.2** / 4.3 | 80.0 / 7.5 / 30.1 | 96.8 / 7.5 / 1.4 |
| `hu-company-names` | 85.3 / 0.0 / 1.6 | 81.1 / 0.0 / 7.4 | 82.0 / 0.0 / 1.6 |

| Candidate | ai4privacy leak, pooled | ai4privacy F1, mean | smoke leak, max | smoke over-masking, max |
|---|---:|---:|---:|---:|
| bardsai EU PII v1 | **10.4**\* | **84.6**\* | **1.9** | 23.1 |
| GLiNER multi v2.1 | 22.5 | 75.9 | 5.4 | 10.0 |
| Davlan XLM-R base | 28.7 | 77.0 | 10.0 | 10.8 |

\* **Not out of distribution for this model.** Its card lists
`ai4privacy/pii-masking-openpii-1m` among its training data without naming the split, and the
ai4privacy fixtures are rows of that dataset's validation split. Read the ai4privacy rows as
in-distribution; the hand-written smoke sets and the synth samples are the fair comparison, and
the model leaks least on those too. The run records carry this note.

**`LOCATION` → `ADDRESS` ablation** (smoke and ai4privacy only, not committed): without the
`LOCATION` mapping the ai4privacy pooled leak doubles (10.4 → 21.5 %) and en-smoke leaks 6.7 %,
while smoke over-masking drops to 15.2 %. Leak is the selection rule, so `LOCATION` stays
mapped, as Davlan's `LOC` is.

**Over-masking.** The cost of the low leak is en-smoke over-masking of 23.1 %: 9 of 39 masked
spans are not in the gold, 4 of them `ADDRESS` (place names, via `LOCATION`), 3 `PERSON` and
2 `ID_DOCUMENT`.

## Latency

`training/ner/bench_latency.py`, ~400-character messages from the hu + en synth samples (122),
8 torch threads, both models in the same session (`latency/`). The machine was loaded by other
jobs (load average 70–100), so these are upper bounds; LAB-1150 measured Davlan at 47 / 53 ms
on CPU when it was idle.

| Model | CPU p50 / p95 | MPS p50 / p95 |
|---|---|---|
| bardsai EU PII v1 | 54.2 / 100.8 ms | 16.7 / 23.4 ms |
| Davlan XLM-R base | 48.3 / 55.5 ms | 16.4 / 20.0 ms |

Both are XLM-R base, so the per-message cost is the same model size. GLiNER multi v2.1 was
107 / 126 ms on CPU (LAB-1150).

Gateway overhead with the fallback (`pii-guard bench latency`, mock upstream at 50 ms, MPS,
[run record](../runs/2026-10-27-gateway-latency-ner-fallback-fast.json)): p50 25.0 ms /
p95 29.1 ms at concurrency 1, p50 72.9 ms / p95 90.4 ms at concurrency 8 (not streamed).

## Not used

- `bardsai/eu-pii-anonimization-multilang-v2` and `-v3` (Apache-2.0, mmBERT base, 1.2 GB):
  better on their own card, but they need the card's word-level decoder. With pii-guard's
  first-sub-token decoder, a sanity check on three fictional sentences cut names into
  fragments (`Kovács` without `Pétert`, `+36` without the number), so they need a decoder
  change before they can be measured fairly.
- `iiiorg/piiranha-v1-detect-personal-information`: CC BY-NC-ND 4.0.

## Reproduce

```bash
uv sync --extra ner
uv run --no-sync python -m pii_guard.detect.ner_resolve fetch     # the pinned model, once
PII_GUARD_NER_MODEL=~/.cache/pii-guard/models/ner/bardsai--eu-pii-anonimization-multilang-62ca57123687 \
    uv run --no-sync python training/ner/eval_candidates.py --candidate bardsai-eu-pii-v1 \
    --detectors rules,ner --out eval/results/2026-10-27-fast-demo-ner/scorecards
uv run --no-sync python training/ner/table.py eval/results/2026-10-27-fast-demo-ner/scorecards --out /tmp/table.md
uv run --no-sync python training/ner/records.py eval/results/2026-10-27-fast-demo-ner/scorecards
uv run --no-sync python training/ner/bench_latency.py --devices cpu,mps --threads 8 \
    --json eval/results/2026-10-27-fast-demo-ner/latency/mac-bardsai-eu-pii-v1.json
uv run --no-sync pii-guard bench latency --record gateway-latency-ner-fallback
```

The `distill-dev` fixtures of LAB-1150 are generated files not present in a clean checkout, so
they were skipped. **Cost:** $0, everything ran locally; the model download is free.
