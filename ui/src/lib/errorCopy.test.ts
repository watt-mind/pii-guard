import { describe, expect, it } from "vitest";
import { errorCopy, statusFromMessage, upstreamHint } from "./errorCopy";

describe("error copy per code (LAB-1335)", () => {
  it("says an upstream refusal reached the upstream, with the status and a hint", () => {
    const c = errorCopy("upstream_error", 404);
    expect(c.kind).toBe("upstream");
    expect(c.title).toBe("The upstream refused the masked request (HTTP 404).");
    expect(c.body).toContain("The masked request reached the upstream, which answered 404");
    expect(c.body).toContain("model not found on the upstream? Pick another model");
    expect(c.body).toContain("Nothing unmasked left PII Guard.");
    expect(`${c.title} ${c.body}`).not.toMatch(/Nothing was sent|fails closed/);
  });

  it("says an unusable model answer was sent masked, never that detection failed (LAB-1626)", () => {
    const c = errorCopy("upstream_did_not_stream");
    expect(c.kind).toBe("upstream");
    expect(c.title).toBe("The model didn't answer as expected.");
    expect(c.body).toContain("The masked request was sent");
    expect(c.title + c.body).not.toMatch(/Nothing was sent|detection or masking fails/);
    expect(errorCopy("detection_failed").kind).toBe("fail_closed");
  });

  it("gives a hint per upstream status", () => {
    expect(upstreamHint(401)).toMatch(/API key/);
    expect(upstreamHint(429)).toMatch(/rate limited/);
    expect(upstreamHint(503)).toMatch(/upstream failed/);
    expect(upstreamHint(null)).toMatch(/model name/);
    expect(errorCopy("upstream_error").title).toBe("The upstream refused the masked request.");
  });

  it("keeps the fail-closed text for detection and masking failures", () => {
    for (const code of ["detection_failed", "detection_unavailable", "masking_failed", "internal_error", undefined]) {
      const c = errorCopy(code);
      expect(c.kind).toBe("fail_closed");
      expect(c.title).toBe("Blocked. Nothing was sent to the model.");
      expect(c.body).toMatch(/fails closed/);
    }
  });

  it("says in plain words when OCR or the detectors are down (LAB-1619)", () => {
    expect(errorCopy("ocr_unavailable").title).toBe("Text recognition is unavailable right now, so the image was not sent.");
    expect(errorCopy("detector_loading").body).toMatch(/Retry/);
    for (const code of ["ocr_unavailable", "detector_loading", "request_timeout"]) expect(errorCopy(code).kind).toBe("fail_closed");
  });

  it("keeps the policy text for policy blocks", () => {
    const c = errorCopy("blocked_entity");
    expect(c.kind).toBe("policy");
    expect(c.title).toBe("Blocked by policy. Nothing was sent to the model.");
  });

  it("separates an unreachable guard, a missing upstream and a broken stream", () => {
    expect(errorCopy("unreachable").title).toBe("The guard is not reachable. Nothing was sent.");
    expect(errorCopy("upstream_not_configured").kind).toBe("not_configured");
    expect(errorCopy("upstream_unavailable").body).toContain("Nothing unmasked left PII Guard.");
    expect(errorCopy("stream_failed").kind).toBe("stream");
  });

  it("reads the status out of the gateway's message", () => {
    expect(statusFromMessage("upstream returned HTTP 404")).toBe(404);
    expect(statusFromMessage("no status")).toBeNull();
    expect(statusFromMessage(undefined)).toBeNull();
  });
});
