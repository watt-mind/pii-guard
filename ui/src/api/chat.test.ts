import { describe, expect, it } from "vitest";
import { DEFAULT_MAX_TOKENS, FALLBACK_CHAT_MODEL, asKeptSpans, createHttpChat, createMockChat, isChatModel, pickDefaultModel } from "./chat";
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

  it("reads kept spans from the echo as UTF-16 offsets (LAB-1180)", async () => {
    // An astral character first: the gateway counts code points, JS strings UTF-16 units.
    const content = "\u{1F600} Minta Kft writes.";
    const body = sse([
      {
        object: "pii_guard.masked_request",
        messages: [{ role: "system", content: "s" }, { role: "user", content }],
        kept_spans: [[], [{ type: "ORGANIZATION", start: 2, end: 11 }]],
      },
      "[DONE]",
    ]);
    const fetch = (async () => new Response(body, { headers: { "content-type": "text/event-stream" } })) as unknown as typeof globalThis.fetch;
    let seen: unknown;
    const r = await createHttpChat({ fetch }).send({
      messages: [{ role: "system", content: "s" }, { role: "user", content }],
      model: "m",
      mode: "fast",
      language: "en",
      sessionId: null,
      onMaskedRequest: (_m, kept) => (seen = kept),
    });
    const expected = [[], [{ entityType: "ORGANIZATION", start: 3, end: 12 }]];
    expect(r.keptSpans).toEqual(expected);
    expect(seen).toEqual(expected);
    expect(content.slice(3, 12)).toBe("Minta Kft");
  });

  it("drops malformed or out-of-range kept spans", () => {
    const messages = [{ role: "user" as const, content: "abc" }];
    expect(asKeptSpans(undefined, messages)).toEqual([[]]);
    expect(asKeptSpans([[{ type: "ORGANIZATION", start: 1, end: 9 }, { type: 3, start: 0, end: 1 }, { type: "ORGANIZATION", start: 2, end: 2 }]], messages)).toEqual([[]]);
    expect(asKeptSpans([[{ type: "ORGANIZATION", start: 0, end: 3 }]], messages)).toEqual([[{ entityType: "ORGANIZATION", start: 0, end: 3 }]]);
  });

  it("maps a contract error to ApiError", async () => {
    const fetch = (async () =>
      new Response(JSON.stringify({ error: { code: "upstream_not_configured", message: "no upstream" } }), { status: 503 })) as unknown as typeof globalThis.fetch;
    await expect(
      createHttpChat({ fetch }).send({ messages: [], model: "m", mode: "audit", language: "hu", sessionId: null }),
    ).rejects.toMatchObject({ code: "upstream_not_configured" });
  });
});

describe("simulated chat", () => {
  it("masks with the demo engine and restores the scripted answer", async () => {
    const r = await createMockChat(createMockClient(), { delayMs: 0 }).send({
      messages: [{ role: "user", content: "Teszt Elek vagyok, teszt.elek@example.com." }],
      model: "m",
      mode: "audit",
      language: "hu",
      sessionId: null,
    });
    expect(r.maskedMessages[0]!.content).not.toContain("Teszt Elek");
    expect(r.maskedAnswer).toMatch(/\[\[PERSON_[0-9a-f]{4,}\]\]/);
    expect(r.answer).toContain("Teszt Elek");
    expect(r.answer).not.toMatch(/\[\[/);
  });
});

describe("Playground model defaulting (LAB-1335)", () => {
  const META = [
    "muse-image-1.0",
    "muse-voice-transcribe-1.0",
    "sam-3.1",
    "muse-spark-1.2",
    "muse-wonder-1.0",
    "muse-spark-1.3",
    "muse-spark-1.3-contributor",
  ];

  it("prefers the last-used model while the upstream still lists it", () => {
    expect(pickDefaultModel(META, "muse-spark-1.2")).toBe("muse-spark-1.2");
    expect(pickDefaultModel(META, "meta-models/muse-spark-open-1026")).toBe("muse-spark-1.3");
  });

  it("then muse-spark-1.3, then muse-wonder-1.0", () => {
    expect(pickDefaultModel(META, null)).toBe("muse-spark-1.3");
    expect(pickDefaultModel(META.filter((m) => m !== "muse-spark-1.3"), null)).toBe("muse-wonder-1.0");
  });

  it("otherwise the first chat-capable id, skipping transcribe, image and SAM ids", () => {
    expect(pickDefaultModel(["sam-3.1", "muse-image-1.0", "muse-voice-transcribe-1.0", "gpt-x", "other"], null)).toBe("gpt-x");
    expect(isChatModel("sam-3.1")).toBe(false);
    expect(isChatModel("meta/sam-3.1")).toBe(false);
    expect(isChatModel("muse-image-1.0")).toBe(false);
    expect(isChatModel("muse-voice-transcribe-1.0")).toBe(false);
    expect(isChatModel("text-embedding-3-small")).toBe(false);
    expect(isChatModel("samba-chat")).toBe(true);
    expect(isChatModel("muse-spark-1.3-contributor")).toBe(true);
  });

  it("never falls back to a Baseten id when nothing is listed", () => {
    expect(FALLBACK_CHAT_MODEL).not.toMatch(/meta-models\//);
    expect(pickDefaultModel([], null)).toBe(FALLBACK_CHAT_MODEL);
  });

  it("lists the gateway's models, de-duplicated, and fails on a contract error", async () => {
    let url = "";
    const ok = (async (u: string) => {
      url = u;
      return new Response(JSON.stringify({ object: "list", data: [{ id: "muse-spark-1.3" }, { id: "sam-3.1" }, { id: "muse-spark-1.3" }, { nope: 1 }] }));
    }) as unknown as typeof globalThis.fetch;
    expect(await createHttpChat({ fetch: ok, baseUrl: "http://g/" }).listModels!()).toEqual(["muse-spark-1.3", "sam-3.1"]);
    expect(url).toBe("http://g/v1/models");
    const bad = (async () =>
      new Response(JSON.stringify({ error: { code: "upstream_unavailable", message: "x" } }), { status: 502 })) as unknown as typeof globalThis.fetch;
    await expect(createHttpChat({ fetch: bad }).listModels!()).rejects.toMatchObject({ code: "upstream_unavailable" });
  });

  it("asks for enough tokens for a reasoning model and reports finish_reason", async () => {
    let body: Record<string, unknown> = {};
    const fetch = (async (_u: string, init: RequestInit) => {
      body = JSON.parse(init.body as string) as Record<string, unknown>;
      return new Response(sse([{ choices: [{ index: 0, delta: { reasoning_content: "hmm" } }] }, { choices: [{ index: 0, delta: {}, finish_reason: "length" }] }, "[DONE]"]), {
        headers: { "content-type": "text/event-stream", "x-pii-guard-session": "s_1" },
      });
    }) as unknown as typeof globalThis.fetch;
    const r = await createHttpChat({ fetch }).send({ messages: [{ role: "user", content: "hi" }], model: "muse-spark-1.3", mode: "fast", language: "en", sessionId: null });
    expect(body.max_tokens).toBeGreaterThanOrEqual(2048);
    expect(body.max_tokens).toBe(DEFAULT_MAX_TOKENS);
    expect(r.answer).toBe("");
    expect(r.finishReason).toBe("length");
  });

  it("keeps upstream_error's status for the error copy", async () => {
    const fetch = (async () =>
      new Response(JSON.stringify({ error: { code: "upstream_error", message: "upstream returned HTTP 404", type: "upstream_error" } }), { status: 404 })) as unknown as typeof globalThis.fetch;
    await expect(
      createHttpChat({ fetch }).send({ messages: [{ role: "user", content: "hi" }], model: "x", mode: "fast", language: "en", sessionId: null }),
    ).rejects.toMatchObject({ code: "upstream_error", status: 404 });
  });
});
