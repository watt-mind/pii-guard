# Models and partners

> Status: proposed. Availability, model names and credit amounts must be confirmed on day 1;
> see [roadmap.md](roadmap.md).

## Which model does what

| Job | Model | Where it runs | Sees real data? |
|---|---|---|---|
| Structured identifiers | Rules (no model) | pii-guard container | yes (inside the boundary) |
| Names, organizations, locations | Multilingual NER model (open) | pii-guard container | yes |
| Second-pass detection and adjudication | **Llama** (small, open weights), fine-tuned | Self-hosted or a hosted GPU endpoint you control | yes |
| Faces, signatures, ID photos | **SAM 3.1** | GPU endpoint | yes |
| OCR | Open OCR engine | pii-guard container or GPU endpoint | yes |
| Synthetic corpus generation | **Muse** (Wonder for documents, Spark for variations) | Meta Model API | **no**: fictional data only |
| The downstream model in the demo | **Muse Spark** | Meta Model API | **no**: only masked data |

The rule behind this table: **anything that sees real personal data is an open-weights model
you can host yourself.** Hosted Meta models only ever see fictional data or masked data.

## Hackathon partners

| Partner | What we use it for |
|---|---|
| **Fireworks** | Supervised fine-tuning of the small Llama detector on the synthetic train split |
| **Modal** | GPU serving for SAM 3.1, and experiment runs |
| **Baseten** | Serving the fine-tuned detector as a dedicated endpoint |

Any of the three can stand in for another; the code talks to model endpoints through
configuration, not vendor SDKs, wherever possible.

## Data-use note

Provider tiers differ in whether traffic may be used to improve the provider's products. For
corpus generation (fictional data) any tier is acceptable. For anything else, use a tier whose
terms exclude training on your data. See [privacy-model.md](privacy-model.md).
