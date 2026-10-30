# PII Guard

<p align="center">
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/banner-narrow.svg">
    <img src="docs/assets/banner.svg" alt="PII Guard: a privacy gateway for AI agents. You send 'Email Jane Placeholder: jane@example.net', the model sees 'Email [[PERSON_7f3a]]: [[EMAIL_20c2]]', you get the real name back." width="100%">
  </picture>
</p>

<p align="center"><b>Mask personal data before it reaches the LLM, and put it back in the answer. Built on Meta's open models; runs on your machine.</b></p>

<p align="center">
  <a href="https://guard.watt-mind.com"><img alt="Try it live: guard.watt-mind.com" src="https://img.shields.io/badge/try%20it%20live-guard.watt--mind.com-b6f36b"></a>
  <a href="https://github.com/watt-mind/pii-guard/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/watt-mind/pii-guard/actions/workflows/ci.yml/badge.svg?branch=develop"></a>
  <a href="https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base"><img alt="Model on Hugging Face" src="https://img.shields.io/badge/%F0%9F%A4%97%20model-watt--mind%2Fpii--guard--ner--xlmr--base-yellow"></a>
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
  <a href="pyproject.toml"><img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-blue"></a>
  <a href="docs/decisions/0005-synthetic-data-only.md"><img alt="Fictional data only" src="https://img.shields.io/badge/data-fictional%20only-b6f36b"></a>
</p>

> **Status: hackathon build** for the Meta Global AI Developer Hackathon (October 26 –
> November 4, 2026). It works end to end; it is not production-hardened yet
> ([what is missing](docs/why-pii-guard.md#what-is-not-here-yet), [roadmap](docs/roadmap.md)).
> **No authentication by default:** keep it on loopback or behind an authenticating proxy, or
> set `PII_GUARD_API_TOKEN` ([operations.md](docs/operations.md#exposure-and-authentication)).

**For teams building AI agents in Europe's regulated professions** (legal, health, finance, HR,
public sector). Their useful data is personal data: a case file, a referral letter, an HR
folder. Under GDPR, sending it to a third-party model is a legal risk; not sending it means the
agent can't do the job. PII Guard is a drop-in proxy in between: change one base URL, and every
name, address, ID and face is swapped for a reversible placeholder before the request leaves
your network, then restored in the answer, even mid-stream and inside tool calls.

| You are… | Start here |
|---|---|
| Evaluating the hackathon entry | [Meta's models](#metas-large-models-teach-metas-small-open-model-runs) and [Results](#results) |
| Putting an agent behind it | [Quickstart](#quickstart), then [Built for agents](#built-for-agents-tool-calls-and-streaming) |
| Checking the EU/GDPR fit | [docs/eu-regulation.md](docs/eu-regulation.md) and the [threat model](docs/privacy-model.md) |

**Why it matters in the EU.** The GDPR requires data minimization (Art. 5) and lists
pseudonymization among example by-design and security measures (Art. 25, 32). Placeholders
reduce the personal data that reaches a model provider outside the EU, though they don't by
themselves settle Chapter V transfer obligations. Pseudonymized data stay personal data for
whoever holds the mapping: a technical measure, not a compliance certificate. Sources, the 2025
CJEU ruling, DORA and the AI Act: [docs/eu-regulation.md](docs/eu-regulation.md).

## Contents

- [Quickstart](#quickstart)
- [How it works](#how-it-works)
- [Meta's large models teach, Meta's small open model runs](#metas-large-models-teach-metas-small-open-model-runs)
- [Results](#results)
- [Built for agents: tool calls and streaming](#built-for-agents-tool-calls-and-streaming)
- [Why PII Guard](#why-pii-guard)
- [What you can see in the demo](#what-you-can-see-in-the-demo)
- [Try it](#try-it)
- [Contributing, security, license](#contributing-security-license)

## Quickstart

| Path | What you run | Needs |
|---|---|---|
| **Live demo** | [guard.watt-mind.com](https://guard.watt-mind.com): guest demo with no sign-up and no key, or sign in with Google for your own gateway endpoint. Fictional data only; capped sponsored allowance | a browser |
| **Offline, from source** | `git clone https://github.com/watt-mind/pii-guard.git && cd pii-guard && make demo`, then open http://localhost:5173 | [uv](https://docs.astral.sh/uv/) and [pnpm](https://pnpm.io/); no key |
| **Planned: no clone** | `uvx --from wattmind-pii-guard pii-guard up` — not runnable yet; there is no PyPI package yet | [uv](https://docs.astral.sh/uv/) |

[More ways to run it](#try-it), including Docker and putting a coding agent behind it.

<p align="center">
  <img src="docs/assets/demo/demo.webp" alt="Demo of the console in the light theme with fictional English data: the Overview counts real gateway calls, a support email is masked in the Playground, the same session continues in Chat and comes back restored, Logs shows each call, and Connect gives the commands for a client" width="100%">
</p>

<p align="center"><sub>Recorded from <code>pii-guard up</code> with the offline mock upstream; a fast-mode recording with the NER on is planned. <b>▶ Video walkthrough:</b> <i>link coming with the submission</i><!-- LAB-1123: video link --></sub></p>

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

The mapping between real values and placeholders **never leaves PII Guard**. Design and
engineering choices: [docs/architecture.md](docs/architecture.md); API guide and
reference: [docs/api.md](docs/api.md), [guard.watt-mind.com/#api](https://guard.watt-mind.com/#api); threat model:
[docs/privacy-model.md](docs/privacy-model.md); everything else: [docs/INDEX.md](docs/INDEX.md).

### Modes

| Mode | Detection | Leaves your machine? | Use it for |
|---|---|---|---|
| `fast` (default) | Rules + on-device NER; no model call | Only the masked request, to your LLM provider | Everyday agent traffic |
| `fast` without the `ner` extra | Rules only; free-text names need known values | Only the masked request | Offline runs, CI, structured data |
| `audit` (opt-in per request, `X-PII-Guard-Mode: audit`) | Rules + NER + an LLM detector (one hosted call per message; fails closed when the call fails) | The unmasked text goes to the audit endpoint you configure | The measured upper bound and teaching data, not production traffic |

Sessions, headers and settings: [docs/architecture-gateway.md](docs/architecture-gateway.md).

### What it detects

People, addresses, emails, phone numbers, dates of birth, national and document IDs
(including Hungarian tax and TAJ numbers), bank accounts and payment cards, vehicle plates,
parcel numbers and secrets such as API keys — plus faces, ID photos and signatures in images.
Full taxonomy, per-language validators and defaults: [docs/entities.md](docs/entities.md).

## Meta's large models teach, Meta's small open model runs

| Job | Meta model | Evidence |
|---|---|---|
| **Runs by default (fast mode):** finds names, addresses and dates in process; no API call, nothing leaves the machine | **XLM-RoBERTa base** (FacebookAI, open weights, MIT), fine-tuned on Muse Glimmer's labels, public PII datasets in 24 EU languages and hard negatives; published as [`watt-mind/pii-guard-ner-xlmr-base`](https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base) `v4.2`. Runs on CPU, no GPU needed ([time per message](#results)) | [model card](training/ner/model-card.md), [training](docs/models.md#ner-v4-v41-and-v42-v42-is-published), [selection](eval/results/2026-10-30-lab-1625-ner-v42/README.md) |
| **Teaches it, and audits:** labels 4,964 fictional documents for distillation; the optional audit mode and upper bound | **Muse Glimmer 30B** (open weights, Apache-2.0); **Muse Spark Open** (open weights) on Baseten partner inference | [Glimmer run](eval/results/runs/2026-10-27-glimmer-zero-shot-rules-llm-low.json), [audit runs](docs/benchmarks.md#smoke) |
| **Sees images:** faces, ID photos and signatures, filled before the image leaves | **SAM 3.1** (Meta Model API) for signatures; faces and ID photos on-device (YuNet); OCR for printed text | [specimen results](eval/results/visual/specimens.md) |

Naming in one line: **Muse Glimmer** is the small open-weight teacher, **Muse Spark Open** is
the open-weight audit model, and **Muse Spark 1.3** is the hosted downstream model in the demo;
the full assignment is in [docs/models.md](docs/models.md#which-model-does-what).
**Muse** (Wonder, Spark 1.3) also writes the fictional benchmark ([models](docs/models.md#which-model-does-what)),
**Muse Spark Open** red-teams the masking ([red team](eval/results/2026-10-27-redteam/README.md)), and
**Muse Spark 1.3** is the demo's downstream model, which only ever sees placeholders.
We also fine-tuned **Muse Glimmer** itself as an answer-only detector (LoRA): 2.2x faster than
zero-shot Glimmer but leakier (1.0 % vs 0.4 % of agent-traffic values with the rules in front),
so the small NER stays the product ([results](eval/results/2026-10-28-glimmer-lora/README.md)).

The rule behind it: anything that sees real personal data is an open-weight model you can run
yourself; hosted models only see fictional or already-masked text. All jobs, with status:
[docs/why-pii-guard.md](docs/why-pii-guard.md#3-built-on-metas-models-end-to-end).

## Results

Headline: in fast mode, nothing leaked on the hand-written set and almost nothing on agent
traffic — the first row of the generated tables below — while the baselines leak visibly more
on the same sets. The chart is the summary; the full generated tables are collapsed under it,
and [docs/benchmarks.md](docs/benchmarks.md) has every set, language and run.

Leak = labeled personal values still readable in what the model receives (lower is safer).
Over-masking = masked spans that were not personal data (lower is better). Fast mode is the
published NER `v4.2` (its run records keep the candidate name `v42-b3`). Everything between the two charts below is generated by
`pii-guard eval report` from the committed run records in
[`eval/results/runs/`](eval/results/runs/), the same records as
[docs/benchmarks.md](docs/benchmarks.md#results-by-fixture-set) and the landing page: the
hand-written set and the public and agent-traffic test splits (none of their rows trained on,
except where marked †).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/benchmarks/leak-vs-latency-dark.svg">
  <img src="docs/benchmarks/leak-vs-latency.svg" alt="Leak rate vs latency">
</picture>

<details>
<summary>Full generated tables: leak and over-masking on every fixture set</summary>

<!-- results:start -->
<!-- Generated by `pii-guard eval report` from the run records and the `readme` section of docs/benchmarks/config.json; edit those, not this block. -->

| Leak | Hand-written (de+en+hu+pl, 62 docs) | Agent traffic (de+en+hu, 990 docs) | Nemotron-PII (en, 300 docs) | CEE-PII (en+hu, 451 docs) | Gretel finance (de+en, 400 docs) | Gretel finance, corrected labels (de+en, 400 docs) | Ai4Privacy (de+en+hu, 600 docs) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **PII Guard fast** (rules + NER, on-device, $0) | **0.0 %** | **0.2 %** | **0.6 %** | **0.8 %** | 19.1 % | **2.4 %** | 0.4 % † |
| PrivAiTe | 13.0 % | 2.4 % | 4.0 % | 4.4 % | 27.7 % | 13.2 % | 9.5 % |
| Presidio | 25.5 % | 16.6 % | 12.8 % | 36.5 % | **18.8 %** | 14.8 % | 34.8 % |
| LLM Guard | 46.3 % | 20.2 % | 28.8 % | 75.8 % | 59.3 % | 51.3 % | 43.8 % ‡ |
| PII Guard rules only (no name detection) | 40.7 % | 38.8 % | 56.0 % | 41.3 % | 80.8 % | 77.1 % | 62.3 % |

Detection p50 on the `smoke` set: fast 37 ms*, PrivAiTe 60 ms*, Presidio 42 ms*, LLM Guard 60 ms* (`*` averaged over several runs), each on the machine in its run record: compare loosely.

Leak per language of the fast row on `smoke`: de 0.0 %, en 0.0 %, hu 0.0 %, pl 0.0 %.

What the NER model (v4.2) takes per message on CPU (the model's own detection time, not the whole gateway; measured alternating with v2.0 in one process on a shared machine): p50 43 ms, p95 50 ms (122 messages of about 382 characters, arm64 macOS-26.5.2-arm64-arm-64bit, 8 threads; [measurement](eval/results/2026-10-30-lab-1625-ner-v42/latency-cpu-local.json)).

| Over-masking | Hand-written (de+en+hu+pl, 62 docs) | Agent traffic (de+en+hu, 990 docs) | Nemotron-PII (en, 300 docs) | CEE-PII (en+hu, 451 docs) | Gretel finance (de+en, 400 docs) | Gretel finance, corrected labels (de+en, 400 docs) | Ai4Privacy (de+en+hu, 600 docs) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **PII Guard fast** (rules + NER, on-device, $0) | 1.3 % | 0.7 % | 1.5 % | 7.3 % | 24.4 % | 24.4 % | 0.3 % |
| PrivAiTe | 25.7 % | 35.2 % | 5.6 % | 59.2 % | 46.5 % | 46.6 % | 4.7 % |
| Presidio | 26.1 % | 33.4 % | 32.0 % | 52.5 % | 75.4 % | 76.7 % | 6.3 % |
| LLM Guard | 33.7 % | 16.9 % | **0.6 %** | 66.4 % | **17.0 %** | **17.0 %** | 14.1 % |
| PII Guard rules only (no name detection) | **0.0 %** | **0.0 %** | 0.8 % | **0.0 %** | 21.7 % | 21.8 % | **0.1 %** |

Over-masking: share of masked spans that are not personal data; lower is better ([how it is scored](docs/benchmarks.md#how-to-read-this)).

Records behind the fast row: Hand-written ([1](eval/results/runs/2026-10-30-lab-1625-pl-smoke-v42-b3.json) · [2](eval/results/runs/2026-10-30-lab-1625-smoke-v42-b3.json)), [Agent traffic](eval/results/runs/2026-10-30-lab-1625-agent-traffic-v42-b3.json), [Nemotron-PII](eval/results/runs/2026-10-30-lab-1625-nemotron-pii-v42-b3.json), [CEE-PII](eval/results/runs/2026-10-30-lab-1625-cee-pii-v42-b3.json), [Gretel finance](eval/results/runs/2026-10-30-lab-1625-gretel-finance-v42-b3.json), [Gretel finance, corrected labels](eval/results/runs/2026-10-30-lab-1625-gretel-finance-corrected-v42-b3.json), [Ai4Privacy](eval/results/runs/2026-10-30-lab-1625-ai4privacy-v42-b3.json); every other cell is in the [run log](docs/benchmarks.md#run-log).
<!-- results:end -->

</details>

† **In-distribution:** the NER was trained on other rows of the same dataset (the OpenPII
train split; no evaluated row was trained on), so this cell is not a win. The same recipe
trained without those rows leaked far more on an earlier version of this sample
([ablation](docs/benchmarks.md#ai4privacy)), so on unseen text in that style PrivAiTe may well
leak less than fast mode. ‡ LLM Guard's model was fine-tuned on Ai4Privacy data too
([configurations](eval/results/2026-10-27-comparison/README.md#systems)).

- **Where fast mode is weak:** finance text on the dataset's own labels, about level with
  Presidio; on the corrected labels ([why](docs/datasets.md)) it leaks least. Over-masking
  is low on the hand-written set and agent traffic but high on Gretel finance and CEE-PII,
  where reference numbers without a cue word come out as IDs
  ([model card](training/ner/model-card.md#limitations)).
- **Where v4.2 is behind v2.0:** with the rules, CEE-PII leaks 0.8 % against v2.0's 0.4 % and
  Polish pl-pii-bench 4.2 % against 3.5 %; on TAB court text, scored locally only, 5.1 %
  against 4.0 %. None of these was a release gate; v4.2 won on the gates (hand-written sets,
  agent traffic, EU languages) and over-masks less
  ([v4.2 results](eval/results/2026-10-30-lab-1625-ner-v42/README.md)).
- **Audit mode** (opt-in: rules + NER + Muse Spark Open, one hosted Baseten call per message,
  fails closed when the call fails) is the upper bound and the teacher, not the production
  path; its runs are in [benchmarks.md](docs/benchmarks.md#smoke).
- **Caveats:** the sets are small (tens to hundreds of documents per language); headline sets
  are hand-written or public because Muse-generated fixtures flatter Muse-based detection.

### What it does not do

- It is not a compliance certificate: pseudonymized data stay personal data for whoever holds
  the mapping ([eu-regulation.md](docs/eu-regulation.md)).
- It is not production-hardened yet, and fast mode is weak on finance text and on reference
  numbers without a cue word (above).
- It does not authenticate callers by default (see the status note at the top).

The full list: [what is not here yet](docs/why-pii-guard.md#what-is-not-here-yet) and the
[roadmap](docs/roadmap.md).

## Built for agents: tool calls and streaming

The gateway speaks the OpenAI chat API, so an agent framework only changes its base URL. It
masks every message, **tool definitions, tool-call arguments and tool results**, restores
placeholders in streamed answers chunk by chunk (when a chunk ends in what could be the start of
a placeholder, only that tail is held back until the next chunk completes or rules it out), keeps
the same placeholder for the same person across a whole session, masks inline images, and
fails closed on anything it can't mask ([field table](docs/contracts.md#gateway-request-fields-implemented)).
Clients that can't send a session header still get one sticky session: from the URL path
that `pii-guard connect` writes, the `prompt_cache_key`, or one per client key
([sessions](docs/architecture-gateway.md#sessions)).

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="unused")
stream = client.chat.completions.create(
    model="muse-spark-1.3",  # any model your upstream serves; the guard is provider-neutral
    stream=True,
    tools=my_tools,  # your agent's tools, unchanged
    messages=[
        {"role": "user", "content": "Refund Jane Placeholder, jane.placeholder@example.net."}
    ],
    extra_headers={"X-PII-Guard-Mode": "fast"},
)  # the model sees [[PERSON_…]] and [[EMAIL_…]]; your code gets the real values back
```

It also serves the Responses API, so coding agents run behind it unmodified. **Four real
harnesses — pi, OpenCode, Codex and Muse Code** — did a two-turn task on a fictional customer
file (`cat` it, reply with an email, then edit the file) through the gateway on Muse Spark:

- Across **115 agent requests, none of the 9 fictional values reached the model**.
- Refused turns went from 7 of 15 to **0 of 10** after the placeholder note; 8 of 10 turns
  finished, with real values restored in the answers and on disk.
- Streaming, multi-turn sessions and tool calls (`read`, `write`, `bash`, `edit`) passed in
  all four; the one Codex failure was a regex-escaped placeholder, since fixed
  ([#221](https://github.com/watt-mind/pii-guard/pull/221)).

Ten turns is a small sample, not a benchmark
([matrix and setup](docs/integrations/harness-matrix-2026-10-29.md),
[Muse Code guide](docs/integrations/muse-code.md)). Sessions, headers, modes and settings:
[docs/architecture-gateway.md](docs/architecture-gateway.md).

## Why PII Guard

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
- **Language packs.** Hungarian, English, German and Polish (`hu`, `en`, `de`, `pl`) each ship
  validated identifier rules, cue words and case handling; a new language is one package
  ([docs/languages.md](docs/languages.md)).
- **Measured in the open.** Every result number is generated from a committed
  [run record](eval/results/runs/) and checked in CI (`pii-guard eval report --check`, and a
  test for the landing page's figures); all data is fictional.

All 13 differentiators, with evidence and status: **[docs/why-pii-guard.md](docs/why-pii-guard.md)**.

## What you can see in the demo

The console has six sections: **Overview**, **Playground** (Text, Chat, Images), **Logs**,
**Connect**, **Policy** and **Evaluation** ([ui/README.md](ui/README.md#screens)). These
screenshots were taken in fast mode without the NER, so free-text names stay readable in them.

| **Text:** every value found, and what the model saw | **Gateway:** a chat, masked out and restored back |
|---|---|
| [![Playground, Text tab: a fictional English support email with each value the rules found highlighted, and the placeholders the model sees](docs/assets/demo/1-mask.webp)](docs/assets/demo/1-mask.webp) | [![Playground, Chat tab: the same email sent through the gateway in the same session; a note says names are not detected without NER, and the model received placeholders](docs/assets/demo/2-chat.webp)](docs/assets/demo/2-chat.webp) |
| **Images:** face, photo, signature and printed values covered | **Logs:** every call, its masks and its timing |
| [![Playground, Images tab: this server refuses images (no OCR, no face detector), so a fictional visitor badge replays regions recorded from a real SAM 3.1 run, and the model saw the face filled](docs/assets/demo/3-images.webp)](docs/assets/demo/3-images.webp) | [![Logs: calls through the gateway with their entity types, a call's details (mock upstream, session from the X-PII-Guard-Session header) and its timing waterfall](docs/assets/demo/6-traffic.webp)](docs/assets/demo/6-traffic.webp) |
| **Overview:** what the guard protected, from real calls only | **Evaluation:** leak against latency, from the run records |
| [![Overview: requests, values masked, requests blocked and PII Guard overhead counted from the traffic log, top entity types and latency per stage](docs/assets/demo/7-traffic-charts.webp)](docs/assets/demo/7-traffic-charts.webp) | [![Evaluation: the benchmark headline, fixture sets, languages and systems to compare](docs/assets/demo/4-benchmarks.webp)](docs/assets/demo/4-benchmarks.webp) |

At phone width: [Text](docs/assets/demo/5-mask-mobile.webp) ·
[Logs](docs/assets/demo/8-traffic-mobile.webp). Connect: [copyable commands per client](docs/assets/demo/9-connect.webp). The screens: [ui/README.md](ui/README.md#screens).

## Try it

**Before you expose it:** there is no authentication by default. Keep PII Guard on loopback or
behind an authenticating proxy, or set `PII_GUARD_API_TOKEN`
([operations.md](docs/operations.md#exposure-and-authentication)).

**Planned — once the package is published** (there is no PyPI package or GitHub release yet), one
command, with no clone, Node or Docker, only [uv](https://docs.astral.sh/uv/), starts the
API, the OpenAI-compatible gateway and the web UI with the live dashboard on
http://localhost:8787, with an offline mock upstream unless you pass `--upstream-url`:

```bash
uvx --from wattmind-pii-guard pii-guard up           # rules only
uvx --from 'wattmind-pii-guard[ner]' pii-guard up    # fast mode with the NER (about 1.1 GB, downloaded once)
```

Today, from source, `uvx --from git+https://github.com/watt-mind/pii-guard pii-guard up` runs
the API and gateway without the UI. To put an agent behind it, run `pii-guard connect pi`
with the same `uvx --from` prefix ([operations.md](docs/operations.md#one-command-pii-guard-up)).

From a checkout:

```bash
make demo           # API + gateway + UI on a mock upstream, fast mode (rules + NER): http://localhost:5173
make demo-traffic   # second terminal: fictional calls (with tools and streaming) through the gateway
make smoke-fast     # the same as a pass/fail check, with the NER
make smoke          # rules only, offline (CI runs it)
```

`make demo` runs **fast mode with the NER** from a clean checkout: it installs the `ner` extra
and, without `PII_GUARD_NER_MODEL`, downloads a NER model once (about 1.1 GB, pinned
revision, SHA-256 checked, into `~/.cache/pii-guard/models`; the banner says which model
runs): PII Guard's own NER, [`watt-mind/pii-guard-ner-xlmr-base`](https://huggingface.co/watt-mind/pii-guard-ner-xlmr-base)
`v4.2` (XLM-R base, Apache-2.0; [model card](training/ner/model-card.md)). Free-text names are then masked with no known values, in the gateway and on the Mask and
Images screens alike. `make demo MODE=rules` is rules only: offline, no download, names need
known values. Which model and why: [models.md](docs/models.md#which-ner-model-fast-mode-runs).
A set `PII_GUARD_NER_MODEL` without the extra stops startup instead of quietly running rules
only. Docker: `docker compose --profile demo up --build` (the demo image is 1.9 GB on arm64
with CPU-only torch; [operations.md](docs/operations.md#docker)). More:
[docs/operations.md](docs/operations.md).

## Contributing, security, license

See [CONTRIBUTING.md](CONTRIBUTING.md); the rule that matters most: **never commit real
personal data**, not even in a test. **No authentication by default:** keep PII Guard on
loopback or behind an authenticating proxy, or set `PII_GUARD_API_TOKEN`
([operations.md](docs/operations.md#exposure-and-authentication)). Found a way to make personal
data leak past the guard? Report it privately: [SECURITY.md](SECURITY.md).
Licensed [Apache-2.0](LICENSE).
