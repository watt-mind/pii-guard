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
export function referenceConfig(specUrl: string, dark: boolean): Configuration {
  return {
    url: specUrl,
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
    documentDownloadType: "json",
    defaultOpenFirstTag: true,
    operationTitleSource: "summary",
    persistAuth: false,
    // Examples in the languages docs/api.md uses: shell (curl), Python, JavaScript and Node.
    hiddenClients: Object.fromEntries(HIDDEN_CLIENTS.map((target) => [target, true])),
  } as Configuration;
}
