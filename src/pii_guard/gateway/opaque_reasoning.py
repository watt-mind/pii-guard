"""Authorize opaque reasoning only after it was observed upstream (LAB-1753).

Digests live on the vault session, so recreated sessions cannot inherit authorization.
Only bounded hashes are retained; streamed fragments are bounded and authorized as a whole.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from typing import Any

from pii_guard.gateway.request import CollectedTexts, UnsupportedContentError
from pii_guard.vault import VaultSession

MAX_BLOB_CHARS = 1024 * 1024
MAX_BLOBS = 1024
MAX_STREAM_CHARS = 4 * MAX_BLOB_CHARS
_LOCK = threading.Lock()
OPAQUE_KEYS = frozenset({"data", "signature", "encrypted_content"})


def _digest(protocol: str, key: str, value: str) -> bytes:
    return hashlib.sha256((protocol + "\0" + key + "\0" + value).encode()).digest()


def remember(session: VaultSession, protocol: str, key: str, value: str) -> None:
    if not value or len(value) > MAX_BLOB_CHARS:
        return
    digest = _digest(protocol, key, value)
    with _LOCK:
        state = session.opaque_reasoning
        state[digest] = None
        state.move_to_end(digest)
        while len(state) > MAX_BLOBS:
            state.popitem(last=False)


def validate(session: VaultSession, protocol: str, collected: CollectedTexts) -> None:
    with _LOCK:
        state = session.opaque_reasoning
        for key, value in collected.opaque:
            if value and (
                len(value) > MAX_BLOB_CHARS or _digest(protocol, key, value) not in state
            ):
                raise UnsupportedContentError(
                    "opaque reasoning must have been issued upstream in this vault session; "
                    "start a new conversation without imported opaque reasoning"
                )


def _fields(block: Any, keys: frozenset[str] = OPAQUE_KEYS) -> Iterator[tuple[str, str]]:
    if isinstance(block, dict):
        for key in keys:
            if isinstance(block.get(key), str):
                yield key, block[key]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _chat_blocks(body: dict[str, Any]) -> Iterator[tuple[Any, Any]]:
    for choice in _list(body.get("choices")):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message", choice.get("delta", {}))
        if not isinstance(message, dict):
            continue
        for name in ("reasoning_details", "thinking_blocks"):
            for i, block in enumerate(_list(message.get(name))):
                if (
                    isinstance(block, dict)
                    and isinstance(choice.get("index", 0), int)
                    and isinstance(block.get("index", i), int)
                ):
                    yield (choice.get("index", 0), name, block.get("index", i)), block


def _response_blocks(body: dict[str, Any]) -> Iterator[tuple[Any, Any]]:
    response = body.get("response", body)
    if isinstance(response, dict):
        for item in _list(response.get("output")):
            if isinstance(item, dict) and item.get("type") == "reasoning":
                yield None, {"encrypted_content": item.get("encrypted_content")}
    item = body.get("item")
    if isinstance(item, dict) and item.get("type") == "reasoning":
        yield None, {"encrypted_content": item.get("encrypted_content")}


def _message_blocks(body: dict[str, Any]) -> Iterator[tuple[Any, Any]]:
    for block in _list(body.get("content")):
        if isinstance(block, dict) and block.get("type") in {"thinking", "redacted_thinking"}:
            key = "signature" if block["type"] == "thinking" else "data"
            yield None, {key: block.get(key)}
    block = body.get("content_block")
    if isinstance(block, dict) and block.get("type") in {"thinking", "redacted_thinking"}:
        key = "signature" if block["type"] == "thinking" else "data"
        yield body.get("index"), {key: block.get(key)}


def _blocks(protocol: str, body: dict[str, Any]) -> Iterator[tuple[Any, Any]]:
    collect = {"chat": _chat_blocks, "responses": _response_blocks, "messages": _message_blocks}
    yield from collect[protocol](body)


def observe(session: VaultSession, protocol: str, body: dict[str, Any]) -> None:
    for _, block in _blocks(protocol, body):
        for key, value in _fields(block):
            remember(session, protocol, key, value)


class OpaqueStream:
    """One upstream stream's bounded fragment assembler; never store individual fragments."""

    def __init__(self, session: VaultSession, protocol: str) -> None:
        self.session = session
        self.protocol = protocol
        self.parts: dict[tuple[Any, str], list[str]] = {}
        self.chars = 0
        self.overflow = False

    def _append(self, index: Any, key: str, text: str) -> None:
        if not isinstance(index, int | tuple | type(None)):
            return
        if not text:
            return
        self.chars += len(text)
        if self.chars > MAX_STREAM_CHARS or len(self.parts) >= MAX_BLOBS:
            self.parts.clear()
            self.overflow = True
        if not self.overflow:
            self.parts.setdefault((index, key), []).append(text)

    def observe(self, body: dict[str, Any]) -> None:
        if self.protocol == "chat":
            for index, block in _blocks(self.protocol, body):
                for key, value in _fields(block):
                    self._append(index, key, value)
            for choice in _list(body.get("choices")):
                if isinstance(choice, dict) and choice.get("finish_reason"):
                    for at in list(self.parts):
                        if at[0][0] == choice.get("index", 0):
                            self.finish(at[0])
        elif self.protocol == "messages":
            self._messages(body)
        else:
            # Responses emits complete encrypted reasoning in output_item and response events.
            observe(self.session, self.protocol, body)

    def _messages(self, body: dict[str, Any]) -> None:
        for index, block in _blocks(self.protocol, body):
            for key, value in _fields(block):
                # Block starts contain complete encrypted data, signatures may follow.
                if key == "data":
                    remember(self.session, self.protocol, key, value)
                else:
                    self._append(index, key, value)
        delta = body.get("delta")
        if (
            isinstance(delta, dict)
            and delta.get("type") == "signature_delta"
            and isinstance(delta.get("signature"), str)
        ):
            self._append(body.get("index"), "signature", delta["signature"])
        if body.get("type") in {"content_block_stop", "message_stop"}:
            self.finish(body.get("index"))

    def finish(self, index: Any = None) -> None:
        for at in list(self.parts):
            if index is None or at[0] == index:
                remember(self.session, self.protocol, at[1], "".join(self.parts.pop(at)))
