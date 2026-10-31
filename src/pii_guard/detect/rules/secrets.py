"""Language-independent secret rules: API keys, tokens, passwords and private keys (``SECRET``).

Coding agents send ``.env`` files, configs, shell history and logs upstream; an API key in that
traffic is the first leak a developer looks for. Three kinds of rule, each reporting a
``SECRET`` hit with a subtype (``Span.subtype``, e.g. ``"github_token"``):

1. **Provider key shapes**: prefixes and lengths that only credentials have (AWS access key
   ids, GitHub, Slack, Stripe, OpenAI/Anthropic-style ``sk-`` keys, Google API keys, JWTs,
   PEM private-key blocks). They are found anywhere, with or without a key name.
2. **Credentials in URLs**: ``scheme://user:password@host``. The password is masked, and the
   user name too unless it is a generic service account (``app``, ``postgres``, ``root``).
3. **Assignments to a secret-ish key**: ``API_KEY=...``, ``password: ...``,
   ``"client_secret": "..."``, ``--token=...`` and ``Authorization: Bearer ...``. Only the value
   is masked. The key name decides (``*_KEY``, ``*_TOKEN``, ``*_SECRET``, ``PASSWORD``,
   ``PASSWD``, ``PWD``, ``AUTH``, ``BEARER``, camelCase too), so a hash, UUID or git SHA is
   masked only when it is assigned to such a key.

Over-masking is the risk in code, so an assignment value must look like a literal, not code:
references (``${DB_PASS}``, ``os.environ[...]``, ``{{ secrets.X }}``), calls, attribute paths,
type annotations (``password: str``), booleans and numbers, empty values, masks (``****``)
and doc placeholders in angle brackets are left alone. ``PASSWORD=changeme`` is still masked:
a weak password in a config file is still a password. A bare value after a spaced ``=``
(``token = token``) is code, not configuration, and needs quotes to count.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterator

from pii_guard.detect.rules._base import Rule, _Hit
from pii_guard.types import EntityType

__all__ = ["RULES", "SUBTYPES", "is_secret_key_name", "looks_like_secret_value"]

_SECRET = EntityType.SECRET

#: Every subtype a ``SECRET`` span can carry (``docs/contracts.md``).
SUBTYPES: tuple[str, ...] = (
    "aws_access_key_id",
    "github_token",
    "slack_token",
    "stripe_key",
    "api_key",
    "google_api_key",
    "jwt",
    "private_key",
    "url_password",
    "url_user",
    "bearer_token",
    "assignment",
)

# --- 1. Provider key shapes ---------------------------------------------------------------

# Not inside a longer token on either side.
_B = r"(?<![A-Za-z0-9_+/-])"
_E = r"(?![A-Za-z0-9_+/=-])"

_PROVIDERS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    ("aws_access_key_id", re.compile(_B + r"(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}" + _E), 0.95),
    ("github_token", re.compile(_B + r"gh[pousr]_[A-Za-z0-9]{36,255}" + _E), 0.97),
    ("github_token", re.compile(_B + r"github_pat_[A-Za-z0-9_]{22,255}" + _E), 0.97),
    ("slack_token", re.compile(_B + r"xox[abposr]-[A-Za-z0-9-]{10,250}" + _E), 0.95),
    (
        "stripe_key",
        re.compile(_B + r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,247}" + _E),
        0.97,
    ),
    ("stripe_key", re.compile(_B + r"whsec_[A-Za-z0-9]{20,247}" + _E), 0.95),
    # OpenAI (sk-, sk-proj-, sk-svcacct-) and Anthropic (sk-ant-api03-...) style keys.
    ("api_key", re.compile(_B + r"sk-(?:[a-z]{2,10}-)*[A-Za-z0-9_-]{20,250}" + _E), 0.9),
    ("google_api_key", re.compile(_B + r"AIza[0-9A-Za-z_-]{35}" + _E), 0.95),
    (
        "jwt",
        re.compile(_B + r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}" + _E),
        0.95,
    ),
)

_PEM_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"
    r"[\s\S]{16,16384}?"
    r"-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"
)


def _has_letter_and_digit(value: str) -> bool:
    return any(c.isdigit() for c in value) and any(c.isalpha() for c in value)


def _find_provider_keys(text: str) -> Iterator[_Hit]:
    for subtype, pattern, score in _PROVIDERS:
        for m in pattern.finditer(text):
            # "sk-learn-compatible-estimator-module": words, not a key.
            if subtype == "api_key" and not _has_letter_and_digit(m.group()[3:]):
                continue
            yield _Hit(m.start(), m.end(), _SECRET, score, subtype)
    for m in _PEM_RE.finditer(text):
        yield _Hit(m.start(), m.end(), _SECRET, 0.99, "private_key")


# --- 2. Credentials in URLs ---------------------------------------------------------------

_URL_CRED_RE = re.compile(
    r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{1,30}://"
    r"(?P<user>[^\s:/?#@\[\]\"'`<>]{1,128}):(?P<password>[^\s/?#@\"'`<>]{1,256})@"
    r"(?=[A-Za-z0-9\[])"
)

#: Service accounts that identify no one; the password next to them is still masked.
_GENERIC_USERS = frozenset(
    {
        "admin",
        "administrator",
        "anonymous",
        "app",
        "application",
        "default",
        "dev",
        "developer",
        "elastic",
        "guest",
        "mongo",
        "mongodb",
        "mysql",
        "oauth2",
        "postgres",
        "rabbitmq",
        "redis",
        "root",
        "service",
        "sa",
        "test",
        "user",
        "username",
        "x-access-token",
        "x-oauth-basic",
    }
)


def _find_url_credentials(text: str) -> Iterator[_Hit]:
    for m in _URL_CRED_RE.finditer(text):
        password = m.group("password")
        if _is_reference_or_placeholder(password):
            continue
        yield _Hit(m.start("password"), m.end("password"), _SECRET, 0.9, "url_password")
        user = m.group("user")
        if user.casefold() not in _GENERIC_USERS and not _is_reference_or_placeholder(user):
            yield _Hit(m.start("user"), m.end("user"), _SECRET, 0.85, "url_user")


# --- 3. Assignments to a secret-ish key ---------------------------------------------------

# The last word of a key name that makes its value a secret.
_SECRET_WORDS = frozenset(
    {
        "apikey",
        "auth",
        "bearer",
        "credential",
        "credentials",
        "passphrase",
        "passwd",
        "password",
        "secret",
        "token",
    }
)
# "key" and "pass" alone are too common in code (dict keys, ``pass``): only with a qualifier.
_QUALIFIED_WORDS = frozenset({"key", "pass"})
# Qualifiers that make "*_key" (or "*_token") a structural name, not a credential.
_NOT_SECRET_QUALIFIERS = frozenset(
    {
        "cache",
        "composite",
        "dict",
        "foreign",
        "hot",
        "idempotency",
        "index",
        "lookup",
        "map",
        "next",
        "page",
        "partition",
        "primary",
        "public",
        "publishable",
        "range",
        "row",
        "shortcut",
        "sort",
        "unique",
        "csrf",
        "max",
        "min",
        "num",
        "old",
        "total",
    }
)

# A one-word key ending in one of these is still secret-ish (``PGPASSWORD``, ``authtoken``).
_RUN_ON_ENDINGS = ("password", "passwd", "secret", "token")

_KEY_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def _key_strength(name: str) -> int:
    """2: the key names a credential (``API_KEY``, ``dbPassword``, ``token``); 1: a qualified
    ``*_KEY`` / ``*_PASS`` that may be one (``STRIPE_KEY``) or a lookup name (``STORAGE_KEY``);
    0: not secret-ish."""
    words = [w.casefold() for w in _KEY_WORD_RE.findall(name)]
    if not words:
        return 0
    last = words[-1]
    if len(words) >= 2 and words[-2] + last in _SECRET_WORDS:  # "api_key", "api-key"
        return 2
    if len(words) == 1 and last.endswith(_RUN_ON_ENDINGS):  # "PGPASSWORD", "authtoken"
        return 2
    if last == "pwd":  # "MYSQL_PWD"; "PWD" alone (and "OLDPWD") is the working directory
        return 2 if len(words) >= 2 and words[-2] not in _NOT_SECRET_QUALIFIERS else 0
    if last in _SECRET_WORDS:
        return 2 if len(words) < 2 or words[-2] not in _NOT_SECRET_QUALIFIERS else 0
    if last in _QUALIFIED_WORDS:
        return 1 if len(words) >= 2 and words[-2] not in _NOT_SECRET_QUALIFIERS else 0
    return 0


def is_secret_key_name(name: str) -> bool:
    """True if a value assigned to ``name`` may be a credential (``API_KEY``, ``dbPassword``)."""
    return _key_strength(name) > 0


# A key name: an identifier with ``_``, ``.`` or ``-`` inside, optionally quoted (JSON, dicts)
# or a CLI flag (``--api-key``). The separator: ``=``, ``:``, ``:=``, ``=>``.
_ASSIGN_RE = re.compile(
    r"(?P<lead>(?<![\w.$-])(?:--?)?)"
    r"(?P<q>[\"']?)(?P<key>[A-Za-z_][A-Za-z0-9_.-]{0,80})(?P=q)"
    r"(?P<sep>[ \t]*(?::=|=>|=|:)[ \t]*)"
    r"(?:(?P<qv>[\"'`])(?P<qvalue>[^\"'`\r\n]{1,512})(?P=qv)"
    r"|(?P<value>[^\s\"'`,;&|]{1,512}))"
)

_TYPE_WORDS = frozenset(
    {
        "any",
        "bool",
        "boolean",
        "bytes",
        "false",
        "float",
        "int",
        "nil",
        "none",
        "null",
        "number",
        "object",
        "off",
        "on",
        "optional",
        "required",
        "secretstr",
        "str",
        "string",
        "true",
        "undefined",
        "unknown",
        "yes",
        "no",
        # authentication schemes and modes, not credentials ("auth": "bearer")
        "apikey",
        "api_key",
        "basic",
        "bearer",
        "digest",
        "header",
        "hmac",
        "jwt",
        "oauth",
        "oauth2",
        "password",
        "query",
        "token",
    }
)

_REFERENCE_RE = re.compile(
    r"^(?:\$\{?[A-Za-z_]|\$\(|%\(|\{\{|\{%|<|\[\[[A-Z_]+_[0-9a-f]+\]\]$"
    r"|(?:os\.|process\.|env[.(\[:]|getenv|secrets\.|vault:|op://|arn:aws:secretsmanager))",
    re.IGNORECASE,
)
_ATTRIBUTE_PATH_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")
_MIN_LENGTH = 4
# Shannon entropy (bits per character) below which a value is a mask or filler: "xxxx",
# "0000", "****". Low on purpose: "changeme" (2.75) is still a password.
_MIN_ENTROPY = 1.5


def _entropy(value: str) -> float:
    counts = Counter(value)
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _is_reference_or_placeholder(value: str) -> bool:
    return bool(_REFERENCE_RE.search(value)) or len(set(value)) <= 1 or "..." in value


# A format or template field inside a string literal: ``"{password}"``, ``"%(pw)s"``.
_FORMAT_FIELD_RE = re.compile(r"\{(?P<name>[\w.\[\]]*)\}|%\(\w+\)[a-z]")
# ``{}``, ``{0}``, ``{12}``: an idiomatic positional ``str.format`` field. ``{0000}`` is not.
_POSITIONAL_FIELD_RE = re.compile(r"(?:0|[1-9]\d?)?")
_FIELD_NAME_PART_RE = re.compile(r"[^.\[\]]+")
_SHORT_PASSWORD_NAMES = frozenset({"pw", "pwd", "pass", "passwd", "passphrase"})


def _names_secret(field: str) -> bool:
    """``{db_password}``, ``{cfg.token}``, ``{creds[pw]}``: a field that names a credential."""
    return any(
        part.casefold() in _SHORT_PASSWORD_NAMES or _key_strength(part) > 0
        for part in _FIELD_NAME_PART_RE.findall(field)
    )


def _is_template(value: str) -> bool:
    """True if a quoted literal is a format template, not a password with braces in it.

    A template when the whole value is one field (``"{password}"``, ``"%(pw)s"``), it has a
    ``%(x)s`` or positional (``{}``, ``{0}``) field, two or more fields
    (``"{user}:{password}@{host}"``), or a field that names a credential (``"pw-{db_password}"``).
    ``"Fake{0000}pw"`` and ``"pre{fix}0000x"`` are literal passwords (LAB-1383).
    """
    fields = list(_FORMAT_FIELD_RE.finditer(value))
    if not fields:
        return False
    if len(fields) >= 2 or fields[0].group(0) == value:
        return True
    name = fields[0].group("name")
    if name is None:  # ``%(x)s``
        return True
    return bool(_POSITIONAL_FIELD_RE.fullmatch(name)) or _names_secret(name)


def looks_like_secret_value(
    value: str, *, password_key: bool = False, quoted: bool = False
) -> bool:
    """True if ``value``, assigned to a secret-ish key, is a literal credential.

    Numbers count only for password keys (a numeric PIN); a token is never ``30``.
    Brackets mark code (``get()``, ``env[...]``), except in a quoted literal assigned to a
    password key: ``password="Synth9![x]pass"`` is a password with punctuation in it, and
    so is ``"Fake{0000}pw"``. A real template (``"{pw}"``, ``"{user}:{password}@{host}"``) is
    not.
    """
    if len(value) < _MIN_LENGTH or value.casefold() in _TYPE_WORDS:
        return False
    if _is_reference_or_placeholder(value) or _entropy(value) < _MIN_ENTROPY:
        return False
    if quoted and password_key:
        if _is_template(value):
            return False
    elif any(ch in value for ch in "()[]{}"):
        return False
    if _ATTRIBUTE_PATH_RE.match(value):
        return False
    # A token or key always has letters; "3.1.1" or "4096" after "*_key" is a version or count.
    return password_key or any(ch.isalpha() for ch in value)


def _credential_shaped(value: str) -> bool:
    """For a weak key name (``*_KEY``): long, with letters and digits, like a generated key."""
    return len(value) >= 16 and _has_letter_and_digit(value) and _entropy(value) >= 3.0


def _extract_assignment_value(
    text: str, m: re.Match[str], key: str, last: str, *, quoted: bool
) -> tuple[str, int, int] | None:
    if quoted:
        value, start = m.group("qvalue"), m.start("qvalue")
        value_end = m.end("qvalue")
        # Bearer inside a quoted header value: the token is the secret, not the scheme.
        scheme = re.match(r"(?i)\s*(?:bearer|basic|token)\s+", value)
        if scheme:
            value, start = value[scheme.end() :], start + scheme.end()
        return value, start, value_end
    value, start = m.group("value"), m.start("value")
    value_end = m.end("value")
    sep = m.group("sep")
    if m.group("q"):
        return None  # JSON / dict: a quoted key takes a quoted literal.
    spaced = sep.strip() == "=" and sep != sep.strip()
    if spaced and _IDENTIFIER_RE.match(value):
        return None  # ``token = token``: code, not configuration.
    if sep.strip() == ":" and not _at_line_start(text, m.start()):
        return None  # "requires API_TOKEN: send ..." is prose; YAML keys start a line.
    folded = value.casefold()
    if _IDENTIFIER_RE.match(value) and (
        folded in {key.casefold(), last} or folded.endswith("_" + last)
    ):
        return None  # ``api_key=api_key``, ``token=access_token``: a keyword argument.
    if folded in {"bearer", "basic", "token"}:
        return None  # handled by the header rule
    return value, start, value_end


def _find_assignments(text: str) -> Iterator[_Hit]:
    for m in _ASSIGN_RE.finditer(text):
        key = m.group("key")
        strength = _key_strength(key)
        if not strength:
            continue
        words = [w.casefold() for w in _KEY_WORD_RE.findall(key)]
        last = words[-1]
        password_key = last.endswith(("password", "passwd", "pwd", "pass", "passphrase"))
        quoted = m.group("qvalue") is not None
        extracted = _extract_assignment_value(text, m, key, last, quoted=quoted)
        if extracted is None:
            continue
        value, start, value_end = extracted
        # Strip padding from both ends and move ``start`` past the leading part, so the span
        # is exactly the value: ``" Synth9!pass"`` must not mask the space and leak the tail.
        stripped = value.lstrip()
        start += len(value) - len(stripped)
        value = stripped.rstrip()
        if not value or not looks_like_secret_value(
            value, password_key=password_key, quoted=quoted
        ):
            continue
        if value.casefold() == key.casefold():
            continue  # ``SECRET = "SECRET"``: an enum member
        if strength == 1 and not _credential_shaped(value):
            continue  # ``STORAGE_KEY = "theme"``: a lookup name
        end = start + len(value)
        if end > value_end:
            continue
        yield _Hit(start, end, _SECRET, 0.85, "assignment")


_LINE_LEAD_RE = re.compile(r"(?:^|\n)[ \t]*(?:-[ \t]+|export[ \t]+)?[\"']?$")


def _at_line_start(text: str, pos: int) -> bool:
    """Only indentation, a YAML list dash or ``export`` stands between the line start and pos."""
    return _LINE_LEAD_RE.search(text, max(0, pos - 120), pos) is not None


# ``Authorization: Bearer <token>``, ``-H 'Authorization: Basic <b64>'``, ``Bearer <token>``.
_BEARER_RE = re.compile(
    r"(?i:(?P<auth>authorization[\"']?[ \t]*[:=][ \t]*(?:[fbr]?[\"'])?)?"
    r"\b(?P<scheme>bearer|basic|token))"
    r"[ \t]+"
    r"(?P<token>[A-Za-z0-9._~+/-]{8,4096}=*)(?![A-Za-z0-9._~+/=-])"
)


def _find_bearer(text: str) -> Iterator[_Hit]:
    for m in _BEARER_RE.finditer(text):
        token = m.group("token")
        if _is_reference_or_placeholder(token) or _entropy(token) < _MIN_ENTROPY:
            continue
        # Without the header name, "Bearer" in prose ("the bearer instrument") needs a token
        # that looks like one: long, mixed letters and digits.
        if m.group("auth") is None and not (
            m.group("scheme").casefold() == "bearer"
            and len(token) >= 16
            and _has_letter_and_digit(token)
        ):
            continue
        yield _Hit(m.start("token"), m.end("token"), _SECRET, 0.9, "bearer_token")


#: Run for every text, like :data:`pii_guard.detect.rules.common.RULES`.
RULES: tuple[Rule, ...] = (
    _find_provider_keys,
    _find_url_credentials,
    _find_assignments,
    _find_bearer,
)
