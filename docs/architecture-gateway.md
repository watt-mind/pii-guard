# Using the gateway

pii-guard's gateway is a drop-in for any OpenAI-compatible client: point the client at
pii-guard instead of the provider. Every message is masked when it arrives, the masked request
is forwarded, and the answer (streamed or not) comes back with the real values restored. How it
is built: [architecture.md](architecture.md#gateway-the-proxy). Running and exposing it:
[operations.md](operations.md).

## Modes

| Mode | Detection | Model call per message | Use it for |
|---|---|---|---|
| `fast` (default) | rules + the in-process NER (rules only without a checkpoint) | none: local, nothing leaves the machine | production: the request path |
| `audit` | rules + NER + an LLM detector | one, to the detector endpoint (about 2 s, $2.5–3 per 1k messages) | a second opinion: sampled or offline quality checks, label generation, the benchmark upper bound |

Fast mode is the default (`PII_GUARD_GATEWAY_MODE`, code default `fast`); opt into audit per
request with `X-PII-Guard-Mode: audit`, or for the whole server with
`PII_GUARD_GATEWAY_MODE=audit`. Audit mode is not meant for production traffic: it sends every
message to the detector endpoint. Current numbers for both:
[benchmarks.md](benchmarks.md#smoke). Old mode names and the rename:
[operations.md](operations.md#modes).

## Run it

Fast mode needs no model key. The NER checkpoint is optional: without one, fast mode is rules
only ([models.md](models.md#ner-detector)).

```bash
uv sync --extra ner
export PII_GUARD_TENANT_KEY=$(openssl rand -hex 32)
export PII_GUARD_NER_MODEL=/path/to/your/ner-checkpoint      # optional
export PII_GUARD_UPSTREAM_BASE_URL=https://api.meta.ai/v1     # any OpenAI-compatible API
export PII_GUARD_UPSTREAM_API_KEY=$META_API_KEY
uv run pii-guard serve                                         # http://127.0.0.1:8787
```

Audit mode adds the LLM detector. The default endpoint and model are Muse Spark Open on
Baseten Model APIs (`https://inference.baseten.co/v1`, `meta-models/muse-spark-open-1026`), so
only the key and the reasoning effort are needed:

```bash
export PII_GUARD_LLM_DETECTOR_API_KEY=$BASETEN_API_KEY
export PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=low     # required: see docs/models.md
```

Muse Spark 1.3 on the Meta Model API works the same way (fictional text only): set
`PII_GUARD_LLM_DETECTOR_URL=https://api.meta.ai/v1`, `PII_GUARD_LLM_DETECTOR_MODEL=muse-spark-1.3`
and `PII_GUARD_LLM_DETECTOR_REASONING_EFFORT=minimal`. Which endpoint may see real data:
[models.md](models.md#baseten-model-apis-the-audit-mode-detector).

## From Python

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

## Headers

| Header | Direction | Meaning |
|---|---|---|
| `X-PII-Guard-Session` | both | The conversation. Omit it to start one; the response carries it. Same session = same placeholders, and history is not detected again. Unknown or expired → 404. |
| `X-PII-Guard-Mode` | both | Request: `fast` (rules + NER, no model call; the default) or `audit` (+ the LLM detector). The response carries the mode that ran. |
| `X-PII-Guard-Language` | request | Language of the conversation (default `PII_GUARD_DEFAULT_LANGUAGE`, `hu`). |
| `X-PII-Guard-Echo` | request | Opt-in, `masked`: also return what the model saw and said. Non-streamed: a `pii_guard` object (`masked_messages`, `masked_answer`) in the body. Streamed: a `pii_guard.masked_request` event first and a `pii_guard.masked_answer` event before `[DONE]`. Masked text only; for UIs that show the boundary (the demo's Chat screen). |
| `X-PII-Guard-Cache-Hits` / `-Misses`, `X-PII-Guard-Masked`, `X-PII-Guard-Unresolved` | response | Counts only: texts served from the detection cache, values masked, placeholders the model invented. |
| `X-PII-Guard-Request-Id` | response | The call's id in the traffic log; with `PII_GUARD_SERVER_TIMING=true` a `Server-Timing` header gives the per-stage latency ([operations.md](operations.md#timing)). |

## Failing closed

A detection error or timeout (`PII_GUARD_GATEWAY_DETECTION_TIMEOUT`, 30 s), a request field
or content part it can't mask (remote image URLs, audio, files, unknown keys), or a missing
tenant key or upstream return an error and nothing is forwarded. Inline images are masked with
SAM 3.1 and OCR, and refused when those aren't available. The full field table is in
[contracts.md](contracts.md). Further
settings (`PII_GUARD_GATEWAY_MODE`, `_UPSTREAM_TIMEOUT`, `_CACHE_SIZE`, `_CONCURRENCY`,
`_KEEP_TYPES`) are documented in `src/pii_guard/gateway/config.py`. Without
`PII_GUARD_UPSTREAM_API_KEY`, the client's own `Authorization` header is forwarded.
