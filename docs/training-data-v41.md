# NER v4.1: court-style and error-mined training data (LAB-1539)

Data for the v4.1 NER candidate. Training is a separate ticket. The data covers two
weaknesses of v2.0 (`watt-mind/pii-guard-ner-xlmr-base@95f612a9`):

- formal court-style text, where people are named by surname alone and the surname is often
  inflected next to a role word;
- the error patterns v2.0 shows on the **dev** splits.

Every source is synthetic or fictional ([ADR 0005](decisions/0005-synthetic-data-only.md)).
No MAPA or TAB text is used, adapted or uploaded (policy LAB-1419), and there are no GDPR
special categories. Rows are not committed. The manifests hold counts, row ids and SHA-256
hashes, and every set is rebuilt from a script and seed 1539:

- `training/ner/v41-data-manifest.json`: every source;
- `training/ner/v41-hf-manifest.json`: the third-party Hugging Face rows.

Data root: `~/Develop/.worktrees/pii-guard/data-eu/v41/`.

**Backup:** the synthetic part (court, variants, their Glimmer labels and the Muse response
cache, 4,576 files) is in the private dataset `watt-mind/pii-guard-ner-train`, under `v41/`
at revision **`a9f9c6e8d5685bd3f0d5d3a27c6feb0dd9d601be`** (pushed with `data_sync.py push v41`).
The Hugging Face sets are not re-hosted. They are downloaded again from their own repos at the
pinned revisions in `hf_v41.py`.

## Sources and licenses

| Source | Script | What | License |
|---|---|---|---|
| Court-style documents | `training/ner/court_eu.py court` | Fictional judgments and opinions in 8 kinds (loan, tenancy, employment, traffic, appeal, administrative, opinion, succession) in 24 languages. Muse Spark writes in a formal register around planted fictional values. People are introduced in full, then referred to by surname alone and in declined forms. Name packs are in `court_eu_names.py`. | Apache-2.0 (pii-guard generator; writer Muse Spark, Meta Model API contributor tier) |
| Error-mined variants | `training/ner/court_eu.py variants` | Fictional variants of each mined v2.0 error pattern (below) | Apache-2.0 |
| Glimmer teacher pass | `training/ner/fireworks_label.py` → `training/distill/label.py` | Muse Glimmer 30B (open weights) on a Fireworks on-demand H200. It adds names the writer invented, and its disagreements with the gold are left out of the loss. Planted gold always wins. | Apache-2.0 |
| [DataikuNLP/kiji-pii-training-data](https://huggingface.co/datasets/DataikuNLP/kiji-pii-training-data) | `training/ner/hf_v41.py` | Synthetic PII rows, mapped to the pii-guard taxonomy | Apache-2.0 (re-verified on the card) |
| [Wismut/nym-pii-multilingual-data](https://huggingface.co/datasets/Wismut/nym-pii-multilingual-data) | `hf_v41.py` | Synthetic multilingual rows. The language is identified with langid and the labels are mapped. | MIT |
| [E3-JSI/synthetic-multi-pii-ner-v1](https://huggingface.co/datasets/E3-JSI/synthetic-multi-pii-ner-v1) | `hf_v41.py` | Synthetic NER rows. The healthcare domain is dropped. | MIT |
| [subhash-holla/pii-anon](https://huggingface.co/datasets/subhash-holla/pii-anon) | `hf_v41.py` | ID-format source only: synthetic rows that hold an ID, with `curated_public` and clinical rows excluded. Capped at 5 % of the mix. | CC0-1.0 |

**Hugging Face set checks:**

- **ai4privacy derivation:** I read about 50 rows of each set and checked for the ai4privacy
  signature e-mail domains. The rate is 0 for kiji, nym and E3, against 0.38 on OpenPII. The
  maximum MinHash Jaccard against ai4privacy-style text is 0.04–0.05. No set looks derived, so
  all three are kept.
- **Special categories:** rows with special-category content or labels are dropped
  (`SPECIAL`, `SPECIAL_LABELS`, `E3_SPECIAL`).
- **Dates:** dates other than birth dates are taught as O.
- **Unmapped labels:** these go to `meta.loss_ignore`.

## Counts per language

The court-style corpus has 160 documents planned per language and **3,818 accepted**. A
document is discarded if a planted value is missing or the writer invented a person.

| Language | Court train / dev | Court PERSON spans | Variants | kiji | nym | E3 | pii-anon |
|---|---|---|---|---|---|---|---|
| bg | 144 / 16 | 2,210 | 22 | | | | 7 |
| cs | 140 / 16 | 2,276 | 22 | | 2,500 | | 10 |
| da | 144 / 16 | 3,066 | 22 | 2,500 | 2,500 | | 10 |
| de | 144 / 16 | 2,626 | 22 | 2,500 | 2,500 | 308 | ~370 |
| el | 143 / 16 | 1,785 | 22 | | 2,500 | 300 | ~370 |
| en | 144 / 16 | 3,044 | 22 | 2,500 | 2,500 | 315 | ~370 |
| es | 144 / 16 | 1,816 | 22 | 2,500 | 2,500 | | ~370 |
| et | 144 / 16 | 2,377 | 21 | | | | 8 |
| fi | 144 / 15 | 3,448 | 22 | | 2,500 | | 5 |
| fr | 144 / 16 | 2,636 | 22 | 2,500 | 2,500 | 311 | ~370 |
| ga | 143 / 16 | 2,051 | 22 | | | | |
| hr | 144 / 16 | 2,290 | 22 | | | | |
| hu | 138 / 15 | 1,894 | 22 | | | | 10 |
| it | 144 / 16 | 1,874 | 22 | | 2,500 | 305 | ~370 |
| lt | 144 / 16 | 2,603 | 22 | | | | |
| lv | 144 / 16 | 2,785 | 22 | | | | 4 |
| mt | 143 / 15 | 2,180 | 22 | | | | |
| nl | 144 / 16 | 2,505 | 22 | 2,500 | 2,500 | 341 | ~370 |
| pl | 144 / 15 | 1,838 | 22 | | 2,500 | | 5 |
| pt | 144 / 16 | 2,144 | 22 | | 2,500 | | ~370 |
| ro | 143 / 16 | 2,013 | 22 | | 2,500 | | 11 |
| sk | 142 / 16 | 2,262 | 21 | | | | |
| sl | 143 / 16 | 2,065 | 20 | | | 284 | |
| sv | 144 / 15 | 3,852 | 22 | | 2,500 | | 11 |
| **Total** | **3,818** | **56,640** | **522** | **15,000** | **35,000** | **2,164** | **2,973** |

Exact pii-anon counts per language are in `v41-hf-manifest.json`; the cells marked ~370 range
from 340 to 385.

## Mined v2.0 error patterns (dev splits only)

`training/ner/mine_v41.py` ran v2.0 in fast mode (rules + NER) on three dev pools:

- agent-traffic-dev: 300 documents;
- OpenPII dev: 2,350 documents;
- the eu dev splits from #251: 406 documents.

The script refuses any test, smoke, gate, inflection, MAPA, TAB or fixtures path. It found
1,264 misses, clustered into patterns. Each targeted group got fictional variants written by
Muse Spark and labelled by Glimmer. The counts are in
`eval/results/2026-10-29-lab-1539-v41-data/mining.json` and `patterns.json`.

| Variant kind | Mined misses | Top patterns (count) | Variants written |
|---|---|---|---|
| variant-dates-not-birth | 1,039 | over-masked dates as DATE_OF_BIRTH: short digits 616, other 388; id_document other 35 | 120 |
| negative-capitalized-words | 61 | over-masked single capitalized word as PERSON 45, sentence-initial word 6, address words 10 | 75 |
| variant-reference-numbers | 52 | lowercase word as ADDRESS 21, address with digits 9, short-digit ID over-masks 6 and leaks 6, bank account 5 | 68 |
| variant-person-like-company | 13 | multi-word company over-masked as PERSON 13 | 56 |
| variant-standalone-declined | 12 | single-token case-rich surname leaked 8, single token 4 | 120 |
| variant-honorific | 9 | honorific inside the PERSON span 9 | 83 |

**Not targeted:**

- `overmask:secret:other` (33): agent-traffic `sk-test` keys, a rules-side matter.
- `leak:address:one-line` (31): mostly OpenPII label noise.
- Seven smaller patterns of 1–7 each.

## Decontamination

`training/ner/decontam.py` uses MinHash at Jaccard 0.8 against every eval set. MAPA and TAB
are compared by hash only.

- Hugging Face sets: 0 of 55,137 rows dropped (`decontam-hf.json`).
- Muse court and variant documents: 0 of 4,340 dropped (`decontam-muse.json`).

## Glimmer teacher pass (Fireworks)

I ran one on-demand deployment session for all unlabelled v4.1 data: Muse Glimmer 30B BF16 on
1x H200 (shape `dkuwotf7`), with scale-to-zero at 300 s, `reasoning_effort` low, and a cap of
$25. Only files that pass `check_payload` and are marked `meta.source == "synthetic"` were
sent.

| Corpus | Documents | Without teacher | Gold found / missed by Glimmer | Agree / disagree | Names adopted |
|---|---|---|---|---|---|
| court | 3,816 | 2 | 51,844 / 18,936 | 58,811 / 1,170 | 702 PERSON |
| variants | 522 | 0 | 3,286 / 92 | 3,904 / 37 | 73 PERSON, 1 ORG |

Glimmer misses many planted inflected surnames, but planted gold always wins, so the missed
spans stay labelled. The two court documents without a teacher response are dropped from
`labelled/`. Stats are in `glimmer-label-stats-{court,variants}.json`.

**Deployments:** both were confirmed `DELETED` through the Fireworks API.

| Session | Deployment | Outcome | Cost |
|---|---|---|---|
| 1 | `pii-guard-label-v41` | Probe failed on one DetectionError; deleted | $0.41 |
| 2 | `pii-guard-label-v41b` | 0.73 h, deleted at 22:21 UTC | $5.84 |

## Teacher agreement check: Muse Spark Open vs Glimmer (evidence only)

**Purpose:** evidence only. The Spark Open labels are **not** trained on and are **not** in
the v41 labelled set.

**Setup:**

- Teacher: `meta-models/muse-spark-open-1026` on Baseten Model APIs, run through
  `training/distill/label.py` with `reasoning_effort` low.
- Sample: 200 court documents, stratified at 8–9 per language across all 24 languages, in
  `spark-check/`.
- Script and output: `training/ner/teacher_agreement.py` →
  `eval/results/2026-10-29-lab-1539-v41-data/teacher-agreement.json`.

**Results per type (200 documents):**

| Type | Gold spans | Gold recall, Spark (overlap) | Gold recall, Glimmer (overlap) | Spark vs Glimmer exact F1 | Overlap agreement |
|---|---|---|---|---|---|
| PERSON | 3,101 | 0.943 | 0.682 | 0.796 | 0.846 |
| ORGANIZATION | 276 | 0.996 | 0.967 | 0.950 | 0.950 |
| ADDRESS | 305 | 1.000 | 1.000 | 0.956 | 1.000 |
| DATE_OF_BIRTH | 105 | 1.000 | 1.000 | 0.981 | 1.000 |

The share of teacher spans that match gold exactly is 0.78 for Spark and 0.79 for Glimmer on
PERSON. The rest are mostly names the writer added; this is not a precision measure.

**PERSON results per language:**

| Lang | Gold | Spark recall | Glimmer recall | Exact F1 | | Lang | Gold | Spark recall | Glimmer recall | Exact F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| bg | 141 | 0.99 | 0.80 | 0.90 | | hu | 114 | 1.00 | 0.86 | 0.92 |
| cs | 144 | 0.85 | 0.47 | 0.60 | | it | 81 | 1.00 | 0.83 | 0.88 |
| da | 130 | 0.82 | 0.68 | 0.87 | | lt | 138 | 0.98 | 0.72 | 0.83 |
| de | 99 | 1.00 | 0.41 | 0.56 | | lv | 131 | 0.99 | 0.73 | 0.77 |
| el | 104 | 0.97 | 0.88 | 0.89 | | mt | 88 | 0.83 | 0.74 | 0.72 |
| en | 167 | 0.61 | 0.51 | 0.91 | | nl | 141 | 1.00 | 0.55 | 0.78 |
| es | 121 | 1.00 | 0.58 | 0.72 | | pl | 99 | 0.98 | 1.00 | 0.97 |
| et | 150 | 1.00 | 0.83 | 0.85 | | pt | 149 | 1.00 | 0.60 | 0.70 |
| fi | 198 | 1.00 | 0.52 | 0.66 | | ro | 127 | 1.00 | 0.83 | 0.90 |
| fr | 143 | 0.99 | 0.86 | 0.89 | | sk | 106 | 0.97 | 0.58 | 0.65 |
| ga | 77 | 1.00 | 0.99 | 0.87 | | sl | 83 | 0.98 | 0.54 | 0.65 |
| hr | 132 | 1.00 | 0.48 | 0.57 | | sv | 238 | 0.86 | 0.69 | 0.83 |

**Reading:**

- The two teachers agree on organizations, addresses and birth dates (F1 0.95–0.98).
- On court-style PERSON, Spark Open finds far more of the planted standalone and inflected
  surnames (0.94 against 0.68 recall). The gap is widest in de, hr, cs, fi, sl, nl and sk.
- English is low for both teachers (0.61 / 0.51). The English writer often puts the role word
  inside the planted span ("Mr Justice ..."), and both teachers leave it out.
- For v4.1 this does not change the labels, because planted gold wins over either teacher.
  It does mean Glimmer's adopted extra names are a conservative addition.

**Spark usage:**

- 251 requests: 546,934 prompt tokens (152,960 cached) and 154,155 completion tokens (119,132
  of them reasoning).
- No invalid outputs or refusals.
- Estimated cost: **$1.17**.
- The first run at 16 workers hit HTTP 429 on 125 documents. The rerun at 4 workers completed
  all 200.

## Cost

| Item | Cost |
|---|---|
| Meta Model API (Muse Spark writer): court $2.49, variants $0.25, pilot $0.02, one stopped run ~$0.05 | ~$2.80 (cap $5) |
| Fireworks Glimmer labelling: two sessions, both deployments deleted | ~$6.25 (cap $25) |
| Baseten Spark Open agreement check | ~$1.17 (cap $3) |
| Modal | $0 (not used) |

## Rebuild

```bash
V=~/Develop/.worktrees/pii-guard/data-eu/v41
R=eval/results/2026-10-29-lab-1539-v41-data
uv run --no-sync python training/ner/court_eu.py court --n 160 --workers 12 \
    --out $V/court --cache $V/cache --budget-usd 4          # Meta API key
uv run --no-sync python training/ner/mine_v41.py --inputs $V/mining-input/*-dev*.jsonl \
    --json $R/mining.json --local $V/mining/misses.jsonl
uv run --no-sync python training/ner/court_eu.py variants --n 22 \
    --out $V/variants --cache $V/cache --budget-usd 1
uv run --no-sync python training/ner/hf_v41.py --hf $V/hf --out $V/hf-mapped \
    --manifest training/ner/v41-hf-manifest.json --mix-total 56504
uv run --no-sync python training/ner/fireworks_label.py --corpus $V/court --corpus $V/variants
uv run --no-sync python training/ner/v41_manifest.py --data $V
```

Or pull the synthetic part with `python training/ner/data_sync.py pull v41 --revision a9f9c6e`.
