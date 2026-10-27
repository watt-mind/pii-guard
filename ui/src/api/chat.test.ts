import { describe, expect, it } from "vitest";
import { createHttpChat, createMockChat } from "./chat";
import { createMockClient } from "./mock";

function sse(events: unknown[]): string {
  return events.map((e) => `data: ${typeof e === "string" ? e : JSON.stringify(e)}\n\n`).join("");
}

describe("gateway chat client", () => {
  it("reads the echoed masked request, the restored stream and the masked answer", async () => {
    const body = sse([
      { object: "pii_guard.masked_request", messages: [{ role: "user", content: "Szia [[PERSON_ab12]]!" }] },
      { choices: [{ index: 0, delta: { reasoning_content: "thinking" } }] },
      { choices: [{ index: 0, delta: { content: "Szia " } }] },
      { choices: [{ index: 0, delta: { content: "Teszt Elek!" } }] },
      { object: "pii_guard.masked_answer", choices: [{ index: 0, content: "Szia [[PERSON_ab12]]!" }] },
      "[DONE]",
    ]);
    let request: RequestInit | undefined;
    const fetch = (async (_url: string, init: RequestInit) => {
      request = init;
      return new Response(body, { headers: { "content-type": "text/event-stream", "x-pii-guard-session": "s_1", "x-pii-guard-masked": "1" } });
    }) as unknown as typeof globalThis.fetch;
    const seen: string[] = [];
    let thinking = false;
    const r = await createHttpChat({ fetch }).send({
      messages: [{ role: "user", content: "Szia Teszt Elek!" }],
      model: "m",
      mode: "fast",
      language: "hu",
      sessionId: null,
      onAnswer: (a) => seen.push(a),
      onThinking: () => (thinking = true),
    });
    expect(r).toMatchObject({ sessionId: "s_1", answer: "Szia Teszt Elek!", maskedAnswer: "Szia [[PERSON_ab12]]!", masked: 1 });
    expect(r.maskedMessages[0]!.content).toBe("Szia [[PERSON_ab12]]!");
    expect(seen).toEqual(["Szia ", "Szia Teszt Elek!"]);
    expect(thinking).toBe(true);
    const headers = request!.headers as Record<string, string>;
    expect(headers["X-PII-Guard-Echo"]).toBe("masked");
    expect(headers["X-PII-Guard-Mode"]).toBe("fast");
    expect(headers["X-PII-Guard-Session"]).toBeUndefined();
  });

  it("maps a contract error to ApiError", async () => {
    const fetch = (async () =>
      new Response(JSON.stringify({ error: { code: "upstream_not_configured", message: "no upstream" } }), { status: 503 })) as unknown as typeof globalThis.fetch;
    await expect(
      createHttpChat({ fetch }).send({ messages: [], model: "m", mode: "strict", language: "hu", sessionId: null }),
    ).rejects.toMatchObject({ code: "upstream_not_configured" });
  });
});

describe("simulated chat", () => {
  it("masks with the demo engine and restores the scripted answer", async () => {
    const r = await createMockChat(createMockClient(), { delayMs: 0 }).send({
      messages: [{ role: "user", content: "Teszt Elek vagyok, teszt.elek@example.com." }],
      model: "m",
      mode: "strict",
      language: "hu",
      sessionId: null,
    });
    expect(r.maskedMessages[0]!.content).not.toContain("Teszt Elek");
    expect(r.maskedAnswer).toMatch(/\[\[PERSON_[0-9a-f]{4,}\]\]/);
    expect(r.answer).toContain("Teszt Elek");
    expect(r.answer).not.toMatch(/\[\[/);
  });
});
