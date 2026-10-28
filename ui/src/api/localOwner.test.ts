import { afterEach, describe, expect, it, vi } from "vitest";
import { getOwnerRevision, setOwnerToken } from "./localOwner";
import { createProjectFetch } from "./project";
import { fetchSnippets } from "./connect";
import { fetchStatus } from "./status";
import { connectTraffic } from "./traffic";
import { setSelectedProject } from "../projects/selection";
import { localRequest } from "../projects/request";

afterEach(() => { setOwnerToken(null); vi.unstubAllGlobals(); });

describe("local owner authentication", () => {
  it.each(["/v1/projects", "/v1/projects/synthetic/endpoints", "/v1/status", "/v1/mask", "/v1/vault/sessions", "/v1/traffic"])("authenticates same-origin local route %s", async (path) => {
    setOwnerToken("synthetic-owner-token");
    const raw = vi.fn<typeof fetch>(async () => new Response("{}"));
    await createProjectFetch(raw)(path);
    expect(new Headers(raw.mock.calls[0]![1]?.headers).get("Authorization")).toBe("Bearer synthetic-owner-token");
  });
  it.each(["https://provider.example/v1/mask", "https://other.example/v1/projects", "/e/synthetic/v1/models", "/v1/account", "/v1/demo", "/healthz", "/assets/example.json"])("does not send the owner token to %s", async (path) => {
    setOwnerToken("synthetic-owner-token");
    const raw = vi.fn<typeof fetch>(async () => new Response("{}"));
    await createProjectFetch(raw)(path);
    expect(new Headers(raw.mock.calls[0]![1]?.headers).has("Authorization")).toBe(false);
  });
  it.each<Record<string, string>>([{ Authorization: "Bearer explicit-synthetic-key" }, { "X-PII-Guard-Token": "explicit-synthetic-key" }])("preserves explicit request credentials", async (headers) => {
    setOwnerToken("synthetic-owner-token");
    const raw = vi.fn<typeof fetch>(async () => new Response("{}"));
    await createProjectFetch(raw)("/v1/models", { headers });
    const actual = new Headers(raw.mock.calls[0]![1]?.headers);
    for (const [name, value] of Object.entries(headers)) expect(actual.get(name)).toBe(value);
    expect([...actual.values()]).not.toContain("Bearer synthetic-owner-token");
  });
  it("clears authentication from an existing client and changes the remount revision", async () => {
    setOwnerToken("synthetic-owner-token");
    const before = getOwnerRevision();
    const raw = vi.fn<typeof fetch>(async () => new Response("{}"));
    const client = createProjectFetch(raw);
    setOwnerToken(null);
    await client("/v1/projects");
    expect(getOwnerRevision()).toBeGreaterThan(before);
    expect(new Headers(raw.mock.calls[0]![1]?.headers).has("Authorization")).toBe(false);
    expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
  });
  it("authenticates both backlog and polling before any project is selected", async () => {
    setSelectedProject(null); setOwnerToken("synthetic-owner-token");
    const raw = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ events: [], level: "masked", size: 0 })));
    const eventSource = vi.fn();
    await new Promise<void>((resolve) => {
      const connection = connectTraffic({ fetch: raw, EventSource: eventSource, pollMs: 1, onEvents: () => {}, onStatus: () => {
        if (raw.mock.calls.length >= 2) { connection.close(); resolve(); }
      } });
    });
    expect(eventSource).not.toHaveBeenCalled(); expect(raw).toHaveBeenCalledTimes(2);
    for (const [, init] of raw.mock.calls) expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer synthetic-owner-token");
  });

  it("uses the same authentication for status and project management", async () => {
    setOwnerToken("synthetic-owner-token");
    const raw = vi.fn<typeof fetch>(async () => new Response("{}"));
    vi.stubGlobal("fetch", raw);
    await fetchStatus(); await localRequest("/v1/projects");
    await fetchSnippets({ session: "synthetic-session" }).catch(() => {});
    for (const [, init] of raw.mock.calls) expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer synthetic-owner-token");
  });
});
