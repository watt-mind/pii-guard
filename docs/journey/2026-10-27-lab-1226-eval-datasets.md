# Six more test sets, with confidence intervals (2026-10-27)

LAB-1226. Until now, every headline number came from our own fixtures plus one public sample
(Ai4Privacy). Now a dataset registry ([datasets.md](../datasets.md)) adds four permissive public
test sets and a seeded generator for agent traffic. Each set records its source, pinned
revision, license, label mapping and split. Every system runs on every set, and each rate
carries a bootstrap 95 % interval ([benchmarks.md](../benchmarks.md#results-per-dataset)).

The four public sets:
- **Gretel finance**: en/de, Apache-2.0.
- **Nemotron-PII**: en, CC-BY-4.0.
- **CEE-PII-Bench**: hu/en, Apache-2.0. These are checksum-valid TAJ numbers with noise.
- **TAB**: real ECHR judgments. The annotations are MIT; the documents are fetch-only and
  never committed.

The generator writes **agent traffic**: 330 test documents per language in hu/en/de, plus a
dev split on another seed. The shapes are tool-call JSON, YAML, CSV, logs, code, email
threads, chats and inflected names. 15 % of the checksums are invalid and 18 % of the values
are perturbed. Hard negatives include public companies.

| Leak %, 95 % CI | rules | **fast** | Presidio | LLM Guard | PrivAiTe |
|---|---:|---:|---:|---:|---:|
| `agent-traffic` (990) | 45.3 | **2.6** (2.1–3.1) | 12.4 | 20.2 | 2.4 |
| `nemotron-pii` (300) | 56.0 | **0.7** (0.1–1.4) | 12.8 | 28.8 | 4.0 |
| `cee-pii` (451) | 40.9 | **0.4** (0.0–1.0) | 36.5 | 75.8 | 4.4 |
| `tab-echr` (40) | 100 | **3.3** (0.3–8.4) | 4.8 | 37.4 | 15.0 |
| `gretel-finance` (400) | 80.7 | **19.1** (15.4–23.0) | 18.8 | 59.3 | 27.6 |
| `ai4privacy` (600) | 63.1 | **0.4** (0.1–0.7) | 29.6 | 43.8 | 9.5 |

- **Fast** is rules + NER v2 base + hard negatives (milestone 37). It has the lowest leak on
  four sets and is within the interval of the best on the other two (PrivAiTe on agent
  traffic, Presidio on Gretel). Its p50 is 17–65 ms per document, and 192 ms on the long TAB
  judgments. These were measured on a busy M1 laptop, so read them as rough figures.
- **Ai4Privacy's 0.4 % is in-distribution.** NER v2 trained on OpenPII train rows (milestone
  37). The new sets are the honest unseen numbers.
- **Over-masking is the cost.** It's 14.0 % on agent traffic, against 35–37 % for
  Presidio and PrivAiTe. On CEE it's 39.4 %, because NER v2 tags uncued tracking and
  reference numbers as account or ID numbers (LAB-1293).
- **Gretel's labels are incomplete.** Every system over-masks on it, and 19 % leak is the
  weakest result.
- **Perturbed values leak more.** On agent traffic, fast leaks 13.7 % of perturbed values
  (homoglyphs, zero-width spaces, spaced digits, leetspeak email) against 2.4 % for PrivAiTe
  (LAB-1297). It also leaks 8.5 % of invalid-checksum ids against 4.9 % of valid ones.
- **Audit mode** (fast + Muse Spark 1.3 on the Meta Model API) ran on a 10-per-language
  sample of each synthetic set: 0 % leak on agent traffic, CEE and Nemotron, and 26.7 % on
  20 Gretel documents. TAB was never sent. Read these numbers as a smoke test; their
  intervals are wide.
- **Split discipline:** a test asserts that no `test` document's hash appears in the NER v2
  training inputs, the rule fixtures or any `dev` split.
- **Cost:** $0. 110 audit documents on free Meta API credits; everything else ran
  locally.
