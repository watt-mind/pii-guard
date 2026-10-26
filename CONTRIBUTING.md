# Contributing to pii-guard

Thanks for helping. pii-guard is a privacy tool, so a few rules are stricter than in most
projects.

## Ground rules

1. **Never commit real personal data.** Not in tests, fixtures, docs, issues, screenshots or
   commit messages. Use the synthetic generator in `eval/`, or write obviously fictional data.
   If you found a bug on a real document, reproduce it with a synthetic one before filing.
2. **Fail closed.** Code paths that cannot finish masking must stop the request, not forward
   it.
3. **No raw values in logs or errors.** Log entity types, counts and placeholder ids.
4. **Measure detection changes.** If you touch detection, include the before/after scorecard
   from `uv run pii-guard eval` in the pull request.

## Development setup

The code scaffold is not in place yet. Once it is:

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Commits and pull requests

- Conventional commit messages: `feat(detect): add IBAN checksum rule`,
  `fix(gateway): split placeholders across stream chunks`.
- Keep pull requests focused on one change. Describe what changed, why, and how you verified
  it.
- Design changes that are hard to reverse get an ADR in `docs/decisions/`.

## Reporting a leak

A way to get personal data past the guard is a **security issue**. Do not open a public
issue; follow [SECURITY.md](SECURITY.md).
