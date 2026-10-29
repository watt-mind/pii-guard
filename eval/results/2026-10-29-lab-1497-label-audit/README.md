# Gold-label audit: Gretel finance corrected, MAPA EUR-Lex checked (2026-10-29)

LAB-1497 (Gretel finance) and LAB-1511 (MAPA EUR-Lex). Evaluation labels only: no model was
trained or changed, and no headline set's upstream labels were edited. The live model is
`watt-mind/pii-guard-ner-xlmr-base@95f612a9` (v2.0).

## Gretel finance: 178 wrong gold labels, corrected in a separate set

LAB-1494's error mining found that most of v2.0's Gretel `PERSON` "misses" were not names.
Reading every distinct gold value of the **test** sample (275 de and 159 en `PERSON` values,
the other types in full; never any system's output) confirms it on the set we publish:
salutations (`Damen`, `Herren` from "Sehr geehrte Damen und Herren"), set phrases
(`Im Rahmen`, `Vielen Dank`), German "your + noun" phrases (`Ihr Vertrauen`), common nouns
(`Saldo`, `Stahl`), role words (`Schuldner`, `Valued Customer`), template slots
(`[Buyer's Name]`, `[Address]`, `phone number`) and codes (`123456789`, `BALI15`).

[`corrections.json`](../../datasets/gretel-finance/corrections.json) lists each class with
its rationale and the exact span texts. `python -m pii_guard.eval.datasets fetch
gretel-finance-corrected` applies it to the committed fixtures and writes a **separate** set;
`gretel-finance` keeps the upstream labels and every system keeps its upstream row. A
corrected span becomes an ignore region, so it is neither a leak when unmasked nor
over-masking when masked, for every system alike.

| Rule | Spans (de + en) |
|---|---:|
| `greeting-or-phrase` | 74 + 0 |
| `common-noun` | 45 + 1 |
| `possessive-noun-phrase` | 26 + 0 |
| `template-slot` (PERSON, ADDRESS, PHONE, EMAIL) | 10 + 7 |
| `role-word` | 9 + 2 |
| `code-not-a-name` (PERSON, EMAIL) | 1 + 3 |
| **total** | **178 of 1,710** (`PERSON` 694 → 524) |

Kept as gold on purpose: placeholder names used as a person's name (`Max Mustermann`,
`John Doe`), spans with a name next to a greeting (`Hallo Lola`), name-like user names
(`Carina20`), and address parts labelled `PERSON` (`Mettmann`, `An der Wupper`). Missing
labels are not added.

### Same predictions, both label sets (v2.0 and rules)

[`scripts/label_audit.py`](../../../scripts/label_audit.py) runs a system once and scores the
same predictions against both label sets, so the difference is label noise only
([`gretel-fast.json`](gretel-fast.json), [`gretel-rules.json`](gretel-rules.json); commit
`e6e2fc1`, clean):

| | Leak, upstream | Leak, corrected | de | en | `PERSON` leaked | F1 (overlap) | Over-masking |
|---|--:|--:|--:|--:|--:|--:|--:|
| **fast, NER v2.0** | 19.07 % (180/944) | **2.44 %** (19/778) | 29.1 → 2.3 % | 5.1 → 2.6 % | 162/516 → 6/357 | 0.717 → 0.758 | 21.8 → 21.8 % |
| rules only | 80.8 % (763/944) | 77.1 % (600/778) | 82.7 → 76.2 % | 78.2 → 78.1 % | 514/516 → 357/357 | 0.209 → 0.230 | 21.7 → 21.8 % |

161 of v2.0's 180 upstream leaks are values the corrections cover (`greeting-or-phrase` 70,
`common-noun` 44, `possessive-noun-phrase` 25, `template-slot` 14, `role-word` 7,
`code-not-a-name` 1). The run record of the corrected set reproduces 2.44 % exactly.

### Every system on the corrected labels

Run records `eval/results/runs/2026-10-29-{datasets,lab-1497}-gretel-finance-corrected-*.json`,
all from a clean commit (`e6e2fc1`; v2.0 fast `f2f9818`, which only changed its label),
CPU, the machine heavily loaded by a parallel training job (load average 15 to 185), so
**latency from these runs is not comparable** with the published rows; leak, F1 and
over-masking don't depend on load. "Upstream" is each system's published `gretel-finance` row
in [docs/benchmarks.md](../../../docs/benchmarks.md) (27–28 Oct; the comparison tools' code
hasn't changed since).

| System | Leak | F1 (overlap) | Over-masking |
|---|--:|--:|--:|
| **pii-guard fast, NER v2.0** | 19.0 → **2.4 %** | 71.4 → 75.8 % | 22.6 → 21.8 % |
| pii-guard NER v2.0 alone (no rules) | 20.3 → 4.1 % | 70.8 → 75.0 % | 22.4 → 22.0 % |
| rules + Wismut/nym-pii-multilingual | 21.8 → 5.8 % | 72.6 → 76.7 % | 27.2 → 26.8 % |
| rules + public fallback bardsai v1 | 21.2 → 6.6 % | 70.6 → 74.9 % | 32.4 → 31.0 % |
| rules + bardsai v3 | 23.3 → 7.5 % | 72.2 → 76.9 % | 16.4 → 15.6 % |
| rules + Horizon-Labs/pii-redactor-small | 23.7 → 8.0 % | 69.5 → 74.0 % | 18.8 → 18.4 % |
| Wismut/nym-pii-multilingual alone | 23.8 → 8.2 % | 72.0 → 76.1 % | 26.6 → 26.4 % |
| rules + Horizon-Labs/pii-redactor-base | 23.9 → 8.2 % | 71.7 → 76.2 % | 19.0 → 18.5 % |
| Horizon-Labs/pii-redactor-small alone | 27.0 → 11.8 % | 68.1 → 72.4 % | 18.1 → 18.1 % |
| Horizon-Labs/pii-redactor-base alone | 27.7 → 12.6 % | 70.4 → 74.8 % | 17.9 → 17.9 % |
| bardsai v3 alone | 27.8 → 12.7 % | 70.4 → 75.0 % | 15.1 → 14.7 % |
| PrivAiTe | 27.7 → 13.2 % | 47.8 → 50.1 % | 46.5 → 46.6 % |
| Presidio | 18.8 → 14.8 % | 29.4 → 28.8 % | 75.4 → 76.7 % |
| rules + tabularisai/eu-pii-safeguard ¹ | 29.8 → 15.3 % | 57.3 → 61.4 % | 25.6 → 25.2 % |
| tabularisai/eu-pii-safeguard alone ¹ | 35.1 → 21.7 % | 53.4 → 57.2 % | 25.7 → 25.7 % |
| LLM Guard | 59.3 → 51.3 % | 40.6 → 43.9 % | 17.0 → 17.0 % |
| pii-guard rules | 80.8 → 77.1 % | 20.9 → 23.0 % | 21.7 → 21.8 % |

¹ Same model and revision as LAB-1386's rows, run through `scripts/bench_ner_encoders.py`,
which records its decoder (`@decoder=first`), so the report keys it as its own system.

- **Every system gains, and the ranking changes.** On the upstream labels Presidio (18.8 %)
  edged v2.0 (19.0 %). On the corrected labels v2.0 has the lowest leak of the 17 systems
  (2.4 %); Presidio is at 14.8 %. Presidio gains least because it masks almost everything
  (76.7 % over-masking), so it was already masking `Damen` and `Saldo`.
- **What is left.** v2.0's 19 remaining leaks: `ADDRESS` 9/248, `PERSON` 6/357, `PHONE`
  2/47, `DATE_OF_BIRTH` 1/22, `ID_DOCUMENT` 1/28; `BANK_ACCOUNT` 0/29 and `EMAIL` 0/47.
  These weren't read value by value; the corrections never looked at them.
- **Not re-scored:** `pii-guard audit` (rules + NER + LLM, 20 documents, 2026-10-27), because
  it calls a remote model; and the unpublished NER candidates (v2.1, v3, v3.1, v3.2 soups),
  which aren't comparison systems.

## MAPA EUR-Lex: audited, no correction warranted

LAB-1494 found role words labelled `PERSON` ("Rapporteur", "Registrar", "agentes") in the
MAPA project's **validation** split (`joelniklaus/mapa`). The **test** set we publish
(`piimb/mapa-eur-lex-pii`, 42 documents) doesn't have them
([`mapa-fast.json`](mapa-fast.json), counts only; the text is real court text, read locally
and never sent anywhere, and no value was printed while auditing it):

- None of its distinct gold `PERSON` strings is one of 79 role words in the MAPA languages
  (`ROLE_WORDS` in `label_audit.py`). Its 1,028 `PERSON` spans hold no lower-case span.
- Of the 63 values v2.0 leaks (of 740), **41 are the same string, gold-labelled `PERSON`, in
  6 or more of the 21 language versions**, 9 in 2–5 and 13 in only one (7 of those share a
  4-letter prefix with a name in other languages: inflected forms). A name isn't translated;
  a role word is.

So the 8.5 % MAPA leak is model error, mostly lone surnames. It stays as published; nothing
was corrected and no `mapa-eur-lex-corrected` set exists.

## Reproduce

```
python -m pii_guard.eval.datasets fetch gretel-finance-corrected
python -m pii_guard.eval.datasets fetch mapa-eur-lex
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/label_audit.py gretel --system fast --json gretel-fast.json
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/label_audit.py gretel --system rules --json gretel-rules.json
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/label_audit.py mapa --json mapa-fast.json
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/bench_ner_encoders.py score \
    --sets gretel-finance-corrected --slug lab-1497 --record --summary unmapped-comparison.json \
    --configs ner-v20 fast-fallback-v1 bardsai-v3 fast-bardsai-v3 horizon-base fast-horizon-base \
              horizon-small fast-horizon-small wismut-nym fast-wismut-nym eu-pii-safeguard fast-eu-pii-safeguard
uv run --no-sync python -m pii_guard.eval.datasets run gretel-finance-corrected --system rules,fast --record
UV_PROJECT_ENVIRONMENT=.venv-baselines uv run --no-sync python -m pii_guard.eval.datasets \
    run gretel-finance-corrected --system presidio,llm-guard,privaite --record
```

**Cost:** $0. Local CPU only; no Modal, no Muse call, no remote model.
