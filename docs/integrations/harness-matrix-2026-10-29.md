# Real harnesses through the gateway: re-run (2026-10-29)

LAB-1475. The [2026-10-28 matrix](harness-matrix-2026-10-28.md) (LAB-1469) ended with 7 of 15
agent turns refused by the model. Since then two fixes merged: the gateway's placeholder note
(LAB-1471, #215) and the agent-text guards that stop the NER masking file names, paths and tool
names (LAB-1470, #216). This is the same task, the same harness versions and the same setup,
run again on `develop` with both fixes in.

## Setup

As on 2026-10-28 ([setup](harness-matrix-2026-10-28.md#setup)), with these differences:

| | |
|---|---|
| Date | 2026-10-29 (UTC) |
| Gateway | `pii-guard up --upstream-url <recorder> --traffic-log masked`, `develop` at `944effc` (#215 and #216 in), then this branch for the runs after the fix below |
| Detection | fast mode: rules + NER `watt-mind/pii-guard-ner-xlmr-base@95f612a9ad65`; the placeholder note on (the default) |
| Harnesses | pi 1.3.0, OpenCode 1.18.26, Codex 0.163.0 ¹, Muse Code 1.4.14. Claude Code is still not testable (LAB-1313); aider was not run |
| Task | turn 1 `contacts.json` with name, email, iban and tax_id of two fictional customers, `cat` it, reply with the German email; turn 2 insert `"verified": true` after the first email with the edit tool. The original file name: on 2026-10-28 OpenCode only finished after a rename to `records.json` |
| Upstream calls | 123 in total (budget about 100): 115 agent requests through the gateway, 8 for the A/B below. 67 of the 115 went to one OpenCode turn that looped on the bug fixed here. No `--check` canaries this time: the `connect` code is unchanged since 2026-10-28 |
| Isolation | as before: scratch `HOME`, `XDG_*`, `CODEX_HOME`, `PI_CODING_AGENT_DIR`, `--muse-dir`; pi and OpenCode under the `sandbox-exec` profile, Codex and Muse in their own workspace sandboxes |

¹ The `codex` on the machine (0.116.0) still does not start (its native binary is missing,
`spawn .../codex-darwin-arm64/.../codex ENOENT`). As on 2026-10-28, the run used 0.163.0 from
a scratch npm prefix; no global tool was reinstalled.

## Matrix

"Masked" means none of the 9 fictional values appeared in any body the upstream received.
A turn counts as **refused** when the model declined all or part of it, as on 2026-10-28.

| Check | pi | OpenCode | Codex | Muse Code |
|---|---|---|---|---|
| Request masked upstream | pass (0 of 9, 7 requests) | pass (0 of 9, 76 requests) | pass (0 of 9, 17 requests) | pass (0 of 9, 15 requests) |
| Refused turns, 2026-10-28 → now | 4 of 6 → **0 of 2** | 3 of 4 → **0 of 3** | 0 of 2 → **0 of 3** | 0 of 3 → **0 of 2** |
| Turns finished, now | 2 of 2 | 3 of 3 (1 after a 67-request loop) | 1 of 3 | 2 of 2 |
| Restored values in the answer and the files | pass | pass | pass (turn 1) | pass |
| Streaming, multi-turn | pass | pass | pass | pass |
| Tool calls and file edits | pass (`read`, `write`, `bash`, `edit`) | pass (`read`, `write`, `bash`, `edit`) | turn 1 pass; turn 2 fail ([LAB-1481](https://linear.app/watt-mind/issue/LAB-1481)) | pass (`read_file`, `write_file`, `bash`, edit) |

**Refusals: 7 of 15 agent turns → 0 of 10.** No model reply declined to copy, `cat` or repeat a
value. Every request that carried a placeholder carried the note. 0 of 10 means "rare", not
"never": these are 10 turns, not a benchmark.

**Finished: 8 of 10 turns**, all four harnesses at least once. The two that did not finish
were Codex turns, for two different gateway reasons, below. Neither was a refusal.

| Run | Turn 1 | Turn 2 |
|---|---|---|
| pi | pass, 4 requests | pass, 3 requests (`edit` with a restored `oldText`) |
| OpenCode, before the fix | pass, after 67 requests: "fixing the German tax ID" again and again | not run (budget) |
| OpenCode, after the fix | pass, 6 requests | pass, 3 requests |
| Codex, before the fix | stopped by the run's call cap after 8 requests: "the IDs shifted between reads" (the file itself was right) | not run |
| Codex, after the fix | pass, 3 requests | fail: a regex-escaped placeholder in `sed` was not restored; stopped by the cap after 6 requests with `"verified": True` in the file |
| Muse Code | pass, 9 requests | pass, 6 requests |

## What broke, and the fix

**One value, two placeholders.** The NER typed the German customer's Steuer-ID as an
`ID_DOCUMENT` in `customers.md` (as OpenCode's `read` prints it, with line numbers), and the
same digits as a `NATIONAL_ID_HU_TAX` in the `"tax_id"` field of the JSON the agent wrote. The
vault keyed entries by type and value, so the model saw `[[ID_DOCUMENT_a37762]]` in the source
and `[[NATIONAL_ID_HU_TAX_a4c6a5]]` in its own file. It "corrected" the copy; the gateway
restored it to the same digits; the next `cat` showed the other placeholder again. OpenCode
went round 67 times before it settled; Codex said "the IDs shifted between reads". The value
never leaked: both placeholders stood for it.

The fix ([`vault/vault.py`](../../src/pii_guard/vault/vault.py), `IDENTIFIER_TYPES`): within a
session, a number-like identifier value (phone, date of birth, national IDs, ID documents,
bank accounts, company IDs, parcel numbers, plates) keeps the placeholder it got first when a
detector reads it as another of these types. Names, addresses, emails and organizations keep
their own keys. Tests:
[`tests/vault/test_vault_identifier_types.py`](../../tests/vault/test_vault_identifier_types.py).
After it, OpenCode finished both turns in 9 requests and Codex its first turn in 3.

## The A/B: is a person placeholder the trigger?

LAB-1471's check through the gateway named the customers "Customer 1" and "Customer 2" and saw
no refusal even without the note, which suggested that a person placeholder next to an
identity number is what makes the model refuse. Tested here on the two LAB-1471 turns that
refused most (`pi-add-taj`, `pi-create-contacts`), placeholders only, **without** the note
(with it, LAB-1471 measured 0 of 15, so there is nothing left to compare), 2 repetitions:

| Condition | OK | Refused |
|---|---|---|
| `baseline`: `[[PERSON_…]]` placeholders | 4 of 4 | 0 of 4 |
| `labels`: "Customer 1" / "Customer 2" instead | 2 of 4 | 2 of 4 (`pi-add-taj`, both times) |

The hypothesis is **not supported**. With the names gone, the model still declined to copy
the TAJ szám ("a sensitive Hungarian social security identifier"); the field name next to the
value is enough. The sample is small, 4 turns an arm, and the baseline's 0 of 4 is lower than
LAB-1471's 4 of 6 on the same turns, so it says only that removing person placeholders does
not prevent the refusal. The note does, and it stays the fix
([record](../../eval/results/2026-10-29-lab-1475-harness-rerun/probe-person-labels.json),
`scripts/probe_placeholder_refusals.py --conditions baseline,labels`).

## What still goes wrong (filed)

- **A regex-escaped placeholder is not restored**
  ([LAB-1481](https://linear.app/watt-mind/issue/LAB-1481)). Codex has no edit tool; for turn 2
  the model wrote `sed 's/"email": "\[\[EMAIL_947786\]\]",/…/'`. The gateway restores
  `[[EMAIL_947786]]`, not `\[\[EMAIL_947786\]\]`, so the pattern matched nothing on disk.
- **Over-masking left after LAB-1470**
  ([LAB-1482](https://linear.app/watt-mind/issue/LAB-1482)). Not in the task text any more, but
  in request metadata and commands: the first segment of UUIDs in Codex's `prompt_cache_key`
  and `client_metadata` as `PHONE`, a millisecond timestamp as `BANK_ACCOUNT`, a JSON `false`,
  `python3` in a shell command and an npm scope in pi's install path as `PERSON`. None of them
  changed what an agent did here.
- **Claude Code** still needs a Messages API adapter
  ([LAB-1313](https://linear.app/watt-mind/issue/LAB-1313)).

## Notes for running it again

The drivers are short shell scripts around the commands in
[Notes for each client](harness-matrix-2026-10-28.md#notes-for-each-client): a local recorder
on another port adds the key, logs every forwarded body and refuses new requests past a call
cap; each harness turn records the count before and after, and a checker greps the logged
bodies for the 9 values. Set a per-turn cap: a loop like the one above spends the budget in
minutes. Muse Code takes `--max-model-steps`.
