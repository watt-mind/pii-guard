# NER v4.2 published and pinned: what changes against v2.0 (2026-10-30)

LAB-1625. The owner published B3 as `watt-mind/pii-guard-ner-xlmr-base` tag `v4.2` (revision
`33ef18fe`, weights SHA-256 `40e8406c…`) after seeing the regressions below, and fast mode now
pins it. v2.0 (`95f612a9`) stays pinned as `ner_resolve.PREVIOUS_PUBLISHED`, so a rollback is
one setting and still checks the weights' hash.

**v2.0 → v4.2**, same commit, CPU, rules + model (fast mode), leak / over-masking %:

- **Better:**
  - agent traffic (990): 0.31 / 1.40 → 0.21 / 0.74, with no leaks left on valid- or
    invalid-checksum identifiers;
  - agent-traffic-dev: over-masking 1.66 → 0.66 at the same 0.13 leak;
  - Nemotron-PII: leak 0.72 → 0.57;
  - CEE-PII: over-masking 12.4 → 7.3;
  - Hungarian inflection: leak 2.0 → 0.0;
  - EU gate sets: leak 0.95 → 0.32;
  - MAPA (report-only): over-masking 55.5 → 44.7;
  - Polish with the model alone (pl-pii-bench): leak 22.7 → 13.3.
- **Same:** hand-written smoke (62, with Polish), 0.0 leak; Ai4Privacy 0.37; Gretel 19.1 (2.4
  with corrected labels). CPU latency is equal within noise: 42.8 / 49.6 ms against
  42.3 / 48.8 ms per message (p50 / p95, alternating run).
- **Worse:**
  - CEE-PII leak 0.40 → 0.79 (0.8 % of values);
  - the model alone on CEE-PII: 1.59 → 10.52, the largest regression;
  - pl-pii-bench: 3.52 → 4.24;
  - TAB: 4.03 → 5.13 (two of 40 documents' values);
  - MAPA: 8.24 → 8.51;
  - smoke over-masking: 0.87 → 1.32;
  - Gretel over-masking: 21.8 → 24.4.
  None of these sets is a release gate. Every gate passed.

Dev images pull the model when they are built (`Dockerfile.hosted`), so a deployment picks up
v4.2 only after a rebuild.

Evidence: [results README](../../eval/results/2026-10-30-lab-1625-ner-v42/README.md) (section
"B3 on every published set"), [model card](../../training/ner/model-card.md).
