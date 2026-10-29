import { describe, expect, it, vi } from "vitest";
import { createRoutingClient, type EngineState } from "./engine";
import { ApiError, createHttpClient, UnreachableError } from "./http";
import { createMockImageEngine, DemoImageUnavailableError, IMAGE_RECORDINGS } from "./imageMock";
import { createMockClient } from "./mock";
import type { GuardClient, ImageMaskResponse } from "./types";

const online: EngineState = { preference: "auto", status: { state: "online", version: "0.1.0" }, endpointsMissing: false };
const png = () => new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: "image/png" });

const liveResponse: ImageMaskResponse = {
  image: "iVBORw0KGgo=",
  media_type: "image/png",
  width: 10,
  height: 10,
  regions: [{ entity_type: "FACE", box: [1, 1, 5, 5], source: "sam", detector: "sam", score: null, policy: "mask" }],
  masked: [{ entity_type: "FACE", count: 1 }],
  kept: [],
  analysis: { sam: { model: "sam-3.1", entity_types: ["FACE"] }, ocr: { ran: false, engine: null, detectors: [], reason: "tesseract_unavailable" } },
};

function textOnly(err?: Error): GuardClient {
  const fail = vi.fn().mockRejectedValue(err ?? new UnreachableError());
  return { analyze: fail, mask: fail, unmask: fail };
}

describe("http maskImage", () => {
  it("posts the raw image with its content type and the language", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(liveResponse), { status: 200 }));
    const client = createHttpClient({ fetch });
    const res = await client.maskImage!({ image: png(), language: "hu", sampleId: "id-card" });
    expect(res.regions).toHaveLength(1);
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/v1/mask/image?language=hu");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("image/png");
    expect(init.body).toBeInstanceOf(Blob);
    expect(String(url)).not.toContain("id-card"); // the sample id never goes on the wire
  });

  it("maps contract errors, such as a fail-closed 503", async () => {
    const body = { error: { code: "detection_failed", message: "SAM request failed: HTTP 500" } };
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 503 }));
    await expect(createHttpClient({ fetch }).maskImage!({ image: png() })).rejects.toMatchObject({
      status: 503,
      code: "detection_failed",
    });
  });
});

describe("demo image engine", () => {
  it("replays the recorded regions for a built-in sample, without an image", async () => {
    const res = await createMockImageEngine().maskImage({ image: png(), sampleId: "id-card" });
    expect(res.image).toBe("");
    expect(res.regions.map((r) => r.entity_type)).toContain("FACE");
    expect(res.regions.some((r) => r.source === "ocr")).toBe(true);
    expect(res).not.toBe(IMAGE_RECORDINGS.samples["id-card"]);
  });

  it("refuses uploads instead of pretending", async () => {
    await expect(createMockImageEngine().maskImage({ image: png(), sampleId: null })).rejects.toBeInstanceOf(DemoImageUnavailableError);
  });

  it("has a recording for every sample, with values-free regions", () => {
    for (const rec of Object.values(IMAGE_RECORDINGS.samples)) {
      for (const r of rec.regions) {
        expect(Object.keys(r).sort()).toEqual(["box", "detector", "entity_type", "policy", "score", "source"]);
        expect(r.box[2]).toBeLessThan(rec.width);
        expect(r.box[3]).toBeLessThan(rec.height);
      }
    }
  });
});

describe("routing maskImage", () => {
  const route = (api: GuardClient, state: EngineState = online) =>
    createRoutingClient({ api, mock: createMockClient(), getState: () => state, onEndpointsMissing: vi.fn(), onUnreachable: vi.fn() });

  it("uses the live API when it answers", async () => {
    const api = { ...textOnly(), maskImage: vi.fn().mockResolvedValue(liveResponse) };
    const res = await route(api).maskImage({ image: png(), sampleId: "id-card" });
    expect(res.engine).toBe("api");
    expect(res.data.image).toBe(liveResponse.image);
  });

  it("falls back to recorded regions in auto mode when the API is unreachable or lacks the route", async () => {
    const unreachable = { ...textOnly(), maskImage: vi.fn().mockRejectedValue(new UnreachableError()) };
    expect((await route(unreachable).maskImage({ image: png(), sampleId: "id-card" })).engine).toBe("mock");
    const missing = { ...textOnly(), maskImage: vi.fn().mockRejectedValue(new ApiError(404, "not_found", "x")) };
    expect((await route(missing).maskImage({ image: png(), sampleId: "id-card" })).engine).toBe("mock");
    expect((await route(textOnly()).maskImage({ image: png(), sampleId: "id-card" })).engine).toBe("mock");
  });

  it("never falls back on a contract error: the guard failed closed", async () => {
    const api = { ...textOnly(), maskImage: vi.fn().mockRejectedValue(new ApiError(503, "detection_failed", "x")) };
    await expect(route(api).maskImage({ image: png(), sampleId: "id-card" })).rejects.toMatchObject({ code: "detection_failed" });
  });

  it("in Live API mode reports a missing route instead of using the demo", async () => {
    await expect(route(textOnly(), { ...online, preference: "api" }).maskImage({ image: png() })).rejects.toBeInstanceOf(UnreachableError);
  });
});
