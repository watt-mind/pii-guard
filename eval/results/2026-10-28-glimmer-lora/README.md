# Answer-only Muse Glimmer LoRA vs Glimmer zero-shot on Fireworks (2026-10-28, LAB-1109)

This is the first evaluation of the LoRA trained on 2026-10-27 (answer-only, 3,883 examples,
r 8; recipe in
[docs/models.md](../../../docs/models.md#answer-only-muse-glimmer-lora-fine-tune-lab-1109)).
Both models ran on the **same hardware**: a Fireworks on-demand deployment, 1x H200 141 GB,
BF16, deployment shape `dkuwotf7`. Each system got its own deployment, deleted right after
scoring. Only synthetic data was sent.

| | |
|---|---|
| Code | branch commit `541a31d` (develop `72026a5` + the 2026-10-27 LAB-1109 commit) plus the then-untracked driver `training/llm/eval_fireworks.py` (committed with these results); nothing under `src/` changed |
| Harness | `run_documents` + `build_scorecard`, the code behind `pii-guard eval --detectors llm` / `rules,llm`, one document at a time. Production prompts (`build_messages`), temperature 0, JSON mode, `max_tokens` 4096 |
| Fixtures | `eval/fixtures/hu-smoke.jsonl` `3766a651708e8749` (31 docs), `en-smoke.jsonl` `5983d84d8dfc9fe3` (10); `eval/synthetic/dev/{hu,en,de}-agent-traffic-dev.jsonl` `f5a0a0e3de68534f` / `80ddf60dd1550851` / `2014c599aa56203c` (100 each) |
| LoRA | `accounts/<account>/models/pii-guard-glimmer-lab1109-v1`, live merge |
| Base | `accounts/fireworks/models/muse-glimmer-30b` |
| Reasoning | `reasoning_effort: low` for both (see "Template" below) |

How to read the columns:

- **Leak**: labelled values of a mask-policy type that survive in any surface form. Matching
  is by overlap.
- **Latency**: detection wall time per document as the client sees it, network included
  (Europe to Fireworks).
- **`rules + llm`** reuses the `llm` pass's answers (the same requests). Its latency is the
  `llm` latency plus about 1 ms for the rules.

### hu + en smoke (41 docs: hu 31, en 10)

| System (1x H200, Fireworks) | Detectors | F1 overlap | F1 exact | Full leak | Partial leak | Over-masking | Recall | p50 / p95 s | Completion tok/doc |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Zero-shot, `reasoning_effort` low | llm | 96.5 | 91.0 | 2.2 | 2.2 | 2.9 | 97.4 | 2.15 / 5.30 | 471 |
| LoRA, live merge (no speculation) | llm | 96.3 | 93.0 | 6.6 | 2.9 | 0.0 | 93.5 | 1.67 / 3.73 | 78 |
| LoRA, live merge + n-gram speculation | llm | 97.0 | 93.0 | 5.1 | 2.9 | 0.0 | 94.8 | 1.13 / 3.49 | 79 |
| Zero-shot, `reasoning_effort` low | rules + llm | **97.8** | 94.6 | **0.7** | 1.5 | 2.8 | 99.4 | 2.15 / 5.30 | 471 |
| LoRA, live merge (no speculation) | rules + llm | 97.0 | 94.4 | 4.4 | 2.2 | 0.0 | 94.8 | 1.67 / 3.73 | 78 |
| LoRA, live merge + n-gram speculation | rules + llm | 97.7 | 94.4 | 2.9 | 2.2 | 0.0 | 96.1 | **1.13** / 3.49 | 79 |

### agent-traffic-dev (300 docs: hu, en, de 100 each)

| System (1x H200, Fireworks) | Detectors | F1 overlap | F1 exact | Full leak | Partial leak | Over-masking | Recall | p50 / p95 s | Completion tok/doc |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Zero-shot, `reasoning_effort` low | llm | 93.8 | 91.5 | 3.5 | 0.0 | 0.0 | 96.8 | 2.28 / 3.92 | 479 |
| LoRA, live merge (no speculation) | llm | 96.9 | 94.9 | 1.1 | 0.3 | 0.1 | 98.6 | 1.88 / 3.54 | 108 |
| LoRA, live merge + n-gram speculation | llm | 96.6 | 94.6 | 1.9 | 0.2 | 0.1 | 97.9 | 1.03 / 1.50 | 108 |
| Zero-shot, `reasoning_effort` low | rules + llm | 94.9 | 92.7 | **0.4** | 0.0 | 0.0 | 99.3 | 2.28 / 3.92 | 479 |
| LoRA, live merge (no speculation) | rules + llm | **96.6** | 94.7 | 1.0 | 0.1 | 0.1 | 98.4 | 1.88 / 3.54 | 108 |
| LoRA, live merge + n-gram speculation | rules + llm | **96.6** | 94.6 | 1.1 | 0.1 | 0.1 | 98.3 | **1.03 / 1.50** | 108 |

Per language, `rules + llm` (F1 overlap / full leak, leaked values of all values):

| System | hu | en | de |
|---|---|---|---|
| Zero-shot, `reasoning_effort` low | 95.0 / 0.4 % (2 of 523) | 94.5 / 0.0 % (0 of 502) | 95.2 / 0.8 % (4 of 530) |
| LoRA, live merge (no speculation) | 95.6 / 1.3 % (7 of 523) | 96.4 / 1.6 % (8 of 502) | 97.8 / 0.0 % (0 of 530) |
| LoRA, live merge + n-gram speculation | 95.9 / 1.1 % (6 of 523) | 96.1 / 2.2 % (11 of 502) | 97.7 / 0.0 % (0 of 530) |

For reference, fast mode (rules + NER v2 base, local CPU, LAB-1226 run
`2026-10-28-datasets-agent-traffic-dev-fast`) on agent-traffic-dev: F1 96.1, leak 0.13 %,
over-masking 2.2 %, p50 0.02 s.

## What this says

- **The LoRA really answers without reasoning.** Across all 682 LoRA documents there were
  0 reasoning tokens, 0 `to=self` turns, and no answers that were non-JSON or truncated.
  `raw_output` shows each completion starting with ` to=user<|message|>{...`. Completion
  tokens per document fall from about 470-480 to about 80-110, a 4.4-6x cut.
- **The speed-up is smaller than the token cut.** On Fireworks the base model is served with
  speculative decoding (`draftTokenCount: 15`, the platform's built-in draft) and decodes at
  about 150-200 tokens/s. The live-merged LoRA gets no draft (`draftTokenCount: 0`) and
  decodes at about 45 tokens/s. Fireworks refuses `draftTokenCount` 15 for it without a draft
  model or n-gram speculation. So plain live merge is only 1.2-1.3x faster at p50.
- **N-gram speculation closes most of the gap.** It suits a model that copies spans out of its
  input. With `ngramSpeculationLength` 3 and `draftTokenCount` 8, the LoRA is **2.2x faster on
  agent traffic** (p50 1.03 s vs 2.28 s, p95 1.50 s vs 3.92 s) and 1.9x faster on smoke.
- **The Modal baseline is not like-for-like.** The zero-shot baseline on a Modal H100 (vLLM,
  no speculation) had a 9.4 s p50. The whole Fireworks setup is much faster than that.
- **It leaks more than zero-shot in the production pipeline.** Strict mode puts the rules in
  front (`rules + llm`). Zero-shot then leaks 0.7 % on smoke and 0.4 % on agent traffic; the
  LoRA leaks 2.9-4.4 % and 1.0-1.1 %. The LoRA misses person names (on both sets) and
  ID-document numbers (agent traffic), and the rules don't cover those. Zero-shot's misses on
  agent traffic are bank-account numbers.
- **Alone, the LoRA beats zero-shot on agent traffic.** As the only detector it scores F1 96.9
  vs 93.8 and leak 1.1 % vs 3.5 %, and it over-masks less. With the rules in front, though,
  the rules already catch what zero-shot misses, so the LoRA's lead disappears.
- **Run-to-run noise is real.** An earlier, superseded run of the LoRA on agent traffic (same
  deployment, first driver version) leaked 27 values with `llm` and 22 with `rules + llm`. The
  numbers above are 17 and 15. Batched GPU kernels are not bit-deterministic at temperature 0,
  so a few values' difference between rows is noise. The gap between zero-shot and the LoRA
  under `rules + llm` (6 vs 15-22 values on agent traffic) is bigger than that noise.
- **German** was not in the training data (hu + en only), yet the LoRA scores best on German
  agent traffic (F1 97.8, 0 leaks).
- **Neither model beats fast mode** (F1 96.1, 0.13 % leak, 0.02 s) on agent traffic.

**Outcome: fast but leaky.** The answer-only LoRA keeps the F1, cuts the output about 5x and,
with n-gram speculation, halves the latency. But it misses more names and ID numbers than
zero-shot Glimmer, so it is not a candidate for a production default.

## Template

**Fireworks ignores `chat_template_kwargs`.** Sent `{"reasoning_strength": "low"}`, the served
prompt (seen through `raw_output`) still ends the system turn with `Reasoning strength: high.`,
the template's default.

**`reasoning_effort: "low"` is what works.** Fireworks rejects a top-level
`reasoning_strength` (`Extra inputs are not permitted`) and maps `reasoning_effort` onto the
template instead. With `reasoning_effort: "low"`, the served prompt for the probe document is
byte for byte the training renderer's `reasoning_strength="low"` render. The renderer is
fw-ai/cookbook's `MuseGlimmerRenderer`, the one Serverless Training used, and both come to
1,128 prompt tokens.

So on Fireworks the detector setting is `PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=low`. vLLM
needs `..._REASONING_STRENGTH` instead.

## Cost and teardown

Fireworks Total Spend, account level (`billing/summary` line items, `usageCosts:query`):

| When (UTC) | On-demand GPU-hours | Spend |
|---|---|---:|
| 2026-10-28 16:26, before anything | none | $0.00 (only the 2026-10-27 Serverless Training line, rated $0) |
| 17:03, after the first two deployments were deleted | 0.44 (metering lags) | $3.53 |
| 17:18, all three deleted (metering still catching up) | 0.48 | $3.81 |

Metering lags by about an hour. From the deployment times below, the expected final figure is
about **$7.0**, if billing runs from each replica's ready time to its deletion (52.6 min). The
hard upper bound is $8.37, from wall time.

All three deployments were 1x H200 BF16 at $8.00 per GPU-hour (fireworks.ai/pricing, fetched
2026-10-28), billed per GPU-second with no charge for start-up:

| Deployment | Created | Ready | Deleted | Wall time |
|---|---|---|---|---:|
| `lab1109-lora` (live merge) | 16:31:34 | 16:34:43 | 17:02:09 | 30.6 min |
| `lab1109-base` (zero-shot) | 16:40:20 | 16:43:52 | 17:02:10 | 21.8 min |
| `lab1109-lora-ngram` (live merge + n-gram) | 17:03:18 | 17:06:50 | 17:13:44 | 10.4 min |

The wall times give an upper bound of 62.8 min x $8/h = **$8.37** of the $25 cap.

Safeguards on each deployment: `minReplicaCount 0`, `maxReplicaCount 1`,
`scaleToZeroWindow 600s`, and a watchdog that would have deleted it at a wall-clock limit.

Teardown checks:

- `GET deployments` returns `totalSize: 0`.
- With `showDeleted=true`, all three show `state: DELETED` with the delete times above.
- `firectl rlor-trainer-job list` is empty.

Nothing else was created: no training, no other models, no serverless inference.

## Reproduce

```bash
# 1x H200 live-merge deployment of the LoRA (REST, shape from deployment-shape-version match)
POST /v1/accounts/<account>/deployments?deploymentId=lab1109-lora
  {"baseModel": "accounts/<account>/models/pii-guard-glimmer-lab1109-v1",
   "deploymentShape": "accounts/fireworks/deploymentShapes/dkuwotf7",
   "minReplicaCount": 0, "maxReplicaCount": 1,
   "autoscalingPolicy": {"scaleToZeroWindow": "600s"}}
#   n-gram variant: add "ngramSpeculationLength": 3, "draftTokenCount": 8
#   zero-shot: "baseModel": "accounts/fireworks/models/muse-glimmer-30b"
export FIREWORKS_API_KEY=...   # from .env, never printed
M='accounts/<account>/models/pii-guard-glimmer-lab1109-v1#accounts/<account>/deployments/lab1109-lora'
uv run python training/llm/eval_fireworks.py --name lora-smoke --model "$M" \
  --fixtures eval/fixtures/hu-smoke.jsonl --fixtures eval/fixtures/en-smoke.jsonl
uv run python training/llm/eval_fireworks.py --name lora-agent-traffic-dev --model "$M" \
  --fixtures eval/synthetic/dev/hu-agent-traffic-dev.jsonl \
  --fixtures eval/synthetic/dev/en-agent-traffic-dev.jsonl \
  --fixtures eval/synthetic/dev/de-agent-traffic-dev.jsonl
DELETE /v1/accounts/<account>/deployments/lab1109-lora?ignoreChecks=true
```

Files:

- `<system>-<set>-llm.json` and `<system>-<set>-rules-llm.json` are full scorecards, with no
  text and no values.
- `<system>-<set>-docs.json` holds, per document, the latency, request and token counts, and
  the reasoning flags.
- `zeroshot-low-agent-traffic-dev-docs.json` is the exception. The first driver version wrote
  it, and that version matched requests to documents by their full text, so it missed the
  documents the pipeline splits. The file's per-document rows are dropped, and its summary is
  rebuilt from the scorecard's latency and the detector's usage counters (see its `note`).
