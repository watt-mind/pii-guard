<p align="center">
  <img src="docs/assets/banner.svg" alt="pii-guard: a privacy firewall for AI agents. You send 'Email Jane Placeholder: jane@example.net', the model sees 'Email [[PERSON_7f3a]]: [[EMAIL_20c2]]', you get the real name back." width="100%">
</p>

<p align="center"><b>Mask personal data before it reaches the LLM, and put it back in the answer. Built on Meta's open models; runs on your machine.</b></p>

<p align="center">
  <a href="https://github.com/watt-mind/pii-guard/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/watt-mind/pii-guard/actions/workflows/ci.yml/badge.svg?branch=develop"></a>
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-blue"></a>
  <a href="docs/decisions/0005-synthetic-data-only.md"><img alt="Fictional data only" src="https://img.shields.io/badge/data-fictional%20only-b6f36b"></a>
</p>

**For teams building AI agents in Europe's regulated professions** (legal, health, finance, HR,
public sector). Their useful data is personal data: a case file, a referral letter, an HR
folder. Under GDPR, sending it to a third-party model is a legal risk; not sending it means the
agent can't do the job. pii-guard is a drop-in proxy in between: change one base URL, and every
name, address, ID and face is swapped for a reversible placeholder before the request leaves
your network, then restored in the answer, even mid-stream and inside tool calls.

**Try it offline** (no key, no model download; needs [uv](https://docs.astral.sh/uv/) and
[pnpm](https://pnpm.io/)): `git clone https://github.com/watt-mind/pii-guard.git && cd pii-guard && make demo`,
then open http://localhost:5173. [More ways to run it](#try-it).

<p align="center">
  <img src="docs/assets/demo/demo.webp" alt="Demo in the dark theme with fictional English data: a support e-mail is masked, a chat goes through the gateway and comes back restored, then the live traffic view shows each call, its masks and its latency" width="100%">
</p>

<p align="center"><sub>Recorded from <code>make demo</code> in fast mode; the offline mock upstream echoes the masked text back (with a key, the same flow runs on Muse Spark). <b>▶ Video walkthrough:</b> <i>link coming with the submission</i><!-- LAB-1123: video link --></sub></p>

## Meta's large models teach, Meta's small open model runs

| Job | Meta model | Evidence |
|---|---|---|
| **Runs in production (fast mode):** finds names, addresses and dates in process; no API call, nothing leaves the machine | **XLM-RoBERTa** (FacebookAI, open weights, MIT), fine-tuned on Muse Glimmer's labels: 36 ms p50 on an Apple-silicon GPU, 241 ms CPU-only | [latency](eval/results/ner/distilled/latency-large.json), [training](docs/models.md#distilled-from-muse-glimmer) |
| **Teaches it, and audits:** labels 4,964 fictional documents for distillation; the optional audit mode and upper bound | **Muse Glimmer 30B** (open weights, Apache-2.0); **Muse Spark Open** (open weights) on Baseten partner inference | [Glimmer run](eval/results/runs/2026-10-27-glimmer-zero-shot-rules-llm-low.json), [audit runs](docs/benchmarks.md#smoke) |
| **Sees images:** faces, ID photos and signatures, filled before the image leaves | **SAM 3.1** (Meta Model API), with OCR for printed text | [specimen results](eval/results/visual/specimens.md) |

**Muse** (Wonder, Spark 1.3) also writes the fictional benchmark ([models](docs/models.md#which-model-does-what)),
**Muse Spark Open** red-teams the masking ([red team](eval/results/2026-10-27-redteam/README.md)), and
**Muse Spark 1.3** is the demo's downstream model, which only ever sees placeholders.

The rule behind it: anything that sees real personal data is an open-weight model you can run
yourself; hosted models only see fictional or already-masked text. All jobs, with status:
[docs/why-pii-guard.md](docs/why-pii-guard.md#3-built-on-metas-models-end-to-end).

## Results

Pooled over German, English and Hungarian. Leak = labelled personal values still readable in
what the model receives (lower is safer). Copied from the generated
[docs/benchmarks.md](docs/benchmarks.md#results-by-fixture-set); every row there names its run
records.

| System | Leak, hand-written (51 docs) | Precision | Leak, [ai4privacy](docs/benchmarks.md#ai4privacy) (600 docs) | Precision | Detect p50 (hand-written, shared CPU) | Per message |
|---|---:|---:|---:|---:|---:|---|
| **pii-guard fast** (rules + NER) | **0.6 %** | 98.5 % | 27.6 % | 92.8 % | 94 ms | on-device, $0 |
| pii-guard audit (`strict` mode: + Muse Spark Open) | 0.6 % | 97.0 % | **3.9 %** | 92.5 % | 1.9 s | one Baseten call |
| PrivAiTe | 12.7 % | 51.2 % | 9.5 % | 64.8 % | 170 ms | on-device |
| Presidio | 24.3 % | 62.5 % | 29.6 % | 38.6 % | 88 ms | on-device |
| LLM Guard | 45.1 % | 61.5 % | 43.8 % | 79.3 % | 110 ms | on-device |

On the hand-written set, fast mode leaks 20× less than the best other tool. On the public
ai4privacy set, **PrivAiTe leaks less than fast mode** (9.5 % vs 27.6 %); only audit mode beats
it there. Run records: fast [hand-written](eval/results/runs/2026-10-27-rules-resolve-after-smoke-fast.json) ·
[ai4privacy](eval/results/runs/2026-10-27-rules-resolve-after-ai4privacy-fast.json); the others
are listed per language in the [run log](docs/benchmarks.md#run-log). Small sets, and latency
on a shared laptop CPU: compare loosely.

## Built for agents: tool calls and streaming

The gateway speaks the OpenAI chat API, so an agent framework only changes its base URL. It
masks every message, **tool definitions, tool-call arguments and tool results**, restores
placeholders in streamed answers chunk by chunk (also when one is split across chunks), keeps
the same placeholder for the same person across a whole session, and fails closed on anything
it can't mask ([field table](docs/contracts.md#gateway-request-fields-implemented)).

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="unused")
stream = client.chat.completions.create(
    model="muse-spark-1.3",
    stream=True,
    tools=my_tools,  # your agent's tools, unchanged
    messages=[
        {"role": "user", "content": "Refund Jane Placeholder, jane.placeholder@example.net."}
    ],
    extra_headers={"X-PII-Guard-Mode": "fast"},
)  # the model sees [[PERSON_…]] and [[EMAIL_…]]; your code gets the real values back
```

Sessions, headers, modes and settings: [docs/architecture-gateway.md](docs/architecture-gateway.md).

## Why pii-guard

- **Reversible, not redacted.** The answer names the real person, and every document in the
  hand-written set unmasks back to its original exactly.
- **Grammar-aware.** In languages like Hungarian a name changes with every case; the ending
  stays outside the placeholder, so the model still writes grammatical text:

  | | Hungarian (real output) | English gloss |
  |---|---|---|
  | You send | Kérem, írjon Próba Zsuzsannának a zsuzsa.proba@example.com címre. | Please write *to Zsuzsanna Próba* at … |
  | The model sees | Kérem, írjon [[PERSON_968e29]]nak a [[EMAIL_e7038b]] címre. | … *to [[PERSON]]* … |
  | You get back | Megírtam a levelet Próba Zsuzsannának. | I wrote *to Zsuzsanna Próba*. |

  Inflected-name leaks went [18/30 → 0/30](docs/journey.md#10-hungarian-inflection-in-the-vault-2026-10-26-2333).
- **Measured in the open.** Every number is a committed [run record](eval/results/runs/); the
  report is regenerated and checked in CI; all data is fictional.

All 13 differentiators, with evidence and status: **[docs/why-pii-guard.md](docs/why-pii-guard.md)**.

## What you can see in the demo

| **Text:** every value found, and what the model saw | **Gateway:** a chat, masked out and restored back |
|---|---|
| [![Mask screen: a fictional English support e-mail with each personal value highlighted, and the placeholders the model sees](docs/assets/demo/1-mask.webp)](docs/assets/demo/1-mask.webp) | [![Chat screen: an English message sent through the gateway in fast mode; the model received placeholders and the answer came back restored](docs/assets/demo/2-chat.webp)](docs/assets/demo/2-chat.webp) |
| **Images:** face, photo, signature and printed values covered | **Live traffic:** every call, its masks and its timing |
| [![Images screen: a fictional English ID card; SAM 3.1 and OCR found the face, photo, signature, name, birth date and document number, and the model saw them filled](docs/assets/demo/3-images.webp)](docs/assets/demo/3-images.webp) | [![Live traffic screen: calls through the gateway with their entity types, an English call's details and its timing waterfall](docs/assets/demo/6-traffic.webp)](docs/assets/demo/6-traffic.webp) |
| **Latency, live:** overhead per call, stages, values per minute | **Benchmarks:** leak against latency, from the run records |
| [![Live latency charts: overhead per call with rolling p50 and p95, overhead by mode, time per stage and values masked per minute](docs/assets/demo/7-traffic-charts.webp)](docs/assets/demo/7-traffic-charts.webp) | [![Benchmarks screen: results table and the leak rate versus latency chart for pii-guard and the open-source tools](docs/assets/demo/4-benchmarks.webp)](docs/assets/demo/4-benchmarks.webp) |

At phone width: [Mask](docs/assets/demo/5-mask-mobile.webp) ·
[Live traffic](docs/assets/demo/8-traffic-mobile.webp). The screens: [ui/README.md](ui/README.md#screens).

## Try it

```bash
make demo           # API + gateway + UI on a mock upstream: http://localhost:5173
make demo-traffic   # second terminal: fictional calls (with tools and streaming) through the gateway
make smoke          # the same as a pass/fail check (CI runs it)
```

Without a NER checkpoint, fast mode is rules only and free-text names need known values. With
`uv sync --extra ner` and `PII_GUARD_NER_MODEL` pointing at one
([models.md](docs/models.md#ner-detector)) it masks names too; the screenshots use one, plus
`PII_GUARD_DETECTORS=rules,ner` for the Mask screen. Docker:
`docker compose --profile demo up --build`. More: [docs/operations.md](docs/operations.md).

## How it works

```
 your app / agent ──► pii-guard ──────────────────────────────► LLM provider
                      │ 1. extract text, tool calls, image regions    │
                      │ 2. detect (rules → NER → optional audit LLM)  │
                      │ 3. apply policies, pseudonymize (keyed)       │
                      │ 4. mask image regions (SAM 3.1 + OCR)         │
                      │◄──────────────── response (streamed) ─────────┘
                      │ 5. restore placeholders, chunk by chunk
 your app / agent ◄───┘
```

The mapping between real values and placeholders **never leaves pii-guard**. Design and
engineering choices: [docs/architecture.md](docs/architecture.md); threat model:
[docs/privacy-model.md](docs/privacy-model.md); everything else: [docs/INDEX.md](docs/INDEX.md).

> **Status: hackathon build** for the Meta Global AI Developer Hackathon (October 26 –
> November 4, 2026). It works end to end; it is not production-hardened yet. What is missing:
> [docs/why-pii-guard.md](docs/why-pii-guard.md#what-is-not-here-yet), [docs/roadmap.md](docs/roadmap.md).

## Contributing, security, license

See [CONTRIBUTING.md](CONTRIBUTING.md); the rule that matters most: **never commit real
personal data**, not even in a test. **No authentication by default:** keep pii-guard on
loopback or behind an authenticating proxy, or set `PII_GUARD_API_TOKEN`
([operations.md](docs/operations.md#exposure-and-authentication)). Found a way to make personal
data leak past the guard? Report it privately: [SECURITY.md](SECURITY.md).
Licensed [Apache-2.0](LICENSE).
