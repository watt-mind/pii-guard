"""Build the secrets eval fixtures: ``en-secrets.jsonl`` (LAB-1257, gate suite ``secrets``).

What coding agents send upstream: ``.env`` files, compose and CI configs, ``curl`` commands,
settings modules, credential files, logs and stack traces with API keys, tokens, passwords and
private keys in them, plus look-alikes that must stay readable (lockfile hashes, git SHAs,
UUIDs, code that only *names* a key).

Every secret is **fake** (ADR 0005), built here from a prefix and an obviously fake body
(``FAKE``, ``EXAMPLE``, zeros); the AWS key id is the one from AWS's own documentation. Only
shapes that cannot pass a provider's validity check are written to the JSONL (GitHub tokens
carry a checksum these fail; the Slack sample has no numeric team id), so GitHub push
protection has nothing to block; gitleaks skips ``eval/fixtures/`` (``.gitleaks.toml``).
Stripe and Google samples live in ``tests/detect/test_secrets.py`` only, assembled at runtime.

Shapes added for LAB-1362 (bugs fixed in LAB-1349 and LAB-1350 that this suite could not see):
whitespace padding inside quotes (the mask must cover the stripped value exactly, not the
padding plus a truncated value), brackets inside a quoted password, two tokens that differ
only in letter case (each needs its own placeholder to round-trip), and ``{...}`` template
fields after a password key as a hard negative.

Known miss, not in the JSONL: a *literal* quoted password that contains a ``{word}`` group
(``password="Fake{0000}pw"``) is read as a format field and left unmasked, the same as
``"{password}"``. The suite's leak limit is 0.0 (``eval/gates.json``), so the case is
documented here and tracked as a follow-up (LAB-1383) rather than added as a failing document.

Regenerate after editing (a test fails if the committed file is stale)::

    uv run python eval/fixtures/secrets/build_secrets.py
"""

from __future__ import annotations

from pathlib import Path

from pii_guard.eval import Document, from_markup, label, write_fixtures

HERE = Path(__file__).resolve().parent


def fake(prefix: str, length: int, alphabet: str = "FAKE0EXAMPLE0") -> str:
    body = (alphabet * (length // len(alphabet) + 1))[:length]
    return prefix + body


def s(value: str) -> str:
    return label("SECRET", value)


def email(value: str) -> str:
    return label("EMAIL", value)


AWS_KEY_ID = "AKIA" + "IOSFODNN7EXAMPLE"
AWS_SECRET = fake("", 40, "FAKE0example0/+")
GH_TOKEN = fake("ghp_", 36)
SLACK_TOKEN = fake("xoxb-", 32, "FAKE-EXAMPLE-0000-")
OPENAI_STYLE = fake("sk-proj-", 48, "FAKE0example0")
JWT = "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiJmYWtlLXVzZXIifQ" + ".ZmFrZS1zaWduYXR1cmUtMDAw"
PEM = "\n".join(
    [
        "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
        fake("", 64, "FAKE0example0+/"),
        fake("", 64, "0000example0FAKE"),
        fake("", 24, "EXAMPLE0"),
        "-----END " + "OPENSSH PRIVATE KEY-----",
    ]
)
SHA256 = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
SHA256_B = "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"
SHA1 = "a94a8fe5ccb19ba61c4c0873d391e987982fbbd3"
SHA1_B = "0beec7b5ea3f0fdbc95d0dd47f3c5bc275da8a33"
UUID = "123e4567-e89b-42d3-a456-426614174000"
# Two GitHub-style tokens that differ only in letter case: distinct credentials (LAB-1350).
GH_TOKEN_UPPER = fake("ghp_", 36, "FAKE0EXAMPLE0AbCd")
GH_TOKEN_LOWER = "ghp_" + GH_TOKEN_UPPER[4:].swapcase()
INTEGRITY = "sha512-" + fake("", 86, "FAKE0example0/+") + "=="


def documents() -> list[Document]:
    docs: list[tuple[str, str, str]] = [
        (
            "env-file",
            "dotenv",
            "# .env for local development\n"
            "APP_ENV=development\n"
            "PORT=8080\n"
            "TIMEOUT=30\n"
            f"SUPPORT_EMAIL={email('support@example.com')}\n"
            f"PAYMENTS_API_KEY={s('fake-payments-key-0000-0000-0000')}\n"
            f"MAIL_API_TOKEN={s('fake-token-0000-0000-0000-000000000000')}\n"
            f"DATABASE_URL=postgres://app:{s('fake-password')}@localhost:5432/bakery\n"
            f"OPENAI_API_KEY={s(OPENAI_STYLE)}\n",
        ),
        (
            "compose",
            "yaml",
            "services:\n"
            "  db:\n"
            "    image: postgres:16\n"
            "    environment:\n"
            f"      - POSTGRES_PASSWORD={s('fake-compose-pw-0000')}\n"
            "      - POSTGRES_DB=bakery\n"
            "  app:\n"
            "    environment:\n"
            f"      REDIS_URL: redis://default:{s('Zx9-fake-0000')}@cache:6379/0\n"
            "      MAX_TOKENS: 4096\n"
            "      DB_PASSWORD: ${DB_PASSWORD}\n",
        ),
        (
            "ci-workflow",
            "yaml",
            "jobs:\n"
            "  deploy:\n"
            "    steps:\n"
            "      - run: ./deploy.sh\n"
            "        env:\n"
            "          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}\n"
            "          password: ${{ secrets.DB_PASSWORD }}\n"
            f"          SLACK_BOT_TOKEN: {s(SLACK_TOKEN)}\n",
        ),
        (
            "curl-bearer",
            "shell",
            "Why does this return 401?\n\n"
            "curl -s https://api.example.com/v1/orders \\\n"
            f"  -H 'Authorization: Bearer {s('fake-bearer-0000-EXAMPLE')}' \\\n"
            "  -H 'Content-Type: application/json'\n",
        ),
        (
            "json-config",
            "json",
            "{\n"
            '  "auth": "bearer",\n'
            '  "client_id": "bakery-web",\n'
            f'  "client_secret": "{s("fake-json-secret-0000")}",\n'
            f'  "apiKey": "{s("fake-js-key-0000-EXAMPLE")}",\n'
            '  "timeoutMs": 5000\n'
            "}\n",
        ),
        (
            "python-settings",
            "code",
            "import os\n\n"
            f'SECRET_KEY = "{s("django-insecure-fake-0000-example")}"\n'
            'STRIPE_KEY = os.environ["STRIPE_KEY"]\n'
            'STORAGE_KEY = "bakery.theme"\n'
            "DEBUG = True\n\n\n"
            "def client(api_key: str, token: str | None = None) -> Client:\n"
            "    return Client(api_key=api_key, token=token, timeout=30)\n",
        ),
        (
            "aws-credentials",
            "ini",
            "[default]\n"
            f"aws_access_key_id = {s(AWS_KEY_ID)}\n"
            f"aws_secret_access_key = {s(AWS_SECRET)}\n"
            "region = eu-central-1\n",
        ),
        (
            "ci-log-token",
            "log",
            "Run git push origin main\n"
            f"remote: Invalid username or token {s(GH_TOKEN)} for 'https://github.com/'\n"
            "fatal: Authentication failed\n",
        ),
        (
            "private-key",
            "chat",
            "My ssh key stopped working, here is the file:\n\n"
            f"{s(PEM)}\n\n"
            "What is wrong with it?\n",
        ),
        (
            "jwt-log",
            "log",
            "2026-10-27T10:12:03Z WARN auth: rejected session "
            f"token={s(JWT)} reason=expired\n"
            f"2026-10-27T10:12:04Z INFO request_id={UUID} status=401\n",
        ),
        (
            "url-credentials",
            "log",
            "sqlalchemy.exc.OperationalError: could not connect to "
            f"mysql://{s('jane.placeholder')}:{s('fake0pw0000')}@db.example.com:3306/shop\n"
            "postgres://app:${PGPASSWORD}@localhost/bakery worked before the upgrade.\n",
        ),
        (
            "padded-quotes",
            "code",
            "# whitespace inside the quotes is not part of the credential\n"
            f'password = " {s("Fake0pw0padded")}"\n'
            f"DB_PASSWORD: '  {s('fake-pw-0000-pad')}  '\n"
            f'token: "  {s("fake-token-0000-EXAMPLE")}  "\n'
            f'"client_secret": "{s("fake-json-secret-pad-0000")}   "\n',
        ),
        (
            "bracketed-password",
            "code",
            "conn = connect(\n"
            '    host="db.example.com",\n'
            '    user="bakery",\n'
            f'    password="{s("Fake0[pw]0000")}",\n'
            ")\n"
            f"passwd = '{s('fake(0000)example')}'\n"
            f'MYSQL_PWD="{s("[Fake]0pw0000")}"\n',
        ),
        (
            "case-differing-tokens",
            "chat",
            "We rotated the CI token, the old and the new one look almost the same:\n"
            f"old: {s(GH_TOKEN_UPPER)}\n"
            f"new: {s(GH_TOKEN_LOWER)}\n"
            f"API_TOKEN={s('fake-token-AbCdEf-0000')}\n"
            f"BACKUP_API_TOKEN={s('fake-token-aBcDeF-0000')}\n",
        ),
        (
            "neg-template-fields",
            "code",
            'DSN = "postgres://{user}:{password}@{host}/bakery"\n'
            'password = "{password}"\n'
            'password = f"{db_password}"\n'
            "passwd = '%(passwd)s'\n"
            "password = creds[0]\n"
            "pwd = cfg[password]\n"
            "pwd: /home/bakery/app\n",
        ),
        (
            "neg-uv-lock",
            "lockfile",
            '[[package]]\nname = "pii-guard-example"\nversion = "0.1.0"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
            'sdist = { url = "https://files.example.org/example-0.1.0.tar.gz", '
            f'hash = "sha256:{SHA256}" }}\n'
            "wheels = [\n"
            '    { url = "https://files.example.org/example-0.1.0-py3-none-any.whl", '
            f'hash = "sha256:{SHA256_B}" }},\n'
            "]\n",
        ),
        (
            "neg-pnpm-lock",
            "lockfile",
            "packages:\n\n"
            "  path-key@3.1.1:\n"
            f"    resolution: {{integrity: {INTEGRITY}}}\n"
            "    engines: {node: '>=8'}\n\n"
            "  js-tokens@4.0.0:\n"
            f"    resolution: {{integrity: {INTEGRITY}}}\n",
        ),
        (
            "neg-git-log",
            "log",
            f"commit {SHA1}\n"
            f"Author: Bakery CI <{email('ci@example.com')}>\n"
            "Date:   Tue Oct 27 10:00:00 2026 +0100\n\n"
            "    fix(auth): read API_KEY from the environment\n\n"
            f"commit {SHA1_B}\n",
        ),
        (
            "neg-code",
            "code",
            "SECRET_WORDS = frozenset({'token', 'secret'})\n\n\n"
            "def find_api_key(text: str) -> str | None:\n"
            "    cache_key = f'user:{uid}'\n"
            "    password: str = form['password']\n"
            "    token = token or settings.api_token\n"
            "    headers = {'Authorization': f'Bearer {token}'}\n"
            "    return lookup(primary_key=cache_key)\n",
        ),
        (
            "neg-docs",
            "docs",
            "Set `PII_GUARD_API_TOKEN` in `.env` and send 'Authorization: Bearer <token>'.\n"
            "API_KEY=<your API key>\n"
            "PASSWORD=****\n"
            "The bearer of this letter may collect the parcel.\n",
        ),
        (
            "hash-as-secret",
            "dotenv",
            f"WEBHOOK_SECRET={s(SHA256)}\nSESSION_TOKEN={s(UUID)}\nBUILD_SHA={SHA1}\n",
        ),
    ]
    return [
        from_markup(
            f"en-secrets-{name}",
            text,
            language="en",
            meta={
                "kind": kind,
                "tags": ["secrets"] + (["hard-negative"] if name.startswith("neg-") else []),
            },
        )
        for name, kind, text in docs
    ]


OUTPUTS = {"en-secrets.jsonl": documents}


def main() -> None:
    for name, build in OUTPUTS.items():
        write_fixtures(HERE / name, build())


if __name__ == "__main__":
    main()
