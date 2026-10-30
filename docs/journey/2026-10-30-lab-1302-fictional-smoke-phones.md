# Smoke phones from the fictional ranges, headline rows re-recorded (2026-10-30)

LAB-1302, split out of LAB-1214. The Hungarian and German smoke fixtures had phone numbers
that weren't from ranges set aside for fiction. They now follow
[ADR 0005](../decisions/0005-synthetic-data-only.md): the German ones are Bundesnetzagentur
drama numbers, and the Hungarian ones use a real area code with an ascending-run or
`555 01xx` subscriber number ([`build_smoke.py`](../../eval/fixtures/build_smoke.py), 3 hu and
5 de values). That changes the fixtures' sha256, so every older hu/de smoke result is stale.
The rows behind the report and the landing are re-recorded from a clean commit, `18edc24`, all
in one pull request:

- rules only, fast mode (published NER v2.0) and Presidio, LLM Guard and PrivAiTe;
- the open-model comparison (`scripts/bench_ner_encoders.py`): five public encoders and the
  bardsai v1 fallback, alone and with the rules, plus pii-guard NER v2.0 alone;
- **audit mode as it ships now**: rules + NER v2.0 + Muse Spark Open on Baseten. The
  2026-10-27 audit row used the unpublished distilled NER checkpoint, which is gone, so this is
  a new row and the old one is kept for reference with `†`.

Leaked values on `smoke` (173 values, 51 documents), before (the latest earlier record) → after:

| system | leak | F1 | over-masking |
| -- | --: | --: | --: |
| fast (rules + NER v2.0) | 0 → 0 | 94.6 → 94.6 % | 1.1 → 1.1 % |
| rules only | 71 → 71 | 70.0 → 70.0 % | 0.0 → 0.0 % |
| audit (rules + NER + Muse Spark Open) | 1 → 0 | 98.2 → 96.2 % | 1.1 → 1.1 % |
| Presidio | 42 → 46 | 64.9 → 70.3 % | 27.5 → 19.0 % |
| LLM Guard | 78 → 78 | 53.2 → 53.2 % | 36.7 → 36.7 % |
| PrivAiTe | 22 → 22 | 55.2 → 54.7 % | 25.8 → 25.8 % |
| rules + Wismut/nym-pii-multilingual | 7 → 6 | 90.6 → 90.1 % | 6.0 → 6.0 % |
| pii-guard NER v2.0 alone | 6 → 8 | 89.3 → 89.8 % | 1.1 → 1.1 % |

Fast mode and rules only score exactly the same on the new numbers, as LAB-1214 predicted.
Presidio moved mostly because its run now loads the German spaCy model `de_core_news_lg`,
which the `baselines` extra pins but the 2026-10-30 LAB-1496 environment didn't have (German
over-masking 44 → 16 %, German leaks 4 → 8). The encoder rows moved by at most two leaked
values or a few tenths of F1. The audit row isn't comparable one to one with the old one: it uses a
different NER.

Left stale with `†` (en-only snapshot): historical NER candidates and ablations (v2 base and
large variants, v2.1 epochs, v3 to v4 candidates, GLiNER, the distilled checkpoints) and the
earlier LLM rows (Muse Glimmer, Muse Spark 1.3, rules + Muse Spark Open). They were
model-selection steps and none of them ships. Records
`eval/results/runs/2026-10-30-lab-1302-*.json` (18). Cost: $0.27 Baseten, two audit runs of
51 requests each (the first at `3449736`, redone after LAB-1199's cue rules merged; same
counts), about 59k prompt tokens (32k cached) and 24k completion per run, at $1.25 / $0.15 /
$4.25 per million; everything else on local CPU.
