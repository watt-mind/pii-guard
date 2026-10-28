# Evaluation datasets

pii-guard is scored on more than its own hand-written fixtures. This page lists every
registered dataset: where it comes from, its licence, what is committed, how its labels map to
pii-guard types, and which split it belongs to. The registry lives in
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

| Set | Source | Licence | Languages | Docs | Split | Text committed |
|---|---|---|---|---:|---|---|
| `ai4privacy` | [Ai4Privacy OpenPII 1M](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m), `validation` @ `ecfdc54` | CC-BY-4.0 | hu, en, de | 600 | test | yes (synthetic) |
| `gretel-finance` | [gretelai/synthetic_pii_finance_multilingual](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual), `test` @ `7b844d1` | Apache-2.0 | en, de | 400 | test | yes (synthetic) |
| `nemotron-pii` | [nvidia/Nemotron-PII](https://huggingface.co/datasets/nvidia/Nemotron-PII), `test` @ `b70ffaf` | CC-BY-4.0 | en | 300 | test | yes (synthetic) |
| `cee-pii` | [flowxai/cee-pii-bench](https://huggingface.co/datasets/flowxai/cee-pii-bench) v0.2 @ `84ee883` | Apache-2.0 | hu, en | 451 | test | yes (synthetic) |
| `pl-pii-bench` | [pl-pii-bench/pl-pii-bench](https://huggingface.co/datasets/pl-pii-bench/pl-pii-bench) v1.0.0 @ `bef947d` | CC-BY-4.0 | pl | 346 | test | yes (synthetic) |
| `mapa-eur-lex` | [piimb/mapa-eur-lex-pii](https://huggingface.co/datasets/piimb/mapa-eur-lex-pii), `test.jsonl` @ `a44958f` | CC-BY-4.0 | 21 EU languages | 42 | test | **no**: real EU court documents |
| `tab-echr` | [TAB](https://github.com/NorskRegnesentral/text-anonymization-benchmark), `echr_test.json` @ `558e09e` | MIT (annotations) | en | 40 | test | **no**: real court documents |
| `agent-traffic` | pii-guard's seeded generator ([below](#synthetic-agent-traffic)) | Apache-2.0 | hu, en, de | 990 | test | yes (generated) |
| `agent-traffic-dev` | the same generator, another seed | Apache-2.0 | hu, en, de | 300 | dev | yes (generated) |

Attribution, as the licences require:

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
- the licence and attribution;
- the split;
- the seed and the sample rule (per language, rows ordered by `sha256("<seed>:<uid>")`, the
  first *n* that convert);
- the full label mapping;
- per language, the sampled ids, the document hashes and the counts of gold, policy-excluded
  and unknown labels.

**Why each set is here**

- **`gretel-finance`**: long financial documents (EDI messages, loan agreements, statements)
  and German text. Its labels were made during generation and checked with GLiNER, so some
  values are unlabelled or mislabelled. This shows up as over-masking for every system. A few
  generated documents contain credentials: a Slack-style token, a JWT, or an API key after
  `API key:`. These rows are skipped (`skipped_unconvertible`). Secret scanning (GitHub push
  protection and gitleaks) rejects them, a public dataset's token can't be shown to be fake,
  and secrets aren't part of this text benchmark. Every loader applies this rule
  (`holds_credential`).
- **`nemotron-pii`**: 55 labels across 50+ industries, half of them US conventions. Rows whose
  span text doesn't match the offsets, or that hold a credential, are skipped and counted (22
  of the first ones drawn).
- **`cee-pii`**: the only public set we found with Hungarian identifiers (checksum-valid TAJ
  numbers). It adds deliberate noise (stripped diacritics, OCR confusions) and unlabelled
  order and tracking numbers. Another detector's authors wrote it as their benchmark, so it
  is a fair third-party set for pii-guard.
- **`pl-pii-bench`**: the first Polish set, and a language pii-guard has no language pack for.
  It has complete, exhaustively annotated synthetic administrative documents, so precision is
  meaningful. Its identifiers are checksum-valid, and a separate negative lane holds
  same-shape values that fail their check digits. An inflection lane puts names in all seven
  Polish cases. Five of its seven public lanes are used; the `robustness` and `pdf` lanes
  are re-renderings of `core` and are left out. Its card asks that nobody train on it. PESEL,
  ID card, passport, driving licence and NIP are `ID_DOCUMENT`; REGON (a business number)
  and VIN have no pii-guard type. Its maintainer also maintains one of the systems it
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

- **WikiANN** (hu/de/en). Its card lists the licence as *unknown*, and its names are real
  people. The licence can't be verified, so the set is dropped.
- **The other Ai4Privacy releases** (300k/400k, PII-Masking-2M). Their licences don't allow
  this use, which is also why only OpenPII is used.
- **An OpenPII `test` split.** OpenPII publishes only `train` and `validation`. The
  evaluation sample comes from `validation`, which NER v2 never trained on, so `validation`
  is the registry's `test` split.

## Label mapping

Each dataset's labels map to [pii-guard types](entities.md). The rules match the Ai4Privacy
conversion:

- **Policy-excluded labels become ignore regions.** These are labels pii-guard has no type
  for: any date, IP and MAC addresses, customer and employee ids, PINs, passwords, API keys,
  user names, health and demographic attributes, routing and SWIFT codes, and contract or
  policy references. An ignore region (`meta.ignore`: offsets and label, no value) is left
  out of the gold spans, so it is never a leak and never recall. A prediction on it is
  neither credited nor charged in precision and over-masking.
- **Adjacent parts of one type are merged into one span.** A given name and a surname, or a
  street and a building number, separated only by spaces or a comma (≤ 3 characters), become
  one span.
- **Address parts count only inside an address.** A city, state, county or postcode merged
  into an address is `ADDRESS`. On its own it is an ignore region, because pii-guard keeps a
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
  random. E-mail domains are the reserved `example.*` ones.
- **Shapes** (`meta.shape`):
  - an OpenAI tool call, whose `arguments` is a JSON string inside JSON;
  - a nested JSON record;
  - YAML;
  - CSV;
  - log lines;
  - Python code with an e-mail address and an API key;
  - an e-mail thread with a quoted reply;
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
  - a leetspeak e-mail (`4nn4 [at] example [dot] com`).
- **Hard negatives** are never labelled: order and invoice numbers, SKUs, request ids,
  amounts, dates that aren't birth dates, and large public companies in context (`OTP Bank`,
  `Siemens`, `Microsoft`). Masking one is over-masking. API keys in code are ignore regions,
  because the text policy has no secret type.
- **No LLM-written prose.** The ticket allowed it within free credits, but template text keeps
  the gold exact.

## Commands

```bash
python -m pii_guard.eval.datasets list                      # also: pii-guard eval datasets list
uv run --with pyarrow python -m pii_guard.eval.datasets fetch gretel-finance nemotron-pii
python -m pii_guard.eval.datasets fetch cee-pii tab-echr agent-traffic agent-traffic-dev
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
- **Parquet** sources need `pyarrow`, which pii-guard doesn't depend on. Only `fetch` reads
  Parquet; the committed samples are JSONL.
- **`run --record`** writes a run record per system to `eval/results/runs/` (the usual
  format) and the per-document counts to `eval/datasets/results/<run_id>.json`. The counts
  are numbers only, never text or values, and the bootstrap intervals come from them.
  `pii-guard eval report` then regenerates `docs/benchmarks.md`.
- **The audit system** (rules + NER + LLM) calls a remote model. It needs `--limit N`, and it
  refuses any set that isn't synthetic.

## Adding a dataset

1. **Check the licence.** It must allow evaluation use without a data-use agreement. Commit
   rows only when the licence allows redistribution and the text is synthetic. Real text is
   fetch-only.
2. **Add a module** to `src/pii_guard/eval/datasets/`. Its `rows()` turns the source files into
   `Row`s: id, language, text, and `(start, end, label)` spans, plus the source's own span
   text when it has one, so mismatched offsets are caught. Its `Dataset` declares:
   - the URL;
   - the pinned revision, and the files with their SHA-256;
   - the licence and attribution;
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
