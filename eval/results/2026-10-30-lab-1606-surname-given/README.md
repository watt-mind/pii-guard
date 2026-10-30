# A lexicon surname + given name is a name without a model span (2026-10-30)

LAB-1606. Counts from `scripts/probe_ner_subword.py` (fast mode, rules + the published NER
`watt-mind/pii-guard-ner-xlmr-base`, release v2.0), local CPU, on `develop` `890a6f6`
(`before.json`) and this branch (`after.json`). No text and no values, only counts. The
write-up is `docs/journey/2026-10-30-lab-1606-lexicon-surname-given-name.md`.

```
uv run --no-sync python scripts/probe_ner_subword.py --probe eval/fixtures/hu-inflection.jsonl \
  eval/fixtures/hu-smoke.jsonl \
  agent-traffic-dev=eval/synthetic/dev/hu-agent-traffic-dev.jsonl,eval/synthetic/dev/en-agent-traffic-dev.jsonl,eval/synthetic/dev/de-agent-traffic-dev.jsonl \
  cee-pii=eval/datasets/cee-pii/hu-cee-pii.jsonl,eval/datasets/cee-pii/en-cee-pii.jsonl \
  ai4privacy=eval/fixtures/public/hu-ai4privacy.jsonl,eval/fixtures/public/en-ai4privacy.jsonl,eval/fixtures/public/de-ai4privacy.jsonl
```

`other-hu-sets.json` scores the other committed Hungarian fixtures (company names, agent
text, brand names, uncued numbers, injection, synth sample) with the same measure, the new
rule off (`before`) and on (`after`) in one process. MAPA and TAB rows are not on this
machine, so they were not scored; the rule only runs for Hungarian.
