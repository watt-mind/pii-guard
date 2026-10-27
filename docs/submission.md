# Hackathon submission (draft)

> **Draft for the owner to review before submitting.** Ready-to-paste text for the Meta
> Global AI Developer Hackathon form. Every claim matches [why-pii-guard.md](why-pii-guard.md),
> where each one links to its evidence; if a number changes there, change it here too. Status
> as of 2026-10-27.

## Tagline (≤ 140 characters)

```text
An open-source privacy firewall for AI agents: reversible, grammar-aware masking of text and images, built on Meta's open-weight models.
```

## Description

```text
pii-guard sits between an application and an LLM. It finds personal data in text and images, replaces each value with a reversible placeholder that stays the same for the whole conversation, sends only the masked request on, and puts the real values back into the answer, even while it streams. It is an OpenAI-compatible proxy, so adopting it is a change of API base URL. It is built for languages where existing tools break: in Hungarian a name changes with every grammatical case, so pii-guard keeps case endings outside the placeholder and re-inflects the name on the way back. On our hand-written test sets, rules alone let 52.6 % (Hungarian) and 46.7 % (English) of labelled values reach the model; with Meta's open-weight Muse Spark Open as the detector that drops to 0.9 % and 0.0 %, at a median 1.2–1.8 s and about $2–2.50 per 1,000 messages. Every run is a committed record, with charts checked in CI, on fictional data only. Apache-2.0.
```

## How we used Meta models

```text
One rule decides where each model runs: anything that sees real personal data is an open-weights model you can host yourself; hosted models only see fictional or masked data.
- Muse Spark Open (open weights, on Baseten Model APIs or your own GPUs) is the production detector in strict mode: 0.9 % Hungarian and 0.0 % English leak.
- Muse Glimmer 30B (open weights, Apache-2.0) was the best zero-shot detector we measured (F1 99.3, 0.0 % leak) but takes 9.4 s per document, so we used it as the teacher: it labelled a 4,964-document fictional corpus, and we distilled it into XLM-RoBERTa, which runs in-process in tens of milliseconds for fast mode. A LoRA fine-tune of Glimmer is in progress.
- Muse Spark 1.3 wrote the synthetic Hungarian and English benchmark and the distillation corpus around fictional identities ($1.05 for 5,004 calls), and is the downstream model in the demo, which only ever sees placeholders.
- Muse Spark Open and Muse Spark 1.3 are also the attackers in our red teams: prompt injection against the detector, and re-identification of masked documents.
- Muse Image painted the portraits, signatures and stamps for 24 fictional specimen ID documents, so image tests need no real ID.
- SAM 3.1 finds faces, ID photos and signatures in images: 90.8 % portrait recall on 65 official specimen ID documents.
```

## What's novel

```text
- Reversible placeholders, consistent for a whole session and restored in streamed answers and tool calls, instead of one-way [REDACTED].
- Grammar-aware masking: all inflected forms of a Hungarian name share one placeholder, and the answer is re-inflected on unmask (inflected-name leaks 18/30 to 0/30).
- The LLM can only point at spans in the original, never rewrite text; checksum-validated rules win on structured IDs. Prompt-injection red team: leak 3.4 % to 0.0 % in two runs after hardening.
- We publish exposure, not just detection: Meta's own model recovers 0.2 % of masked values from the masked text, and 39.2 % when handed five candidates (chance 20 %). We say "pseudonymisation, not anonymisation".
- The gateway masks tool definitions, response schemas and metadata, refuses placeholders pasted back as input, and fails closed on every error.
- Language packs with a conformance suite, so adding a language is a checklist (German was added this way).
- Measured against Presidio, LLM Guard and PrivAiTe on the same fixtures: 1.0 % Hungarian leak against 19.6–49.5 %.
```

## Challenges

```text
- Hungarian morphology: a vowel lengthens before a suffix (Zsuzsanna, Zsuzsannának), so inflected names first slipped through the vault. Fixed by keying every form on its lemma.
- Speed against quality: Muse Spark 1.3 detected well at 10.6 s per document, Glimmer at 9.4 s. Muse Spark Open on Baseten brought it to 1.8 s at the same quality, and distilling Glimmer gave a no-API fast mode.
- Muse Spark Open spent its whole token budget reasoning at the default effort and returned nothing; the detector failed closed, as designed, and reasoning_effort "low" fixed it.
- Honest evaluation: Muse-written test data flatters a Muse-based detector, so headline numbers come from hand-written sets, and the small set sizes are stated next to every number.
- OCR reads the "<" filler of machine-readable zones as "K", so the checksum rule never fired on images; a layout-based finder took MRZ recall on official specimens from 0 % to 76.7 %.
```

## What's next

```text
- A fresh, reproducible comparison against Presidio, LLM Guard and PrivAiTe with today's fast and strict modes, including the public ai4privacy OpenPII-1M benchmark (in progress).
- Masking printed names and numbers on ID cards (in progress), then placeholder-labelled images that share the text session's placeholders, so an assistant can answer "which parties have an ID on file?" without seeing a value (planned). As far as we found in a survey on 2026-10-27, no open-source tool shares placeholders between images and the text session.
- An image baseline against Presidio Image Redactor (planned).
- A LoRA fine-tune of Muse Glimmer as a request-path detector (in progress), and publishing the distilled NER weights.
- Confirming the hosted endpoint's data-retention terms before recommending it for real data.
```

## Links

| Field | Link |
|---|---|
| Repository | https://github.com/watt-mind/pii-guard |
| Why pii-guard (evidence for every claim) | https://github.com/watt-mind/pii-guard/blob/develop/docs/why-pii-guard.md |
| Benchmarks (every run, with charts) | https://github.com/watt-mind/pii-guard/blob/develop/docs/benchmarks.md |
| Journey (milestones, before/after numbers, spend) | https://github.com/watt-mind/pii-guard/blob/develop/docs/journey.md |
| Models (which Meta model does what) | https://github.com/watt-mind/pii-guard/blob/develop/docs/models.md |
| Demo video | *to be added by the owner* |

## Owner checklist before submitting

- Re-read every number against [why-pii-guard.md](why-pii-guard.md); refresh the head-to-head
  line once LAB-1148 merges.
- Switch the links from `develop` to the submitted branch or tag if the form asks for a fixed
  version.
- Add the demo video link.
