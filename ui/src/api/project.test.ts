import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getSelectedEndpoint, getSelectedProject, setSelectedEndpoint, setSelectedProject, subscribeProject, useSelectedEndpoint, useSelectedScope } from "../projects/selection";
import { createProjectFetch } from "./project";
import { connectTraffic } from "./traffic";

afterEach(() => { setSelectedProject(null); });

describe("project request scope", () => {
  it("notifies only when the selected project changes", () => {
    const listener = vi.fn();
    const stop = subscribeProject(listener);
    setSelectedProject("project-one");
    setSelectedProject("project-one");
    expect(getSelectedProject()).toBe("project-one");
    expect(listener).toHaveBeenCalledTimes(1);
    stop();
    setSelectedProject("project-two");
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("captures the project for a client's lifetime and preserves existing headers", async () => {
    setSelectedProject("project-one");
    const raw = vi.fn<typeof fetch>(async () => new Response("{}"));
    const scoped = createProjectFetch(raw);
    setSelectedProject("project-two");
    await scoped("/v1/chat/completions", { headers: { "X-PII-Guard-Session": "synthetic-session" } });
    const headers = new Headers(raw.mock.calls[0]![1]?.headers);
    expect(headers.get("X-PII-Guard-Project")).toBe("project-one");
    expect(headers.get("X-PII-Guard-Session")).toBe("synthetic-session");
  });

  it("clears endpoint inspection when switching project, with one stable scope notification", () => {
    setSelectedProject("project-one");
    setSelectedEndpoint("endpoint-one");
    const listener = vi.fn();
    const stop = subscribeProject(listener);
    const { result } = renderHook(() => ({ scope: useSelectedScope(), endpoint: useSelectedEndpoint() }));
    expect(result.current).toEqual({ scope: '["project-one","endpoint-one"]', endpoint: "endpoint-one" });
    act(() => { setSelectedProject("project-two"); });
    expect(getSelectedEndpoint()).toBeNull();
    expect(result.current).toEqual({ scope: '["project-two",null]', endpoint: null });
    expect(listener).toHaveBeenCalledTimes(1);
    act(() => { setSelectedEndpoint("endpoint-two"); });
    expect(result.current).toEqual({ scope: '["project-two","endpoint-two"]', endpoint: "endpoint-two" });
    stop();
  });

  it.each(["/v1/vault/sessions", "/v1/vault/sessions/synthetic?reveal=true", "/v1/traffic?limit=4"])("captures endpoint inspection for %s", async (path) => {
    setSelectedProject("project-one");
    setSelectedEndpoint("endpoint-one");
    const raw = vi.fn<typeof fetch>(async () => new Response("{}"));
    const scoped = createProjectFetch(raw);
    setSelectedEndpoint("endpoint-two");
    await scoped(path);
    const headers = new Headers(raw.mock.calls[0]![1]?.headers);
    expect(headers.get("X-PII-Guard-Project")).toBe("project-one");
    expect(headers.get("X-PII-Guard-Endpoint")).toBe("endpoint-one");
  });

  it.each(["/v1/mask", "/v1/unmask", "/v1/sessions/synthetic", "/v1/connect/snippets", "/v1/models", "/v1/chat/completions", "/v1/responses"])("keeps endpoint inspection separate from project playground request %s", async (path) => {
    const raw = vi.fn<typeof fetch>(async () => new Response("{}"));
    await createProjectFetch(raw, "project-one", "endpoint-one")(path);
    const headers = new Headers(raw.mock.calls[0]![1]?.headers);
    expect(headers.get("X-PII-Guard-Project")).toBe("project-one");
    expect(headers.has("X-PII-Guard-Endpoint")).toBe(false);
  });

  it.each(["/v1/mask", "/v1/unmask", "/v1/analyze", "/v1/sessions/synthetic", "/v1/images/mask", "/v1/vault/sessions", "/v1/traffic?after=2", "/v1/connect/snippets", "/v1/models", "/v1/responses"])("scopes %s", async (path) => {
    const raw = vi.fn<typeof fetch>(async () => new Response("{}"));
    await createProjectFetch(raw, "project-one")(path);
    expect(new Headers(raw.mock.calls[0]![1]?.headers).get("X-PII-Guard-Project")).toBe("project-one");
  });

  it.each(["/healthz", "/v1/status", "/v1/account", "/v1/demo", "/v1/projects", "/benchmarks/index.json"])("leaves public/operator route %s unscoped", async (path) => {
    const raw = vi.fn<typeof fetch>(async () => new Response("{}"));
    await createProjectFetch(raw, "project-one")(path, { headers: { Accept: "application/json" } });
    expect(new Headers(raw.mock.calls[0]![1]?.headers).has("X-PII-Guard-Project")).toBe(false);
  });

  it("uses header-authenticated polling for project activity instead of an unscoped EventSource", async () => {
    setSelectedProject("project-one");
    setSelectedEndpoint("endpoint-one");
    const raw = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ events: [], level: "masked", size: 0 })));
    const eventSource = vi.fn();
    const live = new Promise<void>((resolve) => {
      const connection = connectTraffic({ fetch: raw, EventSource: eventSource, onEvents: () => {}, onStatus: (status) => {
        if (status.state === "live") { connection.close(); resolve(); }
      } });
    });
    await live;
    expect(eventSource).not.toHaveBeenCalled();
    expect(new Headers(raw.mock.calls[0]![1]?.headers).get("X-PII-Guard-Project")).toBe("project-one");
    expect(new Headers(raw.mock.calls[0]![1]?.headers).get("X-PII-Guard-Endpoint")).toBe("endpoint-one");
  });
});
