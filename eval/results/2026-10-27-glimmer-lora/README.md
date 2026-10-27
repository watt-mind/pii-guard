# Answer-only Muse Glimmer LoRA vs the other detectors (2026-10-27, LAB-1109)

Status: **the fine-tuned model is trained but not evaluated yet.** Its adapter has to be
downloaded from Fireworks before it can be served on Modal, and Fireworks only allows that
after an interactive sign-in (see [docs/models.md](../../../docs/models.md#answer-only-muse-glimmer-lora-fine-tune-lab-1109)).
This directory holds the fast-mode reference runs on the same sets; the fine-tuned rows are
added when the model is served.

| | |
|---|---|
| Code | develop `7e328ad53fd1` plus this branch's uncommitted training scripts, tests and docs (nothing under `src/` changed, hence `dirty: true` in the scorecards) |
| Fixtures | `hu-smoke.jsonl` `3766a651708e8749` (31 docs), `en-smoke.jsonl` `5983d84d8dfc9fe3` (10), `de-smoke.jsonl` `b623ca3b33af7ef7` (10), `hu-synth-sample.jsonl` `ed547228ddc329bb` (20), `en-synth-sample.jsonl` `2c7ab3d12880065d` (10); held-out test split = LAB-1128 distillation dev split, seed 11: `hu-distill-dev.jsonl` `f6dca4b60ca8dfa5` (368), `en-distill-dev.jsonl` `b13f9983ca99ade6` (373), not committed (`eval/generated/`) |
| Fast mode | `rules,ner` with the LAB-1128 distilled xlm-roberta-large checkpoint (`PII_GUARD_NER_MODEL`), Apple M1 Max, MPS, one document at a time |

Files: `<fixture>-rules-ner.{json,md}` are full scorecards.

Reproduce:

```bash
export PII_GUARD_NER_MODEL=models/ner/pii-guard-ner-xlmr-large-distilled   # trained per LAB-1128
for f in hu-smoke en-smoke de-smoke hu-synth-sample en-synth-sample; do
  uv run pii-guard eval --fixtures eval/fixtures/$f.jsonl --detectors rules,ner \
      --json $f-rules-ner.json --markdown $f-rules-ner.md
done
# test split: eval/generated/distill-s11/labelled/{hu,en}-distill-dev.jsonl (training/distill/)
```

## Fast mode (rules + distilled NER large)

Overlap P/R/F1, exact F1, leak, partial leak, over-masking in %; detection latency per
document in seconds.

| Fixture | Docs | P | R | F1 | F1 exact | Leak | Partial leak | Over-masking | p50 s | p95 s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu-smoke` | 31 | 97.5 | 98.3 | 97.9 | 93.8 | 0.9 | 1.9 | 0.9 | 0.03 | 0.04 |
| `en-smoke` | 10 | 100.0 | 97.1 | 98.5 | 85.3 | 0.0 | 6.7 | 0.0 | 0.03 | 0.25 |
| `de-smoke` | 10 | 100.0 | 100.0 | 100.0 | 91.4 | 0.0 | 2.7 | 0.0 | 0.02 | 0.18 |
| `hu-synth-sample` | 20 | 99.6 | 100.0 | 99.8 | 98.9 | 0.0 | 0.0 | 0.4 | 0.06 | 0.14 |
| `en-synth-sample` | 10 | 97.6 | 100.0 | 98.8 | 98.8 | 0.0 | 3.8 | 2.7 | 0.06 | 0.31 |
| `hu-distill-dev` (test) | 368 | 99.6 | 99.6 | 99.6 | 98.4 | 0.5 | 0.0 | 0.4 | 0.10 | 0.35 |
| `en-distill-dev` (test) | 373 | 97.9 | 99.3 | 98.6 | 98.5 | 0.5 | 1.3 | 2.2 | 0.08 | 0.37 |

## Comparison on the hand-written smoke sets (overlap F1 / leak %, p50 s)

| System | `hu-smoke` | `en-smoke` | Source |
|---|---|---|---|
| rules + **Glimmer LoRA, answer-only** | pending | pending | this ticket |
| rules + Glimmer zero-shot, `reasoning_strength` low (Modal H100) | 99.3 / 0.0, 9.4 s (hu 28 docs + en pooled) | (pooled) | LAB-1109 ticket comment, 2026-10-26, older commit |
| rules + Muse Spark Open, Baseten, `reasoning_effort` low | 98.4 / 0.9, 1.8 s | 97.1 / 0.0, 1.2 s | [2026-10-27-baseten](../2026-10-27-baseten/README.md) |
| rules + Muse Spark 1.3, Meta Model API | 98.2 / 1.0, 10.6 s (28-doc version) | 97.1 / 0.0, 7.0 s | [2026-10-26-baselines](../2026-10-26-baselines/README.md) |
| rules + distilled NER large (fast mode) | 97.9 / 0.9, 0.03 s | 98.5 / 0.0, 0.03 s | this directory |

Reading so far: fast mode is already within about a point of the LLM detectors on F1 and leak
at 30-100x lower latency, so the fine-tune has to beat it on leak (the strict-mode job) to
earn its GPU.
