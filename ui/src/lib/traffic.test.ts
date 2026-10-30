import { describe, expect, it } from "vitest";
import full from "../test/trafficFull.json";
import fixture from "../content/trafficFixture.json";
import { parseTrafficEvent, type TrafficEvent } from "../api/traffic";
import {
  refusalReason,
  OWN_STAGES,
  alignValues,
  canShowOriginals,
  entitiesPerMinute,
  isLoopbackHost,
  maskedCounts,
  modeOrder,
  overheadByMode,
  percentile,
  requestMessages,
  requestTools,
  responseChoices,
  rollingOverhead,
  waterfall,
} from "./traffic";

const parse = (raw: unknown[]) => raw.map(parseTrafficEvent) as TrafficEvent[];
const recorded = [...parse(full.events), ...parse(fixture.events)];

describe("waterfall", () => {
  it.each(recorded.map((e) => [e.id, e] as const))("matches the event payload of %s", (_id, e) => {
    const w = waterfall(e.timing);
    // Totals are the payload's own.
    expect(w.total).toBe(e.timing.total_ms);
    expect(w.upstream).toBe(e.timing.upstream_ms);
    expect(w.overhead).toBe(e.timing.overhead_ms);
    // Every stage that ran is a row with exactly its stages_ms value, in pipeline order.
    for (const stage of OWN_STAGES) {
      const ms = e.timing.stages_ms[stage] ?? 0;
      const row = w.rows.find((r) => r.key === stage);
      if (ms > 0) expect(row?.ms).toBe(ms);
      else expect(row).toBeUndefined();
    }
    const up = w.rows.find((r) => r.key === "upstream");
    if (e.timing.upstream_ms > 0) {
      expect(up?.ms).toBe(e.timing.upstream_ms);
      expect(up?.ttfbMs).toBe(e.timing.stages_ms.upstream_ttfb);
    }
    // pii-guard's stages plus "other" are the overhead (payload values are rounded to µs).
    expect(Math.abs(w.own + w.other - e.timing.overhead_ms)).toBeLessThan(0.002);
    // Rows are laid end to end.
    for (let i = 1; i < w.rows.length; i++) {
      expect(w.rows[i]!.start).toBeCloseTo(w.rows[i - 1]!.start + w.rows[i - 1]!.ms, 3);
    }
    expect(w.span).toBeGreaterThanOrEqual(w.total);
  });

  it("orders stages as the pipeline runs them", () => {
    const w = waterfall(recorded[0]!.timing);
    expect(w.rows.map((r) => r.key)).toEqual(["parse", "detect", "mask", "forward", "upstream", "response", "other"]);
  });

  it("reports the stream's time to first token", () => {
    const stream = recorded.find((e) => e.stream && e.timing.ttft_ms !== null)!;
    const w = waterfall(stream.timing);
    expect(w.ttft).toBe(stream.timing.ttft_ms);
    expect(w.addedTtft).toBe(stream.timing.added_ttft_ms);
    expect(w.rows.some((r) => r.key === "unmask")).toBe(true);
  });

  it("has no upstream bar when the call was refused", () => {
    const refused = recorded.find((e) => e.outcome === "refused")!;
    expect(waterfall(refused.timing).rows.some((r) => r.key === "upstream")).toBe(false);
  });
});

describe("stats", () => {
  it("interpolates percentiles like numpy", () => {
    expect(percentile([], 50)).toBeNull();
    expect(percentile([5], 95)).toBe(5);
    expect(percentile([1, 2, 3, 4], 50)).toBe(2.5);
    expect(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95)).toBeCloseTo(9.55);
  });

  it("rolls p50/p95 over the last N events", () => {
    const pts = rollingOverhead(recorded, 3);
    expect(pts).toHaveLength(recorded.length);
    const last3 = recorded.slice(-3).map((e) => e.timing.overhead_ms);
    expect(pts.at(-1)!.p50).toBe(percentile(last3, 50));
    expect(pts.at(-1)!.overhead).toBe(recorded.at(-1)!.timing.overhead_ms);
  });

  it("groups overhead by mode", () => {
    const rows = overheadByMode(recorded);
    expect(rows.map((r) => r.mode)).toEqual(["fast"]);
    expect(rows[0]!.n).toBe(recorded.length);
  });

  it("orders modes fast, audit, then the rest", () => {
    expect(modeOrder(["unknown", "audit", "fast"])).toEqual(["fast", "audit", "unknown"]);
    const audit = recorded.map((e) => ({ ...e, mode: "audit" }));
    expect(overheadByMode([...audit, ...recorded]).map((r) => r.mode)).toEqual(["fast", "audit"]);
  });

  it("buckets masked values per minute and type", () => {
    const now = Date.parse("2026-10-27T12:00:30Z");
    const at = (iso: string, e: TrafficEvent): TrafficEvent => ({ ...e, time: iso });
    const hu = recorded[0]!; // 4 values: EMAIL, PHONE, BANK_ACCOUNT, TAJ
    const b = entitiesPerMinute([at("2026-10-27T12:00:10Z", hu), at("2026-10-27T11:59:59Z", hu), at("2026-10-27T11:30:00Z", hu)], now, 10);
    expect(b).toHaveLength(10);
    expect(b.at(-1)!.total).toBe(4);
    expect(b.at(-2)!.total).toBe(4);
    expect(b.at(-1)!.counts.EMAIL).toBe(1);
    expect(b.slice(0, -2).every((x) => x.total === 0)).toBe(true);
    expect(maskedCounts(hu)).toEqual({ BANK_ACCOUNT: 1, EMAIL: 1, NATIONAL_ID_HU_TAJ: 1, PHONE: 1 });
  });
});

describe("payloads", () => {
  it("reads messages, tools and tool calls", () => {
    const tools = recorded.find((e) => requestTools(e.request?.masked).length)!;
    expect(requestTools(tools.request?.masked)[0]!.name).toBe("send_email");
    const choice = responseChoices(tools.response?.masked)[0]!;
    expect(choice.content).toBeNull();
    expect(choice.toolCalls[0]!.arguments).toMatch(/\[\[EMAIL_[0-9a-f]+\]\]/);
    const original = responseChoices(tools.response?.unmasked)[0]!;
    const segs = alignValues(choice.toolCalls[0]!.arguments, original.toolCalls[0]!.arguments)!;
    expect(segs.filter((s) => s.kind === "restored").map((s) => s.text)).toContain("erika.mustermann@example.de");
  });

  it("reads a stream's collected content", () => {
    const stream = recorded.find((e) => e.stream && e.request?.original)!;
    const [c] = responseChoices(stream.response?.masked);
    expect(c!.content).toMatch(/^Echo: .*\[\[ADDRESS_[0-9a-f]+\]\]/);
    expect(responseChoices(stream.response?.unmasked)[0]!.content).toContain("1051 Budapest, Minta utca 12.");
  });

  it("reads a stream's collected tool calls next to its content", () => {
    const call = (args: string) => ({ index: 0, id: "call_0", type: "function", function: { name: "send_email", arguments: args } });
    const masked = { content: { "0": "Sending." }, tool_calls: { "0": [call('{"to": "[[EMAIL_7f3a]]"}')], "1": [call("{}")] } };
    const choices = responseChoices(masked);
    expect(choices.map((c) => c.index)).toEqual([0, 1]);
    expect(choices[0]).toEqual({ index: 0, content: "Sending.", toolCalls: [{ name: "send_email", arguments: '{"to": "[[EMAIL_7f3a]]"}' }] });
    expect(choices[1]).toMatchObject({ content: null, toolCalls: [{ name: "send_email", arguments: "{}" }] });
    expect(responseChoices({ content: {} })).toEqual([]);
  });

  it("keeps an image part as its summary", () => {
    const img = recorded.find((e) => e.entities?.images)!;
    const [m] = requestMessages(img.request?.original);
    expect(m!.parts.map((p) => p.kind)).toEqual(["text", "image"]);
    expect(m!.parts[1]).toMatchObject({ kind: "image", summary: "[inline image/png, 330 chars]" });
  });
});

describe("originals", () => {
  it("are shown only at level full, from the API, on a loopback page", () => {
    const fullEvent = recorded[0]!;
    const maskedEvent = { ...fullEvent, level: "masked" as const };
    expect(canShowOriginals(fullEvent, "localhost", "api")).toBe(true);
    expect(canShowOriginals(fullEvent, "127.0.0.1", "api")).toBe(true);
    expect(canShowOriginals(fullEvent, "demo.example.com", "api")).toBe(false);
    expect(canShowOriginals(fullEvent, "localhost", "fixture")).toBe(false);
    expect(canShowOriginals(maskedEvent, "localhost", "api")).toBe(false);
    expect(isLoopbackHost("[::1]")).toBe(true);
    expect(isLoopbackHost("app.localhost")).toBe(true);
    expect(isLoopbackHost("10.0.0.2")).toBe(false);
  });
});

describe("refusalReason (LAB-1287)", () => {
  it("names the cause from the error code instead of always blaming detection", () => {
    expect(refusalReason("not_found", false)).toMatch(/Unknown or expired session/);
    expect(refusalReason("detection_unavailable", false)).toMatch(/audit mode/);
    expect(refusalReason("blocked_entity", false)).toMatch(/policy block/);
    expect(refusalReason(undefined, false)).toMatch(/fails closed/);
  });
});
