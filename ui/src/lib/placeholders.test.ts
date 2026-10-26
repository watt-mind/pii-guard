import { describe, expect, it } from "vitest";
import { alignRestored, splitSafe, StreamBuffer, tokenize } from "./placeholders";

describe("tokenize", () => {
  it("splits literal text and placeholders, keeping inflection suffixes as text", () => {
    const tokens = tokenize("[[PERSON_7f3a]] írt [[PERSON_7f3a]]nek.");
    expect(tokens).toEqual([
      { kind: "placeholder", text: "[[PERSON_7f3a]]", entityType: "PERSON", id: "7f3a" },
      { kind: "text", text: " írt " },
      { kind: "placeholder", text: "[[PERSON_7f3a]]", entityType: "PERSON", id: "7f3a" },
      { kind: "text", text: "nek." },
    ]);
  });

  it("recognises multi-word entity types and flags unknown ones", () => {
    const [a, , b] = tokenize("[[NATIONAL_ID_HU_TAX_00ff]] / [[ALIEN_beef]]");
    expect(a).toMatchObject({ kind: "placeholder", entityType: "NATIONAL_ID_HU_TAX", id: "00ff" });
    expect(b).toMatchObject({ kind: "placeholder", entityType: null });
  });

  it("ignores tokens that don't match the contract format", () => {
    expect(tokenize("[[person_7f3a]] [[PERSON_7f]] [PERSON_7f3a]").every((t) => t.kind === "text")).toBe(true);
  });
});

describe("splitSafe", () => {
  it.each([
    ["Kedves [[PERS", "Kedves ", "[[PERS"],
    ["Kedves [", "Kedves ", "["],
    ["Kedves [[PERSON_7f", "Kedves ", "[[PERSON_7f"],
    ["Kedves [[PERSON_7f3a]", "Kedves ", "[[PERSON_7f3a]"],
    ["Kedves [[PERSON_7f3a]]", "Kedves [[PERSON_7f3a]]", ""],
    ["array[0] ok", "array[0] ok", ""],
    ["plain text", "plain text", ""],
  ])("%j -> safe %j, held %j", (input, safe, held) => {
    expect(splitSafe(input)).toEqual({ safe, held });
  });
});

describe("StreamBuffer", () => {
  it("emits the same text as the whole input, never splitting a placeholder", () => {
    const text = "Kedves [[PERSON_7f3a]]! A [[ADDRESS_9c01]] címre küldjük.";
    for (let size = 1; size <= 9; size++) {
      const buf = new StreamBuffer();
      const emitted: string[] = [];
      for (let i = 0; i < text.length; i += size) emitted.push(buf.feed(text.slice(i, i + size)));
      emitted.push(buf.flush());
      expect(emitted.join("")).toBe(text);
      for (const piece of emitted) {
        // every emitted piece contains only whole placeholders
        expect(piece.split("[[").length - 1).toBe(piece.split("]]").length - 1);
      }
    }
  });
});

describe("alignRestored", () => {
  it("marks each restored value with its placeholder", () => {
    const segs = alignRestored("Kedves [[PERSON_7f3a]]!", "Kedves Teszt Elek!");
    expect(segs).toEqual([
      { kind: "text", text: "Kedves " },
      { kind: "restored", text: "Teszt Elek", placeholder: "[[PERSON_7f3a]]", entityType: "PERSON" },
      { kind: "text", text: "!" },
    ]);
  });

  it("keeps unresolved placeholders as such", () => {
    const segs = alignRestored("Hi [[PERSON_dead]].", "Hi [[PERSON_dead]].", ["[[PERSON_dead]]"]);
    expect(segs?.[1]).toEqual({ kind: "unresolved", text: "[[PERSON_dead]]", entityType: "PERSON" });
  });

  it("uses the expected value to settle ambiguous splits", () => {
    const masked = "[[PERSON_aaaa]] [[EMAIL_bbbb]]";
    const unmasked = "Bárdos Kinga kinga@example.com";
    // Without a hint the first space inside the name is taken as the separator.
    expect(alignRestored(masked, unmasked)?.[0]).toMatchObject({ kind: "restored", text: "Bárdos" });
    const hinted = alignRestored(masked, unmasked, [], (ph) =>
      ph === "[[PERSON_aaaa]]" ? "Bárdos Kinga" : ph === "[[EMAIL_bbbb]]" ? "kinga@example.com" : undefined,
    );
    expect(hinted?.filter((s) => s.kind === "restored").map((s) => s.text)).toEqual(["Bárdos Kinga", "kinga@example.com"]);
  });

  it("returns null when the texts don't line up", () => {
    expect(alignRestored("Hello [[PERSON_7f3a]]!", "Goodbye Teszt Elek!")).toBeNull();
  });
});
