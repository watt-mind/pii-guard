import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ErrorBody,
  GuardClient,
  HealthResponse,
  MaskRequest,
  MaskResponse,
  UnmaskRequest,
  UnmaskResponse,
} from "./types";

/** A response from the API that follows the contract's error shape. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message || code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** The API could not be reached, or answered with something that isn't the contract (proxy error page). */
export class UnreachableError extends Error {
  constructor(message = "pii-guard API is not reachable") {
    super(message);
    this.name = "UnreachableError";
  }
}

function isErrorBody(value: unknown): value is ErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const err = (value as { error: unknown }).error;
  return (
    typeof err === "object" &&
    err !== null &&
    typeof (err as { code?: unknown }).code === "string" &&
    typeof (err as { message?: unknown }).message === "string"
  );
}

export interface HttpClientOptions {
  baseUrl?: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
}

export interface HttpGuardClient extends GuardClient {
  health(): Promise<HealthResponse>;
}

export function createHttpClient(options: HttpClientOptions = {}): HttpGuardClient {
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  const doFetch = options.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
  const timeoutMs = options.timeoutMs ?? 15_000;

  async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let res: Response;
    try {
      res = await doFetch(`${baseUrl}${path}`, {
        method,
        headers: body === undefined ? { Accept: "application/json" } : { "Content-Type": "application/json", Accept: "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch {
      throw new UnreachableError();
    } finally {
      clearTimeout(timer);
    }

    let payload: unknown = undefined;
    const text = await res.text();
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = undefined;
      }
    }

    if (res.ok) {
      if (payload === undefined) throw new UnreachableError("pii-guard API returned a non-JSON response");
      return payload as T;
    }
    if (isErrorBody(payload)) {
      throw new ApiError(res.status, payload.error.code, payload.error.message);
    }
    // FastAPI's default 404 ({"detail": "Not Found"}) before the routers land.
    if (res.status === 404 || res.status === 405) {
      throw new ApiError(res.status, "not_found", `${method} ${path} is not available`);
    }
    // A dev-proxy error page or a gateway in front of a stopped API.
    throw new UnreachableError(`pii-guard API answered ${res.status} without a contract error body`);
  }

  return {
    health: () => request<HealthResponse>("GET", "/healthz"),
    analyze: (req: AnalyzeRequest) => request<AnalyzeResponse>("POST", "/v1/analyze", req),
    mask: (req: MaskRequest) => request<MaskResponse>("POST", "/v1/mask", req),
    unmask: (req: UnmaskRequest) => request<UnmaskResponse>("POST", "/v1/unmask", req),
  };
}
