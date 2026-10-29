# Multilingual NER, phase 1: training data and gate sets (LAB-1525)

The data for the first NER training beyond hu / en / de. v2.0
(`watt-mind/pii-guard-ner-xlmr-base`) was trained on Hungarian, English and German only. The
MAPA-21 baseline (LAB-1516) found it leaks the most names in Maltese, Latvian, Lithuanian and
Irish (17–26 %) and in English court-style text that refers to people by surname alone. This
PR builds the data only; training and selection (candidates A and B, both from v2.0) are a
separate ticket.

Every source is synthetic or fictional ([ADR 0005](decisions/0005-synthetic-data-only.md)). No MAPA or TAB court text is
used, adapted or uploaded (policy LAB-1419). No GDPR special categories. Rows are not
committed: the manifests hold counts and SHA-256 hashes, and every set is rebuilt from a
script and a seed (1525).

## Sources and licenses

| Source | Script | What | License |
|---|---|---|---|
| OpenPII-1M **train** split | `training/ner/openpii_eu.py` | Ai4Privacy synthetic PII rows, 19 languages, disjoint from the evaluated `validation` sample (uid and text check) | CC-BY-4.0, attribution "Ai4Privacy / Ai Suisse SA" |
| Muse documents | `training/ner/eu_corpus.py` | fictional documents written by Muse Spark (Meta Model API, contributor tier) around planted fictional values: contracts, leases, court summons and judgment excerpts, invoices, e-mails, chats, minutes, no-PII prose | Apache-2.0 (pii-guard generator, as v2.0's s11 / s13) |
| Glimmer teacher pass | `training/ner/modal_eu_label.py` → `training/distill/label.py` | Muse Glimmer 30B (open weights) adds names the writer invented and masks disagreements out of the loss | Apache-2.0 |
| Hard negatives | `training/ner/negatives_eu.py` | template reference numbers and amounts, no gold spans (as v2.0's `negatives.py`) | Apache-2.0 |
| English court style | `training/ner/court_surnames_en.py` | template judgment sentences, people introduced in full and then by surname alone; honorifics excluded from the loss | Apache-2.0 |
| Gate sets | `eval/fixtures/build_eu_gates.py` | hand-written fictional smoke and inflection sets (evaluation only) | Apache-2.0 |

All counts, file hashes and licenses are in `training/ner/eu-phase1-data-manifest.json`
(`"synthetic": true` on every source, so the Modal upload allowlist of LAB-1527 accepts them)
and `training/ner/eu-openpii-train-manifest.json`.

## Counts per language

| Language | OpenPII train / dev (PERSON spans in train) | Muse docs train / dev (PERSON spans) | Hard negatives | Smoke / inflection gate docs |
|---|---|---|---|---|
| lv | 5,000 / 100 (4,774) | 1,079 / 120 (7,153) | 2,000 | 5 / 5 |
| lt | 5,000 / 100 (4,898) | 1,077 / 120 (7,140) | 2,000 | 5 / 5 |
| hr | 5,000 / 100 (4,954) | 1,078 / 120 (6,594) | 2,000 | 5 / 5 |
| sl | 5,000 / 100 (4,896) | 1,079 / 120 (6,288) | 2,000 | 5 / 5 |
| fr | 5,000 / 100 (4,754) | 1,079 / 120 (6,078) | 2,000 | 5 / 4 |
| es | 5,000 / 100 (4,609) | 1,076 / 120 (5,721) | 2,000 | 5 / 4 |
| it | 5,000 / 100 (4,911) | 1,080 / 120 (6,003) | 2,000 | 5 / 4 |
| nl | 5,000 / 100 (4,866) | 1,080 / 120 (7,579) | 2,000 | 5 / 4 |
| ro | 5,000 / 100 (4,576) | 1,080 / 120 (6,202) | 2,000 | 5 / 4 |
| mt | none in the dataset | 1,075 / 119 (6,460) | 2,000 | 5 / 4 |
| ga | none in the dataset | 1,068 / 119 (6,220) | 2,000 | 5 / 4 |
| bg | 5,000 / 100 (4,853) | – | 2,000 | – |
| cs | 5,000 / 100 (4,715) | – | 2,000 | – |
| da | 5,000 / 100 (4,782) | – | 2,000 | – |
| el | 5,000 / 100 (4,656) | – | 2,000 | – |
| et | 5,000 / 100 (4,814) | – | 2,000 | – |
| fi | 5,000 / 100 (5,049) | – | 2,000 | – |
| pl | 5,000 / 100 (4,703) | – | 2,000 | – |
| pt | 5,000 / 100 (4,426) | – | 2,000 | – |
| sk | 5,000 / 100 (4,834) | – | 2,000 | – |
| sv | 5,000 / 100 (4,764) | – | 2,000 | – |
| en (court style) | – | – | – | 6 (`en-court-smoke`) |

English court-style training set: 1,500 train + 100 dev documents, 14,424 PERSON spans, 11,224 of them a surname alone.

OpenPII rows: 5,000 train + 100 dev per language in seeded order, so candidate A's 2,500 rows
per language are the first half of candidate B's 5,000. OpenPII has no Irish or Maltese rows.
Muse documents: 90 % train / 10 % dev by a seeded split. 4,800 documents were planned (1,200 per language) and 4,793 kept: 3 missing a value, 3 with an invented person, 1 with an invented identifier. Writing cost $2.48 of Meta Model API credits (2.65 M prompt and 11.1 M completion tokens, reasoning included).
Phase 1b (LAB-1534) ran the same pipeline for fr, es, it, nl, ro, ga and mt: 8,400 planned, 8,376
kept (10 missing a value, 14 with an invented person), $3.98 of Meta Model API credits. Its files
are `eval/generated/distill-eu-1b-s1525/` (manifest sources `muse-eu-1b` and
`muse-eu-1b-labelled`).

## How the Muse documents are labeled

The generator's own identity packs exist only for hu and en, so `eu_identities.py` adds
fictional packs for lv, lt, hr and sl (phase 1) and fr, es, it, nl, ro, ga and mt (phase
1b): common given names combined at random with common surnames (with the gendered forms Latvian and Lithuanian use), random house numbers on common
street names of real towns, national-shaped phone numbers, IBANs with valid check digits but
random bank codes, and personal codes in the national format (checksummed where the format has
a check digit). E-mails use the reserved `example.*` domains.

These languages decline names (`Jānis Bērziņš` → `Jāņa Bērziņa`, `Jonas Kazlauskas` →
`Jonui Kazlauskui`). The writer is told to give each full name once in the nominative and to
decline freely after that; the labeler then finds every planted name in any declined form
`eu_identities.name_forms` lists, as a whole word (the convention of
`eval/fixtures/hu-inflection.jsonl`). In phase 1b, Romanian given names take the
genitive-dative and vocative (`Ioana` → `Ioanei`), Irish names their initial mutations and
slender genitive (`Seán Ó Briain` → `Sheáin Uí Bhriain`), a Spanish person's first surname
alone counts (`García López` → `García`), and a Dutch particle may be capitalized
(`De Vries`); French, Italian and Maltese names don't decline. Every other value must appear
exactly as given. A document
is discarded when a value is missing, when the rules find an identifier nobody planted, or
when a capitalized given name of the language's list appears outside every planted person (an
invented person would otherwise be taught as `O`).

### Glimmer teacher pass

`training/ner/modal_eu_label.py` ran `training/distill/label.py` with Muse Glimmer 30B (low
reasoning) on vLLM inside one ephemeral Modal H100 container, on loopback (no public endpoint;
the `pii-guard-glimmer` secret never left Modal). The upload was the 8 Muse files only, through
the LAB-1527 allowlist (`modal_upload.check_payload`). About an hour of H100 time on Modal
credits. Over the 4,793 documents (`eval/results/2026-10-29-lab-1525-eu-data/glimmer-label-stats.json`):

| | count |
|---|---|
| planted gold the teacher also found | 37,614 |
| planted gold the teacher missed (kept: planted gold always wins) | 1,950 |
| teacher spans agreeing with gold | 41,147 |
| disagreements (excluded from the loss) | 76 |
| names the writer added, adopted as labels | 37 people, 8 organizations |

Phase 1b (LAB-1534), the same job over the 8,376 fr / es / it / nl / ro / ga / mt documents
(`eval/results/2026-10-29-lab-1534-eu-data-1b/glimmer-label-stats.json`), on Modal credits:

| | count |
|---|---|
| planted gold the teacher also found | 61,148 |
| planted gold the teacher missed (kept: planted gold always wins) | 4,938 |
| teacher spans agreeing with gold | 66,831 |
| disagreements (excluded from the loss) | 264 |
| names the writer added, adopted as labels | 367 people, 22 organizations |

The writer added more names of its own in phase 1b than in phase 1 (367 against 37). The
teacher adopts them, so they are labeled rather than taught as `O`.

The training files are `eval/generated/distill-eu-s1525/labelled/<lang>-distill-{train,dev}.jsonl`;
the teacher cache is kept next to them, so a rerun of `label.py --cache-only` is local and free.
Phase 1b's are under `eval/generated/distill-eu-1b-s1525/labelled/`. Rows are not committed;
the whole phase-1b output (documents, labels, teacher cache and the Muse response cache) is the
corpus `phase1b` in the data root, backed up at revision
`5b4ddcecbae18ff0f25c5c75439f7d151b7a2b28` (see "Where the data lives").

## Gate sets

`eval/fixtures/eu/`, built by `eval/fixtures/build_eu_gates.py` (a test checks the files are
fresh). Names in the gates are not from the training generator's lists.

| Set | Languages | Documents each | What it checks |
|---|---|---|---|
| `<lang>-smoke.jsonl` | lv lt hr sl fr es it nl ro mt ga | 5 | every common type (person, organization, address, e-mail, phone, IBAN, national ID, birth date) plus one document with reference numbers and no personal data (over-masking) |
| `<lang>-inflection.jsonl` | lv lt hr sl (5); fr es it nl ro mt ga (4) | 4–5 | declined names (lv lt hr sl ro), vocatives, standalone surnames, elision (`d'`, `l'`), particles (`de Wit`), Irish initial mutations (`do Sheán Ó Briain`, `Sheáin Uí Bhriain`) |
| `en-court-smoke.jsonl` | en | 6 | standalone surnames in judgment prose, possessives, surnames that are common words, one no-PII document |

In total 23 files, 109 documents. The proposed gate for the training ticket: on each language's
smoke + inflection set, a candidate's name leak is below v2.0's and its over-masking is at most
v2.0's + 2 pp; the existing gates and the selection protocol stay unchanged, and MAPA-21 is a
veto after selection.

## Checks run

- OpenPII sampler: 0 eval-overlap rows skipped (the train split shares no uid or text with the
  evaluated validation sample).
- Decontamination gate (`training/ner/decontam.py`) over the OpenPII, negative and court sets:
  0 of 140,500 documents dropped
  (`eval/results/2026-10-29-lab-1525-eu-data/decontam-openpii-negatives-court.json`).
- The same gate over the 4,793 Muse documents: 0 dropped
  (`eval/results/2026-10-29-lab-1525-eu-data/decontam-muse.json`).
- MAPA and TAB fixtures are absent from this worktree, so the gate compared them by manifest
  hash only; the Muse and template texts are generated, so an exact copy is the only way one
  could match.

## Where the data lives

The template sets (OpenPII rows, negatives, court-style templates) rebuild byte-identically from
this repository. The LLM-written sets do not: a rerun gets new completions and costs credits and
GPU hours. Since LAB-1542 they live **outside every worktree** and are backed up to a **private**
Hugging Face dataset, so removing a worktree no longer loses them.

- **Local data root.** `PII_GUARD_DATA_DIR`, default `~/Develop/.worktrees/pii-guard/data-eu`.
  One folder per *corpus* (`phase1b/`, `v41/`, ...): the documents, the response cache
  (`cache/`), teacher labels (`labelled/`, `teacher-cache.jsonl`) and a `manifest.json` that
  says `"synthetic": true`. `eu_corpus.py --corpus <name>` and `modal_eu_label.py`
  (`EU_CORPUS=<corpus>/<dir>`) write there; an explicit `--out eval/generated/...` (or a
  repo-relative `EU_CORPUS`) still works as before and is not pushed.
- **Backup.** [`watt-mind/pii-guard-ner-train`](https://huggingface.co/datasets/watt-mind/pii-guard-ner-train)
  (private). Both generators push the corpus at the end of a successful run (one commit; the
  revision is printed); `--no-push` skips it. A push is refused unless the manifest says
  synthetic and every path passes the LAB-1527 real-text allowlist (`modal_upload.check_payload`):
  MAPA, TAB, dataset downloads and mining pools never go.
- **Training.** Config paths `data:<corpus>/<file>` are read from the data root (`train.py`,
  `decontam.py`). On Modal, `modal_train.py --data <corpus>@<rev>` reads the corpus from the
  volume `pii-guard-ner-runs` (`data/<corpus>@<rev>`) instead of uploading it.

| Corpus | What | Revision |
|---|---|---|
| `phase1b` | Muse fr/es/it/nl/ro/ga/mt documents (8,376), response cache, **Glimmer-labelled** (`labelled/`, `teacher-cache.jsonl`) (LAB-1534) | `5b4ddcecbae18ff0f25c5c75439f7d151b7a2b28` |
| `v41` | Muse court-style documents bg..ga, pilot, response cache (LAB-1539, snapshot while the run continued) | `4b6c928f4abd8b9e7137d5d0cfbd519744f6bf9a` |
| `v20-s11` | v2.0's s11 hu/en corpus, Glimmer labels, teacher and writer caches (LAB-1128) | `294adb3fc4d411825f5a416f4b6b93468e4836fe` |

```sh
set -a; source .env; set +a   # or: hf auth login (read access to watt-mind)
# restore a corpus into the data root, pinned to a revision
uv run --no-sync --with huggingface-hub python training/ner/data_sync.py pull phase1b \
  --revision 5b4ddcecbae18ff0f25c5c75439f7d151b7a2b28
# what a push would upload (nothing is sent)
uv run --no-sync python training/ner/data_sync.py check phase1b
# back up a corpus by hand (prints the revision)
uv run --no-sync --with huggingface-hub python training/ner/data_sync.py push phase1b
# copy a revision to the Modal volume, then train from it without uploading
uv run --no-sync --with huggingface-hub --with modal python training/ner/data_sync.py volume phase1b \
  --revision 5b4ddcecbae18ff0f25c5c75439f7d151b7a2b28
modal run training/distill/modal_train.py --config <toml> \
  --data phase1b@5b4ddcecbae18ff0f25c5c75439f7d151b7a2b28
```

## Rebuild

```sh
curl -L -o data/public/openpii-train/train.jsonl \
  https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m/resolve/ecfdc547f4a0955600cfe6ab98ba2a162207fcc0/data/train.jsonl
uv run --no-sync python training/ner/openpii_eu.py --source data/public/openpii-train/train.jsonl --check
uv run --no-sync python training/ner/negatives_eu.py --stats eval/generated/negatives-eu-stats.json
uv run --no-sync python training/ner/court_surnames_en.py
set -a; source .env; set +a   # META_API_KEY; cached responses make a rerun free
# phase-1 paths under eval/generated, as the manifest records them; drop --out/--cache to use
# the data root and push (see "Where the data lives")
uv run --no-sync python training/ner/eu_corpus.py --languages lv,lt,hr,sl --n 1200 --budget-usd 4 --workers 32 \
  --out eval/generated/distill-eu-s1525 --cache eval/generated/cache --no-push
EU_CORPUS=eval/generated/distill-eu-s1525 uv run --no-sync --with modal modal run training/ner/modal_eu_label.py --no-push
# phase 1b (LAB-1534), under the data root (corpus phase1b)
uv run --no-sync python training/ner/eu_corpus.py --languages fr,es,it,nl,ro,ga,mt --n 1200 --budget-usd 4.8 --workers 8 \
  --out ~/Develop/.worktrees/pii-guard/data-eu/phase1b/distill-eu-1b-s1525 --cache ~/Develop/.worktrees/pii-guard/data-eu/phase1b/cache --no-push
EU_CORPUS=phase1b/distill-eu-1b-s1525 uv run --no-sync --with modal modal run training/ner/modal_eu_label.py
uv run --no-sync python training/ner/eu_phase1_manifest.py
uv run --no-sync python eval/fixtures/build_eu_gates.py
```

## Not in this PR

- Maltese zero-shot measurement on MLRS (the ticket's step before Maltese training data).
- Training and selection: the next ticket.
