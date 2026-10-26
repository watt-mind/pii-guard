# pii-guard

**An open-source privacy firewall for AI agents.** pii-guard sits between your application and
an LLM. It finds personal data in text, documents and images, replaces it with reversible
pseudonyms before anything leaves your infrastructure, and puts the real values back into the
model's answer, including streamed answers.

> **Status: pre-alpha.** Being built for the Meta Global AI Developer Hackathon
> (October 26 – November 4, 2026). Nothing here is production-ready yet. See the
> [roadmap](docs/roadmap.md).

## Why

Teams that handle sensitive data (law firms, clinics, HR, finance) want to use cloud LLMs but
cannot send client data to them. Existing PII tools mostly:

- handle **text only**, and miss what is in scans and photos (ID cards, signatures, faces);
- **redact one way**, so the model's answer refers to `[REDACTED]` instead of the real person;
- are tuned for **English**, and do poorly on morphologically rich languages like Hungarian;
- publish **no quality numbers**, so you cannot tell how much leaks.

pii-guard aims to fix all four, starting with Hungarian and extending to other EU languages.

## What it does (planned)

| Capability | Description |
|---|---|
| **Detect** | Layered detection: checksum-validated rules, a multilingual NER model, and a small fine-tuned open-weights LLM that catches what the others miss. |
| **See** | OCR word boxes plus image segmentation (SAM 3.1) to mask personal data in scans and photos: text, faces, signatures, ID photos. |
| **Pseudonymize** | Stable, keyed, non-guessable placeholders (`[[PERSON_7f3a]]`), consistent within a session, unlinkable across tenants. |
| **Re-identify** | Restores real values in the model's response, including streaming responses and inflected forms (e.g. Hungarian suffixes). |
| **Gateway** | Drop-in proxy for OpenAI-compatible APIs. Fails closed: if masking fails, nothing is sent. |
| **Measure** | A synthetic, labelled benchmark with precision, recall and end-to-end leak rate, published with every release. |

## How it works

```
 your app / agent ──► pii-guard ──────────────────────────────► LLM provider
                      │ 1. extract text + layout (docs, images)       │
                      │ 2. detect PII (rules → NER → LLM)             │
                      │ 3. pseudonymize (keyed, reversible)           │
                      │ 4. mask image regions                         │
                      │◄──────────────── response (streamed) ─────────┘
                      │ 5. re-identify placeholders
 your app / agent ◄───┘
```

The mapping between real values and placeholders **never leaves pii-guard**. Details in
[docs/architecture.md](docs/architecture.md) and [docs/privacy-model.md](docs/privacy-model.md).

## Documentation

Start at [docs/INDEX.md](docs/INDEX.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The one rule that matters most: **never commit real
personal data**, not even in a test. All fixtures are synthetic.

## Security

Found a way to make personal data leak past the guard? That is a security bug. Please report
it privately; see [SECURITY.md](SECURITY.md).

## License

[Apache-2.0](LICENSE)
