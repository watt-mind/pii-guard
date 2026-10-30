"""Structural guards for NER hits in agent text (LAB-1470).

The texts are synthetic versions of what real coding agents sent through the gateway
(docs/integrations/harness-matrix-2026-10-28.md); every name, address and number is fictional
(ADR 0005). The spans are what the NER proposed there, built by hand so no model is needed.
"""

from __future__ import annotations

import pytest

from pii_guard.detect import ner_context
from pii_guard.detect.ner import NerDetector, RawEntity
from pii_guard.detect.ner_context import guard_spans, software_names, sweep_vetoed
from pii_guard.types import EntityType, Span

E = EntityType


def hit(text: str, value: str, entity_type: E, nth: int = 0) -> Span:
    start = -1
    for _ in range(nth + 1):
        start = text.index(value, start + 1)
    return Span(start, start + len(value), entity_type, value, 0.9, "ner")


def kept(text: str, *spans: Span, language: str = "hu") -> list[str]:
    return [s.text for s in guard_spans(text, spans, language)]


PROMPT = (
    "Read customers.md. Convert it into the fixture file contacts.json (array of objects), "
    "then run cat contacts.json and reply with the German customer's e-mail."
)


class TestEmailNeedsAt:
    def test_file_name_is_not_an_email(self) -> None:
        assert kept(PROMPT, hit(PROMPT, "contacts.json", E.EMAIL)) == []

    def test_piece_of_a_file_name_is_not_an_email(self) -> None:
        assert kept(PROMPT, hit(PROMPT, "s.json", E.EMAIL)) == []

    def test_word_without_at_is_not_an_email(self) -> None:
        text = "Mentsd el a contact listát."
        assert kept(text, hit(text, "contact", E.EMAIL)) == []

    def test_real_address_is_kept(self) -> None:
        text = "Írj neki: kovacs.reka@example.com, holnap."
        assert kept(text, hit(text, "kovacs.reka@example.com", E.EMAIL)) == [
            "kovacs.reka@example.com"
        ]

    def test_part_of_a_real_address_is_kept(self) -> None:
        text = "Írj neki: kovacs.reka@example.com, holnap."
        assert kept(text, hit(text, "kovacs.reka", E.EMAIL)) == ["kovacs.reka"]

    def test_npm_scope_is_not_an_email(self) -> None:
        text = "Install it with npm i @example-works/pi-coding-agent first."
        assert kept(text, hit(text, "example", E.EMAIL)) == []

    def test_spelled_out_address_is_kept(self) -> None:
        text = "Write to kovacs.reka at example dot com today."
        assert kept(text, hit(text, "kovacs.reka", E.EMAIL)) == ["kovacs.reka"]


class TestFilesAndPaths:
    def test_extension_tagged_as_a_person(self) -> None:
        text = "The sweep masked contacts.json in the prompt."
        assert kept(text, hit(text, "json", E.PERSON)) == []

    def test_fence_info_string(self) -> None:
        text = '```json\n[{"name": "Kovács Réka"}]\n```'
        spans = (hit(text, "json", E.PERSON), hit(text, "Kovács Réka", E.PERSON))
        assert kept(text, *spans) == ["Kovács Réka"]

    def test_uuid_path_segment_is_not_an_id(self) -> None:
        text = "Working directory: /private/tmp/harness-501/opencode-3f2b8c1e-9a7d-4e6f/repo"
        spans = (
            hit(text, "3f2b8c1e-9a7d", E.ID_DOCUMENT),
            hit(text, "9a7d-4e6f", E.BANK_ACCOUNT),
        )
        assert kept(text, *spans) == []

    def test_tool_name_in_a_numbered_path_segment(self) -> None:
        text = "cwd=/private/tmp/claude-501/T/workspace"
        assert kept(text, hit(text, "claude", E.PERSON)) == []

    def test_person_folder_without_digits_is_kept(self) -> None:
        text = "Open /Users/anna.kovacs/Documents/letter.docx please."
        assert kept(text, hit(text, "anna.kovacs", E.PERSON)) == ["anna.kovacs"]

    def test_name_in_a_file_stem_is_kept(self) -> None:
        text = "Attach Kovács Réka.pdf to the reply."
        assert kept(text, hit(text, "Kovács Réka", E.PERSON)) == ["Kovács Réka"]

    def test_slash_in_an_address_is_not_a_path(self) -> None:
        text = "Lakcím: 1051 Budapest, Minta utca 12. 3/5."
        assert kept(text, hit(text, "1051 Budapest, Minta utca 12. 3/5", E.ADDRESS)) == [
            "1051 Budapest, Minta utca 12. 3/5"
        ]

    def test_date_with_slashes_is_not_a_path(self) -> None:
        text = "Született: 04/03/1971."
        assert kept(text, hit(text, "04/03/1971", E.DATE_OF_BIRTH)) == ["04/03/1971"]

    def test_id_document_outside_a_path_is_kept(self) -> None:
        text = "Passport number: AB1234567, valid."
        assert kept(text, hit(text, "AB1234567", E.ID_DOCUMENT)) == ["AB1234567"]


class TestCodeIdentifiers:
    def test_called_chain(self) -> None:
        text = "Serialise it with JSON.stringify(value, null, 2)."
        # JSON is also a listed format; Stringify alone shows the call rule.
        assert kept(text, hit(text, "JSON", E.PERSON)) == []
        text = "Then call Reka.render(item) on each row."
        assert kept(text, hit(text, "Reka", E.PERSON)) == []

    def test_snake_and_camel_parts(self) -> None:
        text = "Call load_customers and getCustomerName before saving."
        assert kept(text, hit(text, "customers", E.PERSON), hit(text, "Customer", E.PERSON)) == []

    def test_dotted_name_that_is_no_code_is_kept(self) -> None:
        text = "His handle is reka.kovacs on the forum."
        assert kept(text, hit(text, "kovacs", E.PERSON)) == ["kovacs"]

    def test_whole_snake_identifier_is_kept(self) -> None:
        text = "The user anna_kovacs logged in."
        assert kept(text, hit(text, "anna_kovacs", E.PERSON)) == ["anna_kovacs"]

    def test_lowercase_word_in_inline_code(self) -> None:
        text = "Run `codex exec --sandbox workspace-write` again."
        assert kept(text, hit(text, "codex", E.PERSON)) == []

    def test_name_in_inline_code_is_kept(self) -> None:
        text = "Set `owner = Kovács Réka` in the config."
        assert kept(text, hit(text, "Kovács Réka", E.PERSON)) == ["Kovács Réka"]


class TestSoftwareNames:
    def test_listed_names(self) -> None:
        text = "You are OpenCode, powered by Muse Spark. Answer with a JSON array, not YAML."
        spans = [hit(text, v, E.PERSON) for v in ("OpenCode", "Muse Spark", "JSON", "YAML")]
        assert kept(text, *spans) == []

    def test_given_name_completed_to_a_product(self) -> None:
        text = "Build it with the Claude API, or ask Claude Code."
        spans = (hit(text, "Claude", E.PERSON), hit(text, "Claude", E.PERSON, nth=1))
        assert kept(text, *spans) == []

    def test_given_name_listed_with_software(self) -> None:
        text = "Available assistants: Claude, Codex, Muse Spark. Ask Claude or Codex."
        spans = [
            hit(text, "Claude", E.PERSON),
            hit(text, "Codex", E.PERSON),
            hit(text, "Claude", E.PERSON, nth=1),
            hit(text, "Codex", E.PERSON, nth=1),
        ]
        assert kept(text, *spans) == []

    def test_given_name_in_a_quoted_list(self) -> None:
        text = "The NER tags `JSON`, `Claude`, `Codex` and `Muse Spark` as PERSON."
        assert kept(text, hit(text, "Claude", E.PERSON)) == []

    def test_given_name_alone_is_kept(self) -> None:
        text = "Claude sent the invoice yesterday."
        assert kept(text, hit(text, "Claude", E.PERSON)) == ["Claude"]

    def test_lexicon_name_listed_with_software_is_kept(self) -> None:
        text = "Ask Anna or Codex for a review."
        assert kept(text, hit(text, "Anna", E.PERSON), hit(text, "Codex", E.PERSON)) == ["Anna"]

    def test_full_name_with_a_listed_word_is_kept(self) -> None:
        text = "Our tester is Claude Martin, not Codex."
        assert kept(text, hit(text, "Claude Martin", E.PERSON)) == ["Claude Martin"]

    def test_listed_word_with_a_name_next_to_it_is_kept(self) -> None:
        text = "Szia, itt Kovács Codex beszél."
        assert kept(text, hit(text, "Kovács", E.PERSON), hit(text, "Codex", E.PERSON)) == [
            "Kovács",
            "Codex",
        ]

    def test_only_person_hits_are_checked(self) -> None:
        text = "Codex utca 4., Budapest"
        assert kept(text, hit(text, "Codex utca 4., Budapest", E.ADDRESS)) == [
            "Codex utca 4., Budapest"
        ]

    def test_list_is_software_only(self) -> None:
        from pii_guard.detect.ner_orgs import _person_names

        persons = _person_names()
        single = {n for n in software_names() if " " not in n}
        assert not single & persons
        assert "claude" not in software_names()  # a given name: only as part of a product
        assert {"json", "codex", "muse spark", "claude code"} <= software_names()


def test_off_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    span = hit(PROMPT, "contacts.json", E.EMAIL)
    monkeypatch.setenv(ner_context.ENV_VAR, "false")
    assert kept(PROMPT, span) == ["contacts.json"]
    assert not sweep_vetoed(PROMPT, span.start, span.end, E.EMAIL, "hu")


def test_sweep_veto_matches_the_span_guard() -> None:
    import re

    text = "Use Claude Code; the logs are in /tmp/claude-501/run and in claude.log."
    starts = [m.start() for m in re.finditer("claude", text, re.IGNORECASE)]
    vetoed = [sweep_vetoed(text, s, s + 6, E.PERSON, "en") for s in starts]
    # A product name and a numbered path segment: left alone. A file stem: still masked.
    assert vetoed == [True, True, False]
    assert not sweep_vetoed("Claude called.", 0, 6, E.PERSON, "en")


def test_ner_detector_applies_the_guards() -> None:
    class Backend:
        def predict(self, text: str) -> list[RawEntity]:
            found = []
            for value, label in (("contacts.json", "EMAIL"), ("Kovács Réka", "PERSON")):
                i = text.index(value)
                found.append(RawEntity(label, i, i + len(value), 0.99))
            return found

    detector = NerDetector(backend=Backend(), entity_types=["EMAIL", "PERSON"])
    text = "Kovács Réka adatait mentsd a contacts.json fájlba."
    assert [s.text for s in detector.detect(text, "hu")] == ["Kovács Réka"]


class TestMachineTokens:
    """LAB-1482: request metadata and commands from the LAB-1475 re-run
    (docs/integrations/harness-matrix-2026-10-29.md). The spans are what the NER proposed."""

    CODEX_UUID = "019a3f2e-7b1c-7d40-abc6-3e9f1a2b4c5d"
    TURN = (
        '{"turn_id":"01934872-6621-7c2e-9a5f-4b6d8c0e2f3a",'
        '"turn_started_at_unix_ms":1793228461234,"analytics_enabled":false,"x":null}'
    )

    def test_leading_segment_of_a_bare_uuid_is_not_a_phone(self) -> None:
        text = f"prompt_cache_key: {self.CODEX_UUID}"
        assert kept(text, hit(text, "019a3f2e", E.PHONE)) == []
        assert kept(self.TURN, hit(self.TURN, "01934872-6621-7c2e", E.PHONE)) == []

    def test_uuid_in_escaped_json_and_prose(self) -> None:
        text = '{"m": "{\\"turn_id\\":\\"01934872-6621-7c2e-9a5f-4b6d8c0e2f3a\\"}"}'
        assert kept(text, hit(text, "01934872", E.BANK_ACCOUNT)) == []
        text = f"Ticket {self.CODEX_UUID} is closed."
        assert kept(text, hit(text, "019a3f2e-7b1c", E.PERSON)) == []

    def test_phone_next_to_a_uuid_is_kept(self) -> None:
        text = f"Ticket {self.CODEX_UUID}: call +36 30 123 4567 or 06301234567."
        spans = (hit(text, "+36 30 123 4567", E.PHONE), hit(text, "06301234567", E.PHONE))
        assert kept(text, *spans) == ["+36 30 123 4567", "06301234567"]

    def test_hit_spilling_out_of_a_uuid_is_kept(self) -> None:
        text = f"id {self.CODEX_UUID} Teszt Elek"
        assert kept(text, hit(text, "4c5d Teszt Elek", E.PERSON)) == ["4c5d Teszt Elek"]

    def test_json_literals_are_not_names(self) -> None:
        assert kept(self.TURN, hit(self.TURN, "false", E.PERSON)) == []
        assert kept(self.TURN, hit(self.TURN, "null", E.PERSON)) == []
        text = "analytics_enabled=false, telemetry: true"
        assert kept(text, hit(text, "false", E.PERSON), hit(text, "true", E.PERSON)) == []

    def test_word_false_in_prose_needs_value_position(self) -> None:
        text = "Ask False about it."  # capitalised, no value position: not this guard's call
        assert kept(text, hit(text, "False", E.PERSON)) == ["False"]

    def test_epoch_milliseconds_in_a_time_field_are_not_an_account(self) -> None:
        assert kept(self.TURN, hit(self.TURN, "1793228461234", E.BANK_ACCOUNT)) == []
        text = "created_at=1793228461 elapsed"
        assert kept(text, hit(text, "1793228461", E.PHONE)) == []

    def test_long_numbers_elsewhere_are_kept(self) -> None:
        text = '{"account":1793228461234,"phone":"3630123456"}'
        spans = (hit(text, "1793228461234", E.BANK_ACCOUNT), hit(text, "3630123456", E.PHONE))
        assert kept(text, *spans) == ["1793228461234", "3630123456"]
        text = "Account 1793228461234 at the bank, call 3630123456."
        spans = (hit(text, "1793228461234", E.BANK_ACCOUNT), hit(text, "3630123456", E.PHONE))
        assert kept(text, *spans) == ["1793228461234", "3630123456"]

    def test_time_field_with_a_phone_shaped_value_is_kept(self) -> None:
        text = '"callback_at": "+36301234567"'
        assert kept(text, hit(text, "+36301234567", E.PHONE)) == ["+36301234567"]

    def test_executable_at_command_position_is_not_a_name(self) -> None:
        text = '{"command": "cd /work/repo && python3 -c \\"print(1)\\" | jq ."}'
        spans = (hit(text, "python3", E.PERSON), hit(text, "jq", E.PERSON))
        assert kept(text, *spans) == []
        text = '{"command": "python3 scripts/check.py"}'
        assert kept(text, hit(text, "python3", E.PERSON)) == []
        text = "$ python3 scripts/check.py --verbose"
        assert kept(text, hit(text, "python3", E.PERSON)) == []

    def test_name_next_to_a_command_is_kept(self) -> None:
        text = '$ cd repo && python3 send.py --to "Kovács Réka" && echo Teszt Elek'
        spans = (hit(text, "Kovács Réka", E.PERSON), hit(text, "Teszt Elek", E.PERSON))
        assert kept(text, *spans) == ["Kovács Réka", "Teszt Elek"]
        text = "cd repo && Elek ran it"  # written as a name: not an executable
        assert kept(text, hit(text, "Elek", E.PERSON)) == ["Elek"]

    def test_lowercase_word_in_prose_is_kept(self) -> None:
        text = "I met elek yesterday."
        assert kept(text, hit(text, "elek", E.PERSON)) == ["elek"]

    def test_letterless_person_is_dropped(self) -> None:
        text = "rows len 89\nchecked 89 of 89"
        assert kept(text, hit(text, "89", E.PERSON), hit(text, "89", E.PERSON, 1)) == []

    def test_npm_scope_under_node_modules_is_not_a_name(self) -> None:
        text = "Read /opt/homebrew/lib/node_modules/@quillstone-works/pi-coding-agent/README.md"
        spans = (hit(text, "quillstone", E.PERSON), hit(text, "pi-coding-agent", E.PERSON))
        assert kept(text, *spans) == []

    def test_home_directory_beside_node_modules_is_kept(self) -> None:
        text = "/Users/anna.kovacs/project/node_modules/@scope-works/pkg/index.js"
        assert kept(text, hit(text, "anna.kovacs", E.PERSON)) == ["anna.kovacs"]


class TestBareNumbersAsAddress:
    """LAB-1477: a bare number the NER typed ``ADDRESS`` with nothing address-like next to it
    (a port, a size, a ticket number). The spans are what NER v2.0 proposed."""

    def test_size_is_not_an_address(self) -> None:
        text = "The vault holds up to 4096 keyed digests."
        assert kept(text, hit(text, "4096", E.ADDRESS)) == []

    def test_ports_are_not_addresses(self) -> None:
        text = "Ports 18790 and 18787 are documented in docs/operations.md."
        assert kept(text, hit(text, "18790", E.ADDRESS), hit(text, "18787", E.ADDRESS)) == []
        text = "The proxy listens on localhost (default 8787, `--port` to change it)."
        assert kept(text, hit(text, "8787", E.ADDRESS)) == []
        for text in ("Start it with --port 8787 now.", "PORT=8787", "a 8787-es porton fut"):
            assert kept(text, hit(text, "8787", E.ADDRESS)) == []

    def test_number_before_a_sentence_end_or_an_address_further_on(self) -> None:
        text = "The metrics exporter uses 18790. Ports are listed below."
        assert kept(text, hit(text, "18790", E.ADDRESS)) == []
        text = "Ship ticket 4471 to Musterstraße 12, 10115 Berlin."
        assert kept(text, hit(text, "4471", E.ADDRESS)) == []

    def test_json_value_under_a_ticket_key_is_not_an_address(self) -> None:
        text = '{"customer": "x", "email": "y", "iban": "z", "ticket": 4471}'
        assert kept(text, hit(text, "4471", E.ADDRESS)) == []

    def test_sku_digits_and_amounts_are_not_addresses(self) -> None:
        text = "items:\n  - sku: GT-81215\n    qty: 3\nrow,830916757880,7869.62"
        assert kept(text, hit(text, "81215", E.ADDRESS), hit(text, "7869.62", E.ADDRESS)) == []

    def test_postcode_next_to_a_settlement_is_kept(self) -> None:
        for text, value in (
            ("lakcím: 1051 Budapest, Minta utca 12.", "1051"),
            ("Musterstraße 12, 10115 Berlin", "10115"),
            ("Budapest, 1051", "1051"),
            ("Anschrift: H-6720 Szeged", "6720"),
        ):
            assert kept(text, hit(text, value, E.ADDRESS)) == [value]

    def test_house_number_after_a_street_is_kept(self) -> None:
        for text, value in (
            ("Minta utca 12. 3/5.", "12."),
            ("Minta utca 12. 3/5.", "3/5."),
            ("She lives at Elm Grove 54 now.", "54"),
            ("Lindenweg 17", "17"),
        ):
            assert kept(text, hit(text, value, E.ADDRESS)) == [value]

    def test_cued_number_is_kept(self) -> None:
        for text, value in (
            ('{"zip": 1051, "city": "x"}', "1051"),
            ("irányítószám: 6720", "6720"),
            ("PLZ 10115", "10115"),
            ("postcode 4471 (see form)", "4471"),
        ):
            assert kept(text, hit(text, value, E.ADDRESS)) == [value]

    def test_number_beside_another_address_hit_is_kept(self) -> None:
        text = "cím: 6720 szeged, kitalált tér 3."
        spans = (hit(text, "6720", E.ADDRESS), hit(text, "szeged, kitalált tér 3.", E.ADDRESS))
        assert kept(text, *spans) == ["6720", "szeged, kitalált tér 3."]

    def test_address_with_letters_is_untouched(self) -> None:
        text = "The vault holds up to 4096 keyed digests at 12 Sample Road."
        assert kept(text, hit(text, "12 Sample Road", E.ADDRESS)) == ["12 Sample Road"]

    def test_bare_address_number_without_a_street_is_kept(self) -> None:
        """LAB-1599: a missing street or city is no reason to drop a number (Ai4Privacy shapes,
        fictional values). Only a positive non-address sign drops one."""
        for text, value in (
            ("Meet near building number 800, where the parade starts.", "800"),
            ("   • Street: Sample Road\n   • Building No.: 607\n   • City: Exampleton", "607"),
            ("the zip code for the area is 92004.", "92004"),
            ("Please send your 123023 to ensure proper mailing.", "123023"),
            ("Mintaköz 34 in Graz (1040) erfasst.", "1040"),
            ("a gig-dolgozók a 6000 környékeken élnek", "6000"),
            ("Mahamat, a Minta utca 94 szám alatt, a 1126 területen", "1126"),
            ("Meet at Bypass Road #542 for the track.", "542"),
            ("shipped to County Road 260 #1963", "1963"),
        ):
            assert kept(text, hit(text, value, E.ADDRESS)) == [value], text

    def test_labelled_non_address_numbers_go(self) -> None:
        for text, value in (
            ("Fixed in PR #295 and issue 4471.", "295"),
            ("Fixed in PR #295 and issue 4471.", "4471"),
            ("Upgrade to version 2026 first.", "2026"),
            ('{"pid": 81215, "timeout": 3000}', "81215"),
            ("hrsz.: 0123", "0123"),
        ):
            assert kept(text, hit(text, value, E.ADDRESS)) == [], text

    def test_weak_sign_next_to_an_address_keeps_it(self) -> None:
        text = "The office listens to callers at Musterstraße 12, 10115 Berlin."
        assert kept(text, hit(text, "10115", E.ADDRESS)) == ["10115"]

    def test_sweep_leaves_a_bare_port_alone(self) -> None:
        text = "Ports 18790 and 18787."
        s = text.index("18787")
        assert sweep_vetoed(text, s, s + 5, E.ADDRESS, "en")


class TestEponyms:
    """LAB-1477: an algorithm's or method's eponym (``Luhn``) in technical prose."""

    def test_luhn_test_card_is_not_a_person(self) -> None:
        text = "Validate the card with a Luhn test card number."
        assert kept(text, hit(text, "Luhn", E.PERSON), language="en") == []
        assert kept(text, hit(text, "Luhn", E.PERSON), language="hu") == []

    def test_method_nouns_in_each_language(self) -> None:
        for text, value in (
            ("Run the Luhn check on it.", "Luhn"),
            ("It uses Levenshtein distance.", "Levenshtein"),
            ("Dijkstra's algorithm finds it.", "Dijkstra"),
            ("A kártyaszámot Luhn-algoritmussal ellenőrzi.", "Luhn"),
            ("A Verhoeff ellenőrzés hibát jelez.", "Verhoeff"),
            ("Die Luhn-Prüfsumme stimmt nicht.", "Luhn"),
            ("Ein Bloom Filter reicht.", "Bloom"),
        ):
            assert kept(text, hit(text, value, E.PERSON)) == [], text

    def test_real_names_are_kept(self) -> None:
        for text, value in (
            ("Kovács test results are ready.", "Kovács"),  # a lexicon name
            ("Hans Luhn test results are ready.", "Luhn"),  # part of a longer name
            ("Ask Luhn about the card.", "Luhn"),  # no method noun after it
            ("Luhn tested the card.", "Luhn"),  # a verb, not the noun
        ):
            spans = [hit(text, value, E.PERSON)]
            if text.startswith("Hans"):
                spans.insert(0, hit(text, "Hans", E.PERSON))
            assert value in kept(text, *spans), text

    def test_full_name_hit_is_kept(self) -> None:
        text = "Peter Luhn test results are ready."
        assert kept(text, hit(text, "Peter Luhn", E.PERSON)) == ["Peter Luhn"]


class TestFamilyFirmWords:
    """LAB-1220: ``Fia`` / ``Társa`` in ``Balogh és Fia Kkt.`` names a relation, not a person."""

    def test_family_word_before_a_legal_form_is_not_a_person(self) -> None:
        for text, value in (
            ("Vállalkozó: Balogh és Fia Kkt., képviseli az ügyvezető.", "Fia"),
            ("A Szabó és Fiai Kkt. ajánlata a legkedvezőbb.", "Fiai"),
            ("A Szabó és Fiai Kkt.-val szerződtünk.", "Fiai"),
            ("Bérlő: Pintér Zoltán és Társa Bt. fizet.", "Társa"),
            ("A Simon & Társa Bt.-vel megyünk tovább.", "Társa"),
            ("A NÉMETH ÉS FIA KFT. képviselője.", "FIA"),
            ("A Kiss és Lánya Építő Kft. nyerte.", "Lánya"),
        ):
            assert kept(text, hit(text, value, E.PERSON)) == [], text
            assert sweep_vetoed(
                text, text.index(value), text.index(value) + len(value), E.PERSON, "hu"
            )

    def test_the_member_name_is_kept(self) -> None:
        text = "Vállalkozó: Balogh és Fia Kkt."
        spans = (hit(text, "Balogh", E.PERSON), hit(text, "Fia", E.PERSON))
        assert kept(text, *spans) == ["Balogh"]

    def test_without_the_firm_shape_it_is_kept(self) -> None:
        for text, value in (
            ("Fia Kkt. ügyvezetője.", "Fia"),  # no connector before it
            ("Balogh és Fia elutazott.", "Fia"),  # no legal form after it
            ("Kovács és Fia Anna Kft.", "Fia Anna"),  # a longer hit is a name
            ("Kovács és Fiala Kft.", "Fiala"),  # a surname, not the family word
        ):
            assert kept(text, hit(text, value, E.PERSON)) == [value], text

    def test_other_types_are_untouched(self) -> None:
        text = "A Balogh és Fia Kkt. ajánlata."
        assert kept(text, hit(text, "Fia", E.ORGANIZATION)) == ["Fia"]
