# Digits inside a hash are not a TAJ number (2026-10-28)

LAB-1282. **Before:** fast mode masked 14 spans in the repository's own `uv.lock`: 13
`NATIONAL_ID_HU_TAJ` and one `ID_DOCUMENT`. Each one was a run of digits inside a sha256 hash
(`…885d392771036a9d…`) that passed the TAJ or the personal-ID check digit. A mod-10 check
passes for one digit run in ten, and a lockfile has thousands of them. A coding agent reads
lockfiles, and a placeholder that lands in a hash corrupts the file if the agent writes it back
unrestored. **After:** 0 masked spans
([before](../../examples/coding-agents/runs/2026-10-28-uv-lock-overmask-before.json),
[after](../../examples/coding-agents/runs/2026-10-28-uv-lock-overmask-after.json)).

- **Fix.** The shared number boundaries `NUM_START` and `NUM_END` (`detect/rules/_base.py`)
  already refused a number that continues a longer run of digits. Now they also refuse one
  that touches a letter or `_`, because those digits belong to a longer token. Every language
  pack's number rules use these boundaries, and so does the TAJ rule. The phone rules already
  refused a letter before the number. Now they refuse one after it as well, which catches a
  UUID tail like `…-0632086141e2`. The cued-number matcher already worked this way ("Nr123").
- **Other hashes.** We also ran 12,000 fictional hashes, 2,000 of each kind: sha256 lock
  hashes, git SHA-1s, image digests, UUIDs, sha512 base64 integrity strings and md5 ETags. They
  went from 75 masked spans to 0 in `en` and `hu` (72 TAJ, 2 tax ID, 1 phone), and from 90 to 0
  in `de`. `ui/pnpm-lock.yaml` stays at 0, since its hashes are base64. The repository's own
  `src/` and `.github/` stay the same in `en` and `hu`. In `de` they lose 4 phone hits, all on
  the `"0123456789abcdef"` alphabet string.
- **What didn't move.** The quality gate has the same leak and over-masking in all 6 suites.
  Agent-traffic-dev (rules) leak stays at 44.9 % and over-masking at 0.1 %.
  `tests/detect/test_rules_hash_tokens.py` checks both sides: the hash shapes give no spans,
  and the same values standing alone (after a cue, in JSON, after `=`, with a `-as` suffix)
  are still masked.
- **Cost:** $0, rules only and offline.
