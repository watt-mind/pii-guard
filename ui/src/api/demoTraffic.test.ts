import { describe, expect, it, vi } from "vitest";
import { DEMO_REQUESTS, sendDemoTraffic } from "./demoTraffic";
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
    // the follow-up continues the first turn's session, the known-values call uses its session
    expect(chats[1]!.headers["X-PII-Guard-Session"]).toBe("sess_1");
    expect(chats.find((c) => JSON.stringify(c.body).includes("Minta Mária"))!.headers["X-PII-Guard-Session"]).toBe("sess_known");
    expect(chats.filter((c) => c.body.tools)).toHaveLength(2);
    expect(chats.filter((c) => c.body.stream)).toHaveLength(3);
  });

  it("fails when the gateway can't be reached", async () => {
    await expect(sendDemoTraffic({ fetch: async () => Promise.reject(new TypeError("down")) })).rejects.toBeInstanceOf(UnreachableError);
  });
});
