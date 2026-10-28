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
    // Operator status and public account/demo routes are deliberately outside project scope.
    const pathname = new URL(url, "http://pii-guard.invalid").pathname;
    if (!/^\/v1\/(?:analyze|mask|unmask|sessions|images|vault|traffic|connect|models|chat|responses|messages)(?:\/|$)/.test(pathname)) return doFetch(input, init);
    const headers = init?.headers ?? (input instanceof Request ? input.headers : undefined);
    return doFetch(input, { ...init, headers: /^\/v1\/(?:vault|traffic)(?:\/|$)/.test(pathname) ? inspectionHeaders(headers, projectId, endpointId) : projectHeaders(headers, projectId) });
  };
}
