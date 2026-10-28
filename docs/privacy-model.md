# Privacy model

> Status: design guarantees; deployment-specific controls must be verified. The hosted launch
> remains gated. See [hosted processing and retention](hosted.md).

## What we protect

Personal data contained in requests to an LLM: in prompt text, uploaded documents and images.
See [entities.md](entities.md) for what counts as personal data.

## Who we protect it from

| Party | Assumption | What pii-guard does |
|---|---|---|
| **The LLM provider** | Honest but curious: may log, retain, or use data for training depending on the tier and terms | Only masked data reaches it |
| **Network observers** between pii-guard and the provider | May see traffic if TLS is misconfigured | Only masked data is in flight; TLS required upstream |
| **Operators reading logs and metrics** | Have access to observability, not to the mapping store | Raw values never appear in logs, metrics, traces or errors |
| **Other tenants** on a shared deployment | Must not correlate data across tenants | Per-tenant keys; placeholders unlinkable across tenants |

## Trust boundary

In a self-hosted deployment, pii-guard itself, its mapping store and its detection models are **inside** the trust
boundary. They see raw data by necessity. That is why detection runs on open-weights models
that can be hosted on infrastructure you control.

If you point the LLM detector at a *hosted* model endpoint, that endpoint is inside your trust
boundary too. Choose one with appropriate terms, or run it yourself.

## Hosted service boundary

A hosted guard receives originals in its Azure process. In private dev, the dedicated TLS
proxy VM also handles originals in memory and is inside the trust boundary; its access/error
content logs are disabled. See [private dev](private-dev.md). Its operators and infrastructure are
inside the trust boundary; "data stays on your infrastructure" applies only to self-hosting.
Local rules and NER process originals in the initial hosted image. The downstream provider
receives masked text, which can still identify someone through missed values or context.
A hosted **detector** endpoint would receive originals and needs separate explicit trust and
terms review. Anonymous hosted traffic uses curated synthetic samples only; editable text and
session-only BYOK require an authenticated owner. Hosted image/upload routes are disabled.

The initial hosted runtime scales from zero to one replicas with one worker and ephemeral
owner state. Each owner also retains up to 50 masked traffic events in memory, released on
owner purge or restart; masked payloads may contain detection misses or identifying context. Restart loses
mappings, temporary profiles and API-key records. Logical deletion/expiry does not promise
physical memory erasure; raw-value caches are a known limitation (LAB-1364). No content archive
or mapping backup is provisioned. A durable marker-only share prevents reuse of sponsored
allocations after restart; this is not durable multi-tenant vault storage (LAB-1376). Key Vault
secret recovery and Azure/provider retention are separate from input retention. See
[hosted.md](hosted.md) for actual controls, lifecycle, deployment gates and policy review.

Hosted downstream privacy claims must also match the provider contract: Meta Standard's
no-training terms do not establish zero retention or EU-only processing. Sponsored proxy use
remains gated on written provider authorization; see [hosted.md](hosted.md).

## Local-only detection boundary

Self-hosting and hosted service are the two deployment choices. A self-hosted guard can still
send original content to a configured remote detector. The explicit
`PII_GUARD_DETECTION_PROFILE=local-only` profile restricts the supported raw-processing
components without changing the downstream model choice. The default `standard` profile
retains configurable remote detection.

| Stage | Local-only processing and data boundary |
|---|---|
| Text detection | Built-in rules and in-process Transformers NER see original text. Local checkpoint loading cannot fetch weights; missing components refuse the request. Explicit rules-only has reduced coverage. |
| OCR | Built-in local Tesseract sees original image pixels; extracted text uses the same permitted text detectors. Missing OCR/languages refuse processing. |
| Image segmentation | Local YuNet sees original pixels. Remote SAM and hybrid segmentation are refused; unsupported requested visual masks are refused. |
| Mapping store | The guard's existing local vault holds reversible text mappings under the configured tenant key. The profile does not add persistence or alter retention. |
| Downstream model | Receives masked text and re-encoded masked images. This separately selected endpoint may be external; missed entities or deliberately kept types can remain visible. |
| Response restoration | The guard restores recognized placeholders using its mapping store before returning the response. |

Model downloads are provisioning traffic, separate from inference on user content. Operators
must provision trusted local weights and dependencies first. There is no automatic remote
fallback. The profile enforces the supported built-in component configuration; it does not
sandbox arbitrary Python extensions or replace host network controls. For fully local
end-to-end inference, the downstream model must also run locally.

Local image support is limited. YuNet detects faces and estimates ID-photo bounds; signatures
and stamps are unsupported. The existing default signature mask policy causes refusal, not a
silent coverage downgrade. In the published local segmentation evaluation, portrait-region
recall was 100% on 24 fictional images and 92.3% on 65 official specimen images; region leak
rates were 0% and 10.8%, respectively. These are visual-region results without OCR, not an
end-to-end privacy guarantee. The chosen margins were evaluated on those same sets and may be
optimistic; see [methods and limitations](models.md#local-segmentation). No detector algorithm
or threshold changes are part of this profile.

See [setup and refusal behavior](operations.md#local-only-detection).

## Guarantees

1. **Fail closed.** If extraction, detection, masking or re-identification errors or times
   out, the request is not forwarded.
2. **No raw values in observability.** Logs, metrics, traces and error messages contain entity
   types, counts and placeholder ids only.
3. **Non-guessable placeholders.** Placeholder ids are keyed HMACs; without the key they can't
   be reversed or enumerated.
4. **Image masks are not reversible.** Masked images are re-encoded from pixels and stripped of
   metadata.
5. **Measured, not promised.** Detection is probabilistic, so recall and leak rate are measured
   on the benchmark and published.

## Explicit non-guarantees

- **Detection is not perfect.** A missed value is sent upstream. The published recall and leak
  rate tell you how often that happens on the benchmark; real data may differ.
- **Pseudonymized data is still personal data** under GDPR (Recital 26). pii-guard reduces
  exposure; it does not anonymize.
- **Context can identify people.** "The only female judge at the Kecskemét court" identifies
  someone without containing a name. Quasi-identifiers are out of scope for v1.
- **The response is only as safe as the model.** If the model hallucinates real personal data,
  pii-guard won't remove it.

## Operational guidance

- Use provider tiers whose terms **exclude training on your data** for any real workload. Some
  low-cost tiers (for example contributor or data-sharing tiers) allow the provider to use
  traffic to improve its products; never send real data through them, even masked.
- Keep the mapping store's TTL as short as your workflow allows.
- Rotate tenant keys on a schedule; rotation makes old placeholders unresolvable, by design.
