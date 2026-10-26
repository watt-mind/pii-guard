# Vision

## The problem

Professionals who handle other people's data (lawyers, doctors, accountants, HR teams) are
asked to use AI every day, and every day they face the same question: *can I send this
document to the model?* Usually the honest answer is no. Professional secrecy, GDPR and client
contracts all say the personal data in that document must not leave the firm.

So today they either don't use the model, or they paste data in and hope.

Existing PII tools don't close the gap:

1. **Text only.** Real work arrives as scans and photos: ID cards, signed contracts, land
   registry extracts. The personal data in those images goes straight through.
2. **One-way redaction.** Replacing names with `[REDACTED]` breaks the answer. The model
   can't say *which* party has to sign, and the user gets a useless reply.
3. **English first.** Morphologically rich languages break naive matching. In Hungarian a
   name takes suffixes (`Kovács Péternek`, `Kovács Pétertől`), so exact-string tools miss most
   occurrences.
4. **Unmeasured.** Tools rarely publish recall, and almost never an end-to-end *leak rate*,
   so nobody can say how safe they are.

## What pii-guard is

A privacy firewall that sits between an application or agent and an LLM:

- it finds personal data in **text, documents and images**;
- it replaces it with **keyed, reversible pseudonyms** before the request leaves;
- it **restores the real values** in the response, including streamed responses and inflected
  forms;
- it **fails closed**: if anything goes wrong, nothing is sent;
- it **publishes its numbers**: precision, recall and leak rate on an open synthetic benchmark.

Detection runs on **open-weights models you can host yourself**, so the data needed to find
personal data never has to leave your infrastructure either.

## Who it is for

- **Teams building agents** on top of cloud LLMs who need a privacy layer they can drop in
  front of an OpenAI-compatible API.
- **Regulated professionals** (legal, medical, finance, HR) whose tools are built on such
  agents.
- **Researchers** who want an open, reproducible PII benchmark for non-English languages.

## Goals for the hackathon

1. A working gateway that masks text and images and re-identifies streamed responses.
2. Measured detection quality on an open synthetic Hungarian benchmark, with a clear
   improvement from the open-weights LLM detector over a rules + NER baseline.
3. Visual masking of scans and photos with OCR and SAM 3.1.
4. A demo that shows *what the model saw* next to *what the user got back*.

## Non-goals (for now)

- **Anonymization guarantees in the legal sense.** Pseudonymized data is still personal data
  under GDPR. pii-guard reduces exposure, it does not make data anonymous.
- **Inference attacks.** A model may still infer identity from context (a unique job title, a
  rare event). Quasi-identifiers are out of scope for the first version; see
  [privacy-model.md](privacy-model.md).
- **Audio and video.**
- **Every EU language at once.** Hungarian first, built so other languages can be added
  through configuration and their own rules.
