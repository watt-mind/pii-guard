import { describe, expect, it } from "vitest";
import { COMPARISON, nextBest, OPEN_MODELS, PROOF } from "./proof";

describe("landing proof (LAB-1478)", () => {
  it("names the best of the other tools, not a weaker one", () => {
    expect(nextBest("leak", 0)).toBe("PrivAiTe 12.7 %");
    expect(nextBest("f1", 0)).toBe("Presidio 64.9 %");
    expect(nextBest("leak", 1)).toBe("PrivAiTe 4.4 %");
    expect(PROOF.map((p) => p.value)).toEqual([`${COMPARISON[0]!.leak[0]} %`, `${COMPARISON[0]!.f1[0]} %`, `${COMPARISON[0]!.leak[1]} %`]);
  });
  it("lists the open models by leak, ours first, with the closest one included", () => {
    const leaks = OPEN_MODELS.map((m) => Number(m.leak));
    expect(leaks).toEqual([...leaks].sort((a, b) => a - b));
    expect(OPEN_MODELS[0]).toMatchObject({ ours: true });
    expect(OPEN_MODELS.map((m) => m.id)).toContain("bardsai/eu-pii-anonimization-multilang");
  });
});
