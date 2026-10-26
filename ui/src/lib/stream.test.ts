import { describe, expect, it } from "vitest";
import { createRoutingClient, type EngineState } from "../api/engine";
import { createMockClient } from "../api/mock";
import { chunkify, playStream, restore, type StreamStep } from "./stream";

const state: EngineState = { preference: "mock", status: { state: "offline" }, endpointsMissing: false };

function client() {
  const mock = createMockClient();
  return createRoutingClient({ api: mock, mock, getState: () => state, onEndpointsMissing: () => {}, onUnreachable: () => {} });
}

describe("chunkify", () => {
  it("is reproducible and loses nothing", () => {
    const text = "Kedves [[PERSON_7f3a]], köszönjük a levelét! 🙂";
    const a = chunkify(text, 42);
    expect(a.join("")).toBe(text);
    expect(chunkify(text, 42)).toEqual(a);
    expect(a.every((c) => [...c].length >= 1 && [...c].length <= 8)).toBe(true);
  });
});

describe("playStream", () => {
  it("restores a streamed answer exactly like a one-shot unmask, holding back split placeholders", async () => {
    const c = client();
    const masked = await c.mask({ text: "Bárdos Kinga, 1137 Budapest, Pozsonyi út 38. 2/5., tel.: +36 30 555 0142" });
    const answer = `Kedves ${masked.data.masked_text}!`;
    const whole = await restore(c, masked.data.session_id, answer, () => undefined);

    const steps: StreamStep[] = [];
    await playStream({
      client: c,
      sessionId: masked.data.session_id,
      chunks: chunkify(answer, 3, 2, 5),
      delayMs: 0,
      expected: () => undefined,
      signal: new AbortController().signal,
      sleep: async () => {},
      onStep: (s) => steps.push(s),
    });

    const last = steps.at(-1)!;
    expect(last.done).toBe(true);
    const text = (s: StreamStep) => s.restoration.segments.map((x) => x.text).join("");
    expect(text(last)).toBe(whole.segments.map((x) => x.text).join(""));
    expect(text(last)).toContain("Bárdos Kinga");
    expect(steps.some((s) => s.held.startsWith("[["))).toBe(true);
    // No intermediate step ever shows a raw placeholder fragment as restored text.
    for (const s of steps) expect(text(s)).not.toMatch(/\[\[[A-Z_]*$/);
  });

  it("stops when aborted", async () => {
    const c = client();
    const masked = await c.mask({ text: "Teszt Elek" });
    const controller = new AbortController();
    const steps: StreamStep[] = [];
    await playStream({
      client: c,
      sessionId: masked.data.session_id,
      chunks: ["a", "b", "c", "d"],
      delayMs: 0,
      expected: () => undefined,
      signal: controller.signal,
      sleep: async () => {
        if (steps.length === 2) controller.abort();
      },
      onStep: (s) => steps.push(s),
    });
    expect(steps).toHaveLength(2);
    expect(steps.every((s) => !s.done)).toBe(true);
  });
});
