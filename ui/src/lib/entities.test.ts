import { describe, expect, it } from "vitest";
import { ENTITY_META, UNKNOWN_META, metaFor } from "./entities";

/** BANK_ACCOUNT covers IBANs and payment cards: the UI must never read as IBAN-only (LAB-1187). */
describe("BANK_ACCOUNT entity meta", () => {
  it("labels bank accounts and cards, not IBANs alone", () => {
    expect(ENTITY_META.BANK_ACCOUNT.label).toContain("card");
    expect(ENTITY_META.BANK_ACCOUNT.label.toLowerCase()).not.toContain("iban");
    expect(ENTITY_META.BANK_ACCOUNT.short.toUpperCase()).not.toBe("IBN");
  });

  it("returns fallback metadata for unknown entity types without throwing", () => {
    const meta = metaFor("FUTURE_UNKNOWN_ENTITY");
    expect(meta).toEqual(UNKNOWN_META);
    expect(meta.label).toBe("Unknown type");
    expect(meta.short).toBe("???");
    expect(meta.policy).toBe("mask");
    expect(metaFor(null)).toEqual(UNKNOWN_META);
    expect(metaFor(undefined)).toEqual(UNKNOWN_META);
  });
});
