# 0010. Language packs as one plugin unit

- **Status:** accepted
- **Date:** 2026-10-27
- **Amends:** [0008](0008-language-packs.md)

## Context

ADR 0008 made a language pack a convention: each per-language piece stayed in the component
that used it, registered in that component's registry under the language code. By the third
language that meant five registries (`detect/rules` `_PACKS`, `detect/llm.py` `LANGUAGES` and
`detect/prompts/languages/`, `eval/forms.py` `register_language_forms`,
`vault/inflection.py` `register_inflection`, and `pii_guard.lang`'s lexicon specs) and no test
that a pack was complete. ADR 0008 deferred unification "until a third language lands or packs
need to be installed from separate distributions". Both are now true: German is the third
language, and the project is open source, so contributors should be able to add a language
without editing five core modules or forking.

## Decision

**One unit.** A language pack is one `pii_guard.languages.LanguagePack` (a frozen dataclass)
holding every part: code and name, `everywhere`/`rules` rule tuples, the inflection matcher,
the alignment profile (`allow_suffix`, `word_boundary`), prompt notes, country-specific entity
types, eval surface forms, lexicon spec and smoke fixtures. Only code, name, prompt and smoke
fixtures are required; every other part keeps the fallback ADR 0008 defined. The built-in
packs live in `src/pii_guard/languages/<code>/`.

**The plugin boundary is the registry, not the components.** The components keep their logic
and ask `pii_guard.languages.get_pack(language)` for the primary language's pack. The pack
provides data and small objects (rule functions, a matcher, a resource); it never subclasses
or patches a component. That keeps the contract small enough to test, and lets a component
change its internals without breaking packs.

**Discovery**, in precedence order: `register_pack()` at runtime; the `pii_guard.languages`
entry-point group (a separate distribution adds or replaces a language); subpackages of
`pii_guard.languages`. An entry point names a `LanguagePack` or a function returning one.
Packs load lazily, on the first lookup: importing a component never imports every language,
and a pack module can import the component helpers it uses without an import cycle (the
inflection protocol moved to the dependency-free `pii_guard.languages.inflection` for this).

**Fail closed.** A pack that fails to import, returns something else, or declares a different
code raises `LanguagePackError` on lookup (ADR 0006). Silently dropping it would lower recall
for that language with nothing in the logs.

**Overrides keep working.** `register_rule_pack`, `register_inflection` and
`register_language_forms` still exist and take precedence over the pack's part, so existing
callers and tests are unaffected. The pre-pack import paths (`pii_guard.detect.rules.hu`/`.en`
as aliases of the packs' rule modules, `HungarianSuffixMatcher` and `EnglishPossessiveMatcher`
from `pii_guard.vault.inflection`, `pii_guard.eval.HungarianForms` and
`pii_guard.detect.llm.LANGUAGES`) were kept for one release and removed in LAB-1145; import
from `pii_guard.languages.<code>.rules`, `pii_guard.languages.<code>.inflection`, and use
`language_forms()` / `language_profile()` instead.

**Conformance is a library**, `pii_guard.languages.conformance`, used by the pytest suite in
`tests/languages/` (parametrized over every registered pack), by `pii-guard lang check`, and by
a third-party pack's own test hook. `pii-guard lang new <code>` generates a skeleton that passes
the structural checks as generated.

## Consequences

- Adding a language is one directory (or one distribution) plus fixtures; the conformance suite
  lists what is missing. [docs/languages.md](../languages.md) is the guide.
- Behavior is unchanged for `hu` and `en`: every scorecard on the committed fixtures is
  identical before and after the move. The German pack's `EVERYWHERE` rules were chosen so that
  they don't change them either (the bare Steuer-ID runs only for German text).
- Lookup is by primary language everywhere, including the eval surface forms, which used to
  match the code case-sensitively.
- A broken third-party pack blocks requests instead of degrading them; that is deliberate, and
  `pii-guard lang list` shows what is installed.
- One more indirection on hot paths (`inflection_for`, the rule list): a dictionary lookup after
  the first load.
