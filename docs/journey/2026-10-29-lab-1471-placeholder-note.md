# The model stops refusing placeholders (2026-10-29)

LAB-1471, found by LAB-1469. With every request masked and answered, `muse-spark-1.3` still
ended 7 of 15 real agent turns in a refusal: it read `[[NATIONAL_ID_HU_TAJ_5a63fe]]` as a
sensitive health-insurance identifier and would not copy it into a file, `cat` the file or
repeat an e-mail. The gateway now puts one constant note in front of every request that carries
a placeholder: placeholders are opaque reference tokens, not real data, to be copied exactly as
written, and restored after the answer
([results](../../eval/results/2026-10-29-lab-1471-placeholder-refusals/README.md)).

Five synthetic turns shaped like the failing ones, replayed 3 times each against
`muse-spark-1.3`, placeholders only:

| | refused |
| -- | --: |
| before: typed placeholders, `AGENTS.md` hint only | 5 of 15 |
| neutral labels (`[[REF_<id>]]`) for identifiers and accounts | 4 of 15 |
| **the gateway's placeholder note** | **0 of 15** |
| neutral labels + the note | 0 of 15 |

- **Labels stay.** Neutral labels barely helped: the field names next to a value (`IBAN:`,
  `TAJ szám:`) say what it is anyway. The type keeps helping the model reason, and the grammar
  is unchanged ([ADR 0007, addendum](../decisions/0007-keyed-pseudonyms.md#addendum-2026-10-29-the-placeholder-note-lab-1471)).
- **Nothing more leaves.** The note is a fixed string, added after masking; it holds no value
  and no placeholder. Through the gateway itself (20 calls, fictional values), no value reached
  the upstream and the note was sent exactly when switched on
  (`PII_GUARD_GATEWAY_PLACEHOLDER_NOTE`, on by default).
- **A replay, not a rerun.** The 15 turns mirror the harness run's failures; the harnesses
  themselves were not run again. Answers vary between runs, so 0 of 15 means "rare", not
  "never".
- **Cost:** 80 calls to the Meta Model API.
