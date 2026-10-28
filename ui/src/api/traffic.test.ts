import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import full from "../test/trafficFull.json";
import fixture from "../content/trafficFixture.json";
import { DEMO_SCENARIOS } from "./demoTraffic";
import { ApiError, UnreachableError } from "./http";
import { DEDUP_WINDOW, SSE_MAX_ERRORS, connectTraffic, fetchTraffic, parseTrafficEvent, startFixtureFeed, type TrafficEvent, type TrafficStatus } from "./traffic";

const events = (full.events as unknown[]).map(parseTrafficEvent) as TrafficEvent[];
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** A controllable stand-in for the browser's EventSource. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readyState = 0;
  onopen: ((ev: Event) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  closed = false;
  private listeners = new Map<string, ((ev: Event) => void)[]>();
  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (ev: Event) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  send(event: unknown) {
    const ev = new MessageEvent("traffic", { data: JSON.stringify(event) });
    for (const fn of this.listeners.get("traffic") ?? []) fn(ev);
  }
  fail() {
    this.readyState = 0;
    this.onerror?.(new Event("error"));
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
});
afterEach(() => {
  vi.useRealTimers();
});

describe("parseTrafficEvent", () => {
  it("keeps the payload's own numbers", () => {
    const raw = full.events[0]!;
    const e = parseTrafficEvent(raw)!;
    expect(e.timing.overhead_ms).toBe(raw.timing.overhead_ms);
    expect(e.timing.stages_ms.detect).toBe(raw.timing.stages_ms.detect);
    expect(e.level).toBe("full");
  });

  it("rejects events without an id, seq or timing", () => {
    expect(parseTrafficEvent({ seq: 1, timing: {} })).toBeNull();
    expect(parseTrafficEvent({ id: "req_1", timing: {} })).toBeNull();
    expect(parseTrafficEvent({ id: "req_1", seq: 1 })).toBeNull();
    expect(parseTrafficEvent("nope")).toBeNull();
  });
});

describe("fetchTraffic", () => {
  it("maps 404 traffic_log_disabled to a contract error", async () => {
    const f = vi.fn(async () => json(404, { error: { code: "traffic_log_disabled", message: "the traffic log is off" } }));
    await expect(fetchTraffic(f, "", { limit: 1 })).rejects.toMatchObject({ code: "traffic_log_disabled" });
  });

  it("treats a network failure or a proxy error page as unreachable", async () => {
    await expect(fetchTraffic(async () => Promise.reject(new TypeError("fetch failed")), "", {})).rejects.toBeInstanceOf(UnreachableError);
    await expect(fetchTraffic(async () => new Response("<html>502</html>", { status: 502 }), "", {})).rejects.toBeInstanceOf(UnreachableError);
  });

  it("sends limit and after", async () => {
    const f = vi.fn(async (url: RequestInfo | URL) => (void url, json(200, { level: "masked", size: 200, events: [] })));
    await fetchTraffic(f as unknown as typeof fetch, "", { limit: 5, after: 7 });
    expect(String(f.mock.calls[0]![0])).toBe("/v1/traffic?limit=5&after=7");
  });
});

describe("connectTraffic", () => {
  it("loads the backlog, follows the SSE stream and drops replayed duplicates", async () => {
    const got: TrafficEvent[] = [];
    const statuses: TrafficStatus[] = [];
    const f = vi.fn(async () => json(200, { level: "full", size: 200, events: full.events.slice(0, 2) }));
    const conn = connectTraffic({
      fetch: f,
      EventSource: FakeEventSource as never,
      onEvents: (e) => got.push(...e),
      onStatus: (s) => statuses.push(s),
    });
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const es = FakeEventSource.instances[0]!;
    expect(es.url).toBe("/v1/traffic/stream?replay=50");
    es.open();
    expect(statuses.at(-1)).toEqual({ state: "live", via: "sse", level: "full", size: 200 });
    // replay=50 re-sends what the backlog already had, then a new call arrives
    es.send(full.events[0]);
    es.send(full.events[1]);
    es.send(full.events[2]);
    es.send({ not: "an event" });
    expect(got.map((e) => e.id)).toEqual(events.slice(0, 3).map((e) => e.id));
    conn.close();
    expect(es.closed).toBe(true);
  });

  it("falls back to polling with after=<last seq> when the stream keeps failing", async () => {
    vi.useFakeTimers();
    const got: TrafficEvent[] = [];
    const statuses: TrafficStatus[] = [];
    const urls: string[] = [];
    const f = vi.fn(async (url: RequestInfo | URL) => {
      urls.push(String(url));
      return urls.length === 1
        ? json(200, { level: "masked", size: 200, events: full.events.slice(0, 1) })
        : json(200, { level: "masked", size: 200, events: full.events.slice(1, 2) });
    });
    const conn = connectTraffic({
      fetch: f as unknown as typeof fetch,
      EventSource: FakeEventSource as never,
      pollMs: 1000,
      onEvents: (e) => got.push(...e),
      onStatus: (s) => statuses.push(s),
    });
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const es = FakeEventSource.instances[0]!;
    for (let i = 0; i < SSE_MAX_ERRORS; i++) es.fail();
    expect(es.closed).toBe(true);
    expect(statuses.at(-1)).toMatchObject({ state: "live", via: "poll" });
    await vi.advanceTimersByTimeAsync(1000);
    expect(urls[1]).toBe(`/v1/traffic?limit=200&after=${events[0]!.seq}`);
    expect(got.map((e) => e.id)).toEqual([events[0]!.id, events[1]!.id]);
    conn.close();
  });

  it("polls when there is no EventSource", async () => {
    const statuses: TrafficStatus[] = [];
    const conn = connectTraffic({
      fetch: async () => json(200, { level: "masked", size: 200, events: [] }),
      EventSource: null,
      onEvents: () => {},
      onStatus: (s) => statuses.push(s),
    });
    await vi.waitFor(() => expect(statuses.at(-1)).toMatchObject({ state: "live", via: "poll" }));
    conn.close();
  });

  it("reports a disabled log and an unreachable API", async () => {
    const disabled: TrafficStatus[] = [];
    const d = connectTraffic({
      fetch: async () => json(404, { error: { code: "traffic_log_disabled", message: "off" } }),
      EventSource: null,
      onEvents: () => {},
      onStatus: (s) => disabled.push(s),
    });
    await vi.waitFor(() => expect(disabled.at(-1)).toMatchObject({ state: "disabled", reason: "off" }));
    d.close();

    const offline: TrafficStatus[] = [];
    const c = connectTraffic({
      fetch: async () => Promise.reject(new TypeError("down")),
      EventSource: null,
      onEvents: () => {},
      onStatus: (s) => offline.push(s),
    });
    await vi.waitFor(() => expect(offline.at(-1)).toMatchObject({ state: "offline" }));
    c.close();
    expect(new ApiError(404, "x", "y")).toBeInstanceOf(Error);
  });
});

// LAB-1357: a restarted backend, a stalled endpoint, a long-running connection.
describe("connectTraffic resilience", () => {
  /** Events from a restarted server: fresh ids, seq numbering from 1 again. */
  const afterRestart = [1, 2].map((seq) => ({ ...full.events[0]!, id: `req_restart_${seq}`, seq }));
  const page = (boot: string | undefined, evs: unknown[]) => json(200, { level: "masked", size: 200, boot, events: evs });

  it("resets the cursor when the server's boot id changes, and re-polls at once", async () => {
    vi.useFakeTimers();
    const urls: string[] = [];
    const pages = [
      () => page("boot_a", full.events.slice(0, 2)), // backlog, seq 9 and 11
      () => page("boot_b", []), // after=11 on the restarted server: its seq 1 and 2 are filtered out
      () => page("boot_b", afterRestart), // after=0
      () => page("boot_b", []),
    ];
    const got: TrafficEvent[] = [];
    const conn = connectTraffic({
      fetch: (async (url: RequestInfo | URL) => (urls.push(String(url)), pages[Math.min(urls.length - 1, pages.length - 1)]!())) as typeof fetch,
      EventSource: null,
      pollMs: 1000,
      onEvents: (e) => got.push(...e),
      onStatus: () => {},
    });
    await vi.advanceTimersByTimeAsync(1000);
    // the restart is noticed once the page's body is read; the re-poll needs no poll interval
    await vi.waitFor(async () => {
      await vi.advanceTimersByTimeAsync(0);
      expect(urls).toHaveLength(3);
    });
    expect(urls.slice(0, 3)).toEqual(["/v1/traffic?limit=200", `/v1/traffic?limit=200&after=${events[1]!.seq}`, "/v1/traffic?limit=200&after=0"]);
    expect(got.map((e) => e.id)).toEqual([events[0]!.id, events[1]!.id, "req_restart_1", "req_restart_2"]);
    await vi.waitFor(async () => {
      await vi.advanceTimersByTimeAsync(1000);
      expect(urls[3]).toBe("/v1/traffic?limit=200&after=2");
    });
    conn.close();
  });

  it("resets the cursor when the SSE stream sends a new event with a lower seq (server without boot)", async () => {
    vi.useFakeTimers();
    const urls: string[] = [];
    const got: TrafficEvent[] = [];
    const conn = connectTraffic({
      fetch: (async (url: RequestInfo | URL) => (urls.push(String(url)), page(undefined, urls.length === 1 ? full.events.slice(0, 2) : []))) as typeof fetch,
      EventSource: FakeEventSource as never,
      pollMs: 1000,
      onEvents: (e) => got.push(...e),
      onStatus: () => {},
    });
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const es = FakeEventSource.instances[0]!;
    es.open();
    // EventSource reconnected on its own to the restarted server, which replays from seq 1
    es.send(afterRestart[0]);
    expect(got.at(-1)?.id).toBe("req_restart_1");
    for (let i = 0; i < SSE_MAX_ERRORS; i++) es.fail();
    await vi.advanceTimersByTimeAsync(1000);
    expect(urls[1]).toBe("/v1/traffic?limit=200&after=1");
    conn.close();
  });

  it("keeps one poll in flight, aborts it after timeoutMs, reports offline and keeps polling", async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    const statuses: TrafficStatus[] = [];
    // After the backlog the endpoint stalls: it never answers and ignores the abort signal.
    const f = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (f.mock.calls.length === 1) return page("boot_a", []);
      signals.push(init!.signal!);
      return new Promise<Response>(() => {});
    });
    const conn = connectTraffic({
      fetch: f as unknown as typeof fetch,
      EventSource: null,
      pollMs: 1000,
      timeoutMs: 5000,
      onEvents: () => {},
      onStatus: (s) => statuses.push(s),
    });
    await vi.advanceTimersByTimeAsync(1000); // first poll starts and hangs
    expect(f).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4000); // four poll intervals, still the same request
    expect(f).toHaveBeenCalledTimes(2);
    expect(signals[0]!.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1000); // timeoutMs reached
    expect(signals[0]!.aborted).toBe(true);
    expect(statuses.at(-1)).toEqual({ state: "offline", message: "pii-guard API did not answer within 5 s" });
    await vi.advanceTimersByTimeAsync(1000); // the next poll, only after the previous one settled
    expect(f).toHaveBeenCalledTimes(3);
    conn.close();
    expect(signals[1]!.aborted).toBe(true);
  });

  it("times out a stalled backlog request too, then retries it", async () => {
    vi.useFakeTimers();
    const statuses: TrafficStatus[] = [];
    const f = vi.fn(async () => new Promise<Response>(() => {}));
    const conn = connectTraffic({
      fetch: f as unknown as typeof fetch,
      EventSource: null,
      pollMs: 1000,
      timeoutMs: 3000,
      onEvents: () => {},
      onStatus: (s) => statuses.push(s),
    });
    await vi.advanceTimersByTimeAsync(3000);
    expect(statuses.at(-1)).toMatchObject({ state: "offline" });
    await vi.advanceTimersByTimeAsync(2000); // the backlog retry waits 2 * pollMs
    expect(f).toHaveBeenCalledTimes(2);
    conn.close();
  });

  it("bounds the dedup set to the display window, newest ids kept", async () => {
    const got: TrafficEvent[] = [];
    const conn = connectTraffic({
      fetch: async () => page("boot_a", []),
      EventSource: FakeEventSource as never,
      onEvents: (e) => got.push(...e),
      onStatus: () => {},
    });
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const es = FakeEventSource.instances[0]!;
    es.open();
    const many = Array.from({ length: DEDUP_WINDOW + 100 }, (_, i) => ({ ...full.events[0]!, id: `req_${i}`, seq: i + 1 }));
    for (const e of many) es.send(e);
    expect(got).toHaveLength(many.length);
    // the newest DEDUP_WINDOW ids are still deduplicated ...
    for (const e of many.slice(-DEDUP_WINDOW)) es.send(e);
    expect(got).toHaveLength(many.length);
    // ... the oldest were evicted: the set no longer holds every id ever seen
    es.send(many[0]);
    expect(got).toHaveLength(many.length + 1);
    conn.close();
  });
});

describe("startFixtureFeed", () => {
  it("replays recorded events with distinct ids and no original values", () => {
    vi.useFakeTimers();
    const recorded = (fixture.events as unknown[]).map(parseTrafficEvent) as TrafficEvent[];
    const got: TrafficEvent[] = [];
    const feed = startFixtureFeed(recorded, (e) => got.push(...e), { intervalMs: 100, initial: 3 });
    expect(got).toHaveLength(3);
    vi.advanceTimersByTime(250);
    expect(got).toHaveLength(5);
    feed.close();
    expect(new Set(got.map((e) => e.id)).size).toBe(5);
    for (const e of got) {
      expect(e.level).toBe("masked");
      expect(e.request?.original).toBeUndefined();
      expect(e.response?.unmasked).toBeUndefined();
    }
    const blob = JSON.stringify(fixture);
    // every demo value is masked in rules-only mode, names included (session known values) ...
    for (const value of DEMO_SCENARIOS.filter((s) => !s.requires.length).flatMap((s) => s.gold)) {
      expect(blob).not.toContain(value);
    }
    // ... except the labelled NER-only scenario's free-text name: the expected miss
    expect(blob).toContain("Gipsz Jakab");
  });

  it("plays each recorded call once, then stops and reports done (LAB-1200)", () => {
    vi.useFakeTimers();
    const recorded = (fixture.events as unknown[]).map(parseTrafficEvent) as TrafficEvent[];
    const got: TrafficEvent[] = [];
    const onDone = vi.fn();
    const feed = startFixtureFeed(recorded, (e) => got.push(...e), { intervalMs: 100, initial: 3, onDone });
    vi.advanceTimersByTime(100 * (recorded.length - 3) - 1);
    expect(onDone).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(got).toHaveLength(recorded.length);
    expect(onDone).toHaveBeenCalledTimes(1);
    // Nothing more arrives: no second pass, no duplicated calls.
    vi.advanceTimersByTime(100 * recorded.length * 3);
    expect(got).toHaveLength(recorded.length);
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(got.map((e) => e.id)).toEqual(recorded.map((e) => `${e.id}_demo`));
    expect(got.map((e) => e.seq)).toEqual(recorded.map((_, i) => i + 1));
    feed.close();
    vi.useRealTimers();
  });

  it("gives a replayed call the same id every pass, so a repeat is deduped", () => {
    vi.useFakeTimers();
    const recorded = (fixture.events as unknown[]).map(parseTrafficEvent) as TrafficEvent[];
    const passes: string[][] = [[], []];
    for (const pass of passes) {
      const feed = startFixtureFeed(recorded, (e) => pass.push(...e.map((x) => x.id)), { intervalMs: 10 });
      vi.advanceTimersByTime(10 * recorded.length);
      feed.close();
    }
    expect(passes[0]).toEqual(passes[1]);
    expect(new Set(passes[0]).size).toBe(recorded.length);
    vi.useRealTimers();
  });

  it("finishes at once when the burst holds the whole recording, or it is empty", () => {
    const one = (fixture.events as unknown[]).slice(0, 2).map(parseTrafficEvent) as TrafficEvent[];
    const got: TrafficEvent[] = [];
    const onDone = vi.fn();
    startFixtureFeed(one, (e) => got.push(...e), { initial: 8, onDone });
    expect(got).toHaveLength(2);
    expect(onDone).toHaveBeenCalledTimes(1);
    const none = vi.fn();
    startFixtureFeed([], () => {}, { onDone: none });
    expect(none).toHaveBeenCalledTimes(1);
  });
});
