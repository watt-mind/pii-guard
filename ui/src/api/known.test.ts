import { describe, expect, it } from "vitest";
import { ApiError } from "./http";
import { createMockClient } from "./mock";

describe("demo engine known values", () => {
  it("masks a pre-loaded value in an inflected form and reports it as known", async () => {
    const mock = createMockClient();
    const created = await mock.createSession!([{ value: "Gyakorló Tihamér", entity_type: "PERSON" }]);
    expect(created).toMatchObject({ added: 1, total: 1 });
    expect(created.session_id.startsWith("s_demo_")).toBe(true);
    const text = "Üdv, Gyakorló Tihamérnak!";
    const analyzed = await mock.analyze({ text, session_id: created.session_id });
    expect(analyzed.spans).toEqual([expect.objectContaining({ start: 5, end: 21, detector: "known", entity_type: "PERSON" })]);
    const masked = await mock.mask({ text, session_id: created.session_id });
    expect(masked.masked_text).toMatch(/^Üdv, \[\[PERSON_[0-9a-f]{4,}\]\]nak!$/);
  });

  it("ignores duplicates and refuses values that are too short", async () => {
    const mock = createMockClient();
    const { session_id } = await mock.createSession!([{ value: "Gyakorló Tihamér", entity_type: "PERSON" }]);
    expect(await mock.addKnownValues!(session_id, [{ value: "gyakorló  tihamér", entity_type: "PERSON" }])).toMatchObject({ added: 0, total: 1 });
    await expect(mock.addKnownValues!(session_id, [{ value: "ab", entity_type: "PERSON" }])).rejects.toMatchObject({
      code: "invalid_known_value",
    });
    await expect(mock.addKnownValues!("s_demo_nope", [{ value: "Gyakorló", entity_type: "PERSON" }])).rejects.toBeInstanceOf(ApiError);
  });
});
