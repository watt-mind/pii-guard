import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HostedApp } from "./HostedApp";
import { consoleSectionOf, loginFor } from "./consoleLink";
import type { Account, Requester } from "./api";
import type { HostedSession } from "./session";

const anonymous: Account = { mode: "hosted", authenticated: false, login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout?post_logout_redirect_uri=%2F", tier: "anonymous", providers: ["meta"], included_model: "muse-spark-1.3", limits: { requests_per_day: 3 }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [] };
const signedIn: Account = { ...anonymous, authenticated: true, tier: "standard", principal: { id: "owner-1", provider: "google" } };

const requester = (next: () => Account) => vi.fn(async () => next()) as unknown as Requester;
const consoleStub = vi.fn((session: HostedSession) => <button type="button" onClick={() => void session.refresh()}>Console stub</button>);

function open(hash: string) {
  window.history.replaceState(null, "", `/${hash}`);
}
afterEach(() => {
  open("");
  consoleStub.mockClear();
});

describe("a console deep link while signed out (LAB-1519)", () => {
  it.each([
    ["#logs", "Sign in to see your logs", "%2F%23logs", "#demo"],
    ["#overview", "Sign in to see your overview", "%2F%23overview", "#how"],
    ["#vault", "Sign in to see your vault", "%2F%23vault", "#data"],
    ["#projects", "Sign in to see your projects", "%2F%23projects", "#how"],
    ["#connect", "Sign in to see your connection snippets", "%2F%23connect", "#how"],
    ["#playground/chat", "Sign in to see the playground", "%2F%23playground%2Fchat", "#demo"],
    ["#traffic", "Sign in to see your logs", "%2F%23traffic", "#demo"],
  ])("%s shows one signed-out panel that signs in back to the same screen", async (hash, heading, redirect, site) => {
    open(hash);
    render(<HostedApp call={requester(() => anonymous)} console={consoleStub} />);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in with Google" })).toHaveAttribute("href", `/.auth/login/google?post_login_redirect_uri=${redirect}`);
    expect(screen.getAllByRole("link").find((l) => l.getAttribute("href") === site)).toBeDefined();
    expect(consoleStub).not.toHaveBeenCalled();
    // Never signed in on this page: no "again", no 401, no zeroed metrics.
    expect(document.body.textContent).not.toMatch(/again|401|session ended/i);
    expect(screen.queryByRole("term")).toBeNull();
  });

  it("leaves the public page's anchors and unknown hashes on the public page", async () => {
    for (const hash of ["#demo", "#images", "#account", "#nope", ""]) {
      open(hash);
      const { unmount } = render(<HostedApp call={requester(() => anonymous)} console={consoleStub} />);
      expect(await screen.findByRole("heading", { level: 1, name: hash === "#demo" || hash === "#images" ? "Interactive demo" : /Send the work to the model/ })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: /^Sign in to see/ })).toBeNull();
      unmount();
    }
  });

  it("the secondary link opens the matching public section", async () => {
    open("#logs");
    const user = userEvent.setup();
    render(<HostedApp call={requester(() => anonymous)} console={consoleStub} />);
    await user.click(await screen.findByRole("link", { name: "Try the demo without an account" }));
    expect(window.location.hash).toBe("#demo");
    expect(await screen.findByRole("heading", { level: 2, name: "See exactly what the model sees." })).toBeInTheDocument();
  });

  it("a signed-in owner still gets the console", async () => {
    open("#logs");
    render(<HostedApp call={requester(() => signedIn)} console={consoleStub} />);
    expect(await screen.findByRole("button", { name: "Console stub" })).toBeInTheDocument();
  });

  it("a session that ends on this page says so, and signs in again to the same screen", async () => {
    open("#vault");
    let current = signedIn;
    const user = userEvent.setup();
    render(<HostedApp call={requester(() => current)} console={consoleStub} />);
    const stub = await screen.findByRole("button", { name: "Console stub" });
    current = anonymous;
    await act(async () => { await user.click(stub); });
    expect(await screen.findByRole("heading", { level: 1, name: "Your session ended" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in again with Google" })).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23vault");
  });
});

describe("consoleLink helpers", () => {
  it("maps hashes to console sections", () => {
    expect(consoleSectionOf("#logs")).toBe("logs");
    expect(consoleSectionOf("#playground/images")).toBe("playground");
    expect(consoleSectionOf("#images")).toBeNull();
    expect(consoleSectionOf("#site")).toBeNull();
    expect(consoleSectionOf("#main")).toBeNull();
  });
  it("keeps the server's login path and replaces only the return address", () => {
    expect(loginFor("/.auth/login/google?post_login_redirect_uri=%2F%23overview", "#policy")).toBe("/.auth/login/google?post_login_redirect_uri=%2F%23policy");
    expect(loginFor("/.auth/login/google", "#logs")).toBe("/.auth/login/google?post_login_redirect_uri=%2F%23logs");
  });
});
