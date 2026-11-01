"""Forward opaque reasoning only after it was observed upstream (LAB-1753).

Digests live on the vault session, so recreated sessions cannot inherit authorization.
Only bounded hashes are retained; streamed fragments are bounded and authorized as a whole.

An opaque blob (a thinking ``signature``, ``redacted_thinking`` data, ``encrypted_content``)
cannot be masked, so a client could smuggle plaintext through one. A blob this vault session
did not see upstream is therefore stripped from the request: the whole reasoning item or
block carrying it is removed, including a thinking block's readable text, so nothing
unverifiable is forwarded (owner decision, 11-01). Stripping cannot leak: it only removes
content. It is what a gateway restart, an expired session or a rotated vault looks like to a
long agent conversation, which keeps working. An upstream that insists on a tool loop's
thinking block may then reject that turn: an upstream error, not a leak.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable, Iterator
from typing import Any

from pii_guard.gateway.request import CollectedTexts
from pii_guard.vault import VaultSession

logger = logging.getLogger("pii_guard.gateway")

#: Response header: how many reasoning items/blocks were stripped (absent: none).
OPAQUE_STRIPPED_HEADER = "X-PII-Guard-Opaque-Reasoning-Stripped"
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


def verified(session: VaultSession, protocol: str, key: str, value: str) -> bool:
    """Whether ``value`` was issued upstream in this session, for this protocol and field."""
    if not value:
        return True  # an empty field carries nothing
    if len(value) > MAX_BLOB_CHARS:
        return False
    with _LOCK:
        return _digest(protocol, key, value) in session.opaque_reasoning


def strip_unverified(
    session: VaultSession,
    protocol: str,
    collected: CollectedTexts,
    recollect: Callable[[], CollectedTexts],
) -> int:
    """Remove every reasoning item or block whose opaque blob this session did not issue.

    Returns how many were removed. ``collected`` is then rebuilt in place from the stripped
    body (``recollect``), so no text of a removed item is detected, masked or checked.
    Only the count is logged, never content.
    """
    unverified = [
        blob for blob in collected.opaque if not verified(session, protocol, blob.key, blob.value)
    ]
    if not unverified:
        return 0
    for blob in unverified:
        blob.drop()
    collected.replace_with(recollect())
    if any(not verified(session, protocol, b.key, b.value) for b in collected.opaque):
        raise AssertionError("an unverified opaque reasoning blob survived stripping")
    logger.info("opaque reasoning stripped protocol=%s count=%d", protocol, len(unverified))
    return len(unverified)


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
            for block in _list(message.get(name)):
                if isinstance(block, dict) and isinstance(choice.get("index", 0), int):
                    at = block.get("index")
                    if at is None:
                        # No index (OpenRouter-style details): each fragment may be a whole
                        # detail, or one piece of one; keyed by its id or type, not position.
                        at = ("id", block["id"]) if isinstance(block.get("id"), str) else None
                        at = at or ("type", str(block.get("type")))
                    elif not isinstance(at, int) or isinstance(at, bool):
                        continue
                    yield (choice.get("index", 0), name, at), block


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
                    if not isinstance(index[2], int):
                        # Unindexed: also a complete detail of its own, as clients may keep it.
                        remember(self.session, self.protocol, key, value)
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
        """Remember the assembled blobs at ``index`` (``None``: all, at the stream's end;
        a stream may end without a ``finish_reason`` or stop event)."""
        for at in list(self.parts):
            if index is None or at[0] == index:
                remember(self.session, self.protocol, at[1], "".join(self.parts.pop(at)))
