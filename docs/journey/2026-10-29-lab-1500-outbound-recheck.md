# The gateway re-checks every masked request before it leaves (2026-10-29)

LAB-1500. **Before:** the gateway failed closed on every error it could see: a detector that
timed out, a field it could not mask, an image without OCR. Nothing checked the result,
though. If masking ran without an error and still left a value, for example through a bug in a
write-back, a tool-argument re-serialisation or an image transcript, that value went upstream
real and nobody would know. **After:** once the request is masked, the gateway reads it again
and searches every text in it for the values its vault session knows. If one is still written
out, the request is refused. That gives a checked "nothing real is left" on every request.

- **Same walker, same patterns.**
  [`gateway/outbound.py`](../../src/pii_guard/gateway/outbound.py) re-reads the masked body with
  the request walker that masked it, so it sees what masking saw: messages, tool definitions,
  tool-call arguments, tool results, reasoning, metadata, and the transcript and summary sent
  after a masked image. That covers Chat Completions and the Responses API, streamed or not.
  It searches with
  [`VaultSession.unmasked`](../../src/pii_guard/vault/vault.py), which uses the sweep's own
  occurrence patterns, folding and guards. It is not a second detector. The values are the
  ones detected in this request and in earlier ones, plus the known values the operator
  pre-loaded. Placeholders never count.
- **What the client sees.** `422 outbound_check_failed` with types and counts only ("PERSON
  (1)"), `X-PII-Guard-Outbound-Check: blocked`, and nothing is sent upstream. A streamed request
  gets the same JSON error, because the stream was never opened. A session that the refused
  call created is dropped. A request that passes carries `X-PII-Guard-Outbound-Check: passed`.
  The traffic event has `outbound_check` (result, texts, hits, short, ms), and so does the Logs
  detail.
- **Short values don't refuse requests.** A value only the NER found needs 4 letters or
  digits to block, a number needs 6 digits, and any other value needs 3. A known value always
  blocks. Shorter occurrences are counted, not blocked. The exemptions that masking makes on
  purpose (product names and paths for NER-only values, ids the upstream issued, declared tool
  names in identifiers) apply here too, so the check never refuses what masking kept on
  purpose.

Fast mode (rules + NER `watt-mind/pii-guard-ner-xlmr-base@95f612a9ad65`), local CPU, through
the real gateway against a mock upstream
([results](../../eval/results/2026-10-29-lab-1500-outbound-check/README.md)):

| set | requests | false blocks (one session per document) | false blocks (one session per language) | re-check p50 / p95 |
| -- | --: | --: | --: | --: |
| agent-traffic-dev | 300 | 0 (0.0 %) | 0 (0.0 %) | 0.17 / 0.44 ms |
| smoke hu/en/de | 51 | 0 (0.0 %) | 0 (0.0 %) | 0.12 / 0.43 ms |
| agent-text hu/en/de | 69 | 0 (0.0 %) | 0 (0.0 %) | 0.05 / 0.18 ms |
| synth-sample hu/en | 30 | 0 (0.0 %) | 0 (0.0 %) | 0.75 / 2.59 ms |
| latency corpus | 200 | 0 | — | **0.10 / 0.18 ms** |

Run records:
[agent-text](../../eval/results/runs/2026-10-29-lab-1500-agent-text.json),
[agent-traffic-dev](../../eval/results/runs/2026-10-29-lab-1500-agent-traffic-dev.json),
[smoke](../../eval/results/runs/2026-10-29-lab-1500-smoke.json),
[synth-sample](../../eval/results/runs/2026-10-29-lab-1500-synth-sample.json).

- **Leak, over-masking, recall and precision did not move** on any of the four sets. The
  numbers are equal to LAB-1482's after-runs, because the re-check reads the request and
  changes nothing in it.
- **Cost is well under the 2 ms budget** on the latency corpus. It grows with the request
  and the session: one session that holds 100 agent-traffic documents' values is 0.84 ms p50
  and 2.0 ms p95. `pii-guard bench latency` shows no change above its run-to-run noise.
- **Zero false blocks is expected, and it is not proof of catching anything.** The check
  shares the sweep's matching, so on correct masking it finds nothing. Its value is the case
  where masking is wrong. That is tested with an injected masking fault in each payload kind:
  message, tool definition, tool-call arguments, tool result, image transcript, Responses
  input, streamed and not, and the hosted path. It is not measured here, because no standard
  set contains a masking bug.
- **Cost:** $0, offline.
