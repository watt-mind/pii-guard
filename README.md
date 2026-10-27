<p align="center">
  <img src="docs/assets/banner.svg" alt="pii-guard: a privacy firewall for AI agents. You send 'Írj Minta Máriának holnap', the model sees 'Írj [[PERSON_7f3a]]nak holnap', you get back the real name." width="100%">
</p>

<p align="center"><b>Mask personal data before it reaches the LLM, and put it back in the answer. On your machine, in milliseconds.</b></p>

<p align="center">
  <a href="https://github.com/watt-mind/pii-guard/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/watt-mind/pii-guard/actions/workflows/ci.yml/badge.svg?branch=develop"></a>
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-blue"></a>
  <a href="docs/decisions/0005-synthetic-data-only.md"><img alt="Fictional data only" src="https://img.shields.io/badge/data-fictional%20only-b6f36b"></a>
</p>

pii-guard sits between your application and any OpenAI-compatible LLM. It finds personal data in
text and images, swaps it for reversible placeholders before anything leaves your
infrastructure, and restores the real values in the model's answer, even while it streams.

```text
"Kérem, írjon Próba Zsuzsannának a zsuzsa.proba@example.com címre."      ← what you send
"Kérem, írjon [[PERSON_525263]] a [[EMAIL_20c291]] címre."                ← what the model sees
"Megírtam a levelet Próba Zsuzsannának."                                  ← what you get back
```

<p align="center">
  <img src="docs/assets/demo/demo.webp" alt="Demo, dark theme, fictional data: a Hungarian contract is masked, a chat goes through the gateway and comes back restored, then the live traffic dashboard fills with calls and per-call latency" width="100%">
</p>

## Try it

Offline, no key, no model download: the API, the gateway and the UI on a mock upstream
(needs [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io/)).

```bash
git clone https://github.com/watt-mind/pii-guard.git && cd pii-guard
make demo           # open http://localhost:5173
make demo-traffic   # second terminal: fictional hu/en/de calls through the gateway
make smoke          # the same as a pass/fail check (CI runs it)
```

Without a NER checkpoint, fast mode is rules only and free-text names need known values. With
`uv sync --extra ner` and `PII_GUARD_NER_MODEL` pointing at one
([models.md](docs/models.md#ner-detector)) it masks names too; the screenshots below use one,
plus `PII_GUARD_DETECTORS=rules,ner` for the Mask screen. Docker:
`docker compose --profile demo up --build`. More: [docs/operations.md](docs/operations.md).

## Why pii-guard

- **Fast mode is the product.** Rules with checksums plus a multilingual NER distilled from
  Meta's Muse Glimmer, in process: no model API call per message, and nothing leaves your
  machine before masking ([results](#results)).
- **Reversible and grammar-aware.** The answer names the real person; Hungarian case endings
  stay outside the placeholder, so inflected-name leaks went
  [18/30 → 0/30](docs/journey.md#10-hungarian-inflection-in-the-vault-2026-10-26-2333).
- **A drop-in gateway that fails closed.** Streaming, tool calls and images through the
  OpenAI-compatible API; a detection error blocks the request
  ([ADR 0006](docs/decisions/0006-fail-closed.md)).
- **Measured in the open.** Every number is a committed [run record](eval/results/runs/), the
  report is regenerated and checked in CI, and all data is fictional.

All 13 differentiators, with evidence and status: **[docs/why-pii-guard.md](docs/why-pii-guard.md)**.

## Results

Hand-written fictional documents (`smoke`: 10 German, 10 English, 31 Hungarian), pooled. Leak =
labelled personal values still readable in what the model receives; lower is safer. Copied
from the generated [docs/benchmarks.md](docs/benchmarks.md#smoke); each row links its run
records.

| System | Leak | F1 | Detect p50 | Model call per message | Run records (2026-10-27) |
|---|---:|---:|---:|---|---|
| **pii-guard fast** (rules + NER) | **0.6 %** | 98.5 % | 63 ms | none | [de+en+hu](eval/results/runs/2026-10-27-unicode-normaliser-after-smoke-fast.json) |
| pii-guard strict (+ Muse Spark Open, optional) | 0.6 % | 98.2 % | 1.9 s | Baseten | [de](eval/results/runs/2026-10-27-comparison-de-smoke-strict.json) · [en](eval/results/runs/2026-10-27-comparison-en-smoke-strict.json) · [hu](eval/results/runs/2026-10-27-comparison-hu-smoke-strict.json) |
| PrivAiTe | 12.7 % | 55.2 % | 170 ms | none | [de](eval/results/runs/2026-10-27-comparison-de-smoke-privaite.json) · [en](eval/results/runs/2026-10-27-comparison-en-smoke-privaite.json) · [hu](eval/results/runs/2026-10-27-comparison-hu-smoke-privaite.json) |
| Presidio | 24.3 % | 64.9 % | 88 ms | none | [de](eval/results/runs/2026-10-27-comparison-de-smoke-presidio.json) · [en](eval/results/runs/2026-10-27-comparison-en-smoke-presidio.json) · [hu](eval/results/runs/2026-10-27-comparison-hu-smoke-presidio.json) |
| LLM Guard | 45.1 % | 53.2 % | 110 ms | none | [de](eval/results/runs/2026-10-27-comparison-de-smoke-llm-guard.json) · [en](eval/results/runs/2026-10-27-comparison-en-smoke-llm-guard.json) · [hu](eval/results/runs/2026-10-27-comparison-hu-smoke-llm-guard.json) |

Small sets: a few points are noise. Latency is per document on a shared laptop CPU, not a
like-for-like speed test. Charts, per-language tables, image masking and the full run log:
**[docs/benchmarks.md](docs/benchmarks.md)**; how the numbers moved: [docs/journey.md](docs/journey.md).

## What you can see in the demo

All five screens run on fictional samples; tabs are deep links (`#mask`, `#chat`, `#images`,
`#benchmarks`, `#traffic`).

| **Text:** every value found, and what the model saw | **Gateway:** a chat, masked out and restored back |
|---|---|
| [![Mask screen: a fictional Hungarian contract with each personal value highlighted, and the placeholders the model sees](docs/assets/demo/1-mask.webp)](docs/assets/demo/1-mask.webp) | [![Chat screen: an English message sent through the gateway in fast mode; the model received placeholders and the answer came back restored](docs/assets/demo/2-chat.webp)](docs/assets/demo/2-chat.webp) |
| **Images:** faces, signatures and ID numbers covered | **Live traffic:** every call, its masks and its latency |
| [![Images screen: a fictional ID card; SAM 3.1 and OCR found the face, photo, signature and printed numbers, and the model saw them filled](docs/assets/demo/3-images.webp)](docs/assets/demo/3-images.webp) | [![Live traffic screen: calls through the gateway with their entity types, the selected call's details and its timing waterfall](docs/assets/demo/6-traffic.webp)](docs/assets/demo/6-traffic.webp) |
| **Latency, live:** overhead per call, stages, values per minute | **Benchmarks:** leak against latency, from the run records |
| [![Live latency charts: overhead per call with rolling p50 and p95, overhead by mode, time per stage and values masked per minute](docs/assets/demo/7-traffic-charts.webp)](docs/assets/demo/7-traffic-charts.webp) | [![Benchmarks screen: results table and the leak rate versus latency chart for pii-guard and the open-source tools](docs/assets/demo/4-benchmarks.webp)](docs/assets/demo/4-benchmarks.webp) |

At phone width: [Mask](docs/assets/demo/5-mask-mobile.webp) ·
[Live traffic](docs/assets/demo/8-traffic-mobile.webp). What each screen does:
[ui/README.md](ui/README.md#screens).

## Use it from your code

Change the base URL of any OpenAI-compatible client; nothing else.

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="unused")
reply = client.chat.completions.create(
    model="muse-spark-1.3",
    messages=[{"role": "user", "content": "I'm Jane Placeholder. Invite Teszt Elek to lunch."}],
    extra_headers={"X-PII-Guard-Mode": "fast"},
)
print(reply.choices[0].message.content)  # real names; the model only saw placeholders
```

Sessions, streaming, the headers, strict mode and every setting:
[docs/architecture-gateway.md](docs/architecture-gateway.md). The REST API (`/v1/analyze`,
`/v1/mask`, `/v1/unmask`, `/v1/mask/image`): [docs/contracts.md](docs/contracts.md).

## How it works

```
 your app / agent ──► pii-guard ──────────────────────────────► LLM provider
                      │ 1. extract text (and image regions)           │
                      │ 2. detect PII (rules → NER → optional LLM)    │
                      │ 3. apply policies, pseudonymize (keyed)       │
                      │ 4. mask image regions (SAM 3.1 + OCR)         │
                      │◄──────────────── response (streamed) ─────────┘
                      │ 5. restore placeholders, chunk by chunk
 your app / agent ◄───┘
```

The mapping between real values and placeholders **never leaves pii-guard**. Design and
engineering choices: [docs/architecture.md](docs/architecture.md); threat model:
[docs/privacy-model.md](docs/privacy-model.md); which Meta model does what:
[docs/why-pii-guard.md](docs/why-pii-guard.md#3-built-on-metas-models-end-to-end).

> **Status: hackathon build** for the Meta Global AI Developer Hackathon (October 26 –
> November 4, 2026). Detection, masking, streaming restore, the gateway, image masking and the
> evaluation harness work end to end; it is not production-hardened yet. What is not done:
> [docs/why-pii-guard.md](docs/why-pii-guard.md#what-is-not-here-yet) and
> [docs/roadmap.md](docs/roadmap.md).

## Documentation

Start at [docs/INDEX.md](docs/INDEX.md): architecture, privacy model, entity taxonomy,
languages, evaluation method, models, contracts and decision records.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The one rule that matters most: **never commit real
personal data**, not even in a test. All fixtures are synthetic.

## Security

**No authentication by default.** Keep pii-guard on loopback (the default) or behind an
authenticating proxy: anyone who can reach it can unmask and use the gateway.
`PII_GUARD_API_TOKEN` turns on a bearer token
([operations.md](docs/operations.md#exposure-and-authentication)). Found a way to make personal
data leak past the guard? Report it privately: [SECURITY.md](SECURITY.md).

## License

[Apache-2.0](LICENSE)
