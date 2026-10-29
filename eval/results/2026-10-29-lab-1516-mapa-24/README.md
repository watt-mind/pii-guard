# MAPA EUR-Lex in every language it has: a measure-only baseline (2026-10-29)

LAB-1516. **Measure only: nothing was trained or tuned here.** This scores the production path,
pii-guard fast mode (rules + NER v2.0,
[`watt-mind/pii-guard-ner-xlmr-base`](https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base)
at `95f612a9ad65`), on every language of the MAPA EUR-Lex **test** split. It also scores NER
v2.0 alone, the rules alone and two public models that claim EU-wide coverage. The goal is to
say honestly where the model stands outside the three languages it is gated on (en, de, hu),
and to put the add-a-language roadmap in order.

**MAPA has 21 languages, not 24.** Both public copies list the same 21:
[`piimb/mapa-eur-lex-pii`](https://huggingface.co/datasets/piimb/mapa-eur-lex-pii) (the one
this repo loads, [dataset README](../../datasets/mapa-eur-lex/README.md)) and
[`joelniklaus/mapa`](https://huggingface.co/datasets/joelniklaus/mapa). **Croatian (hr), Polish
(pl) and Slovenian (sl)** are missing from the 24 official EU languages. Polish is measured
elsewhere, on pl-pii-bench (LAB-1400). Croatian and Slovenian have no test set yet. The Irish
rows have `en_GA` ids, so they were checked by word counts: they are Irish text, not English.

So the honest claim is **gated in 3 languages (en, de, hu), measured in 21 (MAPA), 22 with
Polish**.

## How it was run

All six runs came from one clean commit (`d3ac82e`, `code.dirty: false`), on CPU
(`PII_GUARD_NER_DEVICE=cpu`, `OMP_NUM_THREADS=3`). They ran locally rather than on Modal,
because the MAPA court text is never sent off the machine (dataset README; LAB-1419). Cost: $0.

```bash
uv run --no-sync python -m pii_guard.eval.datasets fetch mapa-eur-lex      # git-ignored fixtures
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/bench_ner_encoders.py score \
  --sets mapa-eur-lex --configs rules fast-v20 ner-v20 \
  --slug lab-1516 --key-tag baseline=lab-1516 --record
PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/bench_ner_encoders.py score \
  --sets mapa-eur-lex --configs fast-fallback-v1 ner-fallback-v1 eu-pii-safeguard \
  --slug lab-1516 --key-tag baseline=lab-1516 --record
```

- Run records: `eval/results/runs/2026-10-29-lab-1516-mapa-eur-lex-<config>.json`.
- Their system keys end in `@baseline=lab-1516`, so they get their own rows in
  [benchmarks.md](../../../docs/benchmarks.md#mapa-eur-lex-mapa-eur-lex-pii-test-split) and
  never replace the featured rows or the earlier MAPA rows.
- **Latency was withheld.** The shared machine had a load average between 18 and 199 during
  the runs, so `latency_ms` is null in these records. Use the published latency figures, not
  these runs.
- `fast-eu-pii-safeguard` (rules + that model) was **not run**, to keep the shared machine's
  load down. It isn't needed: on this set the rules never add a name, so "rules + model" and
  "model alone" leak the same for both v2.0 and bardsai v1 (tables below).
- Scoring is the repo's standard, with overlap matching.
  - **Leak** is per gold `PERSON` value. `ORGANIZATION` (employers) is a keep type, so it is
    scored for recall and never counts as a leak.
  - Case numbers, dates, occupations and the other MAPA labels are ignore regions
    ([dataset README](../../datasets/mapa-eur-lex/README.md)).
  - MAPA gets no label correction (LAB-1511 is looking at the role-word labels separately).

**Read small cells as small.** Every language has 2 documents and 33–38 distinct `PERSON`
values, so **one leaked value is about 3 percentage points**. The 95 % interval is Wilson's.
The English spans are hand-annotated. The other 20 languages were projected by an LLM and are
not exhaustively verified ([dataset README](../../datasets/mapa-eur-lex/README.md)).

## Per language: pii-guard fast (rules + NER v2.0)

The gated languages come first, then the rest by language family.

| lang | docs | gold spans: PERSON / ORG | PERSON values | **leak %** (values leaked) | 95 % CI | partial leak % | over-mask % | recall % | precision % | PERSON recall % | NER alone leak % | rules alone leak % |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **en** (gated) | 2 | 57 / 9 | 37 | **24.3** (9) | 13–40 | 0.0 | 20.0 | 69.7 | 80.0 | 80.7 | 24.3 | 100.0 |
| **de** (gated) | 2 | 50 / 9 | 34 | **5.9** (2) | 2–19 | 0.0 | 40.5 | 81.4 | 55.2 | 96.0 | 5.9 | 100.0 |
| **hu** (gated) | 2 | 49 / 11 | 35 | **2.9** (1) | 1–15 | 0.0 | 48.5 | 80.0 | 46.6 | 98.0 | 2.9 | 100.0 |
| es | 2 | 47 / 10 | 34 | **5.9** (2) | 2–19 | 0.0 | 41.7 | 78.9 | 55.3 | 95.7 | 5.9 | 100.0 |
| fr | 2 | 46 / 9 | 34 | **0.0** (0) | 0–10 | 0.0 | 46.8 | 83.6 | 51.6 | 100.0 | 0.0 | 100.0 |
| it | 2 | 50 / 10 | 34 | **2.9** (1) | 1–15 | 0.0 | 45.3 | 80.0 | 53.4 | 96.0 | 2.9 | 100.0 |
| pt | 2 | 50 / 10 | 37 | **5.4** (2) | 1–18 | 0.0 | 39.7 | 78.3 | 58.2 | 94.0 | 5.4 | 100.0 |
| ro | 2 | 50 / 11 | 34 | **2.9** (1) | 1–15 | 0.0 | 45.6 | 80.3 | 53.3 | 98.0 | 2.9 | 100.0 |
| nl | 2 | 46 / 11 | 33 | **6.1** (2) | 2–20 | 0.0 | 44.6 | 77.2 | 52.4 | 95.7 | 6.1 | 100.0 |
| da | 2 | 49 / 8 | 35 | **0.0** (0) | 0–10 | 0.0 | 35.4 | 84.2 | 60.5 | 98.0 | 0.0 | 94.3 |
| sv | 2 | 47 / 10 | 35 | **5.7** (2) | 2–19 | 0.0 | 40.3 | 78.9 | 59.0 | 95.7 | 5.7 | 100.0 |
| bg | 2 | 50 / 11 | 36 | **2.8** (1) | 0–14 | 0.0 | 40.2 | 80.3 | 51.1 | 98.0 | 2.8 | 100.0 |
| cs | 2 | 49 / 10 | 37 | **5.4** (2) | 1–18 | 0.0 | 44.2 | 79.7 | 54.0 | 95.9 | 5.4 | 100.0 |
| sk | 2 | 49 / 10 | 35 | **0.0** (0) | 0–10 | 0.0 | 42.9 | 83.1 | 49.0 | 100.0 | 0.0 | 100.0 |
| el | 2 | 44 / 10 | 36 | **5.6** (2) | 2–18 | 0.0 | 49.4 | 77.8 | 47.8 | 95.5 | 5.6 | 100.0 |
| et | 2 | 49 / 9 | 36 | **2.8** (1) | 0–14 | 0.0 | 48.5 | 82.8 | 46.2 | 98.0 | 2.8 | 97.2 |
| fi | 2 | 42 / 9 | 33 | **9.1** (3) | 3–24 | 3.0 | 56.9 | 76.5 | 38.8 | 92.9 | 9.1 | 93.9 |
| lt | 2 | 49 / 10 | 35 | **17.1** (6) | 8–33 | 0.0 | 47.9 | 72.9 | 46.8 | 87.8 | 17.1 | 100.0 |
| lv | 2 | 51 / 11 | 38 | **21.1** (8) | 11–36 | 0.0 | 51.1 | 66.1 | 45.2 | 80.4 | 21.1 | 100.0 |
| ga | 2 | 57 / 8 | 37 | **24.3** (9) | 13–40 | 0.0 | 40.5 | 72.3 | 58.8 | 82.5 | 24.3 | 100.0 |
| mt | 2 | 47 / 11 | 35 | **25.7** (9) | 14–42 | 0.0 | 92.5 | 62.1 | 7.3 | 74.5 | 25.7 | 100.0 |
| **all 21** | 42 | 1028 / 207 | 740 | **8.5** (63) | 7–11 | 0.1 | 55.6 | 77.3 | 41.8 | 92.8 | 8.5 | 99.3 |

The **all 21** row reproduces the earlier MAPA figure (8.5 %, LAB-1494) exactly, on a clean
commit this time.

## Against the comparison models

The comparison models are
[`bardsai/eu-pii-anonimization-multilang`](https://huggingface.co/bardsai/eu-pii-anonimization-multilang)
v1 (`62ca571`, Apache-2.0) and
[`tabularisai/eu-pii-safeguard`](https://huggingface.co/tabularisai/eu-pii-safeguard)
(`c928cd5`, XLM-R large).
- bardsai v1 is pii-guard's public fallback, fine-tuned for the 24 official EU languages.
- eu-pii-safeguard says it covers 26 EU languages. Its licence is conflicting (LAB-1386), so
  it is used for evaluation only.

Both ran inside pii-guard's own NER post-processing and resolver, as in LAB-1386 and LAB-1391.
These are leak rates, with leaked values out of the same gold values.

| lang | pii-guard fast (NER v2.0) leak % | bardsai v1 leak % | eu-pii-safeguard leak % | lowest |
|---|--:|--:|--:|---|
| en | 24.3 (9/37) | 32.4 (12) | 27.0 (10) | pii-guard |
| de | 5.9 (2/34) | 52.9 (18) | 20.6 (7) | pii-guard |
| hu | 2.9 (1/35) | 17.1 (6) | 22.9 (8) | pii-guard |
| es | 5.9 (2/34) | 32.4 (11) | 14.7 (5) | pii-guard |
| fr | 0.0 (0/34) | 20.6 (7) | 26.5 (9) | pii-guard |
| it | 2.9 (1/34) | 35.3 (12) | 23.5 (8) | pii-guard |
| pt | 5.4 (2/37) | 24.3 (9) | 18.9 (7) | pii-guard |
| ro | 2.9 (1/34) | 26.5 (9) | 14.7 (5) | pii-guard |
| nl | 6.1 (2/33) | 12.1 (4) | 21.2 (7) | pii-guard |
| da | 0.0 (0/35) | 22.9 (8) | 20.0 (7) | pii-guard |
| sv | 5.7 (2/35) | 34.3 (12) | 20.0 (7) | pii-guard |
| bg | 2.8 (1/36) | 33.3 (12) | 25.0 (9) | pii-guard |
| cs | 5.4 (2/37) | 32.4 (12) | 35.1 (13) | pii-guard |
| sk | 0.0 (0/35) | 22.9 (8) | 11.4 (4) | pii-guard |
| el | 5.6 (2/36) | 38.9 (14) | 25.0 (9) | pii-guard |
| et | 2.8 (1/36) | 25.0 (9) | 16.7 (6) | pii-guard |
| fi | 9.1 (3/33) | 15.2 (5) | 15.2 (5) | pii-guard |
| lt | 17.1 (6/35) | 45.7 (16) | 20.0 (7) | pii-guard |
| lv | 21.1 (8/38) | 18.4 (7) | 28.9 (11) | bardsai v1 (by 1 value) |
| ga | 24.3 (9/37) | 32.4 (12) | 21.6 (8) | eu-pii-safeguard (by 1 value) |
| mt | 25.7 (9/35) | 42.9 (15) | 28.6 (10) | pii-guard |
| **all 21** | 8.5 (63/740) | 29.5 (218) | 21.9 (162) | pii-guard |

| all 21 languages | leak % | partial % | over-mask % | recall % | precision % | F1 % |
|---|--:|--:|--:|--:|--:|--:|
| pii-guard fast (rules + NER v2.0) | **8.5** | **0.1** | 55.6 | **77.3** | 41.8 | **54.3** |
| NER v2.0 alone | 8.5 | 0.1 | 55.5 | 77.3 | 41.9 | 54.3 |
| rules alone | 99.3 | 0.4 | 100.0 | 0.0 | 0.0 | 0.0 |
| rules + bardsai v1 (= bardsai v1 alone) | 29.5 | 1.1 | 60.8 | 71.7 | 10.6 | 18.5 |
| eu-pii-safeguard alone | 21.9 | 7.3 | **33.7** | 53.9 | **49.7** | 51.7 |

## What it says

**v2.0 is strong zero-shot on most of the EU.** v2.0 was trained only on hu, en and de, so 18
of these 21 languages are zero-shot for it.
- 13 of those 18 leak at most 2 values (≤ 6.1 %).
  - Danish, French and Slovak leak none.
  - Bulgarian, Estonian, Italian and Romanian leak one each.
  - Czech, Greek, Spanish, Portuguese, Swedish and Dutch leak two each.
- Finnish leaks 3 (9.1 %).
- **Pooled over all 21, v2.0 leaks a quarter of what bardsai v1 leaks (8.5 % vs 29.5 %) and
  under half of what eu-pii-safeguard leaks (21.9 %).** It has the fewest leaks in 19 of the
  21 languages. In the other two it is one value behind: Latvian (bardsai v1) and Irish
  (eu-pii-safeguard).

**Where v2.0 is weak:**
- **Maltese, 25.7 % leak, and it over-masks badly.** 92.5 % of what it masks is not a gold
  span, at 7.3 % precision. That is the clearest out-of-distribution failure. Maltese mixes a
  Semitic grammar with Latin script, attached articles (`il-`, `l-`, `ta'`) and its own letters
  (ħ, ġ, ż).
- **Latvian (21.1 %) and Lithuanian (17.1 %).** In these Baltic languages names change their
  endings for case and gender. This is the weakest family, and both comparison models struggle
  here too.
- **Irish (24.3 %).** The Irish rows have the same number of gold `PERSON` spans as the English
  ones (57), and English leaks the same 24.3 %. Irish also changes the first letter of a word
  (lenition, eclipsis) and adds name prefixes (Ó, Mac, Ní, Nic).
- **English (24.3 %) is a gated language and the worst cell in it.** That is not a
  zero-shot problem. English is the only hand-annotated language: it has 57 gold `PERSON` spans,
  against 42–51 in the 19 languages other than English and Irish. LAB-1511 found that v2.0's
  MAPA leaks are mostly real standalone surnames in this court-document register, not label
  noise. A plausible but unproven reading: the LLM-projected languages miss some of the harder
  spans, so their leak rates may look better than they would on hand-annotated gold.

**Inflection alone doesn't predict the score.** The heavily inflected languages split in two:
- these do well: Hungarian 2.9 %, Estonian 2.8 %, Czech 5.4 %, Slovak 0 %, Finnish 9.1 %;
- these do badly: Lithuanian, Latvian, Irish and Maltese.

Exposure seems to matter more than how complex the grammar is. Hungarian was trained;
Estonian and Finnish are its Uralic relatives; Czech and Slovak names look like Central
European names the model has seen. The second group has scripts, mutations or name endings
that neither the fine-tuning data nor (much) XLM-R pretraining covers. This is a reading of
two documents per language, not a proven cause.

**The rules add nothing to names here.** That is by design: names are the NER's job. MAPA's
national-ID-like strings (case numbers, ECLI) are ignore regions, and MAPA labels no national
IDs, phone numbers or IBANs. **So MAPA measures name recall, not rule coverage.** The
rule-format items in the roadmap below can't be measured on it.

**Over-masking is high for everyone (34–61 %).** Part of it is MAPA's ignore-region policy:
masked dates, case parties and court names count against precision. LAB-1511 covers the label
side. eu-pii-safeguard over-masks least, but it finds a lot fewer names (64.8 % `PERSON` recall
against 92.8 %).

## Add-a-language roadmap (priority order, roadmap only)

Each item is a [language pack](../../../docs/languages.md) plus data. Order: worst measured
leak first, then the languages MAPA can't measure.

1. **Maltese (mt).**
   - Data: Maltese names (given names and surnames), and hard negatives for the over-masking
     (capitalised legal and institutional words, attached-article forms). These would be the
     first Maltese rows NER training has ever seen.
   - Rules: ID card number (7 digits and a letter), VAT `MT` + 8 digits.
   - Inflection: few changes on the names themselves, but article and preposition prefixes
     need splitting at token boundaries.
2. **Latvian and Lithuanian (lv, lt).**
   - Inflection is the main work: an inflection matcher for case and gender endings. Latvian:
     `-s`/`-š`/`-is` and `-a`/`-e`. Lithuanian: `-as`/`-is`/`-us`, with `-ienė`/`-aitė`/`-ytė`
     for women's surnames. Plus inflected training sentences.
   - Rules: Latvian personal code (DDMMYY-NNNNN, the newer `32` form), Lithuanian personal
     code (11 digits, checksum).
3. **Irish (ga).**
   - Inflection: initial mutations (lenition `h`, eclipsis prefixes) and the name particles
     Ó / Mac / Ní / Nic / Uí, in the matcher and the surface forms.
   - Rules: PPS number (7 digits and 1–2 letters, checksum).
   - Data: Irish rows, few.
4. **English court-register surnames (en, gated).** Not a new pack: this is a data item for
   the next NER round. It needs standalone surnames in formal and legal text without a title,
   the error family LAB-1511 describes.
5. **Croatian and Slovenian (hr, sl): no test set yet.** First a test set (MAPA has neither),
   then packs.
   - Rules: Croatian OIB (11 digits, ISO 7064), Slovenian EMŠO (13 digits, checksum) and tax
     number.
   - Inflection: Slavic case endings, close to Czech and Slovak, which v2.0 already handles.
6. **Finnish and Estonian (fi, et).**
   - Names are mostly found already, so the work is the matcher: Finnish case suffixes with
     consonant gradation, and Estonian's 14 cases.
   - Rules: Finnish personal identity code (DDMMYY, century sign, 3 digits, check character),
     Estonian personal code (11 digits, checksum).
7. **The rest (rules-only packs).** Names already leak ≤ 6 % zero-shot in bg, cs, da, el, es,
   fr, it, nl, pt, ro, sk and sv, so these packs mostly need their national ID formats. That
   follows the German and Polish pattern, where rules closed the gap (LAB-1433). None of these
   formats is in the rules today: es DNI/NIE, fr NIR, it codice fiscale, pt NIF, nl BSN, ro
   CNP, bg EGN, cs/sk rodné číslo, da CPR, sv personnummer, el AMKA. IBANs are already covered
   for every one of them.
   - **These IDs need their own fixtures**, synthetic as in the smoke and synth sets, because
     MAPA labels none of them.

## Headline facts (for the landing and evaluation copy owners)

- **Gated in 3 languages, measured in 21.** On MAPA EUR-Lex (real EU court opinions in 21
  official languages), pii-guard fast leaks **8.5 %** of person names pooled. Two public
  EU-multilingual models leak **21.9 %** (tabularisai/eu-pii-safeguard) and **29.5 %**
  (bardsai v1).
- **Zero-shot it holds up.** In 13 of the 18 languages it was never trained on, it leaks at most
  2 of about 35 names per language (≤ 6.1 %). It leaks fewest in 19 of 21 languages, and in the
  other two it is one name behind.
- **Where we are honest about weakness:** Maltese, Latvian, Lithuanian and Irish (17–26 %), and
  English court-register surnames (24 %, LAB-1511). Croatian and Slovenian aren't in MAPA, so
  there is no claim for them.
