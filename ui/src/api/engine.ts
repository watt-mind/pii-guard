// Chooses between the live API and the built-in demo engine.
//
// - "mock" always uses the demo engine.
// - "api" always uses the live API; errors are shown, never papered over.
// - "auto" uses the API when /healthz answers and the /v1 routes exist, and
//   falls back to the demo engine when the API is unreachable or the routes
//   are missing (404). A contract error from a live endpoint (for example
//   503 detection_failed) is NOT a reason to fall back: the guard failed
//   closed and the UI shows that.

import { ApiError, UnreachableError } from "./http";
import { MOCK_SESSION_PREFIX } from "./mock";
import type {
  GuardClient,
  HealthResponse,
  ImageMaskRequest,
  ImageMaskResponse,
  KnownValue,
  KnownValuesResponse,
} from "./types";

export type ModePreference = "auto" | "api" | "mock";
export type EngineKind = "api" | "mock";
/** What the header shows: "pending" while the first health check is still out. */
export type EngineDisplay = EngineKind | "pending";

export type ApiStatus =
  | { state: "checking" }
  | { state: "online"; version: string }
  | { state: "offline" };

export interface EngineState {
  preference: ModePreference;
  status: ApiStatus;
  /** /healthz answers but /v1/* returned 404. */
  endpointsMissing: boolean;
}

export function effectiveEngine(s: EngineState): EngineDisplay {
  if (s.preference === "mock") return "mock";
  if (s.preference === "api") return "api";
  if (s.status.state === "checking") return "pending";
  return s.status.state === "online" && !s.endpointsMissing ? "api" : "mock";
}

export function engineReason(s: EngineState): string {
  if (s.preference === "mock") return "Demo engine selected";
  if (s.preference === "api") {
    if (s.status.state === "offline") return "Live API selected, but it is not reachable";
    return "Live API selected";
  }
  if (s.status.state === "checking") return "Looking for the pii-guard API";
  if (s.status.state === "offline") return "pii-guard API is not reachable, using the demo engine";
  if (s.endpointsMissing) return "API is up, but /v1 endpoints are not available yet";
  return "Connected to the pii-guard API";
}

export function parseModePreference(value: string | null | undefined): ModePreference {
  return value === "api" || value === "mock" ? value : "auto";
}

export interface Routed<T> {
  data: T;
  engine: EngineKind;
}

export interface RoutingClient {
  analyze(...args: Parameters<GuardClient["analyze"]>): Promise<Routed<Awaited<ReturnType<GuardClient["analyze"]>>>>;
  mask(...args: Parameters<GuardClient["mask"]>): Promise<Routed<Awaited<ReturnType<GuardClient["mask"]>>>>;
  unmask(...args: Parameters<GuardClient["unmask"]>): Promise<Routed<Awaited<ReturnType<GuardClient["unmask"]>>>>;
  maskImage(req: ImageMaskRequest): Promise<Routed<ImageMaskResponse>>;
  createSession(known_values: KnownValue[]): Promise<Routed<KnownValuesResponse>>;
  addKnownValues(session_id: string, known_values: KnownValue[]): Promise<Routed<KnownValuesResponse>>;
}

export interface RoutingDeps {
  api: GuardClient;
  mock: GuardClient;
  getState: () => EngineState;
  onEndpointsMissing: () => void;
  onUnreachable: () => void;
  /** A live call succeeded: clears any earlier "endpoints missing" / "offline" verdict. */
  onApiSuccess?: () => void;
}

export function createRoutingClient(deps: RoutingDeps): RoutingClient {
  async function route<K extends "analyze" | "mask" | "maskImage" | "createSession">(
    method: K,
    req: Parameters<Required<GuardClient>[K]>[0],
  ): Promise<Routed<Awaited<ReturnType<Required<GuardClient>[K]>>>> {
    type Result = Awaited<ReturnType<Required<GuardClient>[K]>>;
    const state = deps.getState();
    const call = (client: GuardClient) => {
      const fn = (client[method] as ((r: typeof req) => Promise<Result>) | undefined)?.bind(client);
      // An engine without this method (a text-only test double) counts as not reachable.
      if (!fn) return Promise.reject(new UnreachableError(`${method} is not available`));
      return fn(req);
    };
    if (state.preference === "mock") return { data: await call(deps.mock), engine: "mock" };
    // A session lives in the engine that created it.
    const sessionId = typeof req === "object" && req !== null && "session_id" in req ? req.session_id : null;
    if (typeof sessionId === "string" && sessionId.startsWith(MOCK_SESSION_PREFIX)) {
      return { data: await call(deps.mock), engine: "mock" };
    }
    // In auto mode every call tries the API first, so a transient 404 or a missed health
    // check can't pin the session to the demo engine.
    try {
      const data = await call(deps.api);
      deps.onApiSuccess?.();
      return { data, engine: "api" };
    } catch (err) {
      if (state.preference !== "auto") throw err;
      if (err instanceof UnreachableError) {
        deps.onUnreachable();
        return { data: await call(deps.mock), engine: "mock" };
      }
      if (err instanceof ApiError && (err.status === 404 || err.status === 405) && err.code === "not_found") {
        deps.onEndpointsMissing();
        return { data: await call(deps.mock), engine: "mock" };
      }
      throw err;
    }
  }

  return {
    analyze: (req) => route("analyze", req),
    mask: (req) => route("mask", req),
    maskImage: (req) => route("maskImage", req),
    createSession: (known) => route("createSession", known),
    async addKnownValues(sessionId, known) {
      const mock = sessionId.startsWith(MOCK_SESSION_PREFIX);
      const client = mock ? deps.mock : deps.api;
      if (!client.addKnownValues) throw new UnreachableError("addKnownValues is not available");
      return { data: await client.addKnownValues(sessionId, known), engine: mock ? "mock" : "api" };
    },
    // A session lives in the engine that created it.
    async unmask(req) {
      if (req.session_id.startsWith(MOCK_SESSION_PREFIX)) {
        return { data: await deps.mock.unmask(req), engine: "mock" };
      }
      return { data: await deps.api.unmask(req), engine: "api" };
    },
  };
}

export async function checkHealth(health: () => Promise<HealthResponse>): Promise<ApiStatus> {
  try {
    const res = await health();
    return res.status === "ok" ? { state: "online", version: res.version } : { state: "offline" };
  } catch {
    return { state: "offline" };
  }
}
