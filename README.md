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

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). Only the skeleton exists so far: the API starts
and answers health checks; detection and masking endpoints are being built.

```bash
git clone https://github.com/watt-mind/pii-guard.git
cd pii-guard
uv sync
uv run pii-guard serve                  # http://127.0.0.1:8787
curl http://127.0.0.1:8787/healthz      # {"status":"ok","version":"0.1.0"}
```

Or with Docker: `docker compose up --build`. Configuration comes from environment variables;
see [.env.example](.env.example).

### Gateway quickstart

Point any OpenAI-compatible client at pii-guard instead of the provider. Every message is
masked when it arrives, the masked request is forwarded, and the answer (streamed or not) comes
back with the real values restored. Example with the Meta Model API as upstream and Muse Spark
as the LLM detector (**fictional data only** on hosted models, see
[docs/models.md](docs/models.md)):

```bash
export PII_GUARD_TENANT_KEY=$(openssl rand -hex 32)
export PII_GUARD_UPSTREAM_BASE_URL=https://api.meta.ai/v1
export PII_GUARD_UPSTREAM_API_KEY=$META_API_KEY
export PII_GUARD_LLM_DETECTOR_URL=https://api.meta.ai/v1      # strict mode's LLM detector
export PII_GUARD_LLM_DETECTOR_API_KEY=$META_API_KEY
export PII_GUARD_LLM_DETECTOR_MODEL=muse-spark-1.3
export PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=minimal
uv run pii-guard serve                                        # http://127.0.0.1:8787
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="unused")
messages = [
    {
        "role": "system",
        "content": "Values like [[PERSON_1a2b3c]] are the user's real data, "
        "masked for privacy. Use them verbatim.",
    },
    {
        "role": "user",
        "content": "I'm Jane Placeholder, jane.placeholder@example.net. "
        "Write one sentence inviting Teszt Elek to lunch.",
    },
]
raw = client.chat.completions.with_raw_response.create(model="muse-spark-1.3", messages=messages)
print(raw.parse().choices[0].message.content)  # real names; the model only saw placeholders
session = raw.headers["X-PII-Guard-Session"]  # send it back on the next turn

stream = client.chat.completions.create(
    model="muse-spark-1.3",
    stream=True,
    messages=[
        *messages,
        {"role": "assistant", "content": raw.parse().choices[0].message.content},
        {"role": "user", "content": "Now mention Minta Mária too."},
    ],
    extra_headers={"X-PII-Guard-Session": session},
)
for chunk in stream:
    if chunk.choices:
        print(chunk.choices[0].delta.content or "", end="")
```

| Header | Direction | Meaning |
|---|---|---|
| `X-PII-Guard-Session` | both | The conversation. Omit it to start one; the response carries it. Same session = same placeholders, and history is not detected again. Unknown or expired → 404. |
| `X-PII-Guard-Mode` | request | `strict` (rules + LLM detector, the default) or `fast` (rules only, no model call). |
| `X-PII-Guard-Language` | request | Language of the conversation (default `PII_GUARD_DEFAULT_LANGUAGE`, `hu`). |
| `X-PII-Guard-Cache-Hits` / `-Misses`, `X-PII-Guard-Masked`, `X-PII-Guard-Unresolved` | response | Counts only: texts served from the detection cache, values masked, placeholders the model invented. |

Fails closed: a detection error or timeout (`PII_GUARD_GATEWAY_DETECTION_TIMEOUT`, 30 s), image
or audio parts, or a missing tenant key or upstream return an error and nothing is forwarded.
Further settings (`PII_GUARD_GATEWAY_MODE`, `_UPSTREAM_TIMEOUT`, `_CACHE_SIZE`, `_CONCURRENCY`,
`_KEEP_TYPES`) are documented in `src/pii_guard/gateway/config.py`. Without
`PII_GUARD_UPSTREAM_API_KEY`, the client's own `Authorization` header is forwarded.

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
