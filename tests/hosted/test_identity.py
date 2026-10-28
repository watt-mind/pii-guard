"""Synthetic identities only: trust, isolation, forgery, expiry and concurrent caps."""

from __future__ import annotations

import base64
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from pii_guard.hosted.identity import (
    ApiKeyStore,
    GuestIdentity,
    IdentityError,
    KeyCapacityError,
    Principal,
    easy_auth_principal,
)

MASTER = bytes(range(32))
SUBJECT = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"
USER = Principal("u_synthetic-one", True, "google")
OTHER = Principal("u_synthetic-two", True, "google")


def encoded(value: object) -> str:
    return base64.b64encode(json.dumps(value).encode()).decode()


def identity(subject: str = "synthetic-subject-one") -> dict[str, object]:
    return {"auth_typ": "google", "claims": [{"typ": SUBJECT, "val": subject}]}


def test_principal_requires_trust_and_stable_subject() -> None:
    header = encoded(identity())
    with pytest.raises(IdentityError):
        easy_auth_principal(header, master_key=MASTER, trusted=False)
    first = easy_auth_principal(header, master_key=MASTER, trusted=True)
    second = easy_auth_principal(header, master_key=MASTER, trusted=True)
    other = easy_auth_principal(encoded(identity("synthetic-two")), master_key=MASTER, trusted=True)
    assert first == second and first != other
    assert first.authenticated and first.auth_method == "google"
    assert "synthetic" not in repr(first)
    assert first != easy_auth_principal(header, master_key=b"s" * 32, trusted=True)


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"auth_typ": "facebook", "claims": [{"typ": "sub", "val": "synthetic"}]},
        {"auth_typ": "google", "claims": []},
        {"auth_typ": "google", "claims": "wrong"},
        {"auth_typ": "google", "claims": ["wrong"]},
        {"auth_typ": "google", "claims": [{"typ": "email", "val": "fake@example.com"}]},
        {"auth_typ": "google", "claims": [{"typ": "sub", "val": ""}]},
        {"auth_typ": "google", "claims": [{"typ": "sub", "val": " synthetic"}]},
        {"auth_typ": "google", "claims": [{"typ": "sub", "val": "synthetic\x00"}]},
        {"auth_typ": "google", "claims": [{"typ": "sub", "val": 123}]},
        {"auth_typ": "google", "claims": [{"typ": "sub", "val": "s" * 2049}]},
        {"auth_typ": "google", "claims": [{"typ": "t" * 513, "val": "s"}]},
        {"auth_typ": "google", "claims": [{"typ": "sub", "val": "s"}] * 129},
        {"auth_typ": "google", "claims": [{"typ": "sub", "val": "same"}] * 2},
        {
            "auth_typ": "google",
            "claims": [{"typ": "sub", "val": "one"}, {"typ": SUBJECT, "val": "two"}],
        },
    ],
)
def test_invalid_identity_does_not_echo_claims(value: object) -> None:
    with pytest.raises(IdentityError) as error:
        easy_auth_principal(encoded(value), master_key=MASTER, trusted=True)
    assert str(error.value) == "a valid hosted identity is required"


@pytest.mark.parametrize("header", ["", "!", "x" * 16385, "e30=\n", "//8="])
def test_malformed_headers(header: str) -> None:
    with pytest.raises(IdentityError):
        easy_auth_principal(header, master_key=MASTER, trusted=True)


def test_duplicate_json_keys_refused_and_equal_aliases_allowed() -> None:
    raw = b'{"auth_typ":"google","auth_typ":"google","claims":[]}'
    with pytest.raises(IdentityError):
        easy_auth_principal(base64.b64encode(raw).decode(), master_key=MASTER, trusted=True)
    value = {
        "auth_typ": "google",
        "claims": [{"typ": "sub", "val": "same"}, {"typ": SUBJECT, "val": "same"}],
    }
    assert easy_auth_principal(encoded(value), master_key=MASTER, trusted=True).authenticated


def test_guest_forgery_expiry_and_cookie_attributes() -> None:
    now = [1000.0]
    guests = GuestIdentity(MASTER, ttl_seconds=100, clock=lambda: now[0])
    principal, cookie = guests.resolve(None)
    assert cookie is not None
    assert guests.resolve(cookie) == (principal, None)
    assert not principal.authenticated
    other, _ = guests.resolve(None)
    assert principal != other
    header = guests.cookie_header(cookie)
    for part in ["__Host-", "Secure", "HttpOnly", "SameSite=Strict", "Path=/", "Max-Age=100"]:
        assert part in header
    assert "Domain=" not in header
    assert guests.resolve(cookie[:-1] + ("0" if cookie[-1] != "0" else "1"))[0] != principal
    assert guests.resolve(cookie.rsplit(".", 1)[0] + "." + "é" * 64)[0] != principal
    assert guests.resolve(".".join(["n" * 43, "9" * 100, "a" * 64]))[0] != principal
    assert guests.resolve(cookie + "x" * 300)[0] != principal
    now[0] = 1100
    assert guests.resolve(cookie)[0] != principal
    with pytest.raises(ValueError):
        guests.cookie_header("synthetic\r\nInjected: invalid")


def test_invalid_constructor_limits() -> None:
    with pytest.raises(ValueError):
        GuestIdentity(b"short")
    with pytest.raises(ValueError):
        GuestIdentity(MASTER, ttl_seconds=0)
    with pytest.raises(ValueError):
        ApiKeyStore(max_keys=0)


def test_key_is_returned_once_owner_scoped_revocable_and_hashed() -> None:
    keys = ApiKeyStore()
    issued = keys.issue(USER, "Synthetic developer key")
    assert issued["key"].startswith("pg_")
    assert keys.resolve(issued["key"]) == Principal(USER.id, True, "api_key")
    metadata = keys.list(USER)
    assert metadata == [{name: value for name, value in issued.items() if name != "key"}]
    assert keys.list(OTHER) == []
    assert not keys.revoke(OTHER, issued["id"])
    assert issued["key"] not in repr(keys._keys)
    assert keys.revoke(USER, issued["id"])
    assert keys.resolve(issued["key"]) is None
    assert not keys.revoke(USER, issued["id"])
    assert keys.resolve("synthetic-invalid") is None
    assert keys.resolve("pg_" + "x" * 43) is None


def test_key_expiry_capacity_and_clear() -> None:
    now = [1000.0]
    keys = ApiKeyStore(ttl_seconds=10, max_keys=1, clock=lambda: now[0])
    issued = keys.issue(USER, "One")
    with pytest.raises(KeyCapacityError):
        keys.issue(OTHER, "Two")
    assert keys.resolve(issued["key"]) is not None
    now[0] += 10
    assert keys.resolve(issued["key"]) is None
    assert keys.list(USER) == []
    keys.issue(OTHER, "Two")
    keys.clear()
    assert keys.list(OTHER) == []


def test_owner_capacity_and_guest_refusal() -> None:
    keys = ApiKeyStore(max_keys_per_principal=1, max_principals=1)
    keys.issue(USER, "One")
    with pytest.raises(KeyCapacityError):
        keys.issue(USER, "Two")
    with pytest.raises(KeyCapacityError):
        keys.issue(OTHER, "Two")
    guest = Principal("g_synthetic", False, "guest")
    with pytest.raises(IdentityError):
        keys.issue(guest, "Guest")
    with pytest.raises(IdentityError):
        keys.list(guest)
    with pytest.raises(IdentityError):
        keys.revoke(guest, "whatever")


@pytest.mark.parametrize("name", ["", " ", "x" * 65, "line\nbreak", "control\x7f"])
def test_key_name_validation(name: str) -> None:
    with pytest.raises(ValueError):
        ApiKeyStore().issue(USER, name)


def test_key_capacity_is_atomic() -> None:
    keys = ApiKeyStore(max_keys_per_principal=2)

    def issue(_: int) -> bool:
        try:
            keys.issue(USER, "Concurrent synthetic key")
        except KeyCapacityError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(issue, range(40))) == 2
    assert len(keys.list(USER)) == 2
