# Connect an application to pii-guard

> [!NOTE]
> **Related guides:** For the REST & OpenAI-compatible route reference, authentication tokens,
> and error code catalog, see [api.md](api.md). For gateway operating modes (`fast` vs. `audit`),
> session selection headers, and outbound re-check mechanics, see
> [architecture-gateway.md](architecture-gateway.md).

Point the application's OpenAI-compatible client at the **guard**. The guard detects and
masks the request, calls the configured upstream, and restores known placeholders in the
answer, including streamed text. Detection coverage depends on the installed detectors and
policy; this is not a guarantee that every personal value will be detected.

The runnable [examples](../examples/integrations/) use only a fictional email on the reserved
`example.com` domain. They call Chat Completions; they do not require OpenAI as the upstream.

## Choose the URL and credential

| Integration | `GUARD_BASE_URL` | `GUARD_API_KEY` | `GUARD_MODEL` |
|---|---|---|---|
| Self-hosted root gateway | `http://127.0.0.1:8787/v1` | The server's `PII_GUARD_API_TOKEN`, if enabled; otherwise unset | A model accepted by the configured upstream |
| Hosted project endpoint | `https://guard.watt-mind.com/e/<endpoint-id>/v1` (copy it from Connect) | The guard endpoint key shown once when issued | The endpoint's pinned model, or any provider model for a pass-through BYOK endpoint (see `GET <base>/models`) |
| Self-hosted project endpoint | `http://127.0.0.1:8787/e/<endpoint-id>/v1` | That endpoint's guard key | The endpoint's pinned model, or any provider model for a pass-through BYOK endpoint (see `GET <base>/models`) |

The Connect page in the console and `pii-guard connect curl|python --print` print ready-made
blocks with the URL and model filled in. `GUARD_API_KEY` here corresponds to
`PII_GUARD_ENDPOINT_KEY` in those blocks. Client-specific setups (Codex, pi, OpenCode, Muse
Code) are in [the harness guides](integrations/README.md).

The URL ends in `/v1`, not `/chat/completions`: the SDK appends the route. An endpoint key is
different from the upstream provider key and cannot manage projects, inspect the vault or
call another endpoint. Use the endpoint URL and key together. Hosted management requires the
signed-in owner; a Google login cookie is not a substitute for the endpoint key in this client.

For a self-hosted root gateway, configure `PII_GUARD_UPSTREAM_BASE_URL` and
`PII_GUARD_UPSTREAM_API_KEY` **on the guard server**, and provision a stable private
`PII_GUARD_TENANT_KEY` (at least 16 bytes, hex encoded). See
[server setup](operations.md) and [.env.example](../.env.example). Start it with
`uv run --no-sync pii-guard serve` after installing dependencies. No application-side model
name changes the server's upstream destination. The upstream model is independent of the
detector: fast mode uses rules and installed local NER; audit adds the configured LLM detector,
which receives original text. See [the privacy boundary](privacy-model.md#trust-boundary).

For a project endpoint, sign in to the guard, create/select a project and policy version,
configure a provider, model and provider credential, then issue an endpoint key. The endpoint
pins the provider, policy version, language and mode, and a model unless it is a pass-through
BYOK endpoint (see [Endpoint model: pinned or pass-through](contracts.md#projects-policies-and-endpoints)).
Matching the pinned settings is required; caller overrides are refused. Hosted policy mode is `fast`. `sponsored` uses the deployment's
allowlisted Meta model and available allocation; a BYOK endpoint uses its stored provider
credential. Responses support still depends on the selected provider's native `/responses`
route. See [projects](projects.md) and the [API contract](contracts.md#projects-policies-and-endpoints).

## Run cURL or the OpenAI Python SDK

From a repository checkout, install the locked environment once:

```bash
uv sync --locked
```

Set the non-secret values in your client shell. For the root gateway, for example:

```bash
export GUARD_BASE_URL='http://127.0.0.1:8787/v1'
export GUARD_MODEL='your-upstream-model'
```

For hosted use, replace those values with your copied endpoint URL and its pinned model (or
your own model for a pass-through BYOK endpoint). Supply `GUARD_API_KEY` from your secret manager or read it without terminal echo
(Bash or Zsh):

```bash
read -r -s GUARD_API_KEY
export GUARD_API_KEY
printf '\n'
```

Leave it unset for a root gateway with authentication disabled. Keep that server on trusted
loopback or behind authentication. Do not put a provider key in `GUARD_API_KEY`.

```bash
# cURL: ordinary JSON response, then raw server-sent events (SSE)
uv run --no-sync python examples/integrations/curl_chat.py
uv run --no-sync python examples/integrations/curl_chat.py --stream

# SDK: prints restored answer text, then restored text deltas
uv run --no-sync python examples/integrations/openai_chat.py
uv run --no-sync python examples/integrations/openai_chat.py --stream
```

The cURL example runs the installed `curl` executable with `--config -`, feeding the URL,
JSON body and Authorization header through stdin. The key never appears in cURL's process
arguments or a temporary config file. `-q` disables user `.curlrc` settings, and the example
does not enable verbose HTTP traces. The SDK reads the same environment at runtime and does
not print exception bodies. Both commands print the restored application response; treat
output from real requests as sensitive rather than saving it as a debug log.

For a small application, the SDK configuration is:

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.environ["GUARD_BASE_URL"],
    api_key=os.environ["GUARD_API_KEY"],
    max_retries=0,
    timeout=180.0,
)
```

The runnable example also handles unauthenticated loopback use, where the SDK requires a
non-secret dummy key. It disables automatic SDK retries because retrying a submitted
request can repeat provider work or spend, and requests at most 256 completion tokens.

The SDK's `--stream` loop handles role-only and usage-only events, prints only content
deltas, closes the stream and exits nonzero on an SDK/guard error or missing finish event.
An answer already printed before a stream error is incomplete. cURL displays **raw SSE**:
events are separated by blank lines, `data:` JSON chunks can have no text, and
`data: [DONE]` terminates a successful stream. An HTTP 200 alone does not prove success:
check for an `error` event and a final `[DONE]`; cURL's exit status cannot detect an error
inside an otherwise successful HTTP stream. Do not concatenate arbitrary byte chunks as JSON
or try to restore placeholders yourself.

## Images: self-hosted root gateway only

**Project endpoints (hosted and self-hosted) reject image parts in chat requests.** Hosted
signed-in owners can mask images with native `/v1/mask/image` in the console; see
[hosted.md](hosted.md). These examples use the
self-hosted root `/v1` URL for images, without an `/e/<endpoint-id>` prefix or a nondefault
`X-PII-Guard-Project` selection.

Provision OCR and segmentation before using the live image path; see
[image setup](models.md#local-segmentation) and the
[image contract](contracts.md#post-v1maskimage). A text-only installation is insufficient.
The default `hybrid` segmenter sends the **unmasked image** to the configured SAM service
for signature detection before OCR masking; SAM is inside that trusted processing boundary.
`sam-api` also sends original pixels remotely. Do not describe either mode as local-only.
Server-level `PII_GUARD_SEGMENTER=local` without a project policy has no signature detector
and fails closed under the default signature policy; changing signatures to `keep` means they
stay visible. Project policies with `visual_detection: local` use the on-device signature
detector instead (see [contracts](contracts.md#projects-policies-and-endpoints)). OCR is required by default;
do not disable that check to make an image request pass.

Generate a fictional image locally, then use a vision-capable upstream model:

```bash
GUARD_IMAGE_PATH="$(uv run --no-sync python examples/integrations/make_synthetic_image.py)"
export GUARD_BASE_URL='http://127.0.0.1:8787/v1'
export GUARD_MODEL='your-vision-model'
uv run --no-sync python examples/integrations/curl_chat.py --image "$GUARD_IMAGE_PATH"
uv run --no-sync python examples/integrations/openai_chat.py --image "$GUARD_IMAGE_PATH" --stream
```

These send `messages[].content` with a text part and an `image_url` part containing an inline
`data:image/png;base64,...` URL. The guard accepts inline PNG/JPEG, masks the pixels and sends
a masked PNG to the downstream model. With the default `labels` rendering it also appends
a masked transcript and document summary in the same vault session. **Only returned answer
text is restored; original image pixels are not restored.** Remote image URLs are refused;
the guard does not fetch them.

For an application that only needs a masked image, the native `POST /v1/mask/image` route
accepts raw PNG/JPEG bytes or a JSON base64 body and returns a masked PNG in its JSON `image`
field. It does not call the downstream chat model. That route is separate from the OpenAI
vision message schema and is unavailable to endpoint keys. A deterministic recorded-OCR
image demonstration is also available in [which parties have an ID](../examples/README.md).
Its default mock deliberately leaves faces and signatures visible; it demonstrates identity
matching and restored answer text, not complete visual privacy. Native image rendering can
also use `opaque` (solid boxes, no transcript/summary) instead of `labels` (placeholder labels,
masked transcript and summary); neither is reversible pixel restoration.

## Errors and sessions

Authentication failures, model/policy mismatches and missing OCR/detectors are refusals.
Fix their configuration; never retry the original request directly against the provider to
work around the guard. Relevant stable error codes are listed in the
[API contract](contracts.md#errors-1). The examples never fall back to another URL.

The gateway manages a vault session automatically. Applications that need distinct
conversation lifetimes can use `/s/<session-id>/v1` for a self-hosted root gateway, or reuse
the returned `X-PII-Guard-Session` header within the same authorized namespace. An unknown
explicit session header is refused; the path form creates a missing session. Mappings live
in process memory and expire; project configuration persistence does not persist them. See
[gateway sessions](contracts.md#gateway-sessions-implemented).
