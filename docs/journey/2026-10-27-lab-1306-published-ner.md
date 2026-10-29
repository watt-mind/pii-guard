# The trained NER is on Hugging Face; v2.1 didn't beat v2 (2026-10-27)

LAB-1306. **Fast mode now downloads pii-guard's own NER from a clean checkout:**
[`hdkiller/pii-guard-ner-xlmr-base`](https://huggingface.co/hdkiller/pii-guard-ner-xlmr-base),
release `v2.0`, revision `95f612a9`, weights SHA-256 `4a9a598f…`. It is step 2 of the NER
resolution order (LAB-1192), so the public stop-gap fallback, which over-masks about 23 % on
en-smoke, no longer runs by default. `make smoke-fast` from an empty model cache downloads it,
checks the hash and masks the NER-only scenario.

**What was published is v2, not the v2.1 retrain.** v2.1 used the same recipe for 5 epochs
instead of 3, with 1,500 more hard negatives per language (`training/ner/negatives_v21.py`):
reference numbers with no cue word, lone street names, and family firms (`és Fia`, `& Sons`,
`& Söhne`) as `ORGANIZATION`. Every epoch was kept. The rule set in advance: lowest leak on
unseen `agent-traffic-dev` with smoke over-masking no worse than v2; on a tie, v2.

| rules + NER, % | agent-traffic-dev leak / over-masking | smoke leak, max | smoke over-masking, max |
| -- | --: | --: | --: |
| **v2 (published)** | **1.7** / 11.9 | **0.0** | 3.0 |
| v2.1, best epoch (5) | 2.4 / 11.2 | 0.9 | 3.0 |
| v2.1, epochs 1–4 | 2.5–4.8 / 9.1–16.6 | 0.9–1.9 | 0.0–6.1 |

- **The negatives fixed what they aimed at.** "Fia" as `PERSON` on hu-company-names went from
  4 spans to 0, the lone "… Street" went away, and cee-pii over-masking fell from 39.4 to
  29.0 %.
- **They cost leak.** Without a cue word, the model also stopped marking real document ids and
  e-mails: uncued `ID_DOCUMENT` leaks on agent-traffic-dev went from 5 to 11, and hu-smoke
  leaked a name. The held-out test sets, scored once after the choice, agree: agent-traffic
  2.6 → 3.4 %, gretel-finance 19.1 → 19.9 %.
- **In-distribution vs held out.** v2's 0.4 % ai4privacy leak is in-distribution (it trained on
  OpenPII train rows). The model card reports it separately from the held-out sets, where v2
  leaks 0.4–2.6 % (19.1 % on finance text) and over-masks up to 39 %.

Full tables: [results README](../../eval/results/2026-10-27-ner-v21/README.md); model card:
[training/ner/model-card.md](../../training/ner/model-card.md) (Apache-2.0, with the
"Ai4Privacy / Ai Suisse SA" attribution OpenPII's CC-BY-4.0 asks for).

- **Cost:** $2.92 of Modal free credits: Muse Glimmer on an H100 to regenerate the s13 corpus
  (whose files had been lost), and one A10G training run.
