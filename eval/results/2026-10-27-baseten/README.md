# Muse Spark Open on Baseten as the LLM detector (2026-10-27)

`rules,llm` with the LLM detector on Baseten Model APIs: Meta's open-weight Muse Spark Open,
`meta-models/muse-spark-open-1026`, `reasoning_effort: low`, JSON mode, `temperature: 0`.
Same scorer and fixtures as [2026-10-26-baselines](../2026-10-26-baselines/README.md). All
values in the fixtures are fictional.

| | |
|---|---|
| Code | commit `5dd3c23cbe9b` (clean tree; every scorecard here) |
| Fixtures | `hu-smoke.jsonl` `3766a651708e8749` (31 documents), `en-smoke.jsonl` `5983d84d8dfc9fe3` (hand-written); `hu-synth-sample.jsonl` `ed547228ddc329bb`, `en-synth-sample.jsonl` `2c7ab3d12880065d` (Muse-generated) |
| Endpoint | `https://inference.baseten.co/v1`, Baseten Model APIs (shared, hackathon credits) |
| Client | Apple Silicon arm64, macOS 26.5, one request at a time |
| Price | $1.25 / 1M input, $0.15 / 1M cached input, $4.25 / 1M output tokens ([baseten.co/pricing](https://www.baseten.co/pricing/), 2026-10-27); reasoning tokens bill as output |

Files: `<fixture>-rules-llm.{json,md}` are the full scorecards (per entity type, exact and
overlap, leak, over-masking, consistency, latency); `usage.json` has the token counts the
endpoint reported for each run (`LlmDetector.usage`), cost, refusal and invalid-output rates.

Reproduce (about $0.20 for all four):

```bash
export PII_GUARD_LLM_DETECTOR_API_KEY=$BASETEN_API_KEY   # URL and model are the defaults
export PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=low
for f in hu-smoke en-smoke hu-synth-sample en-synth-sample; do
  uv run pii-guard eval --fixtures eval/fixtures/$f.jsonl --detectors rules,llm \
      --json $f-rules-llm.json --markdown $f-rules-llm.md
done
```

## Results

Overlap P/R/F1, leak, partial leak, over-masking in %; detection latency per document in
seconds; cost per 1,000 messages (one message = one fixture document) at the prices above.

| Fixture | Docs | P | R | F1 | F1 exact | Leak | Partial leak | Over-masking | p50 s | p95 s | $ / 1k msgs | $ / 1k, no cache |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `hu-smoke` | 31 | 97.6 | 99.2 | 98.4 | 92.2 | 0.9 | 0.9 | 0.0 | 1.8 | 4.0 | 2.42 | 3.30 |
| `en-smoke` | 10 | 94.4 | 100.0 | 97.1 | 94.3 | 0.0 | 3.3 | 3.2 | 1.2 | 3.7 | 1.99 | 2.70 |
| `hu-synth-sample` | 20 | 100.0 | 100.0 | 100.0 | 99.3 | 0.0 | 0.0 | 0.0 | 2.1 | 3.0 | 3.57 | 4.94 |
| `en-synth-sample` | 10 | 100.0 | 98.3 | 99.2 | 99.2 | 2.5 | 6.2 | 0.0 | 2.1 | 2.6 | 2.91 | 3.98 |

"No cache" prices every prompt token at the full input rate (Baseten reported 87–92 % of
prompt tokens as cached here, because the system prompt repeats). Per document: about
740–1,380 prompt tokens and 420–760 completion tokens, of which 340–530 are reasoning.

**Run-to-run variation.** The four fixtures were run four times on 2026-10-27 (three earlier
runs on equivalent code are not committed). Ranges over the four runs: overlap F1 `hu-smoke`
97.5–98.4, `en-smoke` 97.1–100.0, `hu-synth-sample` 100.0, `en-synth-sample` 98.3–99.2; leak
`hu-smoke` 0.9, `en-smoke` 0.0, `hu-synth-sample` 0.0, `en-synth-sample` 2.5–5.0 (missed
English names); p50 1.2–2.1 s, p95 2.6–5.7 s; $1.99–4.00 per 1k messages.

**Refusals: 0.** Across 284 detector requests (4 runs × 71 documents) there were 0 refusals and
0 invalid outputs (every response was valid JSON with `finish_reason: stop`, no retry). In
probing, a bare extraction prompt without the detector's system framing was refused; the
detector's system prompt avoids that.

## Compared with Muse Spark 1.3 and Muse Glimmer

| System | Fixtures | P | R | F1 | Leak | p50 s | p95 s |
|---|---|---:|---:|---:|---:|---:|---:|
| rules + **Muse Spark Open** on Baseten, `low` (this run) | `hu-smoke` (31 docs) | 97.6 | 99.2 | 98.4 | 0.9 | 1.8 | 4.0 |
| rules + Muse Spark 1.3, Meta Model API ([2026-10-26](../2026-10-26-baselines/README.md)) | `hu-smoke` (28-doc version) | 98.2 | 98.2 | 98.2 | 1.0 | 10.6 | 26.0 |
| rules + **Muse Spark Open** on Baseten, `low` (this run) | `en-smoke` | 94.4 | 100.0 | 97.1 | 0.0 | 1.2 | 3.7 |
| rules + Muse Spark 1.3, Meta Model API ([2026-10-26](../2026-10-26-baselines/README.md)) | `en-smoke` | 94.4 | 100.0 | 97.1 | 0.0 | 7.0 | 29.3 |
| rules + Muse Glimmer 30B, vLLM on 1× H100, `reasoning_strength: low` (LAB-1109, scorecard not committed) | `hu-smoke` (28) + `en-smoke` | | 100.0 | 99.3 | 0.0 | 9.4 | 20.7 |

Reading: on the same hand-written smoke sets, Muse Spark Open on Baseten matches Muse Spark 1.3
on quality (F1 within a point, leak at most one value) and is about 5–6× faster at the median
and 6–8× faster at p95. Glimmer's zero-shot quality is as good or slightly better, but at
roughly 9 s per document it is a teacher model (see [docs/models.md](../../../docs/models.md)),
not a request-path detector. Caveats: the Muse Spark 1.3 numbers are from an older commit and
the 28-document version of `hu-smoke`, and their reasoning effort was not recorded; the Glimmer row is
pooled over hu + en from a run on an older commit. There is no committed `rules,llm` run of
Muse Spark 1.3 on the synth samples (LAB-1103).

## Spend

Baseten, all of LAB-1108: about **$0.84** of the $100 credit (four eval runs $0.22, $0.20,
$0.20, $0.20 = $0.82; recording the test fixture and the live tests about $0.02). Computed from
the token counts each response reported, at the list prices above.
