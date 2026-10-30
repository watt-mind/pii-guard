import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "../components/Sidebar";
import { HOSTED_CAPABILITIES, LOCAL_CAPABILITIES } from "../lib/capabilities";
import { isApiHash, referenceConfig } from "./apiConfig";
import { HostedApp } from "./HostedApp";
import type { Account, Requester } from "./api";
import type { HostedSession } from "./session";

// The renderer is heavy and needs a real browser; the page around it is what these tests check.
vi.mock("./ScalarReference", () => ({
  default: ({ specUrl, dark }: { specUrl: string; dark: boolean }) => <div data-testid="scalar" data-spec={specUrl} data-dark={String(dark)} />,
}));

const anonymous: Account = { mode: "hosted", authenticated: false, login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout?post_logout_redirect_uri=%2F", tier: "anonymous", providers: ["meta"], included_model: "muse-spark-1.3", limits: { requests_per_day: 3 }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" }, state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [] };
const signedIn: Account = { ...anonymous, authenticated: true, tier: "standard", principal: { id: "owner-1", provider: "google" } };

const consoleStub = vi.fn((session: HostedSession) => <p>Console stub for {session.account.tier}</p>);

function open(hash: string) {
  window.history.replaceState(null, "", `/${hash}`);
}
const requester = (account: Account) => vi.fn(async () => account) as unknown as Requester;

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
});
afterEach(() => {
  open("");
  consoleStub.mockClear();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("#api routing", () => {
  it.each([
    ["#api", true],
    ["#api/tag/gateway/POST/v1/chat/completions", true],
    ["#apis", false],
    ["#overview", false],
    ["", false],
  ])("%s -> %s", (hash, expected) => {
    expect(isApiHash(hash)).toBe(expected);
  });
});

describe("the renderer's configuration (LAB-1586)", () => {
  it("is read-only and stays on this origin", () => {
    const config = referenceConfig("/assets/openapi-abc.json", false) as Record<string, unknown>;
    expect(config).toMatchObject({
      url: "/assets/openapi-abc.json",
      slug: "api",
      hideTestRequestButton: true,
      hideClientButton: true,
      showDeveloperTools: "never",
      isEditable: false,
      telemetry: false,
      withDefaultFonts: false,
      mcp: { disabled: true },
      agent: { disabled: true },
      forceDarkModeState: "light",
      hideDarkModeToggle: true,
    });
    expect(config).not.toHaveProperty("proxyUrl");
    expect(config).not.toHaveProperty("proxy");
    expect((referenceConfig("/x.json", true) as Record<string, unknown>).forceDarkModeState).toBe("dark");
  });
});

describe("the API reference page", () => {
  it.each(["#api", "#api/tag/gateway/POST/v1/chat/completions"])("%s opens it for a visitor, with no API call but the account", async (hash) => {
    open(hash);
    const call = requester(anonymous);
    render(<HostedApp call={call} console={consoleStub} />);
    expect(await screen.findByRole("heading", { level: 1, name: "API reference" })).toBeInTheDocument();
    expect(consoleStub).not.toHaveBeenCalled();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByText("API")).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Console" })).toHaveAttribute("href", anonymous.login_url);
    // The spec is the committed docs/openapi.json, served from the build, never the runtime /openapi.json.
    const download = screen.getByRole("link", { name: "openapi.json" });
    expect(download.getAttribute("href")).toMatch(/openapi\.json$/);
    expect(download.getAttribute("href")).not.toBe("/openapi.json");
    expect(screen.getByRole("link", { name: /Guide: quickstart/ })).toHaveAttribute("href", "https://github.com/watt-mind/pii-guard/blob/develop/docs/api.md");
    expect((call as unknown as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0])).toEqual(["/v1/account"]);
  });

  it("is the same for a signed-in owner, whose Console link opens the console", async () => {
    open("#api");
    render(<HostedApp call={requester(signedIn)} console={consoleStub} />);
    expect(await screen.findByRole("heading", { level: 1, name: "API reference" })).toBeInTheDocument();
    await vi.waitFor(() => expect(within(screen.getByRole("navigation", { name: "Main navigation" })).getByRole("link", { name: "Console" })).toHaveAttribute("href", "#overview"));
    expect(consoleStub).not.toHaveBeenCalled();
  });

  it("links to the hosted reference in the local build, which doesn't bundle the renderer", async () => {
    open("#api");
    render(<HostedApp call={requester(anonymous)} console={consoleStub} />);
    expect(await screen.findByRole("link", { name: /guard\.watt-mind\.com\/#api/ })).toHaveAttribute("href", "https://guard.watt-mind.com/#api");
    expect(screen.queryByTestId("scalar")).not.toBeInTheDocument();
  });

  it("renders the bundled spec with Scalar in the hosted build", async () => {
    vi.stubEnv("VITE_PII_GUARD_HOSTED", "true");
    vi.resetModules();
    const { ApiReference } = await import("./ApiReference");
    render(<ApiReference consoleHref="#overview" />);
    const scalar = await screen.findByTestId("scalar");
    expect(scalar.dataset.spec).toMatch(/openapi\.json$/);
    expect(scalar.dataset.dark).toBe("false");
  });
});

describe("links to the reference", () => {
  it("the landing has it in the nav and the footer", async () => {
    open("");
    render(<HostedApp call={requester(anonymous)} console={consoleStub} />);
    const footer = await screen.findByRole("navigation", { name: "Footer" });
    expect(within(footer).getByRole("link", { name: "API reference" })).toHaveAttribute("href", "#api");
    // The Resources menu lists it.
    const links = within(screen.getByRole("navigation", { name: "Main navigation" })).getAllByRole("link", { name: "API reference" });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect(link).toHaveAttribute("href", "#api");
  });

  it("the hosted console's navigation has it; the local console doesn't", () => {
    const props = {
      route: { section: "overview", tab: "text" },
      onSection: () => {},
      engineState: { preference: "auto", status: { state: "online", version: "0.1.0" } },
      engine: "api",
      onPreference: () => {},
      onRecheck: () => {},
      theme: "light",
      onTheme: () => {},
    } as unknown as Parameters<typeof Sidebar>[0];
    const { unmount } = render(<Sidebar {...props} caps={HOSTED_CAPABILITIES} />);
    expect(screen.getByRole("link", { name: "API reference" })).toHaveAttribute("href", "#api");
    unmount();
    render(<Sidebar {...props} caps={LOCAL_CAPABILITIES} />);
    expect(screen.queryByRole("link", { name: "API reference" })).not.toBeInTheDocument();
  });
});
