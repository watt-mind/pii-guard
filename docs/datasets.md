# Evaluation datasets

PII Guard is scored on more than its own hand-written fixtures. This page lists every
registered dataset: where it comes from, its license, what is committed, how its labels map to
PII Guard types, and which split it belongs to. The registry lives in
[`src/pii_guard/eval/datasets/`](../src/pii_guard/eval/datasets/), one module per dataset.
Results, with bootstrap confidence intervals, are in
[benchmarks.md](benchmarks.md#results-per-dataset).

## Split policy

Every dataset declares one split:

- **`test`**: held out. Never used to write or tune a rule, to train or select an NER model, or
  to pick a threshold. Headline numbers only come from `test` splits.
- **`dev`**: may be looked at and tuned on. Never reported as a headline.

[`tests/eval/test_datasets_disjoint.py`](../tests/eval/test_datasets_disjoint.py) enforces this.
It hashes every `test` document (SHA-256 of the whitespace-folded text; the manifests carry
the hashes, so this works for sets whose text isn't committed). It then asserts that none of
them appears in:

- the NER v2 training inputs (LAB-1150). The hard negatives are regenerated from their seed.
  The OpenPII train rows were sampled by a script that refused every evaluation uid and text,
  and the test checks that this is recorded. Where the generated corpora exist locally, every
  train and dev file of the `training/ner/v2-*.toml` configs is checked too;
- the rule fixtures in `eval/fixtures/`, which rules are written and tuned against;
- any `dev` split.

Hash equality only catches exact copies. The **decontamination gate**
([`training/ner/decontam.py`](../training/ner/decontam.py), LAB-1392) also catches near
copies: it compares every training and dev document with every evaluation text (every `test`
set here and every `dev` set, which NER candidates are selected on, by text where it is on disk and by manifest hash always, plus every fixture under
`eval/fixtures/`) and drops a document whose word-5-gram Jaccard similarity to one of them is
0.8 or more. `training/ner/train.py` runs it by default; see
[evaluation.md](evaluation.md#decontamination).

## Datasets

| Set | Source | License | Languages | Docs | Split | Text committed |
|---|---|---|---|---:|---|---|
| `ai4privacy` | [Ai4Privacy OpenPII 1M](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m), `validation` @ `ecfdc54` | CC-BY-4.0 | hu, en, de | 600 | test | yes (synthetic) |
| `gretel-finance` | [gretelai/synthetic_pii_finance_multilingual](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual), `test` @ `7b844d1` | Apache-2.0 | en, de | 400 | test | yes (synthetic) |
| `gretel-finance-corrected` | `gretel-finance` with [committed label corrections](#corrected-labels) | Apache-2.0 | en, de | 400 | test (variant) | rebuilt locally from the committed rows |
| `nemotron-pii` | [nvidia/Nemotron-PII](https://huggingface.co/datasets/nvidia/Nemotron-PII), `test` @ `b70ffaf` | CC-BY-4.0 | en | 300 | test | yes (synthetic) |
| `cee-pii` | [flowxai/cee-pii-bench](https://huggingface.co/datasets/flowxai/cee-pii-bench) v0.2 @ `84ee883` | Apache-2.0 | hu, en | 451 | test | yes (synthetic) |
| `pl-pii-bench` | [pl-pii-bench/pl-pii-bench](https://huggingface.co/datasets/pl-pii-bench/pl-pii-bench) v1.0.0 @ `bef947d` | CC-BY-4.0 | pl | 346 | test | yes (synthetic) |
| `mapa-eur-lex` | [piimb/mapa-eur-lex-pii](https://huggingface.co/datasets/piimb/mapa-eur-lex-pii), `test.jsonl` @ `a44958f` | CC-BY-4.0 | 21 EU languages | 42 | test | **no**: real EU court documents |
| `tab-echr` | [TAB](https://github.com/NorskRegnesentral/text-anonymization-benchmark), `echr_test.json` @ `558e09e` | MIT (annotations) | en | 40 | test | **no**: real court documents |
| `agent-traffic` | PII Guard's seeded generator ([below](#synthetic-agent-traffic)) | Apache-2.0 | hu, en, de | 990 | test | yes (generated) |
| `agent-traffic-dev` | the same generator, another seed | Apache-2.0 | hu, en, de | 300 | dev | yes (generated) |
| `cee-dev` | PII Guard's CEE reference generator ([below](#synthetic-cee-references)) | Apache-2.0 | hu, en | 240 | dev | yes (generated) |

Attribution, as the licenses require:

- Ai4Privacy / Ai Suisse SA (CC-BY-4.0).
- Gretel.ai (Apache-2.0).
- NVIDIA Corporation, *Nemotron-PII: Synthesized Data for Privacy-Preserving AI* (2025),
  CC-BY-4.0.
- FlowX.AI, *CEE-PII-Bench v0.2* (Apache-2.0).
- *pl-pii-bench, version 1.0.0*, Anonimator, CC BY 4.0.
- camillevanhoffelen, *MAPA EUR-LEX PII* (CC-BY-4.0), built from the MAPA project's EUR-Lex
  test split (de Gibert Bonet, García Pablos, Cuadros and Melero, LREC 2022); the texts are
  EUR-Lex documents of the Court of Justice of the EU.
- Pilán, Lison, Øvrelid, Papadopoulou, Sánchez and Batet, *The Text Anonymization
  Benchmark (TAB)*, Computational Linguistics 48(4), 2022. Annotations MIT; the judgments are
  public ECHR documents from HUDOC.

Each set's manifest is `eval/datasets/<set>/manifest.json`; for Ai4Privacy it is
`eval/fixtures/public/ai4privacy-openpii-1m.json`. A manifest holds:

- the source URL, the pinned revision and the SHA-256 of each file;
- the license and attribution;
- the split;
- the seed and the sample rule (per language, rows ordered by `sha256("<seed>:<uid>")`, the
  first *n* that convert);
- the full label mapping;
- per language, the sampled ids, the document hashes and the counts of gold, policy-excluded
  and unknown labels.

**Why each set is here**

- **`gretel-finance`**: long financial documents (EDI messages, loan agreements, statements)
  and German text. Its labels were made during generation and checked with GLiNER, so some
  values are unlabeled or mislabeled. This shows up as over-masking for every system. Many
  of its `PERSON` labels aren't names (`Damen`, `Saldo`, `[Borrower Name]`), which shows up as leaks
  for every system; [`gretel-finance-corrected`](#corrected-labels) scores the same documents
  with those corrected. A few
  generated documents contain credentials: a Slack-style token, a JWT, or an API key after
  `API key:`. These rows are skipped (`skipped_unconvertible`). Secret scanning (GitHub push
  protection and gitleaks) rejects them, a public dataset's token can't be shown to be fake,
  and secrets aren't part of this text benchmark. Every loader applies this rule
  (`holds_credential`).
- **`nemotron-pii`**: 55 labels across 50+ industries, half of them US conventions. Rows whose
  span text doesn't match the offsets, or that hold a credential, are skipped and counted (22
  of the first ones drawn).
- **`cee-pii`**: the only public set we found with Hungarian identifiers (checksum-valid TAJ
  numbers). It adds deliberate noise (stripped diacritics, OCR confusions) and unlabeled
  order and tracking numbers. Another detector's authors wrote it as their benchmark, so it
  is a fair third-party set for PII Guard.
- **`pl-pii-bench`**: the first Polish set. It was scored before the `pl` language pack existed
  (LAB-1392) and again with it (LAB-1400, report-only: the pack was tuned on other sets). It has complete, exhaustively annotated synthetic administrative documents, so precision is
  meaningful. Its identifiers are checksum-valid, and a separate negative lane holds
  same-shape values that fail their check digits. An inflection lane puts names in all seven
  Polish cases. Five of its seven public lanes are used; the `robustness` and `pdf` lanes
  are re-renderings of `core` and are left out. Its card asks that nobody train on it. PESEL,
  ID card, passport, driving license and NIP are `ID_DOCUMENT`; REGON (a business number)
  and VIN have no PII Guard type. Its maintainer also maintains one of the systems it
  scores.
- **`mapa-eur-lex`**: two long Advocate General opinions in 21 EU languages, including
  Hungarian, Czech, Slovak and Romanian. It is the only set with most EU languages, and the
  only parallel one: the same names appear in every language. The English labels are
  hand-made; the other languages' labels were projected by an LLM and not fully checked.
  Names (`first_name`, `last_name`) are `PERSON` and `employer` is `ORGANIZATION`. Case
  numbers and the demographic labels are ignore regions. Like TAB, the text is real and
  never committed.
- **`tab-echr`**: real, long legal text with names of applicants, lawyers, judges and
  witnesses. It is a names stressor that nobody generated.

**Rejected candidates**

- **WikiANN** (hu/de/en). Its card lists the license as *unknown*, and its names are real
  people. The license can't be verified, so the set is dropped.
- **The other Ai4Privacy releases** (300k/400k, PII-Masking-2M). Their licenses don't allow
  this use, which is also why only OpenPII is used.
- **An OpenPII `test` split.** OpenPII publishes only `train` and `validation`. The
  evaluation sample comes from `validation`, which NER v2 never trained on, so `validation`
  is the registry's `test` split.

## Label mapping

Each dataset's labels map to [PII Guard types](entities.md). The rules match the Ai4Privacy
conversion:

- **Policy-excluded labels become ignore regions.** These are labels PII Guard has no type
  for: any date, IP and MAC addresses, customer and employee ids, PINs, passwords, API keys,
  user names, health and demographic attributes, routing and SWIFT codes, and contract or
  policy references. An ignore region (`meta.ignore`: offsets and label, no value) is left
  out of the gold spans, so it is never a leak and never recall. A prediction on it is
  neither credited nor charged in precision and over-masking.
- **Adjacent parts of one type are merged into one span.** A given name and a surname, or a
  street and a building number, separated only by spaces or a comma (≤ 3 characters), become
  one span.
- **Address parts count only inside an address.** A city, state, county or postcode merged
  into an address is `ADDRESS`. On its own it is an ignore region, because PII Guard keeps a
  town on its own.
- **Company names are `ORGANIZATION`**, a `keep` type. They count for recall but are never a
  leak.

The full mapping, with a note per label, is in each manifest's `label_mapping`.

## Synthetic agent traffic

[`synthetic.py`](../src/pii_guard/eval/datasets/synthetic.py) writes the traffic an AI gateway
sees, in Hungarian, English and German: 330 test and 100 dev documents per language. Same seed,
same bytes: `python -m pii_guard.eval.datasets check agent-traffic agent-traffic-dev`
rebuilds them and compares.

- **Gold comes from construction.** Values are inserted into templates, and the gold spans are
  where they went. No model labels anything.
- **The values are fictional.** Hungarian and English people and companies come from
  `pii_guard.eval.identities`; German ones come from common first and last names combined at
  random. Email domains are the reserved `example.*` ones.
- **Shapes** (`meta.shape`):
  - an OpenAI tool call, whose `arguments` is a JSON string inside JSON;
  - a nested JSON record;
  - YAML;
  - CSV;
  - log lines;
  - Python code with an email address and an API key;
  - an email thread with a quoted reply;
  - a multi-turn chat, as JSON messages or a transcript;
  - Hungarian prose with inflected names (`Kovács Annának`, `Nagy Péterrel`); English and
    German get a free-text call note instead.
- **Checksums.**
  - The identifiers pass their check digits: adóazonosító and TAJ for Hungarian, Steuer-ID
    for German, IBANs, and Luhn card numbers.
  - The exception is 15 %, which are altered so they fail. They are marked in
    `meta.checksum`, and the report shows leak for valid and invalid ones separately.
  - A mistyped identifier is still personal data, so invalid ones stay in the headline leak
    rate.
- **Perturbations.** 18 % of values get one perturbation, marked in `meta.perturbed`:
  - spaced or dotted digits;
  - a Cyrillic look-alike letter;
  - a zero-width space;
  - a name broken over two lines, only where a newline doesn't break the format;
  - a leetspeak email (`4nn4 [at] example [dot] com`).
- **Hard negatives** are never labeled: order and invoice numbers, SKUs, request ids,
  amounts, dates that aren't birth dates, and large public companies in context (`OTP Bank`,
  `Siemens`, `Microsoft`). Masking one is over-masking. API keys in code are ignore regions,
  because the text policy has no secret type.
- **No LLM-written prose.** The ticket allowed it within free credits, but template text keeps
  the gold exact.

## Synthetic CEE references

`cee-pii` over-masks reference and tracking numbers, but it is a test split, so its spans must
not be read to tune against (LAB-1344). [`cee_dev.py`](../src/pii_guard/eval/datasets/cee_dev.py)
writes a dev split to tune on instead: 120 Hungarian and 120 English documents in the same
kinds of register (bank statement lines, chats, support tickets, emails, form fields, OCR-ish
fragments without accents, shipping notices, SMS), written from scratch.
`python -m pii_guard.eval.datasets check cee-dev` rebuilds it and compares.

- **Real identifiers**, gold from construction, from the agent-traffic values: names, emails,
  phones, IBANs and giro accounts, cards, TAJ and tax numbers, UK national insurance and
  passport numbers, with the same checksum failures and perturbations.
- **Hard negatives**, never labeled, listed per document in `meta.negatives`: 13-digit epoch
  milliseconds and 14-digit `yyyymmddhhmmss` stamps (also after a short letter prefix, such as
  `TR…`), UPS `1Z…` and UPU S10 tracking numbers with valid check digits, GLS- and DPD-style
  parcel numbers, and CEE order and invoice formats (`SZLA-2026-004812`, `2026/004812`,
  `HU-260412-8812`). Half follow a label that names them; the rest follow a neutral word
  (`ref`, `hivatkozás`, `közlemény`) or none. In the OCR register some get an `O` for a `0`.

## Corrected labels

Some gold labels in a public set are plainly wrong, and every system pays for them as leaks.
We never edit an upstream set because of that. Instead, a committed corrections file lists
each class of error, why it is an error, and the exact span texts it covers. A **separate**
set is built from it, so every system has two numbers side by side: on the set as published
upstream, and on the corrected set.

| Corrected set | Built from | Corrections | Spans corrected | Text committed |
|---|---|---|---:|---|
| `gretel-finance-corrected` | `gretel-finance` (same 400 documents) | [`gretel-finance/corrections.json`](../eval/datasets/gretel-finance/corrections.json) | 178 of 1,710 | no: rebuilt locally from the committed rows |

```bash
python -m pii_guard.eval.datasets fetch gretel-finance-corrected   # data/ + manifest
python -m pii_guard.eval.datasets check gretel-finance-corrected   # rebuild, compare
```

**The rule.** A correction matches a gold span of one of its entity types whose text (whitespace
runs collapsed) equals one of its listed values exactly. It reads the span's own text and never
any system's output. A matched span stops being gold and becomes an ignore region
(`corrected:<rule>`): unmasked it is not a leak, masked it is not over-masking. So no system
is credited or charged for it, and every system is scored on the same corrected files. The
values were picked by reading every distinct gold value of the sample (275 de and 159 en
`PERSON` values; the other types in full), not from any model's misses.

**What was corrected in `gretel-finance`** (counts from
[`gretel-finance-corrected/manifest.json`](../eval/datasets/gretel-finance-corrected/manifest.json)):

| Rule | What it covers | Spans (de + en) |
|---|---|---:|
| `greeting-or-phrase` | salutations and set phrases labeled as names: `Damen`, `Herren` (from "Sehr geehrte Damen und Herren"), `Vielen Dank`, `Guten Morgen`, `Im Rahmen`, `Ihnen` | 74 + 0 |
| `common-noun` | dictionary words: `Saldo`, `Betrag`, `Sitz`, `Recht`, `Stahl`, `Seife`, `Engineering`, … | 45 + 1 |
| `possessive-noun-phrase` | German "Ihr/Ihre/Ihren + noun": `Ihr Vertrauen`, `Ihren Warenkorb`, … | 26 + 0 |
| `template-slot` | template fields, not values: `[Buyer's Name]`, `BORROWER NAME]`, `[Address]`, `phone number`, `[contact email]` | 10 + 7 |
| `role-word` | roles, not names: `Schuldner`, `Arbeitnehmer 1`, `Valued Customer`, `Data Protection Officer` | 9 + 2 |
| `code-not-a-name` | numbers and codes labeled as names or emails: `123456789`, `MD123456`, `BALI15`, an EDI segment | 1 + 3 |

`PERSON` gold goes from 694 to 524 spans. **Kept as gold on purpose:** placeholder names used
as a person's name (`Max Mustermann`, `John Doe`); spans holding a name next to a greeting
(`Hallo Lola`); name-like user names (`Carina20`); address parts labeled `PERSON` (`Mettmann`,
`An der Wupper`), which still say where someone lives or works. Missing labels (values the
generator never labeled) aren't added; they still count as over-masking for every system.

**Before and after** (leak; every system on the same corrected files; the full table and the
records are in the [audit](../eval/results/2026-10-29-lab-1497-label-audit/README.md) and
[benchmarks.md](benchmarks.md)). For PII Guard fast (NER v2.0) one run is scored against both
label sets, so the change is label noise only: **19.07 % → 2.44 %** (German 29.1 → 2.3 %,
English 5.1 → 2.6 %); 161 of its 180 upstream leaks are corrected values.

| System | Upstream | Corrected |
|---|--:|--:|
| PII Guard fast (rules + NER v2.0) | 19.0 % | **2.4 %** |
| PII Guard NER v2.0 alone | 20.3 % | 4.1 % |
| rules + Wismut/nym-pii-multilingual | 21.8 % | 5.8 % |
| rules + bardsai v3 | 23.3 % | 7.5 % |
| PrivAiTe | 27.7 % | 13.2 % |
| Presidio | 18.8 % | 14.8 % |
| LLM Guard | 59.3 % | 51.3 % |
| PII Guard rules | 80.8 % | 77.1 % |

Every system gains, and on the corrected labels PII Guard fast has the lowest leak of the 17
systems; on the upstream labels Presidio (18.8 %) edged it. Presidio gains least because it
masks almost everything (76.7 % over-masking). The upstream rows stay the published ones.

**MAPA EUR-Lex was audited and needs no correction** (LAB-1511). LAB-1494 found role words
labeled `PERSON` ("Rapporteur", "Registrar", "agentes") in the MAPA project's *validation*
split. The test set scored here doesn't have them: none of its 1,028 gold `PERSON` spans is one
of 79 role words in the MAPA languages, and of the 63 values NER v2.0 leaks, 41 are the same
string, gold-labelled `PERSON`, in 6 or more of the 21 language versions. A name isn't
translated; a role word is. Its 8.5 % leak is model error, mostly lone surnames
([audit](../eval/results/2026-10-29-lab-1497-label-audit/README.md)).

## Commands

```bash
python -m pii_guard.eval.datasets list                      # also: pii-guard eval datasets list
uv run --with pyarrow python -m pii_guard.eval.datasets fetch gretel-finance nemotron-pii
python -m pii_guard.eval.datasets fetch cee-pii tab-echr agent-traffic agent-traffic-dev cee-dev
python -m pii_guard.eval.datasets check NAME ...            # rebuild, compare, write nothing
python -m pii_guard.eval.datasets paths NAME                # fixture files, for pii-guard eval --fixtures

# Score: rules and fast (rules + NER v2 base + hard negatives) in the ner environment ...
PII_GUARD_NER_MODEL=models/ner/pii-guard-ner-xlmr-base-v2-hn \
  uv run --no-sync python -m pii_guard.eval.datasets run gretel-finance --system rules,fast --record
# ... and the comparison tools in the baselines environment (Presidio conflicts with torch).
UV_PROJECT_ENVIRONMENT=.venv-baselines uv run --no-sync \
  python -m pii_guard.eval.datasets run gretel-finance --system presidio --record
```

- **Downloads** go to `data/datasets/raw/` (git-ignored) and are checked against the pinned
  SHA-256 before use.
- **Parquet** sources need `pyarrow`, which PII Guard doesn't depend on. Only `fetch` reads
  Parquet; the committed samples are JSONL.
- **`run --record`** writes a run record per system to `eval/results/runs/` (the usual
  format) and the per-document counts to `eval/datasets/results/<run_id>.json`. The counts
  are numbers only, never text or values, and the bootstrap intervals come from them.
  `pii-guard eval report` then regenerates `docs/benchmarks.md`.
- **The audit system** (rules + NER + LLM) calls a remote model. It needs `--limit N`, and it
  refuses any set that isn't synthetic.

## Adding a dataset

1. **Check the license.** It must allow evaluation use without a data-use agreement. Commit
   rows only when the license allows redistribution and the text is synthetic. Real text is
   fetch-only.
2. **Add a module** to `src/pii_guard/eval/datasets/`. Its `rows()` turns the source files into
   `Row`s: id, language, text, and `(start, end, label)` spans, plus the source's own span
   text when it has one, so mismatched offsets are caught. Its `Dataset` declares:
   - the URL;
   - the pinned revision, and the files with their SHA-256;
   - the license and attribution;
   - the languages and sample sizes;
   - the split;
   - `synthetic` and `commit_rows`;
   - a `LabelMap`.
3. **Register it** in `REGISTRY` (`__init__.py`).
4. **Fetch it**, read its manifest's `unknown_labels` and `skipped_unconvertible`, and fix the
   mapping until both are explained.
5. **Run** `rules,fast` and the comparison tools with `--record`.
6. **Run the tests**, which cover the split-disjointness checks: `uv run --no-sync pytest
   tests/eval -q`. Then run `pii-guard eval report` and commit the records, the counts and
   the regenerated pages.
