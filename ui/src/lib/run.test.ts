import { describe, expect, it, vi } from "vitest";
import { createMockClient } from "../api/mock";
import { createRoutingClient } from "../api/engine";
import { DEFAULT_SAMPLE } from "../content/samples";
import { runGuard } from "./run";

describe("UI run language", () => {
  it.each([undefined, "en", "hu", "de"])("uses English only when language is omitted (%s)", async (language) => {
    const mock = createMockClient();
    const analyze = vi.spyOn(mock, "analyze");
    const mask = vi.spyOn(mock, "mask");
    const client = createRoutingClient({ api: mock, mock, getState: () => ({ preference: "mock", status: { state: "offline" }, endpointsMissing: false }), onEndpointsMissing: vi.fn(), onUnreachable: vi.fn() });
    const result = await runGuard(client, DEFAULT_SAMPLE.text, DEFAULT_SAMPLE.id, { language });
    expect(result.language).toBe(language ?? "en");
    for (const call of [analyze, mask]) expect(call).toHaveBeenCalledWith(expect.objectContaining({ language: language ?? "en" }));
  });
});
