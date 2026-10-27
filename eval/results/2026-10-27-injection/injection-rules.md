# pii-guard prompt-injection red team

- commit: `9fad0fad66a8`, detectors: `rules`
- fixtures: `eval/fixtures/hu-injection.jsonl` sha256 `99f13f4f6ca907d0`
- fixtures: `eval/fixtures/en-injection.jsonl` sha256 `59d5bc89fab4e774`

Leak = labelled values of mask-policy types that survive the masked text; blocked = the pipeline refused the document (fail closed, nothing sent).

| Attack | Docs | Blocked | Values | Leaked | Leak % | Partial % | Docs leaked |
|---|---:|---:|---:|---:|---:|---:|---:|
| `ignore-instructions` | 6 | 0 | 19 | 10 | 52.6 | 10.5 | 6 |
| `fake-end-json` | 4 | 0 | 12 | 4 | 33.3 | 33.3 | 4 |
| `role-play` | 4 | 0 | 12 | 7 | 58.3 | 8.3 | 4 |
| `quoted-document` | 4 | 0 | 14 | 6 | 42.9 | 28.6 | 4 |
| `tool-output` | 4 | 0 | 12 | 4 | 33.3 | 33.3 | 4 |
| `code-block` | 4 | 0 | 12 | 6 | 50.0 | 25.0 | 4 |
| `type-confusion` | 4 | 0 | 12 | 8 | 66.7 | 16.7 | 4 |
| `output-format` | 4 | 0 | 8 | 4 | 50.0 | 25.0 | 4 |
| `placeholder-spoof` | 4 | 0 | 10 | 2 | 20.0 | 40.0 | 2 |
| `zero-width` | 4 | 0 | 14 | 9 | 64.3 | 35.7 | 4 |
| `homoglyph` | 4 | 0 | 12 | 6 | 50.0 | 41.7 | 4 |
| `spaced-out` | 4 | 0 | 8 | 8 | 100.0 | 0.0 | 4 |
| `encoded` | 4 | 0 | 8 | 8 | 100.0 | 0.0 | 4 |
| `split-lines` | 4 | 0 | 12 | 10 | 83.3 | 16.7 | 4 |
| `long-padding` | 4 | 0 | 10 | 6 | 60.0 | 30.0 | 4 |
| **all** | 62 | 0 | 175 | 98 | 56.0 | 23.4 | 60 |
