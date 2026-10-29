// The console's sections and their URL hashes. The open section lives in the hash, so a reload
// or a shared link lands on the same screen; the demo-era tab hashes redirect here (LAB-1287).

export type Section = "overview" | "playground" | "logs" | "vault" | "connect" | "policy" | "projects" | "evaluation";
export type PlaygroundTab = "text" | "chat" | "images";

export interface Route {
  section: Section;
  /** The Playground's sub-tab; only meaningful when `section` is "playground". */
  tab: PlaygroundTab;
  /** The Connect screen's client tab; only meaningful when `section` is "connect". */
  client?: string;
  /** The Evaluation screen's filters; only meaningful when `section` is "evaluation". */
  evaluation?: EvaluationParams;
}

/** The Benchmarks filters a URL hash carries (LAB-1133): set, language, systems, sort. */
export interface EvaluationParams {
  set?: string;
  lang?: string;
  /** The selected systems, one `systems` key each: ids can contain commas (LAB-1133). */
  systems?: string[];
  /** A sort column, `key` or `key:dir` (LAB-1133). */
  sort?: string;
}

export const SECTIONS: readonly { id: Section; label: string; hint: string }[] = [
  { id: "overview", label: "Overview", hint: "What the guard protected" },
  { id: "playground", label: "Playground", hint: "Try text, chat and images" },
  { id: "logs", label: "Logs", hint: "Every call through the gateway" },
  { id: "vault", label: "Vault", hint: "Sessions and their placeholders" },
  { id: "projects", label: "Projects", hint: "Gateway endpoints and versioned policies" },
  { id: "connect", label: "Connect", hint: "Point a client at the gateway" },
  { id: "policy", label: "Policy", hint: "Mode, detectors, entity policies" },
  { id: "evaluation", label: "Evaluation", hint: "Benchmarks" },
];

export const PLAYGROUND_TABS: readonly { id: PlaygroundTab; label: string }[] = [
  { id: "text", label: "Text" },
  { id: "chat", label: "Chat" },
  { id: "images", label: "Images" },
];

export const DEFAULT_ROUTE: Route = { section: "overview", tab: "text" };

/** Hashes from the tabbed demo UI, kept working as links in the README, docs and old posts. */
export const LEGACY_HASHES: Readonly<Record<string, Route>> = {
  "#mask": { section: "playground", tab: "text" },
  "#playground": { section: "playground", tab: "text" },
  "#chat": { section: "playground", tab: "chat" },
  "#images": { section: "playground", tab: "images" },
  "#benchmarks": { section: "evaluation", tab: "text" },
  "#traffic": { section: "logs", tab: "text" },
};

/** The Connect screen's client tabs (`api/connect.ts` TOOLS): `#connect/<client>` deep-links one. */
export const CONNECT_CLIENTS: readonly string[] = [
  "muse-code",
  "pi",
  "codex",
  "opencode",
  "curl",
  "python",
  "claude-code",
];

const SECTION_IDS = new Set<string>(SECTIONS.map((s) => s.id));
const TAB_IDS = new Set<string>(PLAYGROUND_TABS.map((t) => t.id));
const CLIENT_IDS = new Set<string>(CONNECT_CLIENTS);

export function hashOf(route: Route): string {
  if (route.section === "playground") return `#playground/${route.tab}`;
  if (route.section === "connect" && route.client && CLIENT_IDS.has(route.client)) return `#connect/${route.client}`;
  if (route.section === "evaluation") {
    const query = evaluationQuery(route.evaluation);
    return query ? `#evaluation?${query}` : "#evaluation";
  }
  return `#${route.section}`;
}

/** The Benchmarks filters as a hash query string, or "" for the defaults (LAB-1133). */
export function evaluationQuery(params: EvaluationParams | undefined): string {
  if (!params) return "";
  const query = new URLSearchParams();
  if (params.set) query.set("set", params.set);
  if (params.lang) query.set("lang", params.lang);
  for (const system of params.systems ?? []) query.append("systems", system);
  if (params.sort) query.set("sort", params.sort);
  return query.toString();
}

/** The filters a `#evaluation?...` hash names (unknown keys dropped, LAB-1133). */
export function parseEvaluationQuery(query: string): EvaluationParams {
  const params: EvaluationParams = {};
  const search = new URLSearchParams(query.startsWith("?") ? query.slice(1) : query);
  const set = search.get("set");
  const lang = search.get("lang");
  const sort = search.get("sort");
  if (set) params.set = set;
  if (lang) params.lang = lang;
  if (sort) params.sort = sort;
  const systems = search.getAll("systems").filter((s) => s);
  if (systems.length) params.systems = systems;
  return params;
}

/**
 * The route a hash names, or null when it names none (the skip link's `#main`, an anchor).
 * Old tab hashes map to their new place; `redirect` says the URL should be rewritten.
 */
export function parseHash(hash: string): { route: Route; redirect: boolean } | null {
  const legacy = LEGACY_HASHES[hash];
  if (legacy) return { route: legacy, redirect: true };
  // No hash, and the skip link's #main, are not routes: the section stays as it is.
  if (hash === "" || hash === "#" || hash === "#main") return null;
  // Client ids contain hyphens (`muse-code`); section ids don't.
  const m = /^#([a-z]+)(?:\/([a-z][a-z-]*))?(\?[^#]*)?$/.exec(hash);
  // Any other unknown hash lands on the Overview, with the URL cleaned up.
  if (!m || !SECTION_IDS.has(m[1]!)) return { route: DEFAULT_ROUTE, redirect: true };
  const section = m[1] as Section;
  const sub = m[2];
  const query = m[3];
  if (section === "playground") {
    const tab = sub && TAB_IDS.has(sub) ? (sub as PlaygroundTab) : "text";
    return { route: { section, tab }, redirect: sub !== tab || query !== undefined };
  }
  if (section === "connect") {
    const client = sub !== undefined && CLIENT_IDS.has(sub) ? sub : undefined;
    if (query !== undefined)
      return { route: { section, tab: "text", ...(client ? { client } : {}) }, redirect: true };
    return { route: { section, tab: "text", ...(client ? { client } : {}) }, redirect: sub !== client };
  }
  if (section === "evaluation") {
    if (sub !== undefined) return { route: { section, tab: "text" }, redirect: true };
    if (query === undefined) return { route: { section, tab: "text" }, redirect: false };
    return { route: { section, tab: "text", evaluation: parseEvaluationQuery(query) }, redirect: false };
  }
  return { route: { section, tab: "text" }, redirect: sub !== undefined || query !== undefined };
}

export function routeFromLocation(): Route {
  return parseHash(globalThis.location?.hash ?? "")?.route ?? DEFAULT_ROUTE;
}

export const sameRoute = (a: Route, b: Route) =>
  a.section === b.section &&
  (a.section !== "playground" || a.tab === b.tab) &&
  (a.section !== "connect" || a.client === b.client) &&
  (a.section !== "evaluation" || evaluationQuery(a.evaluation) === evaluationQuery(b.evaluation));
