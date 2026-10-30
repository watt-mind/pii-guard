import { describe, expect, it } from "vitest";
import { ENTITY_META } from "./entities";

/** BANK_ACCOUNT covers IBANs and payment cards: the UI must never read as IBAN-only (LAB-1187). */
describe("BANK_ACCOUNT entity meta", () => {
  it("labels bank accounts and cards, not IBANs alone", () => {
    expect(ENTITY_META.BANK_ACCOUNT.label).toContain("card");
    expect(ENTITY_META.BANK_ACCOUNT.label.toLowerCase()).not.toContain("iban");
    expect(ENTITY_META.BANK_ACCOUNT.short.toUpperCase()).not.toBe("IBN");
  });
});
