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

    def test_short_harness_name_completed_to_a_product(self) -> None:
        # LAB-1485: "pi" is a surname on its own, so only the software context unmasks it.
        text = "Read the pi coding agent docs, then run pi-coding-agent."
        spans = (hit(text, "pi", E.PERSON), hit(text, "pi-coding-agent", E.PERSON))
        assert kept(text, *spans) == []

    def test_short_harness_name_alone_is_kept(self) -> None:
        # Bare "pi" (as in "pi's documentation") cannot be told from the surname Pi:
        # the over-mask is accepted, as for a bare "Claude".
        text = "pi's documentation: run pi --help"
        assert kept(text, hit(text, "pi", E.PERSON)) == ["pi"]

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
