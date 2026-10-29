"""Hosted identity primitives. Headers are trusted only behind the configured auth sidecar.

No header parser can establish that deployment boundary: the caller must first establish
that the application's origin is inaccessible except through Azure Easy Auth. Browser
headers, email addresses and arbitrary bearer strings never establish an owner here.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pii_guard.types import PiiGuardError

GUEST_COOKIE_NAME = "__Host-pii-guard-guest"
_SUBJECT_CLAIMS = frozenset(
    {"sub", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"}
)
_GUEST_ID = re.compile(r"^[A-Za-z0-9_-]{43}$")
_KEY = re.compile(r"^pg_[A-Za-z0-9_-]{43}$")


class IdentityError(PiiGuardError):
    code = "unauthorized"
    status_code = 401

    def __init__(self) -> None:
        super().__init__("a valid hosted identity is required")


class KeyCapacityError(PiiGuardError):
    code = "api_key_limit"
    status_code = 429

    def __init__(self) -> None:
        super().__init__("API key capacity reached; revoke an existing key")


@dataclass(frozen=True, slots=True)
class Principal:
    id: str
    authenticated: bool
    auth_method: Literal["google", "api_key", "guest"]


def _check_master(master_key: bytes) -> None:
    if len(master_key) < 32:
        raise ValueError("hosted master key must contain at least 32 bytes")


def _opaque_id(master_key: bytes, namespace: bytes, value: str) -> str:
    return hmac.new(master_key, namespace + b"\x00" + value.encode(), hashlib.sha256).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise IdentityError()
        result[key] = value
    return result


def easy_auth_principal(encoded: str, *, master_key: bytes, trusted: bool) -> Principal:
    """Decode an authenticated Google subject, never an email or display-name claim.

    ``trusted`` is a deployment assertion, not a request header. Duplicate JSON keys or
    subject claims are refused; two accepted subject aliases must agree exactly.
    """
    _check_master(master_key)
    if not trusted or not isinstance(encoded, str) or not 1 <= len(encoded) <= 16_384:
        raise IdentityError()
    try:
        raw = base64.b64decode(encoded, validate=True)
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, binascii.Error, RecursionError):
        raise IdentityError() from None
    if not isinstance(value, dict) or value.get("auth_typ") != "google":
        raise IdentityError()
    claims = value.get("claims")
    if not isinstance(claims, list) or not 1 <= len(claims) <= 128:
        raise IdentityError()
    subjects: dict[str, str] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            raise IdentityError()
        kind, subject = claim.get("typ"), claim.get("val")
        if (
            not isinstance(kind, str)
            or not isinstance(subject, str)
            or len(kind) > 512
            or len(subject) > 2048
        ):
            raise IdentityError()
        if kind in _SUBJECT_CLAIMS:
            if kind in subjects or not subject or subject != subject.strip():
                raise IdentityError()
            if any(ord(char) < 32 or ord(char) == 127 for char in subject):
                raise IdentityError()
            subjects[kind] = subject
    if not subjects or len(set(subjects.values())) != 1:
        raise IdentityError()
    subject = next(iter(subjects.values()))
    return Principal("u_" + _opaque_id(master_key, b"google", subject), True, "google")


class GuestIdentity:
    """Signed, expiring random guests. Invalid cookies start a fresh isolated guest.

    The cookie stores only a random nonce and expiry. It cannot turn a guest into a user,
    choose a user id, or renew an old guest's lifetime. Its signature has a distinct domain
    from user ids and vault keys. A deployment restart may rotate the master key.
    """

    def __init__(
        self,
        master_key: bytes,
        *,
        ttl_seconds: int = 3600,
        clock: Callable[[], float] = time.time,
    ) -> None:
        _check_master(master_key)
        if not 1 <= ttl_seconds <= 86_400:
            raise ValueError("guest lifetime must be between 1 and 86400 seconds")
        self._master_key = master_key
        self.ttl_seconds = ttl_seconds
        self._clock = clock

    def _sign(self, value: str) -> str:
        return _opaque_id(self._master_key, b"guest-cookie-v1", value)

    def resolve(self, cookie: str | None) -> tuple[Principal, str | None]:
        """Return the guest and a new cookie value only when no valid cookie was supplied."""
        now = int(self._clock())
        if cookie and len(cookie) <= 200:
            parts = cookie.split(".")
            if len(parts) == 3:
                nonce, expires, signature = parts
                if (
                    _GUEST_ID.fullmatch(nonce)
                    and expires.isascii()
                    and expires.isdigit()
                    and len(expires) <= 12
                    and re.fullmatch(r"[a-f0-9]{64}", signature)
                    and now < int(expires) <= now + self.ttl_seconds
                    and hmac.compare_digest(signature, self._sign(f"{nonce}.{expires}"))
                ):
                    return Principal("g_" + nonce, False, "guest"), None
        nonce = secrets.token_urlsafe(32)
        value = f"{nonce}.{now + self.ttl_seconds}"
        return Principal("g_" + nonce, False, "guest"), value + "." + self._sign(value)

    def cookie_header(self, cookie: str) -> str:
        """Use only the newly generated value from :meth:`resolve`. No Domain attribute."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}\.[0-9]{1,12}\.[a-f0-9]{64}", cookie):
            raise ValueError("invalid generated guest cookie")
        return (
            f"{GUEST_COOKIE_NAME}={cookie}; Path=/; Max-Age={self.ttl_seconds}; "
            "Secure; HttpOnly; SameSite=Strict"
        )


@dataclass(frozen=True, slots=True)
class _StoredKey:
    id: str
    owner: str
    name: str
    prefix: str
    created_at: str
    expires_at: float
    digest: bytes = field(repr=False)

    def metadata(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "prefix": self.prefix,
            "created_at": self.created_at,
        }


class ApiKeyStore:
    """Bounded ephemeral owner-scoped keys: only SHA-256 verifiers are retained.

    A full store refuses issuance; it never evicts another user's live key. Revocation and
    expiry deny subsequent admission; an already admitted request may finish. User-provided
    key names are returned to their owner only, and must never be used as log fields.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 86_400,
        max_keys_per_principal: int = 5,
        max_keys: int = 1000,
        max_principals: int = 1000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if min(ttl_seconds, max_keys_per_principal, max_keys, max_principals) < 1:
            raise ValueError("API key limits must be positive")
        self._ttl = ttl_seconds
        self._per_principal = max_keys_per_principal
        self._max_keys = max_keys
        self._max_principals = max_principals
        self._clock = clock
        self._keys: dict[bytes, _StoredKey] = {}
        self._lock = threading.Lock()

    def _prune(self) -> None:
        now = self._clock()
        for digest, entry in tuple(self._keys.items()):
            if entry.expires_at <= now:
                del self._keys[digest]

    @staticmethod
    def _require_user(principal: Principal) -> None:
        # A signed-in session only: a guard API key must never mint or list its successors,
        # or a leaked key could outlive its own revocation.
        if not principal.authenticated or principal.auth_method != "google":
            raise IdentityError()

    def issue(self, principal: Principal, name: str) -> dict[str, str]:
        self._require_user(principal)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 64:
            raise ValueError("API key name must contain between 1 and 64 characters")
        if any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise ValueError("API key name must not contain control characters")
        with self._lock:
            self._prune()
            owners = {entry.owner for entry in self._keys.values()}
            owned = sum(entry.owner == principal.id for entry in self._keys.values())
            if (
                len(self._keys) >= self._max_keys
                or owned >= self._per_principal
                or (principal.id not in owners and len(owners) >= self._max_principals)
            ):
                raise KeyCapacityError()
            key = "pg_" + secrets.token_urlsafe(32)
            digest = hashlib.sha256(key.encode()).digest()
            now = self._clock()
            entry = _StoredKey(
                id="key_" + secrets.token_urlsafe(16),
                owner=principal.id,
                name=name.strip(),
                prefix=key[:11],
                created_at=datetime.fromtimestamp(now, UTC).isoformat(),
                expires_at=now + self._ttl,
                digest=digest,
            )
            self._keys[digest] = entry
            return {**entry.metadata(), "key": key}

    def list(self, principal: Principal) -> list[dict[str, str]]:
        self._require_user(principal)
        with self._lock:
            self._prune()
            return [
                entry.metadata() for entry in self._keys.values() if entry.owner == principal.id
            ]

    def revoke(self, principal: Principal, key_id: str) -> bool:
        self._require_user(principal)
        with self._lock:
            self._prune()
            for digest, entry in self._keys.items():
                if entry.owner == principal.id and entry.id == key_id:
                    del self._keys[digest]
                    return True
        return False

    def resolve(self, key: str) -> Principal | None:
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            return None
        digest = hashlib.sha256(key.encode()).digest()
        with self._lock:
            self._prune()
            entry = self._keys.get(digest)
            if entry is None:
                return None
            return Principal(entry.owner, True, "api_key")

    def clear(self) -> None:
        with self._lock:
            self._keys.clear()

    def purge_expired(self) -> None:
        """Forget expired verifiers even when no client accesses the store."""
        with self._lock:
            self._prune()
