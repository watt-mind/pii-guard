# Meta reasoning budget, pricing and the private dev boundary (2026-10-28)

LAB-1372 AC6 (measure before choosing limits), follow-up to LAB-1334. Synthetic text only, no
answer text and no credential recorded. 51 Meta calls in all (one shape probe, the 48-call sweep,
two streaming calls) on the owner's key; about 26 requests to the private dev deployment.

## 1. How `muse-spark-1.3` spends its output budget

[`measurements.json`](measurements.json), produced by:

```
set -a; . ./.env; set +a      # META_API_KEY; never in argv
uv run --no-sync python scripts/measure_meta_reasoning.py --effort low \
  --out eval/results/2026-10-28-lab-1372-meta-reasoning/measurements.json
```

Direct calls to `https://api.meta.ai/v1/chat/completions`, `max_completion_tokens` swept. Four
prompts: the two hosted demo samples as the gateway sends them (masked), and two chat-length
ones (49 to 143 prompt tokens). Two calls per prompt and budget, one at 128.

| max_completion_tokens | calls | empty content | finish=length | median completion | most used by an answered call | median latency |
| --: | --: | --: | --: | --: | --: | --: |
| 128 | 4 | **4** | 4 | 128 | n/a | 1.3 s |
| 256 | 8 | **8** | 8 | 256 | n/a | 1.2 s |
| 512 | 8 | **8** | 8 | 512 | n/a | 1.9 s |
| 1024 | 8 | **6** | 7 | 1024 | 1024 | 3.7 s |
| 2048 | 8 | 1 | 1 | 1,345 | 2,044 | 4.7 s |
| 4096 | 8 | **0** | 0 | 1,470 | 2,338 | 5.9 s |
| 512, `reasoning_effort: low` | 4 | 4 | 4 | 512 | n/a | 2.3 s |

- Reasoning tokens are reported in `completion_tokens_details.reasoning_tokens` and counted
  inside `completion_tokens`. An empty answer is a `finish_reason: length` with all but two
  tokens spent on reasoning, and `message.content: null`.
- `reasoning_effort: low` changed nothing at 512.
- Answered calls used 763 to 2,338 completion tokens, of which the visible answer was about
  60 to 100. The same prompt varies a lot (demo-en: 763 and 1,776 at 2048).
- Streaming through the gateway (section 3) used 944 (chat) and **2,994** (Responses).

**Chosen limits.**

| Limit | Before | Now | Why |
| -- | --: | --: | -- |
| `DEMO_MAX_OUTPUT_TOKENS` (curated demo, reserved and sent) | 512 | **4096** | 512 answered 0 of 8 demo calls, so every sponsored demo would have failed and still been charged. 4096 answered 8 of 8; the most used was 2,994 |
| `PII_GUARD_HOSTED_MAX_OUTPUT_TOKENS` minimum | 1024 | **4096** | Never below the demo's reservation; below that empty answers are the common case |
| `PII_GUARD_HOSTED_MAX_OUTPUT_TOKENS` default | 8192 | 8192 | 2.7× the largest observed use |
| Guest tokens per day | 100,000 | 100,000 | One demo reserves about 8,250 tokens (4,150 input bound + 4,096 output), so five demos take about 41,000 |
| Signed-in tokens per day | 1,000,000 | 1,000,000 | A default request (1 KiB body, 8192 output) reserves about 14,300; a full 32 KiB body about 77,800 |

## 2. Pricing reconciliation

Source: <https://dev.meta.ai/docs/pricing-rate-limits>, read 2026-10-28 (the page shows no date).

| | Meta Standard `muse-spark-1.3` | Reservation default | Margin |
| -- | --: | --: | --: |
| Input | $1.25 / M = 1.25 µ$/token | 5 µ$/token | 4× |
| Output (reasoning included) | $4.25 / M = 4.25 µ$/token | 30 µ$/token | 7.1× |
| Cached input | $0.15 / M | charged as input | — |
| Muse Wonder 1.0 (not allowlisted) | $4.00 / $20.00 per M | 5 / 30 | 1.25× / 1.5× |

- The page lists no separate reasoning price. The API reports reasoning inside
  `completion_tokens`, so the reservation charges it at the output rate.
- There is no long-context premium and no minimum.
- Web search grounding costs **$2.50 per 1,000 queries** on top of tokens. A token reservation
  cannot bound that, so sponsored requests may no longer ask for provider-side tools
  (`web_search_options`, or a `tools` entry other than `function`/`custom`). They are refused
  `403` before any work.
- The rate limits are 3,000 RPM and 4,000,000 TPM per team. The response headers matched
  (`x-ratelimit-limit-requests: 3000`).

**Per demo**: reserved 4,148 × 5 + 4,096 × 30 = 143,620 µ$ (about $0.14). The worst answered
demo actually cost 67 × 1.25 + 1,776 × 4.25 ≈ 7,600 µ$ (about $0.008), so the reservation is
about 19× above it. A USD 10 allocation therefore admits about **69 sponsored demos**, because
reservations are never refunded. The operator can lower the rates within the documented bound
(for example 2 / 9 µ$, still 1.6× / 2.1× Meta's price) through
`PII_GUARD_HOSTED_INPUT_/OUTPUT_MICRODOLLARS_PER_TOKEN`. That gives about 220 demos. The
defaults stay conservative.

## 3. Live streaming through the gateway

`pii-guard up --upstream meta` on a free loopback port. Fast mode, one call each:

| Route | status | events | finish | first text | total | usage | original restored, no placeholder leaked |
| -- | --: | --: | -- | --: | --: | -- | -- |
| `/v1/chat/completions`, `stream_options.include_usage` | 200 | 13 | stop | 9.0 s | 9.3 s | 59 in / 944 out (880 reasoning) | yes / yes |
| `/v1/responses` | 200 | 24 | completed | 12.5 s | 12.8 s | 59 in / 2,994 out (2,925 reasoning) | n/a (model did not repeat the address) / yes |

Reasoning produces no visible stream events. The first text arrives after 9 to 13 s, well
inside the 180 s hosted deadline. The local server log had no prompt text, address or key.

A **signed-in** streaming check on dev was not run. It needs a Google browser sign-in, and dev
sponsorship is 0 until the LAB-1398 allocation exists.

## 4. Private dev boundary (`proxy_headers`)

[`dev-boundary.json`](dev-boundary.json). From a tailnet Mac with no sign-in, through
`guard-dev.watt-mind.com` (Tailscale, then router VM, then ACA, then Easy Auth), revision
`piiguard-dev-app--0000005`. Each probe carried a valid-shaped forged Google
`X-MS-CLIENT-PRINCIPAL`, `X-MS-CLIENT-PRINCIPAL-ID/-NAME/-IDP`, `X-MS-TOKEN-GOOGLE-*`, the
app's `X-Pii-Guard-External-Host/-Proto`, `X-Forwarded-For/-Host`, `Forwarded`, `X-Real-IP`,
`X-Original-URL` and `X-Arr-SSL`.

- `/v1/account` stayed `authenticated: false`, with a fresh guest cookie. `/v1/status`,
  `/v1/projects`, `/v1/mask`, `/v1/chat/completions` and `/v1/account/api-keys` (GET and POST)
  returned `401`. `/v1/demo` ran as a guest (`503 sponsored_unavailable`, sponsorship 0).
- Forged guard keys (`Authorization: Bearer pg_…`, `pg_ep_…`, `X-PII-Guard-Token`) and a forged
  `AppServiceAuthSession` cookie were refused or left anonymous.
- Duplicates:
  - two `Authorization` headers were refused by the router with `400`;
  - two principals or two Cookies stayed anonymous;
  - for two Origins, two connection IDs or two tokens, the router forwards only the first
    value, and the request was refused or stayed anonymous. The app's own duplicate-header
    `403` is therefore not reached through this router; nginx's first-value collapse is what
    applies.
- A cross-origin demo POST was refused with `403`. Google sign-in under forged host headers
  still used `redirect_uri` on `guard-dev.watt-mind.com`.
- The ACA FQDN has no public DNS answer, so there is no path around the router.
- Config read: Easy Auth `AllowAnonymous`, the Custom forward proxy reads
  `X-Pii-Guard-External-*`, the token store is off and `CLIENT_IP_SOURCE=off`. The router
  (`deploy/azure/dev_router/bootstrap.py`) forwards only an allowlist of headers
  (`proxy_pass_request_headers off`) and sets the host, proto and XFF fields itself. Its
  access log is off and its error log is `/dev/null`. The deployed router was not inspected
  over SSH, which is disabled by design.
- Logs: `az containerapp logs show --tail 300` returned only the start-up lines (model load)
  and one uvicorn `ASGI callable returned without completing response` from before the probes.
  There were no request bodies, no IPs (no forged, tailnet or router address) and no tokens.
  The environment has no Log Analytics destination, so nothing is retained beyond the console
  stream.
