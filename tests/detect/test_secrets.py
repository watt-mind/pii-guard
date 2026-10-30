"""SECRET rules: API keys, tokens, passwords and private keys (LAB-1257).

Every value is fake (ADR 0005). Provider-shaped samples are assembled at runtime from a
prefix and an obviously fake body (``FAKE``, ``EXAMPLE``, zeros), so this file holds no string
a secret scanner (gitleaks, GitHub push protection) would take for a real credential.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.pipeline import DetectionPipeline, resolve_spans
from pii_guard.detect.rules import RuleDetector
from pii_guard.detect.rules.secrets import (
    SUBTYPES,
    is_secret_key_name,
    looks_like_secret_value,
)
from pii_guard.policy import DEFAULT_POLICIES, Policy
from pii_guard.types import TEXT_ENTITY_TYPES, EntityType, Span

E = EntityType
ROOT = Path(__file__).resolve().parents[2]
ENV_FAKE = ROOT / "examples" / "coding-agents" / "mini-repo" / "env.fake"


BASIC = "ZmFrZT" + "pmYWtl"  # base64 of "fake:fake", split so no scanner reads a header


def fake(prefix: str, length: int, alphabet: str = "FAKE0EXAMPLE0") -> str:
    """``prefix`` + a fake body of ``length`` characters cycled from ``alphabet``."""
    body = (alphabet * (length // len(alphabet) + 1))[:length]
    return prefix + body


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector(cued_numbers=False)


def secrets_in(detector: RuleDetector, text: str, language: str = "en") -> list[tuple[str, str]]:
    spans = detector.detect(text, language)
    for span in spans:
        assert text[span.start : span.end] == span.text
    return [(s.subtype or "", s.text) for s in spans if s.entity_type is E.SECRET]


def values(detector: RuleDetector, text: str) -> list[str]:
    return [v for _, v in secrets_in(detector, text)]


# --- The type ------------------------------------------------------------------------------


def test_secret_is_a_masked_text_type() -> None:
    assert E("SECRET") is E.SECRET
    assert E.SECRET in TEXT_ENTITY_TYPES
    assert DEFAULT_POLICIES[E.SECRET] is Policy.MASK


def test_subtype_is_metadata_not_identity() -> None:
    a = Span(0, 4, E.SECRET, "abcd", 0.9, "rules", subtype="assignment")
    b = Span(0, 4, E.SECRET, "abcd", 0.9, "rules")
    assert a == b
    assert hash(a) == hash(b)
    assert a.to_public_dict()["subtype"] == "assignment"
    assert "subtype" not in b.to_public_dict()
    assert "abcd" not in repr(a)


def test_every_hit_has_a_known_subtype(detector: RuleDetector) -> None:
    text = ENV_FAKE.read_text(encoding="utf-8") + "\nAuthorization: Bearer " + fake("", 24)
    subtypes = {s for s, _ in secrets_in(detector, text)}
    assert subtypes
    assert subtypes <= set(SUBTYPES)


# --- The coding-agent example (examples/coding-agents/mini-repo/env.fake) -------------------


def test_env_fake_secrets_are_found(detector: RuleDetector) -> None:
    text = ENV_FAKE.read_text(encoding="utf-8")
    found = secrets_in(detector, text)
    assert sorted(v for _, v in found) == sorted(
        [
            "fake-payments-key-0000-0000-0000",
            "fake-token-0000-0000-0000-000000000000",
            "fake-password",
        ]
    )
    assert ("url_password", "fake-password") in found
    # The rest of the file is configuration, not secrets.
    others = [s for s in detector.detect(text, "en") if s.entity_type is not E.SECRET]
    assert [(s.entity_type, s.text) for s in others] == [(E.EMAIL, "support@example.com")]


def test_env_fake_matches_the_gold_file() -> None:
    import json

    gold = json.loads((ENV_FAKE.parents[1] / "gold.json").read_text(encoding="utf-8"))
    text = ENV_FAKE.read_text(encoding="utf-8")
    found = {s.text for s in RuleDetector(cued_numbers=False).detect(text, "en")}
    secrets = {"fake-payments-key-0000-0000-0000", "fake-token-0000-0000-0000-000000000000"}
    secrets.add("fake-password")
    assert secrets <= set(gold["rules"])  # must never reach the upstream
    assert secrets <= found
    assert "secrets" not in gold.get("known_gaps", {})


# --- 1. Provider key shapes -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "subtype"),
    [
        ("AKIA" + "IOSFODNN7EXAMPLE", "aws_access_key_id"),  # the AWS documentation example
        (fake("ASIA", 16, "FAKE0000EXAMPLE"), "aws_access_key_id"),
        (fake("ghp_", 36), "github_token"),
        (fake("gho_", 40), "github_token"),
        (fake("github_pat_", 60, "FAKE_0000_EXAMPLE_"), "github_token"),
        (fake("xoxb-", 30, "FAKE-0000-EXAMPLE-"), "slack_token"),
        (fake("xoxp-", 40, "0000-fake-"), "slack_token"),
        (fake("sk_" + "live_", 24), "stripe_key"),
        (fake("sk_" + "test_", 24), "stripe_key"),
        (fake("rk_" + "live_", 24), "stripe_key"),
        (fake("whsec_", 32), "stripe_key"),
        (fake("sk-", 48, "FAKE0example0"), "api_key"),
        (fake("sk-proj-", 48, "FAKE0example0"), "api_key"),
        (fake("sk-ant-api03-", 80, "FAKE0example0_"), "api_key"),
        (fake("AIza", 35, "FAKE0EXAMPLE0_-"), "google_api_key"),
        (
            "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiJmYWtlLXVzZXIifQ" + ".ZmFrZS1zaWduYXR1cmUtMDAw",
            "jwt",
        ),
    ],
)
def test_provider_shapes_are_found_anywhere(
    detector: RuleDetector, value: str, subtype: str
) -> None:
    for text in (
        value,
        f"the key {value} leaked in the log",
        f'{{"credential": "{value}"}}',
        f"export SOMETHING={value}",
    ):
        found = secrets_in(detector, text)
        assert found == [(subtype, value)] or (
            # an assignment to a secret-ish key may report the same value as an assignment
            len(found) == 1 and found[0][1] == value
        ), text


def test_private_key_block_is_masked_whole(detector: RuleDetector) -> None:
    begin = "-----BEGIN " + "RSA PRIVATE KEY-----"
    end = "-----END " + "RSA PRIVATE KEY-----"
    block = "\n".join([begin, fake("", 64), fake("", 64, "0000example"), end])
    text = f"cat id_rsa\n{block}\n$ "
    assert secrets_in(detector, text) == [("private_key", block)]
    openssh = block.replace("RSA PRIVATE", "OPENSSH PRIVATE")
    assert values(detector, openssh) == [openssh]


@pytest.mark.parametrize(
    "text",
    [
        "AKIA1234",  # too short
        "pip install scikit-learn; import sklearn",
        "sk-learn-compatible-estimator-wrapper",  # words, no digits
        "the pk_live_ prefix is a publishable key",
        "gh_pages branch and ghp_short",
        "xoxo, Jane",
        "-----BEGIN PUBLIC KEY-----\nMIIBIjAN\n-----END PUBLIC KEY-----",
        "eyJhbGciOi",  # half a JWT header
    ],
)
def test_provider_look_alikes_are_not_secrets(detector: RuleDetector, text: str) -> None:
    assert secrets_in(detector, text) == []


# --- 2. Credentials in URLs -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "DATABASE_URL=postgres://app:fake-password@localhost:5432/bakery",
            [("url_password", "fake-password")],
        ),
        (
            "redis://default:Zx9-fake-0000@cache.example.com:6379/0",
            [("url_password", "Zx9-fake-0000")],
        ),
        (
            "mysql://jane.placeholder:fake0pw@db.example.com/shop",
            [("url_user", "jane.placeholder"), ("url_password", "fake0pw")],
        ),
        ("https://x-access-token:FAKE0token0000@git.example.com/repo.git", None),
    ],
)
def test_url_credentials(
    detector: RuleDetector, text: str, expected: list[tuple[str, str]] | None
) -> None:
    found = secrets_in(detector, text)
    if expected is None:
        assert [v for _, v in found] == ["FAKE0token0000"]
    else:
        assert found == expected
    # The host is not an e-mail address.
    assert E.EMAIL not in {s.entity_type for s in detector.detect(text, "en")}


@pytest.mark.parametrize(
    "text",
    [
        "postgres://app:${DB_PASSWORD}@localhost/bakery",
        "postgres://app:<password>@localhost/bakery",
        "https://example.com/path?q=a:b@c",  # no scheme://user: before it
        "ssh://git@git.example.com/repo.git",  # a user name, no password
        "mailto:jane.placeholder@example.com",
    ],
)
def test_url_without_credentials(detector: RuleDetector, text: str) -> None:
    assert secrets_in(detector, text) == []


# --- 3. Assignments and Authorization headers -----------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("PAYMENTS_API_KEY=fake-payments-key-0000", "fake-payments-key-0000"),
        ("export MAIL_API_TOKEN='fake-token-0000-0000'", "fake-token-0000-0000"),
        ("PASSWORD=changeme", "changeme"),  # a weak password in a config is still one
        ("DB_PASSWD=fake0pass", "fake0pass"),
        ("PGPASSWORD=fake-pg-0000 psql -h localhost", "fake-pg-0000"),
        ("password: fake-yaml-pw-00", "fake-yaml-pw-00"),
        ("  client_secret: fake-client-secret-0000", "fake-client-secret-0000"),
        ("- token: fake-list-token-00", "fake-list-token-00"),
        ('"client_secret": "fake-json-secret-0000"', "fake-json-secret-0000"),
        ("{'refresh_token': 'fake-refresh-0000'}", "fake-refresh-0000"),
        ('SECRET_KEY = "django-insecure-fake-0000"', "django-insecure-fake-0000"),
        ('const apiKey = "fake-js-key-0000";', "fake-js-key-0000"),
        ('dbPassword := "fake-go-pw-0000"', "fake-go-pw-0000"),
        ("mycli --api-key=fake-cli-key-0000 --verbose", "fake-cli-key-0000"),
        ("GET /v1/items?access_token=fake0query0token&page=2", "fake0query0token"),
        ("ADMIN_PIN_PASSWORD=123456", "123456"),  # numbers count for password keys
        (
            "aws_secret_access_key = " + fake("", 40, "FAKE0example0/+"),
            fake("", 40, "FAKE0example0/+"),
        ),
        ("STRIPE_KEY=" + fake("", 24, "FAKE0example0"), fake("", 24, "FAKE0example0")),
        ("Authorization: Bearer fake-bearer-0000", "fake-bearer-0000"),
        (
            "curl -H 'Authorization: Basic " + BASIC + "' https://api.example.com",
            BASIC,
        ),
        ('{"Authorization": "Bearer fake-json-bearer-00"}', "fake-json-bearer-00"),
        ("headers = {'Authorization': f'token fake0gh0token0'}", "fake0gh0token0"),
        ("sent Bearer FAKE0bearer0token0000 to the API", "FAKE0bearer0token0000"),
    ],
)
def test_assignment_values_are_masked(detector: RuleDetector, text: str, value: str) -> None:
    assert values(detector, text) == [value]


@pytest.mark.parametrize(
    "text",
    [
        "TIMEOUT=30",
        "MAX_TOKENS=4096",
        "max_tokens: 1024",
        "PORT=5432",
        "APP_ENV=development",
        "password: str",
        "def login(user: str, password: str) -> bool:",
        "token: Optional[str] = None",
        "api_key = os.environ['API_KEY']",
        "api_key = settings.api_key",
        "token = token",
        "secret = get_secret()",
        "client(api_key=api_key, timeout=5)",
        "run(token=access_token)",
        "PASSWORD=",
        "PWD=/home/jane/project",
        "PASSWORD=****",
        "PASSWORD=xxxxxxxx",
        "API_KEY=<your API key>",
        "API_KEY=${API_KEY}",
        "API_KEY=$API_KEY",
        "password: ${{ secrets.DB_PASSWORD }}",
        "password: {{ vault_db_password }}",
        "token: true",
        "AUTH=none",
        '"auth": "bearer"',
        "auth_type: basic",
        'STORAGE_KEY = "pii-guard.theme"',  # a lookup name, not a credential
        'PLACEHOLDER_KEY = "pii-guard"',
        "cache_key = 'user:1234'",
        "primary_key: id",
        "public_key: fake-public-0000",
        "csrf_token: abc",
        'SECRET = "SECRET"',
        "path-key: 3.1.1",
        "this server requires PII_GUARD_API_TOKEN: send the header",
        "Remember: the password is changed every month.",
        "the bearer of this letter",
        "Authorization: Bearer <token>",
        "Authorization: Bearer $TOKEN",
        "PASSWORD=[[SECRET_ab12cd]]",
    ],
)
def test_code_and_config_that_holds_no_secret(detector: RuleDetector, text: str) -> None:
    assert secrets_in(detector, text) == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("API_KEY", True),
        ("api-key", True),
        ("apiKey", True),
        ("PAYMENTS_API_KEY", True),
        ("aws_secret_access_key", True),
        ("GITHUB_TOKEN", True),
        ("accessToken", True),
        ("client_secret", True),
        ("PASSWORD", True),
        ("PGPASSWORD", True),
        ("db_passwd", True),
        ("MYSQL_PWD", True),
        ("PWD", False),  # the shell's working directory
        ("OLDPWD", False),
        ("AUTH", True),
        ("STRIPE_KEY", True),
        ("key", False),
        ("pass", False),
        ("MAX_TOKENS", False),
        ("primary_key", False),
        ("sort_key", False),
        ("public_key", False),
        ("TIMEOUT", False),
        ("keyboard", False),
        ("tokenizer", False),
    ],
)
def test_secret_key_names(name: str, expected: bool) -> None:
    assert is_secret_key_name(name) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("changeme", True),
        ("fake-token-0000", True),
        ("abc", False),  # below the length floor
        ("0000", False),  # one character repeated: a mask
        ("aaaaaaaa", False),
        ("1234", False),  # a number is not a token ...
        ("true", False),
        ("${X}", False),
        ("os.environ", False),
        ("settings.api_key", False),
        ("get()", False),
    ],
)
def test_secret_values(value: str, expected: bool) -> None:
    assert looks_like_secret_value(value) is expected


def test_numeric_password() -> None:
    assert looks_like_secret_value("1234", password_key=True)


# --- Look-alikes in lockfiles and code: hashes, UUIDs, git SHAs -----------------------------


SHA256 = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
SHA1 = "a94a8fe5ccb19ba61c4c0873d391e987982fbbd3"
UUID = "123e4567-e89b-42d3-a456-426614174000"
INTEGRITY = "sha512-" + fake("", 86, "FAKE0example0/+") + "=="


@pytest.mark.parametrize(
    "text",
    [
        f'{{ url = "https://files.example.org/pkg-1.0.tar.gz", hash = "sha256:{SHA256}" }}',
        f"    resolution: {{integrity: {INTEGRITY}}}",
        f"      integrity: {INTEGRITY}",
        f"commit {SHA1}\nAuthor: Jane Placeholder <jane.placeholder@example.com>",
        f"git checkout {SHA1}",
        f"request_id={UUID}",
        f'"id": "{UUID}"',
        f"checksum: {SHA256}",
        "from pii_guard.detect.rules.secrets import RULES",
        "def find_api_key(text: str) -> str | None:",
        "SECRET_WORDS = frozenset({'token', 'secret'})",
    ],
)
def test_hashes_uuids_and_shas_are_not_secrets(detector: RuleDetector, text: str) -> None:
    assert secrets_in(detector, text) == []


@pytest.mark.parametrize("value", [SHA256, SHA1, UUID])
def test_hash_assigned_to_a_secret_key_is_masked(detector: RuleDetector, value: str) -> None:
    assert values(detector, f"WEBHOOK_SECRET={value}") == [value]


@pytest.mark.parametrize("path", ["uv.lock", "ui/pnpm-lock.yaml"])
def test_repository_lockfiles_hold_no_secret(detector: RuleDetector, path: str) -> None:
    file = ROOT / path
    if not file.exists():
        pytest.skip(f"{path} is not in this checkout")
    assert secrets_in(detector, file.read_text(encoding="utf-8")) == []


def test_mini_repo_code_holds_no_secret(detector: RuleDetector) -> None:
    for file in (ENV_FAKE.parent / "src").rglob("*.py"):
        assert secrets_in(detector, file.read_text(encoding="utf-8")) == [], file


# --- The eval fixtures (gate suite "secrets") ---------------------------------------------------


def test_committed_secret_fixtures_match_the_builder() -> None:
    import importlib.util

    from pii_guard.eval.fixtures import dump_document

    path = ROOT / "eval" / "fixtures" / "secrets" / "build_secrets.py"
    spec = importlib.util.spec_from_file_location("build_secrets", path)
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    for name, build in builder.OUTPUTS.items():
        expected = "\n".join(dump_document(d) for d in build()) + "\n"
        assert (path.parent / name).read_text(encoding="utf-8") == expected, (
            f"{name} is stale: run `uv run python eval/fixtures/secrets/build_secrets.py`"
        )


def test_secret_fixtures_are_found_exactly(detector: RuleDetector) -> None:
    from pii_guard.eval.fixtures import load_fixtures

    docs = load_fixtures(ROOT / "eval" / "fixtures" / "secrets" / "en-secrets.jsonl")
    assert len(docs) >= 15
    assert sum("hard-negative" in d.meta.get("tags", []) for d in docs) >= 5
    for doc in docs:
        gold = {(s.start, s.end, s.entity_type) for s in doc.spans}
        got = {(s.start, s.end, s.entity_type) for s in detector.detect(doc.text, doc.language)}
        assert got == gold, doc.id


# --- Exact offsets and quoted literals (LAB-1349) ----------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ('password=" Synth9!pass"', "Synth9!pass"),  # leading space: the tail leaked
        ('password="Synth9!pass "', "Synth9!pass"),
        ("password='\tSynth9!pass\t'", "Synth9!pass"),
        ('token: "  fake-token-0000-1111  "', "fake-token-0000-1111"),
        ('"client_secret": " fake-json-secret-0000"', "fake-json-secret-0000"),
        ('Authorization = " Bearer fake0bearer0token0000"', "fake0bearer0token0000"),
    ],
)
def test_padded_quoted_value_is_masked_exactly(
    detector: RuleDetector, text: str, value: str
) -> None:
    spans = [s for s in detector.detect(text, "en") if s.entity_type is E.SECRET]
    assert [s.text for s in spans] == [value]
    assert all(text[s.start : s.end] == s.text for s in spans)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ('password="Synth9![x]pass"', "Synth9![x]pass"),
        ("db_password = 'Synth(9)pass!'", "Synth(9)pass!"),
        ('"passphrase": "Synth9!(x)-pass"', "Synth9!(x)-pass"),
        ("MYSQL_PWD=`Synth[9]pw`", "Synth[9]pw"),
    ],
)
def test_bracketed_quoted_password_is_masked(detector: RuleDetector, text: str, value: str) -> None:
    assert values(detector, text) == [value]


@pytest.mark.parametrize(
    "text",
    [
        "password=Synth9![x]pass",  # unquoted: may be code (an index expression)
        'token="fake[0]token0000"',  # not a password key: brackets still mean code
        'password = "{password}"',  # a format field, not a value
        'password = "Synth{0}pass"',  # a positional field too
        'password = "%(password)s"',
        "password = os.environ['DB_PASSWORD']",
        'password = "${DB_PASSWORD}"',
        'password: "{{ secrets.DB_PASSWORD }}"',
        'password = "[[SECRET_ab12cd]]"',
    ],
)
def test_bracket_negatives_stay_unmasked(detector: RuleDetector, text: str) -> None:
    assert secrets_in(detector, text) == []


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ('password="Fake{0000}pw"', "Fake{0000}pw"),
        ("password='pre{fix}0000x'", "pre{fix}0000x"),
        ("db_password = 'pre{fix}0000x'", "pre{fix}0000x"),
        ('"passphrase": "Synth9-{bakery}-pass"', "Synth9-{bakery}-pass"),
        ("MYSQL_PWD=`{fake}0pw0000`", "{fake}0pw0000"),
        ('ADMIN_PASSWORD: "fake0pw{0000}"', "fake0pw{0000}"),
        ('password := "Fake{x}{0000}pw"', None),  # two fields: a template, see negatives
    ],
)
def test_literal_password_with_brace_group_is_masked(
    detector: RuleDetector, text: str, value: str | None
) -> None:
    """LAB-1383: a ``{word}`` group inside a literal password is not a format field."""
    assert values(detector, text) == ([value] if value else [])


@pytest.mark.parametrize(
    "value",
    [
        "{password}",
        "{0}",
        "{}",
        "%(pw)s",
        "pw-{db_password}",
        "{cfg.db.password}",
        "{creds[pw]}",
        "{secrets.token}",
        "Synth{0}pass",
        "pw{}",
        "{user}:{password}@{host}",
        "{prefix}-{suffix}",
        "x%(passwd)s",
    ],
)
def test_template_fields_after_password_key_stay_templates(value: str) -> None:
    assert not looks_like_secret_value(value, password_key=True, quoted=True)


@pytest.mark.parametrize("value", ["Fake{0000}pw", "pre{fix}0000x", "{fake}0pw0000", "a{bc}de"])
def test_brace_literal_is_a_password_value(value: str) -> None:
    assert looks_like_secret_value(value, password_key=True, quoted=True)
    # Unquoted or after a non-password key, braces still mean code.
    assert not looks_like_secret_value(value, password_key=True, quoted=False)
    assert not looks_like_secret_value(value, password_key=False, quoted=True)


_PAD = st.text(alphabet=" \t", max_size=3)
_BODY = st.text(alphabet="abcXYZ0189!#*+-_[]()~^", min_size=4, max_size=24)


@given(
    key=st.sampled_from(["password", "DB_PASSWORD", "client_secret", "API_TOKEN", "admin_pwd"]),
    sep=st.sampled_from(["=", ": ", " = ", ":="]),
    quote=st.sampled_from(['"', "'", "`"]),
    lead=_PAD,
    trail=_PAD,
    body=_BODY,
)
def test_secret_offsets_are_exact_after_strip(
    key: str, sep: str, quote: str, lead: str, trail: str, body: str
) -> None:
    """Every emitted SECRET span is the exact value: no padding inside, no tail outside."""
    value = "Synth9" + body
    text = f"{key}{sep}{quote}{lead}{value}{trail}{quote}\n"
    spans = [s for s in RuleDetector().detect(text, "en") if s.entity_type is E.SECRET]
    for span in spans:
        assert text[span.start : span.end] == span.text
        assert span.text and span.text == span.text.strip()
    password_key = key.casefold().startswith(("password", "db_password", "admin_pwd"))
    if password_key or not any(ch in value for ch in "()[]"):
        assert [s.text for s in spans] == [value]


# --- Through the pipeline ---------------------------------------------------------------------


def test_rules_secret_wins_and_keeps_its_subtype() -> None:
    text = "DATABASE_URL=postgres://app:fake-password@localhost:5432/bakery"
    spans = DetectionPipeline([RuleDetector(cued_numbers=False)]).detect(text, "en")
    assert [(s.entity_type, s.subtype, s.text) for s in spans] == [
        (E.SECRET, "url_password", "fake-password")
    ]


def test_secret_beats_an_overlapping_model_span() -> None:
    text = "MAIL_API_TOKEN=fake-token-0000-0000"
    start = text.index("fake")
    rules = Span(start, len(text), E.SECRET, text[start:], 0.85, "rules", subtype="assignment")
    model = Span(start, start + 10, E.PERSON, text[start : start + 10], 0.99, "ner")
    resolved = resolve_spans(text, [model, rules], detector_order=("rules", "ner"))
    assert [(s.entity_type, s.subtype, s.text) for s in resolved] == [
        (E.SECRET, "assignment", "fake-token-0000-0000")
    ]
