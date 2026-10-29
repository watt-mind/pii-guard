# Real coding agents finish their tasks: ids stop reading as phone numbers (2026-10-29)

LAB-1469.

The scripted end-to-end tests passed for every client, but they run without the NER and with
a mock model. With the versions installed on a developer Mac, the published NER and the Meta
Model API (`muse-spark-1.3`, fictional data, 108 upstream calls), three of the four
OpenAI-API agents could not finish one task:

- **Before:** pi refused on its 4th request, Muse Code from its 3rd (then retried for 4
  minutes), Codex on its first, OpenCode on every agent request. The NER read opaque tokens as
  personal data in fields that can't carry a placeholder: upstream call ids (37 of 300 random
  `call_<hex>` ids as PHONE), Codex's own `msg_<uuid>` message ids (59 of 200), and the
  `Number.MAX_SAFE_INTEGER` bounds in OpenCode's tool schemas (BANK_ACCOUNT).
- **After:** 0 refusals by the gateway. Each agent wrote the file with all requested values
  restored, edited it in a second turn, streamed, and none of the 9 values reached the model
  in any of the 108 requests. `pii-guard connect --check` now covers Codex and OpenCode too.
  [Results matrix](../integrations/harness-matrix-2026-10-28.md).
- **How:** ids the upstream issued are remembered per session and forwarded as sent; in a
  prefixed UUID, hex run or number the NER's hits are dropped, rules and the LLM detector
  still apply ([opaque_ids.py](../../src/pii_guard/gateway/opaque_ids.py)).
- **Still open:** the NER over-masks agent text (`contacts.json` as an EMAIL, `JSON` and
  product names as PERSON, path segments as ID numbers; LAB-1470), and the model declines to
  copy values whose placeholder says `NATIONAL_ID` or `BANK_ACCOUNT` in 7 of 15 agent turns
  (LAB-1471). Claude Code needs the Messages API (LAB-1313).
