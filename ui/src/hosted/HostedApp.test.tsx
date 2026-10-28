import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { HostedApp } from "./HostedApp";
import type { Account, DemoResult, Requester } from "./api";

const account: Account = { mode: "hosted", authenticated: false, login_url: "/.auth/login/google", logout_url: "/.auth/logout", tier: "anonymous", providers: ["meta"], limits: { requests_per_day: 3 }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [] };
const result: DemoResult = { sample_id: "hu-support", language: "hu", original: "Synthetic original", masked: "[[PERSON_live]]", answer: "Hello [[PERSON_live]]", restored: "Hello Synthetic Person", model: "test-model", session_id: "test-session", request_id: "test-request", entities: [{ start: 0, end: 9, type: "PERSON" }] };

function requester(handler: (path: string, body?: unknown, method?: string) => unknown) {
  return vi.fn(async (path: string, body?: unknown, method?: string) => handler(path, body, method)) as unknown as Requester;
}

describe("public hosted workflow", () => {
  it("labels the static mechanism, requests only a server sample, and shows all live stages", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    const user = userEvent.setup();
    render(<HostedApp call={call} />);
    expect(screen.getByText("Static illustration · synthetic")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByText("Live result · test-model");
    expect(call).toHaveBeenCalledWith("/v1/demo", { sample_id: "hu-support", language: "hu" });
    for (const text of [result.original, result.masked, result.answer, result.restored]) expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.queryByLabelText("Your text")).not.toBeInTheDocument();
    expect(screen.queryByText("Vault")).not.toBeInTheDocument();
  });
  it("clears previous success on quota failure and makes static recovery explicit", async () => {
    let runs = 0;
    const call = requester((path) => { if (path === "/v1/account") return account; if (++runs === 1) return result; throw new ApiError(429, "quota_exceeded", "sensitive server text must never render"); });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByText("Live result · test-model");
    await user.click(screen.getByRole("button", { name: "Run live example" }));
    await screen.findByRole("alert");
    expect(screen.queryByText(result.restored)).not.toBeInTheDocument();
    expect(screen.queryByText(/sensitive server text/)).not.toBeInTheDocument();
    expect(screen.getByText("Live request did not complete")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show static example" }));
    expect(screen.getByText("Static illustration · synthetic")).toBeInTheDocument();
  });
  it("rejects incomplete live results rather than showing a successful model run", async () => {
    const call = requester((path) => path === "/v1/account" ? account : { ...result, restored: "" });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByRole("alert"); expect(screen.queryByText("Live result · test-model")).not.toBeInTheDocument();
  });
  it("offers honest unavailable state with reconnect and keeps the static walkthrough", async () => {
    const call = requester(() => { throw new Error("offline"); });
    render(<HostedApp call={call} />);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Run live example" })).toBeDisabled();
    expect(screen.getByText("Static illustration · synthetic")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect to API" })).toBeInTheDocument();
  });
  it("creates and revokes guard keys, and does not reload their secret from metadata", async () => {
    const call = requester((path, body, method) => {
      if (path === "/v1/account") return { ...account, authenticated: true };
      if (method === "DELETE") return undefined;
      if (body) return { id: "key-one", name: "Test integration", prefix: "pg_test", created_at: "2026-10-28T00:00:00Z", key: "synthetic-once-only-secret" };
      return [];
    });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.type(await screen.findByLabelText("Key name"), "Test integration");
    await user.click(screen.getByRole("button", { name: "Create guard key" }));
    await screen.findByText("synthetic-once-only-secret");
    expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0);
    await user.click(screen.getByRole("button", { name: "Dismiss key" }));
    expect(screen.queryByText("synthetic-once-only-secret")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/account/api-keys/key-one", undefined, "DELETE"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument());
  });
});
