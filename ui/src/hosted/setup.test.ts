import { describe, expect, it, vi } from "vitest";
import type { Account, Requester } from "./api";
import { SETUP_STEPS, loadSetup } from "./setup";

// Fictional owner data only.
const account = (over: Partial<Account> = {}): Account => ({
  mode: "hosted", authenticated: true, login_url: "", logout_url: "", tier: "standard", providers: [], limits: {},
  usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [], ...over,
});

function requester(data: { policies?: unknown[]; endpoints?: unknown[]; keys?: unknown[] }): Requester {
  return vi.fn(async (path: string) => {
    if (path === "/v1/projects") return { projects: [{ id: "p1", name: "Example", default_policy_id: "" }], default_project_id: "p1" };
    if (path.endsWith("/policies")) return { policies: data.policies ?? [] };
    if (path.endsWith("/keys")) return { keys: data.keys ?? [] };
    if (path.endsWith("/endpoints")) return { endpoints: data.endpoints ?? [] };
    return {};
  }) as unknown as Requester;
}

describe("first-run setup (LAB-1448)", () => {
  it("lists the steps in the order each needs the one before", () => {
    expect(SETUP_STEPS.map((s) => s.id)).toEqual(["provider", "policy", "endpoint", "key", "call"]);
  });

  it("ticks nothing for a new owner", async () => {
    expect(await loadSetup(requester({}), account())).toEqual({ provider: false, policy: false, endpoint: false, key: false, call: false });
  });

  it("ticks from the owner's own data: an endpoint counts as a chosen model; revoked keys don't count", async () => {
    const endpoint = { id: "e1", enabled: true };
    const call = requester({ policies: [{}], endpoints: [endpoint], keys: [{ id: "k1", revoked_at: "2026-10-28T10:00:00Z" }] });
    expect(await loadSetup(call, account())).toEqual({ provider: true, policy: true, endpoint: true, key: false, call: false });
    const withKey = requester({ policies: [{}], endpoints: [endpoint], keys: [{ id: "k2", revoked_at: null }] });
    expect(await loadSetup(withKey, account({ usage: { requests_today: 2, resets_at: "" } }))).toEqual({ provider: true, policy: true, endpoint: true, key: true, call: true });
  });
});
