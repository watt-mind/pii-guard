# A lexicon surname before a NER name joins the span (2026-10-30)

LAB-1359. Counts from `scripts/probe_ner_subword.py` (fast mode, rules + the published NER
`watt-mind/pii-guard-ner-xlmr-base@95f612a9ad65`, release v2.0), on one commit with the surname join in
`src/pii_guard/detect/ner_words.py` off (`before.json`) and on (`after.json`). `probe` is the
script's synthetic set of 220 fictional-surname names; `probe-real` is the same 220 values
over five real surnames that are everyday words (Kovács, Szabó, Molnár, Fekete, Takács). No
text and no values, only counts. The write-up is
`docs/journey/2026-10-30-lab-1359-preceding-surname.md`.

```
uv run --no-sync python scripts/probe_ner_subword.py --probe eval/fixtures/hu-inflection.jsonl \
  eval/fixtures/hu-smoke.jsonl \
  agent-traffic-dev=eval/synthetic/dev/hu-agent-traffic-dev.jsonl,eval/synthetic/dev/en-agent-traffic-dev.jsonl,eval/synthetic/dev/de-agent-traffic-dev.jsonl \
  cee-pii=eval/datasets/cee-pii/hu-cee-pii.jsonl,eval/datasets/cee-pii/en-cee-pii.jsonl \
  ai4privacy=eval/fixtures/public/hu-ai4privacy.jsonl,eval/fixtures/public/en-ai4privacy.jsonl,eval/fixtures/public/de-ai4privacy.jsonl
```
