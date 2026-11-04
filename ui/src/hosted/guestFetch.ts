// What the hosted guest Playground may send (LAB-1812). The server refuses everything else to a
// visitor without a Google sign-in; this keeps the page from asking at all.

/** The routes a guest may call, POST and same-origin only; the server refuses the rest without a Google sign-in. */
const GUEST_ROUTES = /^\/v1\/(?:analyze|mask|unmask|sessions|chat\/completions)$/;
/** Owner scoping a guest never sends, even when this tab picked a project or connection while signed in. */
const OWNER_HEADERS = ["X-PII-Guard-Project", "X-PII-Guard-Endpoint", "X-PII-Guard-Connection"] as const;

/** Why the guard stopped a guest: the daily allowance for this network, the abuse throttle, or a sign-in it now asks for. */
export type GuestLimit = "quota_exceeded" | "abuse_throttled" | "sign_in_required";

async function limitOf(response: Response): Promise<GuestLimit> {
  let code = "";
  try {
    const payload: unknown = await response.clone().json();
    const error = typeof payload === "object" && payload !== null && "error" in payload ? (payload as { error?: { code?: unknown } }).error : undefined;
    if (typeof error?.code === "string") code = error.code;
  } catch {
    // A proxy's page: the status alone decides.
  }
  if (code === "quota_exceeded" || code === "abuse_throttled" || code === "sign_in_required") return code;
  return response.status === 401 ? "sign_in_required" : "abuse_throttled";
}

/** What a route outside the guest list gets, without a request: the server's own answer to a guest. */
const refused = () =>
  new Response(JSON.stringify({ error: { code: "sign_in_required", message: "Sign in with Google to use this endpoint" } }), { status: 401, headers: { "Content-Type": "application/json" } });

/**
 * Same-origin fetch for the guest routes only, without owner headers. Every answer is reported:
 * `limit` is set when the guard refused for the allowance, the throttle or a sign-in.
 */
export function createGuestFetch(onAnswer: (limit: GuestLimit | null) => void, doFetch: typeof fetch = (...args) => fetch(...args)): typeof fetch {
  return async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, globalThis.location.origin);
    const method = (init?.method ?? "GET").toUpperCase();
    if (url.origin !== globalThis.location.origin || method !== "POST" || !GUEST_ROUTES.test(url.pathname)) return refused();
    const headers = new Headers(init?.headers);
    for (const name of OWNER_HEADERS) headers.delete(name);
    const response = await doFetch(`${url.pathname}${url.search}`, { ...init, headers, credentials: "same-origin" });
    onAnswer(response.status === 429 || response.status === 401 ? await limitOf(response) : null);
    return response;
  };
}
