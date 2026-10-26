import { describe, expect, it, vi } from "vitest";
import { createRoutingClient, effectiveEngine, type EngineState } from "./engine";
import { ApiError, createHttpClient, UnreachableError } from "./http";
import { createMockClient } from "./mock";
import type { GuardClient } from "./types";

const online: EngineState = { preference: "auto", status: { state: "online", version: "0.1.0" }, endpointsMissing: false };

function failingApi(err: Error): GuardClient {
  return {
    analyze: vi.fn().mockRejectedValue(err),
    mask: vi.fn().mockRejectedValue(err),
    unmask: vi.fn().mockRejectedValue(err),
  };
}

function setup(api: GuardClient, state: EngineState) {
  const onEndpointsMissing = vi.fn();
  const onUnreachable = vi.fn();
  const client = createRoutingClient({
    api,
    mock: createMockClient(),
    getState: () => state,
    onEndpointsMissing,
    onUnreachable,
  });
  return { client, onEndpointsMissing, onUnreachable };
}

describe("effectiveEngine", () => {
  it("follows the preference, and in auto mode the API's health", () => {
    expect(effectiveEngine(online)).toBe("api");
    expect(effectiveEngine({ ...online, preference: "mock" })).toBe("mock");
    expect(effectiveEngine({ ...online, status: { state: "offline" } })).toBe("mock");
    expect(effectiveEngine({ ...online, status: { state: "checking" } })).toBe("pending");
    expect(effectiveEngine({ ...online, endpointsMissing: true })).toBe("mock");
    expect(effectiveEngine({ ...online, preference: "api", status: { state: "offline" } })).toBe("api");
  });
});

describe("routing client", () => {
  it("falls back to the demo engine when the API is unreachable (auto)", async () => {
    const { client, onUnreachable } = setup(failingApi(new UnreachableError()), online);
    const res = await client.mask({ text: "Teszt Elek" });
    expect(res.engine).toBe("mock");
    expect(res.data.masked_text).toMatch(/^\[\[PERSON_/);
    expect(onUnreachable).toHaveBeenCalled();
  });

  it("falls back when the /v1 routes are missing (auto)", async () => {
    const { client, onEndpointsMissing } = setup(failingApi(new ApiError(404, "not_found", "nope")), online);
    const res = await client.analyze({ text: "Teszt Elek" });
    expect(res.engine).toBe("mock");
    expect(onEndpointsMissing).toHaveBeenCalled();
  });

  it("re-probes the API on every call, so a transient 404 can't pin the demo engine", async () => {
    const api: GuardClient = {
      analyze: vi
        .fn()
        .mockRejectedValueOnce(new ApiError(404, "not_found", "starting"))
        .mockResolvedValue({ spans: [] }),
      mask: vi.fn(),
      unmask: vi.fn(),
    };
    const onApiSuccess = vi.fn();
    const client = createRoutingClient({
      api,
      mock: createMockClient(),
      getState: () => ({ ...online, endpointsMissing: true }),
      onEndpointsMissing: () => {},
      onUnreachable: () => {},
      onApiSuccess,
    });
    expect((await client.analyze({ text: "x" })).engine).toBe("mock");
    expect(await client.analyze({ text: "x" })).toEqual({ engine: "api", data: { spans: [] } });
    expect(onApiSuccess).toHaveBeenCalledOnce();
  });

  it("tries the API while the first health check is still pending", async () => {
    const api: GuardClient = { analyze: vi.fn().mockResolvedValue({ spans: [] }), mask: vi.fn(), unmask: vi.fn() };
    const { client } = setup(api, { ...online, status: { state: "checking" } });
    expect((await client.analyze({ text: "x" })).engine).toBe("api");
  });

  it("fails closed on a contract error: no fallback, the error surfaces", async () => {
    const { client } = setup(failingApi(new ApiError(503, "detection_failed", "detector timed out")), online);
    await expect(client.mask({ text: "Teszt Elek" })).rejects.toMatchObject({ code: "detection_failed" });
  });

  it("never falls back when the live API was chosen explicitly", async () => {
    const { client } = setup(failingApi(new UnreachableError()), { ...online, preference: "api" });
    await expect(client.mask({ text: "Teszt Elek" })).rejects.toBeInstanceOf(UnreachableError);
  });

  it("unmasks a session in the engine that created it", async () => {
    const api = failingApi(new UnreachableError());
    const { client } = setup(api, { ...online, preference: "mock" });
    const masked = await client.mask({ text: "Teszt Elek" });
    const back = await client.unmask({ text: masked.data.masked_text, session_id: masked.data.session_id });
    expect(back).toEqual({ engine: "mock", data: { text: "Teszt Elek", unresolved: [] } });
    expect(api.unmask).not.toHaveBeenCalled();
  });
});

describe("http client", () => {
  const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  it("posts the contract body and returns the parsed response", async () => {
    const fetch = vi.fn().mockResolvedValue(json(200, { spans: [] }));
    const http = createHttpClient({ fetch, baseUrl: "http://guard.test/" });
    await expect(http.analyze({ text: "x", language: "hu" })).resolves.toEqual({ spans: [] });
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("http://guard.test/v1/analyze");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ text: "x", language: "hu" });
  });

  it("turns contract error bodies into ApiError", async () => {
    const fetch = vi.fn().mockResolvedValue(json(503, { error: { code: "detection_failed", message: "could not finish" } }));
    await expect(createHttpClient({ fetch }).mask({ text: "x" })).rejects.toMatchObject({
      status: 503,
      code: "detection_failed",
      message: "could not finish",
    });
  });

  it("treats FastAPI's default 404 as a missing route", async () => {
    const fetch = vi.fn().mockResolvedValue(json(404, { detail: "Not Found" }));
    await expect(createHttpClient({ fetch }).mask({ text: "x" })).rejects.toMatchObject({ status: 404, code: "not_found" });
  });

  it("treats network failures and non-contract 5xx pages as unreachable", async () => {
    const down = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(createHttpClient({ fetch: down }).health()).rejects.toBeInstanceOf(UnreachableError);
    const proxy = vi.fn().mockResolvedValue(new Response("", { status: 500 }));
    await expect(createHttpClient({ fetch: proxy }).health()).rejects.toBeInstanceOf(UnreachableError);
  });
});
