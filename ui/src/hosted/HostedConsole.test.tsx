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
import { getSelectedEndpoint, setSelectedEndpoint, setSelectedProject } from "../projects/selection";
import type { BenchmarkIndex } from "../api/benchmarks";
import bundled from "virtual:pii-guard/benchmarks-index";
import { HostedApp } from "./HostedApp";
import type { Account, Requester } from "./api";
import { hostedChatFetch, setPlaygroundConnection } from "./session";
import { resetFirstRun } from "./firstRun";

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
// Two enabled endpoints and a disabled one (fictional).
const endpointOf = (id: string, name: string, enabled = true) => ({ id, name, enabled, project_id: "project-one", policy_id: "policy-one", policy_version_id: "pv-1", policy_version: 1, provider: "openai", base_url: "https://api.example.com/v1", model: "example-model", credential_configured: true, base_path: `/e/${id}/v1` });
const withEndpoints = (path: string) => (path.endsWith("/endpoints") ? { endpoints: [endpointOf("ep-off", "Retired", false), endpointOf("ep-one", "Support bot"), endpointOf("ep-two", "Billing bot")] } : undefined);
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
afterEach(() => { setPlaygroundConnection(""); setSelectedEndpoint(null); setSelectedProject(null); resetFirstRun(); vi.restoreAllMocks(); });

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
    expect(screen.queryByText("Send the work to the model.")).not.toBeInTheDocument();
  });

  it("shows the owner's usage and limits on the Overview, with one setup list, and hides the server setup it can't read", async () => {
    renderHosted(requester());
    const summary = await screen.findByRole("region", { name: "Your account" });
    expect(within(summary).getByText("of 25", { exact: false })).toBeInTheDocument();
    expect(within(summary).getByText("standard tier", { exact: false })).toBeInTheDocument();
    // Ticks from the owner's data (a connection and calls today, no policy yet); one primary action: the next step (LAB-1448).
    const setup = await within(summary).findByRole("region", { name: "Set up your gateway" });
    expect(within(setup).getByText("2 of 5 done")).toBeInTheDocument();
    expect(within(setup).getAllByRole("link")).toHaveLength(1);
    expect(within(setup).getByRole("link", { name: /Create a policy/ })).toHaveAttribute("href", "#projects");
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
    await user.type(await screen.findByLabelText(/^Provider API key/), "sk-test-fictional");
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
    expect(within(group).getAllByRole("radio").map((r) => r.closest("label")?.textContent)).toEqual(["Fast"]);
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
    await screen.findByRole("heading", { level: 1, name: "Projects" });
    await user.type(await screen.findByLabelText(/^New project name/), "Example billing desk");
    await user.click(screen.getByRole("button", { name: "Create project" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/projects", { name: "Example billing desk" }));
  });

  it("connects a provider on Connect, confirms it, selects it for chat and points to the endpoint snippets in Projects", async () => {
    history.replaceState(null, "", "#connect");
    const call = requester(true, (path, body) => (path === "/v1/account/connections" && body ? { ...account.connections[0] } : undefined));
    const user = userEvent.setup();
    renderHosted(call);
    await user.type(await screen.findByLabelText(/^Provider API key/), "sk-test-fictional");
    await user.click(screen.getByRole("button", { name: "Connect provider" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/account/connections", { provider: "openai", api_key: "sk-test-fictional" }));
    expect(screen.queryByText("sk-test-fictional")).not.toBeInTheDocument();
    expect(await screen.findByText("Connected OpenAI · https://api.example.com. Playground chat now sends through it.")).toBeInTheDocument();
    expect(screen.getByLabelText("Playground chat sends through")).toHaveValue("conn-one");
    const connect = screen.getByRole("region", { name: "Connect" });
    for (const link of within(connect).getAllByRole("link", { name: "Projects" })) expect(link).toHaveAttribute("href", "#projects");
    expect(screen.queryByTestId("gateway-url")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Playground chat sends through"), "conn-one");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
    await hostedChatFetch("/v1/models");
    expect(new Headers(fetchSpy.mock.calls[0]![1]!.headers).get("X-PII-Guard-Connection")).toBe("conn-one");
    fetchSpy.mockRestore();
  });

  it("asks before disconnecting a provider, then deletes it, announces it and focuses the list", async () => {
    history.replaceState(null, "", "#connect");
    let connections = account.connections;
    const call = requester(true, (path, _body, method) => {
      if (path === "/v1/account") return { ...account, connections };
      if (method === "DELETE") { connections = []; return null; }
    });
    const user = userEvent.setup();
    renderHosted(call);
    setPlaygroundConnection("conn-one");
    await user.click(await screen.findByRole("button", { name: "Disconnect OpenAI · https://api.example.com" }));
    const confirm = screen.getByRole("group", { name: "Disconnect OpenAI · https://api.example.com?" });
    expect(confirm).toHaveTextContent("Playground chat through it stops.");
    expect(call.mock.calls.some(([, , method]) => method === "DELETE")).toBe(false);
    await user.click(within(confirm).getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/account/connections/conn-one", undefined, "DELETE"));
    expect(await screen.findByText("Disconnected OpenAI · https://api.example.com.")).toBeInTheDocument();
    expect(await screen.findByText(/No provider connections yet/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Your connections" })).toHaveFocus());
    expect(screen.getByLabelText("Playground chat sends through")).toHaveValue("");
  });

  it("opens the Evaluation from the bundled benchmark index", async () => {
    history.replaceState(null, "", "#evaluation");
    renderHosted(requester());
    expect(await screen.findByRole("heading", { level: 1, name: "Evaluation" })).toBeInTheDocument();
  });

  it("shows the public page on View site, with a way back to the console", async () => {
    renderHosted(requester());
    await screen.findByRole("navigation", { name: "Console" });
    history.pushState(null, "", "#site");
    act(() => { window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByText("Send the work to the model.", { exact: false })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Open console" })[0]).toHaveAttribute("href", "#overview");
    expect(screen.queryByRole("navigation", { name: "Console" })).not.toBeInTheDocument();
  });

  it("keeps the public page for anonymous visitors", async () => {
    renderHosted(requester(false));
    expect((await screen.findAllByRole("link", { name: "Sign in with Google" }))[0]).toHaveAttribute("href", "/.auth/login/google?post_login_redirect_uri=%2F%23overview");
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
    renderHosted(requester(true, withEndpoints), withStatus);
    await waitFor(() => expect(fetchSpy.mock.calls.some(([url]) => String(url).includes("/v1/connect/snippets?endpoint=ep-one"))).toBe(true));
    expect(fetchSpy.mock.calls.some(([url]) => /snippets\?.*session=/.test(String(url)))).toBe(false);
    expect(screen.queryByTestId("gateway-url")).not.toBeInTheDocument();
  });

  // Hosted Connect's client setup (LAB-1448): the three states.
  it("Connect, a server without first run and no endpoint: previews the client setup, disabled, and sends the owner to Projects", async () => {
    setSelectedProject("project-one");
    setSelectedEndpoint(null);
    history.replaceState(null, "", "#connect");
    renderHosted(requester(), withStatus);
    const setup = await screen.findByRole("region", { name: "Connect your client" });
    const preview = await within(setup).findByTestId("client-setup-preview");
    for (const tab of within(preview).getAllByRole("tab")) expect(tab).toBeDisabled();
    expect(within(preview).getByRole("tab", { name: "Claude Code" })).toBeInTheDocument();
    expect(within(preview).getByRole("link", { name: /Create an endpoint/ })).toHaveAttribute("href", "#projects");
    // Client setup comes before the Playground's provider keys.
    const keys = screen.getByRole("region", { name: "Model provider keys for the Playground" });
    expect(setup.compareDocumentPosition(keys) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("Connect, endpoints but none picked: preselects the first enabled one and shows its client blocks", async () => {
    setSelectedProject("project-one");
    setSelectedEndpoint(null);
    history.replaceState(null, "", "#connect");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: { code: "unavailable" } }), { status: 503 }));
    renderHosted(requester(true, withEndpoints), withStatus);
    const setup = await screen.findByRole("region", { name: "Connect your client" });
    const select = await within(setup).findByRole("combobox", { name: "Endpoint" });
    expect(select).toHaveValue("ep-one");
    await waitFor(() => expect(fetchSpy.mock.calls.some(([url]) => String(url).includes("/v1/connect/snippets?endpoint=ep-one"))).toBe(true));
    expect(within(setup).getByText("Ready")).toBeInTheDocument();
    // Picking another endpoint here is the console's selection (the header's menu shows the same).
    await userEvent.setup().selectOptions(select, "ep-two");
    await waitFor(() => expect(getSelectedEndpoint()).toBe("ep-two"));
  });

  it("Connect, an endpoint picked in the header: Connect shows that one", async () => {
    setSelectedProject("project-one");
    setSelectedEndpoint("ep-two");
    history.replaceState(null, "", "#connect");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: { code: "unavailable" } }), { status: 503 }));
    renderHosted(requester(true, withEndpoints), withStatus);
    expect(await screen.findByRole("combobox", { name: "Endpoint" })).toHaveValue("ep-two");
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
