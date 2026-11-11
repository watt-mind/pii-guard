# Dutch language pack: smoke scores and the hu/en/de/pl check (LAB-1777)

Rules detector, offline, on CPU. *Before* is `origin/develop` at `48889d4` without an `nl`
pack; *after* is the same commit with the pack (`src/pii_guard/languages/nl/`). The Dutch
scorecard in this folder: [nl-smoke-rules.json](nl-smoke-rules.json) (the pack's three smoke
files together, as `pii-guard lang check nl` scores them).

## Dutch sets

| Rules | Docs | Labels | P overlap | R overlap | Leak | Over-masking | Round trip |
|---|---:|---:|---:|---:|---:|---:|---:|
| `nl-smoke` before | 12 | 49 | 100.0 | 20.4 | 78.3 % | 0.0 | 100 |
| **`nl-smoke` after** | 12 | 49 | 100.0 | **61.2** | **34.8 %** | 0.0 | 100 |
| `nl-smoke` + `eu/nl-smoke` + `eu/nl-inflection` before | 21 | 77 | 100.0 | 19.5 | 77.5 % | 0.0 | 100 |
| **the same, after** | 21 | 77 | 100.0 | **49.4** | **46.5 %** | 0.0 | 100 |
| `negative/nl-uncued-numbers` before / after | 12 | 0 | — | — | — | 0.0 / 0.0 | 100 |

After the pack, every structured value in the three smoke files is found: 9/9 identifiers
(BSNs labelled, unlabelled, dotted and spaced, one with a failing elfproef after its cue;
passport, ID-card and driving-licence numbers after their cues), 10/10 addresses, 9/9 phones,
5/5 e-mail addresses and the IBANs and the card. What leaks is the 30 names and 4 dates of
birth, which the rules don't cover by design (the NER and LLM passes do). The two hard
negatives in `nl-smoke` and the twelve uncued numbers (order, invoice, credit-note, customer,
case and payment-reference numbers, elfproef-valid nine-digit numbers after those labels, a
KvK and a btw number, amounts, dates) mask nothing.

`eu/nl-inflection.jsonl` scores a higher leak after the pack (88.9 → 100 %): the rules find no
names in it either way, but with the pack's genitive matcher the leak check also counts
`Pieters` as a surface form of the unmasked `Pieter`. That is the measurement getting
stricter, not a regression.

`eu/nl-smoke.jsonl` and `eu/nl-inflection.jsonl` (LAB-1525) keep their ids `0001`-`0005`; the
pack's own documents start at `0101`, since `lang check` loads all three files together.

## hu/en/de/pl unchanged

Each set scored alone with `pii-guard eval --fixtures <set> --detectors rules`, before and
after. "Before = after" compares the whole JSON scorecard (per-type detection, leak,
over-masking and round-trip counts) except timings and the git metadata, not only the columns
shown:

| Fixture set | Docs | R overlap | F1 overlap | Leak | Over-masking | Round trip | Before = after |
|---|---:|---:|---:|---:|---:|---:|:-:|
| `agent-text` | 90 | 56.1 | 71.8 | 43.7 | 0.0 | 100 | yes |
| `de-smoke` | 10 | 52.5 | 68.9 | 43.2 | 0.0 | 100 | yes |
| `de-synth-sample` | 14 | 33.1 | 49.8 | 57.0 | 0.0 | 100 | yes |
| `en-injection` | 31 | 43.7 | 60.8 | 56.3 | 0.0 | 100 | yes |
| `en-smoke` | 10 | 47.1 | 64.0 | 46.7 | 0.0 | 100 | yes |
| `en-synth-sample` | 10 | 37.5 | 54.5 | 46.2 | 0.0 | 100 | yes |
| `hu-company-names` | 44 | 61.3 | 76.0 | 2.5 | 0.0 | 100 | yes |
| `hu-inflection` | 12 | 14.8 | 25.7 | 84.0 | 0.0 | 100 | yes |
| `hu-injection` | 31 | 47.7 | 64.6 | 52.3 | 0.0 | 100 | yes |
| `hu-smoke` | 31 | 56.7 | 72.0 | 38.7 | 0.0 | 100 | yes |
| `hu-synth-sample` | 20 | 46.1 | 63.1 | 41.6 | 0.0 | 100 | yes |
| `negative/de-brand-names` | 6 | — | — | — | — | 100 | yes |
| `negative/de-uncued-numbers` | 11 | — | — | — | — | 100 | yes |
| `negative/en-brand-names` | 12 | — | — | — | — | 100 | yes |
| `negative/en-uncued-numbers` | 13 | — | — | — | — | 100 | yes |
| `negative/hu-brand-names` | 6 | — | — | — | — | 100 | yes |
| `negative/hu-uncued-numbers` | 17 | — | — | — | — | 100 | yes |
| `negative/pl-brand-names` | 6 | — | — | — | — | 100 | yes |
| `negative/pl-uncued-numbers` | 11 | — | — | — | — | 100 | yes |
| `pl-smoke` | 11 | 55.3 | 71.2 | 39.5 | 0.0 | 100 | yes |
| `public/de-ai4privacy` | 200 | 42.2 | 59.2 | 57.3 | 0.0 | 100 | yes |
| `public/en-ai4privacy` | 200 | 33.8 | 50.1 | 65.1 | 0.4 | 100 | yes |
| `public/hu-ai4privacy` | 200 | 36.4 | 53.4 | 63.6 | 0.0 | 100 | yes |
| `secrets/en-secrets` | 22 | 100.0 | 100.0 | 0.0 | 0.0 | 100 | yes |

The `EVERYWHERE` rule (a labelled BSN), the Dutch cues and the Dutch reference words run on all
of these texts; none of them changes a count.

## Reproduce

```bash
uv run --no-sync pii-guard lang check nl
uv run --no-sync pii-guard eval --fixtures eval/fixtures/nl-smoke.jsonl \
    --fixtures eval/fixtures/eu/nl-smoke.jsonl --fixtures eval/fixtures/eu/nl-inflection.jsonl \
    --detectors rules --json nl-smoke-rules.json
uv run --no-sync pii-guard eval --fixtures eval/fixtures/hu-smoke.jsonl --detectors rules  # per set
```

*Before* is the same commands with `src/pii_guard/languages/nl/` moved out of the tree.
