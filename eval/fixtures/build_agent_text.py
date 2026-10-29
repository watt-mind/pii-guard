"""Build ``agent-text/<lang>-agent-text.jsonl``: what coding agents send, with and without data.

LAB-1470. Real coding agents sent their system prompts, skill lists, file names, absolute
paths and tool output through the gateway (``docs/integrations/harness-matrix-2026-10-28.md``),
and the NER read some of it as personal data: ``contacts.json`` as an ``EMAIL``, ``JSON``,
``Claude``, ``Codex`` and ``Muse Spark`` as a ``PERSON``, a ``<project>-<uuid>`` path segment as
an ``ID_DOCUMENT``. This set rebuilds those requests from scratch, in two kinds:

- ``meta.kind = "negative"``: agent text with no personal data at all (system prompts, skill
  lists, file and path names, commands, code). Every masked span is over-masking.
- ``meta.kind = "positive"``: the same kind of text carrying fictional personal data, the way
  a tool result or a user prompt does: a ``cat`` of a JSON file, a CSV in a code fence, a name
  in a file name, an IBAN in an export path. These must stay masked (fail closed).

LAB-1482 adds what the real-harness re-run (LAB-1475,
``docs/integrations/harness-matrix-2026-10-29.md``) still found masked after LAB-1470: Codex's
``prompt_cache_key`` and ``client_metadata`` (bare UUIDs, a ``*_unix_ms`` timestamp, a JSON
``false`` inside a JSON string), an OpenCode ``bash`` command (``python3`` at command position)
and its debug output (``len 89``), and pi's install path (an ``@scope`` under ``node_modules/``).
Its positives put a phone number, an account number and a name right next to those shapes.

Every value is **fictional** (ADR 0005): names from the language packs' test names, ``example``
e-mail domains, textbook IBANs, test phone numbers. No tool or company here is a client.

The Hungarian file uses English agent text with Hungarian prompts, as the gateway saw it (its
default language is ``hu`` for clients that send no header).

Regenerate after editing (a test fails if the committed files are stale)::

    uv run python eval/fixtures/build_agent_text.py

Measure (fast mode)::

    uv run --extra ner pii-guard eval --detectors rules,ner --fixtures eval/fixtures/agent-text
"""

from __future__ import annotations

import sys
from pathlib import Path

from pii_guard.eval import Document, from_markup, label, write_fixtures

HERE = Path(__file__).resolve().parent / "agent-text"
NOTE = (
    "synthetic coding-agent requests (LAB-1470): system prompts, skill lists, file names, "
    "paths and tool output; negatives carry no personal data, positives fictional values only"
)


def P(v: str) -> str:
    return label("PERSON", v)


def E(v: str) -> str:
    return label("EMAIL", v)


def PH(v: str) -> str:
    return label("PHONE", v)


def B(v: str) -> str:
    return label("BANK_ACCOUNT", v)


IBAN_HU = "HU42117730161111101800000000"
IBAN_DE = "DE89370400440532013000"

SYSTEM_OPENCODE = (
    "You are opencode, an interactive CLI tool that helps users with software engineering "
    "tasks. You are powered by the model named Muse Spark. The exact model ID is "
    "meta/muse-spark-1.3.\nHere is some useful information about the environment you are "
    "running in:\n<env>\n  Working directory: "
    "/private/tmp/harness-501/opencode-3f2b8c1e-9a7d-4e6f-b1c2-0d9e8f7a6b5c/repo\n"
    "  Is directory a git repo: yes\n  Platform: darwin\n  Today's date: Wed Oct 28 2026\n"
    "</env>\n<files>\n  AGENTS.md\n  customers.md\n</files>"
)
SKILLS_MUSE = (
    "When a tool returns structured data, serialise it with JSON.stringify(value, null, 2) and "
    "answer with a JSON array, never YAML or TOML. Read files with read_file, write them with "
    "write_file and edit them with edit_file.\n## Skills\n"
    "- claude-api: Build apps with the Claude API or the Anthropic SDK.\n"
    "- codex-review: Ask Codex for a second opinion on a diff.\n"
    "- muse-spark: Notes on the Muse Spark model family and its limits.\n"
    "Available assistants: Claude, Codex, Muse Spark, OpenCode."
)
SKILLS_XML = (
    '<skill id="bundled:claude-api" scope="bundled" '
    'path="bundled://muse-core/skills/claude-api/SKILL.md">Use when the user asks about Claude '
    "or Codex.</skill>\n"
    '<skill id="bundled:json-tools" scope="bundled" '
    'path="bundled://muse-core/skills/json-tools/SKILL.md">Validate JSON and YAML files.</skill>'
)
LS_OUTPUT = (
    "$ ls -la /private/tmp/harness-501/muse-7c1e9a2b-55d0-4c3e-9f1a-2b8d7e6c5a41/workspace\n"
    "-rw-r--r--  1 dev  staff   412 Oct 28 22:41 contacts.json\n"
    "-rw-r--r--  1 dev  staff   388 Oct 28 22:40 AGENTS.md\n"
    "$ cat /Users/dev/.muse/sessions/2026-10-28/b3f1c2d4e5f60718293a4b5c6d7e8f90/state.json"
)
TOOL_SUMMARY = (
    "Wrote `contacts.json` (2 records). Next: run `cat contacts.json`, then "
    "`jq '.[0].email' contacts.json`. The schema lives in `src/schema/contact.schema.json` and "
    "the tests in tests/test_contacts.py; Codex and Claude Code read the same AGENTS.md."
)
CODE = (
    "```ts\nimport { readFileSync } from 'node:fs';\n"
    "const rows = JSON.parse(readFileSync('customers.json', 'utf8'));\n"
    "export function toContact(row: Row): Contact {\n"
    "  return { name: row.fullName, email: row.emailAddress };\n}\n```"
)

# LAB-1482: request metadata and commands (Codex 0.163, OpenCode 1.18, pi 1.3). The UUIDs are
# random v7-shaped ids, the timestamp a 2026 one; the npm scope is made up.
CODEX_CACHE_KEY = (
    "prompt_cache_key: 019a3f2e-7b1c-7d40-abc6-3e9f1a2b4c5d\n"
    "x-codex-window-id: 01934872-5512-7a0c-9e3d-2f4b6a8c0d1e"
)
CODEX_TURN_METADATA = (
    '{"root_turn_id":"01934872-6620-7b1d-8f4e-3a5c7b9d1e2f",'
    '"turn_id":"01934872-6621-7c2e-9a5f-4b6d8c0e2f3a",'
    '"turn_started_at_unix_ms":1793228461234,"sandbox":"workspace-write",'
    '"analytics_enabled":false,"approval_policy":null,"git_dirty":true}'
)
CODEX_CLIENT_METADATA = (
    '{"x-codex-window-id": "019a3f2e-7b1c-7d40-abc6-3e9f1a2b4c5d", '
    '"x-codex-turn-metadata": "{\\"turn_id\\":\\"01934872-6621-7c2e-9a5f-4b6d8c0e2f3a\\",'
    '\\"turn_started_at_unix_ms\\":1793228461234,\\"analytics_enabled\\":false}", '
    '"created_at": 1793228461, "elapsed_ms": 48213}'
)
OPENCODE_BASH = (
    '{"command": "cd /private/tmp/harness-501/opencode-3f2b8c1e/repo && python3 -c '
    "\\\"import json; d = json.load(open('contacts.json')); print('len', len(d))\\\" "
    '| head -n 5; node scripts/check.mjs && jq length contacts.json", '
    '"description": "Count the records"}'
)
OPENCODE_DEBUG = (
    "$ python3 scripts/check.py --verbose\n"
    "rows len 89\nchecked 89 of 89 (len 89, 0 dropped)\nbuffer len 4096, offset 512\nok"
)
PI_INSTALL_PATH = (
    "Documentation: /opt/homebrew/lib/node_modules/@quillstone-works/pi-coding-agent/"
    "README.md (examples in /opt/homebrew/lib/node_modules/@quillstone-works/pi-coding-agent/"
    "examples/extensions/)"
)


def _negatives(prompt: str, edit: str) -> list[str]:
    return [
        SYSTEM_OPENCODE, prompt, edit, SKILLS_MUSE, SKILLS_XML, LS_OUTPUT, TOOL_SUMMARY, CODE,
        CODEX_CACHE_KEY, CODEX_TURN_METADATA, CODEX_CLIENT_METADATA, OPENCODE_BASH,
        OPENCODE_DEBUG, PI_INSTALL_PATH,
    ]  # fmt: skip


def _positives(lang: str) -> list[str]:
    hu_name, de_name = "Kovács Réka", "Jana Beispiel"
    hu_mail, de_mail = "kovacs.reka@example.com", "jana.beispiel@example.de"
    cat_json = (
        "$ cat contacts.json\n```json\n[\n"
        f'  {{"name": "{P(hu_name)}", "email": "{E(hu_mail)}", "iban": "{B(IBAN_HU)}"}},\n'
        f'  {{"name": "{P(de_name)}", "email": "{E(de_mail)}", "iban": "{B(IBAN_DE)}"}}\n'
        "]\n```"
    )
    csv_fence = (
        "Tool result (read_file customers.csv):\n```csv\nname,email,phone\n"
        f"{P(hu_name)},{E(hu_mail)},{PH('+36 30 123 4567')}\n"
        f"{P('Jane Placeholder')},{E('jane.placeholder@example.org')},{PH('+44 20 7946 0958')}\n"
        "```"
    )
    export_path = (
        f"Saved the statement to /exports/2026-10/{B(IBAN_DE)}.csv and attached "
        f"`{P(hu_name)}.pdf` for {P(hu_name)}."
    )
    prompts = {
        "hu": (
            f"Az első ügyfél {P(hu_name)} ({E(hu_mail)}, {PH('+36 30 123 4567')}), a második "
            f"{P(de_name)} ({E(de_mail)}). Írd be mindkettőt a contacts.json fájlba, és futtasd: "
            "cat contacts.json."
        ),
        "en": (
            f"Customer 1 is {P(hu_name)} ({E(hu_mail)}, phone {PH('+36 30 123 4567')}); customer 2 "
            f"is {P(de_name)} ({E(de_mail)}). Save both to contacts.json, then run cat "
            "contacts.json."
        ),
        "de": (
            f"Kundin 1 ist {P(de_name)} ({E(de_mail)}, Telefon {PH('+49 30 901820')}), Kundin 2 "
            f"ist {P(hu_name)} ({E(hu_mail)}). Speichere beide in contacts.json und führe cat "
            "contacts.json aus."
        ),
    }
    edit_with_value = (
        "edit_file contacts.json: replace "
        f'`"email": "{E(de_mail)}"` with `"email": "{E(de_mail)}", "verified": true`.'
    )
    # LAB-1482: personal values right next to the shapes the new guards rule out.
    metadata_values = (
        '{"turn_id":"01934872-6621-7c2e-9a5f-4b6d8c0e2f3a",'
        '"created_at_unix_ms":1793228461234,"notify":false,'
        f'"owner":"{P(hu_name)}","callback":"{PH("+36 30 123 4567")}"}}'
    )
    uuid_prose = (
        f"Ticket 019a3f2e-7b1c-7d40-abc6-3e9f1a2b4c5d: call {P(de_name)} on "
        f"{PH('+49 30 901820')} and refund to {B(IBAN_DE)}."
    )
    command_with_name = (
        f'$ cd repo && python3 send_invoice.py --to "{P(hu_name)}" --phone '
        f"{PH('+36 30 123 4567')} && git commit --author \"{P(de_name)} <{E(de_mail)}>\""
    )
    path_with_name = (
        f"{P(hu_name)} reported a crash in /opt/homebrew/lib/node_modules/@quillstone-works/"
        f"pi-coding-agent/dist/cli.js; reply to {E(hu_mail)}."
    )
    return [
        prompts[lang], cat_json, csv_fence, export_path, edit_with_value, metadata_values,
        uuid_prose, command_with_name, path_with_name,
    ]  # fmt: skip


PROMPTS = {
    "hu": (
        "Olvasd el a customers.md fájlt, és készíts belőle egy contacts.json fájlt (objektumok "
        "tömbje name, email és iban mezőkkel), aztán futtasd: cat contacts.json, és válaszolj a "
        "német ügyfél e-mail címével.",
        'A szerkesztő eszközöddel szúrd be a "verified": true mezőt az első e-mail után a '
        "contacts.json fájlban, a JSON tömb formáját tartsd meg.",
    ),
    "en": (
        "Read customers.md. Convert it into the fixture file contacts.json (array of objects with "
        "name, email and iban fields), then run cat contacts.json and reply with the German "
        "customer's e-mail address.",
        'With your edit tool, insert "verified": true after the first e-mail in contacts.json, '
        "and keep it a JSON array.",
    ),
    "de": (
        "Lies customers.md und wandle sie in die Fixture-Datei contacts.json um (ein Array von "
        "Objekten mit name, email und iban), führe dann cat contacts.json aus und antworte mit "
        "der E-Mail-Adresse der deutschen Kundin.",
        'Füge mit deinem Edit-Tool "verified": true nach der ersten E-Mail in contacts.json ein; '
        "es bleibt ein JSON-Array.",
    ),
}


def build(lang: str) -> list[Document]:
    prompt, edit = PROMPTS[lang]
    docs: list[Document] = []
    for i, text in enumerate(_negatives(prompt, edit), start=1):
        meta = {"kind": "negative", "source": "hand-written", "note": NOTE}
        docs.append(from_markup(f"{lang}-agent-text-n{i:02d}", text, language=lang, meta=meta))
    for i, text in enumerate(_positives(lang), start=1):
        meta = {"kind": "positive", "source": "hand-written", "note": NOTE}
        docs.append(from_markup(f"{lang}-agent-text-p{i:02d}", text, language=lang, meta=meta))
    return docs


LANGUAGES = ("hu", "en", "de")


def main() -> int:
    HERE.mkdir(exist_ok=True)
    for lang in LANGUAGES:
        write_fixtures(HERE / f"{lang}-agent-text.jsonl", build(lang))
    return 0


if __name__ == "__main__":
    sys.exit(main())
