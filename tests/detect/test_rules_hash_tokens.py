"""Digit runs inside hashes and other alphanumeric tokens are not identifiers (LAB-1282).

Coding agents read lockfiles, image digests and git SHAs. One digit run in ten passes a mod-10
check by chance, so before LAB-1282 the repository's own ``uv.lock`` had 14 masked spans
(TAJ and personal-ID numbers inside sha256 hashes). Every value here is fictional: the hex
strings are made up and the identifiers are built from their check-digit functions.
"""

from __future__ import annotations

import pytest

from pii_guard.detect.checksums import hu_tax_id_check_digit, taj_check_digit
from pii_guard.detect.rules import RuleDetector
from pii_guard.types import EntityType

E = EntityType

TAJ = f"12345678{taj_check_digit('12345678')}"  # 123456788
TAX_ID = f"812345678{hu_tax_id_check_digit('812345678')}"
PERSONAL_ID = "51705016523"  # passes the personal-ID check (sex digit, date, check digit)
PHONE = "06301234567"
LANGUAGES = ("hu", "en", "de")


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector(cued_numbers=True)


def _types(detector: RuleDetector, text: str, language: str) -> list[tuple[EntityType, str]]:
    return [(s.entity_type, s.text) for s in detector.detect(text, language)]


# A checksum-valid digit run glued to letters on at least one side.
EMBEDDED = [
    pytest.param(f'hash = "sha256:aa0bf00b2eef142fe5092885d{TAJ}a9d43f576043"', id="lock-mid"),
    pytest.param(f'hash = "sha256:{TAJ}c57936ef93f4aa0bf00b2eef142fe5092"', id="lock-start"),
    pytest.param(f'hash = "sha256:aa0bf00b2eef142fe5092885d4ca3697f{TAJ}"', id="lock-end"),
    pytest.param(f"commit 4ab{TAJ}e21635c8a271fb8d310d6aa0bf00b2eef", id="git-sha"),
    pytest.param(f"image@sha256:cf72b26862df52fbb4ca3697f{PERSONAL_ID}d41", id="personal-id"),
    pytest.param(f'etag: W/"ab{TAX_ID}cdef0123456789ab"', id="tax-id"),
    pytest.param(f'"id": "9759ae8c-174a-4e2c-b63d-{PHONE[:10]}e2"', id="uuid-tail-phone"),
    pytest.param(f"integrity: sha512-Kx{TAJ}AbQz+Yt7w==", id="base64"),
    pytest.param(f"{PHONE}abc", id="phone-then-letters"),
    pytest.param('_INVERT = str.maketrans("0123456789abcdef", "fedcba9876543210")', id="alphabet"),
    pytest.param(f"cache_key = build_{TAJ}", id="identifier"),
]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("text", EMBEDDED)
def test_digits_inside_a_token_are_not_masked(
    detector: RuleDetector, text: str, language: str
) -> None:
    assert _types(detector, text, language) == []


# The same values standing on their own: still personal data.
STANDALONE = [
    pytest.param(f"TAJ: {TAJ[:3]} {TAJ[3:6]} {TAJ[6:]}", E.NATIONAL_ID_HU_TAJ, id="taj-cued"),
    pytest.param(f"Her number is {TAJ}.", E.NATIONAL_ID_HU_TAJ, id="taj-sentence"),
    pytest.param(f'{{"taj": "{TAJ}"}}', E.NATIONAL_ID_HU_TAJ, id="taj-json"),
    pytest.param(f"taj={TAJ}", E.NATIONAL_ID_HU_TAJ, id="taj-equals"),
    pytest.param(f"{TAJ}\nnext line", E.NATIONAL_ID_HU_TAJ, id="taj-line-start"),
    pytest.param(f"({TAJ})", E.NATIONAL_ID_HU_TAJ, id="taj-parentheses"),
    pytest.param(f"a {TAJ}-as számot", E.NATIONAL_ID_HU_TAJ, id="taj-suffix"),
    pytest.param(f"adóazonosító jel: {TAX_ID}", E.NATIONAL_ID_HU_TAX, id="tax-id"),
    pytest.param(f"személyi azonosító: {PERSONAL_ID}", E.ID_DOCUMENT, id="personal-id"),
    pytest.param(f"Hívj: {PHONE}, köszi", E.PHONE, id="phone"),
]


@pytest.mark.parametrize("text,entity_type", STANDALONE)
def test_standalone_values_are_still_masked(
    detector: RuleDetector, text: str, entity_type: EntityType
) -> None:
    assert entity_type in {t for t, _ in _types(detector, text, "hu")}
