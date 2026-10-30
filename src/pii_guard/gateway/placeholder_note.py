"""The note the gateway adds when a request carries placeholders (LAB-1471).

A model that reads ``[[NATIONAL_ID_HU_TAJ_5a63fe]]`` can take the label for the data and
decline to copy it, which breaks the agent task the gateway exists for. When the masked body
holds at least one placeholder this session issued, the gateway puts one short system note in
front of the conversation saying what placeholders are.

The note is a constant: it carries no value, no placeholder and nothing derived from the
request, so it can't leak anything or be restored into anything. It contains no
placeholder-shaped token (``[[TYPE_id]]`` doesn't match
:data:`~pii_guard.vault.PLACEHOLDER_RE`), so a model
that quotes it back produces nothing the restorer would touch. It is added after masking and
never scanned, and it is the first item of the conversation, so a provider's prompt cache keeps
a stable prefix. ``PII_GUARD_GATEWAY_PLACEHOLDER_NOTE=false`` turns it off.
"""

from __future__ import annotations

from typing import Any

from pii_guard.vault import VaultSession

__all__ = [
    "NOTE_HEADER",
    "PLACEHOLDER_NOTE",
    "add_chat_note",
    "add_messages_note",
    "add_responses_note",
    "needs_note",
]

#: Response header set (``added``) when the note went upstream with the request.
NOTE_HEADER = "X-PII-Guard-Placeholder-Note"

PLACEHOLDER_NOTE = (
    "Note from the user's privacy gateway: personal data in this conversation "
    "was replaced by placeholders of the form [[TYPE_id]]. A placeholder is an opaque reference "
    "token, not real data; its TYPE is only a label, even when it names an ID number or a bank "
    "account. Copy, repeat, write and edit placeholders exactly as written wherever the task "
    "needs the value: in replies, files, commands and tool arguments. The gateway turns them "
    "back into the real values after your answer, outside this conversation. Never refuse, "
    "leave out or alter a "
    "placeholder because of its label."
)


def needs_note(payload: str, session: VaultSession) -> bool:
    """True if ``payload`` (the masked body) holds a placeholder ``session`` issued."""
    return session.issued_any(payload)


def add_chat_note(body: dict[str, Any]) -> None:
    """Put the note in front of a Chat Completions ``messages`` list."""
    messages = body.get("messages")
    if isinstance(messages, list):
        messages.insert(0, {"role": "system", "content": PLACEHOLDER_NOTE})


def add_responses_note(body: dict[str, Any]) -> None:
    """Put the note in front of a Responses request's ``instructions``.

    ``instructions`` is the Responses API's system prompt; an absent or empty one becomes the
    note alone. ``input`` is left as the client sent it, so item indexes in errors stay right.
    """
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions:
        body["instructions"] = f"{PLACEHOLDER_NOTE}\n\n{instructions}"
    elif instructions is None or instructions == "":
        body["instructions"] = PLACEHOLDER_NOTE


def add_messages_note(body: dict[str, Any]) -> None:
    """Put the note in front of a Messages API request's ``system`` (LAB-1605).

    A string ``system`` gets the note as a first paragraph; a list of text blocks gets it as
    a first block (the client's ``cache_control`` marks stay on its own blocks); an absent or
    empty one becomes the note alone. ``messages`` is left as sent, so indexes in errors stay
    right.
    """
    system = body.get("system")
    if isinstance(system, str) and system:
        body["system"] = f"{PLACEHOLDER_NOTE}\n\n{system}"
    elif isinstance(system, list) and system:
        system.insert(0, {"type": "text", "text": PLACEHOLDER_NOTE})
    elif system is None or system == "" or system == []:
        body["system"] = PLACEHOLDER_NOTE
