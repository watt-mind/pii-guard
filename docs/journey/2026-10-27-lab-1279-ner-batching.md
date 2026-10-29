# A coding agent's first request detects 4x faster (2026-10-27)

LAB-1279. **A coding-agent request (a system prompt and 15 tools) has 41 different texts, and
fast mode ran the NER model on them one at a time.** Each text was its own worker job and took
the model lock for one forward pass with batch size 1. On a new session (every request of a
client without sticky sessions, and the first turn of every other one) that was most of the
time pii-guard added to the request.

- **One job, batched forwards.** Fast mode now sends all uncached texts of a request as one
  job. The NER model tokenizes them together and runs their windows longest first, in
  micro-batches of up to 8 windows, 4,096 tokens, and no more padding than real tokens (so the
  system prompt does not pad seven short tool texts to its length). 41 forward passes become 6.
  Audit mode keeps one job per text, because its LLM detector is remote.
- **Softmax on the CPU.** The logits go to the CPU once per batch, and softmax and argmax run
  there, which saves a device sync on Apple MPS.
- **Same spans.** On the 652 smoke and ai4privacy documents, plus one text of several windows,
  batched detection gives the same spans as detection one text at a time, on CPU and on MPS.
  Scores differ by at most 2e-5, from the padding.

Measured with the NER v2 checkpoint on an M1 Max under load, `develop` and the fix alternated
three times per device (medians):

| | CPU | MPS |
| -- | -- | -- |
| Agent request, detect stage | 1,285 → 292 ms (4.4×) | 409 → 91 ms (4.5×) |
| One message, detect p50 (`bench latency`, c=1) | 31.5 → 31.8 ms (no change) | 17.9 → 17.0 ms (−5 %) |

- **Cost:** $0.
