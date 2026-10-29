import { getSelectedEndpoint, getSelectedProject } from "../projects/selection";
import { createProjectFetch, inspectionHeaders } from "./project";
// The gateway's traffic log (docs/operations.md, "Traffic log"): one event per LLM call.
//
// - `GET /v1/traffic?limit=&after=` returns the stored events, oldest first.
// - `GET /v1/traffic/stream?replay=N` is server-sent events, one `traffic` event per call.
//
// `connectTraffic` loads the backlog, then follows the SSE stream; when the stream can't be
// opened (no EventSource, a proxy that buffers, repeated errors) it polls `/v1/traffic` with
// `after=<last seq>` instead. Events are de-duplicated by request id, so a stream replay or a
// reconnect never shows a call twice. Both routes answer 404 `traffic_log_disabled` while the
// server runs with `PII_GUARD_TRAFFIC_LOG=off`.
//
// Robustness (LAB-1357):
// - A restarted server numbers events from 1 again, so the old `after` cursor would hide every
//   new event. A page's `boot` (one random id per server process) changing, or an unseen SSE
//   event at or below the cursor, resets the cursor to 0.
// - One `/v1/traffic` request at a time: the next poll is scheduled once the previous one
//   settles, and each request is aborted after `timeoutMs`.
// - The dedup set keeps the newest `dedupWindow` ids, not every id ever seen.
//
// Status honesty (LAB-1437): a 429 is `limited` and a 401/403 is `denied`, never `offline`. The
// server answered, so the page must not say it is unreachable. Both keep retrying with an
// exponential backoff (capped at `MAX_BACKOFF_MS`); a 429's `Retry-After` is a floor.

import { getOwnerToken } from "./localOwner";
import type { EntityType } from "./types";
import { ApiError, UnreachableError } from "./http";

export type TrafficLevel = "masked" | "full";
export type TrafficOutcome = "ok" | "blocked" | "refused" | "upstream_error" | "stream_error" | "error";

export interface TrafficTiming {
  total_ms: number;
  upstream_ms: number;
  overhead_ms: number;
  stages_ms: Partial<Record<Stage, number>>;
  detectors_ms: Record<string, number>;
  ttft_ms: number | null;
  upstream_ttft_ms: number | null;
  added_ttft_ms: number | null;
}

/** Stage names in pipeline order (src/pii_guard/observability/timing.py, STAGES). */
export const STAGES = ["parse", "detect", "image", "mask", "forward", "upstream_ttfb", "upstream", "unmask", "response"] as const;
export type Stage = (typeof STAGES)[number];

export interface TrafficEntities {
  detected: Partial<Record<EntityType, number>>;
  masked: Partial<Record<EntityType, number>>;
  texts: number;
  images?: { count: number; masked: Partial<Record<EntityType, number>>; kept: Partial<Record<EntityType, number>>; ocr: boolean };
}

export interface TrafficEvent {
  id: string;
  seq: number;
  time: string;
  level: TrafficLevel;
  outcome: TrafficOutcome | string;
  error: { code: string; status: number | null; entity_types?: Partial<Record<EntityType, number>> } | null;
  mode: string | null;
  language: string | null;
  stream: boolean;
  model: string | null;
  session_ref: string | null;
  session_new: boolean;
  /** How the gateway picked the vault session (LAB-1286): `header`, `path`, `prompt_cache_key` or `default`. */
  session_source: string | null;
  detectors: string[];
  entities: TrafficEntities | null;
  cache: { hits: number; misses: number; seeded: number } | null;
  upstream: { status: number | null; model: string | null; unresolved_placeholders: number } | null;
  usage: Record<string, number> | null;
  timing: TrafficTiming;
  /** `masked`: the body sent upstream; `original`: the client's request (level `full` only). */
  request: { masked?: unknown; original?: unknown } | null;
  /** `masked`: the upstream's answer; `unmasked`: what the client got (level `full` only). */
  response: { masked?: unknown; unmasked?: unknown; chunks?: number } | null;
  /** Hosted: the endpoint the call went through (LAB-1492); `null` for a call on the project itself. */
  endpoint?: { id: string; name: string } | null;
}

export interface TrafficPage {
  level: TrafficLevel;
  size: number;
  /** One random id per server process; a new one means the server restarted (its seq starts at 1). `null` from servers that predate it. */
  boot: string | null;
  events: TrafficEvent[];
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** A traffic event from the wire, or null when it doesn't have the fields the screen needs. */
export function parseTrafficEvent(raw: unknown): TrafficEvent | null {
  if (!isRecord(raw) || typeof raw.id !== "string" || typeof raw.seq !== "number" || !isRecord(raw.timing)) return null;
  const t = raw.timing;
  const stages: Partial<Record<Stage, number>> = {};
  if (isRecord(t.stages_ms)) for (const s of STAGES) stages[s] = num(t.stages_ms[s]);
  const detectors: Record<string, number> = {};
  if (isRecord(t.detectors_ms)) for (const [k, v] of Object.entries(t.detectors_ms)) detectors[k] = num(v);
  return {
    id: raw.id,
    seq: raw.seq,
    time: typeof raw.time === "string" ? raw.time : new Date().toISOString(),
    level: raw.level === "full" ? "full" : "masked",
    outcome: typeof raw.outcome === "string" ? raw.outcome : "ok",
    error: isRecord(raw.error) && typeof raw.error.code === "string" ? (raw.error as TrafficEvent["error"]) : null,
    mode: typeof raw.mode === "string" ? raw.mode : null,
    language: typeof raw.language === "string" ? raw.language : null,
    stream: raw.stream === true,
    model: typeof raw.model === "string" ? raw.model : null,
    session_ref: typeof raw.session_ref === "string" ? raw.session_ref : null,
    session_new: raw.session_new === true,
    session_source: typeof raw.session_source === "string" ? raw.session_source : null,
    detectors: Array.isArray(raw.detectors) ? raw.detectors.filter((d): d is string => typeof d === "string") : [],
    entities: isRecord(raw.entities) ? (raw.entities as unknown as TrafficEntities) : null,
    cache: isRecord(raw.cache) ? (raw.cache as TrafficEvent["cache"]) : null,
    upstream: isRecord(raw.upstream) ? (raw.upstream as TrafficEvent["upstream"]) : null,
    usage: isRecord(raw.usage) ? (raw.usage as Record<string, number>) : null,
    timing: {
      total_ms: num(t.total_ms),
      upstream_ms: num(t.upstream_ms),
      overhead_ms: num(t.overhead_ms),
      stages_ms: stages,
      detectors_ms: detectors,
      ttft_ms: numOrNull(t.ttft_ms),
      upstream_ttft_ms: numOrNull(t.upstream_ttft_ms),
      added_ttft_ms: numOrNull(t.added_ttft_ms),
    },
    request: isRecord(raw.request) ? raw.request : null,
    response: isRecord(raw.response) ? raw.response : null,
    endpoint:
      isRecord(raw.endpoint) && typeof raw.endpoint.id === "string"
        ? { id: raw.endpoint.id, name: typeof raw.endpoint.name === "string" && raw.endpoint.name ? raw.endpoint.name : raw.endpoint.id }
        : null,
  };
}

export type TrafficStatus =
  | { state: "connecting" }
  | { state: "live"; via: "sse" | "poll"; level: TrafficLevel; size: number }
  /** The server answers, but its traffic log is off (`PII_GUARD_TRAFFIC_LOG=off`) or absent. */
  | { state: "disabled"; reason: "off" | "unsupported"; message: string }
  /** The API can't be reached (or stopped answering); polling keeps retrying. */
  | { state: "offline"; message: string }
  /** The API answered 429: too many requests for now. Retried after `retryAfterMs` at the earliest. */
  | { state: "limited"; message: string; retryAfterMs: number }
  /** The API answered 401 (`signed_out`) or 403 (`forbidden`). Retried with backoff (a sign-in in another tab heals it). */
  | { state: "denied"; reason: "signed_out" | "forbidden"; message: string };

/** A 429 from `/v1/traffic`, with the server's `Retry-After` in milliseconds (0 when absent). */
export class TrafficRateLimitedError extends ApiError {
  readonly retryAfterMs: number;

  constructor(code: string, message: string, retryAfterMs: number) {
    super(429, code, message);
    this.name = "TrafficRateLimitedError";
    this.retryAfterMs = retryAfterMs;
  }
}

/** `Retry-After` as delay-seconds or an HTTP date, in milliseconds; 0 when absent or invalid. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number {
  if (!value) return 0;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed) * 1000;
  const at = Date.parse(trimmed);
  return Number.isFinite(at) ? Math.max(0, at - now) : 0;
}

type EventSourceCtor = new (url: string) => Pick<EventSource, "addEventListener" | "close" | "readyState"> & {
  onopen: ((ev: Event) => unknown) | null;
  onerror: ((ev: Event) => unknown) | null;
};

export interface TrafficConnectOptions {
  baseUrl?: string;
  fetch?: typeof fetch;
  /** `null` forces polling (tests, or a browser without EventSource). */
  EventSource?: EventSourceCtor | null;
  pollMs?: number;
  /** Per-request timeout of `/v1/traffic` (backlog and polls). Default {@link TRAFFIC_TIMEOUT_MS}. */
  timeoutMs?: number;
  /** Event ids remembered for de-duplication, newest first. Default {@link DEDUP_WINDOW}. */
  dedupWindow?: number;
  /** Events loaded before following the stream. */
  backlog?: number;
  onEvents: (events: TrafficEvent[]) => void;
  onStatus: (status: TrafficStatus) => void;
}

export interface TrafficConnection {
  close(): void;
}

/** SSE errors in a row (without an open in between) before falling back to polling. */
export const SSE_MAX_ERRORS = 3;

/** Default per-request timeout of `/v1/traffic`. */
export const TRAFFIC_TIMEOUT_MS = 10_000;

/**
 * Default dedup window: the Logs screen keeps `MAX_EVENTS` (500) events, and duplicates only
 * come from the stream's `replay=50` and the 200-event backlog, so older ids can be forgotten.
 */
export const DEDUP_WINDOW = 500;

/** Longest wait between retries while the API rate-limits or denies traffic reads. */
export const MAX_BACKOFF_MS = 60_000;

export async function fetchTraffic(
  doFetch: typeof fetch,
  baseUrl: string,
  query: { limit?: number; after?: number },
  signal?: AbortSignal,
  projectId: string | null = getSelectedProject(),
  endpointId: string | null = getSelectedEndpoint(),
): Promise<TrafficPage> {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.after !== undefined) params.set("after", String(query.after));
  let res: Response;
  try {
    res = await createProjectFetch(doFetch, projectId, endpointId)(`${baseUrl}/v1/traffic?${params}`, { headers: inspectionHeaders({ Accept: "application/json" }, projectId, endpointId), signal });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new UnreachableError();
  }
  let payload: unknown;
  try {
    payload = JSON.parse(await res.text());
  } catch {
    payload = undefined;
  }
  if (res.ok && isRecord(payload) && Array.isArray(payload.events)) {
    return {
      level: payload.level === "full" ? "full" : "masked",
      size: num(payload.size),
      boot: typeof payload.boot === "string" ? payload.boot : null,
      events: payload.events.map(parseTrafficEvent).filter((e): e is TrafficEvent => e !== null),
    };
  }
  const contract = isRecord(payload) && isRecord(payload.error) && typeof payload.error.code === "string" ? payload.error : null;
  const code = contract ? (contract.code as string) : null;
  const message = contract && typeof contract.message === "string" ? contract.message : code;
  if (res.status === 429) throw new TrafficRateLimitedError(code ?? "rate_limited", message ?? "Too many requests", parseRetryAfter(res.headers.get("retry-after")));
  if (contract) throw new ApiError(res.status, code as string, message as string);
  if (res.status === 401 || res.status === 403) throw new ApiError(res.status, res.status === 401 ? "unauthorized" : "forbidden", `PII Guard API answered ${res.status}`);
  if (res.status === 404 || res.status === 405) throw new ApiError(res.status, "not_found", "GET /v1/traffic is not available");
  throw new UnreachableError(`PII Guard API answered ${res.status} without a contract error body`);
}

/** Load the backlog, then follow the live stream (or poll). Call `close()` to stop. */
export function connectTraffic(options: TrafficConnectOptions): TrafficConnection {
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  const doFetch = options.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
  const projectId = getSelectedProject();
  const endpointId = getSelectedEndpoint();
  // EventSource cannot send the project header. Polling retains the same authorization
  // boundary as REST, without adding another selector to URLs or browser history.
  const ES: EventSourceCtor | null = projectId || endpointId || (import.meta.env.VITE_PII_GUARD_HOSTED !== "true" && getOwnerToken()) ? null :
    options.EventSource === undefined ? ((globalThis as { EventSource?: EventSourceCtor }).EventSource ?? null) : options.EventSource;
  const pollMs = options.pollMs ?? 2000;
  const timeoutMs = options.timeoutMs ?? TRAFFIC_TIMEOUT_MS;
  const dedupWindow = Math.max(1, options.dedupWindow ?? DEDUP_WINDOW);
  const backlog = options.backlog ?? 200;
  // Insertion-ordered: the first entry is the oldest id, evicted once the window is full.
  const seen = new Set<string>();
  let lastSeq = 0;
  let boot: string | null = null;
  let closed = false;
  let polling = false;
  let level: TrafficLevel = "masked";
  let size = 0;
  let es: InstanceType<EventSourceCtor> | null = null;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  const controller = new AbortController();

  const remember = (id: string) => {
    seen.add(id);
    while (seen.size > dedupWindow) seen.delete(seen.values().next().value as string);
  };

  const emit = (events: TrafficEvent[]) => {
    const fresh: TrafficEvent[] = [];
    for (const e of events) {
      if (seen.has(e.id)) continue;
      remember(e.id);
      // A new call at or below the cursor: the server restarted and numbers from 1 again.
      lastSeq = e.seq <= lastSeq ? e.seq : Math.max(lastSeq, e.seq);
      fresh.push(e);
    }
    if (fresh.length && !closed) options.onEvents(fresh);
  };

  const status = (s: TrafficStatus) => {
    if (!closed) options.onStatus(s);
  };

  const failure = (err: unknown): TrafficStatus => {
    if (err instanceof ApiError && err.code === "traffic_log_disabled") return { state: "disabled", reason: "off", message: err.message };
    if (err instanceof ApiError && err.code === "not_found")
      return { state: "disabled", reason: "unsupported", message: "this PII Guard server has no traffic log (it predates /v1/traffic)" };
    if (err instanceof TrafficRateLimitedError) return { state: "limited", message: err.message, retryAfterMs: err.retryAfterMs };
    if (err instanceof ApiError && (err.status === 401 || err.status === 403))
      return { state: "denied", reason: err.status === 401 ? "signed_out" : "forbidden", message: err.message };
    return { state: "offline", message: err instanceof Error ? err.message : String(err) };
  };

  // Failed attempts in a row that the server answered (429, 401, 403): each doubles the wait.
  let refusals = 0;
  /** The wait before the next attempt after a failure; `base` is the usual retry interval. */
  const retryDelay = (s: TrafficStatus, base: number): number => {
    if (s.state !== "limited" && s.state !== "denied") {
      refusals = 0;
      return base;
    }
    refusals += 1;
    const backoff = Math.min(MAX_BACKOFF_MS, base * 2 ** (refusals - 1));
    return s.state === "limited" ? Math.max(backoff, s.retryAfterMs) : backoff;
  };

  /** One `/v1/traffic` request, aborted after `timeoutMs` or on `close()`, whatever the fetch does with the signal. */
  const load = (query: { limit?: number; after?: number }): Promise<TrafficPage> => {
    const request = new AbortController();
    const abort = () => request.abort();
    controller.signal.addEventListener("abort", abort);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = new Promise<never>((_, reject) => {
      const onAbort = () =>
        reject(controller.signal.aborted ? new DOMException("closed", "AbortError") : new UnreachableError(`PII Guard API did not answer within ${timeoutMs / 1000} s`));
      request.signal.addEventListener("abort", onAbort);
      timer = setTimeout(abort, timeoutMs);
    });
    return Promise.race([fetchTraffic(doFetch, baseUrl, query, request.signal, projectId, endpointId), stop]).finally(() => {
      clearTimeout(timer);
      controller.signal.removeEventListener("abort", abort);
    });
  };

  /**
   * Take a page fetched with `after`. False when its boot id says the server restarted and the
   * page was filtered by the old cursor: the cursor is reset and the caller fetches again.
   */
  const accept = (page: TrafficPage, after: number): boolean => {
    level = page.level;
    size = page.size;
    const restarted = page.boot !== null && boot !== null && page.boot !== boot;
    if (page.boot !== null) boot = page.boot;
    if (restarted) lastSeq = 0;
    if (restarted && after > 0) return false;
    emit(page.events);
    return true;
  };

  const schedulePoll = (delay: number) => {
    if (!closed) pollTimer = setTimeout(poll, delay);
  };

  const poll = () => {
    pollTimer = null;
    if (closed) return;
    const after = lastSeq;
    load({ after, limit: 200 }).then(
      (page) => {
        if (closed) return;
        refusals = 0;
        if (!accept(page, after)) return schedulePoll(0); // restarted: fetch again from seq 0 right away
        status({ state: "live", via: "poll", level, size });
        schedulePoll(pollMs);
      },
      (err: unknown) => {
        if (closed) return;
        const s = failure(err);
        status(s);
        schedulePoll(retryDelay(s, pollMs));
      },
    );
  };

  const startPolling = () => {
    if (closed || polling) return;
    polling = true;
    es?.close();
    es = null;
    status({ state: "live", via: "poll", level, size });
    schedulePoll(pollMs);
  };

  const follow = () => {
    if (closed) return;
    if (!ES) return startPolling();
    let errors = 0;
    try {
      // replay re-sends recent events: anything published between the backlog and this
      // subscription still arrives, and duplicates are dropped by id.
      es = new ES(`${baseUrl}/v1/traffic/stream?replay=50`);
    } catch {
      return startPolling();
    }
    es.addEventListener("traffic", (ev) => {
      let data: unknown;
      try {
        data = JSON.parse((ev as MessageEvent<string>).data);
      } catch {
        return;
      }
      const event = parseTrafficEvent(data);
      if (event) {
        level = event.level;
        emit([event]);
      }
    });
    es.onopen = () => {
      errors = 0;
      status({ state: "live", via: "sse", level, size });
    };
    es.onerror = () => {
      errors += 1;
      // CLOSED (2): the browser gave up (for example a 404 once the log was turned off).
      if (es?.readyState === 2 || errors >= SSE_MAX_ERRORS) startPolling();
    };
  };

  // Load the backlog; retry it every 2 * pollMs while the API is down, then follow it.
  const loadBacklog = () => {
    pollTimer = null;
    if (closed) return;
    load({ limit: backlog }).then(
      (page) => {
        if (closed) return;
        refusals = 0;
        accept(page, 0);
        status({ state: "live", via: ES ? "sse" : "poll", level, size });
        follow();
      },
      (err: unknown) => {
        if (closed) return;
        const s = failure(err);
        status(s);
        // Keep trying while the API is down, limited or denied; a disabled log needs a restart, so stop there.
        if (s.state !== "disabled") pollTimer = setTimeout(loadBacklog, retryDelay(s, pollMs * 2));
      },
    );
  };
  loadBacklog();

  return {
    close() {
      closed = true;
      controller.abort();
      es?.close();
      if (pollTimer !== null) clearTimeout(pollTimer);
    },
  };
}

/**
 * Offline demo: replays events recorded from `make demo` + `make demo-traffic` (masked level,
 * mock upstream) **once**, one every `intervalMs` after an initial burst, then stops and calls
 * `onDone`. While `paused()` is true the replay waits, so "done" means every call was shown. Each replayed event keeps a stable id (`<recorded id>_demo`) and gets a fresh seq
 * and time, so a repeat is dropped by the caller's id dedupe instead of inflating counters.
 * Replaying again is a new feed on an emptied list. The recording holds no original values,
 * so nothing here can show one.
 */
export function startFixtureFeed(
  recorded: readonly TrafficEvent[],
  onEvents: (events: TrafficEvent[]) => void,
  options: { intervalMs?: number; initial?: number; now?: () => number; onDone?: () => void; paused?: () => boolean } = {},
): TrafficConnection {
  const intervalMs = options.intervalMs ?? 1600;
  const now = options.now ?? Date.now;
  let n = 0;
  const next = (): TrafficEvent => {
    const base = recorded[n]!;
    n += 1;
    return {
      ...base,
      level: "masked",
      id: `${base.id}_demo`,
      seq: n,
      time: new Date(now()).toISOString(),
      request: base.request ? { masked: base.request.masked } : null,
      response: base.response ? { masked: base.response.masked, chunks: base.response.chunks } : null,
    };
  };
  let timer: ReturnType<typeof setInterval> | null = null;
  const stop = () => {
    if (timer !== null) clearInterval(timer);
    timer = null;
  };
  const finish = () => {
    stop();
    options.onDone?.();
  };
  if (!recorded.length) {
    finish();
    return { close() {} };
  }
  const initial = Math.min(options.initial ?? 8, recorded.length);
  onEvents(Array.from({ length: initial }, next));
  if (n >= recorded.length) {
    finish();
    return { close: stop };
  }
  timer = setInterval(() => {
    if (options.paused?.()) return;
    onEvents([next()]);
    if (n >= recorded.length) finish();
  }, intervalMs);
  return { close: stop };
}
