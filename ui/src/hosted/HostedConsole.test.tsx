import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SignedInConsole } from "../App";
import { createMockChat } from "../api/chat";
import type { HttpGuardClient } from "../api/http";
import { createMockClient } from "../api/mock";
import type { ServerStatus, StatusResult } from "../api/status";
import { capabilitiesOf, chatModesOf, HOSTED_CAPABILITIES, LOCAL_CAPABILITIES, offersDemoTraffic, offersSection, playgroundHint } from "../lib/capabilities";
import type { TrafficConnectOptions } from "../api/traffic";
import { fetchSnippets, parseSnippets } from "../api/connect";
import { parseStatus } from "../api/status";
import { setSelectedEndpoint, setSelectedProject } from "../projects/selection";
import type { BenchmarkIndex } from "../api/benchmarks";
import bundled from "virtual:pii-guard/benchmarks-index";
import { HostedApp } from "./HostedApp";
import type { Account, Requester } from "./api";
import { hostedChatFetch, setPlaygroundConnection } from "./session";

// Fictional owner data only.
const account: Account = {
  mode: "hosted", authenticated: true, login_url: "/.auth/login/google?post_login_redirect_uri=%2F%23overview", logout_url: "/.auth/logout?post_logout_redirect_uri=%2F",
  tier: "standard", providers: ["meta"], limits: { requests_per_day: 25, tokens_per_day: 50000, sponsored_enabled: false }, usage: { requests_today: 3, resets_at: "2026-10-29T00:00:00Z" },
  state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [{ id: "conn-one", provider: "openai", origin: "https://api.example.com", expires_at: "2026-10-28T20:00:00Z" }],
};
const project = { id: "project-one", name: "Example support desk", default_policy_id: "policy-one" };

function requester(signedIn = true, extra: (path: string, body?: unknown, method?: string) => unknown = () => undefined) {
  return vi.fn(async (path: string, body?: unknown, method?: string) => {
    const handled = extra(path, body, method);
    if (handled !== undefined) return handled;
    if (path === "/v1/account") return signedIn ? account : { ...account, authenticated: false, tier: "anonymous", connections: [] };
    if (path === "/v1/projects") return body ? { id: "project-two", name: (body as { name: string }).name, default_policy_id: "policy-one" } : { projects: [project], default_project_id: project.id };
    if (path.endsWith("/policies")) return { policies: [] };
    if (path.endsWith("/endpoints")) return { endpoints: [] };
    return {};
  }) as unknown as Requester & ReturnType<typeof vi.fn>;
}

function liveApi(): HttpGuardClient {
  const backend = createMockClient();
  return { health: () => Promise.resolve({ status: "ok", version: "0.1.0" }), analyze: backend.analyze, mask: backend.mask, unmask: backend.unmask };
}

// A hosted owner's /v1/status (LAB-1431): no upstream, images, auth, rest or metrics; fast mode only.
const hostedStatus = { version: "0.1.0", gateway: { default_mode: "fast", url: "https://guard.example.com/v1", modes: { fast: { detectors: ["rules", "ner"], available: true, reason: null } } }, ner: { available: true, state: "ready", error: null }, policies: { PERSON: "mask" }, default_language: "hu", traffic_log: "masked", vault_inspect: "masked", capabilities: { text: true, chat: true, images: false, logs: true, vault: true, server_policy: false, projects: true, connect: true, evaluation: true, accounts: true } };
const withStatus = () => Promise.resolve<StatusResult>({ state: "ok", status: parseStatus(hostedStatus)! });

// Today's hosted image refuses /v1/status, so the console runs on the mode's defaults.
const noStatus = () => Promise.resolve<StatusResult>({ state: "offline" });

// The owner's default project policy (fictional): two versions, the newest keeps organisations.
const policyV1 = { id: "pv-1", policy_id: "policy-one", policy_version_id: "pv-1", name: "Support default", version: 1, entity_policies: { PERSON: "mask", ORGANIZATION: "mask", EMAIL: "block" }, language: "hu", mode: "fast", detection_profile: "default" };
const policyV2 = { ...policyV1, id: "pv-2", policy_version_id: "pv-2", version: 2, entity_policies: { ...policyV1.entity_policies, ORGANIZATION: "keep" } };
const otherPolicy = { ...policyV1, id: "pv-x", policy_id: "policy-other", policy_version_id: "pv-x", name: "Strict", version: 7 };
const withPolicies = (path: string) => (path.endsWith("/policies") ? { policies: [otherPolicy, policyV1, policyV2] } : undefined);

/** A traffic log that reports itself live and empty, as an owner's fresh log does. */
const liveEmptyLog = (o: TrafficConnectOptions) => {
  queueMicrotask(() => act(() => o.onStatus({ state: "live", via: "sse", level: "masked", size: 200 })));
  return { close() {} };
};

function renderHosted(call: Requester, loadStatus: () => Promise<StatusResult> = noStatus, connect: (o: TrafficConnectOptions) => { close(): void } = () => ({ close() {} })) {
  const mock = createMockClient();
  return render(
    <HostedApp
      call={call}
      console={(session) => (
        <SignedInConsole
          session={session}
          api={liveApi()}
          mock={mock}
          chat={{ api: createMockChat(mock), mock: createMockChat(mock) }}
          traffic={{ connect, sendDemo: vi.fn() }}
          loadStatus={loadStatus}
          loadBenchmarks={() => Promise.resolve(bundled as BenchmarkIndex)}
        />
      )}
    />,
  );
}

const menu = () => screen.getByRole("navigation", { name: "Console" });

beforeEach(() => {
  localStorage.clear();
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
});
afterEach(() => { setPlaygroundConnection(""); setSelectedEndpoint(null); setSelectedProject(null); vi.restoreAllMocks(); });

describe("hosted console for a signed-in owner", () => {
  it("opens the console's menu, without the sections the hosted server doesn't offer", async () => {
    renderHosted(requester());
    await screen.findByRole("navigation", { name: "Console" });
    for (const name of ["Overview", "Playground", "Logs", "Vault", "Projects", "Connect", "Policy", "Evaluation"]) expect(within(menu()).getByRole("link", { name: new RegExp(`^${name}`) })).toBeInTheDocument();
    // The menu hint names only the tabs the server offers (no images here).
    expect(within(menu()).getByRole("link", { name: /^Playground/ })).toHaveTextContent("Try text and chat");
    expect(within(menu()).getByRole("link", { name: /^Playground/ })).not.toHaveTextContent(/images/i);
    expect(within(menu()).getByRole("link", { name: /^Overview/ })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByLabelText("Engine")).not.toBeInTheDocument();
    // View site and Sign out live in the header's profile menu (LAB-1436).
    await userEvent.setup().click(screen.getByRole("button", { name: "Account menu" }));
    expect(screen.getByRole("menuitem", { name: "Visit site" })).toHaveAttribute("href", "#site");
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toHaveAttribute("href", account.logout_url);
    expect(screen.queryByText("Reduce personal data")).not.toBeInTheDocument();
  });

  it("shows the owner's usage and limits on the Overview, with shortcuts, and hides the server setup it can't read", async () => {
    renderHosted(requester());
    const summary = await screen.findByRole("region", { name: "Your account" });
    expect(within(summary).getByText("of 25", { exact: false })).toBeInTheDocument();
    expect(within(summary).getByText("standard tier", { exact: false })).toBeInTheDocument();
    expect(within(summary).getByRole("link", { name: "Create a project" })).toHaveAttribute("href", "#projects");
    expect(within(summary).getByRole("link", { name: "Add a provider connection" })).toHaveAttribute("href", "#connect");
    expect(within(summary).getByRole("link", { name: "Try the playground" })).toHaveAttribute("href", "#playground/text");
    expect(screen.queryByText("Upstream")).not.toBeInTheDocument();
  });

  it("retries a failed account refresh without leaving the console or rendering server text", async () => {
    let fail = false;
    const call = requester(true, (path) => { if (path === "/v1/account" && fail) throw new Error("sensitive server text"); });
    const user = userEvent.setup();
    renderHosted(call);
    const summary = await screen.findByRole("region", { name: "Your account" });
    fail = true;
    history.replaceState(null, "", "#connect");
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    await user.type(await screen.findByLabelText("Provider API key"), "sk-test-fictional");
    await user.click(screen.getByRole("button", { name: "Connect provider" }));
    history.replaceState(null, "", "#overview");
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await within(summary).findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/sensitive server text/)).not.toBeInTheDocument();
    fail = false;
    await user.click(within(summary).getByRole("button", { name: "Reconnect to API" }));
    await waitFor(() => expect(within(summary).queryByRole("alert")).not.toBeInTheDocument());
  });

  it("runs the Playground's text masking, without the Images tab", async () => {
    history.replaceState(null, "", "#playground/images");
    const user = userEvent.setup();
    renderHosted(requester());
    const tabs = await screen.findByRole("tablist", { name: "Playground" });
    expect(within(tabs).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Text", "Chat"]);
    await waitFor(() => expect(location.hash).toBe("#playground/text"));
    await user.click(screen.getByRole("button", { name: /mask document/i }));
    const masked = await within(screen.getByRole("tabpanel", { name: "Text" })).findByTestId("masked-text");
    expect(masked).toHaveTextContent(/\[\[PERSON_[0-9a-f]{4,}\]\]/);
  });

  it("shows the owner's default project policy, read-only, on Policy, never the server's", async () => {
    history.replaceState(null, "", "#policy");
    const call = requester(true, withPolicies);
    renderHosted(call, withStatus);
    const region = await screen.findByRole("region", { name: "Policy" });
    expect(await within(region).findByText("Example support desk")).toBeInTheDocument();
    expect(location.hash).toBe("#policy");
    expect(call).toHaveBeenCalledWith("/v1/projects/project-one/policies");
    // The default policy's newest version, not another family's.
    expect(within(region).getByText("Support default")).toBeInTheDocument();
    expect(within(region).getByText("· v2")).toBeInTheDocument();
    expect(within(region).queryByText("Strict")).not.toBeInTheDocument();
    const text = within(region).getByRole("table");
    expect(within(within(text).getByRole("row", { name: /ORGANIZATION/ })).getByText("Kept in place")).toBeInTheDocument();
    expect(within(within(text).getByRole("row", { name: /EMAIL/ })).getByText("Blocks the request")).toBeInTheDocument();
    expect(within(region).getByRole("link", { name: "Edit policies in Projects" })).toHaveAttribute("href", "#projects");
    // No server configuration, no editing here.
    for (const gone of ["Upstream", "Authentication", "Traffic log", "PII_GUARD_POLICY_OVERRIDES"]) expect(within(region).queryByText(gone, { exact: false })).not.toBeInTheDocument();
    expect(within(region).queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("says why the owner's policy can't be shown, and retries", async () => {
    history.replaceState(null, "", "#policy");
    let fail = true;
    const call = requester(true, (path) => {
      if (path === "/v1/projects" && fail) throw new Error("sensitive server text");
      return withPolicies(path);
    });
    const user = userEvent.setup();
    renderHosted(call, withStatus);
    const region = await screen.findByRole("region", { name: "Policy" });
    expect(await within(region).findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/sensitive server text/)).not.toBeInTheDocument();
    fail = false;
    await user.click(within(region).getByRole("button", { name: "Retry" }));
    expect(await within(region).findByText("Support default")).toBeInTheDocument();
  });

  it("offers Chat's fast mode only, before and after the status answers", async () => {
    history.replaceState(null, "", "#playground/chat");
    renderHosted(requester(), withStatus);
    const group = await screen.findByRole("radiogroup", { name: "Detection mode" });
    expect(within(group).getAllByRole("radio").map((r) => r.textContent)).toEqual(["Fast"]);
  });

  it("doesn't offer Send demo traffic on the Overview or Logs", async () => {
    renderHosted(requester(), withStatus, liveEmptyLog);
    expect(await screen.findByText("Nothing has gone through the gateway yet.")).toBeInTheDocument();
    const overview = screen.getByRole("region", { name: "Overview" });
    expect(within(overview).getByText(/Connect a client to one of your endpoints/)).toBeInTheDocument();
    expect(within(overview).queryByRole("button", { name: "Send demo traffic" })).not.toBeInTheDocument();
    history.replaceState(null, "", "#logs");
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    const logs = screen.getByRole("region", { name: "Logs" });
    expect(await within(logs).findByText(/Connect a client to one of your endpoints/)).toBeInTheDocument();
    expect(within(logs).queryByRole("button", { name: "Send demo traffic" })).not.toBeInTheDocument();
  });

  it("manages the owner's projects through the session's requester", async () => {
    history.replaceState(null, "", "#projects");
    const call = requester();
    const user = userEvent.setup();
    renderHosted(call);
    await screen.findByRole("heading", { name: "Projects & endpoints" });
    await user.type(await screen.findByLabelText("New project name"), "Example billing desk");
    await user.click(screen.getByRole("button", { name: "Create project" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects", { name: "Example billing desk" }));
  });

  it("connects a provider on Connect and points to the endpoint snippets in Projects", async () => {
    history.replaceState(null, "", "#connect");
    const call = requester();
    const user = userEvent.setup();
    renderHosted(call);
    await user.type(await screen.findByLabelText("Provider API key"), "sk-test-fictional");
    await user.click(screen.getByRole("button", { name: "Connect provider" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/account/connections", { provider: "openai", api_key: "sk-test-fictional" }));
    expect(screen.queryByText("sk-test-fictional")).not.toBeInTheDocument();
    const connect = screen.getByRole("region", { name: "Connect" });
    for (const link of within(connect).getAllByRole("link", { name: "Projects" })) expect(link).toHaveAttribute("href", "#projects");
    expect(screen.queryByTestId("gateway-url")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Playground chat sends through"), "conn-one");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
    await hostedChatFetch("/v1/models");
    expect(new Headers(fetchSpy.mock.calls[0]![1]!.headers).get("X-PII-Guard-Connection")).toBe("conn-one");
    fetchSpy.mockRestore();
  });

  it("opens the Evaluation from the bundled benchmark index", async () => {
    history.replaceState(null, "", "#evaluation");
    renderHosted(requester());
    expect(await screen.findByRole("heading", { name: /How much gets through/ })).toBeInTheDocument();
  });

  it("shows the public page on View site, with a way back to the console", async () => {
    renderHosted(requester());
    await screen.findByRole("navigation", { name: "Console" });
    history.pushState(null, "", "#site");
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByText("Reduce personal data", { exact: false })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Open console" })[0]).toHaveAttribute("href", "#overview");
    expect(screen.queryByRole("navigation", { name: "Console" })).not.toBeInTheDocument();
  });

  it("keeps the public page for anonymous visitors", async () => {
    renderHosted(requester(false));
    expect(await screen.findByRole("link", { name: "Continue with Google" })).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23overview");
    expect(screen.queryByRole("navigation", { name: "Console" })).not.toBeInTheDocument();
  });

  it("reads the hosted status projection: detectors shown, no upstream panel", async () => {
    renderHosted(requester(), withStatus);
    expect(await screen.findByText("Mode and detectors")).toBeInTheDocument();
    expect(screen.queryByText("Upstream")).not.toBeInTheDocument();
    expect(within(menu()).getByRole("link", { name: /^Policy/ })).toHaveAttribute("href", "#policy");
  });

  it("asks for one endpoint's snippets on Connect when an endpoint is picked", async () => {
    setSelectedProject("project-one");
    setSelectedEndpoint("ep-one");
    history.replaceState(null, "", "#connect");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: { code: "unavailable" } }), { status: 503 }));
    renderHosted(requester(), withStatus);
    await waitFor(() => expect(fetchSpy.mock.calls.some(([url]) => String(url).includes("/v1/connect/snippets?endpoint=ep-one"))).toBe(true));
    expect(fetchSpy.mock.calls.some(([url]) => /snippets\?.*session=/.test(String(url)))).toBe(false);
    expect(screen.queryByTestId("gateway-url")).not.toBeInTheDocument();
  });

  it("follows the server's reported capabilities when it has them", async () => {
    const status = { capabilities: { images: true, server_policy: false } } as unknown as ServerStatus;
    expect(capabilitiesOf(status, true)).toEqual({ ...HOSTED_CAPABILITIES, images: true });
    expect(capabilitiesOf(null, true)).toEqual(HOSTED_CAPABILITIES);
    expect(capabilitiesOf(null, false)).toEqual(LOCAL_CAPABILITIES);
    expect(capabilitiesOf({ capabilities: { images: "yes" } } as unknown as ServerStatus, true).images).toBe(false);
    // A local server with its traffic log off keeps Logs and Vault in the menu, as before.
    expect(offersSection(LOCAL_CAPABILITIES, "logs")).toBe(true);
    expect(offersSection({ ...LOCAL_CAPABILITIES, vault: false }, "vault")).toBe(true);
    // Policy is the server's, or else the owner's project policies; neither: no Policy.
    expect(offersSection(HOSTED_CAPABILITIES, "policy")).toBe(true);
    expect(offersSection({ ...HOSTED_CAPABILITIES, projects: false }, "policy")).toBe(false);
    expect(offersSection(LOCAL_CAPABILITIES, "policy")).toBe(true);
  });

  it("derives the Playground hint, Chat's modes and demo traffic from the capabilities", () => {
    expect(playgroundHint(LOCAL_CAPABILITIES)).toBe("Try text, chat and images");
    expect(playgroundHint(HOSTED_CAPABILITIES)).toBe("Try text and chat");
    expect(playgroundHint({ ...HOSTED_CAPABILITIES, images: true })).toBe("Try text, chat and images");
    expect(playgroundHint({ ...HOSTED_CAPABILITIES, chat: false })).toBe("Try text");
    const hosted = parseStatus(hostedStatus)!;
    const local = { ...hosted, gateway: { ...hosted.gateway, modes: { ...hosted.gateway.modes, audit: { detectors: ["rules", "ner", "llm"], available: false, reason: "no key" } } } };
    expect(chatModesOf(hosted, HOSTED_CAPABILITIES)).toEqual(["fast"]);
    expect(chatModesOf(local, LOCAL_CAPABILITIES)).toEqual(["fast", "audit"]);
    expect(chatModesOf(null, HOSTED_CAPABILITIES)).toEqual(["fast"]);
    expect(chatModesOf(null, LOCAL_CAPABILITIES)).toEqual(["fast", "audit"]);
    expect(offersDemoTraffic(LOCAL_CAPABILITIES)).toBe(true);
    expect(offersDemoTraffic(HOSTED_CAPABILITIES)).toBe(false);
  });

  it("parses endpoint snippets, which pin their URL and carry no session", async () => {
    const body = { gateway_url: "https://guard.example.com/e/ep-one/v1", session: null, session_url: null, endpoint: { id: "ep-one", name: "Support assistant", model: "gpt-example" }, models: ["gpt-example"], model: "gpt-example", auth: { token_required: true, token_env: "PII_GUARD_ENDPOINT_KEY" }, upstream: { connected: true, mock: false, origin: null, preset: null, label: null }, presets: [], tools: [{ id: "python", label: "Python", api: "chat", kind: "request", supported: true, code: "client = OpenAI()", note: "", tested_version: null, docs: null }], traffic_log: "masked", session_ref: null };
    expect(parseSnippets(body)?.endpoint?.id).toBe("ep-one");
    expect(parseSnippets({ ...body, endpoint: undefined })).toBeNull();
    const doFetch = vi.fn(async () => new Response(JSON.stringify(body)));
    expect((await fetchSnippets({ endpoint: "ep-one" }, doFetch as unknown as typeof fetch)).state).toBe("ok");
    expect(String((doFetch.mock.calls[0] as unknown[])[0])).toMatch(/\/v1\/connect\/snippets\?endpoint=ep-one$/);
  });
});
