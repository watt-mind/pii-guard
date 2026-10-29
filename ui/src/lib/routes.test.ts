import { describe, expect, it } from "vitest";
import { DEFAULT_ROUTE, hashOf, parseHash } from "./routes";

describe("console routes (LAB-1287)", () => {
  it.each([
    ["#mask", "#playground/text"],
    ["#playground", "#playground/text"],
    ["#chat", "#playground/chat"],
    ["#images", "#playground/images"],
    ["#benchmarks", "#evaluation"],
    ["#traffic", "#logs"],
  ])("redirects the old tab hash %s to %s", (old, now) => {
    const parsed = parseHash(old)!;
    expect(parsed.redirect).toBe(true);
    expect(hashOf(parsed.route)).toBe(now);
  });

  it.each(["#overview", "#logs", "#connect", "#policy", "#evaluation", "#playground/text", "#playground/chat", "#playground/images"])("reads %s as itself", (hash) => {
    const parsed = parseHash(hash)!;
    expect(parsed.redirect).toBe(false);
    expect(hashOf(parsed.route)).toBe(hash);
  });

  it.each(["#connect/pi", "#connect/muse-code", "#connect/codex", "#connect/opencode", "#connect/curl", "#connect/python", "#connect/claude-code"])(
    "reads %s as itself (LAB-1314)",
    (hash) => {
      const parsed = parseHash(hash)!;
      expect(parsed.redirect).toBe(false);
      expect(hashOf(parsed.route)).toBe(hash);
    },
  );

  it("rewrites an unknown Connect client to #connect (LAB-1314)", () => {
    expect(parseHash("#connect/bogus")).toEqual({ route: { section: "connect", tab: "text" }, redirect: true });
    expect(hashOf({ section: "connect", tab: "text", client: "bogus" })).toBe("#connect");
  });

  it("falls back to the Text tab for an unknown Playground tab, and rewrites the URL", () => {
    expect(parseHash("#playground/nope")).toEqual({ route: { section: "playground", tab: "text" }, redirect: true });
  });

  it("ignores hashes that are not routes (the skip link's #main)", () => {
    expect(parseHash("#main")).toBeNull();
    expect(parseHash("")).toBeNull();
    expect(parseHash("#")).toBeNull();
  });

  it("sends any other unknown hash to the Overview, with the URL cleaned up", () => {
    expect(parseHash("#bogus")).toEqual({ route: DEFAULT_ROUTE, redirect: true });
    expect(parseHash("#Logs/x")).toEqual({ route: DEFAULT_ROUTE, redirect: true });
  });

  it("opens on the Overview", () => {
    expect(hashOf(DEFAULT_ROUTE)).toBe("#overview");
  });
});
