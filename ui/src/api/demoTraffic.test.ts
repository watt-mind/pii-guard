import { describe, expect, it, vi } from "vitest";
import { DEMO_REQUESTS, DEMO_SCENARIOS, LABELLED_SCENARIOS, labelledScenarioFor, sendDemoTraffic } from "./demoTraffic";
import type { TrafficEvent } from "./traffic";
import fixture from "../content/trafficFixture.json";
import { parseTrafficEvent } from "./traffic";
import { UnreachableError } from "./http";

describe("sendDemoTraffic", () => {
  it("sends every scenario through the gateway, with a session for known values and a follow-up turn", async () => {
    const calls: { url: string; body: Record<string, unknown>; headers: Record<string, string> }[] = [];
    const f = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      calls.push({ url: String(url), body, headers: init?.headers as Record<string, string> });
      if (String(url) === "/v1/sessions") return new Response(JSON.stringify({ session_id: "sess_known" }), { status: 200 });
      const messages = body.messages as { content: unknown }[];
      if (Array.isArray(messages.at(-1)!.content)) {
        return new Response(JSON.stringify({ error: { code: "detection_failed", message: "no SAM" } }), { status: 503 });
      }
      if (body.stream) return new Response('data: {"choices":[{"delta":{"content":"Echo"}}]}\n\ndata: [DONE]\n\n', { status: 200 });
      return new Response(JSON.stringify({ choices: [{ message: { content: "Echo" } }] }), { status: 200, headers: { "X-PII-Guard-Session": "sess_1" } });
    });
    const progress = await sendDemoTraffic({ fetch: f as unknown as typeof fetch });
    expect(progress).toEqual({ done: DEMO_REQUESTS, total: DEMO_REQUESTS, refused: 1 });
    const chats = calls.filter((c) => c.url === "/v1/chat/completions");
    expect(chats).toHaveLength(DEMO_REQUESTS);
    expect(chats.every((c) => c.body.model === "pii-guard-mock")).toBe(true);
    // the follow-up continues the first turn's session, the known-values calls use theirs
    expect(chats[0]!.headers["X-PII-Guard-Session"]).toBe("sess_known");
    expect(chats[1]!.headers["X-PII-Guard-Session"]).toBe("sess_1");
    const sessions = calls.filter((c) => c.url === "/v1/sessions");
    expect(sessions).toHaveLength(DEMO_SCENARIOS.filter((s) => s.known).length);
    // every name is pre-loaded as a known value, except in the labelled NER-only scenario
    const known = sessions.flatMap((c) => (c.body.known_values as { value: string }[]).map((k) => k.value));
    expect(known).toEqual(expect.arrayContaining(["Teszt Elek", "Jane Placeholder", "Erika Mustermann", "Minta Mária"]));
    expect(known).not.toContain("Gipsz Jakab");
    expect(chats.find((c) => JSON.stringify(c.body).includes("Minta Máriának"))!.headers["X-PII-Guard-Session"]).toBe("sess_known");
    expect(chats.filter((c) => c.body.tools)).toHaveLength(2);
    expect(chats.filter((c) => c.body.stream)).toHaveLength(DEMO_SCENARIOS.filter((s) => s.stream).length);
  });

  it("fails when the gateway can't be reached", async () => {
    await expect(sendDemoTraffic({ fetch: async () => Promise.reject(new TypeError("down")) })).rejects.toBeInstanceOf(UnreachableError);
  });
});

describe("labelled demo scenarios", () => {
  const recorded = (fixture.events as unknown[]).map(parseTrafficEvent) as TrafficEvent[];
  const event = (text: string): TrafficEvent => ({ ...recorded[0]!, request: { masked: { messages: [{ role: "user", content: text }] } } });

  it("exactly one scenario needs the NER, and it has no known values", () => {
    expect(LABELLED_SCENARIOS.map((s) => [s.name, s.requires, s.label])).toEqual([["hu-needs-ner", ["ner"], "needs fast mode (NER)"]]);
    expect(LABELLED_SCENARIOS[0]!.known).toBeUndefined();
  });

  it("recognises the labelled call, missed (rules only) or masked (NER)", () => {
    const s = LABELLED_SCENARIOS[0]!;
    expect(labelledScenarioFor(event(s.text))).toEqual({ scenario: s, missed: ["Gipsz Jakab"] });
    const masked = s.text.replace("Gipsz Jakab", "[[PERSON_1a2b3c]]");
    expect(labelledScenarioFor(event(masked))).toEqual({ scenario: s, missed: [] });
    expect(labelledScenarioFor(event("Tegnap valaki telefonált."))).toBeNull();
    expect(labelledScenarioFor({ ...recorded[0]!, request: null })).toBeNull();
  });

  it("the recorded fixture shows the labelled call as the one expected miss", () => {
    const matches = recorded.map(labelledScenarioFor).filter((m) => m !== null);
    expect(matches.length).toBeGreaterThan(0);
    expect(matches.every((m) => m.missed.length === 1)).toBe(true);
    const others = recorded.filter((e) => labelledScenarioFor(e) === null);
    expect(others.length).toBeGreaterThan(matches.length);
  });
});
