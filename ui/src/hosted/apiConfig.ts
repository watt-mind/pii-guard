// The public API reference at #api (LAB-1586): routing and the renderer's configuration.
import type { ComponentProps } from "react";
import type { ApiReferenceReact } from "@scalar/api-reference-react";

type Configuration = ComponentProps<typeof ApiReferenceReact>["configuration"];

const HIDDEN_CLIENTS = ["c", "clojure", "csharp", "dart", "fsharp", "go", "http", "java", "kotlin", "objc", "ocaml", "php", "powershell", "r", "ruby", "rust", "swift"];

/** `#api`, and the reference's own deep links (`#api/tag/gateway/...`: the document slug is `api`). */
export function isApiHash(hash: string): boolean {
  return hash === "#api" || hash.startsWith("#api/");
}

/**
 * Read-only: no "Test request" button, no API client, no proxy, no telemetry, no MCP or editor
 * tooling and no web fonts (the hosted CSP allows only this origin). The spec is the committed
 * docs/openapi.json, bundled with the page; the runtime /openapi.json stays off in production.
 */
export function referenceConfig(specUrl: string, dark: boolean, servers?: ApiServer[], content?: object): Configuration {
  return {
    // Signed in, the document itself is rewritten for this service (`hostedSpec`); else the bundled file.
    ...(content ? { content } : { url: specUrl }),
    // Signed in, the examples start from this service, not the self-hosted default (LAB-1626).
    ...(servers ? { servers } : {}),
    // The reference's anchors start with the document slug, so its deep links stay on this page.
    slug: "api",
    theme: "none",
    layout: "modern",
    forceDarkModeState: dark ? "dark" : "light",
    hideDarkModeToggle: true,
    hideTestRequestButton: true,
    hideClientButton: true,
    showDeveloperTools: "never",
    isEditable: false,
    telemetry: false,
    withDefaultFonts: false,
    mcp: { disabled: true },
    agent: { disabled: true },
    // The page toolbar owns the bundled-spec download.
    documentDownloadType: "none",
    defaultOpenFirstTag: true,
    operationTitleSource: "summary",
    persistAuth: false,
    // Examples in the languages docs/api.md uses: shell (curl), Python, JavaScript and Node.
    hiddenClients: Object.fromEntries(HIDDEN_CLIENTS.map((target) => [target, true])),
  } as Configuration;
}

export interface ApiServer { url: string; description: string }

/**
 * The Server choices in the console: this service first, then the endpoint the header picked
 * (its gateway routes sit under `/e/<id>`), then a self-hosted install.
 */
export function hostedServers(origin: string, endpointId: string | null): ApiServer[] {
  return [
    { url: origin, description: "This PII Guard service" },
    ...(endpointId ? [{ url: `${origin}/e/${encodeURIComponent(endpointId)}`, description: "Your endpoint (gateway routes, endpoint key)" }] : []),
    { url: "http://127.0.0.1:8787", description: "Self-hosted (`pii-guard serve`)" },
  ];
}

type Spec = { servers?: ApiServer[]; paths?: Record<string, Record<string, unknown>> };
type ServerEntry = { url: string; description?: string; variables?: unknown };
const PUBLIC_ORIGIN = "https://guard.watt-mind.com";

/**
 * The bundled spec as a signed-in owner should read it (LAB-1626): this service's servers first,
 * and the gateway operations' own server lists led by the hosted endpoint, on this origin, with
 * the picked endpoint's id filled in. The self-hosted root gateway stays, last.
 */
export function hostedSpec(spec: Spec, origin: string, endpointId: string | null): Spec {
  const local = (server: ServerEntry) => /^http:\/\/(127\.0\.0\.1|localhost)[:/]/.test(server.url);
  const rewrite = (server: ServerEntry): ServerEntry => {
    let url = server.url.startsWith(PUBLIC_ORIGIN) ? origin + server.url.slice(PUBLIC_ORIGIN.length) : server.url;
    if (endpointId && url.includes("{endpoint_id}")) {
      url = url.replace("{endpoint_id}", encodeURIComponent(endpointId));
      return { url, description: "Your endpoint (endpoint key)" };
    }
    return { ...server, url };
  };
  const paths = Object.fromEntries(
    Object.entries(spec.paths ?? {}).map(([path, item]) => [
      path,
      Object.fromEntries(
        Object.entries(item).map(([method, op]) => {
          const servers = (op as { servers?: ServerEntry[] } | null)?.servers;
          if (!Array.isArray(servers)) return [method, op];
          return [method, { ...(op as object), servers: [...servers.filter((x) => !local(x)), ...servers.filter(local)].map(rewrite) }];
        }),
      ),
    ]),
  );
  return { ...spec, servers: hostedServers(origin, endpointId), paths };
}
