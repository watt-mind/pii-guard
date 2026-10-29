import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HostedApp } from "./HostedApp";
import type { Account, Requester } from "./api";
import type { HostedSession } from "./session";

const anonymous: Account = { mode: "hosted", authenticated: false, login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout?post_logout_redirect_uri=%2F", tier: "anonymous", providers: ["meta"], included_model: "muse-spark-1.3", limits: { requests_per_day: 3 }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [] };
const signedIn: Account = { ...anonymous, authenticated: true, tier: "standard", principal: { id: "owner-1", provider: "google" } };

const consoleStub = vi.fn((session: HostedSession) => <p>Console stub for {session.account.tier}</p>);
let fetched: string[] = [];

function open(hash: string) {
  window.history.replaceState(null, "", `/${hash}`);
}
beforeEach(() => {
  fetched = [];
  // The benchmark parts are static files next to the page; record what the screen asks for.
  vi.stubGlobal("fetch", vi.fn(async (url: string) => { fetched.push(String(url)); return new Response("{}", { status: 404 }); }));
});
afterEach(() => {
  open("");
  consoleStub.mockClear();
  vi.unstubAllGlobals();
});

describe("the Evaluation page while signed out (LAB-1533)", () => {
  it.each(["#evaluation", "#benchmarks"])("%s shows the benchmarks, not a sign-in panel", async (hash) => {
    open(hash);
    const call = vi.fn(async () => anonymous) as unknown as Requester;
    render(<HostedApp call={call} console={consoleStub} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Evaluation" }, { timeout: 10_000 })).toBeInTheDocument();
    expect(screen.queryByText(/Sign in to see/)).not.toBeInTheDocument();
    expect(consoleStub).not.toHaveBeenCalled();
    // Sign-in comes back to Evaluation.
    const nav = screen.getByRole("navigation", { name: "Main navigation" }).closest("header")!;
    expect(within(nav).getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23evaluation");
    // Only the account check goes to the API; the benchmarks are static bundled files.
    await vi.waitFor(() => expect(fetched.length).toBeGreaterThan(0));
    expect((call as unknown as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0])).toEqual(["/v1/account"]);
    for (const url of fetched) expect(url).toMatch(/^\/assets\/benchmarks-[\w-]+\.json$/);
  });

  it("still opens when the account can't be read", async () => {
    open("#evaluation");
    const call = vi.fn(async () => { throw new Error("offline"); }) as unknown as Requester;
    render(<HostedApp call={call} console={consoleStub} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Evaluation" }, { timeout: 10_000 })).toBeInTheDocument();
  });

  it("a signed-in owner gets Evaluation inside the console", async () => {
    open("#evaluation");
    render(<HostedApp call={vi.fn(async () => signedIn) as unknown as Requester} console={consoleStub} />);
    expect(await screen.findByText("Console stub for standard")).toBeInTheDocument();
  });

  it("the public Results section links to the page", async () => {
    open("#results");
    render(<HostedApp call={vi.fn(async () => anonymous) as unknown as Requester} console={consoleStub} />);
    expect(await screen.findByRole("link", { name: "Open the Evaluation page" })).toHaveAttribute("href", "#evaluation");
  });
});
