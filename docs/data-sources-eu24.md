# Data sources for the 24 EU languages: licence and coverage audit

**Status:** research, 2026-10-29 (LAB-1517). Nothing here has been downloaded, trained on or
evaluated. Every licence was read from the source's own page: the Hugging Face card (YAML
`license:` field and card body), the repository record (LINDAT, CLARIN.SI, Zenodo, figshare),
the project's GitHub `LICENSE`, or the paper. No licence is inferred. Where none is stated the
cell says **not stated**. Where two pages disagree, both are given and the stricter one wins.

PII Guard ships `en`, `de`, `hu` and `pl` today. Its NER model
([`watt-mind/pii-guard-ner-xlmr-base`](https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base))
is gated on en/de/hu. This page asks what it would take to cover all 24 official EU
languages: bg, cs, da, de, el, en, es, et, fi, fr, ga, hr, hu, it, lt, lv, mt, nl, pl, pt, ro,
sk, sl, sv.

**Colour key**, for training the weights of an Apache-2.0 model:

- **G (green):** permissive. CC0, CC BY, MIT, Apache-2.0, ODC-BY, or the EU reuse decision
  with attribution.
- **A (amber):** CC BY-SA, GPL/LGPL on data, custom terms, conflicting statements, or
  unclear. Whether share-alike reaches model weights is a legal call, not settled here.
- **R (red):** NC, ND, research-only, LDC, DUA, paid, or no licence at all.

## Read this first

1. **ADR 0005 comes before any real corpus.**
   [ADR 0005](decisions/0005-synthetic-data-only.md) says *all fine-tuning data is synthetic*.
   - Every human-annotated NER corpus below is real text with real people's names: news,
     Wikipedia, EUR-Lex court documents. MAPA is real EUR-Lex text.
   - Using any of them as **training** data, even green ones, needs an ADR amendment first,
     for example "public, licence-clean, already-published text may train the NER; it is
     never committed".
   - Without that amendment, the real corpora below are usable only as **evaluation** sets,
     handled like `mapa-eur-lex` and `tab-echr` today: text not committed, scored in place.
   - The synthetic sources (Ai4Privacy OpenPII, Gretel, Nemotron, E3-JSI, nym) are not
     affected.
2. **The one large green PII source covers 22 of the 24 languages.**
   Ai4Privacy OpenPII-1M has about 36k train rows for each of 22 EU languages. **Irish and
   Maltese are absent.**
3. **For Irish and Maltese, the only permissive real data is MAPA**: about 1.4k and 0.9k
   training sentences, plus a hand-corrected Maltese release with 3.9k.
4. **Maltese is not in XLM-R's pretraining data.**
   - CC-100 has no Maltese ([Conneau et al. 2020](https://arxiv.org/abs/1911.02116),
     Table 6; the [CC-100 list](https://data.statmt.org/cc-100/) agrees).
   - Irish is in it, but tiny: 86M tokens, 0.5 GiB.
   - Data alone will not fix Maltese. It is the one language where the encoder itself is the
     gap.
5. **Most national gold corpora are amber or red.**
   - Green: RONEC (ro), EstNER (et), SUC 3.0 scrambled (sv), GermEval 2014 and German LER (de),
     AnCora and MEDDOCAN (es), KPWr and NKJP from nkjp.pl (pl), MLRS MAPA Maltese (mt), TAB (en).
   - Everything else is CC BY-SA, NC, or has no licence.

## 1. Coverage matrix

### 1a. Multilingual sources by language

Each cell gives the **training rows or sentences for that language**, with the licence colour
in brackets. A dash means the language is absent. Source details (licence string, link, kind,
entity types) are in [§1b](#1b-source-catalogue).

| lang | OpenPII-1M (synthetic PII) | MAPA (gold, legal, PII-style) | WikiANN (silver) | MultiCoNER v2 (gold) | UNER v1 (gold) | WikiNER (silver) | Gretel finance (synthetic PII) | MultiNERD / WikiNEuRal (silver) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bg | 37,379 [G] | 1,411 [G] | 20k [R] | – | – | – | – | – |
| cs | 37,251 [G] | 1,464 [G] | 20k [R] | – | PUD test 1k [A] | – | – | – |
| da | 36,117 [G] | 1,455 [G] | 20k [R] | – | 4,383 [A] | – | – | – |
| de | 96,179 [G] | 1,457 [G] | 20k [R] | 9,785 [G] | PUD test 1k [A] | yes [G] | 4,054 [G] | 251k / 99k [R] |
| el | 36,236 [G] | 1,529 [G] | 20k [R] | – | – | – | – | – |
| en | 143,515 [G] | 893 [G] | 20k [R] | 16,778 [G] | 12,543 [A] | yes [G] | 25,948 [G] | 263k / 93k [R] |
| es | 72,180 [G] | 806 [G] | 20k [R] | 16,453 [G] | – | yes [G] | 4,165 [G] | 277k / 76k [R] |
| et | 36,667 [G] | 1,391 [G] | 15k [R] | – | – | – | – | – |
| fi | 36,228 [G] | 1,398 [G] | 20k [R] | – | – | – | – | – |
| fr | 105,227 [G] | 1,297 [G] | 20k [R] | 16,548 [G] | – | yes [G] | 4,032 [G] | 282k / 101k [R] |
| **ga** | **–** | 1,383 [G] | 1k [R] | – | – | – | – | – |
| hr | 35,842 [G] | **–** | 20k [R] | – | 6,914 [A] | – | – | – |
| hu | 36,332 [G] | 1,390 [G] | 20k [R] | – | – | – | – | – |
| it | 71,362 [G] | 1,411 [G] | 20k [R] | 16,579 [G] | – | yes [G] | 4,032 [G] | 291k / 88k [R] |
| lt | 36,695 [G] | 1,413 [G] | 10k [R] | – | – | – | – | – |
| lv | 36,591 [G] | 1,383 [G] | 10k [R] | – | – | – | – | – |
| **mt** | **–** | 937 [G] | 100 [R] | – | – | – | – | – |
| nl | 35,677 [G] | 1,391 [G] | 20k [R] | – | – | yes [G] | 4,002 [G] | 275k / 84k [R] |
| pl | 37,331 [G] | **–** | 20k [R] | – | – | yes [G] | – | 312k / 108k [R] |
| pt | 35,061 [G] | 1,086 [G] | 20k [R] | 16,469 [G] | 7,018 [A] | yes [G] | – | 284k / 81k [R] |
| ro | 36,166 [G] | 1,480 [G] | 20k [R] | – | – | – | – | – |
| sk | 36,736 [G] | 1,395 [G] | 20k [R] | – | 8,483 [A] | – | – | – |
| sl | 36,048 [G] | **–** | 15k [R] | – | – | – | – | – |
| sv | 36,598 [G] | 1,453 [G] | 20k [R] | 16,363 [G] | 4,303 [A] | – | 4,113 [G] | – |

Units and how the counts were taken:

- **OpenPII-1M:** rows in the train split (about 9k more per language in validation).
- **MAPA, WikiANN, MultiCoNER, UNER, MultiNERD, WikiNEuRal:** sentences in the train split.
- **Gretel finance:** train rows, which are documents.
- **Where the counts come from:** the cards and the Hugging Face datasets-server `/size`
  endpoint. Counting needed no download.
- **WikiNER:** per-language counts were not taken.
- **Gretel's Swedish rows:** present in the data, but the card's YAML language list omits
  `sv`.

### 1b. Source catalogue

Abbreviations:

- **Types:** `PII` = identifiers (ID, tax, phone, e-mail, IBAN and the like) as well as names.
  `PLO` = PER/LOC/ORG (sometimes plus MISC) only.
- **Kind:** *syn* = synthetic, *gold* = manual annotation, *silver* = automatic annotation.

**Synthetic PII sets (not affected by ADR 0005)**

| Source | Licence string (where found) | Col. | Kind | Domain | Types |
|---|---|:-:|---|---|---|
| [ai4privacy/pii-masking-openpii-1m](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m) | YAML `other` / `license_name: cc-by-4.0`; body "License: CC-BY-4.0. Copyright © 2026 Ai Suisse SA". Changed from all-rights-reserved on 2026-03-31 (commit history) | G | syn | general | PII, 19 labels, no ORG |
| [ai4privacy/pii-masking-openpii-1.5m](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1.5m) | same as 1M | G | syn | general | PII. EU rows equal the 1M set's (plus Asian languages), so the two should not be stacked |
| [ai4privacy/pii-masking-400k](https://huggingface.co/datasets/ai4privacy/pii-masking-400k) | YAML `other`; LICENSE: "Access to this dataset is granted exclusively for academic research and non-commercial purposes" | R | syn | general | PII; en/it/fr/de/es/nl |
| [ai4privacy/pii-masking-300k](https://huggingface.co/datasets/ai4privacy/pii-masking-300k) | YAML `other`; LICENSE.md same academic/non-commercial text | R | syn | general, finance | PII; en/fr/de/it/es/nl |
| [ai4privacy/pii-masking-200k](https://huggingface.co/datasets/ai4privacy/pii-masking-200k), [-65k](https://huggingface.co/datasets/ai4privacy/pii-masking-65k) | no YAML licence; LICENSE: custom free licence for individuals, small for-profits and non-profits only, no distribution of derivatives | R | syn | general | PII; en/fr/de/it |
| [ai4privacy/open-pii-masking-500k-ai4privacy](https://huggingface.co/datasets/ai4privacy/open-pii-masking-500k-ai4privacy) | YAML `other` / `cc-by-4.0`, but the body binds the Llama 3.1/3.3 Community Licence (derived models named "Llama…") and says commercial use "may require explicit written permission" | A/R | syn | general | PII; en/fr/de/es/it/nl |
| [gretelai/synthetic_pii_finance_multilingual](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual) | YAML `apache-2.0`; body "All data in this generated dataset is Apache 2.0 licensed" | G | syn | finance | PII, about 29 types |
| [nvidia/Nemotron-PII](https://huggingface.co/datasets/nvidia/Nemotron-PII) | YAML `cc-by-4.0`; body CC BY 4.0, "ready for commercial use" | G | syn | 50+ industries | PII, 55 types; **English only** |
| [E3-JSI/synthetic-multi-pii-ner-v1](https://huggingface.co/datasets/E3-JSI/synthetic-multi-pii-ner-v1) | YAML `mit` | G | syn | health, finance, legal | PII; en, nl, de, fr, sl, it, el, about 400 rows each |
| [Wismut/nym-pii-multilingual-data](https://huggingface.co/datasets/Wismut/nym-pii-multilingual-data) | YAML `mit`, body "MIT." (LAB-1404 found no LICENSE file at an earlier revision; check the revision you pin) | G | syn (LLM templates + Faker) | general | PII, 40 types; de fr es it pt nl pl sv cs ro fi da el; per-language counts not stated |
| [urchade/synthetic-pii-ner-mistral-v1](https://huggingface.co/datasets/urchade/synthetic-pii-ner-mistral-v1) | YAML `apache-2.0` | G | syn | general | PII; en fr it de es |

**Real-text corpora (ADR 0005 applies)**

| Source | Licence string (where found) | Col. | Kind | Domain | Types |
|---|---|:-:|---|---|---|
| [joelniklaus/mapa](https://huggingface.co/datasets/joelniklaus/mapa) | YAML `cc-by-4.0`; body "Attribution 4.0 International (CC BY 4.0)". The original ELRC-SHARE record could not be read: the repository announced termination in October 2025 | G | gold, single annotator | EUR-Lex legal | PII-style, two levels: PERSON, ADDRESS, ORGANISATION, DATE, AMOUNT, plus ID document, SSN, e-mail, licence plate and more |
| [MLRS/mapa_maltese](https://huggingface.co/datasets/MLRS/mapa_maltese) | YAML `cc-by-4.0` | G | gold (hand-corrected MAPA) | legal | MAPA tags; 3,901 / 1,093 / 2,109 sentences |
| [piimb/mapa-eur-lex-pii](https://huggingface.co/datasets/piimb/mapa-eur-lex-pii) | CC BY 4.0, but the card says evaluation only, "not for training"; the non-English labels are LLM-projected | G (eval only) | mixed | legal | PII; already our `mapa-eur-lex` test set |
| [Universal NER v1](https://huggingface.co/datasets/universalner/universal_ner) | "CC BY-SA 4.0" (card). The underlying UD treebanks are CC BY-SA 4.0, except the PUD sets, which are CC BY-SA 3.0 | A | gold | UD genres | PLO |
| [MultiCoNER v2](https://huggingface.co/datasets/MultiCoNER/multiconer_v2) | YAML `cc-by-4.0`; body CC BY 4.0 | G | gold | wiki, queries | 33 fine types, no PII ids |
| [WikiNER](https://figshare.com/articles/dataset/Learning_multilingual_named_entity_recognition_from_Wikipedia/5462500) (Nothman et al. 2013) | "CC BY 4.0" (figshare record) | G | silver | Wikipedia | PLO+MISC |
| [unimelb-nlp/wikiann](https://huggingface.co/datasets/unimelb-nlp/wikiann) (PAN-X) | YAML `unknown`; body "[More Information Needed]"; [XTREME](https://huggingface.co/datasets/google/xtreme) states nothing specific to PAN-X | R (no licence) | silver | Wikipedia | PLO |
| [rmyeid/polyglot_ner](https://huggingface.co/datasets/rmyeid/polyglot_ner) | YAML `unknown` | R (no licence) | silver | Wikipedia | PLO; 22 EU languages, no ga/mt |
| [Babelscape/multinerd](https://huggingface.co/datasets/Babelscape/multinerd) | YAML `cc-by-nc-sa-4.0`; body "restricted to only non-commercial research purposes" | R | silver | wiki, news | 15 types |
| [Babelscape/wikineural](https://huggingface.co/datasets/Babelscape/wikineural) | YAML `cc-by-nc-sa-4.0` | R | silver | Wikipedia | PLO+MISC |
| [bltlab/open-ner-standardized](https://huggingface.co/datasets/bltlab/open-ner-standardized) (OpenNER 1.0) | "CC-BY 4.0 for the OpenNER collection. Individual datasets have their own licenses" | A (per sub-set) | gold | mixed | PLO; use the sub-sets' own licences ([§1c](#1c-national-corpora)) |
| [TAB](https://github.com/NorskRegnesentral/text-anonymization-benchmark) | "MIT License" (annotations) | G | gold | ECHR judgments | PII with masking decisions; en; already our `tab-echr` test set |

### 1c. National corpora

The colour is for training weights. The size is as stated by the source.

| lang | Corpus | Licence string (where found) | Col. | Size | Kind, domain, types |
|---|---|---|:-:|---|---|
| bg | BSNLP 2017–2023 shared tasks ([2024 consolidated corpus](https://arxiv.org/abs/2404.00482)) | not stated on the task pages; secondary reports of the consolidated corpus conflict (BY-SA vs BY-NC) | A/R | 5,017 docs (bg cs pl sl ru uk) | gold, news, PER/LOC/ORG/EVT/PRO |
| bg | BulTreeBank NE | not stated | A | – | gold |
| cs | [CNEC 2.0](http://hdl.handle.net/11858/00-097C-0000-0023-1B22-8) | "Attribution-NonCommercial-ShareAlike 3.0 Unported (CC BY-NC-SA 3.0)" (LINDAT) | R | 8,993 sent., 35,220 ents | gold, news, two-level fine types |
| sk | [WikiGoldSK](https://huggingface.co/datasets/NaiveNeuron/wikigoldsk) | YAML `cc-by-sa-3.0` | A | over 10k ents | gold, Wikipedia, PLO+MISC |
| sl | [SUK 1.1](http://hdl.handle.net/11356/1959) | "Creative Commons - Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)" (CLARIN.SI) | A | NE in about 570k words | gold, mixed, PER/LOC/ORG/MISC/DERIV |
| sl | [ssj500k 2.2](http://hdl.handle.net/11356/1210) | "CC BY-NC-SA 4.0" (CLARIN.SI); the classla HF mirror says `cc-by-sa-4.0` | R | 586k tokens | gold |
| hr | [hr500k 1.0](http://hdl.handle.net/11356/1183) | "Creative Commons - Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)" (CLARIN.SI); successor 11356/1792 not checked | A | 24,624 sent. | gold, mixed |
| fi | [Turku NER](https://github.com/TurkuNLP/turku-ner-corpus) | LICENSE "Creative Commons Attribution-ShareAlike 4.0 International"; the TurkuNLP HF card says `cc-by-nc-sa-4.0` | A | – | gold, multi-genre, 6 types |
| fi | [FiNER](https://github.com/mpsilfve/finer-data) | README: "CC BY-ND-NC 1.0" (Digitoday training data), "CC BY-SA 3.0" (Wikipedia test set); the HF mirror says `mit` | R | 193,742 tokens | gold, tech news |
| et | [EstNER](https://huggingface.co/datasets/tartuNLP/EstNER) | "Creative Commons Attribution 4.0 International License" | **G** | 23.1k sent. | gold, news and social media, 11 types |
| lv | [LUMII FullStack NE](https://github.com/LUMII-AILab/FullStack) | "Creative Commons Attribution-ShareAlike 4.0 International License" | A | 9,697 ents | gold, balanced, 9 types |
| lt | none found open; TildeNER not stated | – | – | – | **MAPA is the only open source** |
| ro | [RONEC v2](https://github.com/dumitrescustefan/ronec) | LICENSE "MIT License" | **G** | about 9k sent. (OpenNER) | gold, 16 OntoNotes-style types |
| ro | [LegalNERo](https://zenodo.org/records/4922385) | `cc-by-nc-nd-4.0` (Zenodo); the UNER mirror says CC-BY-SA-4.0 | R | – | gold, legal |
| el | [elNER](https://github.com/nmpartzio/elNER) | badge "CC BY-NC-SA 4.0" | R | 17k sent. | gold, news, 4 or 18 types |
| el | greek_legal_ner (LEXTREME) | `cc-by-nc-sa-4.0` | R | – | gold, legal |
| hu | [NYTK-NerKor](https://github.com/nytud/NYTK-NerKor) | "CC-BY-SA 4.0" | A | 1M tokens | gold, multi-genre, PLO+MISC |
| hu | Szeged NER | not stated | A | 200k tokens | gold, business and criminal news |
| da | [DaNE](https://huggingface.co/datasets/alexandrainst/dane) | CC BY-SA 4.0 | A | 5,512 sent. | gold, PLO+MISC |
| da | [DANSK](https://huggingface.co/datasets/chcaa/dansk-ner) | card text "Creative Commons Attribution-Share Alike 4.0 International"; YAML empty | A | 14.7k sent. | gold, multi-domain, 18 types |
| sv | [SUC 3.0 NE, scrambled](https://huggingface.co/datasets/KBLab/sucx3_ner) | "CC-BY-4.0" for the scrambled release; the unscrambled release needs an individual licence | **G** | 74k sent. | gold, balanced, 9 types |
| sv | [swedish_ner_corpus](https://github.com/klintan/swedish-ner-corpus) | LICENSE "CC BY 4.0" | G | small | semi-manual |
| nl | CoNLL-2002 nl | HF: "The licensing status of the data, especially the news source text, is unknown" | R | 15.8k sent. | gold, news |
| nl | SoNaR-1 | TST-Centrale / IVDNT non-commercial licence | R | 1M words | gold |
| es | [MEDDOCAN](https://zenodo.org/records/4279323) | "Creative Commons Attribution 4.0 International (CC BY 4.0)" | **G** | 1,000 synthetic clinical cases | **gold PHI: the only green real-format PII set outside English** |
| es | [AnCora-ES](https://huggingface.co/datasets/CLiC-UB/AnCora-ES) | YAML `cc-by-4.0` (gated) | G | – | gold, news |
| es | CoNLL-2002 es | unknown (HF) | R | 8.3k sent. | gold, news |
| pt | [LeNER-Br](https://github.com/peluz/lener-br) | repo LICENSE "MIT License" (may cover only the code); HF `unknown` | A | 7.8k sent. | gold, pt-BR legal |
| pt | HAREM | not stated | A | – | gold, mostly pt-PT |
| it | [KIND](https://github.com/dhfbk/KIND) | "Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)"; De Gasperi part CC BY-NC-SA 4.0 | R | about 1M tokens | gold/silver, PLO |
| it | I-CAB, EVALITA NER | research-only / `cc-by-nc-sa-4.0` | R | – | gold, news |
| fr | Quaero, FTB-NE | ELRA licences (paid or non-commercial) / French Treebank licence | R | – | gold |
| de | [GermEval 2014](https://sites.google.com/site/germeval2014ner/) | site: "distributed under the CC-BY license"; the HF card body says CC BY-SA 4.0 | G/A | 31k sent. | gold, wiki and news, nested PLO+OTH |
| de | [German LER](https://huggingface.co/datasets/elenanereiss/german-ler) | YAML `cc-by-4.0` | G | – | gold, court decisions, 19 types |
| de | [GraSCCo_PHI](https://zenodo.org/records/11502329) | `cc-by-4.0` (Zenodo) | G | about 1.4k PHI | gold PHI, synthetic clinical |
| en | CoNLL-2003, OntoNotes 5, i2b2/n2c2 | Reuters research terms / LDC / DUA | R | – | – |
| en | Few-NERD | CC BY-SA 4.0 (data; code Apache-2.0) | A | – | fine-grained |
| pl | [NKJP 1M](http://nkjp.pl/) | nkjp.pl: "CC-BY 4.0"; the HF `nkjp/nkjp-ner` mirror says "GNU GPL v.3" | G from nkjp.pl | 1M words | gold, balanced, PER/ORG/places |
| pl | [KPWr-NER](https://huggingface.co/datasets/clarin-pl/kpwr-ner) | YAML `cc-by-3.0` (the CLARIN-PL record was not reachable; `clarin-knext/kpwr` says `cc-by-sa-4.0`) | G/A | 18.3k rows | gold, fine-grained |
| ga | Adkins et al. 2025 Irish NER (1,249 sent.) | no release location or licence in the paper | – | – | **unavailable; MAPA is the only open source**. `tlabdev/ner-irish-dataset` on HF is Indonesian |
| mt | MLRS/mapa_maltese (above) | `cc-by-4.0` | G | 3.9k train sent. | the only Maltese NER data found |

### 1d. Parallel corpora for label projection

Projection means translating or aligning labelled English or Hungarian text to another
language and carrying the spans across. It is a way to reach languages with no green gold
data. These corpora are real text, so ADR 0005 applies to training on their sentences.
Projecting *our synthetic documents* through machine translation does not touch real text.

| Corpus | Terms (where found) | Col. | ga | mt | Domain |
|---|---|:-:|:-:|:-:|---|
| [Europarl v7/v10](https://www.statmt.org/europarl/) | no licence: "We are not aware of any copyright restrictions of the material" | A | no | no | parliament |
| [DGT-TM](https://joint-research-centre.ec.europa.eu/language-technology-resources/dgt-translation-memory_en) | "exclusive property of the European Commission"; free reuse under Decision 2011/833/EU with acknowledgement | G | little | yes | legislation |
| [JRC-Acquis](https://joint-research-centre.ec.europa.eu/language-technology-resources/jrc-acquis_en) | 2011/833/EU reuse with attribution; Eurovoc needs a separate licence for commercial use | G | no | yes | legislation |
| [EUR-Lex](https://eur-lex.europa.eu/content/legal-notice/legal-notice.html) | Commission legal notice: EU content "licensed under … (CC BY 4.0)" ([commission.europa.eu](https://commission.europa.eu/legal-notice_en)); EUR-Lex's own notice was not retrieved | G | limited | yes | law, case law |
| [MultiEURLEX](https://huggingface.co/datasets/coastalcph/multi_eurlex) | `cc-by-4.0` plus EU reuse terms | G | no | yes | law (comparable, not sentence-aligned) |
| [ParaCrawl v9](https://paracrawl.eu/) | "We license the actual packaging of these parallel data under the Creative Commons CC0 license"; "We do not own any of the text" | G (packaging) / A (text) | 3.25M sent. | 1.21M sent. | web |
| [MaCoCu mt-en 2.0](http://hdl.handle.net/11356/1811) | "CC0-No Rights Reserved" | G (packaging) | – | 925k seg. | web |
| [Tatoeba](https://opus.nlpl.eu/legacy/Tatoeba.php) | CC BY 2.0 FR | G | yes | yes | short sentences |
| [WikiMatrix](https://opus.nlpl.eu/legacy/WikiMatrix.php) | CC-BY-SA 4.0 | A | no | no | Wikipedia |
| [ELRC-EMEA](https://opus.nlpl.eu/legacy/ELRC-EMEA.php) | CC-BY-4.0 (check per resource) | G | no | yes | medical |
| CCMatrix, EUbookshop, EMEA (OPUS) | no licence on the OPUS pages | A | – | – | web, EU publications, medical |
| OpenSubtitles | no licence; asks only for a link and citation | R | yes | no | subtitles |
| JW300 | withdrawn: "distributed without permission from the copyright holders" ([arXiv 2201.05609](https://arxiv.org/abs/2201.05609)) | R | – | – | religious |

## 2. XLM-R pretraining coverage

From Table 6 of [Conneau et al. 2020](https://arxiv.org/abs/1911.02116) (CC-100, millions of
tokens and GiB):

| lang | tokens (M) | GiB | | lang | tokens (M) | GiB |
|---|---:|---:|---|---|---:|---:|
| bg | 5,487 | 57.5 | | it | 4,983 | 30.2 |
| cs | 2,498 | 16.3 | | lt | 1,835 | 13.7 |
| da | 7,823 | 45.6 | | lv | 1,198 | 8.8 |
| de | 10,297 | 66.6 | | **mt** | **absent** | – |
| el | 4,285 | 46.9 | | nl | 5,025 | 29.3 |
| en | 55,608 | 300.8 | | pl | 6,490 | 44.6 |
| es | 9,374 | 53.3 | | pt | 8,405 | 49.1 |
| et | 843 | 6.1 | | ro | 10,354 | 61.4 |
| fi | 6,730 | 54.3 | | sk | 3,525 | 23.2 |
| fr | 9,780 | 56.8 | | sl | 1,669 | 10.3 |
| **ga** | **86** | **0.5** | | sv | 77.8 (as printed) | 12.1 |
| hr | 3,297 | 20.5 | | hu | 7,807 | 58.4 |

- **Swedish:** the paper's token figure next to 12.1 GiB looks like a typo; the GiB figure is
  the reliable one.
- **Weak pretraining:** Estonian, Latvian and Slovene have under 2B tokens. Irish has 86M.
- **Maltese:** none at all. Maltese uses the Latin script with ċ, ġ, ħ, ż and `għ`, so the
  SentencePiece vocabulary can represent it. The encoder has simply never been trained on it.

## 3. Per-language verdict

**Columns:**

- **Gap:** how much is missing for a model *and* rules to reach the en/de/hu bar.
  0 = shipped; low = green gold names data plus OpenPII; medium = green names data is MAPA
  only, or amber; high = no green real gold at all, or weak pretraining; severe = no OpenPII
  and almost no data.
- **Synthetic must carry:** whether our pipeline (fictional documents written by Muse, labelled
  by the Muse Glimmer teacher) has to supply the language because nothing licence-clean exists.
  It always supplies the **identifiers**: no real corpus outside MEDDOCAN, MAPA, GraSCCo and TAB
  labels them.

| lang | Best licence-clean real source(s) | XLM-R | Gap | Synthetic must carry |
|---|---|---|---|---|
| bg | MAPA (1.4k, G) | strong | medium | names and identifiers |
| cs | MAPA (1.5k, G); CNEC is R | medium | medium | names and identifiers |
| da | MAPA (G); DaNE/DANSK (A) | strong | low/medium (A if SA is accepted) | identifiers |
| de | GermEval 2014, German LER, GraSCCo_PHI (G) | strong | 0 (shipped) | – |
| el | MAPA (G); elNER is R | strong | medium | names and identifiers |
| en | TAB (G); Nemotron, Gretel (G, syn) | strong | 0 (shipped) | – |
| es | MEDDOCAN (G, PHI), AnCora (G), MultiCoNER (G), WikiNER (G) | strong | low | identifiers (NIF/NIE) |
| et | EstNER (G), MAPA (G) | weak (843M) | low/medium | identifiers |
| fi | MAPA (G); Turku (A); FiNER is R | strong | medium | names and identifiers |
| fr | WikiNER (G), MultiCoNER (G), MAPA (G) | strong | low | identifiers (NIR) |
| **ga** | MAPA only (1.4k, G) | **very weak (86M)** | **severe** | **everything**: no OpenPII rows, no gold beyond MAPA |
| hr | none green; hr500k, UNER (A) | medium | **high** | names and identifiers (OIB) |
| hu | MAPA (G); NerKor (A) | strong | 0 (shipped) | – |
| it | WikiNER (G), MultiCoNER (G), MAPA (G); KIND is R | strong | low | identifiers (codice fiscale) |
| lt | MAPA only (G) | medium | **high** | names and identifiers |
| lv | MAPA (G); FullStack (A) | weak (1.2B) | high | names and identifiers |
| **mt** | MAPA + MLRS mapa_maltese (3.9k, G) | **absent** | **severe** | **everything**, and the encoder never saw Maltese |
| nl | WikiNER (G), MAPA (G) | strong | low/medium | identifiers (BSN) |
| pl | NKJP from nkjp.pl (G), KPWr (G/A), WikiNER (G) | strong | 0 (rules shipped; NER not gated) | – |
| pt | MultiCoNER (G), WikiNER (G), MAPA (G); mostly pt-BR elsewhere | strong | low/medium | identifiers (NIF, CC) and pt-PT forms |
| ro | RONEC (G, MIT), MAPA (G) | strong | low | identifiers (CNP) |
| sk | MAPA (G); WikiGoldSK, UNER (A) | medium | medium | names and identifiers |
| sl | none green; SUK (A); ssj500k is R | weak (1.7B) | **high** | names and identifiers (EMŠO) |
| sv | SUC 3.0 scrambled (G), MultiCoNER (G), MAPA (G) | strong | low | identifiers (personnummer) |

Without an ADR 0005 amendment, the "best real source" column is the **evaluation** plan, and
synthetic data carries every language.

## 4. National identifiers for rules

Abbreviations: **Check** says whether the identifier has a check digit. **In repo** says
whether `src/pii_guard` has a validating rule today. ✓ means a checksum rule exists. *cue*
means the word only appears in the generic number-label list of
[`detect/ner_numbers.py`](../src/pii_guard/detect/ner_numbers.py), with no validation.

**Checksum details are research leads, not specs.**
- **Where the details come from:** about a third of the algorithm details were read from
  source code or official sheets during this audit. The rest are recalled and must be
  checked against the official specification before a rule is written. The yes/no is
  reliable; the weights are not.
- **What the spec links are:** the
  [python-stdnum](https://arthurdejong.org/python-stdnum/) module pages, which cite their
  sources.
- **Licence:** python-stdnum is **LGPL-2.1-or-later**. Reimplement from the published
  specifications; don't copy its code into this Apache-2.0 repository.
- **Primary national specs:** the European Commission's
  [TIN portal](https://taxation-customs.ec.europa.eu/online-services/online-services-and-databases-taxation/taxpayer-identification-number-tin_en)
  publishes per-country TIN sheets (now as a ZIP bundle) with the primary national
  specifications.

| CC | Identifier | Format | Check | Spec (secondary) | In repo |
|---|---|---|---|---|---|
| AT | Sozialversicherungsnummer | 10 digits, check digit in 4th position, then DDMMYY | yes, weighted mod 11 | [at.vnr](https://arthurdejong.org/python-stdnum/doc/stdnum.at.vnr.html) | – |
| AT | Abgabenkontonummer (tax) | 9 digits | yes, Luhn-style | [at.tin](https://arthurdejong.org/python-stdnum/doc/stdnum.at.tin.html) | – |
| BE | Rijksregisternummer / numéro national | 11 digits, YYMMDD-SSS-CC | yes, 97 − (n mod 97), with a 2000+ variant | [be.nn](https://arthurdejong.org/python-stdnum/doc/stdnum.be.nn.html) | – |
| BG | EGN | 10 digits, birth date with month offset | yes, weighted mod 11 | [bg.egn](https://arthurdejong.org/python-stdnum/doc/stdnum.bg.egn.html) | cue |
| CY | Tax identification code (TIC) | 8 digits + letter | unclear (Microsoft Purview: "not applicable"; stdnum checks the same-shaped VAT number's letter) | [cy.vat](https://arthurdejong.org/python-stdnum/doc/stdnum.cy.vat.html) | – |
| CY | ID card number | not researched | unclear | – | – |
| CZ/SK | Rodné číslo | YYMMDD/XXX(X); month +50 for women, +20/+70 since 2004 | yes for 10 digits (divisible by 11); none for 9-digit pre-1954 numbers | [cz.rc](https://arthurdejong.org/python-stdnum/doc/stdnum.cz.rc.html), [sk.rc](https://arthurdejong.org/python-stdnum/doc/stdnum.sk.rc.html) | cue |
| DE | Steuer-ID | 11 digits | yes, ISO 7064 MOD 11,10 | [de.idnr](https://arthurdejong.org/python-stdnum/doc/stdnum.de.idnr.html) | ✓ (`languages/de`) |
| DE | Sozialversicherungsnummer | 12 characters: area + DDMMYY + letter + serial + check | yes | [de.wikipedia](https://de.wikipedia.org/wiki/Versicherungsnummer) | ✓ (`languages/de`) |
| DK | CPR | DDMMYY-SSSS | mod 11 **dropped in 2007**: never reject on it | [dk.cpr](https://arthurdejong.org/python-stdnum/doc/stdnum.dk.cpr.html) | – |
| EE | Isikukood | 11 digits, GYYMMDDSSSC | yes, two-pass mod 11 | [ee.ik](https://arthurdejong.org/python-stdnum/doc/stdnum.ee.ik.html) | – |
| ES | DNI / NIF | 8 digits + letter | yes, mod 23 letter | [es.dni](https://arthurdejong.org/python-stdnum/doc/stdnum.es.dni.html), [es.nif](https://arthurdejong.org/python-stdnum/doc/stdnum.es.nif.html) | cue |
| ES | NIE | X/Y/Z + 7 digits + letter | yes, mod 23 letter | [es.nie](https://arthurdejong.org/python-stdnum/doc/stdnum.es.nie.html) | cue |
| FI | Henkilötunnus | DDMMYY + century sign + ZZZ + check character (new century signs since 2023) | yes, mod 31 | [fi.hetu](https://arthurdejong.org/python-stdnum/doc/stdnum.fi.hetu.html) | – |
| FR | NIR (INSEE) | 13 digits + 2-digit key; 2A/2B for Corsica | yes, 97 − (n mod 97) | [fr.nir](https://arthurdejong.org/python-stdnum/doc/stdnum.fr.nir.html) | – |
| FR | Numéro fiscal (SPI) | 13 digits | yes, mod 511 | [fr.nif](https://arthurdejong.org/python-stdnum/doc/stdnum.fr.nif.html) | – |
| GR | AMKA | 11 digits, DDMMYY + 5 | yes, Luhn | [gr.amka](https://arthurdejong.org/python-stdnum/doc/stdnum.gr.amka.html) | – |
| GR | AFM (tax) | 9 digits | yes, mod 11 | [gr.vat](https://arthurdejong.org/python-stdnum/doc/stdnum.gr.vat.html) | – |
| HR | OIB | 11 digits | yes, ISO 7064 MOD 11,10 | [hr.oib](https://arthurdejong.org/python-stdnum/doc/stdnum.hr.oib.html) | cue |
| HU | Személyi azonosító, adóazonosító jel, TAJ | 11, 10 and 9 digits | yes, all three | repo `detect/checksums.py` (stdnum has none) | ✓ (`detect/checksums.py`) |
| IE | PPSN | 7 digits + check letter (+ A/B/H) | yes, weighted mod 23 | [ie.pps](https://arthurdejong.org/python-stdnum/doc/stdnum.ie.pps.html) | – |
| IT | Codice fiscale | 16 alphanumeric characters | yes, odd/even table, mod 26 | [it.codicefiscale](https://arthurdejong.org/python-stdnum/doc/stdnum.it.codicefiscale.html) | – |
| LT | Asmens kodas | 11 digits (same scheme as Estonia) | yes, two-pass mod 11 | [lt.asmens](https://arthurdejong.org/python-stdnum/doc/stdnum.lt.asmens.html) | – |
| LU | Matricule national | 13 digits, YYYYMMDD + NNN + 2 check digits | unclear: Luhn + Verhoeff per secondary sources only; not in the official TIN sheet | EU TIN sheet (LU) | – |
| LV | Personas kods | old DDMMYY-CNNNN; since 2017 `32` + 9 digits | old: yes (mod 11); new: **unclear** (stdnum says its algorithm "has not been confirmed by an independent source"). Match the shape; use the check only to raise confidence | [lv.pvn](https://arthurdejong.org/python-stdnum/doc/stdnum.lv.pvn.html) | – |
| MT | ID card number (also the TIN) | 7 digits + letter (M, G, A, P, L, H, B, Z) | **no** | [Microsoft Purview](https://learn.microsoft.com/en-us/purview/sit-defn-malta-identity-card-number) | – |
| NL | BSN | 9 digits | yes, "11-proef" | [nl.bsn](https://arthurdejong.org/python-stdnum/doc/stdnum.nl.bsn.html) | cue |
| PL | PESEL, NIP, REGON, ID card, passport | 11 / 10 / 9 or 14 / 3 letters + 6 digits / 2 letters + 7 digits | yes, all | [pl.pesel](https://arthurdejong.org/python-stdnum/doc/stdnum.pl.pesel.html) | ✓ (`languages/pl`) |
| PT | NIF | 9 digits | yes, mod 11 | [pt.nif](https://arthurdejong.org/python-stdnum/doc/stdnum.pt.nif.html) | cue |
| PT | Cartão de Cidadão | 12 characters (NIC + check + 2 letters + check) | yes | [pt.cc](https://arthurdejong.org/python-stdnum/doc/stdnum.pt.cc.html) | – |
| RO | CNP | 13 digits, SYYMMDDJJNNNC | yes, weighted mod 11 | [ro.cnp](https://arthurdejong.org/python-stdnum/doc/stdnum.ro.cnp.html) | cue |
| SE | Personnummer / samordningsnummer | YYMMDD-NNNC (`+` from age 100; day +60 for samordningsnummer) | yes, Luhn | [se.personnummer](https://arthurdejong.org/python-stdnum/doc/stdnum.se.personnummer.html) | – |
| SI | EMŠO | 13 digits, DDMMYYYRRBBBK | yes, weighted mod 11 | [si.emso](https://arthurdejong.org/python-stdnum/doc/stdnum.si.emso.html) | cue |
| SI | Davčna številka | 8 digits | yes, mod 11 | [si.ddv](https://arthurdejong.org/python-stdnum/doc/stdnum.si.ddv.html) | – |

**Already language-independent:** IBAN for every EU country (mod 97, with per-country
lengths), payment cards (Luhn) and ICAO 9303 MRZ (`detect/checksums.py`). The English pack
adds US SSN and UK NINO.

**Weak rules on their own:** the Danish CPR (no checksum since 2007), the Maltese ID card (no
checksum) and the new Latvian codes (unclear) need cue words (`cues.tsv`) to be precise.

## 5. Acquisition plan

**Ordering.** The 24-language MAPA baseline (LAB-1516) has no PR yet. Its per-language leak
should **re-order this list** when it lands. Until then the order is gap severity × speaker
population: approximate native speakers in the EU, used for ranking only.

**Steps 0 to 2 can start now**: they need no real data and no model change.
**Steps 3 and later wait for the 2026-11-01 NER freeze** and, for real text, the ADR decision.

0. **Decide ADR 0005** (owner). Choose between:
   - *eval-only*: real corpora are scored, never trained on;
   - *amend*: green, already-public real corpora may train the NER, are never committed, and
     pass the decontamination gate.

   Everything below that says "train" depends on this.
1. **Rules for the biggest languages without a pack**, synthetic fixtures only.
   - Covers fr (NIR, SPI), it (codice fiscale), es (DNI/NIF/NIE), ro (CNP) and nl (BSN).
   - Together about 230M speakers.
   - All have checksums.
   - These need no NER data at all: identifiers are rule-led.
2. **Rules for the next group.** Each is about one day of `pii-guard lang new` work:
   - pt (NIF, CC), el (AMKA, AFM), cs/sk (rodné číslo), sv (personnummer), bg (EGN),
     hr (OIB), fi (henkilötunnus), da (CPR, cue-led), be (national number; nl/fr text).
   - Then sl (EMŠO), lt/et (asmens kodas, isikukood), lv (personas kods), ie (PPSN), lu, at,
     mt (ID card, cue-led), cy.
3. **Synthetic NER data for the 20 new languages.**
   - **Source rows:** OpenPII-1M train rows (G, already in our pipeline at 5k per language
     for en/de/hu), extended to the 20 new languages it covers.
   - **Muse-written documents:** add these for the high-gap languages first (hr, sl, lt, lv,
     then cs, sk, bg, el, fi). Glimmer labels them, and the language pack's lexicons (given
     names, surnames, streets) feed the generator.
   - Gretel (G) adds finance-domain es/fr/it/nl/sv. E3-JSI and nym (G) are small add-ons
     after a revision-pinned licence check.
4. **Evaluation sets per language, real text never committed:**
   - MAPA train split (G) for 21 languages, as a *second* MAPA lane next to our test set.
   - Decontaminate it against `mapa-eur-lex`, because both come from the same MAPA EUR-Lex
     release.
   - Plus the green national sets: EstNER, RONEC, SUC scrambled, MEDDOCAN, AnCora, GermEval,
     NKJP, MLRS Maltese.
   - Amber sets (NerKor, DaNE, hr500k, SUK, Turku, FullStack, UNER) are fine for
     **evaluation**: share-alike binds redistribution of the data, which scoring in place
     does not do.
5. **If ADR 0005 is amended: real gold names data.**
   - Green only, in this order of need: MAPA (all 21 languages), RONEC, EstNER, SUC
     scrambled, AnCora, MEDDOCAN, NKJP, MultiCoNER (de en es fr it pt sv), WikiNER (silver).
   - Amber stays out of training until a legal opinion on share-alike and model weights.
6. **Irish and Maltese last.** They are about 0.7M speakers together, but they have the
   largest gaps.
   - Maltese needs an encoder decision: measure XLM-R zero-shot on MLRS mapa_maltese first.
     If it is too weak, evaluate a Maltese-pretrained encoder (licence to be checked) or
     continued pretraining on CC0 MaCoCu.
   - Irish: synthetic documents plus MAPA, and possibly DGT-TM projection. CC-100 has 86M
     tokens of Irish.
   - Until a language is measured, it stays rules-only and is flagged in `languages.md` as
     not gated.

**Never use:** Ai4Privacy 400k/300k/200k/65k and the 500k Llama-bound set; MultiNERD;
WikiNEuRal; WikiANN; Polyglot-NER; KIND; CNEC; elNER; ssj500k; FiNER; LegalNERo; SoNaR;
CoNLL-2002/2003; OntoNotes. `docs/datasets.md` already rejects WikiANN and the older Ai4Privacy
sets; this audit confirms both from the primary pages.

## Licence surprises

1. **Two Ai4Privacy sets that look open are not.**
   - `open-pii-masking-500k` has `cc-by-4.0` in its YAML, but its body binds the Llama
     Community Licence (derived models named "Llama…").
   - The 400k and 300k sets are academic, non-commercial only.
   - OpenPII-1M itself was "all rights reserved" until 2026-03-31.
2. **MultiNERD and WikiNEuRal**, among the most-used multilingual NER sets, are both
   CC BY-NC-SA 4.0.
3. **KIND (Italian)** is often described as commercially usable because its *source texts*
   are. Its annotations are CC BY-NC 4.0.
4. **Hugging Face mirrors relabel licences, in both directions.**
   - Looser than the original: FiNER is NC-ND upstream but `mit` on HF; ssj500k is NC-SA
     upstream but CC BY-SA on HF.
   - Stricter than the original: Turku NER is BY-SA on GitHub but NC-SA on HF; NKJP is CC BY
     on nkjp.pl but GPL-3 on HF.
   - Always read the original record.
5. **WikiANN/PAN-X**, used in every multilingual NER paper, has no stated licence anywhere.
   The XTREME paper claims only that it selected permissively licensed tasks.
