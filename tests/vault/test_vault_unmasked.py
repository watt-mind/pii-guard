"""``VaultSession.unmasked``: the values a session holds that are still written out (LAB-1500).

The gateway's outbound re-check runs this over every text of the masked request. It uses the
sweep's own patterns, so it finds a value however the sweep would (casing, Unicode form,
inflection), and the sweep's own guards, so it never counts an occurrence the sweep is meant
to leave alone. All values are fictional (ADR 0005).
"""

from __future__ import annotations

from dataclasses import replace

from vault_helpers import span_of

from pii_guard.types import EntityType
from pii_guard.vault import Vault
from pii_guard.vault.known import KnownValue

NAME = "Teszt Elek"
TEXT = f"Szia, {NAME} vagyok, e-mail: teszt.elek@example.com."


def _session(vault: Vault):
    session = vault.session()
    session.mask(
        TEXT,
        [span_of(TEXT, NAME, "PERSON"), span_of(TEXT, "teszt.elek@example.com", "EMAIL")],
    )
    return session


def test_masked_text_has_no_unmasked_value(vault: Vault) -> None:
    session = _session(vault)
    masked = session.mask(TEXT, [span_of(TEXT, NAME, "PERSON")])
    assert session.unmasked([masked], "hu") == []


def test_a_value_left_in_any_form_is_found(vault: Vault) -> None:
    session = _session(vault)
    texts = [
        "nothing here",
        f"Írj {NAME.upper()}-nek!",  # another casing, before a suffix
        "Teszt Eleknek küldd",  # an inflected form
        "teszt.elek@EXAMPLE.com",
    ]
    found = session.unmasked(texts, "hu")
    assert sorted((u.index, u.entity_type.value) for u in found) == [
        (1, "PERSON"),
        (2, "PERSON"),
        (3, "EMAIL"),
    ]
    first = next(u for u in found if u.index == 1)
    assert texts[1][first.start : first.end] == NAME.upper()
    # The occurrence carries counts and flags only, never the value.
    assert NAME not in repr(found) and NAME.upper() not in repr(found)


def test_placeholders_never_count(vault: Vault) -> None:
    session = vault.session()
    text = "A PERSON nevű mező"
    session.mask(text, [span_of(text, "PERSON", "PERSON")])  # a value spelled like a label
    masked = session.mask(f"Ügyfél: {NAME}", [span_of(f"Ügyfél: {NAME}", NAME, "PERSON")])
    assert "[[PERSON_" in masked
    assert session.unmasked([masked], "hu") == []


def test_overlapping_values_count_once(vault: Vault) -> None:
    session = vault.session()
    a, b = "Teszt Elek írt.", "Elek írt."
    session.mask(a, [span_of(a, NAME, "PERSON")])
    session.mask(b, [span_of(b, "Elek", "PERSON")])
    (found,) = session.unmasked([f"Üdv: {NAME}"], "hu")
    assert (found.end - found.start) == len(NAME)


def test_ner_only_value_follows_the_sweep_guards(vault: Vault) -> None:
    session = vault.session()
    first = "Ask Claude to review the patch."
    session.mask(first, [replace(span_of(first, "Claude", "PERSON"), detector="ner")])
    # The sweep leaves a product name and a path alone (LAB-1470); so does the re-check.
    assert session.unmasked(["Claude Code wrote /tmp/claude-501/out.log"], "en") == []
    (found,) = session.unmasked(["then tell Claude thanks"], "en")
    assert found.model_only


def test_flags_for_the_short_value_policy(vault: Vault) -> None:
    session = vault.session()
    text = "Al és 12345 és 1234567"
    session.mask(
        text,
        [
            replace(span_of(text, "Al", "PERSON"), detector="ner"),
            span_of(text, "12345", "BANK_ACCOUNT"),
            span_of(text, "1234567", "BANK_ACCOUNT"),
        ],
    )
    found = {u.chars: u for u in session.unmasked([text], "hu")}
    assert set(found) == {2, 5, 7}
    assert found[2].model_only and not found[2].digits_only
    assert found[5].digits_only and not found[5].model_only
    assert not found[7].known


def test_known_values_count_before_any_detection(vault: Vault) -> None:
    session = vault.session()
    session.known_values.add([KnownValue("Ann Minta", EntityType.PERSON)])
    (found,) = session.unmasked(["Hívd fel Ann Mintát!"], "hu")
    assert found.known and found.entity_type is EntityType.PERSON
    assert session.unmasked(["Hívd fel [[PERSON_0a1b2c]]!"], "hu") == []


def test_unmasked_records_nothing(vault: Vault) -> None:
    session = _session(vault)
    before = (session.generation, session.entry_count, session.entities())
    session.unmasked([TEXT, "új név: Minta Kende"], "hu")
    assert (session.generation, session.entry_count, session.entities()) == before
