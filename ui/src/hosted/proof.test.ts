import { describe, expect, it } from "vitest";
import { AGENT_TRAFFIC, COMPARISON, nextBest, OPEN_MODELS, PROOF, trafficNextBest } from "./proof";

describe("landing proof (LAB-1478)", () => {
  it("names the best of the other tools, not a weaker one", () => {
    expect(nextBest("leak", 0)).toBe("PrivAiTe 13.0\u00a0%");
    expect(nextBest("f1", 0)).toBe("Presidio 62.9\u00a0%");
    expect(nextBest("leak", 1)).toBe("PrivAiTe 4.4\u00a0%");
    expect(trafficNextBest("over")).toBe("LLM Guard 16.9\u00a0%");
    expect(trafficNextBest("leak")).toBe("PrivAiTe 2.4\u00a0%");
    const ours = AGENT_TRAFFIC.find((r) => r.ours)!;
    expect(PROOF.map((p) => p.value)).toEqual([`${ours.over}\u00a0%`, `${ours.leak}\u00a0%`, `${COMPARISON[0]!.leak[0]}\u00a0%`]);
  });
  it("lists the open models by leak, ours first, with the closest one included", () => {
    const leaks = OPEN_MODELS.map((m) => Number(m.leak));
    expect(leaks).toEqual([...leaks].sort((a, b) => a - b));
    expect(OPEN_MODELS[0]).toMatchObject({ ours: true });
    expect(OPEN_MODELS.map((m) => m.id)).toContain("bardsai/eu-pii-anonimization-multilang");
  });
});
