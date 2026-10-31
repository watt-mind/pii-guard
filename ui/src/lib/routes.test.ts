import { describe, expect, it } from "vitest";
import { DEFAULT_ROUTE, evaluationQuery, hashOf, parseEvaluationQuery, parseHash, sameRoute } from "./routes";

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

  it("parses and round-trips #cli-auth deep links (LAB-1708)", () => {
    const parsed = parseHash("#cli-auth?port=51234&state=st_123&telemetry=stats")!;
    expect(parsed.redirect).toBe(false);
    expect(parsed.route).toEqual({
      section: "connect",
      tab: "text",
      cliAuth: { port: 51234, state: "st_123", telemetry: "stats" },
    });
    expect(hashOf(parsed.route)).toBe("#cli-auth?port=51234&state=st_123&telemetry=stats");
    expect(parseHash("#cli-auth")).toEqual({
      route: { section: "connect", tab: "text", cliAuth: {} },
      redirect: false,
    });
  });
});

describe("evaluation deep links (LAB-1133)", () => {
  it("round-trips filters, including system ids that contain commas", () => {
    const route = {
      section: "evaluation" as const,
      tab: "text" as const,
      evaluation: { set: "smoke", lang: "hu", systems: ["rules", "sys,with,commas", "rules+ner:x"], sort: "f1:desc" },
    };
    const hash = hashOf(route);
    expect(hash).toBe(
      "#evaluation?set=smoke&lang=hu&systems=rules&systems=sys%2Cwith%2Ccommas&systems=rules%2Bner%3Ax&sort=f1%3Adesc",
    );
    const parsed = parseHash(hash)!;
    expect(parsed.redirect).toBe(false);
    expect(parsed.route).toEqual(route);
  });

  it("drops unknown query keys and empty values", () => {
    expect(parseEvaluationQuery("?set=smoke&bogus=1&lang=&systems=a&systems=")).toEqual({ set: "smoke", systems: ["a"] });
    expect(parseEvaluationQuery("")).toEqual({});
  });

  it("reads a bare #evaluation with no filters", () => {
    const parsed = parseHash("#evaluation")!;
    expect(parsed).toEqual({ route: { section: "evaluation", tab: "text" }, redirect: false });
    expect(hashOf(parsed.route)).toBe("#evaluation");
    expect(evaluationQuery(undefined)).toBe("");
  });

  it("treats an evaluation sub-path, or a query on another section, as a redirect", () => {
    expect(parseHash("#evaluation/smoke")).toEqual({ route: { section: "evaluation", tab: "text" }, redirect: true });
    expect(parseHash("#overview?set=smoke")!.redirect).toBe(true);
  });
});
