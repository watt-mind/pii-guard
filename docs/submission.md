# Hackathon submission (draft)

> **Draft for the owner to review before submitting.** Ready-to-paste text for the Meta
> Global AI Developer Hackathon form. Every claim matches [why-pii-guard.md](why-pii-guard.md),
> where each one links to its evidence; if a number changes there, change it here too. Status
> as of 2026-10-28; numbers from [benchmarks.md](benchmarks.md) on `develop`.

## Tagline (≤ 140 characters)

```text
An open-source privacy firewall for AI agents: reversible, grammar-aware masking of text and images, built on Meta's open-weight models.
```

## Description

```text
pii-guard sits between an application and an LLM. It finds personal data in text and images, replaces each value with a reversible placeholder that stays the same for the whole conversation, sends only the masked request on, and puts the real values back into the answer, even while it streams. It is an OpenAI-compatible proxy, so adopting it is a change of API base URL. It is built for languages where existing tools break: in Hungarian a name changes with every grammatical case, so pii-guard keeps case endings outside the placeholder and re-inflects the name on the way back. On our hand-written test set (German, English and Hungarian, 51 documents), rules alone let 41.6 % of labelled values reach the model; the default fast mode (rules + our published NER, an XLM-RoBERTa fine-tuned on Meta's Muse Glimmer labels and public data) runs on the machine at $0 in about 18 ms per document and brings that to 0.0 %. On public test sets it never trained on it leaks 0.4–0.7 % (CEE-PII, Nemotron-PII) but 19.1 % on finance text. The optional audit mode adds a second opinion from Meta's open-weight Muse Spark Open for quality checks: 0.6 % at about 1.9 s per message. Every run is a committed record, with charts checked in CI, on fictional data only. Apache-2.0.
```

## How we used Meta models

```text
One rule decides where each model runs: anything that sees real personal data is an open-weights model you can host yourself; hosted models only see fictional or masked data.
- Muse Spark Open (open weights, on Baseten Model APIs or your own GPUs) is the LLM detector of audit mode, the optional second opinion for quality checks and the benchmark upper bound: 0.9 % Hungarian and 0.0 % English leak. Production traffic runs fast mode (rules + the NER, local, about 18 ms per document, $0, nothing leaves the machine).
- Muse Glimmer 30B (open weights, Apache-2.0) was the best zero-shot detector we measured (F1 99.3, 0.0 % leak) but takes 9.4 s per document, so we used it as the teacher: it labelled a 4,964-document fictional corpus, which, with public OpenPII rows and hard negatives, trained an XLM-RoBERTa base model. It is published as watt-mind/pii-guard-ner-xlmr-base v2.0 and runs in-process for fast mode. Two later retrains (v3, v3.1) were scored on a selection set fixed before training; none beat v2.0 on every gate, so v2.0 stays.
- We also fine-tuned Muse Glimmer itself (LoRA, 3,883 fictional documents) to answer without reasoning: 2.2x faster than zero-shot Glimmer (agent traffic p50 1.03 s vs 2.28 s) but it leaks 1.0 % of values against 0.4 % with the rules in front, so the small NER (0.13 % at 0.02 s) stays the product.
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
- Measured against Presidio, LLM Guard and PrivAiTe with one scorer: on the hand-written set fast mode leaks 0.0 % against PrivAiTe 12.7 %, Presidio 24.3 % and LLM Guard 45.1 %; on public test sets 0.7 % vs 4.0 % (Nemotron-PII) and 0.4 % vs 4.4 % (CEE-PII, best other tool). It is behind or level where it is weak: finance text (19.1 % vs Presidio 18.8 %), agent traffic (2.6 % vs PrivAiTe 2.4 %), and Ai4Privacy-style text it has not seen (13.8 % for the same recipe trained without those rows, vs PrivAiTe 9.5 %).
- Images: portraits, signatures and machine-readable zones on 65 official specimen IDs masked at 90.8 %, 83.8 % and 80.0 % (MRZ with the LLM detector), against 55–57 %, 46–49 % and at most 10 % for Eka PII Redaction; each masked region can carry the text session's placeholder, so a model told "which parties have an ID on file?" got 3 of 3 right with labelled images and 1 of 3 with black boxes.
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
- Fewer false alarms in fast mode: reference and tracking numbers without a cue word are read as IDs (39.4 % over-masking on CEE-PII, 14.0 % on agent traffic).
- Better finance coverage (19.1 % leak on Gretel finance) and an NER that generalises to unseen Ai4Privacy-style text (13.8 % held out).
- A reader for security-printed ID cards: OCR returns no word for 108 of 274 specimen text values.
- Polish next: on the public pl-pii-bench set fast mode leaks 17.5 %, nearly all national ID numbers, which a Polish language pack with checksum validators covers.
- Publishing the package to PyPI, so `uvx --from wattmind-pii-guard pii-guard up` is the one-command start.
- Confirming the hosted endpoint's data-retention terms before recommending it for real data.
```

## Links

| Field | Link |
|---|---|
| Repository | https://github.com/watt-mind/pii-guard |
| Why PII Guard (evidence for every claim) | https://github.com/watt-mind/pii-guard/blob/develop/docs/why-pii-guard.md |
| Benchmarks (every run, with charts) | https://github.com/watt-mind/pii-guard/blob/develop/docs/benchmarks.md |
| Journey (milestones, before/after numbers, spend) | https://github.com/watt-mind/pii-guard/blob/develop/docs/journey.md |
| Models (which Meta model does what) | https://github.com/watt-mind/pii-guard/blob/develop/docs/models.md |
| Demo video | *to be added by the owner* ([shot list](demo-script.md)) |

## Owner checklist before submitting

- Re-read every number against [benchmarks.md](benchmarks.md) and
  [why-pii-guard.md](why-pii-guard.md) (why-pii-guard.md still carries some older figures).
- Switch the links from `develop` to the submitted branch or tag if the form asks for a fixed
  version.
- Record the video from [demo-script.md](demo-script.md) and add its link.
