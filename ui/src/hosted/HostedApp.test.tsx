import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { HostedApp } from "./HostedApp";
import type { Account, DemoResult, Requester } from "./api";

const account: Account = { mode: "hosted", authenticated: false, login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout?post_logout_redirect_uri=%2F", tier: "anonymous", providers: ["meta"], limits: { requests_per_day: 3 }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [] };
const result: DemoResult = { sample_id: "hu-support", language: "hu", original: "Synthetic original", masked: "[[PERSON_live]]", answer: "Hello [[PERSON_live]]", restored: "Hello Synthetic Person", model: "test-model", session_id: "test-session", request_id: "test-request", entities: [{ start: 0, end: 9, type: "PERSON" }] };

function requester(handler: (path: string, body?: unknown, method?: string) => unknown) {
  return vi.fn(async (path: string, body?: unknown, method?: string) => handler(path, body, method)) as unknown as Requester;
}

describe("public hosted workflow", () => {
  it("sends sign-in back to the console instead of the provider's bare page", async () => {
    const call = requester((path) => path === "/v1/account" ? account : result);
    render(<HostedApp call={call} />);
    await screen.findByRole("link", { name: "Continue with Google" });
    expect(screen.getByRole("link", { name: "Continue with Google" })).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23overview");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23overview");
  });
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
  it.each([null, {}, { start: 0.5, end: 2, type: "PERSON" }, { start: 3, end: 2, type: "PERSON" }, { start: 0, end: 2, type: null }])("rejects malformed entity metadata without rendering a live success: %j", async (entity) => {
    const call = requester((path) => path === "/v1/account" ? account : { ...result, entities: [entity] });
    const user = userEvent.setup(); render(<HostedApp call={call} />);
    await user.click(await screen.findByRole("button", { name: "Run live example" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("Live result · test-model")).not.toBeInTheDocument();
    expect(screen.queryByText(result.restored)).not.toBeInTheDocument();
    expect(screen.getByText("Live request did not complete")).toBeInTheDocument();
  });
  it("offers honest unavailable state with reconnect and keeps the static walkthrough", async () => {
    const call = requester(() => { throw new Error("offline"); });
    render(<HostedApp call={call} />);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Run live example" })).toBeDisabled();
    expect(screen.getByText("Static illustration · synthetic")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect to API" })).toBeInTheDocument();
  });
  it("points a signed-in visitor of the public page to the console, without broad account keys", async () => {
    const call = requester((path) => path === "/v1/account" ? { ...account, authenticated: true } : []);
    render(<HostedApp call={call} />);
    await screen.findByText(/You’re signed in/);
    expect(screen.getByRole("link", { name: "Sign out" })).toHaveAttribute("href", account.logout_url);
    expect(screen.queryByRole("button", { name: "Create guard key" })).not.toBeInTheDocument();
    expect(screen.queryByText("Local guard access")).not.toBeInTheDocument();
    expect(call).not.toHaveBeenCalledWith("/v1/account/api-keys");
    expect(call).not.toHaveBeenCalledWith("/v1/projects");
  });
});
