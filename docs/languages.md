# Adding a language

PII Guard ships Hungarian (`hu`), English (`en`), German (`de`) and Polish (`pl`). Everything a language
contributes is one **language pack**: a Python package with one `LanguagePack` object
([ADR 0010](decisions/0010-language-pack-plugins.md)). The components (rule detector, vault,
LLM detector, evaluation) ask the pack registry for the text's language and fall back to
language-independent behaviour when there is none, so a pack can start small and grow.

A **conformance suite** checks a pack: which parts are present, that they are well-formed,
that masking round-trips on the pack's fixtures, that no allowed inflected form leaks a
masked value, and how the rules score on the pack's smoke set. It tells you what is still
missing; it is also what "done" means (below).

German is the worked example: `src/pii_guard/languages/de/` was written by following this
guide, and every step below points at it. The Polish pack (`src/pii_guard/languages/pl/`,
LAB-1400) was built the same way, from the skeleton below.

## What a pack is made of

| Part | `LanguagePack` field | Used by | Without it |
|---|---|---|---|
| Code and English name | `code`, `name` | everything; the LLM prompt | *required* |
| LLM prompt notes | `prompt` (`prompt.md`) | `detect/llm.py`, substituted into `prompts/system.md` | *required* |
| Smoke fixtures | `smoke_fixtures` (`eval/fixtures/<code>-*.jsonl`) | conformance suite, `pii-guard eval` | *required* |
| Rules, run for every language | `everywhere` | `RuleDetector` | other packs' rules only |
| Rules, run for this language | `rules` | `RuleDetector` | — |
| Inflection matcher | `inflection` | vault, LLM alignment, eval suffixes | exact matching between word boundaries |
| Script / word-boundary profile | `allow_suffix`, `word_boundary` | LLM alignment | suffixes tolerated, word boundaries on |
| Country-specific entity types | `country_entity_types` | the LLM prompt asks for them | generic types only |
| Eval surface forms | `surface_forms` (`SurfaceForms`) | leak rate, corpus spans | exact matching, no stopwords |
| Lexicons | `lexicons` (`LexiconSpec`) | `pii_guard.lang`, the corpus generator, rules | `LexiconUnavailable` |
| Document field captions | `captions` (`captions.tsv`) | `visual/captions.py`: the value next to `Név` / `Date of birth` on an ID card is masked | captions in this language not recognised in images |
| Cue words for numbers | `cues` (`cues.tsv`) | `RuleDetector` via `languages/cues.py`: a number right after `TAJ` or `passport` is masked even when its checksum fails | only the other packs' cues |
| Brand names | `brands` (`brands.tsv`) | `NerDetector` via `detect/ner_orgs.py`: an NER `PERSON` span that is only a company or product name (`OTP Bank`, `Deutsche Bahn`) becomes `ORGANIZATION`, which policy keeps | the shared list (`languages/brands.tsv`) and the other packs' names |

The NER and LLM passes are multilingual: a new language needs no model change, only prompt
notes and a measurement.

## Step by step

### 1. Generate the skeleton

```bash
uv run pii-guard lang new pl --name Polish
```

This writes `src/pii_guard/languages/pl/` (`__init__.py` with the pack, `rules.py`,
`prompt.md`) and `eval/fixtures/pl-smoke.jsonl.example`. A package inside
`src/pii_guard/languages/` is registered automatically. The skeleton already passes the
structural checks:

```bash
uv run pii-guard lang check pl --structure-only
```

`pii-guard lang check pl` (without `--structure-only`) fails until the smoke fixtures exist.

For a language shipped **in its own distribution** (no fork), pass `--dest` and `--tests`,
and register the pack with an entry point in that distribution's `pyproject.toml`:

```toml
[project.entry-points."pii_guard.languages"]
pl = "pii_guard_polish.pl:pack"
```

The entry point names a `LanguagePack` or, as in the skeleton, a function returning one
(packs load lazily, on first use). An installed entry point with the code of a built-in pack
replaces it. A pack that fails to load raises `LanguagePackError`: PII Guard fails closed
rather than silently running without the language.

### 2. Write the smoke fixtures first

About ten hand-written documents in `eval/fixtures/<code>-smoke.jsonl`, in the format of
[contracts.md](contracts.md#evaluation-fixtures-and-harness-implemented): e-mails, a contract,
a letter, a chat message, a form, and at least one **hard negative** (no personal data, but
numbers, dates and amounts that look like it). Every value is fictional
([ADR 0005](decisions/0005-synthetic-data-only.md)): `example.com` addresses, numbers from
fiction ranges, checksummed identifiers computed from made-up payloads. Write them with inline
labels in `eval/fixtures/build_smoke.py` (`{{PERSON|Anna Probst}}`, a detachable suffix outside
the label: `{{PERSON|Anna}}s`) so offsets are never typed by hand; a test fails if the committed
JSONL is stale. German: `de_documents()` in that file.

Writing fixtures first gives you a baseline: run `uv run pii-guard eval --fixtures
eval/fixtures/pl-smoke.jsonl` before any rule exists, and every later step shows its effect.

### 3. Rules

`rules.py` exports two tuples of rule functions. A rule takes the whole text and yields
`_Hit(start, end, entity_type, score)` for **validated** matches only:

- `EVERYWHERE`: identifiers with a checksum or a distinctive format (a German
  Sozialversicherungsnummer: date, letter, check digit). They run for every language, because
  a German ID in an English e-mail is still personal data. Keep them precise: they run on
  every other language's text too.
- `RULES`: formats that are only unambiguous in this language's texts (postcodes, national
  phone numbers, an 11-digit number without its label). They run only for this language.

Accept common printed forms, not only the official one: the Hungarian giro account detector
handles compact values, groups joined by hyphens, spaces or dots, and four-group layouts. IBAN
matching also accepts lowercase text and variable spaces between its groups. When a grouping
is also common for something that is not personal data, require a label instead of dropping
the form: dotted or slashed numeric groups can be thousands-grouped amounts, so those TAJ
variants require a TAJ cue. An unlabelled TAJ (format and checksum only) runs for Hungarian
text only: a one-in-ten check is too weak for another language's nine-digit numbers, such as
a Polish phone number (LAB-1433).

Put check-digit functions next to the rules (`languages/de/checksums.py`) with tests against
the algorithm's published examples. Use the helpers in `detect/rules/_base.py`
(`NUM_START`/`NUM_END` reject digits inside longer numbers and dates, `context_before` finds a
label). Before adding an `EVERYWHERE` rule, check what it does to the other languages: the
hu/en scorecards must not change (`--language hu,en`). That is why the German Steuer-ID runs
everywhere only next to its label: Hungarian personal ID numbers are 11 digits too.

Every German noun is capitalised, so "five digits before a capitalised word" is not a
postcode ("20000 Teilnehmer"); the German postcode rule only fires where an address line
starts. Hard negatives in the smoke set catch this kind of rule.

**Cue words** (`cues=files(__name__).joinpath("cues.tsv")`, scaffolded with commented
examples). The rules above only mask what validates, so a card number with a wrong check
digit or a phone number in an unknown numbering plan is missed even when the text says what
it is. `cues.tsv` lists the words that say so, one `cue<TAB>ENTITY_TYPE` per line, and a
number right after one of them is masked as that type at a lower score (0.6), whatever its
checksum ([languages/cues.py](../src/pii_guard/languages/cues.py)):

```text
Telefon*	PHONE
Kreditkarte*	BANK_ACCOUNT
Steuer-ID	ID_DOCUMENT
Bestellnummer*	-
und	-
```

- The value must have the type's shape (`SHAPES` in `cues.py`: 7–15 digits for a phone,
  12–34 characters for a card or account, 6–20 letters and digits with at least two digits
  for a document number ...). A cue may name only a type with a shape; there is no
  per-language shape to write.
- Matching ignores case and accents; a space in a cue also matches a hyphen or nothing; a
  trailing `*` lets the word take suffixes (`Telefonnummer`, `kártyaszámát`). Up to three
  short words may stand between the cue and the number (`Kreditkarte mit der Nummer`).
- A `-` cue names a number that is not personal data (order, invoice, customer, reference
  numbers, amounts, postcodes) or hands the window on (`und`, `oder`): it ends the window, so
  `Telefon- und Bestellnummer 4500123456` stays unmasked. List the words that introduce
  numbers in your language's invoices and orders; the conformance suite warns when there are
  none.
- Dates, amounts (a currency next to the number) and numbers inside longer runs are rejected,
  and a validated rule's hit always wins.
- Cues run for every text, like `EVERYWHERE` rules: a form in your language may carry
  English labels and the other way round. Pick words that are unambiguous next to a number;
  when two packs map one cue to different types, the text's own language wins.
- Two shared word lists are not read from `cues.tsv` yet, so add your language's order,
  invoice, shipment and amount words to them by hand: `_REFERENCE_WORD` in
  `detect/rules/_base.py` (`reference_or_amount_before`: a validated number right after such a
  label is a business number) and `_NEGATIVE` in `detect/ner_numbers.py` (an NER number right
  after one is dropped). List the generic "number" word of your language in `_GENERIC` and
  `_FILLER` there too (`Nummer`, `numer`), or every cue containing it makes it a positive cue.
- Check them against `eval/fixtures/negative/` (order numbers, amounts, dates, postcodes and
  references without a cue: nothing may be masked) and add a `<code>-uncued-numbers.jsonl`
  there; `PII_GUARD_RULES_CUED_NUMBERS=false` turns the rule off for comparison.

### 4. Inflection matcher

If names or places take suffixes, the vault must mask `Annas` as `[[PERSON_7f3a]]s` and
unmask it back. Implement `suffix_pattern(value, entity_type)`: a regex fragment **without
capturing groups** for what may follow a confirmed value (`""` for nothing). German:

```python
class GermanGenitiveMatcher:
    def suffix_pattern(self, value, entity_type):
        if not value[-1:].isalpha():
            return ""  # codes and numbers take no suffix
        if value.casefold().endswith(("s", "ß", "x", "z", "ce")):
            return "(?:['’])"  # Hans' Fahrrad
        return "(?:['’]s|s|['’])"  # Annas, Anna's
```

If the stem itself changes before a suffix (Hungarian `Zsuzsanna` → `Zsuzsannának`), also
implement the optional `variant_stems`, `splits` and `restore` methods; see
`languages/hu/inflection.py` and the protocol in `languages/inflection.py`. The conformance
suite's property tests generate every suffix your pattern allows and check that the masked
text never contains the value and that unmasking restores the original.

Also set the alignment profile: `allow_suffix=False` if a name never runs on into a longer word
(English), `word_boundary=False` for scripts written without spaces.

### 5. Prompt notes

`prompt.md` is a short bullet list of what the LLM needs to know about this language: how names
inflect and which form to report, titles to leave out, how addresses are written, which local
identifiers map to which entity type, generic roles that are not names. Keep it short and
concrete; the language-neutral instructions are in `detect/prompts/system.md`. A `TODO` left in
the notes is a conformance warning. If the country has identifiers with a type of their own in
`pii_guard.types` (Hungarian `NATIONAL_ID_HU_*`), list them in `country_entity_types`.

### 6. Surface forms and lexicons (optional)

`surface_forms=SurfaceForms(stopwords=...)`: street-type words, month names and company forms,
which the partial-leak check ignores. Subclass `SurfaceForms` and implement `stem_variants`
only if stems change; the evaluation keeps its own copy of those rules on purpose, so the leak
rate is not measured with the code it checks.

`lexicons=LexiconSpec(directory=..., kinds=(...))`: name and place lists for the corpus
generator and for validating addresses, from sources whose terms allow redistribution
([ADR 0009](decisions/0009-third-party-lexicons.md)). German has none yet.

`captions=files(__name__).joinpath("captions.tsv")`: the field captions printed on the
language's ID documents and forms, one `caption<TAB>ENTITY_TYPE` per line (`-` for a caption
whose value is not personal data, such as `Sex` or `Expiry`: it is still recognised, so it
bounds the neighbouring fields). Image masking pairs each caption with the value on its right
or under it and masks that value ([visual/captions.py](../src/pii_guard/visual/captions.py)).
Write captions as printed, with accents; matching ignores case, accents and punctuation and
tolerates small OCR errors. The conformance suite checks that the file parses (and
`cues.tsv`, see [Rules](#3-rules)).

`brands=files(__name__).joinpath("brands.tsv")`: the country's well-known company and brand
names, one per line as written (`OTP Bank`, `Deutsche Bahn`). The NER model sometimes calls a
bare brand a person (`Write a haiku about Meta` came out as `[[PERSON_x]]`, LAB-1336); a
`PERSON` span that is exactly a listed name, plus a suffix your inflection matcher allows for
an organisation (`Google-nek`, `Metáról`, `Metas`), becomes `ORGANIZATION`, which policy
keeps. Global names (Meta, Llama, Google, OpenAI ...) are already in the shared
`languages/brands.tsv`, and every pack's names count for every text. Leave out names that are
also given names or surnames (Ford, Dell, Siemens, Otto): a missed brand is an over-mask, a
missed person a leak. A name your pack's name lexicons list is never relabelled, and neither
is one next to an honorific (`Ms. Apple`) or another part of a name (`Meta Kovács`). Add a
few prompts with your brands to `eval/fixtures/negative/<code>-brand-names.jsonl`.

### 7. Check, measure, document

```bash
uv run pii-guard lang check pl          # structure, fixtures, round trip, smoke scores
uv run pytest tests/languages           # the conformance suite, for every registered pack
uv run pii-guard eval --fixtures eval/fixtures/pl-smoke.jsonl --json eval/results/pl-smoke.json
```

Add a per-language table to [entities.md](entities.md) (identifier, type, validation, scope).

## What "done" means

A language is **supported** when:

1. `pii-guard lang check <code>` conforms (no errors) and `uv run pytest tests/languages`
   passes. Gated: the structural checks, fixtures that validate and are in the pack's
   language, mask → unmask identity on every smoke document, the inflection property tests,
   a 100 % round trip on the smoke set and a rules overlap precision of at least 90 %. Recall
   is reported, not gated: the rules cover structured identifiers; names and dates come from
   the NER and LLM passes.
2. Its smoke-set scorecard is recorded with the commit (see "Reporting" in
   [evaluation.md](evaluation.md)), and the other languages' scorecards are unchanged.
3. `entities.md` documents what its rules find.

Until then a language without a pack still works, as a recall floor: language-independent
rules, every pack's `EVERYWHERE` rules, the multilingual NER and LLM passes with the default
prompt, and exact matching in the vault.

## German smoke results

`uv run pii-guard eval --fixtures eval/fixtures/de-smoke.jsonl` (rules detector, 10 documents
with 40 labels, 2 of them hard negatives without any):

| Detector | P overlap | R overlap | R exact | Leak | Round trip |
|---|---:|---:|---:|---:|---:|
| `rules` | 100.0 | 52.5 | 50.0 | 43.2 | 100.0 |

Every structured identifier is found (addresses, e-mails, phones, Steuer-IDs,
Sozialversicherungsnummern, IBANs: 100 % overlap recall); the misses are the names, dates of
birth and organisations that the rules don't cover by design. Adding the German pack left the
`hu` and `en` scorecards unchanged.

## Polish smoke results

`uv run pii-guard eval --fixtures eval/fixtures/pl-smoke.jsonl` (rules detector, 11 documents
with 47 labels, 2 of them hard negatives without any):

| Detector | P overlap | R overlap | R exact | Leak | Round trip |
|---|---:|---:|---:|---:|---:|
| `rules` | 100.0 | 55.3 | 55.3 | 39.5 | 100.0 |

Every structured identifier is found (PESEL, NIP, REGON, ID-card, passport and driving-licence
numbers, IBANs, phones, addresses); the misses are names, dates of birth and organisations. In
fast mode (rules + NER v2.0) the smoke set leaks 0.0 %, and pl-pii-bench (report-only) goes
from 17.5 to 3.5 % ([results](../eval/results/2026-10-28-lab-1400-pl-pack/README.md)). Adding
the Polish pack left the `hu`, `en` and `de` scorecards unchanged.
