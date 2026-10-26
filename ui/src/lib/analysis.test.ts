import { describe, expect, it } from "vitest";
import { createMockClient } from "../api/mock";
import { SAMPLES } from "../data/samples";
import { fillAnswerTemplate, genericAnswer, linkPlaceholders, toLocalSpans, type PlaceholderLink } from "./analysis";

/** Every original value that was masked must be absent from the simulated answer. */
function maskedValues(input: string, links: readonly PlaceholderLink[]): string[] {
  return [...new Set(links.map((l) => input.slice(l.start, l.end)))];
}

describe("fillAnswerTemplate", () => {
  it.each(SAMPLES.map((s) => [s.id, s] as const))("never echoes a masked value (%s, demo engine)", async (_id, sample) => {
    const client = createMockClient();
    const [{ spans }, masked] = await Promise.all([client.analyze({ text: sample.text }), client.mask({ text: sample.text })]);
    const local = toLocalSpans(sample.text, spans);
    const links = linkPlaceholders(sample.text, masked.masked_text, local)!;
    expect(links).not.toBeNull();
    const answer = fillAnswerTemplate(sample.answer, sample.text, links)!;
    for (const value of maskedValues(sample.text, links)) expect(answer).not.toContain(value);
    expect(answer).not.toContain("{{");
  });

  it("masks only the detected part of a value when a detector found a sub-span (postcode inside an address)", () => {
    const sample = SAMPLES[0]!;
    const postcode = sample.text.indexOf("1137");
    const tax = sample.text.indexOf("8406144122");
    // What a rules-only engine finds: the postcode, not the rest of the address.
    const links: PlaceholderLink[] = [
      { placeholder: "[[NATIONAL_ID_HU_TAX_0fb6]]", entityType: "NATIONAL_ID_HU_TAX", start: tax, end: tax + 10 },
      { placeholder: "[[ADDRESS_b7ef]]", entityType: "ADDRESS", start: postcode, end: postcode + 4 },
    ];
    const answer = fillAnswerTemplate(sample.answer, sample.text, links)!;
    expect(answer).toContain("living at [[ADDRESS_b7ef]] Budapest, Pozsonyi út 38. 2/5.");
    expect(answer).not.toContain("1137");
    expect(answer).not.toContain("8406144122");
    // Unmasked values reached the model as written, so the model may repeat them.
    expect(answer).toContain("Seller: Bárdos Kinga");
  });

  it("refuses to fill when the masked text couldn't be lined up with the input", () => {
    expect(fillAnswerTemplate(SAMPLES[0]!.answer, SAMPLES[0]!.text, null)).toBeNull();
  });
});

describe("genericAnswer", () => {
  it("lists placeholders only, in neutral wording", () => {
    const text = genericAnswer({
      masked_text: "",
      session_id: "s",
      entities: [{ placeholder: "[[PERSON_7f3a]]", entity_type: "PERSON", count: 2 }],
    });
    expect(text).toContain("[[PERSON_7f3a]] (mentioned 2×)");
    expect(text).toContain("Which of these should I look into?");
  });
});
