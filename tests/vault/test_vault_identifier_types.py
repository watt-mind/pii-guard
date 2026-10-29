"""One identifier value is one placeholder per session, whichever type a detector reads it as.

LAB-1475: in a real OpenCode and Codex run, the NER read a fictional Steuer-ID as an
``ID_DOCUMENT`` in ``customers.md`` and as a ``NATIONAL_ID_HU_TAX`` in the ``tax_id`` field of
the JSON the agent wrote. The model saw two placeholders for one value, "fixed" the copy, and
the next ``cat`` showed the other placeholder again: 67 requests in one turn. All values are
fictional (ADR 0005).
"""

from __future__ import annotations

from vault_helpers import span_of

from pii_guard.vault import Vault

STEUER = "41756368295"
SOURCE = f"2. Erika Mustermann, Steuer-ID {STEUER}."
COPY = f'{{"name": "Erika Mustermann", "tax_id": "{STEUER}"}}'


def test_a_value_keeps_its_placeholder_under_another_identifier_type(vault: Vault) -> None:
    session = vault.session()
    first = session.mask(SOURCE, [span_of(SOURCE, STEUER, "ID_DOCUMENT")])
    second = session.mask(COPY, [span_of(COPY, STEUER, "NATIONAL_ID_HU_TAX")])
    placeholder = first.split("Steuer-ID ")[1].rstrip(".")
    assert placeholder.startswith("[[ID_DOCUMENT_")
    assert placeholder in second
    assert "NATIONAL_ID_HU_TAX" not in second
    assert session.unmask(second) == COPY


def test_both_types_in_one_request_share_the_placeholder(vault: Vault) -> None:
    session = vault.session()
    text = f"{SOURCE}\n{COPY}"
    spans = [
        span_of(text, STEUER, "ID_DOCUMENT"),
        span_of(text, STEUER, "NATIONAL_ID_HU_TAX", nth=1),
    ]
    masked = session.mask(text, spans)
    assert STEUER not in masked
    assert masked.count("[[ID_DOCUMENT_") == 2
    assert session.unmask(masked) == text


def test_a_rule_confirms_an_ner_identifier_it_reuses(vault: Vault) -> None:
    from dataclasses import replace

    session = vault.session()
    session.mask(SOURCE, [replace(span_of(SOURCE, STEUER, "ID_DOCUMENT"), detector="ner")])
    session.mask(COPY, [replace(span_of(COPY, STEUER, "NATIONAL_ID_HU_TAX"), detector="rules")])
    # Confirmed by a rule, the value is swept everywhere, a path included.
    path = f"exports/{STEUER}.csv"
    assert STEUER not in session.mask(path, [])


def test_names_and_emails_keep_their_own_keys(vault: Vault) -> None:
    session = vault.session()
    a = "Contact: Paris Weber."
    b = "Office: Paris."
    first = session.mask(a, [span_of(a, "Paris", "PERSON")])
    second = session.mask(b, [span_of(b, "Paris", "ADDRESS")])
    assert "[[PERSON_" in first
    assert "[[ADDRESS_" in second
