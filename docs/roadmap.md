# Roadmap

## Hackathon: October 26 – November 4, 2026

Submission deadline: **November 4, 21:00 ET** (03:00 Budapest time on November 5).

| Day | Date | Goal |
|---|---|---|
| 1 | Mon Oct 26 | Repo and docs scaffold. Day-1 checks (below). Code skeleton, CI, rules for structured identifiers |
| 2 | Tue Oct 27 | Fictional identity generator and the Muse document generator; first corpus |
| 3 | Wed Oct 28 | Scorer and eval CLI. **Baseline numbers** for rules and rules + NER |
| 4 | Thu Oct 29 | Prompted Llama detector and the resolver. Measured against the baseline |
| 5 | Fri Oct 30 | Fine-tune the Llama detector on the train split; serve it. Measure |
| 6 | Sat Oct 31 | Vault (keyed pseudonyms, morphology) and gateway with streaming re-identification |
| 7 | Sun Nov 1 | Visual: OCR boxes, SAM 3.1 regions, image masking. Synthetic image set |
| 8 | Mon Nov 2 | End-to-end leak test, demo UI (*what the model saw* vs *what you got back*), hardening |
| 9 | Tue Nov 3 | Buffer, polish, results page, demo video |
| — | Wed Nov 4 | Submit |

**If time runs short, cut in this order:** fine-tuning (keep the prompted detector, still
measured) → visual masking for non-text regions (keep OCR-based text masking) → demo UI polish.
Never cut: the evaluation set, fail-closed behavior, streaming re-identification.

## Day-1 checks

- [ ] Meta Model API access works; which Muse models and tiers are available; quality of
      Hungarian document generation on a few samples.
- [ ] Which small Llama models Fireworks can fine-tune, and the data format it expects.
- [ ] SAM 3.1 weights and license; can it be served on Modal within the credits.
- [ ] Partner credits activated (Baseten, Modal, Fireworks).
- [ ] Official hackathon rules: open-source requirements, use of third-party libraries,
      submission format.
- [ ] Pick the multilingual NER baseline model.

## After the hackathon

- More EU languages (each with rules, morphology and a corpus).
- Quasi-identifier detection (rare attributes that identify someone in context).
- Encrypted shared mapping store for multi-instance deployments.
- PDF output with true redaction (text layer removed, not just covered).
- Published benchmark as a standalone dataset.
