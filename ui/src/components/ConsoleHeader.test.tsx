// The console header (LAB-1436): the project switcher and, for a signed-in hosted owner, the
// profile menu. Fictional projects and owner only.

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, SignedInConsole } from "../App";
import { createMockChat } from "../api/chat";
import type { HttpGuardClient } from "../api/http";
import { createMockClient } from "../api/mock";
import type { StatusResult } from "../api/status";
import type { Account, Requester } from "../hosted/api";
import { getSelectedEndpoint, getSelectedProject, setSelectedEndpoint, setSelectedProject } from "../projects/selection";

const projects = {
  projects: [
    { id: "project-one", name: "Example support desk", default_policy_id: "policy-one" },
    { id: "project-two", name: "Internal research bot", default_policy_id: "policy-one" },
  ],
  default_project_id: "project-one",
};
const endpoints = { endpoints: [{ id: "ep-one", name: "Support assistant" }] };

// The switcher's requests go through the projects module's requester, whatever the build.
vi.mock("../projects/request", () => ({
  localRequest: vi.fn(async (path: string) => (path === "/v1/projects" ? projects : path.endsWith("/endpoints") ? endpoints : {})),
}));

const account: Account = {
  mode: "hosted", authenticated: true, principal: { id: "opaque-subject", provider: "google" },
  login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout?post_logout_redirect_uri=%2F",
  tier: "standard", providers: ["meta"], limits: { requests_per_day: 25 }, usage: { requests_today: 1, resets_at: "2026-10-29T00:00:00Z" },
  state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [],
};

function liveApi(): HttpGuardClient {
  const backend = createMockClient();
  return { health: () => Promise.resolve({ status: "ok", version: "0.1.0" }), analyze: backend.analyze, mask: backend.mask, unmask: backend.unmask };
}
const noStatus = () => Promise.resolve<StatusResult>({ state: "offline" });

function renderHosted(over: Partial<Account> = {}) {
  const mock = createMockClient();
  const call = vi.fn(async () => ({})) as unknown as Requester;
  return render(
    <SignedInConsole
      session={{ account: { ...account, ...over }, error: "", refresh: async () => {}, call }}
      api={liveApi()}
      mock={mock}
      chat={{ api: createMockChat(mock), mock: createMockChat(mock) }}
      traffic={{ connect: () => ({ close() {} }) }}
      loadStatus={noStatus}
    />,
  );
}

function renderLocal() {
  return render(<App api={liveApi()} mock={createMockClient()} traffic={{ connect: () => ({ close() {} }) }} loadStatus={noStatus} />);
}

const switcher = () => screen.findByRole("button", { name: /^Project:/ });

beforeEach(() => {
  localStorage.clear();
  history.replaceState(null, "", "#overview");
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
});
afterEach(() => { setSelectedEndpoint(null); setSelectedProject(null); });

describe("project switcher", () => {
  it("names the current project and lists the owner's projects with a check on it, outside the left menu", async () => {
    const user = userEvent.setup();
    renderHosted();
    const button = await switcher();
    expect(button).toHaveTextContent("Example support desk");
    expect(button).toHaveAttribute("aria-haspopup", "menu");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(within(screen.getByRole("navigation", { name: "Console" })).queryByText("Example support desk")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Project" })).not.toBeInTheDocument();

    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu", { name: "Projects" });
    const yours = within(menu).getByRole("group", { name: "Your projects" });
    expect(within(yours).getByRole("menuitemradio", { name: "Example support desk" })).toHaveAttribute("aria-checked", "true");
    expect(within(yours).getByRole("menuitemradio", { name: "Internal research bot" })).toHaveAttribute("aria-checked", "false");
    // Opening by click lands on the current project.
    expect(within(yours).getByRole("menuitemradio", { name: "Example support desk" })).toHaveFocus();
    expect(within(menu).getByRole("group", { name: "Inspect activity & vault" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Manage projects" })).toHaveAttribute("href", "#projects");
  });

  it("switches project, then returns focus to the switcher", async () => {
    const user = userEvent.setup();
    renderHosted();
    await user.click(await switcher());
    await user.click(screen.getByRole("menuitemradio", { name: "Internal research bot" }));
    expect(getSelectedProject()).toBe("project-two");
    const after = await screen.findByRole("button", { name: "Project: Internal research bot" });
    await waitFor(() => expect(after).toHaveFocus());
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("picks the endpoint whose activity and vault the console inspects", async () => {
    const user = userEvent.setup();
    renderHosted();
    await user.click(await switcher());
    await user.click(await screen.findByRole("menuitemradio", { name: "Support assistant" }));
    expect(getSelectedEndpoint()).toBe("ep-one");
    expect(await screen.findByRole("button", { name: "Project: Example support desk, inspecting Support assistant" })).toBeInTheDocument();
  });

  it("moves with the arrow keys, wraps, and closes on Escape with focus back on the button", async () => {
    const user = userEvent.setup();
    renderHosted();
    const button = await switcher();
    button.focus();
    await user.keyboard("{ArrowDown}");
    await screen.findByRole("menuitemradio", { name: "Support assistant" });
    const items = Array.from(screen.getByRole("menu").querySelectorAll<HTMLElement>("[role^=menuitem]"));
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(items.at(-1)).toHaveFocus();
    await user.keyboard("{Home}{ArrowDown}");
    expect(items[1]).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on a click outside", async () => {
    const user = userEvent.setup();
    renderHosted();
    await user.click(await switcher());
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.click(screen.getByRole("heading", { level: 1 }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

describe("profile menu", () => {
  it("shows a hosted owner who is signed in, their account, the site, docs, GitHub and sign-out", async () => {
    const user = userEvent.setup();
    renderHosted();
    const avatar = screen.getByRole("button", { name: "Account menu" });
    expect(avatar).toHaveAttribute("aria-haspopup", "menu");
    await user.click(avatar);
    const menu = screen.getByRole("menu", { name: "Account" });
    expect(within(menu).getByText("Signed in")).toBeInTheDocument();
    expect(within(menu).getByText(/with Google · standard tier/)).toBeInTheDocument();
    // The opaque subject is not a name: it is never shown.
    expect(within(menu).queryByText(/opaque-subject/)).not.toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Account" })).toHaveAttribute("href", "#overview");
    expect(within(menu).getByRole("menuitem", { name: "Visit site" })).toHaveAttribute("href", "#site");
    expect(within(menu).getByRole("menuitem", { name: /^Docs/ })).toHaveAttribute("target", "_blank");
    expect(within(menu).getByRole("menuitem", { name: /^GitHub/ })).toHaveAttribute("href", "https://github.com/watt-mind/pii-guard");
    expect(within(menu).getByRole("menuitem", { name: "Sign out" })).toHaveAttribute("href", account.logout_url);
    expect(within(menu).getByRole("menuitem", { name: "Account" })).toHaveFocus();
    // Sign-out left the left menu for the header.
    expect(screen.queryByRole("link", { name: "Sign out" })).not.toBeInTheDocument();
    await user.keyboard("{End}");
    expect(within(menu).getByRole("menuitem", { name: "Sign out" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(avatar).toHaveFocus();
  });

  it("shows the initial of a display name when the server sends one", async () => {
    renderHosted({ principal: { id: "opaque-subject", provider: "google", name: "robin example" } });
    const avatar = screen.getByRole("button", { name: "Account menu for robin example" });
    expect(avatar).toHaveTextContent("R");
  });

  it("opening one header menu closes the other", async () => {
    const user = userEvent.setup();
    renderHosted();
    await user.click(await switcher());
    await user.click(screen.getByRole("button", { name: "Account menu" }));
    expect(screen.getAllByRole("menu")).toHaveLength(1);
    expect(screen.getByRole("menu", { name: "Account" })).toBeInTheDocument();
  });
});

describe("local console", () => {
  it("has the project switcher but no avatar, identity or sign-out", async () => {
    renderLocal();
    expect(await switcher()).toHaveTextContent("Example support desk");
    expect(screen.queryByRole("button", { name: /^Account menu/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sign out" })).not.toBeInTheDocument();
    expect(screen.queryByText("Signed in")).not.toBeInTheDocument();
  });

  it("still opens Projects from the switcher", async () => {
    const user = userEvent.setup();
    renderLocal();
    await user.click(await switcher());
    const manage = screen.getByRole("menuitem", { name: "Manage projects" });
    await user.click(manage);
    await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(location.hash).toBe("#projects");
  });
});
