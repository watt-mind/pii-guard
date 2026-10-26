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

## How to report

Please report privately, not in a public issue. Once the GitHub repository is published, use
GitHub's **private vulnerability reporting** ("Report a vulnerability" on the Security tab).

Include a **synthetic** reproduction. Do not send real personal data, even to demonstrate the
issue.

## Supported versions

The project is pre-alpha. Only the latest commit on `main` is supported.
