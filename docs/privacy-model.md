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

A hosted guard receives originals in its Azure process. Its operators and infrastructure are
inside the trust boundary; "data stays on your infrastructure" applies only to self-hosting.
Local rules and NER process originals in the initial hosted image. The downstream provider
receives masked text, which can still identify someone through missed values or context.
A hosted **detector** endpoint would receive originals and needs separate explicit trust and
terms review. Anonymous hosted traffic uses curated synthetic samples only; editable text and
session-only BYOK require an authenticated owner. Hosted image/upload routes are disabled.

The initial hosted runtime is one replica/worker with ephemeral owner state. Restart loses
mappings, temporary profiles and API-key records. Logical deletion/expiry does not promise
physical memory erasure; raw-value caches are a known limitation (LAB-1364). No content archive
or mapping backup is provisioned. A durable marker-only share prevents reuse of sponsored
allocations after restart; this is not durable multi-tenant vault storage (LAB-1376). Key Vault
secret recovery and Azure/provider retention are separate from input retention. See
[hosted.md](hosted.md) for actual controls, lifecycle, deployment gates and policy review.

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
