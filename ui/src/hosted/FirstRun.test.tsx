import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SignedInConsole } from "../App";
import { createMockChat } from "../api/chat";
import type { HttpGuardClient } from "../api/http";
import { createMockClient } from "../api/mock";
import type { StatusResult } from "../api/status";
import { setSelectedEndpoint, setSelectedProject } from "../projects/selection";
import type { BenchmarkIndex } from "../api/benchmarks";
import bundled from "virtual:pii-guard/benchmarks-index";
import { HostedApp } from "./HostedApp";
import type { Account, Requester } from "./api";
import { endpointState, parseFirstRun, resetFirstRun, testRecovery, TestRequestError, withKey } from "./firstRun";

// First run (LAB-1455). Fictional owner, endpoint and keys only (ADR 0005).
const KEY = "pg_ep_exampleKey0123456789-_exampleKey0123456";
const ORIGIN = globalThis.location.origin;
const account = (sponsored: boolean): Account => ({
  mode: "hosted", authenticated: true, login_url: "/.auth/login/google", logout_url: "/.auth/logout",
  tier: "standard", providers: ["meta"], limits: { requests_per_day: 25, tokens_per_day: 50000, sponsored_enabled: sponsored }, usage: { requests_today: 0, resets_at: "2026-10-29T00:00:00Z" },
  state: { persistence: "ephemeral", restart_loses_sessions: true }, connections: [],
});
const endpoint = (provider: string, credential = false) => ({ id: "ep-default", name: "Default endpoint", enabled: true, project_id: "project-default", policy_id: "policy-one", policy_version_id: "pv-1", policy_version: 1, provider, base_url: "https://api.meta.ai/v1", model: "muse-spark-1.3", credential_configured: credential, base_path: "/e/ep-default/v1" });
const firstRun = (sponsored: boolean, extra: Record<string, unknown> = {}) => ({ project_id: "project-default", endpoint: endpoint("sponsored"), state: sponsored ? "ready" : "needs_key", created: true, active_keys: 1, key: { id: "key-1", name: "First-run key", key: KEY, created_at: "2026-10-28T20:00:00Z" }, sponsored_enabled: sponsored, gateway_url: `${ORIGIN}/e/ep-default/v1`, ...extra });

const url = `${ORIGIN}/e/ep-default/v1`;
const snippets = {
  gateway_url: url, session: null, session_url: null, endpoint: { id: "ep-default", name: "Default endpoint", model: "muse-spark-1.3" }, models: ["muse-spark-1.3"], model: "muse-spark-1.3",
  auth: { token_required: true, token_env: "PII_GUARD_ENDPOINT_KEY" }, upstream: { connected: true, mock: false, origin: null, preset: null, label: null }, presets: [], traffic_log: "masked", session_ref: null,
  tools: [
    { id: "muse-code", label: "Muse Code", api: "responses", kind: "unsupported", supported: false, code: "", note: "Not for endpoint URLs yet.", tested_version: null, docs: null },
    { id: "codex", label: "Codex", api: "responses", kind: "launch", supported: true, code: `codex -m muse-spark-1.3 \\\n  -c 'model_providers.pii-guard={base_url="${url}", env_key="PII_GUARD_ENDPOINT_KEY"}'`, note: "No config file.", tested_version: null, docs: null },
    { id: "python", label: "Python", api: "chat", kind: "request", supported: true, code: `import os\nfrom openai import OpenAI\n\nclient = OpenAI(base_url="${url}", api_key=os.environ["PII_GUARD_ENDPOINT_KEY"])`, note: "pip install openai.", tested_version: null, docs: null },
    { id: "curl", label: "cURL", api: "chat", kind: "request", supported: true, code: `curl -si ${url}/chat/completions \\\n  -H "Authorization: Bearer $PII_GUARD_ENDPOINT_KEY"`, note: "", tested_version: null, docs: null },
  ],
};
const roundTrip = { choices: [{ message: { role: "assistant", content: "Note to jane.placeholder@example.net: confirmed." } }], pii_guard: { masked_messages: [{ role: "user", content: "Write a two-line note to [[EMAIL_1a2b3c]] (phone [[PHONE_4d5e6f]]) confirming the appointment." }], masked_answer: [{ content: "Note to [[EMAIL_1a2b3c]]: confirmed." }] } };

function requester(sponsored: boolean, handlers: Record<string, (body: unknown, method?: string) => unknown> = {}) {
  let converted = false;
  return vi.fn(async (path: string, body?: unknown, method?: string) => {
    if (handlers[path]) return handlers[path]!(body, method);
    if (path === "/v1/account") return account(sponsored);
    if (path === "/v1/account/first-run") {
      const b = body as { meta_api_key?: string };
      if (b?.meta_api_key) {
        converted = true;
        return firstRun(sponsored, { endpoint: endpoint("meta", true), state: "ready", created: false, key: null });
      }
      return converted ? firstRun(sponsored, { endpoint: endpoint("meta", true), state: "ready", created: false, key: null }) : firstRun(sponsored);
    }
    if (path === "/v1/projects") return { projects: [{ id: "project-default", name: "Default project", default_policy_id: "policy-one" }], default_project_id: "project-default" };
    if (path.endsWith("/endpoints")) return { endpoints: [converted ? endpoint("meta", true) : endpoint("sponsored")] };
    if (path.endsWith("/policies")) return { policies: [] };
    if (path.endsWith("/keys")) return method === undefined && body ? { id: "key-2", name: "Console key", key: `${KEY}2`, created_at: "2026-10-28T21:00:00Z" } : { keys: [] };
    return {};
  }) as unknown as Requester & ReturnType<typeof vi.fn>;
}

function serve() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const u = String(input);
    if (u.includes("/v1/connect/snippets")) return new Response(JSON.stringify(snippets));
    if (u.includes("/e/ep-default/v1/chat/completions")) return new Response(JSON.stringify(roundTrip), { headers: { "X-PII-Guard-Masked": "2" } });
    return new Response(JSON.stringify({ error: { code: "unavailable" } }), { status: 503 });
  });
}

function renderConsole(call: Requester) {
  const mock = createMockClient();
  const api: HttpGuardClient = { health: () => Promise.resolve({ status: "ok", version: "0.1.0" }), analyze: mock.analyze, mask: mock.mask, unmask: mock.unmask };
  return render(
    <HostedApp
      call={call}
      console={(session) => (
        <SignedInConsole session={session} api={api} mock={mock} chat={{ api: createMockChat(mock), mock: createMockChat(mock) }} traffic={{ connect: () => ({ close() {} }), sendDemo: vi.fn() }} loadStatus={() => Promise.resolve<StatusResult>({ state: "offline" })} loadBenchmarks={() => Promise.resolve(bundled as BenchmarkIndex)} />
      )}
    />,
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  window.matchMedia ??= vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} });
  setSelectedEndpoint(null);
  setSelectedProject(null);
});
afterEach(() => {
  resetFirstRun();
  vi.restoreAllMocks();
});

const storedAnywhere = (secret: string) => [localStorage, sessionStorage].some((s) => Object.keys(s).some((k) => k.includes(secret) || (s.getItem(k) ?? "").includes(secret)));

describe("first run, sponsored on", () => {
  it("lands on Connect after sign-in with the key, copy-paste blocks and a test request", async () => {
    history.replaceState(null, "", "#overview");
    serve();
    const call = requester(true);
    renderConsole(call);
    const setup = await screen.findByRole("region", { name: "Connect your client" });
    expect(location.hash).toBe("#connect");
    expect(await within(setup).findByText("Ready")).toBeInTheDocument();
    expect(within(setup).getByText("Copy your guard key now. It is shown only once.")).toBeInTheDocument();
    expect(within(setup).getAllByText(`export PII_GUARD_ENDPOINT_KEY=${KEY}`).length).toBeGreaterThan(0);
    // The first sign-in's single call provisions and issues the key; nothing else mints one.
    expect(call.mock.calls.filter(([p]) => p === "/v1/account/first-run")).toHaveLength(1);
    expect(call.mock.calls.filter(([p]) => p === "/v1/account/first-run")[0]![1]).toEqual({ issue_key: true });

    // Tabs in order; Codex selected: its block exports the key, then runs against the endpoint.
    const user = userEvent.setup();
    expect(await within(setup).findByText(/codex -m muse-spark-1.3/)).toHaveTextContent(`export PII_GUARD_ENDPOINT_KEY=${KEY}`);
    const tabs = within(setup).getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Muse Code", "Codex", "OpenAI SDK", "cURL"]);
    await user.click(within(setup).getByRole("tab", { name: "OpenAI SDK" }));
    const python = await within(setup).findByText(/from openai import OpenAI/);
    expect(python).toHaveTextContent(`api_key="${KEY}"`);
    expect(python.textContent).not.toContain("import os");
    await user.click(within(setup).getByRole("tab", { name: "Muse Code" }));
    expect(within(setup).getByText("Not for endpoint URLs yet.")).toBeInTheDocument();

    await user.click(within(setup).getByRole("button", { name: "Send a test request" }));
    expect(await within(setup).findByText(/Round trip complete: 2 values masked/)).toBeInTheDocument();
    expect(within(setup).getByText(/to \[\[EMAIL_1a2b3c\]\] \(phone/)).toBeInTheDocument();
    expect(within(setup).getByText("Note to jane.placeholder@example.net: confirmed.")).toBeInTheDocument();
    expect(storedAnywhere(KEY)).toBe(false);
  });

  it("a returning owner whose key was shown before gets one-click new key, not the old one", async () => {
    history.replaceState(null, "", "#overview");
    serve();
    const call = requester(true, { "/v1/account/first-run": () => firstRun(true, { created: false, key: null }) });
    renderConsole(call);
    // No redirect: sign-in lands where it used to.
    await screen.findByRole("navigation", { name: "Console" });
    expect(location.hash).toBe("#overview");
    history.pushState(null, "", "#connect");
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    const setup = await screen.findByRole("region", { name: "Connect your client" });
    expect(within(setup).queryByText(KEY, { exact: false })).not.toBeInTheDocument();
    expect(await within(setup).findByText(/env_key="PII_GUARD_ENDPOINT_KEY"/, { selector: "pre" }, { timeout: 3000 })).toBeInTheDocument();
    await userEvent.setup().click(within(setup).getByRole("button", { name: "Create a new guard key" }));
    expect(await within(setup).findAllByText(`export PII_GUARD_ENDPOINT_KEY=${KEY}2`, { exact: false })).not.toHaveLength(0);
    expect(call).toHaveBeenCalledWith("/v1/projects/project-default/endpoints/ep-default/keys", { name: "Console key" });
  });
});

describe("first run, sponsored off", () => {
  it("asks for exactly one field, the Meta key, then shows the key and blocks", async () => {
    history.replaceState(null, "", "#overview");
    serve();
    const call = requester(false);
    const { container } = renderConsole(call);
    const setup = await screen.findByRole("region", { name: "Connect your client" });
    expect(location.hash).toBe("#connect");
    expect(await within(setup).findByText("Needs a key")).toBeInTheDocument();
    expect(within(setup).getByText(/Meta API key needed/)).toBeInTheDocument();
    const form = within(setup).getByRole("form", { name: "Add your Meta API key" });
    expect(form.querySelectorAll("input, textarea, select")).toHaveLength(1);
    expect(within(form).getByRole("link", { name: /Get one at dev.meta.ai/ })).toHaveAttribute("href", "https://dev.meta.ai");
    // Nothing to copy before the endpoint can answer.
    expect(within(setup).queryByRole("tab")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.type(within(form).getByLabelText("Meta API key"), "example-meta-key");
    await user.click(within(form).getByRole("button", { name: "Save key and continue" }));
    await waitFor(() => expect(call).toHaveBeenCalledWith("/v1/account/first-run", { meta_api_key: "example-meta-key", issue_key: true }));
    expect(await within(setup).findByText("Ready")).toBeInTheDocument();
    // The form is gone: focus moves on to step 1, not back to the page.
    await waitFor(() => expect(document.activeElement).toHaveTextContent("Copy your guard key"));
    // The guard key issued at sign-in is shown now, and the blocks embed it.
    expect(within(setup).getAllByText(`export PII_GUARD_ENDPOINT_KEY=${KEY}`, { exact: false }).length).toBeGreaterThan(0);
    expect(within(setup).getByText(/Your Meta API key/)).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("example-meta-key");
    expect(storedAnywhere("example-meta-key")).toBe(false);
    expect(storedAnywhere(KEY)).toBe(false);
  });

  it("a refused test request says why, and never claims a fallback", () => {
    expect(testRecovery(new TestRequestError(503, "sponsored_unavailable"))).toMatch(/Add your own Meta API key/);
    expect(testRecovery(new TestRequestError(401, "upstream_error"))).toMatch(/check it is valid for the Meta Model API/);
    expect(testRecovery(new TestRequestError(401, "unauthorized"))).toMatch(/Sign in again/);
  });
});

describe("first-run helpers", () => {
  it("embeds a key only into blocks that read it", () => {
    expect(withKey({ id: "curl", code: 'curl -H "Authorization: Bearer $PII_GUARD_ENDPOINT_KEY"' }, KEY)).toBe(`export PII_GUARD_ENDPOINT_KEY=${KEY}\ncurl -H "Authorization: Bearer $PII_GUARD_ENDPOINT_KEY"`);
    expect(withKey({ id: "curl", code: "curl x" }, KEY)).toBe("curl x");
    expect(withKey({ id: "curl", code: "$PII_GUARD_ENDPOINT_KEY" }, null)).toBe("$PII_GUARD_ENDPOINT_KEY");
    // Never a value that could break out of the shell line.
    expect(withKey({ id: "curl", code: "$PII_GUARD_ENDPOINT_KEY" }, "pg_ep_x; rm")).toBe("$PII_GUARD_ENDPOINT_KEY");
  });

  it("parses the server's answer and derives endpoint state", () => {
    expect(parseFirstRun(firstRun(true))?.key?.key).toBe(KEY);
    expect(parseFirstRun({ ...firstRun(true), state: "unknown" })).toBeNull();
    expect(parseFirstRun({ ...firstRun(true), key: { key: "not-a-key" } })?.key).toBeNull();
    expect(endpointState(endpoint("sponsored"), false)).toBe("needs_key");
    expect(endpointState(endpoint("sponsored"), true)).toBe("ready");
    expect(endpointState(endpoint("meta", true), false)).toBe("ready");
    expect(endpointState({ ...endpoint("meta", true), enabled: false }, true)).toBe("disabled");
  });
});
