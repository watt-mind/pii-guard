import { describe, expect, it, vi } from "vitest";
import { fetchStatus, parseStatus } from "./status";

const BODY = {
  version: "0.1.0",
  gateway: { url: "http://127.0.0.1:8899/v1", default_mode: "fast", modes: { fast: { detectors: ["rules"], available: true, reason: null }, audit: { detectors: [], available: false, reason: "no key" } } },
  rest: { detectors: ["rules"] },
  ner: { available: false, model: null },
  upstream: { configured: true, mock: true, origin: null },
  images: { segmenter: "hybrid", sam: false, ocr_required: true, gaps: [], available: true },
  policies: { EMAIL: "block" },
  auth: { token_required: false },
  default_language: "hu",
  traffic_log: "masked",
  metrics: false,
};

const answer = (status: number, body: unknown) => vi.fn(() => Promise.resolve(new Response(typeof body === "string" ? body : JSON.stringify(body), { status })));

describe("GET /v1/status", () => {
  it("reads the server's configuration", async () => {
    const f = answer(200, BODY);
    const result = await fetchStatus(f as unknown as typeof fetch, "http://127.0.0.1:8899/");
    expect(f).toHaveBeenCalledWith("http://127.0.0.1:8899/v1/status", expect.anything());
    expect(result).toEqual({ state: "ok", status: BODY });
  });

  it("treats a 404 as a server that predates the endpoint", async () => {
    expect(await fetchStatus(answer(404, { detail: "Not Found" }) as unknown as typeof fetch)).toEqual({ state: "missing" });
  });

  it("treats a body it can't read as missing, not as a configuration", async () => {
    expect(await fetchStatus(answer(200, { version: "0.0.1" }) as unknown as typeof fetch)).toEqual({ state: "missing" });
    expect(parseStatus({ ...BODY, gateway: { ...BODY.gateway, url: 8 } })).toBeNull();
  });

  it("reports offline when the server can't be reached or fails", async () => {
    expect(await fetchStatus((() => Promise.reject(new TypeError("fetch failed"))) as unknown as typeof fetch)).toEqual({ state: "offline" });
    expect(await fetchStatus(answer(500, "boom") as unknown as typeof fetch)).toEqual({ state: "offline" });
    expect(await fetchStatus(answer(200, "not json") as unknown as typeof fetch)).toEqual({ state: "offline" });
  });
});
