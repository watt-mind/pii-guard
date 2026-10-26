# pii-guard vs Presidio, LLM Guard and PrivAiTe (2026-10-26)

Same fixtures, same scorer, every tool in its default configuration. How the tools are run,
the label mapping and the scoring rules: [docs/evaluation.md](../../../docs/evaluation.md#comparison-with-open-source-tools).
All values in the fixtures are fictional.

| | |
|---|---|
| Code | commit `62b64fc65593` (clean tree; every scorecard here) |
| Fixtures | `hu-smoke.jsonl` `292c687941f295cb`, `en-smoke.jsonl` `5983d84d8dfc9fe3` (hand-written); `hu-synth-sample.jsonl` `ed547228ddc329bb`, `en-synth-sample.jsonl` `2c7ab3d12880065d` (Muse-generated, `muse-spark-1.3-contributor`, corpus seed 2026) |
| Host | Apple Silicon arm64, macOS 26.5, 10 CPUs, CPU only |
| Presidio | presidio-analyzer / -anonymizer 2.2.365, spaCy 3.8.18, `en_core_web_lg` 3.8.0 (en), huSpaCy `hu_core_news_lg` 3.8.1 (hu) |
| LLM Guard | llm-guard 0.3.16 (presidio 2.2.358, transformers 4.51.3, torch 2.14.1), `Isotonic/deberta-v3-base_finetuned_ai4privacy_v2@9ea9927`, `en_core_web_sm` / `zh_core_web_sm` 3.8.0, language `en` |
| PrivAiTe | privaite 0.7.3 (presidio 2.2.365, onnxruntime 1.31.1, transformers 5.21.0), preset `onnx`: `openai/privacy-filter@7ffa9a0` (q4) + `en_core_web_lg` 3.8.0 + `fr_core_news_md` 3.8.0 |

Files: `smoke-rules-baselines.{json,md}`, `synth-rules-baselines.{json,md}` and
`smoke-{hu,en}-rules-llm.json` are the full scorecards (per entity type, exact and overlap, masking latency, unmapped labels);
[`comparison.md`](comparison.md) puts everything side by side.

Reproduce (the first run downloads a few GB of packages and models):

```bash
uv sync --extra baselines
uv run pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl --fixtures eval/fixtures/en-smoke.jsonl \
    --detectors rules --baselines presidio,llm-guard,privaite --json smoke-rules-baselines.json
uv run pii-guard eval --fixtures eval/fixtures/hu-synth-sample.jsonl --fixtures eval/fixtures/en-synth-sample.jsonl \
    --detectors rules --baselines presidio,llm-guard,privaite --json synth-rules-baselines.json
python -m pii_guard.eval.baselines.compare smoke-rules-baselines.json synth-rules-baselines.json
```

Detection metrics are deterministic (two runs gave identical numbers); latency varies by
a few tens of percent between runs.

## Results (hand-written smoke sets)

Overlap P/R/F1, leak and partial leak, over-masking, round trip in %; detection latency in ms.

### Hungarian (`hu-smoke`, 28 documents)

| System | P | R | F1 | F1 exact | Leak | Partial leak | Over-masking | Round trip | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pii-guard rules | 100.0 | 45.0 | 62.1 | 47.2 | 52.6 | 15.5 | 0.0 | 100.0 | 0.1 | 0.2 |
| pii-guard rules+llm | 98.2 | 98.2 | 98.2 | 86.6 | 1.0 | 1.0 | 0.0 | 100.0 | 10578 | 26002 |
| Presidio | 76.4 | 64.9 | 70.1 | 48.0 | 28.9 | 12.4 | 15.5 | n/a | 75.6 | 128.0 |
| LLM Guard | 57.1 | 43.2 | 49.2 | 5.0 | 49.5 | 4.1 | 41.7 | 100.0 | 61.4 | 86.8 |
| PrivAiTe | 47.5 | 53.2 | 50.2 | 23.2 | 19.6 | 10.3 | 26.6 | 100.0 | 60.1 | 120.1 |
