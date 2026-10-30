# Hackathon submission (draft)

> **Draft for the owner to review before submitting.** Evidence checked on 2026-10-30.
> The text below describes the measured configuration, not a guarantee that every identity
> is detected. Freeze the linked source revision and add the approved demo before submission.

## Tagline (≤ 140 characters)

```text
An OpenAI-compatible privacy gateway for existing agents: consistent placeholders across text and images, with restored answers.
```

## Description

```text
PII Guard sits between an existing agent and its answering model. It replaces detected personal data with session-consistent placeholders, then restores known text values in streamed answers and tool-call arguments. The agent can keep relationships between people and documents without needing those original values in its request. Developers connect through an OpenAI-compatible base URL and can inspect masked outbound traffic.

Self-hosted fast text mode uses rules and a small CPU model trained on Meta Muse Glimmer labels and public data. On 990 synthetic agent-traffic documents, v4.2 leaked 0.21% of labeled values and over-masked 0.74%, versus 2.4% and 35.2% for the lowest-leak alternative in that comparison. These results describe one test set, not universal superiority. We publish the run records, evaluation protocol and regressions: CEE-PII value leakage rose from 0.4% to 0.8% against v2.0.

Deployment matters. A self-hosted fast text detector runs locally; the hosted preview receives originals on its server. Remote SAM image segmentation receives unmasked image pixels, and optional remote audit receives original text. Detection can miss values, and reversible placeholders are not anonymization. Apache-2.0.
```

Evidence for the description:

- [Gateway integration and streaming](integrations.md),
  [tool/schema/metadata masking and restoration tests](../tests/gateway/test_request_tools_metadata.py).
- [v4.2 agent-traffic record](../eval/results/runs/2026-10-30-datasets-agent-traffic-fast-v42-b3.json),
  [comparator record](../eval/results/runs/2026-10-30-lab-1656-agent-traffic-privaite.json),
  [published B3 release and regressions](journey/2026-10-30-lab-1625-ner-v42-published.md).
- [Privacy boundaries and limitations](privacy-model.md),
  [hosted processing](hosted.md#what-each-mode-processes),
  [hybrid image processing](models.md#hybrid-vs-sam-only-lab-1245),
  [remote audit terms](models.md#baseten-model-apis-the-audit-mode-detector),
  [licence](../LICENSE).

## How we used Meta models

```text
Muse Glimmer served as a teacher: its labels, public OpenPII data and hard negatives trained our small XLM-RoBERTa CPU detector. The released v4.2 model runs in-process in fast text mode, without a detection API call. After correcting the evaluation protocol, the v4.2 gates and selection rules were fixed before training. B3 passed every release gate and was published and pinned; report-only regressions remain visible.

Meta's hosted answering models perform the downstream task on the guarded request. Recorded examples use Muse Spark 1.3; model passthrough is not a claim that every listed model was tested. Muse Spark Open is an optional audit detector and has also been used in red-team evaluations. If its detector endpoint is remote, it receives original text.

Muse Image created fictional portraits, signatures and textures for synthetic ID specimens. The hybrid image path uses local YuNet for faces and ID-photo bounds and Meta SAM 3.1 for signatures. SAM receives normalized but unmasked pixels. A masked image can carry the same person placeholder as its accompanying text; the original image cannot be reconstructed from that mask.
```

Sources: [model roles and deployment locations](models.md),
[OpenCode integration and recorded live test](integrations/opencode.md#end-to-end-test),
[v4.2 protocol and results](../eval/results/2026-10-30-lab-1625-ner-v42/README.md),
[published model card](../training/ner/model-card.md),
[fictional image provenance](../eval/fixtures/visual/NOTICE),
[image integration and session labels](integrations.md#images-self-hosted-root-gateway-only).

## Measured results and their scope

The agent-traffic comparison uses the same 990 synthetic documents and scorer. **Value
leakage** is the share of labeled values left fully visible; partial leakage is reported
separately in the records. **Over-masking** is the share of masks placed on non-personal data.
Lower is better for both.

| Configuration | Value leakage | Over-masking | Exact record |
|---|---:|---:|---|
| PII Guard fast, v4.2 B3 | 0.21% | 0.74% | [run](../eval/results/runs/2026-10-30-datasets-agent-traffic-fast-v42-b3.json) |
| PrivAiTe | 2.4% | 35.2% | [run](../eval/results/runs/2026-10-30-lab-1656-agent-traffic-privaite.json) |

PrivAiTe is the **lowest-leak alternative among the compared tools on this set**, not the
lowest-over-masking tool or a universally best alternative. The v4.2 record names the B3
candidate at measurement time; the [release milestone](journey/2026-10-30-lab-1625-ner-v42-published.md)
records that those weights were subsequently published and pinned. The full comparison,
including Presidio and LLM Guard, remains in [the benchmark tables](benchmarks.md#agent-traffic).

The hand-written set now contains **62 fictional documents in German, English, Hungarian
and Polish**. Its small size and zero full-value leakage do not establish perfect detection;
partial leaks, over-masking and per-language results are also reported in
[the smoke tables](benchmarks.md#smoke). Training data across more languages is not proof of
equal reliability in every language.

The **43 ms p50** figure is **the NER model alone**, on an Apple M1 Max CPU with roughly
400-character messages, alternating v4.2 and v2.0 in one process on a shared machine. It is
not end-to-end gateway or agent latency. See the [raw latency measurement](../eval/results/2026-10-30-lab-1625-ner-v42/latency-cpu-local.json)
and [measurement context](../eval/results/2026-10-30-lab-1625-ner-v42/README.md#b3-on-every-published-set-lab-1656).

CEE-PII full-value leakage regressed from **0.4% to 0.8%** against v2.0. Finance text is another
known weak area. Keep those limitations alongside the gains; see the
[release report](journey/2026-10-30-lab-1625-ner-v42-published.md) and
[model-card limitations](../training/ner/model-card.md#limitations).

For reproduction: [dataset definitions and labels](datasets.md),
[evaluation methodology](evaluation.md),
[baseline setup and common scorer](evaluation.md#comparison-with-open-source-tools),
[all committed run records](../eval/results/runs/). Records include source commits, fixture
hashes, settings and counts. They let reviewers distinguish configurations and test sets.

## What's novel

```text
- Reversible, session-consistent text placeholders preserve identity relationships and are restored in streamed answers and tool calls, rather than leaving one-way redaction markers.
- Language-pack logic handles Hungarian name inflection; training on multilingual data is paired with language-specific evaluation rather than a blanket coverage promise.
- Labeled image masks can preserve the link to a person mentioned in text, while the masked image itself is irreversible.
- The gateway covers agent surfaces such as tool definitions, schemas and metadata, and refuses unsafe requests when extraction, detection or masking fails.
- A Meta-model teacher is distilled into the small CPU detector used in the request path; measured release gates, rejected rounds and regressions are public.
```

Evidence: [session placeholders and inflection](why-pii-guard.md#1-reversible-placeholders-consistent-for-a-whole-session),
[inflection tests](../tests/vault/test_vault_inflection_hu.py),
[image integration](integrations.md#images-self-hosted-root-gateway-only),
[tool and metadata tests](../tests/gateway/test_request_tools_metadata.py),
[fail-closed design](decisions/0006-fail-closed.md),
[training and evaluation protocol](../eval/results/2026-10-30-lab-1625-ner-v42/README.md).

## Challenges and next steps

```text
The hard engineering trade-off is retaining useful relationships while minimizing exposure. We addressed name inflection, repeated identities, tool-call restoration and image labels, then measured failure cases rather than treating a successful example as a guarantee.

Next priorities are reducing false alarms on uncued reference numbers, improving finance and OCR coverage, and validating more languages independently. Remote detectors and hosted deployments require their own trust and retention review. Self-hosting is a deployment choice, not automatic legal compliance.
```

See [published limitations](../training/ner/model-card.md#limitations),
[privacy model](privacy-model.md) and [hosted deployment gates](hosted.md).

## Links

| Field | Link |
|---|---|
| Repository | https://github.com/watt-mind/pii-guard |
| Try / integrate | [README](../README.md#quickstart), [agent guides](integrations/README.md) |
| Benchmarks and methodology | [tables](benchmarks.md), [methods](evaluation.md), [records](../eval/results/runs/) |
| Training and release evidence | [v4.2 protocol](../eval/results/2026-10-30-lab-1625-ner-v42/README.md), [release](journey/2026-10-30-lab-1625-ner-v42-published.md) |
| Model and trust boundaries | [models](models.md), [privacy](privacy-model.md), [hosted processing](hosted.md#what-each-mode-processes) |
| Repeatable demo and limits | [walkthrough](demo-story.md), [integrations](integrations.md), [synthetic-image notice](../eval/fixtures/visual/NOTICE) |
| Demo video | *Owner adds the approved public URL before submitting.* |

## Owner checklist before submitting

- Freeze the source revision and use immutable links for the submitted evidence.
- Recheck the exact metrics and model pin against the linked records; do not mix test sets,
  old audit results, NER-only latency or full gateway latency.
- Rehearse the submitted route with fictional data and label mock services and recordings.
- Add the approved demo URL. Do not describe an unrecorded workflow as completed.
