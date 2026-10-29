import { getOwnerToken } from "./localOwner";
import { getSelectedEndpoint, getSelectedProject } from "../projects/selection";

export function projectHeaders(headers: HeadersInit | undefined, projectId: string | null = getSelectedProject()): HeadersInit | undefined {
  if (!projectId) return headers;
  const scoped = new Headers(headers);
  scoped.set("X-PII-Guard-Project", projectId);
  return scoped;
}

export function inspectionHeaders(headers: HeadersInit | undefined, projectId: string | null = getSelectedProject(), endpointId: string | null = getSelectedEndpoint()): HeadersInit | undefined {
  const scoped = projectHeaders(headers, projectId);
  if (!endpointId) return scoped;
  const inspected = new Headers(scoped);
  inspected.set("X-PII-Guard-Endpoint", endpointId);
  return inspected;
}

/** Capture one project for the lifetime of a client or operation. */
export function createProjectFetch(doFetch: typeof fetch, projectId: string | null = getSelectedProject(), endpointId: string | null = getSelectedEndpoint()): typeof fetch {
  return (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const parsed = new URL(url, globalThis.location.origin);
    const pathname = parsed.pathname;
    const original = init?.headers ?? (input instanceof Request ? input.headers : undefined);
    let headers = original;
    // Never send a local owner credential to providers, endpoint-key routes, or another origin.
    if (import.meta.env.VITE_PII_GUARD_HOSTED !== "true" && parsed.origin === globalThis.location.origin &&
      /^\/v1\/(?:projects|status|analyze|mask|unmask|sessions|images|vault|traffic|connect|models|chat|responses|messages)(?:\/|$)/.test(pathname)) {
      const token = getOwnerToken();
      if (token) {
        const authorized = new Headers(headers);
        if (!authorized.has("Authorization") && !authorized.has("X-PII-Guard-Token")) authorized.set("Authorization", `Bearer ${token}`);
        headers = authorized;
      }
    }
    // Public account/demo and operator configuration routes have no project namespace.
    if (/^\/v1\/(?:analyze|mask|unmask|sessions|images|vault|traffic|connect|models|chat|responses|messages)(?:\/|$)/.test(pathname)) {
      headers = /^\/v1\/(?:vault|traffic)(?:\/|$)/.test(pathname) ? inspectionHeaders(headers, projectId, endpointId) : projectHeaders(headers, projectId);
    }
    return headers === original ? doFetch(input, init) : doFetch(input, { ...init, headers });
  };
}
