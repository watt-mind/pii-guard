// What a failed gateway call means, by error code (LAB-1335).
//
// Not every error is pii-guard failing closed. `upstream_error` means the masked request
// reached the upstream model and the upstream refused it: telling the user "nothing was sent"
// there sends them looking for a detection problem that doesn't exist. Detection and masking
// failures keep the fail-closed text, and policy blocks keep theirs.

export type ErrorKind = "unreachable" | "policy" | "not_configured" | "upstream" | "stream" | "fail_closed";

export interface ErrorCopy {
  kind: ErrorKind;
  /** One line, ends with a full stop. */
  title: string;
  /** What happened and what to do. */
  body: string;
}

const FAIL_CLOSED =
  "PII Guard fails closed: if detection or masking fails, the request is stopped rather than forwarded unmasked.";

/** The HTTP status in a message like "upstream returned HTTP 404", for errors that carry no status field. */
export function statusFromMessage(message: string | undefined): number | null {
  const m = /\bHTTP (\d{3})\b/.exec(message ?? "");
  return m ? Number(m[1]) : null;
}

/** A short, actionable guess at why the upstream answered with this status. */
export function upstreamHint(status: number | null): string {
  if (status === null) return "check the model name and the upstream's API key";
  if (status === 404) return "model not found on the upstream? Pick another model";
  if (status === 401 || status === 403) return "the upstream rejected the API key; check --api-key-env";
  if (status === 400 || status === 422) return "the upstream rejected the request; check the model and its parameters";
  if (status === 429) return "rate limited or out of quota; wait and retry";
  if (status >= 500) return "the upstream failed; retry, or pick another model";
  return "check the model name and the upstream's API key";
}

export function errorCopy(code: string | undefined, status: number | null = null): ErrorCopy {
  switch (code) {
    case "unreachable":
      return { kind: "unreachable", title: "The guard is not reachable. Nothing was sent.", body: FAIL_CLOSED };
    case "blocked_entity":
      return {
        kind: "policy",
        title: "Blocked by policy. Nothing was sent to the model.",
        body: "A detected type has the policy block (see Policy), so the request stopped.",
      };
    case "upstream_not_configured":
      return {
        kind: "not_configured",
        title: "No upstream model is configured. Nothing was sent.",
        body: "The guard masked nothing and called no model because it has no upstream to forward to.",
      };
    case "upstream_error": {
      const answered = status === null ? "an error" : String(status);
      return {
        kind: "upstream",
        title: `The upstream refused the masked request${status === null ? "" : ` (HTTP ${status})`}.`,
        body: `The masked request reached the upstream, which answered ${answered}: ${upstreamHint(status)}. Nothing unmasked left PII Guard.`,
      };
    }
    case "upstream_unavailable":
      return {
        kind: "upstream",
        title: "The upstream could not be reached, or its answer was unusable.",
        body: "PII Guard masked the request before forwarding it; the upstream didn't give a usable answer. Nothing unmasked left PII Guard. Retry, or check the upstream URL.",
      };
    case "stream_failed":
      return {
        kind: "stream",
        title: "The answer stream failed partway.",
        body: "The masked request reached the upstream, but its answer stream broke off. Nothing unmasked left PII Guard. Retry the message.",
      };
    // Image and detector outages in plain words (LAB-1619); the code stays on the notice as small text.
    case "ocr_unavailable":
      return {
        kind: "fail_closed",
        title: "Text recognition is unavailable right now, so the image was not sent.",
        body: "PII Guard can't read the text in images at the moment, and it never forwards an image it couldn't check. Retry in a minute.",
      };
    case "detector_loading":
      return {
        kind: "fail_closed",
        title: "The detectors are still starting, so nothing was sent.",
        body: "PII Guard loads its models after a restart, and never forwards what it couldn't check. Retry in a few seconds.",
      };
    case "request_timeout":
      return {
        kind: "fail_closed",
        title: "Checking took too long, so nothing was sent.",
        body: "PII Guard stops rather than forward something it couldn't finish checking. Retry, or try a smaller image or text.",
      };
    default:
      return { kind: "fail_closed", title: "Blocked. Nothing was sent to the model.", body: FAIL_CLOSED };
  }
}
