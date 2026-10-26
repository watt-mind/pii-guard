import { describe, expect, it } from "vitest";
import { SAMPLES } from "../data/samples";
import { placeholderRegex } from "../lib/placeholders";
import { ApiError } from "./http";
import { createMockClient, MOCK_SESSION_PREFIX, validHuTaj, validHuTaxId, validIban } from "./mock";

const client = () => createMockClient({ latencyMs: 0 });

describe("checksums", () => {
  it("accepts the fictional sample identifiers and rejects one-digit typos", () => {
    expect(validHuTaxId("8406144122")).toBe(true);
    expect(validHuTaxId("8406144123")).toBe(false);
    expect(validHuTaj("039812654")).toBe(true);
    expect(validHuTaj("039812655")).toBe(false);
    expect(validIban("HU78 1177 3016 2048 5733 0000 0006")).toBe(true);
    expect(validIban("HU78 1177 3016 2048 5733 0000 0007")).toBe(false);
  });
});

describe("mock analyze", () => {
  it("returns sorted, non-overlapping spans in the public shape, without values", async () => {
    const text = SAMPLES[0]!.text;
    const { spans } = await client().analyze({ text });
    expect(spans.length).toBeGreaterThan(10);
    for (const s of spans) {
      expect(Object.keys(s).sort()).toEqual(["detector", "end", "entity_type", "score", "start"]);
      expect(s.score).toBeGreaterThan(0);
      expect(s.score).toBeLessThanOrEqual(1);
    }
    for (let i = 1; i < spans.length; i++) expect(spans[i]!.start).toBeGreaterThanOrEqual(spans[i - 1]!.end);
    const types = new Set(spans.map((s) => s.entity_type));
    for (const t of ["PERSON", "ADDRESS", "DATE_OF_BIRTH", "NATIONAL_ID_HU_TAX", "NATIONAL_ID_HU_TAJ", "BANK_ACCOUNT", "PHONE", "EMAIL", "ORGANIZATION"]) {
      expect(types).toContain(t);
    }
  });

  it("finds a name with a Hungarian case suffix without swallowing the suffix", async () => {
    const text = "A beteget Kerekes Ottótól kaptuk.";
    const { spans } = await client().analyze({ text });
    expect(spans).toHaveLength(1);
    expect(text.slice(spans[0]!.start, spans[0]!.end)).toBe("Kerekes Ottó");
  });

  it("reports code-point offsets, not UTF-16 offsets", async () => {
    const text = "🙂 Teszt Elek";
    const { spans } = await client().analyze({ text });
    expect(spans[0]).toMatchObject({ start: 2, end: 12, entity_type: "PERSON" });
    expect([...text].slice(2, 12).join("")).toBe("Teszt Elek");
  });
});

describe("mock mask / unmask", () => {
  it("gives the same value the same placeholder and counts occurrences", async () => {
    const res = await client().mask({ text: "Teszt Elek írt Teszt Eleknek." });
    expect(res.masked_text).toMatch(/^\[\[PERSON_[0-9a-f]{4,}\]\] írt \[\[PERSON_[0-9a-f]{4,}\]\]nek\.$/);
    const placeholders = res.masked_text.match(placeholderRegex());
    expect(new Set(placeholders).size).toBe(1);
    expect(res.entities).toEqual([{ placeholder: placeholders![0], entity_type: "PERSON", count: 2 }]);
    expect(res.session_id.startsWith(MOCK_SESSION_PREFIX)).toBe(true);
  });

  it("never puts original values in the masked text or the entity list", async () => {
    const text = SAMPLES[1]!.text;
    const res = await client().mask({ text });
    for (const value of ["Takács Gábor", "8454671188", "+36 20 555 0187", "takacs.gabor@example.org", "AAB-123"]) {
      expect(res.masked_text).not.toContain(value);
      expect(JSON.stringify(res.entities)).not.toContain(value);
    }
  });

  it("leaves keep-policy types (organizations, company IDs) in place", async () => {
    const text = SAMPLES[2]!.text;
    const res = await client().mask({ text });
    expect(res.masked_text).toContain("Győri Egészségközpont Kft.");
    expect(res.masked_text).toContain("08-09-123456");
    expect(res.entities.map((e) => e.entity_type)).not.toContain("ORGANIZATION");
  });

  it("round-trips through unmask and reports invented placeholders", async () => {
    const c = client();
    const text = SAMPLES[0]!.text;
    const masked = await c.mask({ text });
    const back = await c.unmask({ text: masked.masked_text, session_id: masked.session_id });
    expect(back).toEqual({ text, unresolved: [] });

    const invented = await c.unmask({ text: "Kedves [[PERSON_0bad]]!", session_id: masked.session_id });
    expect(invented).toEqual({ text: "Kedves [[PERSON_0bad]]!", unresolved: ["[[PERSON_0bad]]"] });
  });

  it("reuses a session's mapping when its id is passed back", async () => {
    const c = client();
    const first = await c.mask({ text: "Varga Levente" });
    const second = await c.mask({ text: "Szia, Varga Levente!", session_id: first.session_id });
    expect(second.session_id).toBe(first.session_id);
    expect(second.masked_text).toBe(`Szia, ${first.masked_text}!`);
  });

  it("isolates sessions: different sessions issue different placeholders", async () => {
    const c = client();
    const a = await c.mask({ text: "Varga Levente" });
    const b = await c.mask({ text: "Varga Levente" });
    expect(a.masked_text).not.toBe(b.masked_text);
  });

  it("answers an unknown session with 404 not_found", async () => {
    await expect(client().unmask({ text: "x", session_id: "s_demo_nope" })).rejects.toMatchObject({
      status: 404,
      code: "not_found",
    });
    await expect(client().unmask({ text: "x", session_id: "s_demo_nope" })).rejects.toBeInstanceOf(ApiError);
  });
});
