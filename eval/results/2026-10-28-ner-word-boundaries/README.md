# NER spans snapped to whole words (2026-10-28)

LAB-1338. Counts from `scripts/probe_ner_subword.py` (fast mode, rules + NER
`hdkiller/pii-guard-ner-xlmr-base@95f612a9ad65`), on one commit with the word snap
(`src/pii_guard/detect/ner_words.py`) off (`before.json`) and on (`after.json`). `probe` is
the script's synthetic set of 220 fictional names. No text and no values, only counts.
The write-up is `docs/journey/2026-10-28-lab-1338-ner-word-boundaries.md`.

```
uv run --no-sync python scripts/probe_ner_subword.py --probe eval/fixtures/hu-inflection.jsonl \
  eval/fixtures/hu-smoke.jsonl \
  agent-traffic-dev=eval/synthetic/dev/hu-agent-traffic-dev.jsonl,eval/synthetic/dev/en-agent-traffic-dev.jsonl,eval/synthetic/dev/de-agent-traffic-dev.jsonl \
  cee-pii=eval/datasets/cee-pii/hu-cee-pii.jsonl,eval/datasets/cee-pii/en-cee-pii.jsonl \
  ai4privacy=eval/fixtures/public/hu-ai4privacy.jsonl,eval/fixtures/public/en-ai4privacy.jsonl,eval/fixtures/public/de-ai4privacy.jsonl
```
