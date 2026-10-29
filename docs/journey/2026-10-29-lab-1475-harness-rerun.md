# Real coding agents stop refusing, and one value gets one placeholder (2026-10-29)

LAB-1475, the re-run LAB-1471 asked for. The same task and the same four harnesses as LAB-1469
(pi 1.3.0, OpenCode 1.18.26, Codex 0.163.0, Muse Code 1.4.14), through `pii-guard up` in fast
mode against `muse-spark-1.3`, now with the placeholder note (LAB-1471) and the agent-text
guards (LAB-1470) in ([matrix](../integrations/harness-matrix-2026-10-29.md)).

- **Refusals: 7 of 15 agent turns → 0 of 10** (pi 4 of 6 → 0 of 2, OpenCode 3 of 4 → 0 of 3,
  Codex 0 of 2 → 0 of 3, Muse 0 of 3 → 0 of 2). LAB-1471 had shown 5 of 15 → 0 of 15 on a
  replay; this is the first measurement on the real agents. OpenCode finished the task as
  written, `contacts.json` included, without the rename LAB-1469 needed.
- **Finished: 8 of 10 turns.** The re-run found a vault bug: the NER read one Steuer-ID as an
  `ID_DOCUMENT` in the source file and as a `NATIONAL_ID_HU_TAX` in the JSON the agent wrote,
  and the vault, keyed by type and value, gave it two placeholders. The model kept "fixing"
  the copy: one OpenCode turn took 67 requests, a Codex turn ran out of its cap. Now a
  number-like identifier keeps its first placeholder under any other identifier type
  ([vault.py](../../src/pii_guard/vault/vault.py), `IDENTIFIER_TYPES`); after it, OpenCode
  finished both turns in 9 requests and Codex its first in 3. The other unfinished turn is a
  regex-escaped placeholder in a Codex `sed` command that the gateway does not restore
  (LAB-1481).
- **Masked:** none of the 9 fictional values in any of the 115 requests the upstream received.
  Over-masking is out of the task text; what is left is in request metadata and commands
  (Codex's UUIDs as `PHONE`, `python3` as `PERSON`; LAB-1482).
- **The A/B, person placeholders vs "Customer 1/2" labels (no note):** 0 of 4 vs 2 of 4
  refused. Taking the names out did not stop the model declining to copy a TAJ szám, so the
  hypothesis that a person placeholder is the trigger is not supported. The note stays the fix
  ([record](../../eval/results/2026-10-29-lab-1475-harness-rerun/README.md)).
- **Cost:** 123 calls to the Meta Model API (budget about 100; 67 of them in the loop above),
  free credits. Codex 0.116.0 on the machine still doesn't start; 0.163.0 ran from a scratch
  prefix.
