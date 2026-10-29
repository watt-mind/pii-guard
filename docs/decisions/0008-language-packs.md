# 0008. Language packs

- **Status:** accepted; amended by [0010](0010-language-pack-plugins.md) (one `LanguagePack`
  object and a plugin registry replace the per-component registries described below)
- **Date:** 2026-10-26

## Context

pii-guard started Hungarian-first and is meant to cover English next and other EU languages
after that. Everything language-specific already exists, but it is spread over four modules
that were each made per-language on their own:

| Piece | Where | Keyed by |
|---|---|---|
| Rules (national identifiers, phone/postcode/plate formats) | `detect/rules.py` (one Hungarian-first module) | nothing: all rules ran for every text |
| Vault inflection (which suffixes may follow a value) | `vault/inflection.py`, `register_inflection` | language code |
| LLM prompt notes, requested types, alignment | `detect/llm.py` `LANGUAGES`, `detect/prompts/languages/<code>.md` | language code |
| Eval surface forms (leak rate, corpus spans) | `eval/forms.py` `LanguageForms`, `register_language_forms` | language code |

Adding a language meant knowing all four, and the rules had no notion of language at all, so a
format that is only unambiguous in one language's texts (a 4-digit Hungarian postcode before a
capitalized word) also ran on English text ("In 2019 Robin moved").

## Decision

A **language pack** is the set of contributions one language makes, keyed by its ISO 639-1
code. It is a convention and a checklist, not a single runtime object: each piece stays in the
component that uses it, registered in that component's registry under the same code.

| A pack contributes | Module | Registered with | Without it |
|---|---|---|---|
| Rules | `detect/rules/<code>.py` exporting `EVERYWHERE` and `RULES` | `RulePack` in `detect/rules/__init__.py` (built in) or `register_rule_pack()` | language-independent rules + other packs' `EVERYWHERE` rules |
| Vault inflection matcher | `vault/inflection.py` (`InflectionMatcher`) | `register_inflection(code, matcher)` | `ExactMatcher` (word boundaries only) |
| LLM prompt notes and profile | `detect/prompts/languages/<code>.md` + `LanguageProfile` in `detect/llm.py` | `LANGUAGES[code]` | `default.md`, generic entity types, suffix-tolerant alignment (except a list of languages that rarely inflect names) |
| Eval surface forms | `eval/forms.py` (`LanguageForms`) | `register_language_forms(forms)` | the vault matcher's suffixes + exact matching |
| Corpus templates | `eval/` generator (later) | per language | no synthetic corpus: the language is not measured |
| Policy defaults | `docs/entities.md` per-language table | — | the language-independent defaults |

Rules for a language come in two scopes:

- **`EVERYWHERE`**: identifiers with a checksum or a distinctive, validated format (Hungarian
  tax ID, TAJ, giro, company numbers, `+36` phone numbers; US SSN `123-45-6789`; UK NINO).
  They run for every text: a Hungarian tax ID in an English email is still personal data.
- **`RULES`**: formats that are only unambiguous in that language's texts (postcodes, vehicle
  plates, national phone formats without a country code, labeled ID numbers). They run only
  when the request's `language` matches the pack.

Language-independent rules (IBAN, email, `+<country>` phone numbers, payment cards) live in
`detect/rules/common.py` and always run.

**Lookup** is by primary language everywhere: `en-GB`, `EN_us` and `en` all select the `en`
pack (rules, vault matcher, LLM profile and eval forms already did this; the vault now does
too).

**Unknown languages** (no pack) are handled, not rejected: language-independent rules, every
pack's `EVERYWHERE` rules, the multilingual NER/LLM passes with the default prompt, and exact
matching in the vault. That is a recall floor, not a supported language; a language counts as
supported only once it has a fixture file and a reported scorecard (see
[evaluation.md](../evaluation.md)).

**No unification now.** The pieces are not merged into one `LanguagePack` object or a
`pii_guard/languages/` package. The eval surface forms already delegate their detachable
suffixes to the vault's matcher (`LanguageForms.suffix_pattern` → `inflection_for`), so the
inflection rules are not duplicated; what remains duplicated is the Hungarian stem-change
logic (`Anna` → `Annának`, digraph doubling), which lives only in `eval/forms.py`. Moving it
into the vault matcher (an optional `stem_variants` method) is the next step, because it would
also let the vault mask stem-changed forms it misses today; it is tracked as a follow-up rather
than done here. *(Update, LAB-1115: the vault matcher now has optional `variant_stems`,
`splits` and `restore` methods, so the vault and `LlmDetector.align` mask stem-changed forms
under the lemma's placeholder and unmask re-inflects them. `eval/forms.py` keeps its own copy of
the stem-change rules on purpose, so the leak rate is not measured with the code it checks.)*
We revisit a single pack object when a third language lands or when packs need to be
installed from separate distributions (entry points).

## Consequences

- Adding a language is a known checklist: `rules/<code>.py`, an inflection matcher if the
  language inflects names, `prompts/languages/<code>.md` + a profile, `LanguageForms` if it has
  stem changes or generic stopwords, a `<code>-*.jsonl` fixture set, and a row block in
  `entities.md`. Each step is optional; missing steps fall back as in the table above.
- Hungarian postcode and plate rules no longer run on non-Hungarian text. That removes false
  positives on English text and loses Hungarian postcodes inside an English document; the LLM
  and NER passes still cover addresses there.
- `pii_guard.detect.rules:RuleDetector` and the registry name `rules` are unchanged; the module
  is now a package.
- Four registries instead of one: a pack can be half-registered (rules but no vault matcher).
  The fallbacks keep that safe (fail towards more masking or exact matching), and the
  per-language scorecard shows what is missing.
