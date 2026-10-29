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
  return `#${route.section}`;
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
  const m = /^#([a-z]+)(?:\/([a-z][a-z-]*))?$/.exec(hash);
  // Any other unknown hash lands on the Overview, with the URL cleaned up.
  if (!m || !SECTION_IDS.has(m[1]!)) return { route: DEFAULT_ROUTE, redirect: true };
  const section = m[1] as Section;
  if (section === "connect" && m[2] !== undefined)
    return CLIENT_IDS.has(m[2])
      ? { route: { section, tab: "text", client: m[2] }, redirect: false }
      : { route: { section, tab: "text" }, redirect: true };
  if (section !== "playground") return { route: { section, tab: "text" }, redirect: m[2] !== undefined };
  const tab = m[2] && TAB_IDS.has(m[2]) ? (m[2] as PlaygroundTab) : "text";
  return { route: { section, tab }, redirect: m[2] !== tab };
}

export function routeFromLocation(): Route {
  return parseHash(globalThis.location?.hash ?? "")?.route ?? DEFAULT_ROUTE;
}

export const sameRoute = (a: Route, b: Route) =>
  a.section === b.section && (a.section !== "playground" || a.tab === b.tab) && (a.section !== "connect" || a.client === b.client);
