# Security policy

## What counts as a security issue

For pii-guard, the most important class of vulnerability is a **leak**: any input that
causes personal data to reach the upstream LLM provider unmasked, or to appear in logs,
metrics, traces or error messages. Examples:

- a formatting, encoding or language trick that makes a detector miss a value it should catch;
- a streaming edge case that sends an unmasked chunk upstream;
- an error path that forwards the request instead of failing closed;
- placeholders that can be reversed or linked without the tenant key;
- image regions that are visually masked but still recoverable (metadata, layers, OCR text).

Ordinary false negatives found by the evaluation set are tracked as normal issues. A
**systematic** bypass is a security issue.

## Deployment: no authentication by default

pii-guard has **no authentication unless `PII_GUARD_API_TOKEN` is set**. Anyone who can reach
it can unmask placeholders, read the traffic log and use the gateway, which spends the
configured `PII_GUARD_UPSTREAM_API_KEY`: that key is shared by every caller. Run it on loopback
(the default) or behind an authenticating proxy, and publish a container's port on
`127.0.0.1` only. It answers only `localhost`, `127.0.0.1`, `[::1]`, `PII_GUARD_HOST` and
`PII_GUARD_ALLOWED_HOSTS` as `Host` (a DNS-rebinding guard), and the `full` traffic log only
serves loopback connections. Details: [docs/operations.md](docs/operations.md#exposure-and-authentication).

The **vault inspector** (`/v1/vault/sessions*`, the console's Vault screen) is on by default
in `masked` mode: anyone who can reach the API sees which sessions exist, where they came from,
their placeholders, entity types, counts and a redacted hint of each value (a word's first
letter and length, a number's last two digits), never an original or a session id. With
`PII_GUARD_VAULT_INSPECT=full` it can also return **every original value the vault holds**,
their inflected forms and the session id (a bearer handle for `/v1/unmask`): as sensitive as
the `full` traffic log, and guarded the same way (loopback bind and loopback connections only,
the token when set, the host check), with every reveal logged. Set it to `off` where nobody
needs it.

Values live in memory only: in the vault until their session is deleted or its TTL ends, and
for a short while in Python's bounded `re` compile cache (at most 512 recent patterns, cleared
by `pii_guard.detect.llm.clear_alignment_caches()` or a restart). A detector cache that keeps a
value after its request, unbounded or past session deletion, is a security issue. Details:
[docs/operations.md](docs/operations.md#values-held-in-memory-outside-the-vault).

Reports about an open deployment that ignored this are not vulnerabilities; a way around the
token, the host check, the loopback-only `full` log or vault inspector, or a value in a
`masked` inspector response is.

## How to report

Please report privately, not in a public issue. Once the GitHub repository is published, use
GitHub's **private vulnerability reporting** ("Report a vulnerability" on the Security tab).

Include a **synthetic** reproduction. Do not send real personal data, even to demonstrate the
issue.

## Supported versions

The project is pre-alpha. Only the latest commit on `main` is supported.
