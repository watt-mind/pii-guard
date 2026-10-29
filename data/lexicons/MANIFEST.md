# Lexicon manifest

Third-party name and place lists behind the Hungarian language pack's lexicons
([ADR 0009](../../docs/decisions/0009-third-party-lexicons.md)). They are **names and places,
never person records**: no list says who is called what or who lives where.

`data/lexicons/fetch.py fetch` downloads every source into `data/lexicons/raw/` (gitignored)
with an identifying User-Agent, at most one request per second, after checking `robots.txt`.
`fetch.py normalise` rebuilds the lists from those cached files, offline:

- **committed** lists go to `src/pii_guard/lang/data/hu/` and ship with the package (the
  Docker image copies only `src/`, so the address rule has its gazetteer in the container);
- **local-only** lists go to `data/lexicons/raw/derived/hu/`; set
  `PII_GUARD_LEXICON_DIR=data/lexicons/raw/derived` to use them on your machine.

```bash
uv run --with openpyxl --with pypdf --with osmium python data/lexicons/fetch.py all
uv run python data/lexicons/fetch.py checksums     # the raw-file table below
```

Retrieved 2026-10-27. Re-running `normalise` on these raw files reproduces the committed
lists byte for byte (checked 2026-10-27).

## Sources and terms

| Key | Source | Terms | Use |
|---|---|---|---|
| `ksh-hnt` | KSH Helységnévtár 2026-01-01, <https://www.ksh.hu/docs/helysegnevtar/hnt_letoltes_2026.xlsx> | CC BY 4.0 ([ksh.hu/copyright](https://www.ksh.hu/copyright)). KSH's `robots.txt` disallows `/apps/` (the interactive gazetteer), not `/docs/`. | **Committed** with attribution: settlements (name, county, KSH code, population), postcode → settlement pairs. |
| `ksh-names-*` (7 files) | KSH infographics "Gyermekek utónevei" (`https://www.ksh.hu/infografika/<year>/nevek_<span>.pdf`, spans 2000-2025, 2015-2025, 2024-2025, 2014-2024, 2013-2023, 2012-2022, 2008-2018) | CC BY 4.0 | **Committed**: the 50 most chosen given names of newborns per sex, weighted by how many of the lists they appear in (counts aren't reliably recoverable from the PDF layout). |
| `posta-irsz` | Magyar Posta, <https://www.posta.hu/static/internet/download/Iranyitoszam-Internet_uj.xlsx> | "Minden jog fenntartva" (all rights reserved) | **Fetch-only.** Cross-checks the KSH postcodes locally (`postcodes_posta.tsv`). Outside Budapest, 3283 of Posta's 3321 pairs are also in KSH; all 246 street-level codes it lists for Budapest, Debrecen, Szeged, Pécs, Győr and Miskolc pass the structural check. |
| `bm-surnames` | Belügyminisztérium, 100 most frequent birth family names, 2026-01-01 (kormany.hu document `abb23fee…`) | No licence stated | **Fetch-only** (`surnames.tsv`, with counts). Public statistics, but without stated terms we don't treat them as redistributable. |
| `bm-given` | Belügyminisztérium, 100 most frequent given names per sex, 2026-01-01 (kormany.hu document `3222d7d8…`) | No licence stated | **Fetch-only** (`given_names_m.tsv`, `given_names_f.tsv`, with counts). |
| `osm-hu` | OpenStreetMap Hungary via Geofabrik, <https://download.geofabrik.de/europe/hungary-latest.osm.pbf> (`highway=*` `name` values) | ODbL 1.0, © OpenStreetMap contributors | Full list of 13,361 street names (≥ 2 ways) **fetch-only**. **Committed**: the 100 most common street names and the public-space type counts, a non-substantial extract. Overpass wasn't used: its `robots.txt` disallows `/api/`. |
| — | pii-guard contributors | Apache-2.0 | **Committed**, hand-curated: classic given names (107 male, 99 female) and 227 surnames with frequency tiers, 36 surnames that are also common words (hard negatives). |

**Not obtained:** the HUN-REN NYTK list of registrable given names
(<https://nytud.hu/szolgaltatas/nevadasi-tanacsadas>). The site answers 403 to an identifying
User-Agent, `robots.txt` included; we didn't work around that. The KSH lists and the
hand-curated names cover the generator's needs.

## Committed lists

`src/pii_guard/lang/data/hu/` (192 KB in total). Each file's `#` header names its source.

| File | Entries | Source | SHA-256 |
|---|---:|---|---|
| `settlements.tsv` | 3155 | `ksh-hnt` | `2a0ce672e97abaf10c54a2404c6ea09acbc6dc87da9821ec0a40ff45939af9f9` |
| `postcodes.tsv` | 3632 | `ksh-hnt` | `9f31ef17382110949fc5f1bcb2f97ca52690847813ceb697b4d43666ea4155ca` |
| `recent_given_names_m.tsv` | 70 | `ksh-names-*` | `b2be0434fdfdbc07827fe1c36b7ffed3614d3bc39fda1032901f2112632720dd` |
| `recent_given_names_f.tsv` | 99 | `ksh-names-*` | `ca2d7c166ad9596afc6e410b2df286ff9e5c8fe7731f651d6bf0c7690bf553cf` |
| `street_names.tsv` | 100 | `osm-hu` (top 100) | `372aa7c5a9a78fa19f085a17e1587f989b46229cf3efd75558347eb75b9ffe8a` |
| `street_types.tsv` | 42 | `osm-hu` (counts) | `7e5a4da523a004cda9b61c5a7d90e424b502f948d7a4419756761c36a13ea0cc` |
| `given_names_m.tsv` | 107 | contributors | `cfd04df7394df80b7700ff38cb27f15ee93dd4d49437fc3a715b94d7b9208653` |
| `given_names_f.tsv` | 99 | contributors | `536909cad0d3705d58cf9f001b92749b6a0575d8c313b289cb8d6cf6297c6734` |
| `surnames.tsv` | 227 | contributors | `0d3cb789c4220b8d0f080f201f823b8c513b9cc11b28db66bebeae1262c5641d` |
| `common_word_surnames.tsv` | 36 | contributors | `4186a5a54aea226d2066ffecfd4768941af221cc1c2d7cd9674fc334b5dd9983` |

The English pack has only `src/pii_guard/lang/data/en/street_types.tsv` (hand-written by
contributors, Apache-2.0; SHA-256
`53be2ea6b4996503110ac819d219c3299cfccb882d3c3a20f956dc50d7fbbcbd`).

## Raw files (not committed)

SHA-256 of the files the committed and local lists were built from, as fetched on 2026-10-27.

| Key | File | SHA-256 |
|---|---|---|
| `ksh-hnt` | `ksh-hnt-2026.xlsx` | `bd21f7e80f721093d2d471e4037ffc846c29fbb1d393e4edbd7058259417702d` |
| `ksh-names-2000-2025` | `ksh-nevek_2000-2025.pdf` | `fbb88e0154fef33d41f7f70f49fb1084bfd8c16292e254550e20aea204d940d8` |
| `ksh-names-2015-2025` | `ksh-nevek_2015-2025.pdf` | `f52c79bf5ef73cb6fe00a6f43d6e8e8d775055090e86a9edcf09d72db56536c7` |
| `ksh-names-2024-2025` | `ksh-nevek_2024-2025.pdf` | `9dbf4fb6b4b33e1603387daa802101bf3b24f265940a09e849b476c44e659fbc` |
| `ksh-names-2014-2024` | `ksh-nevek_2014-2024.pdf` | `c7cc91ed13808b0e21956dd09f5ece7debf8b5f55d9e907e8d18b84a203c8d76` |
| `ksh-names-2013-2023` | `ksh-nevek_2013-2023.pdf` | `e797ce60211c85a9313669f56bb574a8545b6c152a7fcf699fa97bd2d9932285` |
| `ksh-names-2012-2022` | `ksh-nevek_2012-2022.pdf` | `027a51a851f5de4c72be907f38b1be14c8f5378ba1c1a8dc9fef9fb96b54979b` |
| `ksh-names-2008-2018` | `ksh-nevek_2008-2018.pdf` | `891551ff11519afa11a6954dfea2d1a5005164caf803a76e29b58c291dcbeca8` |
| `posta-irsz` | `posta-iranyitoszam.xlsx` | `7ed76a7f595396136f6f85b220787b8e712bc44d7adf33dd0a94e44605500906` |
| `bm-surnames` | `bm-csaladinev-2026.xlsx` | `5a2dfe0472fbd1229de1ea03dcdceb03a47ccd0c3e0b514ede3b742b4878f9cf` |
| `bm-given` | `bm-utonev-2026.xlsx` | `1bf7a46a981ebd7b7be155a27c917b21811cf9ed7c90f22f8685c4e401216e01` |
| `osm-hu` | `osm-hungary-latest.osm.pbf` | `95cee027cb022b35b6633c511119d72f19fb6a606e8c8eceba0de80709d66912` |

`hungary-latest` changes daily; a later fetch gives a different hash and slightly different
counts.
