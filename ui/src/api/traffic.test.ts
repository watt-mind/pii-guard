import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import full from "../test/trafficFull.json";
import fixture from "../content/trafficFixture.json";
import { DEMO_SCENARIOS } from "./demoTraffic";
import { ApiError, UnreachableError } from "./http";
import { SSE_MAX_ERRORS, connectTraffic, fetchTraffic, parseTrafficEvent, startFixtureFeed, type TrafficEvent, type TrafficStatus } from "./traffic";

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

describe("startFixtureFeed", () => {
  it("replays recorded events with fresh ids and no original values", () => {
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
});
