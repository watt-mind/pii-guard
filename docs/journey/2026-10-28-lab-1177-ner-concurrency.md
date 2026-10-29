# Concurrent requests share the NER model: fast mode at c=8 is twice as fast (2026-10-28)

LAB-1177, found during LAB-1166. **Fast mode got slower the more requests came in at once.**
The NER model has one lock around the tokenizer and the forward pass, so eight concurrent
requests ran eight forward passes one after another, each with one request's texts, and the
last one waited for the seven before it. On the CPU, overhead at concurrency 8 was 7× the
overhead of one request, and throughput stopped growing at concurrency 4.

- **Shared runs, no wait window.** A request that finds the model idle runs at once, as
  before. Requests that arrive while it runs queue up, and the next run takes all of their
  texts as one batch, which the LAB-1279 micro-batching packs into forward passes. Each
  request gets exactly its own spans. The next run is done by the next waiting request's own
  thread, so a request is never kept busy serving later ones.
- **Still one forward at a time.** The tokenizer and the model are still used by one thread at
  a time: two forwards at once on Apple MPS crashed the process (LAB-1274).
- **Errors stay with their request.** If a shared run fails, its requests are run again one at
  a time, so only the request whose text fails gets the error; the others are masked.

`pii-guard bench latency`, fast mode, the published NER v2.0, an M1 Max shared with other
agents. `develop` and the fix alternated three times per device (medians, overhead in ms):

| | CPU | MPS |
| -- | -- | -- |
| c=1, p50 | 35.4 → 35.6 (no change) | 20.8 → 20.7 (no change) |
| c=4, p50 | 92.0 → 70.4 | 16.0 → 17.6 |
| c=8, p50 | 242.6 → 131.2 (1.8×) | 69.1 → 34.5 (2.0×) |
| c=8, p95 | 258.9 → 151.1 | 85.2 → 57.0 |
| c=8, throughput | 26.3 → 40.6 req/s | 62.8 → 81.3 req/s |
| c=8 streamed, p50 (2 runs) | 261–284 → 151–159 | 87 → 45–46 |

Run records: [MPS](../../eval/results/runs/2026-10-28-ner-concurrency-mps-fast.json),
[CPU](../../eval/results/runs/2026-10-28-ner-concurrency-cpu-fast.json).

- **MPS compiles each new batch shape once.** In the c=4 cell, the first cell where requests
  share runs, p95 rose from 25 to 45 ms: shared runs have batch sizes other than 1, and MPS
  compiles a kernel the first time it sees a shape. Three c=4 cells in one process gave a
  NER p95 of 49, 28 and 27 ms. Padding to fewer shapes is LAB-1329.
- **Cost:** $0.
