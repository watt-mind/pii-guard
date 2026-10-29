import { createProjectFetch } from "./project";
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ErrorBody,
  GuardClient,
  HealthResponse,
  ImageMaskRequest,
  ImageMaskResponse,
  KnownValue,
  KnownValuesResponse,
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
  constructor(message = "PII Guard API is not reachable") {
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

/** SAM 3.1 makes one request per concept prompt, so an image takes several seconds. */
export const IMAGE_TIMEOUT_MS = 120_000;

export function createHttpClient(options: HttpClientOptions = {}): HttpGuardClient {
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  const doFetch = createProjectFetch(options.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args)));
  const timeoutMs = options.timeoutMs ?? 15_000;
  const imageTimeoutMs = options.timeoutMs ?? IMAGE_TIMEOUT_MS;

  async function request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    raw?: { body: Blob; contentType: string; timeoutMs: number },
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), raw?.timeoutMs ?? timeoutMs);
    let res: Response;
    try {
      res = await doFetch(`${baseUrl}${path}`, {
        method,
        headers: raw
          ? { "Content-Type": raw.contentType, Accept: "application/json" }
          : body === undefined
            ? { Accept: "application/json" }
            : { "Content-Type": "application/json", Accept: "application/json" },
        body: raw ? raw.body : body === undefined ? undefined : JSON.stringify(body),
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
      if (payload === undefined) throw new UnreachableError("PII Guard API returned a non-JSON response");
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
    throw new UnreachableError(`PII Guard API answered ${res.status} without a contract error body`);
  }

  return {
    health: () => request<HealthResponse>("GET", "/healthz"),
    analyze: (req: AnalyzeRequest) => request<AnalyzeResponse>("POST", "/v1/analyze", req),
    mask: (req: MaskRequest) => request<MaskResponse>("POST", "/v1/mask", req),
    unmask: (req: UnmaskRequest) => request<UnmaskResponse>("POST", "/v1/unmask", req),
    createSession: (known_values: KnownValue[]) => request<KnownValuesResponse>("POST", "/v1/sessions", { known_values }),
    addKnownValues: (session_id: string, known_values: KnownValue[]) =>
      request<KnownValuesResponse>("POST", `/v1/sessions/${encodeURIComponent(session_id)}/known-values`, { known_values }),
    maskImage: (req: ImageMaskRequest) =>
      request<ImageMaskResponse>(
        "POST",
        `/v1/mask/image${req.language ? `?language=${encodeURIComponent(req.language)}` : ""}`,
        undefined,
        { body: req.image, contentType: req.image.type || "application/octet-stream", timeoutMs: imageTimeoutMs },
      ),
  };
}
