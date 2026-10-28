# Polish language pack on pl-pii-bench (LAB-1400)

Fast mode is rules + the published NER v2.0 (`watt-mind/pii-guard-ner-xlmr-base`, weights
`sha256:4a9a598f…`), on CPU. *Before* is `origin/develop` at `793ddf9`, without a `pl` pack.
*After* is the same commit with the pack (`src/pii_guard/languages/pl/`). The NER is the same
in both. Run records:
[before](../runs/2026-10-28-lab-1400-pl-pii-bench-before.json),
[after](../runs/2026-10-28-lab-1400-pl-pii-bench-after.json),
[rules only, after](../runs/2026-10-28-lab-1400-pl-pii-bench-rules.json),
[pl-smoke rules](../runs/2026-10-28-lab-1400-pl-smoke-rules.json),
[pl-smoke fast](../runs/2026-10-28-lab-1400-pl-smoke-fast.json).

## Selection discipline

pl-pii-bench (`test`, all 346 documents of five lanes) is **report-only**. It has no dev
split, so the pack was written from the public format descriptions of each identifier and
tuned on two other sets:

- `eval/fixtures/pl-smoke.jsonl`: 11 hand-written documents, 2 of them hard negatives;
- a synthetic dev split: 60 documents from six templates (seed 1400, not committed), with
  valid identifiers, labelled identifiers whose check digit fails, and hard negatives
  (same-shape numbers after order, invoice and shipment labels).

pl-pii-bench was scored once, after the rules were fixed. The only follow-up was a
count-only attribution of the `negative` lane (which detector produced each mask, no text
read). Nothing was changed after it.

## Results

| Fast mode | Leak | `identifiers` leak | `core` | `address` | `inflection` | `negative` over-masked spans | Over-masking | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| before | 17.5 % (144/825) | 47.0 % (141/300) | 0.5 % (1/191) | 0.0 % (0/61) | 0.7 % (2/273) | 88 | 10.4 % | 84.4 % | 75.3 % | 79.6 % |
| **after** | **3.5 %** (29/825) | **9.0 %** (27/300) | 0.0 % (0/191) | 0.0 % (0/61) | 0.7 % (2/273) | 117 | 11.7 % | 87.2 % | 91.3 % | 89.2 % |

Rules only: leak 84.1 % → 54.1 %, F1 21.8 % → 54.7 %.

| Tuning sets, after | Leak | Over-masked spans | F1 |
|---|---:|---:|---:|
| pl-smoke, rules | 39.5 % (17/43: names, dates, organisations) | 0 | 71.2 % |
| pl-smoke, fast | 0.0 % (0/43) | 0 | 98.9 % |
| synthetic dev, fast | 0.0 % (0/220) | 9 (all NER, on order and shipment numbers) | — |

- **Every leaked identifier now fails its check digit.** In the generated number-validity
  split ([benchmarks.md](../../../docs/benchmarks.md#pl-pii-bench)), fast mode leaks 0 of the
  192 checksum-valid values and 27 of the 165 invalid ones.
- **The `negative` lane rose from 88 to 117 over-masked spans.** The validators reject every
  value there: the validated rules mask nothing in that lane. All 39 rule masks there come
  from the cue rule, which masks a labelled number whatever its check digit (`PESEL
  <11 digits>`). The NER had already masked 88 of those values. Masking a labelled
  identifier with a bad check digit is pii-guard's policy, since a mistyped real identifier is
  still personal data ([evaluation.md](../../../docs/evaluation.md#number-validity)). The
  benchmark counts those values as not personal data. So the ticket's "no rise above 88"
  criterion and the cue requirement conflict on this lane. We kept the policy and report the
  number.
- **hu/en/de unchanged.** Rules on the hu/en/de smoke, synth-sample, ai4privacy and negative
  sets, and fast mode on the hu/en/de smoke sets, give the same counts before and after.
  `make gate` passes.

## Reproduce

```bash
uv sync --extra ner
uv run --no-sync pii-guard lang check pl
PII_GUARD_NER_DEVICE=cpu uv run --no-sync pii-guard eval \
    --fixtures eval/datasets/pl-pii-bench/pl-pl-pii-bench.jsonl --detectors rules,ner
```

The per-lane split groups the scorecard's documents by `meta.lane`.
