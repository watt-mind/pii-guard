# Demo video script (3 minutes)

The shot list for the submission video. Each shot gives what is on screen, what to type or
click, and the voice-over. Every value on screen is fictional
([ADR 0005](decisions/0005-synthetic-data-only.md)): the names, email addresses and IDs below
come from the committed fixtures and the README, never from a real person.

Judges score Impact, Use of Meta AI, Technical depth and the Demo itself. The shots are in the
order a judge's questions come up: *what is the problem* (shot 1), *does it work* (2–5), *where
is Meta* (2, 5, 6), *is it measured* (7).

## Before recording

```bash
# Terminal 1: the full console on the Meta Model API, fast mode (rules + the published NER)
set -a; . ./.env; set +a          # META_API_KEY, never shown on screen
uv run pii-guard up --port 8787 --upstream-url https://api.meta.ai/v1 --api-key-env META_API_KEY
```

- Open http://localhost:8787. The banner must name `watt-mind/pii-guard-ner-xlmr-base`; if it
  says rules only, the NER is missing and free-text names will pass.
- Offline fallback (no key, mock upstream that echoes the masked text): `make demo`, then
  http://localhost:5173. Say "mock upstream" in the voice-over if you record this way.
- Light theme, browser at 1440 × 900, zoom 110 %. Hide the bookmarks bar and every terminal
  that shows `.env`.
- Run `make demo-traffic` once beforehand so Overview and Logs have calls to show, then clear
  nothing: the counts are real.

## Shots

| # | Time | On screen | Do | Voice-over |
|---|---|---|---|---|
| 1 | 0:00–0:20 | The README banner: what you send, what the model sees, what you get back | Slow scroll over the banner | "AI agents in law, health and HR need personal data to be useful, and GDPR makes sending it to a third-party model a risk. PII Guard sits in between: change one base URL, and every name, ID and face is swapped for a reversible placeholder before it leaves, then put back in the answer." |
| 2 | 0:20–0:50 | Playground → **Text**, Hungarian sample | Paste `Kérem, írjon Próba Zsuzsannának a zsuzsa.proba@example.com címre.` and run | "Hungarian changes a name with every case. Our open NER, a fine-tuned version of Meta's XLM-RoBERTa, finds the name in 20 milliseconds on this laptop. The ending stays outside the placeholder, so the model still writes correct Hungarian." Point at `[[PERSON_…]]nak`. |
| 3 | 0:50–1:20 | Playground → **Chat**, same session | Ask "Write a two-line reply to this customer and address them by name" | "This goes to Muse Spark on the Meta Model API. Muse only ever saw placeholders, and the answer comes back with the real name, re-inflected, while it streams." Open the "what the model saw" panel. |
| 4 | 1:20–1:45 | Playground → **Images**, a fictional specimen ID card | Upload or pick the sample card, run | "Images too: SAM 3.1 finds the signature, the photo is found on the device, OCR reads the printed values. Each region carries the same placeholder as the text, so the model can still say which party has an ID on file." |
| 5 | 1:45–2:10 | A terminal running Muse Code through the gateway (`pii-guard connect muse-code`), then **Logs** | Ask Muse to add a fictional customer record to a file; switch to Logs and open the call | "Agents work through it unchanged. This is Meta's own coding agent, Muse Code, on the Responses API: the tool calls write the real values into the file, and the log shows the upstream saw only placeholders. Zero of sixteen test values reached the model." |
| 6 | 2:10–2:35 | [models.md](models.md#which-model-does-what) table, or a slide of it | Static | "Meta models do every job. Muse Glimmer labeled our training data and taught the small model that runs in production. Muse Spark wrote the fictional benchmark and red-teams the masking. We also fine-tuned Glimmer itself as a detector: two times faster, but leakier, so we measured it and kept the small model." |
| 7 | 2:35–2:55 | **Evaluation** screen: leak vs latency | Hover the PII Guard point, then Presidio and LLM Guard | "Every number is a committed run record. On agent traffic, fast mode masks text that isn't personal data less than one time in a hundred, against more than one in three for PrivAiTe, and leaks two values in a thousand, against twenty-four for PrivAiTe. On our hand-written German, English, Hungarian and Polish set it leaks nothing in any language, against about a quarter of values for Presidio and almost half for LLM Guard. Where we are weak, finance text, the page says so." |
| 8 | 2:55–3:00 | **Overview** with real counts, repo URL | Static | "PII Guard. Open source, Apache-2.0, runs on your machine. github.com/watt-mind/pii-guard." |

## Numbers said aloud, and where they come from

Re-check each one on the day you record; if a run changed, change the line.

| Claim | Source |
|---|---|
| The NER takes 43 ms per message on CPU (p50, the model alone) | [README results](../README.md#results): the generated latency line |
| Agent traffic: over-masking 0.7 % vs PrivAiTe 35.2 %, leak 0.2 % vs 2.4 % | [README results](../README.md#results) (leak and over-masking tables) |
| Hand-written set: 0.0 % in each language, Presidio 25.5 %, LLM Guard 46.3 % | [benchmarks.md](benchmarks.md#smoke), [README results](../README.md#results) |
| Muse Code: 0 of 16 values reached the upstream | [integrations/muse-code.md](integrations/muse-code.md), [journey milestone 45](journey.md#45-one-value-one-placeholder-every-turn-sticky-sessions-without-headers-2026-10-27) |
| Glimmer LoRA: 2.2× faster than zero-shot, leaks 1.0 % against 0.4 % with the rules in front | [glimmer-lora results](../eval/results/2026-10-28-glimmer-lora/README.md) |
| "which party has an ID": 3 of 3 with labeled images, 1 of 3 with black boxes | [journey milestone 27](journey.md#27-images-that-say-whose-data-they-hid-2026-10-27) |

## Don't

- Don't show `.env`, a terminal with a key, or the Fireworks, Baseten or Modal consoles.
- Don't type a real name, not even your own: every value comes from the fixtures.
- Don't claim anonymization: say "pseudonymization" or "masking"
  ([privacy-model.md](privacy-model.md)).
- Don't cut the weak spot in shot 7. Judges trust a number more when its limit is next to it.
