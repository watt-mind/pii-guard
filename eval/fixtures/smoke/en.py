"""English smoke fixtures: ``en-smoke.jsonl``. Built by ``eval/fixtures/build_smoke.py``;
fictional values only (ADR 0005)."""

from __future__ import annotations

from collections.abc import Callable

from build_smoke import BANK, DOB, IDD, ORG, PH, PLATE, TAX, A, E, P, hu_iban, iban, tax_id

from pii_guard.eval import Document, from_markup

# Hungarian values in the mixed-language e-mail (the same payloads as smoke/hu.py's).
TAX_2 = tax_id("834567012")
IBAN_HU_1 = hu_iban("1177777", "000000012345678")


def en_documents() -> list[Document]:
    iban_gb = iban("GB", "EXMP00000012345678")
    iban_de = iban("DE", "100000000123456789")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "en-email-0001",
            f"Subject: tenancy\n\nHi {P('Jane Example')},\n\nThe deposit will be returned to "
            f"{BANK(iban_gb)}. Call me on {PH('+44 20 7946 0123')} or reply to "
            f"{E('jane.example@example.com')}.\n\nBest,\n{P('John Sample')}",
            {"kind": "email"},
        ),
        (
            "en-contract-0002",
            "SERVICE AGREEMENT\n\n"
            f"This agreement is made between {ORG('Fictional Widgets Ltd')} and "
            f"{P('Alex Placeholder')} (born {DOB('14 March 1988')}), residing at "
            f"{A('12 Sample Road, Exampleton EX1 2AB')}. Payments are made to {BANK(iban_de)}.",
            {"kind": "contract"},
        ),
        (
            "en-letter-0003",
            f"Dear {P('Ms Testwood')},\n\nYour passport {IDD('X1234567')} is ready for "
            f"collection at {A('400 Imaginary Avenue, Suite 9, Springfield')}. Please bring a "
            f"copy of this letter.\n\n{ORG('Example County Records Office')}",
            {"kind": "letter"},
        ),
        (
            "en-chat-0004",
            f"hey its {P('Sam Dummy')}, my new number is {PH('+1 202 555 0143')}, "
            f"email {E('sam.dummy@example.net')}. car plate is {PLATE('EX12 MPL')} btw",
            {"kind": "chat", "tags": ["informal"]},
        ),
        (
            "en-email-0005",
            "Subject: invoice 2026-0042\n\n"
            f"Please pay EUR 1,250.00 to {BANK(iban('NL', 'EXMP0123456789'))} "
            f"by 30 November 2026. Questions: {E('billing@example.org')} or "
            f"{PH('+31 20 555 0199')}.\n\n{ORG('Sample Consulting B.V.')}",
            {"kind": "email"},
        ),
        (
            "en-letter-0006",
            f"To whom it may concern,\n\nI confirm that {P('Robin Exampleford')}, date of birth "
            f"{DOB('02/07/1991')}, has lived at {A('Flat 3, 77 Fiction Lane, Exampleton EX4 9ZZ')} "
            "since 2019.\n\nYours faithfully,\n"
            f"{P('Chris Mockley')}, {ORG('Mockley & Partners')}",
            {"kind": "letter"},
        ),
        (
            "en-mixed-0007",
            f"Hi {P('Teszt Elek')}, we received your Hungarian tax ID {TAX(TAX_2)} and your "
            f"bank details ({BANK(IBAN_HU_1)}). Kind regards, {P('Jane Example')}",
            {"kind": "email", "tags": ["mixed-language"]},
        ),
        (
            "en-negative-0008",
            "Order 4417-2209-3301 shipped on 3 November 2026. Reference GB00 0000 0000, "
            "tracking number 1Z999AA10123456784. Customer support is open 9am to 5pm, Monday "
            "to Friday. Room 101, Building 7.",
            {"kind": "notice", "tags": ["hard-negative"]},
        ),
        (
            "en-negative-0009",
            "The baker and the smith walked down Bishop Street past the Rose and Crown. "
            "May turned to June, and Hope was in the air.",
            {"kind": "prose", "tags": ["hard-negative", "common-words"]},
        ),
        (
            "en-chat-0010",
            f"meet at {A('5 Placeholder Square, Exampleton')} at 7? ask for {P('Dana')}. "
            f"my mobile {PH('+44 7700 900123')}",
            {"kind": "chat"},
        ),
    ]
    return [from_markup(doc_id, text, language="en", meta=meta) for doc_id, text, meta in docs]


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    "en-smoke.jsonl": en_documents,
}
