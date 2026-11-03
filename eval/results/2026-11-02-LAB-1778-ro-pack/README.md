# Romanian language pack: smoke scores and the hu/en/de/pl check (LAB-1778)

Rules detector, offline, on CPU. *Before* is `origin/develop` at `48889d4` without an `ro`
pack; *after* is the same commit with the pack (`src/pii_guard/languages/ro/`). The Romanian
scorecard in this folder: [ro-smoke-rules.json](ro-smoke-rules.json) (the pack's three smoke
files together, as `pii-guard lang check ro` scores them).

## Romanian sets

| Rules | Docs | Labels | P overlap | R overlap | Leak | Over-masked | Round trip |
|---|---:|---:|---:|---:|---:|---:|---:|
| `ro-smoke` before | 12 | 56 | 100.0 | 17.9 | 81.1 % (43/53) | 0 | 100 |
| **`ro-smoke` after** | 12 | 56 | 100.0 | **57.1** | **39.6 %** (21/53) | 0 | 100 |
| `ro-smoke` + `eu/ro-smoke` + `eu/ro-inflection` before | 21 | 83 | 100.0 | 16.9 | 81.6 % (62/76) | 0 | 100 |
| **the same, after** | 21 | 83 | 100.0 | **48.2** | **47.4 %** (36/76) | 0 | 100 |
| `negative/ro-uncued-numbers` before / after | 12 | 0 | — | — | — | 0 / 0 | 100 |

After the pack, every structured value in the three smoke files is found: 14/14 identifiers
(CNPs, one with a bad check digit after its cue; CIFs with and without the `RO` prefix,
identity card series and numbers, a passport and a driving-licence number), 8/8 addresses,
8/8 phones, 5/5 e-mail addresses and 5/5 IBANs and cards. What leaks is the 32 names and 4
dates of birth, which the rules don't cover by design (the NER and LLM passes do). The two
hard negatives in `ro-smoke` and the twelve uncued numbers (order, invoice, receipt, case,
customer and AWB numbers, a valid CNP shape after `Factura nr.`, a mobile-shaped order number,
an EAN, amounts, dates, a postcode) mask nothing.

`eu/ro-smoke.jsonl` and `eu/ro-inflection.jsonl` (LAB-1525) keep their ids `0001`-`0005`; the
pack's own documents start at `0101`, since `lang check` loads all three files together. The
inflection set's leaks are names only: the rules find no names; the matcher's effect (a
confirmed `Maria` masks `Mariei` under its placeholder) is in the vault and is tested in
`tests/languages/test_ro.py` and the conformance property tests.

## hu/en/de/pl unchanged

Each set scored alone with `pii-guard eval --fixtures <set> --detectors rules`, before and
after. "Before = after" compares the whole scorecard (per-type detection, leak, over-masking
and round-trip counts; latencies and timestamps left out), not only the columns shown:

| Fixture set | Docs | P overlap | R overlap | Leak | Over-masked | Round trip | Before = after |
|---|---:|---:|---:|---:|---:|---:|:-:|
| `agent-text` | 90 | 100.0 | 56.1 | 43.7 | 0 | 100 | yes |
| `de-smoke` | 10 | 100.0 | 52.5 | 43.2 | 0 | 100 | yes |
| `de-synth-sample` | 14 | 100.0 | 33.1 | 57.0 | 0 | 100 | yes |
| `en-injection` | 31 | 100.0 | 43.7 | 56.3 | 0 | 100 | yes |
| `en-smoke` | 10 | 100.0 | 47.1 | 46.7 | 0 | 100 | yes |
| `en-synth-sample` | 10 | 100.0 | 37.5 | 46.2 | 0 | 100 | yes |
| `hu-company-names` | 44 | 100.0 | 61.3 | 2.5 | 0 | 100 | yes |
| `hu-inflection` | 12 | 100.0 | 14.8 | 84.0 | 0 | 100 | yes |
| `hu-injection` | 31 | 100.0 | 47.7 | 52.3 | 0 | 100 | yes |
| `hu-smoke` | 31 | 98.6 | 56.7 | 38.7 | 0 | 100 | yes |
| `hu-synth-sample` | 20 | 100.0 | 46.1 | 41.6 | 0 | 100 | yes |
| `negative/de-brand-names` | 6 | — | — | — | 0 | 100 | yes |
| `negative/de-uncued-numbers` | 11 | — | — | — | 0 | 100 | yes |
| `negative/en-brand-names` | 12 | — | — | — | 0 | 100 | yes |
| `negative/en-uncued-numbers` | 13 | — | — | — | 0 | 100 | yes |
| `negative/hu-brand-names` | 6 | — | — | — | 0 | 100 | yes |
| `negative/hu-uncued-numbers` | 17 | — | — | — | 0 | 100 | yes |
| `negative/pl-brand-names` | 6 | — | — | — | 0 | 100 | yes |
| `negative/pl-uncued-numbers` | 11 | — | — | — | 0 | 100 | yes |
| `pl-smoke` | 11 | 100.0 | 55.3 | 39.5 | 0 | 100 | yes |
| `public/de-ai4privacy` | 200 | 98.9 | 42.2 | 57.3 | 0 | 100 | yes |
| `public/en-ai4privacy` | 200 | 96.8 | 33.8 | 65.1 | 1 | 100 | yes |
| `public/hu-ai4privacy` | 200 | 100.0 | 36.4 | 63.6 | 0 | 100 | yes |
| `secrets/en-secrets` | 22 | 100.0 | 100.0 | 0.0 | 0 | 100 | yes |

The `EVERYWHERE` rule (the CNP), the Romanian cues and the Romanian reference words run on all
of these texts; none of them changes a count.

## Reproduce

```bash
uv run --no-sync pii-guard lang check ro
uv run --no-sync pii-guard eval --fixtures eval/fixtures/ro-smoke.jsonl \
    --fixtures eval/fixtures/eu/ro-smoke.jsonl --fixtures eval/fixtures/eu/ro-inflection.jsonl \
    --detectors rules --json ro-smoke-rules.json
uv run --no-sync pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl --detectors rules  # per set
```

*Before* is the same commands with `src/pii_guard/languages/ro/` moved out of the tree.
