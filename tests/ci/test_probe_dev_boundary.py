"""The boundary probe's forged-demo check asserts anonymous guest semantics (LAB-1521)."""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "probe_dev_boundary.py"
MODULE = runpy.run_path(str(SCRIPT))
main = MODULE["main"]
Reply = MODULE["Reply"]
GUEST = "__Host-pii-guard-guest=synthetic-guest-0001"


class StubServer:
    """A stubbed hosted deployment that answers every probe check the way a safe one does."""

    def __init__(self, *, sponsored: bool = True) -> None:
        self.sponsored = sponsored
        self.forged_account_authenticated = False
        self.reflect_identity = False
        self.issue_cookie = True
        self.calls: list[tuple[str, str, list[tuple[str, str]]]] = []

    def __call__(
        self, method: str, path: str, headers: list[tuple[str, str]], body: bytes | None
    ) -> Any:
        self.calls.append((method, path, headers))
        names = {key.lower() for key, _ in headers}
        if path == "/.auth/login/google":
            location = "https://login.example/?redirect_uri=https%3A%2F%2Fguard-dev.example%2Fcb"
            return Reply(302, [], location, b"")
        if path == "/v1/account":
            forged = "x-ms-client-principal" in names
            signed_in = forged and self.forged_account_authenticated
            account = {
                "authenticated": signed_in,
                "tier": "standard" if signed_in else "anonymous",
                "principal": {"id": "synthetic-forged"} if signed_in else None,
            }
            return Reply(200, [], "", json.dumps(account).encode())
        if path == "/v1/demo":
            origin = dict((key.lower(), value) for key, value in headers).get("origin", "")
            if (
                origin != "https://guard-dev.example"
                or len([k for k, _ in headers if k.lower() == "origin"]) != 1
            ):
                return Reply(403, [], "", b'{"error": {"code": "forbidden"}}')
            if not self.sponsored:
                return Reply(503, [], "", b'{"error": {"code": "sponsored_disabled"}}')
            demo = {
                key: "x"
                for key in ("sample_id", "language", "original", "masked", "answer", "restored")
            }
            demo |= {"entities": [{"type": "EMAIL"}], "session_id": "s_1", "request_id": "r_1"}
            if self.reflect_identity:
                demo["principal"] = "synthetic-forged@example.com"
            cookies = [f"{GUEST}; Path=/; Secure; HttpOnly"] if self.issue_cookie else []
            return Reply(200, cookies, "", json.dumps(demo).encode())
        return Reply(401, [], "", b'{"error": {"code": "unauthorized"}}')


def run(server: StubServer, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = main(["https://guard-dev.example"], send=server)
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    return code, next(line for line in lines if line.get("check") == "forged-demo")


def test_sponsored_guest_demo_passes_with_anonymous_follow_ups(
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = StubServer(sponsored=True)
    code, line = run(server, capsys)
    assert code == 0
    assert line["status"] == 200
    assert line["ok"] is True
    assert line["path"] == "guest"
    assert line["guest_cookie"] is True
    assert line["reflected"] is False
    assert line["account_anonymous"] == [True, True]
    follow_ups = [h for m, p, h in server.calls if p == "/v1/account" and ("Cookie", GUEST) in h]
    assert len(follow_ups) == 2
    assert follow_ups[0] == [("Cookie", GUEST)]
    assert ("X-MS-CLIENT-PRINCIPAL-ID", "synthetic-forged") in follow_ups[1]
    # Content-free output: no cookie value or demo text is printed.
    assert "synthetic-guest-0001" not in json.dumps(line)
    # Exactly one demo call spends (sponsored); the cross-origin one is refused up front.
    assert sum(p == "/v1/demo" for _, p, _ in server.calls) == 2


def test_unsponsored_refusal_passes_without_follow_ups(
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = StubServer(sponsored=False)
    code, line = run(server, capsys)
    assert code == 0
    assert line == {
        "check": "forged-demo",
        "status": 503,
        "authenticated": None,
        "error": "sponsored_disabled",
        "redirect_uri_host": None,
        "path": "refused",
        "ok": True,
    }
    assert not any(("Cookie", GUEST) in h for _, _, h in server.calls)


@pytest.mark.parametrize(
    ("flaw", "field", "value"),
    [
        ("forged_account_authenticated", "account_anonymous", [True, False]),
        ("reflect_identity", "reflected", True),
    ],
)
def test_forged_identity_leaks_fail(
    flaw: str, field: str, value: object, capsys: pytest.CaptureFixture[str]
) -> None:
    server = StubServer()
    setattr(server, flaw, True)
    code, line = run(server, capsys)
    assert code == 1
    assert line["ok"] is False
    assert line[field] == value


def test_guest_demo_without_guest_cookie_fails(capsys: pytest.CaptureFixture[str]) -> None:
    server = StubServer()
    server.issue_cookie = False
    code, line = run(server, capsys)
    assert code == 1
    assert line["guest_cookie"] is False
    assert line["account_anonymous"] == []
