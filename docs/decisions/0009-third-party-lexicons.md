# 0009. Third-party lexicons in language packs

- **Status:** accepted
- **Date:** 2026-10-27

## Context

The synthetic corpus drew Hungarian people and addresses from short hand-picked lists (54
surnames, 20 towns, 25 streets), so a 50-document sample repeated the same 45 surnames and 19
towns, and models trained or tuned on it saw a narrow slice of real names and places. The
rules layer had a matching blind spot: it flagged only the four digits of a postcode before a
capitalized word, so a masked address still leaked its street, and it couldn't tell a real
Hungarian postcode/town pair from four digits that happen to sit before a capitalized word.

Official public lists exist for all of this (the KSH gazetteer, Magyar Posta's postcode table,
the interior ministry's name statistics, OpenStreetMap streets), but under different terms:
some allow redistribution with attribution, some state no license, some reserve all rights,
and OpenStreetMap's ODbL is share-alike for substantial extracts.

## Decision

**Lexicons are a language-pack contribution** (ADR 0008), looked up by kind and language:
`pii_guard.lang.lexicon(kind, language)` returns a weighted list (`given_names_m/f`,
`surnames`, `settlements`, `postcodes`, `street_types`, `street_names`, plus pack-specific
extras), and `postcode_index(language)` answers "is this postcode one of this settlement's?".
A pack without a kind raises `LexiconUnavailable`; English has only `street_types` for now.

**Committed only where the terms clearly allow it.** `data/lexicons/fetch.py` fetches every
source politely into gitignored `data/lexicons/raw/` and normalizes offline. Lists from
CC BY 4.0 sources (KSH) and our own hand-curated lists are committed, with their source in
each file's header and in [`data/lexicons/MANIFEST.md`](../../data/lexicons/MANIFEST.md)
(URL, retrieval date, terms, SHA-256). Sources with all rights reserved (Magyar Posta) or no
stated license (ministry name statistics) are **fetch-only**: they are normalized to
`data/lexicons/raw/derived/` and used on a developer's machine through
`PII_GUARD_LEXICON_DIR`, never committed. From OpenStreetMap we commit only a non-substantial
extract (the 100 most common street names and the public-space type counts).

**Shipped inside the package**, at `src/pii_guard/lang/data/<code>/`, not in `data/lexicons/`:
the address rule needs the gazetteer at runtime and the Docker image copies only `src/`. The
lists are 192 KB in total, so they stay plain UTF-8 TSV (diffable) instead of gzip.

**Used in two places:**

- **Generator** (`pii_guard.eval`): Hungarian names and places are drawn from the lexicons
  by frequency, flattened with a temperature so small samples are diverse, and combined at
  random, so no generated person is a real one. Every address gets one of its own
  settlement's postcodes. The prompt also asks for **hard negatives**, ordinary phrases that
  look like personal data but aren't (a surname that is a common word used as the word, a
  town outside an address, "Eladó lakás"), which are never labeled.
  `GENERATOR_VERSION` is 2.
- **Rules** (`detect/rules/hu.py`): a full Hungarian address recogniser,
  `[<postcode>] <settlement>[ <district>], <street> <type> <number>[ <floor/door>]`, whose
  span is the whole address. The postcode↔settlement check works like a checksum: a
  consistent pair scores 0.97, an unknown settlement 0.85, and a known settlement with
  another place's postcode 0.75, no more than a bare postcode. Without a postcode, the
  settlement must be in the gazetteer, possibly inflected (`Szegeden`, through the vault's
  Hungarian suffix matcher).

**Postcode structure.** The KSH file lists only the main code of the cities that have
street-level codes. For those, a code is accepted by structure: Budapest is `1` + district
`01`–`23` + one digit (and a written district, `XIII.`, must match), Debrecen, Szeged, Pécs,
Győr and Miskolc share the first two digits of their main code. A code that the gazetteer
assigns to another settlement still fails (`6750` is Algyő, not Szeged). Checked against
Magyar Posta's own table: every street-level code it lists for those six cities passes.

## Consequences

- Names and places are names and places: no list links a name to a person, an address or an
  identifier, and the generator never pairs them with real IDs (ADR 0005 holds).
- Rules-only ADDRESS detection on the Hungarian fixtures goes from 0 to 100% exact recall at
  unchanged precision, and partially leaked addresses (street left after the postcode was
  masked) from over 90% to 0 ([evaluation.md](../evaluation.md)).
- The generator records `meta.lexicons` (a digest of the lists used) in every document, so a
  corpus built with local-only overrides is distinguishable from one built with the packaged
  lists. A corpus generated before version 2 can't be reproduced by the current code.
- A settlement or postcode that changes after the 2026 gazetteer scores as unvalidated or
  mismatched until the lists are refreshed (`fetch.py all`, then commit the diff with a new
  manifest).
- Adding a language's lexicons is the same checklist as the rest of a pack: a fetcher entry
  per source with its terms, a `_PackSpec` in `pii_guard.lang`, and committed lists only where
  the terms allow.
