"""Language packs: everything one language contributes, as one unit (ADR 0010).

A :class:`LanguagePack` bundles the per-language parts that used to live in five registries:
rules, the vault's inflection matcher, the LLM prompt notes and alignment profile, the eval
surface forms, the lexicons and the document field captions. The components still own their
logic (the rule detector runs rules, the vault masks, the scorer scores); they ask this
registry for the pack of the text's language and fall back when there is none (see the table
in ``docs/languages.md``).

Where packs come from, in order of precedence:

1. :func:`register_pack` at runtime (tests, applications embedding pii-guard);
2. the ``pii_guard.languages`` entry-point group, so a separate distribution can ship a
   language without forking::

       [project.entry-points."pii_guard.languages"]
       de = "my_package.de:pack"

3. the packs built into this package (``pii_guard/languages/<code>/``).

An entry point (or a built-in package's ``pack`` attribute) names either a
:class:`LanguagePack` or a zero-argument function returning one. Packs are loaded lazily, on
the first lookup, so importing a component never imports every language, and a pack module
may import the components it extends without an import cycle.

Lookup is by primary language: ``en-GB``, ``EN_us`` and ``en`` all select the ``en`` pack.
A pack that fails to load raises :class:`LanguagePackError` (fail closed, ADR 0006): a broken
pack must not silently turn into "no pack", which would lower recall without anyone noticing.
"""

from __future__ import annotations

import logging
import pkgutil
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib import import_module, metadata
from importlib.resources.abc import Traversable
from typing import TYPE_CHECKING, Any

from pii_guard.types import EntityType, PiiGuardError

if TYPE_CHECKING:
    import random

    from pii_guard.detect.rules import Rule
    from pii_guard.languages.inflection import InflectionMatcher

__all__ = [
    "ENTRY_POINT_GROUP",
    "LanguagePack",
    "LanguagePackError",
    "LexiconSpec",
    "SurfaceForms",
    "available_languages",
    "clear_registry",
    "get_pack",
    "on_change",
    "packs",
    "primary_language",
    "register_pack",
    "unregister_pack",
]

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "pii_guard.languages"
CODE_RE = re.compile(r"^[a-z]{2,3}$")


class LanguagePackError(PiiGuardError):
    """A language pack could not be loaded or is not a :class:`LanguagePack`."""

    code = "language_pack_error"


def primary_language(language: str) -> str:
    """``"en-GB"`` / ``"EN_us"`` -> ``"en"``; blank -> ``"und"``."""
    return (language or "").strip().lower().replace("_", "-").split("-")[0] or "und"


# --- The pack -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SurfaceForms:
    """How the evaluation recognises a labelled value in this language (``eval/forms.py``).

    - ``stopwords``: generic tokens (street-type words, month names, company forms) that do
      not identify anyone on their own; the partial-leak check ignores them.
    - :meth:`stem_variants`: regex alternatives matching a whole inflected form whose stem
      changed (Hungarian ``Anna`` -> ``Annának``). Detachable suffixes that leave the stem
      intact come from the pack's inflection matcher instead.

    The eval keeps its own copy of stem-change rules on purpose, separate from the vault's
    matcher, so the leak rate is not measured with the code it checks (ADR 0008).
    """

    stopwords: frozenset[str] = frozenset()

    def stem_variants(self, value: str, entity_type: EntityType) -> list[str]:
        return []


@dataclass(frozen=True, slots=True)
class LexiconSpec:
    """The lexicons a pack ships (``pii_guard.lang``, ADR 0009).

    - ``directory``: where ``<kind>.tsv`` files live (a package resource directory).
    - ``kinds``: the kinds it provides (:data:`pii_guard.lang.LEXICON_KINDS` plus extras).
    - ``merges``: kind -> files merged into it (later files add weight to earlier entries).
    - ``structural``: settlement (casefolded) -> postcode prefix, for settlements whose
      postcodes follow a pattern rather than a list (Budapest districts).
    """

    directory: Traversable
    kinds: tuple[str, ...]
    merges: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    structural: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LanguagePack:
    """Everything one language contributes. Only ``code``, ``name``, ``prompt`` and
    ``smoke_fixtures`` are required; every other part has a documented fallback.

    Identity
        ``code``: ISO 639-1 (or 639-3 when there is no 639-1 code), lowercase.
        ``name``: the language's English name, used in the LLM prompt.

    Rules (``detect/rules``)
        ``everywhere``: validated identifiers of the country (checksum or distinctive format),
        run for **every** language: a Hungarian tax ID in an English e-mail is still personal
        data. ``rules``: formats that are only unambiguous in this language's texts
        (postcodes, plates, national phone formats), run only when the text is in ``code``.

    Script / word-boundary profile (LLM alignment)
        ``allow_suffix``: a value may run on into a longer word (agglutinative languages,
        German genitive ``Annas``). ``word_boundary``: matches start at a word boundary (off
        for scripts written without spaces).

    Inflection (vault)
        ``inflection``: an :class:`~pii_guard.vault.inflection.InflectionMatcher`; ``None``
        means exact matching between word boundaries.

    LLM prompt
        ``prompt``: a Markdown resource with language-specific instructions, substituted into
        ``detect/prompts/system.md``. ``country_entity_types``: country-specific types the
        LLM is asked for in this language, on top of the generic ones.

    Evaluation
        ``surface_forms``: :class:`SurfaceForms` (stopwords, stem changes).
        ``smoke_fixtures``: hand-written fixture files (``<code>-*.jsonl``), relative to the
        repository's ``eval/fixtures/`` or absolute; the conformance suite runs on them.

    Lexicons
        ``lexicons``: a :class:`LexiconSpec`, or ``None`` for a language without lists.

    Document field captions (``visual/captions``)
        ``captions``: a ``captions.tsv`` resource (``caption<TAB>ENTITY_TYPE``, ``-`` for a
        caption whose value is not personal data), so the value printed next to ``Név`` or
        ``Date of birth`` on an ID card is masked; ``None``: this language's captions are not
        recognised in images.

    Cued numbers (``languages/cues.py``)
        ``cues``: a ``cues.tsv`` resource (``cue<TAB>ENTITY_TYPE``, ``-`` for a cue that names
        something else, such as an order number), so a number right after ``TAJ`` or
        ``passport`` is masked even when its checksum fails; ``None``: no cue words.

    Brand names (``detect/ner_orgs.py``)
        ``brands``: a ``brands.tsv`` resource (one company or product name per line), so an
        NER ``PERSON`` span that is only such a name (``OTP Bank``, ``Deutsche Bahn``) becomes
        ``ORGANIZATION``, which policy keeps; ``None``: only the shared list
        (``languages/brands.tsv``) and the other packs' names.

    Reference words (``languages/references.py``)
        ``references``: a ``references.tsv`` resource (one business-reference word per line:
        order, invoice, tracking ...), so a validated number right after such a label is a
        business number in the rules check and an NER number right after one is dropped;
        ``None``: the built-in fallback lists (``_REFERENCE_WORD``/``_NEGATIVE``) apply.
    Synthetic corpus (``eval/generate.py``, ``eval/identities.py``)
        ``identity_generator``: a function ``(random.Random) -> IdentityGenerator`` making
        this language's fictional people, companies, properties and institutions (ADR 0005).
        ``corpus_templates``: a TOML resource with the document templates the corpus model
        writes from (schema of ``pii_guard/eval/templates/hu.toml``). A corpus needs both;
        ``None``: no synthetic corpus, the language is measured on its smoke set only.
    """

    code: str
    name: str
    prompt: Traversable | None = None
    smoke_fixtures: tuple[str, ...] = ()
    everywhere: tuple[Rule, ...] = ()
    rules: tuple[Rule, ...] = ()
    inflection: InflectionMatcher | None = None
    surface_forms: SurfaceForms | None = None
    country_entity_types: tuple[EntityType, ...] = ()
    allow_suffix: bool = True
    word_boundary: bool = True
    lexicons: LexiconSpec | None = None
    captions: Traversable | None = None
    cues: Traversable | None = None
    brands: Traversable | None = None
    references: Traversable | None = None
    identity_generator: Callable[[random.Random], Any] | None = None
    corpus_templates: Traversable | None = None

    def __repr__(self) -> str:
        return (
            f"LanguagePack(code={self.code!r}, everywhere={len(self.everywhere)}, "
            f"rules={len(self.rules)}, inflection={type(self.inflection).__name__})"
        )


# --- The registry ---------------------------------------------------------------------------

#: What an entry point or a built-in package's ``pack`` attribute may be.
PackSource = LanguagePack | Callable[[], LanguagePack]

_lock = threading.RLock()
_registered: dict[str, LanguagePack] = {}
_discovered: dict[str, LanguagePack] | None = None
_listeners: list[Callable[[], None]] = []


def _materialise(source: Any, where: str) -> LanguagePack:
    try:
        pack = source() if callable(source) and not isinstance(source, LanguagePack) else source
    except Exception as exc:
        raise LanguagePackError(
            f"language pack {where} failed to load: {type(exc).__name__}"
        ) from exc
    if not isinstance(pack, LanguagePack):
        raise LanguagePackError(
            f"language pack {where} is a {type(pack).__name__}, not a LanguagePack"
        )
    return pack


def _builtin_sources() -> dict[str, Callable[[], Any]]:
    """``code -> loader`` for every subpackage of :mod:`pii_guard.languages`."""
    sources: dict[str, Callable[[], Any]] = {}
    for info in pkgutil.iter_modules(__path__):
        if not info.ispkg or info.name.startswith("_") or not CODE_RE.match(info.name):
            continue

        def load(name: str = info.name) -> Any:
            return import_module(f"{__name__}.{name}").pack

        sources[info.name] = load
    return sources


def _entry_point_sources() -> dict[str, metadata.EntryPoint]:
    eps = sorted(metadata.entry_points(group=ENTRY_POINT_GROUP), key=lambda ep: ep.value)
    found: dict[str, metadata.EntryPoint] = {}
    for ep in eps:
        code = primary_language(ep.name)
        if code in found and found[code].value != ep.value:
            logger.warning("language pack %r: entry point %s overrides %s", code, ep.value,
                           found[code].value)  # fmt: skip
        found[code] = ep
    return found


def _discover() -> dict[str, LanguagePack]:
    global _discovered
    with _lock:
        if _discovered is None:
            loaders: dict[str, tuple[str, Callable[[], Any]]] = {
                code: (f"{code!r} (built in)", load) for code, load in _builtin_sources().items()
            }
            for code, ep in _entry_point_sources().items():
                if code in loaders and ep.value.startswith(f"{__name__}.{code}:"):
                    continue  # this package's own entry point for a built-in pack
                loaders[code] = (f"{code!r} (entry point {ep.value})", ep.load)
            found: dict[str, LanguagePack] = {}
            for code in sorted(loaders):
                where, load = loaders[code]
                try:
                    source = load()
                except Exception as exc:
                    raise LanguagePackError(
                        f"language pack {where} failed to import: {type(exc).__name__}"
                    ) from exc
                pack = _materialise(source, where)
                if primary_language(pack.code) != code:
                    raise LanguagePackError(
                        f"language pack {where} declares code {pack.code!r}, expected {code!r}"
                    )
                found[code] = pack
            _discovered = found
        return _discovered


def _notify() -> None:
    for listener in list(_listeners):
        listener()


def on_change(listener: Callable[[], None]) -> None:
    """Call ``listener`` whenever the set of packs changes (components clear their caches)."""
    _listeners.append(listener)


def register_pack(source: PackSource) -> LanguagePack:
    """Use ``source`` (a pack or a function returning one) for its language.

    Replaces a built-in or entry-point pack of the same code; takes effect for detectors
    created afterwards.
    """
    pack = _materialise(source, "passed to register_pack")
    code = primary_language(pack.code)
    with _lock:
        _registered[code] = pack
    _notify()
    return pack


def unregister_pack(code: str) -> None:
    """Remove a pack added with :func:`register_pack` (built-in packs come back)."""
    with _lock:
        _registered.pop(primary_language(code), None)
    _notify()


def clear_registry() -> None:
    """Forget registered packs and re-run discovery on the next lookup."""
    global _discovered
    with _lock:
        _registered.clear()
        _discovered = None
    _notify()


def packs() -> dict[str, LanguagePack]:
    """Every available pack by code, sorted by code (a copy)."""
    with _lock:
        merged = {**_discover(), **_registered}
    return dict(sorted(merged.items()))


def available_languages() -> tuple[str, ...]:
    """The codes of every available pack."""
    return tuple(packs())


def get_pack(language: str) -> LanguagePack | None:
    """The pack for ``language``'s primary language, or ``None`` without one."""
    code = primary_language(language)
    with _lock:
        pack = _registered.get(code)
        return pack if pack is not None else _discover().get(code)
