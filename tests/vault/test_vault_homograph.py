"""A held homograph of a common word over-masks, and never leaks (LAB-1343).

``Bor`` held as a PERSON also masks ``bort`` ("wine", accusative): the vault cannot tell a
surname from the same common word, and a capitalisation or lexicon gate would leak a
lower-case name in chat text, so the guard stays biased toward masking. All names and
words are fictional (ADR 0005).
"""

from __future__ import annotations

from vault_helpers import span_of

from pii_guard.types import EntityType
from pii_guard.vault import PLACEHOLDER_RE, Vault

PERSON = EntityType.PERSON


def test_held_homograph_masks_the_common_words_inflection(vault: Vault) -> None:
    session = vault.session()
    text = "Bor úr bort ivott."
    masked = session.mask(text, [span_of(text, "Bor", "PERSON")], language="hu")
    assert "bort" not in masked
    assert len(PLACEHOLDER_RE.findall(masked)) == 2
    assert session.unmask(masked) == text


def test_lower_case_names_still_mask(vault: Vault) -> None:
    # The fail-closed side of the trade-off: a name written lower-case is still masked.
    session = vault.session()
    text = "teszt elek jött."
    masked = session.mask(text, [span_of(text, "teszt elek", "PERSON")], language="hu")
    assert "teszt elek" not in masked
    assert session.unmask(masked) == text
