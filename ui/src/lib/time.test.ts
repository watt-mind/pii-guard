import { describe, expect, it } from "vitest";
import { clockMinutes, clockTime, dateTime, relativeTime } from "./time";

describe("console time formats (LAB-1619)", () => {
  const at = new Date(2026, 9, 30, 14, 5, 9).toISOString();

  it("uses a 24-hour clock, never AM/PM", () => {
    expect(clockTime(at)).toBe("14:05:09");
    expect(clockMinutes(at)).toBe("14:05");
    expect(clockTime(at)).not.toMatch(/AM|PM/i);
  });

  it("writes dates the EU way", () => {
    expect(dateTime(at)).toBe("30 Oct 2026, 14:05");
    expect(dateTime(undefined)).toBe("not available");
    expect(dateTime("nope")).toBe("not available");
  });

  it("passes an unparseable clock value through", () => {
    expect(clockTime("later")).toBe("later");
  });

  it("drops a zero minute part and moves to days", () => {
    const now = Date.parse(at);
    expect(relativeTime(new Date(now - 3600_000).toISOString(), now)).toBe("1 h ago");
    expect(relativeTime(new Date(now - 3900_000).toISOString(), now)).toBe("1 h 5 min ago");
    expect(relativeTime(new Date(now - 2 * 86_400_000).toISOString(), now)).toBe("2 days ago");
    expect(relativeTime(new Date(now - 2000).toISOString(), now)).toBe("just now");
    expect(relativeTime(null, now)).toBe("not recorded");
  });
});
