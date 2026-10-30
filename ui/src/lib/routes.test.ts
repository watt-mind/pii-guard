import { describe, expect, it } from "vitest";
import { DEFAULT_ROUTE, hashOf, parseHash, sameRoute } from "./routes";

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

  it("deep-links an open vault session (LAB-1333)", () => {
    expect(parseHash("#vault")).toEqual({ route: { section: "vault", tab: "text" }, redirect: false });
    expect(parseHash("#vault/s_3f9a1c0b7d2e4a61")).toEqual({
      route: { section: "vault", tab: "text", ref: "s_3f9a1c0b7d2e4a61" },
      redirect: false,
    });
    expect(hashOf({ section: "vault", tab: "text", ref: "s_3f9a1c0b7d2e4a61" })).toBe("#vault/s_3f9a1c0b7d2e4a61");
    expect(hashOf({ section: "vault", tab: "text" })).toBe("#vault");
    // Anything else after the section is not a route: back to the section.
    expect(parseHash("#vault/not-a-ref!")).toEqual({ route: { section: "vault", tab: "text" }, redirect: true });
    expect(parseHash("#logs/s_3f9a1c0b7d2e4a61")).toEqual({ route: { section: "logs", tab: "text" }, redirect: true });
    expect(sameRoute({ section: "vault", tab: "text", ref: "s_aaa" }, { section: "vault", tab: "text", ref: "s_aaa" })).toBe(true);
    expect(sameRoute({ section: "vault", tab: "text", ref: "s_aaa" }, { section: "vault", tab: "text", ref: "s_bbb" })).toBe(false);
    expect(sameRoute({ section: "vault", tab: "text" }, { section: "vault", tab: "text", ref: "s_aaa" })).toBe(false);
  });
});
