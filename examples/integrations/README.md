# Application integrations

Follow [the integration guide](../../docs/integrations.md) for self-hosted and hosted project
URLs, credential setup, provider/model configuration, streaming and image limitations.

| Example | What it runs |
|---|---|
| `curl_chat.py` | Installed cURL; secret Authorization header supplied over stdin |
| `openai_chat.py` | OpenAI Python SDK Chat Completions; ordinary or streamed restored text |
| `make_synthetic_image.py` | Pillow only; creates a PNG in a fresh temporary directory and prints its path |

Both clients accept `--stream` and `--image <synthetic.png>`, and read `GUARD_BASE_URL`,
`GUARD_API_KEY`, `GUARD_MODEL` at runtime. Images require a provisioned self-hosted root
gateway and vision model. Hosted preview and project endpoints are text-only.

```bash
uv run --no-sync python examples/integrations/curl_chat.py
uv run --no-sync python examples/integrations/openai_chat.py --stream
```

All input data is synthetic. No provider call is made by generating the image. Client
commands make live calls to the configured guard; they are not offline demonstrations.
