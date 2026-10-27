# Adding a language

pii-guard ships Hungarian (`hu`), English (`en`) and German (`de`). Everything a language
contributes is one **language pack**: a Python package with one `LanguagePack` object
([ADR 0010](decisions/0010-language-pack-plugins.md)). The components (rule detector, vault,
LLM detector, evaluation) ask the pack registry for the text's language and fall back to
language-independent behaviour when there is none, so a pack can start small and grow.

A **conformance suite** checks a pack: which parts are present, that they are well-formed,
that masking round-trips on the pack's fixtures, that no allowed inflected form leaks a
masked value, and how the rules score on the pack's smoke set. It tells you what is still
missing; it is also what "done" means (below).

German is the worked example: `src/pii_guard/languages/de/` was written by following this
guide, and every step below points at it.

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
replaces it. A pack that fails to load raises `LanguagePackError`: pii-guard fails closed
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

Put check-digit functions next to the rules (`languages/de/checksums.py`) with tests against
the algorithm's published examples. Use the helpers in `detect/rules/_base.py`
(`NUM_START`/`NUM_END` reject digits inside longer numbers and dates, `context_before` finds a
label). Before adding an `EVERYWHERE` rule, check what it does to the other languages: the
hu/en scorecards must not change (`--language hu,en`). That is why the German Steuer-ID runs
everywhere only next to its label: Hungarian personal ID numbers are 11 digits too.

Every German noun is capitalised, so "five digits before a capitalised word" is not a
postcode ("20000 Teilnehmer"); the German postcode rule only fires where an address line
starts. Hard negatives in the smoke set catch this kind of rule.

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
