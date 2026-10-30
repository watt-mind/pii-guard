import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "../components/Sidebar";
import { HOSTED_CAPABILITIES, LOCAL_CAPABILITIES } from "../lib/capabilities";
import { hostedServers, hostedSpec, isApiHash, referenceConfig } from "./apiConfig";
import { HostedApp } from "./HostedApp";
import type { Account, Requester } from "./api";
import type { HostedSession } from "./session";

// The renderer is heavy and needs a real browser; the page around it is what these tests check.
vi.mock("./ScalarReference", () => ({
  default: ({ specUrl, dark, servers }: { specUrl: string; dark: boolean; servers?: unknown }) => (
    <div data-testid="scalar" data-spec={specUrl} data-dark={String(dark)} data-servers={servers ? JSON.stringify(servers) : undefined} />
  ),
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
      documentDownloadType: "none",
    });
    expect(config).not.toHaveProperty("proxyUrl");
    expect(config).not.toHaveProperty("proxy");
    expect((referenceConfig("/x.json", true) as Record<string, unknown>).forceDarkModeState).toBe("dark");
    expect(config).not.toHaveProperty("servers");
  });

  it("rewrites the gateway operations' servers for the console: this origin's endpoint first, self-hosted last (LAB-1626)", () => {
    const spec = {
      servers: [{ url: "http://127.0.0.1:8787", description: "Self-hosted" }],
      paths: {
        "/v1/chat/completions": {
          post: { servers: [{ url: "http://127.0.0.1:8787", description: "Self-hosted root gateway" }, { url: "https://guard.watt-mind.com/e/{endpoint_id}", description: "Hosted project endpoint", variables: { endpoint_id: { default: "your-endpoint-id" } } }] },
        },
        "/v1/projects": { get: { summary: "List" } },
      },
    };
    const picked = hostedSpec(spec, "https://guard.example.test", "ep_1");
    expect((picked.paths!["/v1/chat/completions"]!.post as { servers: { url: string }[] }).servers.map((s) => s.url)).toEqual(["https://guard.example.test/e/ep_1", "http://127.0.0.1:8787"]);
    expect(picked.paths!["/v1/projects"]!.get).toEqual({ summary: "List" });
    expect(picked.servers![0]!.url).toBe("https://guard.example.test");
    const none = hostedSpec(spec, "https://guard.example.test", null);
    expect((none.paths!["/v1/chat/completions"]!.post as { servers: { url: string }[] }).servers[0]!.url).toBe("https://guard.example.test/e/{endpoint_id}");
  });

  it("in the console, offers this service first, then the picked endpoint, then self-hosted (LAB-1626)", () => {
    const servers = hostedServers("https://guard.example.test", "ep 1");
    expect(servers.map((s) => s.url)).toEqual(["https://guard.example.test", "https://guard.example.test/e/ep%201", "http://127.0.0.1:8787"]);
    expect(hostedServers("https://guard.example.test", null)).toHaveLength(2);
    expect((referenceConfig("/x.json", false, servers) as Record<string, unknown>).servers).toBe(servers);
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

  it("opens inside the console for a signed-in owner (LAB-1626)", async () => {
    open("#api");
    render(<HostedApp call={requester(signedIn)} console={consoleStub} />);
    expect(await screen.findByText("Console stub for standard")).toBeInTheDocument();
  });

  it("embedded, it has no page chrome of its own and starts the examples from this service", async () => {
    vi.stubEnv("VITE_PII_GUARD_HOSTED", "true");
    vi.resetModules();
    const { ApiReference } = await import("./ApiReference");
    render(<ApiReference embedded />);
    expect(screen.getByRole("heading", { level: 1, name: "API reference" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main navigation" })).not.toBeInTheDocument();
    expect(screen.queryByRole("main")).not.toBeInTheDocument();
    const scalar = await screen.findByTestId("scalar");
    expect(JSON.parse(scalar.dataset.servers ?? "[]")[0].url).toBe(window.location.origin);
    vi.unstubAllEnvs();
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
    // The wide nav and the phone menu both list it.
    const links = within(screen.getByRole("navigation", { name: "Main navigation" })).getAllByRole("link", { name: "API" });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect(link).toHaveAttribute("href", "#api");
  });

  it("the sidebar doesn't repeat the header's API link (LAB-1626)", () => {
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
    expect(screen.queryByRole("link", { name: "API reference" })).not.toBeInTheDocument();
    unmount();
    render(<Sidebar {...props} caps={LOCAL_CAPABILITIES} />);
    expect(screen.queryByRole("link", { name: "API reference" })).not.toBeInTheDocument();
  });
});
