"""Surface forms of a labelled value, per language: what counts as the value "appearing".

Used twice:

- the **leak rate** searches the masked text for every labelled value in any surface form;
- a **corpus generator** locates inserted values (including inflected forms) to record spans.

Matching is case-insensitive and whitespace-tolerant everywhere. Structured identifiers
(phone numbers, national IDs, bank accounts, plates …) match on their letters and digits
with any separators in between (``1234 5678`` == ``1234-5678``), phone numbers also by their
national number (``+36 30 …`` == ``06 30 …``) and Hungarian IBANs also by the giro number
inside them.

Words-like values (names, addresses, organisations, e-mails, dates) go through a
per-language :class:`LanguageForms` hook. The default is exact matching plus whatever
suffixes the vault's inflection matcher allows for that language
(:func:`pii_guard.vault.inflection_for`, exact for languages without one). Hungarian adds
stem-changing forms (``Anna`` -> ``Annának``, ``Kovács`` -> ``Kováccsal``). Register another
language with :func:`register_language_forms`.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pii_guard.languages import SurfaceForms, get_pack, on_change, primary_language
from pii_guard.types import EntityType
from pii_guard.vault.inflection import inflection_for

__all__ = [
    "CODE_ENTITY_TYPES",
    "HungarianForms",
    "LanguageForms",
    "PackForms",
    "find_surface_forms",
    "language_forms",
    "register_language_forms",
    "surface_pattern",
]

#: Types matched on their letters and digits, separators ignored.
CODE_ENTITY_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.PHONE,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
        EntityType.ID_DOCUMENT,
        EntityType.BANK_ACCOUNT,
        EntityType.COMPANY_ID_HU,
        EntityType.PARCEL_NUMBER_HU,
        EntityType.VEHICLE_PLATE,
    }
)

_SEP = r"[\s\-./()]*"


class LanguageForms:
    """Default surface forms: the value itself plus the vault's suffixes for ``language``.

    ``stopwords`` are generic tokens (street-type words, month names) that don't identify
    anyone on their own; the partial-leak check ignores them.
    """

    def __init__(self, language: str, stopwords: frozenset[str] = frozenset()) -> None:
        self.language = language
        self.stopwords = frozenset(w.casefold() for w in stopwords)

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        """Regex fragment for a detachable suffix (kept outside the matched span)."""
        return inflection_for(self.language).suffix_pattern(value, entity_type)

    def stem_variants(self, value: str, entity_type: EntityType) -> list[str]:
        """Regex alternatives matching a whole inflected form whose stem changed.

        The matched span covers the whole inflected word. Default: none.
        """
        return []


def _words(value: str) -> str:
    return r"\s+".join(re.escape(token) for token in value.split())


class PackForms(LanguageForms):
    """Surface forms from a language pack's :class:`~pii_guard.languages.SurfaceForms`."""

    def __init__(self, language: str, forms: SurfaceForms) -> None:
        super().__init__(language, forms.stopwords)
        self._forms = forms

    def stem_variants(self, value: str, entity_type: EntityType) -> list[str]:
        return self._forms.stem_variants(value, entity_type)


class HungarianForms(PackForms):
    """Hungarian surface forms (kept for compatibility; they live in the ``hu`` pack)."""

    def __init__(self) -> None:
        from pii_guard.languages.hu.forms import HungarianSurfaceForms

        super().__init__("hu", HungarianSurfaceForms())


#: Hooks registered with :func:`register_language_forms`; they take precedence over packs.
_FORMS: dict[str, LanguageForms] = {}


def _clear() -> None:
    surface_pattern.cache_clear()
    _pack_forms.cache_clear()


def register_language_forms(forms: LanguageForms) -> None:
    """Use ``forms`` for ``forms.language``, replacing any existing hook."""
    _FORMS[forms.language] = forms
    _clear()


@lru_cache(maxsize=64)
def _pack_forms(code: str) -> LanguageForms | None:
    pack = get_pack(code)
    if pack is None:
        return None
    if pack.surface_forms is None:
        return LanguageForms(pack.code)
    return PackForms(pack.code, pack.surface_forms)


def language_forms(language: str) -> LanguageForms:
    """The hook for ``language`` (``"en-GB"`` falls back to ``"en"``), or the default.

    A hook registered with :func:`register_language_forms` first, then the language pack's
    surface forms (:mod:`pii_guard.languages`), then exact matching plus the vault's suffixes.
    """
    forms = _FORMS.get(language) or _FORMS.get(language.split("-", 1)[0])
    if forms is None:
        forms = _pack_forms(primary_language(language))
    return forms if forms is not None else LanguageForms(language)


def _code_body(chars: str) -> str:
    return _SEP.join(re.escape(ch) for ch in chars)


def _code_pattern(chars: str) -> str:
    left = r"(?<!\d)" if chars[0].isdigit() else r"(?<![^\W_])"
    right = r"(?!\d)" if chars[-1].isdigit() else r"(?![^\W_])"
    return left + _code_body(chars) + right


def _code_alternatives(value: str, entity_type: EntityType) -> list[str]:
    chars = "".join(re.findall(r"[^\W_]", value))
    if not chars:
        return []
    alternatives = [_code_pattern(chars)]
    digits = "".join(ch for ch in value if ch.isdigit())
    if entity_type is EntityType.PHONE:
        national = None
        if value.lstrip().startswith("+"):
            # "+36 30 …": drop the country code (Hungarian, or 1-3 digits otherwise).
            national = digits[2:] if digits.startswith("36") else None
        elif digits.startswith("0036"):
            national = digits[4:]
        elif digits.startswith("06"):
            national = digits[2:]
        if national and len(national) >= 8:
            alternatives.append(_code_pattern(national))
            alternatives.append(r"(?<!\d)(?:\+|00)?36" + _SEP + _code_body(national) + r"(?!\d)")
            alternatives.append(r"(?<!\d)06" + _SEP + _code_body(national) + r"(?!\d)")
    if (
        entity_type is EntityType.BANK_ACCOUNT
        and chars.upper().startswith("HU")
        and len(chars) == 28
    ):
        alternatives.append(_code_pattern(chars[4:]))  # the giro number inside a HU IBAN
    return alternatives


def _word_alternatives(value: str, entity_type: EntityType, forms: LanguageForms) -> list[str]:
    value = value.strip()
    body = _words(value)
    # An underscore counts as a boundary, not a word character: a value glued to one
    # (``[[PERSON_Teszt Elek]]``, ``user_Teszt Elek``) still survived there (LAB-1147).
    left = r"(?<![^\W_])" if _is_word(value[0]) else ""
    if _is_word(value[-1]):
        suffix = forms.suffix_pattern(value, entity_type)
        right = f"(?=(?:{suffix})?(?![^\\W_]))" if suffix else r"(?![^\W_])"
    else:
        right = ""
    alternatives = [left + body + right]
    alternatives.extend(left + v + r"(?![^\W_])" for v in forms.stem_variants(value, entity_type))
    return alternatives


def _is_word(char: str) -> bool:
    return char.isalnum()


@lru_cache(maxsize=4096)
def surface_pattern(value: str, entity_type: EntityType, language: str) -> re.Pattern[str]:
    """Compiled, case-insensitive pattern matching any surface form of ``value``.

    A match's span covers the value as written, without a detachable suffix
    (``Teszt Elek|nek``), or the whole word for a stem-changing form (``Annának``).
    """
    if not value.strip():
        raise ValueError("value must not be blank")
    entity_type = EntityType(entity_type)
    if entity_type in CODE_ENTITY_TYPES:
        alternatives = _code_alternatives(value, entity_type)
    else:
        alternatives = []
    alternatives += _word_alternatives(value, entity_type, language_forms(language))
    return re.compile("|".join(f"(?:{a})" for a in alternatives), re.IGNORECASE)


def find_surface_forms(
    text: str, value: str, entity_type: EntityType | str, language: str
) -> list[tuple[int, int]]:
    """Non-overlapping ``(start, end)`` offsets of every surface form of ``value`` in ``text``."""
    pattern = surface_pattern(value, EntityType(entity_type), language)
    return [m.span() for m in pattern.finditer(text) if m.end() > m.start()]


on_change(_clear)
