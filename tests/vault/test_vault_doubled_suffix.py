"""A doubled case suffix does not round-trip, by design (LAB-1142).

``Teszt Hajnánaknak`` is a case ending stacked on a case ending, which is not Hungarian
(the real stacks, ``-é``/``-ék``/``-éi`` plus a case ending, are LAB-1337 and round-trip).
The vault keys both occurrences on the labelled value's lemma and restores one suffix, so
the extra ``nak`` is dropped on unmask. No value leaks; the text just does not round-trip.
All names are fictional (ADR 0005).
"""

from __future__ import annotations

from vault_helpers import span_of

from pii_guard.types import EntityType
from pii_guard.vault import PLACEHOLDER_RE, Vault

PERSON = EntityType.PERSON


def test_doubled_suffix_is_masked_but_not_round_tripped(vault: Vault) -> None:
    session = vault.session()
    text = "Teszt Hajnának: Teszt Hajnánaknak ."
    span = span_of(text, "Teszt Hajnának", "PERSON")
    masked = session.mask(text, [span], language="hu")
    assert PLACEHOLDER_RE.search(masked) is not None
    assert "Hajna" not in masked
    # Both occurrences share the labelled value's placeholder; the second keeps its own
    # trailing run outside it.
    assert masked.count("nak") == 2
    assert session.unmask(masked) == "Teszt Hajnának: Teszt Hajnának ."
