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
}

export interface TrafficPage {
  level: TrafficLevel;
  size: number;
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
  };
}

export type TrafficStatus =
  | { state: "connecting" }
  | { state: "live"; via: "sse" | "poll"; level: TrafficLevel; size: number }
  /** The server answers, but its traffic log is off (`PII_GUARD_TRAFFIC_LOG=off`) or absent. */
  | { state: "disabled"; reason: "off" | "unsupported"; message: string }
  /** The API can't be reached (or stopped answering); polling keeps retrying. */
  | { state: "offline"; message: string };

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

export async function fetchTraffic(
  doFetch: typeof fetch,
  baseUrl: string,
  query: { limit?: number; after?: number },
  signal?: AbortSignal,
): Promise<TrafficPage> {
  const params = new URLSearchParams();
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.after !== undefined) params.set("after", String(query.after));
  let res: Response;
  try {
    res = await doFetch(`${baseUrl}/v1/traffic?${params}`, { headers: { Accept: "application/json" }, signal });
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
      events: payload.events.map(parseTrafficEvent).filter((e): e is TrafficEvent => e !== null),
    };
  }
  if (isRecord(payload) && isRecord(payload.error) && typeof payload.error.code === "string") {
    throw new ApiError(res.status, payload.error.code, typeof payload.error.message === "string" ? payload.error.message : payload.error.code);
  }
  if (res.status === 404 || res.status === 405) throw new ApiError(res.status, "not_found", "GET /v1/traffic is not available");
  throw new UnreachableError(`pii-guard API answered ${res.status} without a contract error body`);
}

/** Load the backlog, then follow the live stream (or poll). Call `close()` to stop. */
export function connectTraffic(options: TrafficConnectOptions): TrafficConnection {
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  const doFetch = options.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
  const ES: EventSourceCtor | null =
    options.EventSource === undefined ? ((globalThis as { EventSource?: EventSourceCtor }).EventSource ?? null) : options.EventSource;
  const pollMs = options.pollMs ?? 2000;
  const seen = new Set<string>();
  let lastSeq = 0;
  let closed = false;
  let level: TrafficLevel = "masked";
  let size = 0;
  let es: InstanceType<EventSourceCtor> | null = null;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  const controller = new AbortController();

  const emit = (events: TrafficEvent[]) => {
    const fresh: TrafficEvent[] = [];
    for (const e of events) {
      if (seen.has(e.id)) continue;
      seen.add(e.id);
      lastSeq = Math.max(lastSeq, e.seq);
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
      return { state: "disabled", reason: "unsupported", message: "this pii-guard server has no traffic log (it predates /v1/traffic)" };
    return { state: "offline", message: err instanceof Error ? err.message : String(err) };
  };

  const poll = () => {
    if (closed) return;
    fetchTraffic(doFetch, baseUrl, { after: lastSeq, limit: 200 }, controller.signal).then(
      (page) => {
        level = page.level;
        size = page.size;
        emit(page.events);
        status({ state: "live", via: "poll", level, size });
      },
      (err: unknown) => {
        if (!closed) status(failure(err));
      },
    );
    pollTimer = setTimeout(poll, pollMs);
  };

  const startPolling = () => {
    if (closed || pollTimer !== null) return;
    es?.close();
    es = null;
    status({ state: "live", via: "poll", level, size });
    pollTimer = setTimeout(poll, pollMs);
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

  fetchTraffic(doFetch, baseUrl, { limit: options.backlog ?? 200 }, controller.signal).then(
    (page) => {
      level = page.level;
      size = page.size;
      emit(page.events);
      status({ state: "live", via: ES ? "sse" : "poll", level, size });
      follow();
    },
    (err: unknown) => {
      if (closed) return;
      const s = failure(err);
      status(s);
      // Keep trying while the API is down; a disabled log needs a restart, so stop there.
      if (s.state === "offline") startPollingQuiet();
    },
  );

  // Retry the backlog until the API answers, then switch to following it.
  function startPollingQuiet() {
    if (closed) return;
    pollTimer = setTimeout(() => {
      pollTimer = null;
      fetchTraffic(doFetch, baseUrl, { limit: options.backlog ?? 200 }, controller.signal).then(
        (page) => {
          level = page.level;
          size = page.size;
          emit(page.events);
          status({ state: "live", via: ES ? "sse" : "poll", level, size });
          follow();
        },
        (err: unknown) => {
          if (closed) return;
          const s = failure(err);
          status(s);
          if (s.state === "offline") startPollingQuiet();
        },
      );
    }, pollMs * 2);
  }

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
 * mock upstream), one every `intervalMs`, each with a fresh id, seq and time. The recording
 * holds no original values, so nothing here can show one.
 */
export function startFixtureFeed(
  recorded: readonly TrafficEvent[],
  onEvents: (events: TrafficEvent[]) => void,
  options: { intervalMs?: number; initial?: number; now?: () => number } = {},
): TrafficConnection {
  const intervalMs = options.intervalMs ?? 1600;
  const now = options.now ?? Date.now;
  let n = 0;
  const next = (): TrafficEvent => {
    const base = recorded[n % recorded.length]!;
    n += 1;
    return {
      ...base,
      level: "masked",
      id: `${base.id}_demo${n}`,
      seq: n,
      time: new Date(now()).toISOString(),
      request: base.request ? { masked: base.request.masked } : null,
      response: base.response ? { masked: base.response.masked, chunks: base.response.chunks } : null,
    };
  };
  if (!recorded.length) return { close() {} };
  const initial = Math.min(options.initial ?? 8, recorded.length);
  onEvents(Array.from({ length: initial }, next));
  const timer = setInterval(() => onEvents([next()]), intervalMs);
  return { close: () => clearInterval(timer) };
}
